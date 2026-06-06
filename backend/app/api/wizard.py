"""Initial sync wizard — FR-1 … FR-6 (read + decision endpoints).

This router builds everything up to the user *deciding* the sync: connectivity →
direction → matches → weights → variants, all persisted. It performs NO write to
the upstream systems. Decision state is persisted in BridgeConfig (the bridge's
key→JSON store) and wizard_completed stays False.

FR-7 (POST /api/wizard/execute) — the single endpoint that performs the initial
write to both upstreams — is Phase 3b. It drops in alongside these endpoints and
flips wizard_completed; the decision state it consumes is what we persist here.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Body, Depends, Request
from sqlalchemy.orm import Session

from app import __version__
from app.api.config import get_config_value, set_config_value
from app.api.errors import api_error
from app.api.health import _check_filamentdb, _check_spoolman
from app.config import settings as _settings
from app.core.color import sm_multicolor_to_fdb, to_sm_color
from app.core.engine import _fdb_snapshot_dict, _log, _sm_snapshot_dict, _upsert_snapshot
from app.core.matcher import (
    extract_finish_line,
    match_filaments,
    normalize_name,
    normalize_vendor,
    sm_prop_conflicts,
    sm_variant_cluster_key,
)
from app.core.planner import (
    _DEFAULT_FDB_MATERIAL,
    _FilamentPlanItem,
    _SpoolPlanItem,
    _SyncPlan,
    _plan_spoolman_to_fdb,
)
from app.core.weight import DEFAULT_TARE_GRAMS, fdb_to_spoolman_net, spoolman_to_fdb_gross
from app.db import get_db
from app.models.mapping import FilamentMapping, SpoolMapping
from app.schemas.api import (
    AmbiguousRow,
    DefaultTareEntry,
    EmptyActiveEntry,
    FilamentRef,
    MatchDecision,
    MatchPairRow,
    NameCollisionEntry,
    PlannedWrite,
    PlannedWriteField,
    PreviewFlagCounts,
    ReconciledField,
    SMVariantGroupRow,
    SMVariantMemberRow,
    SMVariancesDecisionsRequest,
    SMVariantsRequest,
    SystemStatus,
    VariancesFilament,
    VariancesGroupRow,
    VariancesGroupReconcile,
    VariancesResponse,
    VariantGroupPreviewEntry,
    VariantGroupRow,
    VariantPropConflict,
    WeightPreviewRow,
    WizardConnectivityResponse,
    WizardDecisionAck,
    WizardDirectionRequest,
    WizardDirectionResponse,
    WizardExecuteRecord,
    WizardExecuteRequest,
    WizardExecuteResponse,
    WizardMatchesRequest,
    WizardMatchesResponse,
    WizardPreviewResponse,
    WizardVariantsRequest,
    WizardVariantsResponse,
    WizardWeightsResponse,
)
from app.schemas.filamentdb import FDBFilament, FDBSpool
from app.schemas.spoolman import SpoolmanFilament, encode_extra_value
from app.services.filamentdb import extract_created_spool_id

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Ref builders
# ---------------------------------------------------------------------------


def _sm_ref(sm: SpoolmanFilament) -> FilamentRef:
    return FilamentRef(
        spoolman_filament_id=sm.id,
        name=sm.name,
        vendor=sm.vendor.name if sm.vendor else None,
        color=sm.color_hex,  # display-only ref; bare Spoolman format is fine here
        material=sm.material,
    )


def _fdb_ref(fdb: FDBFilament) -> FilamentRef:
    return FilamentRef(
        filamentdb_filament_id=fdb.id,
        name=fdb.name,
        vendor=fdb.vendor,
        color=fdb.color,
        material=fdb.type,
    )


def _included_sm_ids(db: Session) -> set[int]:
    """Return the set of SM filament ids with a link or create match decision."""
    decisions = get_config_value(db, "wizard_match_decisions", []) or []
    return {d["spoolman_filament_id"] for d in decisions if d.get("action") in ("link", "create")}


def _resolve_variant_keywords(db: Session) -> list[str]:
    """Return the effective variant-line keyword list (BridgeConfig override > env default)."""
    raw: str = get_config_value(db, "variant_line_keywords", _settings.variant_line_keywords)
    seen: set[str] = set()
    result: list[str] = []
    for kw in raw.split(","):
        kw = kw.strip().lower()
        if kw and kw not in seen:
            seen.add(kw)
            result.append(kw)
    return result


def _sm_filament_tare(sm: SpoolmanFilament) -> tuple[float, str]:
    """Return (tare_grams, tare_source) for a Spoolman filament (filament-level spool_weight)."""
    if sm.spool_weight is not None:
        return (sm.spool_weight, "spoolman")
    return (DEFAULT_TARE_GRAMS, "default")


def _vendor_hint(sm_vendor: str | None, fdb_vendor: str | None) -> str | None:
    if not sm_vendor or not fdb_vendor:
        return None
    if sm_vendor != fdb_vendor and normalize_vendor(sm_vendor) == normalize_vendor(fdb_vendor):
        return f"Vendor names differ ('{sm_vendor}' vs '{fdb_vendor}') but normalize equal"
    return None


# ---------------------------------------------------------------------------
# FR-1 — connectivity
# ---------------------------------------------------------------------------


@router.get("/wizard/connectivity", response_model=WizardConnectivityResponse)
async def wizard_connectivity(request: Request) -> WizardConnectivityResponse:
    spoolman_health = await _check_spoolman(request)
    filamentdb_health = await _check_filamentdb(request)
    systems = {
        "spoolman": SystemStatus(**spoolman_health.model_dump()),
        "filamentdb": SystemStatus(**filamentdb_health.model_dump()),
    }
    ok = sum(1 for s in systems.values() if s.status == "ok")
    overall = "ok" if ok == 2 else "degraded" if ok == 1 else "error"
    blocked = ok < 2  # FR-1: block further steps if either is unreachable
    return WizardConnectivityResponse(
        status=overall,
        bridge_version=__version__,
        blocked=blocked,
        systems=systems,
    )


# ---------------------------------------------------------------------------
# FR-2 — direction + source-of-truth
# ---------------------------------------------------------------------------


@router.get("/wizard/direction", response_model=WizardDirectionResponse)
def wizard_get_direction(db: Session = Depends(get_db)) -> WizardDirectionResponse:
    direction = get_config_value(db, "import_direction", None)
    include_empty = bool(get_config_value(db, "wizard_include_empty_spools", False))
    return WizardDirectionResponse(import_direction=direction, include_empty_spools=include_empty)


def _sot_to_direction(sot: str) -> str:
    """Translate a legacy SourceOfTruth value to a SyncDirection2 value.

    Wizard UI still submits binary per-category 'spoolman'/'filamentdb' choices;
    we translate to the new one-way direction keys before persisting.
    """
    return "spoolman_to_filamentdb" if sot == "spoolman" else "filamentdb_to_spoolman"


@router.post("/wizard/direction", response_model=WizardDecisionAck)
def wizard_direction(payload: WizardDirectionRequest, db: Session = Depends(get_db)) -> WizardDecisionAck:
    persisted = 0
    set_config_value(db, "import_direction", payload.import_direction)
    persisted += 1

    # Translate per-category wizard selections into the new direction+policy keys.
    # The wizard's binary choice (spoolman/filamentdb) maps to a one-way direction.
    # A richer wizard UI with full direction+policy is a later nicety.
    if payload.weight_source_of_truth is not None:
        set_config_value(db, "weight_sync_direction", _sot_to_direction(payload.weight_source_of_truth))
        set_config_value(db, "weight_conflict_policy", "manual")
        persisted += 2

    if payload.material_properties_source_of_truth is not None:
        set_config_value(db, "material_properties_sync_direction", _sot_to_direction(payload.material_properties_source_of_truth))
        set_config_value(db, "material_properties_conflict_policy", "manual")
        persisted += 2

    if payload.new_spool_source_of_truth is not None:
        set_config_value(db, "new_spool_sync_direction", _sot_to_direction(payload.new_spool_source_of_truth))
        persisted += 1

    if payload.include_empty_spools is not None:
        set_config_value(db, "wizard_include_empty_spools", payload.include_empty_spools)
        persisted += 1
    db.commit()
    return WizardDecisionAck(persisted=persisted)


# ---------------------------------------------------------------------------
# FR-3 / FR-4 — auto-matching + review
# ---------------------------------------------------------------------------


@router.get("/wizard/matches", response_model=WizardMatchesResponse)
async def wizard_matches(request: Request, db: Session = Depends(get_db)) -> WizardMatchesResponse:
    sm_filaments = await request.app.state.spoolman.get_filaments()
    fdb_filaments = await request.app.state.filamentdb.get_filaments()
    mr = match_filaments(sm_filaments, fdb_filaments)

    matched = [
        MatchPairRow(
            spoolman=_sm_ref(p.spoolman_filament),
            filamentdb=_fdb_ref(p.fdb_filament),
            confidence=p.confidence,
            vendor_dedup_hint=_vendor_hint(
                p.spoolman_filament.vendor.name if p.spoolman_filament.vendor else None,
                p.fdb_filament.vendor,
            ),
        )
        for p in mr.matched
    ]
    ambiguous = [
        AmbiguousRow(spoolman=_sm_ref(sm), candidates=[_fdb_ref(f) for f in cands])
        for sm, cands in mr.ambiguous
    ]
    raw_decisions = get_config_value(db, "wizard_match_decisions", []) or []
    saved_decisions = [MatchDecision.model_validate(d) for d in raw_decisions]
    return WizardMatchesResponse(
        matched=matched,
        unmatched_spoolman=[_sm_ref(s) for s in mr.unmatched_spoolman],
        unmatched_filamentdb=[_fdb_ref(f) for f in mr.unmatched_fdb],
        ambiguous=ambiguous,
        saved_decisions=saved_decisions,
    )


@router.post("/wizard/matches", response_model=WizardDecisionAck)
def wizard_save_matches(payload: WizardMatchesRequest, db: Session = Depends(get_db)) -> WizardDecisionAck:
    set_config_value(db, "wizard_match_decisions", [d.model_dump() for d in payload.decisions])
    db.commit()
    return WizardDecisionAck(persisted=len(payload.decisions))


@router.post("/wizard/matches/{sm_filament_id}/skip", response_model=WizardDecisionAck)
def wizard_skip_match(sm_filament_id: int, db: Session = Depends(get_db)) -> WizardDecisionAck:
    """Set a single SM filament's match decision to 'skip' (Variances → Ignore action).

    Reads the existing decision list, updates or appends the skip entry, and saves.
    This is the single path that updates _included_sm_ids, so the change flows to
    variances / weights / preview / execute for free.
    """
    decisions: list[dict] = list(get_config_value(db, "wizard_match_decisions", []) or [])
    for d in decisions:
        if d.get("spoolman_filament_id") == sm_filament_id:
            d["action"] = "skip"
            set_config_value(db, "wizard_match_decisions", decisions)
            db.commit()
            return WizardDecisionAck(persisted=1)
    decisions.append({"spoolman_filament_id": sm_filament_id, "action": "skip"})
    set_config_value(db, "wizard_match_decisions", decisions)
    db.commit()
    return WizardDecisionAck(persisted=1)


# ---------------------------------------------------------------------------
# FR-5 — weight conversion preview
# ---------------------------------------------------------------------------


@router.get("/wizard/weights", response_model=WizardWeightsResponse)
async def wizard_weights(request: Request, db: Session = Depends(get_db)) -> WizardWeightsResponse:
    import_direction = get_config_value(db, "import_direction", "spoolman")
    rows: list[WeightPreviewRow] = []

    if import_direction == "spoolman":
        direction = "spoolman_to_filamentdb"
        included = _included_sm_ids(db)
        spools = await request.app.state.spoolman.get_spools()
        for s in spools:
            if s.archived:
                continue
            if s.filament and s.filament.id not in included:
                continue
            tare = s.spool_weight if s.spool_weight is not None else (
                s.filament.spool_weight if s.filament else None
            )
            net = s.remaining_weight or 0.0
            gross_res = spoolman_to_fdb_gross(net, tare)
            rows.append(
                WeightPreviewRow(
                    direction=direction,
                    spoolman_spool_id=s.id,
                    name=s.filament.name if s.filament else None,
                    net_weight=net,
                    gross_weight=gross_res.total_weight,
                    tare=gross_res.total_weight - net,
                    tare_source="default" if gross_res.used_default_tare else "spoolman",
                )
            )
    else:
        direction = "filamentdb_to_spoolman"
        filaments = await request.app.state.filamentdb.get_filaments()
        for f in filaments:
            for sp in f.spools:
                gross = sp.totalWeight or 0.0
                net_res = fdb_to_spoolman_net(gross, f.spoolWeight)
                rows.append(
                    WeightPreviewRow(
                        direction=direction,
                        filamentdb_filament_id=f.id,
                        filamentdb_spool_id=sp.id,
                        name=f.name,
                        net_weight=net_res.remaining_weight,
                        gross_weight=gross,
                        tare=gross - net_res.remaining_weight,
                        tare_source="default" if net_res.used_default_tare else "filamentdb",
                    )
                )

    return WizardWeightsResponse(direction=direction, rows=rows)


# ---------------------------------------------------------------------------
# FR-6 — variant grouping
# ---------------------------------------------------------------------------


def _strip_color(name: str, color: str | None) -> str:
    base = name
    if color:
        base = base.replace(color, "").replace(color.lower(), "").replace(color.title(), "")
    return normalize_name(base) or normalize_name(name)


@router.get("/wizard/variants", response_model=WizardVariantsResponse)
async def wizard_variants(request: Request, db: Session = Depends(get_db)) -> WizardVariantsResponse:
    import_direction = get_config_value(db, "import_direction", "spoolman")

    if import_direction == "spoolman":
        sm_filaments: list[SpoolmanFilament] = await request.app.state.spoolman.get_filaments()
        sm_spools = await request.app.state.spoolman.get_spools()
        included = _included_sm_ids(db)
        variant_keywords = _resolve_variant_keywords(db)

        spools_per_filament: dict[int, int] = {}
        for s in sm_spools:
            if not s.archived:
                spools_per_filament[s.filament.id] = spools_per_filament.get(s.filament.id, 0) + 1

        clusters: dict[tuple[str, str, str], list[SpoolmanFilament]] = {}
        for sm in sm_filaments:
            if sm.id not in included:
                continue
            key = sm_variant_cluster_key(sm, keywords=variant_keywords)
            clusters.setdefault(key, []).append(sm)

        sm_groups: list[SMVariantGroupRow] = []
        for (_vendor_norm, _material_norm, _finish_norm), members in clusters.items():
            if len(members) < 2:
                continue
            master = max(members, key=lambda f: (spools_per_filament.get(f.id, 0), -len(f.name)))
            member_rows: list[SMVariantMemberRow] = []
            for m in members:
                is_master = m.id == master.id
                conflicts: list[VariantPropConflict] = [] if is_master else [
                    VariantPropConflict(**c) for c in sm_prop_conflicts(master, m)
                ]
                member_rows.append(SMVariantMemberRow(ref=_sm_ref(m), is_master=is_master, conflicts=conflicts))
            display_base = normalize_name(
                f"{(master.vendor.name + ' ') if master.vendor else ''}{master.material or ''}".strip()
            )
            sm_groups.append(SMVariantGroupRow(
                base_name=display_base,
                vendor=master.vendor.name if master.vendor else None,
                material=master.material,
                suggested_master=_sm_ref(master),
                members=member_rows,
            ))
        return WizardVariantsResponse(direction="spoolman", sm_groups=sm_groups)

    # filamentdb direction — existing FDB clustering
    filaments: list[FDBFilament] = await request.app.state.filamentdb.get_filaments()
    fdb_clusters: dict[tuple[str, str, str], list[FDBFilament]] = {}
    for f in filaments:
        key = (normalize_vendor(f.vendor), _strip_color(f.name, f.color), f.type or "")
        fdb_clusters.setdefault(key, []).append(f)

    fdb_groups: list[VariantGroupRow] = []
    for (vendor, base_name, _type), members in fdb_clusters.items():
        if len(members) < 2:
            continue
        ordered = sorted(members, key=lambda f: len(f.name))
        parent, *variants = ordered
        fdb_groups.append(VariantGroupRow(
            base_name=base_name,
            vendor=parent.vendor,
            suggested_parent=_fdb_ref(parent),
            variants=[_fdb_ref(v) for v in variants],
        ))
    return WizardVariantsResponse(direction="filamentdb", fdb_groups=fdb_groups)


@router.post("/wizard/variants", response_model=WizardDecisionAck)
def wizard_save_variants(payload: WizardVariantsRequest, db: Session = Depends(get_db)) -> WizardDecisionAck:
    set_config_value(db, "wizard_variant_decisions", [g.model_dump() for g in payload.groups])
    db.commit()
    return WizardDecisionAck(persisted=len(payload.groups))


@router.post("/wizard/variants/sm", response_model=WizardDecisionAck)
def wizard_save_sm_variants(payload: SMVariancesDecisionsRequest, db: Session = Depends(get_db)) -> WizardDecisionAck:
    """Persist SM variant grouping decisions AND per-group reconcile decisions.

    Extends the original SMVariantsRequest to also accept an optional `reconcile`
    list (list[VariancesGroupReconcile]). Both are persisted via BridgeConfig:
      - wizard_sm_variant_decisions (unchanged key)
      - wizard_variances_reconcile (new key for Phase 2 reconcile decisions)
    """
    match_decisions = get_config_value(db, "wizard_match_decisions", []) or []
    skip_sm_ids = {d["spoolman_filament_id"] for d in match_decisions if d.get("action") == "skip"}
    for group in payload.groups:
        if group.master_spoolman_filament_id in skip_sm_ids:
            raise api_error(
                422, "master_is_skipped",
                f"SM filament {group.master_spoolman_filament_id} is marked skip and cannot be a master",
            )
    set_config_value(db, "wizard_sm_variant_decisions", [g.model_dump() for g in payload.groups])
    if payload.reconcile:
        set_config_value(db, "wizard_variances_reconcile", [r.model_dump() for r in payload.reconcile])
    db.commit()
    persisted = len(payload.groups)
    return WizardDecisionAck(persisted=persisted)


# ---------------------------------------------------------------------------
# Variances — merged Weights + Variants step (SM direction)
# ---------------------------------------------------------------------------


@router.get("/wizard/variances", response_model=VariancesResponse)
async def wizard_variances(request: Request, db: Session = Depends(get_db)) -> VariancesResponse:
    """Combined variant-grouping + tare preview for the SM import direction.

    Returns suggested variant groups, the pool of ungrouped (singleton) included
    filaments, and per-filament comparable props + tare so the client can edit
    one tare per group / per standalone filament and recompute conflicts live.

    For the filamentdb import direction, returns an empty response; the frontend
    uses the legacy GET /wizard/variants and GET /wizard/weights endpoints.
    """
    import_direction = get_config_value(db, "import_direction", "spoolman")
    if import_direction != "spoolman":
        return VariancesResponse(direction="filamentdb")

    included = _included_sm_ids(db)
    include_empty = bool(get_config_value(db, "wizard_include_empty_spools", False))
    variant_keywords = _resolve_variant_keywords(db)
    sm_filaments: list[SpoolmanFilament] = await request.app.state.spoolman.get_filaments()
    sm_spools = await request.app.state.spoolman.get_spools()
    fdb_filaments: list[FDBFilament] = await request.app.state.filamentdb.get_filaments()

    included_filaments = [f for f in sm_filaments if f.id in included]

    # Phase 1: Build SM filament id → matched FDB filament type (for material_type field)
    match_decisions: list[dict] = get_config_value(db, "wizard_match_decisions", []) or []
    fdb_by_id: dict[str, FDBFilament] = {f.id: f for f in fdb_filaments}
    sm_to_fdb_type: dict[int, str | None] = {}
    for d in match_decisions:
        sm_id = d.get("spoolman_filament_id")
        fdb_id = d.get("filamentdb_id")
        if sm_id and fdb_id and d.get("action") == "link":
            fdb_fil = fdb_by_id.get(fdb_id)
            sm_to_fdb_type[sm_id] = fdb_fil.type if fdb_fil else None

    # Spool ids per filament (active only; D4 — skip zero-weight spools when toggle is off)
    spool_ids_per_filament: dict[int, list[int]] = {}
    for s in sm_spools:
        if not s.archived and s.filament:
            if not include_empty and (s.remaining_weight or 0.0) == 0.0:
                continue
            spool_ids_per_filament.setdefault(s.filament.id, []).append(s.id)

    # Count ALL active spools per filament (for master heuristic — unaffected by toggle)
    spools_per_filament: dict[int, int] = {}
    for s in sm_spools:
        if not s.archived and s.filament:
            spools_per_filament[s.filament.id] = spools_per_filament.get(s.filament.id, 0) + 1

    # D3 — build FDB parent tree: (vendor_norm, material_norm, finish_norm) → FilamentRef
    # Finish is extracted from the FDB filament name so Silk parents match Silk SM groups.
    _parent_ids: set[str] = {f.parentId for f in fdb_filaments if f.parentId}
    fdb_parent_by_key: dict[tuple[str, str, str], FilamentRef] = {}
    for f in fdb_filaments:
        if f.id in _parent_ids or f.hasVariants:
            key = (
                normalize_vendor(f.vendor),
                normalize_name(f.type or ""),
                extract_finish_line(f.name or "", f.type, keywords=variant_keywords),
            )
            if key not in fdb_parent_by_key:
                fdb_parent_by_key[key] = FilamentRef(
                    filamentdb_filament_id=f.id,
                    name=f.name,
                    vendor=f.vendor,
                    material=f.type,
                )

    # D1/B — cluster included filaments by (vendor, material, finish)
    clusters: dict[tuple[str, str, str], list[SpoolmanFilament]] = {}
    for sm in included_filaments:
        key = sm_variant_cluster_key(sm, keywords=variant_keywords)
        clusters.setdefault(key, []).append(sm)

    grouped_ids: set[int] = set()
    groups: list[VariancesGroupRow] = []

    for (vendor_norm, material_norm, finish_norm), members in clusters.items():
        if len(members) < 2:
            continue
        master = max(members, key=lambda f: (spools_per_filament.get(f.id, 0), -len(f.name)))
        grouped_ids.update(m.id for m in members)
        member_rows: list[VariancesFilament] = []
        for m in members:
            is_master = m.id == master.id
            conflicts: list[VariantPropConflict] = [] if is_master else [
                VariantPropConflict(**c) for c in sm_prop_conflicts(master, m)
            ]
            tare, tare_source = _sm_filament_tare(m)
            member_rows.append(VariancesFilament(
                ref=_sm_ref(m),
                spool_ids=spool_ids_per_filament.get(m.id, []),
                tare=tare,
                tare_source=tare_source,
                is_master=is_master,
                conflicts=conflicts,
                suggest_exclude=bool(conflicts) and not is_master,  # D2
                material=m.material,
                density=m.density,
                spool_weight=m.spool_weight,
                settings_extruder_temp=m.settings_extruder_temp,
                settings_bed_temp=m.settings_bed_temp,
                # Phase 1: enriched display fields
                material_type=sm_to_fdb_type.get(m.id),
                diameter=m.diameter,
                color_hex=m.color_hex,
            ))
        display_base = normalize_name(
            f"{(master.vendor.name + ' ') if master.vendor else ''}{master.material or ''}".strip()
        )
        existing_fdb_parent = fdb_parent_by_key.get((vendor_norm, material_norm, finish_norm))  # D3
        groups.append(VariancesGroupRow(
            base_name=display_base,
            vendor=master.vendor.name if master.vendor else None,
            material=master.material,
            finish=finish_norm or None,  # Part B: shown in group header
            suggested_master=_sm_ref(master),
            members=member_rows,
            existing_fdb_parent=existing_fdb_parent,
        ))

    # Ungrouped (singleton) included filaments
    ungrouped: list[VariancesFilament] = []
    for sm in included_filaments:
        if sm.id not in grouped_ids:
            tare, tare_source = _sm_filament_tare(sm)
            ungrouped.append(VariancesFilament(
                ref=_sm_ref(sm),
                spool_ids=spool_ids_per_filament.get(sm.id, []),
                tare=tare,
                tare_source=tare_source,
                is_master=False,
                conflicts=[],
                suggest_exclude=False,
                material=sm.material,
                density=sm.density,
                spool_weight=sm.spool_weight,
                settings_extruder_temp=sm.settings_extruder_temp,
                settings_bed_temp=sm.settings_bed_temp,
                # Phase 1: enriched display fields
                material_type=sm_to_fdb_type.get(sm.id),
                diameter=sm.diameter,
                color_hex=sm.color_hex,
            ))

    return VariancesResponse(direction="spoolman", groups=groups, ungrouped=ungrouped)


# ---------------------------------------------------------------------------
# FR-7 — execute initial sync (the bulk write to BOTH upstream systems)
# ---------------------------------------------------------------------------
#
# This is the project's riskiest write path: on first run it mutates both live
# systems in bulk. It consumes the decisions persisted by FR-2…FR-6 (direction,
# match decisions, variant groupings) plus the per-spool tare overrides supplied
# with the request, and:
#   1. creates the missing filaments/spools in the *target* system,
#   2. writes the cross-reference IDs on both sides (never raw — JSON-encoded),
#   3. seeds weights *directly* on create (no usage entries — usage is for
#      ongoing decrements, FR-9),
#   4. records FilamentMapping / SpoolMapping rows + a SyncLog per action,
#   5. seeds Snapshot rows so the first auto-sync cycle has a correct baseline,
#   6. flips wizard_completed once the run finishes without a fatal error.
#
# Safety: per-record isolation (one API error → a `failed` entry + continue,
# never abort the run, NFR-4) and idempotency (an already-linked record is a
# no-op, so a re-run after a partial failure never duplicates). Nothing upstream
# is ever deleted to "clean up". The wizard is the user explicitly choosing the
# initial state, so there are no conflicts to queue here (conflicts are FR-13).



def _build_master_of_sm(sm_variant_decisions: list[dict]) -> dict[int, int]:
    """Build {variant_sm_id: master_sm_id} from persisted wizard_sm_variant_decisions."""
    result: dict[int, int] = {}
    for group in sm_variant_decisions:
        master_id = group.get("master_spoolman_filament_id")
        if master_id is None:
            continue
        for variant_id in group.get("variant_spoolman_filament_ids", []):
            result[variant_id] = master_id
    return result


def _build_attach_parent_for_sm(sm_variant_decisions: list[dict]) -> dict[int, str]:
    """Build {sm_id: existing_fdb_parent_id} for all members of D3 attach groups.

    When existing_fdb_parent_id is set on a decision, ALL members (the master SM
    filament and all variant SM filaments) should be created with that FDB parentId.
    No new parent is promoted; the existing FDB parent is never modified.
    """
    result: dict[int, str] = {}
    for group in sm_variant_decisions:
        existing_parent = group.get("existing_fdb_parent_id")
        if not existing_parent:
            continue
        master_id = group.get("master_spoolman_filament_id")
        if master_id:
            result[master_id] = existing_parent
        for variant_id in group.get("variant_spoolman_filament_ids", []):
            result[variant_id] = existing_parent
    return result


class _ExecResult:
    """Accumulates the FR-7 report (counts + per-record detail)."""

    def __init__(self, cycle_id: str, direction: str) -> None:
        self.cycle_id = cycle_id
        self.direction = direction
        self.created = 0
        self.updated = 0
        self.skipped = 0
        self.failed = 0
        self.records: list[WizardExecuteRecord] = []

    def add(
        self,
        db: Session,
        entity_type: str,
        action: str,
        *,
        detail: str | None = None,
        error: str | None = None,
        sm_filament_id: int | None = None,
        sm_spool_id: int | None = None,
        fdb_filament_id: str | None = None,
        fdb_spool_id: str | None = None,
    ) -> None:
        self.records.append(
            WizardExecuteRecord(
                entity_type=entity_type,
                action=action,
                spoolman_filament_id=sm_filament_id,
                spoolman_spool_id=sm_spool_id,
                filamentdb_filament_id=fdb_filament_id,
                filamentdb_spool_id=fdb_spool_id,
                detail=detail,
                error=error,
            )
        )
        setattr(self, action, getattr(self, action) + 1)
        log_action = {
            "created": "create", "updated": "update", "skipped": "skip", "failed": "error",
        }[action]
        _log(
            db, self.cycle_id, self.direction, log_action, entity_type,
            spoolman_id=sm_spool_id if sm_spool_id is not None else sm_filament_id,
            fdb_filament_id=fdb_filament_id,
            fdb_spool_id=fdb_spool_id,
            error_message=error,
        )



def _sm_filament_payload_from_fdb(fdb: FDBFilament, vendor_id: int | None) -> dict:
    """Map an FDB filament onto the Spoolman create-filament body (core fields only)."""
    payload: dict = {
        "name": fdb.name,
        "material": fdb.type,
        "color_hex": to_sm_color(fdb.color),
        "density": fdb.density,
        "spool_weight": fdb.spoolWeight,
    }
    if vendor_id is not None:
        payload["vendor_id"] = vendor_id
    return {k: v for k, v in payload.items() if v is not None}


def _cross_ref_extra(fdb_filament_id: str, fdb_spool_id: str, parent_id: str | None) -> dict:
    """The three Spoolman cross-ref extra fields, JSON-encoded (never raw)."""
    return {
        _settings.spoolman_field_filamentdb_id: encode_extra_value(fdb_filament_id),
        _settings.spoolman_field_filamentdb_spool_id: encode_extra_value(fdb_spool_id),
        _settings.spoolman_field_filamentdb_parent_id: encode_extra_value(parent_id or ""),
    }


def _seed_snapshots(db: Session, sm_spool, fdb_spool_obj: FDBSpool) -> None:
    """Seed both snapshot rows for a freshly-linked pair (best-effort baseline).

    Failure here never fails the import — the engine baselines a first-seen pair
    on its own; this just spares cycle 1 a spurious "first seen" skip.
    """
    try:
        _upsert_snapshot(db, "spoolman", "spool", str(sm_spool.id), _sm_snapshot_dict(sm_spool, []))
        _upsert_snapshot(db, "filamentdb", "spool", fdb_spool_obj.id, _fdb_snapshot_dict(fdb_spool_obj))
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("wizard execute %s: snapshot seed failed for SM spool %s: %s",
                       getattr(sm_spool, "id", "?"), sm_spool, exc)


# ---------------------------------------------------------------------------
# Phase 3 — Reconcile helpers
# ---------------------------------------------------------------------------

# Mapping from canonical reconcile key → (FDB payload key, SM payload key)
_RECONCILE_FIELD_MAP: dict[str, tuple[str, str]] = {
    "type":         ("type", "material"),
    "density":      ("density", "density"),
    "diameter":     ("diameter", "diameter"),
    "nozzle_temp":  ("temperatures.nozzle", "settings_extruder_temp"),
    "bed_temp":     ("temperatures.bed", "settings_bed_temp"),
    "spool_weight": ("spoolWeight", "spool_weight"),
}


def _build_reconcile_by_master(reconcile_decisions: list[dict]) -> dict[int, list[dict]]:
    """Build {master_sm_id: [reconciled_field_dicts]} from persisted wizard_variances_reconcile."""
    result: dict[int, list[dict]] = {}
    for entry in reconcile_decisions:
        master_id = entry.get("master_spoolman_filament_id")
        fields = entry.get("fields", [])
        if master_id is not None:
            result[master_id] = fields
    return result


def _overlay_reconcile_on_fdb_payload(payload: dict, reconcile_fields: list[dict]) -> dict:
    """Overlay reconciled canonical values onto an FDB create/update payload.

    Only sets shared-property fields (type/density/diameter/temperatures/spoolWeight).
    Color is never touched. FDB `settings{}` bag is never touched.
    Returns a new dict (does not mutate in place).
    """
    result = dict(payload)
    for rf in reconcile_fields:
        canonical_key = rf.get("field")
        value = rf.get("value")
        if canonical_key not in _RECONCILE_FIELD_MAP:
            continue
        fdb_key, _ = _RECONCILE_FIELD_MAP[canonical_key]
        if "." in fdb_key:
            # Nested: e.g. "temperatures.nozzle"
            top, sub = fdb_key.split(".", 1)
            nested = dict(result.get(top) or {})
            nested[sub] = value
            result[top] = nested
        else:
            result[fdb_key] = value
    return result


def _compute_sm_reconcile_patch(
    sm_filament: SpoolmanFilament,
    reconcile_fields: list[dict],
) -> dict:
    """Build the Spoolman PATCH payload for a filament: only fields that differ from canonical.

    Maps canonical keys to Spoolman field names. Never touches color fields.
    """
    patch: dict = {}
    for rf in reconcile_fields:
        canonical_key = rf.get("field")
        canonical_value = rf.get("value")
        if canonical_key not in _RECONCILE_FIELD_MAP:
            continue
        _, sm_key = _RECONCILE_FIELD_MAP[canonical_key]
        current = getattr(sm_filament, sm_key, None)
        if current != canonical_value:
            patch[sm_key] = canonical_value
    return patch


async def _execute_spoolman_to_fdb(
    db: Session,
    res: _ExecResult,
    spoolman,
    filamentdb,
    sm_filaments: list[SpoolmanFilament],
    sm_spools: list,
    fdb_filaments: list[FDBFilament],
    decisions_by_sm: dict[int, dict],
    master_of_sm: dict[int, int],
    attach_parent_for_sm: dict[int, str],
    tare_by_sm_spool: dict[int, float],
    reconcile_by_master: dict[int, list[dict]] | None = None,
    precision: int = 2,
    include_empty_spools: bool = True,
) -> None:
    """Import direction "spoolman": seed Filament DB from Spoolman.

    Delegates the decision/planning phase to _plan_spoolman_to_fdb (no writes),
    then executes each plan item in two passes so variant parentId is injected
    after the master filament is created/resolved.
    """
    plan = _plan_spoolman_to_fdb(
        db, sm_filaments, sm_spools, fdb_filaments,
        decisions_by_sm, master_of_sm, tare_by_sm_spool, precision,
        include_empty_spools=include_empty_spools,
    )

    fdb_field_name = _settings.filamentdb_spoolman_id_field
    fdb_by_id: dict[str, FDBFilament] = {f.id: f for f in fdb_filaments}
    fil_map_by_sm: dict[int, FilamentMapping] = {
        m.spoolman_filament_id: m for m in db.query(FilamentMapping).all()
    }
    just_created_fdb_ids: set[str] = set()
    # master_sm_id → fdb_id; populated during Pass 1 so Pass 2 can resolve parentId
    master_map: dict[int, str] = {}

    # Phase 3: build reconcile lookup (master sm_id → reconcile field dicts)
    _reconcile_by_master: dict[int, list[dict]] = reconcile_by_master or {}

    # Finish-tag write-back: sm_filament_id → sorted list of OpenPrintTag finish IDs.
    # Populated from the _sm_finish_ids sentinel in fdb_payload (stripped before FDB POST).
    _finish_ids_by_sm: dict[int, list[int]] = {}

    # ---- Pass 1: masters + ungrouped (variant_master_sm_id is None) ----
    for item in plan.filament_items:
        if item.variant_master_sm_id is not None:
            continue
        attach_parent = attach_parent_for_sm.get(item.sm_filament.id)
        if item.action == "skip":
            if item.error:
                res.add(db, "filament", "failed", error=item.error,
                        sm_filament_id=item.sm_filament.id, fdb_filament_id=item.fdb_id)
            else:
                res.add(db, "filament", "skipped", detail=item.detail,
                        sm_filament_id=item.sm_filament.id, fdb_filament_id=item.fdb_id)
        elif item.action == "link":
            if attach_parent:
                # D3 attach: set parentId on the linked filament too
                try:
                    await filamentdb.update_filament(item.fdb_id, {"parentId": attach_parent})
                    res.add(db, "filament", "updated", detail="variant parent set (attach)",
                            sm_filament_id=item.sm_filament.id, fdb_filament_id=item.fdb_id)
                except Exception as exc:
                    logger.error("wizard execute %s: set parentId (attach) on FDB %s failed: %s",
                                 res.cycle_id, item.fdb_id, exc)
                    res.add(db, "filament", "failed", error=str(exc),
                            sm_filament_id=item.sm_filament.id, fdb_filament_id=item.fdb_id)
                    item.error = str(exc)
            else:
                res.add(db, "filament", "updated", detail=item.detail,
                        sm_filament_id=item.sm_filament.id, fdb_filament_id=item.fdb_id)
        elif item.action == "create":
            payload = dict(item.fdb_payload)
            # Strip the internal sentinel before sending to FDB; stash finish IDs for SM write-back.
            sm_finish_ids = payload.pop("_sm_finish_ids", None)
            if sm_finish_ids:
                _finish_ids_by_sm[item.sm_filament.id] = sm_finish_ids
            if attach_parent:
                payload["parentId"] = attach_parent  # D3: all attach-group members get parentId
            # Phase 3: overlay reconciled canonical values on the master/ungrouped payload (masters only —
            # variants inherit from parent in FDB; never set shared props on variant payloads)
            reconcile_fields = _reconcile_by_master.get(item.sm_filament.id, [])
            if reconcile_fields:
                payload = _overlay_reconcile_on_fdb_payload(payload, reconcile_fields)
            try:
                created = await filamentdb.create_filament(payload)
                item.fdb_id = created.id
                fdb_by_id[created.id] = created
                just_created_fdb_ids.add(created.id)
                res.add(db, "filament", "created",
                        sm_filament_id=item.sm_filament.id, fdb_filament_id=created.id)
            except Exception as exc:
                logger.error("wizard execute %s: create FDB filament failed (SM %s): %s",
                             res.cycle_id, item.sm_filament.id, exc)
                res.add(db, "filament", "failed", error=str(exc),
                        sm_filament_id=item.sm_filament.id)
                item.error = str(exc)
        if item.fdb_id and not item.error:
            # D3: for attach groups, master_map points to the existing FDB parent (not the created id)
            # so Pass 2 variants also receive parentId = existing_fdb_parent_id
            master_map[item.sm_filament.id] = attach_parent if attach_parent else item.fdb_id

    # ---- Pass 2: variants (variant_master_sm_id is set) ----
    for item in plan.filament_items:
        if item.variant_master_sm_id is None:
            continue
        master_fdb_id = master_map.get(item.variant_master_sm_id)
        if master_fdb_id is None:
            err = f"master SM filament {item.variant_master_sm_id} failed or was not resolved"
            res.add(db, "filament", "failed", error=err, sm_filament_id=item.sm_filament.id)
            item.error = err
            continue
        if item.action == "skip":
            if item.error:
                res.add(db, "filament", "failed", error=item.error,
                        sm_filament_id=item.sm_filament.id, fdb_filament_id=item.fdb_id)
            else:
                res.add(db, "filament", "skipped", detail=item.detail,
                        sm_filament_id=item.sm_filament.id, fdb_filament_id=item.fdb_id)
        elif item.action == "link":
            try:
                await filamentdb.update_filament(item.fdb_id, {"parentId": master_fdb_id})
                res.add(db, "filament", "updated", detail="variant parent set",
                        sm_filament_id=item.sm_filament.id, fdb_filament_id=item.fdb_id)
            except Exception as exc:
                logger.error("wizard execute %s: set parentId on FDB %s failed: %s",
                             res.cycle_id, item.fdb_id, exc)
                res.add(db, "filament", "failed", error=str(exc),
                        sm_filament_id=item.sm_filament.id, fdb_filament_id=item.fdb_id)
                item.error = str(exc)
        elif item.action == "create":
            payload = dict(item.fdb_payload)
            # Strip the internal sentinel before sending to FDB; stash finish IDs for SM write-back.
            sm_finish_ids = payload.pop("_sm_finish_ids", None)
            if sm_finish_ids:
                _finish_ids_by_sm[item.sm_filament.id] = sm_finish_ids
            payload["parentId"] = master_fdb_id
            try:
                created = await filamentdb.create_filament(payload)
                item.fdb_id = created.id
                fdb_by_id[created.id] = created
                just_created_fdb_ids.add(created.id)
                res.add(db, "filament", "created",
                        sm_filament_id=item.sm_filament.id, fdb_filament_id=created.id)
            except Exception as exc:
                logger.error("wizard execute %s: create FDB variant failed (SM %s): %s",
                             res.cycle_id, item.sm_filament.id, exc)
                res.add(db, "filament", "failed", error=str(exc),
                        sm_filament_id=item.sm_filament.id)
                item.error = str(exc)

    # ---- Pass 2.5: Spoolman write-backs (Phase 3 reconcile) ----
    # For each SM filament in a group that has reconcile decisions, PATCH it with the canonical
    # values. Apply to ALL members (master + variants). Skip if no fields differ.
    # Master's canonical values were already used to seed FDB — now we correct Spoolman.
    if _reconcile_by_master:
        # Build: variant_sm_id → master_sm_id (reverse of plan.master_of_sm)
        sm_by_id_reconcile: dict[int, SpoolmanFilament] = {f.id: f for f in sm_filaments}
        for item in plan.filament_items:
            # Determine which master's reconcile fields apply to this SM filament
            if item.variant_master_sm_id is not None:
                # This is a variant — use its master's reconcile fields
                master_sm_id = item.variant_master_sm_id
            else:
                # This is a master/ungrouped — its own reconcile fields apply (if any)
                master_sm_id = item.sm_filament.id
            reconcile_fields = _reconcile_by_master.get(master_sm_id, [])
            if not reconcile_fields:
                continue
            sm_fil = sm_by_id_reconcile.get(item.sm_filament.id)
            if sm_fil is None:
                continue
            patch = _compute_sm_reconcile_patch(sm_fil, reconcile_fields)
            if not patch:
                continue
            try:
                await spoolman.update_filament(item.sm_filament.id, patch)
                _log(
                    db, res.cycle_id, res.direction, "update", "filament",
                    spoolman_id=item.sm_filament.id,
                    new_value=patch,
                )
                logger.info(
                    "wizard execute %s: Spoolman write-back for filament %s: %s",
                    res.cycle_id, item.sm_filament.id, patch,
                )
            except Exception as exc:
                logger.error(
                    "wizard execute %s: Spoolman write-back for filament %s failed: %s",
                    res.cycle_id, item.sm_filament.id, exc,
                )
                # Non-fatal: log and continue (don't abort the execute run)
                _log(
                    db, res.cycle_id, res.direction, "error", "filament",
                    spoolman_id=item.sm_filament.id,
                    error_message=f"Spoolman reconcile write-back failed: {exc}",
                )

    # ---- Pass 2.6: Spoolman finish-tag write-back (OpenPrintTag material-tags field) ----
    # For each newly-created FDB filament that had finish IDs, write the structured
    # list back to the SM filament's extra field so the SM side is structural.
    if _finish_ids_by_sm:
        mt_field = _settings.spoolman_field_filamentdb_material_tags
        for sm_fil_id, finish_ids in _finish_ids_by_sm.items():
            encoded = encode_extra_value(finish_ids)
            try:
                await spoolman.update_filament(sm_fil_id, {"extra": {mt_field: encoded}})
                logger.info(
                    "wizard execute %s: wrote finish tags %s to SM filament %s",
                    res.cycle_id, finish_ids, sm_fil_id,
                )
            except Exception as exc:
                logger.warning(
                    "wizard execute %s: finish-tag write-back to SM filament %s failed: %s",
                    res.cycle_id, sm_fil_id, exc,
                )
                # Non-fatal: the SM extra field is for structural tracking; FDB optTags are
                # the authoritative finish representation.

    # ---- Pass 3: FilamentMappings + spool seeding ----
    spool_items_by_fil: dict[int, list[_SpoolPlanItem]] = {}
    for si in plan.spool_items:
        spool_items_by_fil.setdefault(id(si.fil_item), []).append(si)

    # Pre-fetch FDB locations once; new names are created on-demand within each spool's
    # try block so a missing location fails only that spool, not the whole run.
    _fdb_loc_cache: dict[str, str] = {}  # location name → FDB _id
    try:
        for loc in await filamentdb.get_locations():
            if loc.get("name") and loc.get("_id"):
                _fdb_loc_cache[loc["name"]] = loc["_id"]
    except Exception as exc:
        logger.warning("wizard execute %s: could not prefetch FDB locations: %s", res.cycle_id, exc)

    for item in plan.filament_items:
        if item.error or item.fdb_id is None:
            continue
        fdb_id = item.fdb_id
        parent_fdb_id = master_map.get(item.variant_master_sm_id) if item.variant_master_sm_id else None

        # Push structured multicolor for linked/prior-linked multicolor filaments.
        # Creates already have color/secondaryColors/optTags baked into the create payload.
        if item.sm_filament.multi_color_hexes and fdb_id not in just_created_fdb_ids:
            existing = fdb_by_id.get(fdb_id)
            mc = sm_multicolor_to_fdb(
                item.sm_filament.color_hex, item.sm_filament.multi_color_hexes,
                item.sm_filament.multi_color_direction,
                existing_opt_tags=existing.optTags if existing else None,
            )
            try:
                await filamentdb.update_filament(fdb_id, {
                    "color": mc["color"],
                    "secondaryColors": mc["secondaryColors"],
                    "optTags": mc["optTags"],
                })
            except Exception as exc:
                logger.warning(
                    "wizard execute %s: multicolor update for FDB filament %s failed: %s",
                    res.cycle_id, fdb_id, exc,
                )

        fil_map = fil_map_by_sm.get(item.sm_filament.id)
        if fil_map is None:
            fil_map = FilamentMapping(
                spoolman_filament_id=item.sm_filament.id,
                filamentdb_id=fdb_id,
                filamentdb_parent_id=parent_fdb_id,
            )
            db.add(fil_map)
            db.flush()
            fil_map_by_sm[item.sm_filament.id] = fil_map
        elif parent_fdb_id and fil_map.filamentdb_parent_id != parent_fdb_id:
            fil_map.filamentdb_parent_id = parent_fdb_id

        for spool_item in spool_items_by_fil.get(id(item), []):
            if spool_item.action == "skip":
                res.add(db, "spool", "skipped", detail=spool_item.detail,
                        sm_spool_id=spool_item.sm_spool.id, fdb_filament_id=fdb_id,
                        fdb_spool_id=spool_item.skip_fdb_spool_id)
                continue
            try:
                sm_location = spool_item.sm_spool.location
                if sm_location and sm_location not in _fdb_loc_cache:
                    new_loc = await filamentdb.create_location(sm_location)
                    _fdb_loc_cache[sm_location] = new_loc["_id"]
                spool_payload: dict = {
                    "totalWeight": spool_item.planned_gross,
                    fdb_field_name: str(spool_item.sm_spool.id),
                }
                if sm_location:
                    spool_payload["locationId"] = _fdb_loc_cache[sm_location]
                # Seed weight is SET on create — never a usage entry (FR-9 is for decrements).
                raw = await filamentdb.create_spool(fdb_id, spool_payload)
                new_fdb_spool_id = extract_created_spool_id(
                    raw,
                    label_field=fdb_field_name,
                    label_value=str(spool_item.sm_spool.id),
                )
                await spoolman.update_spool(
                    spool_item.sm_spool.id,
                    {"extra": _cross_ref_extra(fdb_id, new_fdb_spool_id, parent_fdb_id)}
                )
                db.add(SpoolMapping(
                    spoolman_spool_id=spool_item.sm_spool.id,
                    filamentdb_filament_id=fdb_id,
                    filamentdb_spool_id=new_fdb_spool_id,
                    filament_mapping_id=fil_map.id,
                ))
                spool_item.sm_spool.extra.update(
                    _cross_ref_extra(fdb_id, new_fdb_spool_id, parent_fdb_id))
                _seed_snapshots(db, spool_item.sm_spool, FDBSpool.model_validate({
                    "_id": new_fdb_spool_id, "label": str(spool_item.sm_spool.id),
                    "totalWeight": spool_item.planned_gross, "retired": False,
                }))
                res.add(db, "spool", "created", sm_spool_id=spool_item.sm_spool.id,
                        fdb_filament_id=fdb_id, fdb_spool_id=new_fdb_spool_id)
            except Exception as exc:
                logger.error("wizard execute %s: create FDB spool failed (SM spool %s): %s",
                             res.cycle_id, spool_item.sm_spool.id, exc)
                res.add(db, "spool", "failed", error=str(exc),
                        sm_spool_id=spool_item.sm_spool.id, fdb_filament_id=fdb_id)


async def _execute_fdb_to_spoolman(
    db: Session,
    res: _ExecResult,
    spoolman,
    filamentdb,
    sm_filaments: list[SpoolmanFilament],
    fdb_filaments: list[FDBFilament],
    decisions_by_sm: dict[int, dict],
    parent_of_fdb: dict[str, str],
    tare_by_fdb_spool: dict[str, float],
    precision: int = 2,
) -> None:
    """Import direction "filamentdb": seed Spoolman from Filament DB.

    The persisted match decisions are Spoolman-keyed, so they describe `link`
    pairs (both ids) and `skip`s of *existing* Spoolman filaments. Filament DB
    filaments with no `link` decision are created in Spoolman (the FR-4 per-record
    skip of an unmatched FDB filament isn't representable in the Spoolman-keyed
    decision model — see docs/decisions.md).
    """
    fdb_field_name = _settings.filamentdb_spoolman_id_field

    # FDB id → Spoolman filament id, taken from the user's link decisions.
    linked_sm_by_fdb: dict[str, int] = {
        d["filamentdb_id"]: d["spoolman_filament_id"]
        for d in decisions_by_sm.values()
        if d.get("action") == "link" and d.get("filamentdb_id")
    }
    sm_filament_by_id = {f.id: f for f in sm_filaments}

    fil_map_by_fdb: dict[str, FilamentMapping] = {
        m.filamentdb_id: m for m in db.query(FilamentMapping).all()
    }
    mapped_fdb_spool_ids: set[str] = {m.filamentdb_spool_id for m in db.query(SpoolMapping).all()}

    # Vendor dedup cache (normalized name → Spoolman vendor id).
    try:
        existing_vendors = await spoolman.get_vendors()
    except Exception:
        existing_vendors = []
    vendor_id_by_norm: dict[str, int] = {normalize_vendor(v.name): v.id for v in existing_vendors}

    async def _ensure_vendor(name: str | None) -> int | None:
        if not name:
            return None
        norm = normalize_vendor(name)
        if norm in vendor_id_by_norm:
            return vendor_id_by_norm[norm]
        created = await spoolman.create_vendor({"name": name})
        vendor_id_by_norm[norm] = created.id
        return created.id

    for fdb_fil in fdb_filaments:
        parent_id = parent_of_fdb.get(fdb_fil.id)

        # ---- resolve the Spoolman filament id (link to existing, or create) ----
        existing_map = fil_map_by_fdb.get(fdb_fil.id)
        if existing_map is not None:
            sm_filament_id = existing_map.spoolman_filament_id
            fil_map = existing_map
            res.add(db, "filament", "skipped", detail="already linked",
                    sm_filament_id=sm_filament_id, fdb_filament_id=fdb_fil.id)
        else:
            linked_sm_id = linked_sm_by_fdb.get(fdb_fil.id)
            try:
                if linked_sm_id is not None and linked_sm_id in sm_filament_by_id:
                    sm_filament_id = linked_sm_id
                    res.add(db, "filament", "updated", detail="linked",
                            sm_filament_id=sm_filament_id, fdb_filament_id=fdb_fil.id)
                else:
                    vendor_id = await _ensure_vendor(fdb_fil.vendor)
                    created = await spoolman.create_filament(
                        _sm_filament_payload_from_fdb(fdb_fil, vendor_id)
                    )
                    sm_filament_id = created.id
                    res.add(db, "filament", "created",
                            sm_filament_id=sm_filament_id, fdb_filament_id=fdb_fil.id)
            except Exception as exc:
                logger.error("wizard execute %s: seed Spoolman filament from FDB %s failed: %s",
                             res.cycle_id, fdb_fil.id, exc)
                res.add(db, "filament", "failed", error=str(exc), fdb_filament_id=fdb_fil.id)
                continue

            fil_map = FilamentMapping(
                spoolman_filament_id=sm_filament_id,
                filamentdb_id=fdb_fil.id,
                filamentdb_parent_id=parent_id,
            )
            db.add(fil_map)
            db.flush()
            fil_map_by_fdb[fdb_fil.id] = fil_map

        # ---- seed spools ----
        for fdb_spool in fdb_fil.spools:
            if fdb_spool.id in mapped_fdb_spool_ids:
                res.add(db, "spool", "skipped", detail="already linked",
                        fdb_filament_id=fdb_fil.id, fdb_spool_id=fdb_spool.id)
                continue

            tare = tare_by_fdb_spool.get(fdb_spool.id)
            if tare is None:
                tare = fdb_fil.spoolWeight
            net_res = fdb_to_spoolman_net(fdb_spool.totalWeight or 0.0, tare, precision=precision)
            try:
                new_sm_spool = await spoolman.create_spool({
                    "filament_id": sm_filament_id,
                    "remaining_weight": net_res.remaining_weight,
                    "extra": _cross_ref_extra(fdb_fil.id, fdb_spool.id, parent_id),
                })
                await filamentdb.update_spool(
                    fdb_fil.id, fdb_spool.id, {fdb_field_name: str(new_sm_spool.id)}
                )
                db.add(SpoolMapping(
                    spoolman_spool_id=new_sm_spool.id,
                    filamentdb_filament_id=fdb_fil.id,
                    filamentdb_spool_id=fdb_spool.id,
                    filament_mapping_id=fil_map.id,
                ))
                mapped_fdb_spool_ids.add(fdb_spool.id)
                _seed_snapshots(db, new_sm_spool, fdb_spool)
                res.add(db, "spool", "created", sm_spool_id=new_sm_spool.id,
                        fdb_filament_id=fdb_fil.id, fdb_spool_id=fdb_spool.id)
            except Exception as exc:
                logger.error("wizard execute %s: seed Spoolman spool from FDB spool %s failed: %s",
                             res.cycle_id, fdb_spool.id, exc)
                res.add(db, "spool", "failed", error=str(exc),
                        fdb_filament_id=fdb_fil.id, fdb_spool_id=fdb_spool.id)


# ---------------------------------------------------------------------------
# Preview flag helpers — pure functions over a _SyncPlan
# ---------------------------------------------------------------------------


def _compute_name_collisions(
    plan: _SyncPlan, fdb_filaments: list[FDBFilament]
) -> list[NameCollisionEntry]:
    # Key on (vendor, name) so that same name from different vendors does NOT collide.
    existing: dict[tuple[str, str], str] = {
        (normalize_vendor(f.vendor), normalize_name(f.name)): f.id
        for f in fdb_filaments
    }
    incoming: dict[tuple[str, str], list[_FilamentPlanItem]] = {}
    for item in plan.filament_items:
        if item.action == "create" and not item.error and item.fdb_payload:
            norm_name = normalize_name(item.fdb_payload.get("name", "") or "")
            norm_vendor = normalize_vendor(item.fdb_payload.get("vendor") or "")
            if norm_name:
                key = (norm_vendor, norm_name)
                incoming.setdefault(key, []).append(item)
    result: list[NameCollisionEntry] = []
    for (norm_vendor, norm_name), items in incoming.items():
        key = (norm_vendor, norm_name)
        vs_existing = key in existing
        intra_batch = len(items) > 1
        if vs_existing or intra_batch:
            result.append(NameCollisionEntry(
                normalized_name=norm_name,
                sm_filament_ids=[i.sm_filament.id for i in items],
                vs_existing=vs_existing,
                intra_batch=intra_batch,
                existing_fdb_filament_id=existing.get(key),
            ))
    return result


def _compute_empty_active(sm_spools: list) -> list[EmptyActiveEntry]:
    result: list[EmptyActiveEntry] = []
    for s in sm_spools:
        if not getattr(s, "archived", False) and (s.remaining_weight or 0.0) == 0.0:
            result.append(EmptyActiveEntry(
                spoolman_spool_id=s.id,
                spoolman_filament_id=s.filament.id if s.filament else None,
                name=s.filament.name if s.filament else None,
            ))
    return result


def _compute_default_tare(plan: _SyncPlan) -> list[DefaultTareEntry]:
    result: list[DefaultTareEntry] = []
    for si in plan.spool_items:
        if si.action == "create" and si.tare_source == "default":
            result.append(DefaultTareEntry(
                spoolman_spool_id=si.sm_spool.id,
                spoolman_filament_id=si.sm_spool.filament.id if si.sm_spool.filament else None,
                name=si.sm_spool.filament.name if si.sm_spool.filament else None,
                planned_gross=si.planned_gross,
                default_tare_used=si.used_tare,
            ))
    return result


def _compute_variant_groups(plan: _SyncPlan) -> list[VariantGroupPreviewEntry]:
    groups: dict[tuple, list[_FilamentPlanItem]] = {}
    for item in plan.filament_items:
        if item.action == "create" and not item.error:
            sm = item.sm_filament
            vendor = sm.vendor.name if sm.vendor else None
            material = sm.material or _DEFAULT_FDB_MATERIAL
            key = (normalize_vendor(vendor), normalize_name(material))
            groups.setdefault(key, []).append(item)
    result: list[VariantGroupPreviewEntry] = []
    for (vendor_key, material_key), items in groups.items():
        if len(items) >= 2:
            first_sm = items[0].sm_filament
            display_base = normalize_name(
                f"{(first_sm.vendor.name + ' ') if first_sm.vendor else ''}{first_sm.material or ''}".strip()
            )
            result.append(VariantGroupPreviewEntry(
                base_name=display_base,
                vendor=first_sm.vendor.name if first_sm.vendor else None,
                material=first_sm.material or _DEFAULT_FDB_MATERIAL,
                sm_filament_ids=[i.sm_filament.id for i in items],
            ))
    return result


def _compute_sm_variant_plan(
    plan: _SyncPlan, sm_filaments: list[SpoolmanFilament]
) -> list[SMVariantGroupRow]:
    """Build the SMVariantGroupRow tree from a plan that has variant_master_sm_id annotated."""
    sm_by_id: dict[int, SpoolmanFilament] = {f.id: f for f in sm_filaments}
    groups: dict[int, list[_FilamentPlanItem]] = {}  # master_sm_id → variant items
    for item in plan.filament_items:
        if item.variant_master_sm_id is not None:
            groups.setdefault(item.variant_master_sm_id, []).append(item)

    result: list[SMVariantGroupRow] = []
    for master_sm_id, variant_items in groups.items():
        master_sm = sm_by_id.get(master_sm_id)
        if master_sm is None:
            continue
        master_row = SMVariantMemberRow(ref=_sm_ref(master_sm), is_master=True, conflicts=[])
        member_rows: list[SMVariantMemberRow] = [master_row]
        for vi in variant_items:
            conflicts = [VariantPropConflict(**c) for c in (vi.prop_conflicts or [])]
            member_rows.append(SMVariantMemberRow(
                ref=_sm_ref(vi.sm_filament), is_master=False, conflicts=conflicts,
            ))
        variant_base = normalize_name(
            f"{(master_sm.vendor.name + ' ') if master_sm.vendor else ''}{master_sm.material or ''}".strip()
        )
        result.append(SMVariantGroupRow(
            base_name=variant_base,
            vendor=master_sm.vendor.name if master_sm.vendor else None,
            material=master_sm.material,
            suggested_master=_sm_ref(master_sm),
            members=member_rows,
        ))
    return result


# ---------------------------------------------------------------------------
# Phase 4 — Planned writes helper
# ---------------------------------------------------------------------------


def _compute_planned_writes(
    plan: "_SyncPlan",
    sm_filaments: list[SpoolmanFilament],
    reconcile_by_master: dict[int, list[dict]],
) -> list["PlannedWrite"]:
    """Build the structured write-op list for the Phase-4 pre-flight summary.

    Covers:
    - FDB filament creates (action=="create")
    - FDB variant creates (action=="create" with variant_master_sm_id set)
    - FDB spool creates (spool_items with action=="create")
    - Spoolman filament write-backs (reconcile-driven PATCHes for differing fields)

    Does NOT perform any I/O — purely computes what execute would do.
    """
    sm_by_id: dict[int, SpoolmanFilament] = {f.id: f for f in sm_filaments}
    planned_writes: list[PlannedWrite] = []

    # FDB filament creates + variant creates
    for item in plan.filament_items:
        if item.action != "create" or item.error:
            continue
        sm = item.sm_filament
        label_parts = [sm.name]
        if sm.vendor:
            label_parts.append(f"({sm.vendor.name})")
        label_parts.append(f"[SM #{sm.id}]")
        label = " ".join(label_parts)
        # Compute fields from the payload
        payload = item.fdb_payload or {}
        # Overlay reconcile for master/ungrouped creates
        if item.variant_master_sm_id is None:
            rec_fields = reconcile_by_master.get(sm.id, [])
            if rec_fields:
                payload = _overlay_reconcile_on_fdb_payload(payload, rec_fields)
        fields = [
            PlannedWriteField(name=k, old=None, new=v)
            for k, v in payload.items()
            if k not in ("name", "vendor")  # skip identity fields for cleaner display
        ]
        # Ensure cost is always surfaced in the planned-write fields when present.
        # (payload filtering above already includes it; this comment documents intent.)
        planned_writes.append(PlannedWrite(
            system="filamentdb",
            entity_type="filament",
            action="create",
            target_label=label,
            fields=fields,
        ))

    # FDB spool creates
    for si in plan.spool_items:
        if si.action != "create":
            continue
        sm_spool = si.sm_spool
        sm_fil = getattr(sm_spool, "filament", None)
        fil_name = sm_fil.name if sm_fil else f"SM filament #{getattr(sm_fil, 'id', '?')}"
        label = f"{fil_name} — Spool #{sm_spool.id}"
        planned_writes.append(PlannedWrite(
            system="filamentdb",
            entity_type="spool",
            action="create",
            target_label=label,
            fields=[
                PlannedWriteField(name="totalWeight", old=None, new=si.planned_gross),
                PlannedWriteField(name="tare_source", old=None, new=si.tare_source),
            ],
        ))

    # Spoolman filament write-backs (reconcile PATCHes)
    for item in plan.filament_items:
        # Determine which master's reconcile fields apply
        if item.variant_master_sm_id is not None:
            master_sm_id = item.variant_master_sm_id
        else:
            master_sm_id = item.sm_filament.id
        rec_fields = reconcile_by_master.get(master_sm_id, [])
        if not rec_fields:
            continue
        sm_fil = sm_by_id.get(item.sm_filament.id)
        if sm_fil is None:
            continue
        patch = _compute_sm_reconcile_patch(sm_fil, rec_fields)
        if not patch:
            continue
        label_parts = [sm_fil.name]
        if sm_fil.vendor:
            label_parts.append(f"({sm_fil.vendor.name})")
        label_parts.append(f"[SM #{sm_fil.id}]")
        label = " ".join(label_parts)
        fields = [
            PlannedWriteField(
                name=sm_key,
                old=getattr(sm_fil, sm_key, None),
                new=canonical_value,
            )
            for sm_key, canonical_value in patch.items()
        ]
        planned_writes.append(PlannedWrite(
            system="spoolman",
            entity_type="filament",
            action="update",
            target_label=label,
            fields=fields,
        ))

    return planned_writes


# ---------------------------------------------------------------------------
# FR-4 foundation — GET /api/wizard/preview (read-only)
# ---------------------------------------------------------------------------


@router.get("/wizard/preview", response_model=WizardPreviewResponse)
async def wizard_preview(request: Request, db: Session = Depends(get_db)) -> WizardPreviewResponse:
    """Read-only preview: what execute would do, plus reconcile flags (FR-4 foundation).

    Makes no writes to either upstream system. The plan is computed from the same
    planner as wizard_execute so preview ≡ execute by construction.
    """
    import_direction = get_config_value(db, "import_direction", "spoolman")
    sync_direction = (
        "spoolman_to_filamentdb" if import_direction == "spoolman" else "filamentdb_to_spoolman"
    )
    precision: int = int(get_config_value(db, "weight_precision_decimals", 2))

    match_decisions = get_config_value(db, "wizard_match_decisions", []) or []
    decisions_by_sm = {d["spoolman_filament_id"]: d for d in match_decisions}
    sm_variant_decisions = get_config_value(db, "wizard_sm_variant_decisions", []) or []
    master_of_sm = _build_master_of_sm(sm_variant_decisions)
    include_empty = bool(get_config_value(db, "wizard_include_empty_spools", False))
    # Phase 4: load reconcile decisions for the planned-writes summary
    reconcile_decisions_raw = get_config_value(db, "wizard_variances_reconcile", []) or []
    reconcile_by_master_preview = _build_reconcile_by_master(reconcile_decisions_raw)

    try:
        sm_filaments = await request.app.state.spoolman.get_filaments()
        sm_spools = await request.app.state.spoolman.get_spools()
        fdb_filaments = await request.app.state.filamentdb.get_filaments()
    except Exception as exc:
        logger.error("wizard preview: upstream fetch failed: %s", exc)
        raise api_error(502, "upstream_fetch_failed",
                        "Could not read both systems to generate the preview.")

    if import_direction != "spoolman":
        return WizardPreviewResponse(
            direction=sync_direction,
            plan_rows=[],
            flag_counts=PreviewFlagCounts(
                name_collision=0, empty_active=0, default_tare=0, variant_group=0,
            ),
            name_collisions=[], empty_active=[], default_tare=[], variant_groups=[],
        )

    plan = _plan_spoolman_to_fdb(
        db, sm_filaments, sm_spools, fdb_filaments,
        decisions_by_sm, master_of_sm, {},  # no tare overrides for preview
        precision=precision,
        include_empty_spools=include_empty,
    )

    _action_for_plan: dict[str, str] = {
        "create": "created", "link": "updated", "skip": "skipped",
    }
    plan_rows: list[WizardExecuteRecord] = []
    for item in plan.filament_items:
        action = "failed" if item.error else _action_for_plan.get(item.action, "skipped")
        plan_rows.append(WizardExecuteRecord(
            entity_type="filament",
            action=action,
            spoolman_filament_id=item.sm_filament.id,
            filamentdb_filament_id=item.fdb_id,
            detail=item.detail,
            error=item.error,
        ))
    for si in plan.spool_items:
        plan_rows.append(WizardExecuteRecord(
            entity_type="spool",
            action="created" if si.action == "create" else "skipped",
            spoolman_spool_id=si.sm_spool.id,
            spoolman_filament_id=si.sm_spool.filament.id if si.sm_spool.filament else None,
            filamentdb_filament_id=si.fdb_filament_id,
            filamentdb_spool_id=si.skip_fdb_spool_id,
            detail=si.detail,
        ))

    name_collisions = _compute_name_collisions(plan, fdb_filaments)
    empty_active = _compute_empty_active(sm_spools)
    default_tare = _compute_default_tare(plan)
    variant_groups = _compute_variant_groups(plan)
    variant_plan = _compute_sm_variant_plan(plan, sm_filaments)
    # Phase 4: compute structured planned-writes list
    planned_writes = _compute_planned_writes(plan, sm_filaments, reconcile_by_master_preview)

    return WizardPreviewResponse(
        direction=sync_direction,
        plan_rows=plan_rows,
        flag_counts=PreviewFlagCounts(
            name_collision=len(name_collisions),
            empty_active=len(empty_active),
            default_tare=len(default_tare),
            variant_group=len(variant_groups),
        ),
        name_collisions=name_collisions,
        empty_active=empty_active,
        default_tare=default_tare,
        variant_groups=variant_groups,
        variant_plan=variant_plan,
        include_empty_spools=include_empty,
        planned_writes=planned_writes,
    )


@router.post("/wizard/execute", response_model=WizardExecuteResponse)
async def wizard_execute(
    request: Request,
    payload: WizardExecuteRequest | None = Body(default=None),
    db: Session = Depends(get_db),
) -> WizardExecuteResponse:
    """Perform the initial sync write to both upstreams (FR-7)."""
    cycle_id = str(uuid.uuid4())
    spoolman = request.app.state.spoolman
    filamentdb = request.app.state.filamentdb

    import_direction = get_config_value(db, "import_direction", "spoolman")
    sync_direction = (
        "spoolman_to_filamentdb" if import_direction == "spoolman" else "filamentdb_to_spoolman"
    )
    res = _ExecResult(cycle_id=cycle_id, direction=sync_direction)

    overrides = payload.tare_overrides if payload else []
    tare_by_sm_spool = {o.spoolman_spool_id: o.tare for o in overrides if o.spoolman_spool_id is not None}
    tare_by_fdb_spool = {o.filamentdb_spool_id: o.tare for o in overrides if o.filamentdb_spool_id is not None}
    precision: int = int(get_config_value(db, "weight_precision_decimals", 2))

    match_decisions = get_config_value(db, "wizard_match_decisions", []) or []
    decisions_by_sm = {d["spoolman_filament_id"]: d for d in match_decisions}

    # SM-direction variant decisions (keyed on SM ids)
    sm_variant_decisions = get_config_value(db, "wizard_sm_variant_decisions", []) or []
    master_of_sm = _build_master_of_sm(sm_variant_decisions)
    attach_parent_for_sm = _build_attach_parent_for_sm(sm_variant_decisions)
    include_empty = bool(get_config_value(db, "wizard_include_empty_spools", False))

    # Phase 3: load reconcile decisions
    reconcile_decisions_raw = get_config_value(db, "wizard_variances_reconcile", []) or []
    reconcile_by_master = _build_reconcile_by_master(reconcile_decisions_raw)

    # FDB-direction variant decisions (keyed on FDB ids, legacy — unchanged)
    variant_decisions = get_config_value(db, "wizard_variant_decisions", []) or []
    parent_of_fdb: dict[str, str] = {}
    for group in variant_decisions:
        parent = group.get("parent_filamentdb_id")
        for variant in group.get("variant_filamentdb_ids", []):
            if parent:
                parent_of_fdb[variant] = parent

    # Guarantee the Spoolman cross-ref extra fields exist before we write them.
    try:
        await spoolman.ensure_extra_fields()
    except Exception as exc:
        logger.warning("wizard execute %s: ensure_extra_fields failed (continuing): %s", cycle_id, exc)

    # Fetch upstream state. A failure here is FATAL — we cannot drive the import,
    # so we do NOT flip wizard_completed and surface a 502.
    try:
        sm_filaments = await spoolman.get_filaments()
        sm_spools = await spoolman.get_spools()
        fdb_filaments = await filamentdb.get_filaments()
    except Exception as exc:
        logger.error("wizard execute %s: fatal — could not read upstream state: %s", cycle_id, exc)
        _log(db, cycle_id, sync_direction, "error", "filament", error_message=f"upstream fetch failed: {exc}")
        db.commit()
        raise api_error(
            502, "upstream_fetch_failed",
            "Could not read both systems to execute the initial sync; nothing was written.",
        )

    if import_direction == "spoolman":
        await _execute_spoolman_to_fdb(
            db, res, spoolman, filamentdb,
            sm_filaments, sm_spools, fdb_filaments,
            decisions_by_sm, master_of_sm, attach_parent_for_sm, tare_by_sm_spool,
            reconcile_by_master=reconcile_by_master,
            precision=precision,
            include_empty_spools=include_empty,
        )
    else:
        await _execute_fdb_to_spoolman(
            db, res, spoolman, filamentdb,
            sm_filaments, fdb_filaments,
            decisions_by_sm, parent_of_fdb, tare_by_fdb_spool,
            precision=precision,
        )

    # Only flip wizard_completed when the run had zero failures. A partial run
    # leaves the flag false so the user can fix issues and re-run (idempotent).
    wizard_done = res.failed == 0
    if wizard_done:
        set_config_value(db, "wizard_completed", True)
    db.commit()

    logger.info(
        "wizard execute %s (%s) — created=%d updated=%d skipped=%d failed=%d wizard_completed=%s",
        cycle_id, sync_direction, res.created, res.updated, res.skipped, res.failed, wizard_done,
    )
    return WizardExecuteResponse(
        cycle_id=cycle_id,
        direction=sync_direction,
        created=res.created,
        updated=res.updated,
        skipped=res.skipped,
        failed=res.failed,
        wizard_completed=wizard_done,
        records=res.records,
    )
