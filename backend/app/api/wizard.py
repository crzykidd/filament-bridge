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
from app.core.engine import _fdb_snapshot_dict, _log, _sm_snapshot_dict, _upsert_snapshot
from app.core.matcher import match_filaments, normalize_name, normalize_vendor
from app.core.weight import fdb_to_spoolman_net, spoolman_to_fdb_gross
from app.db import get_db
from app.models.mapping import FilamentMapping, SpoolMapping
from app.schemas.api import (
    AmbiguousRow,
    FilamentRef,
    MatchPairRow,
    SystemStatus,
    WeightPreviewRow,
    WizardConnectivityResponse,
    WizardDecisionAck,
    WizardDirectionRequest,
    WizardExecuteRecord,
    WizardExecuteRequest,
    WizardExecuteResponse,
    WizardMatchesRequest,
    WizardMatchesResponse,
    WizardVariantsRequest,
    WizardVariantsResponse,
    WizardWeightsResponse,
    VariantGroupRow,
)
from app.schemas.filamentdb import FDBFilament, FDBSpool
from app.schemas.spoolman import SpoolmanFilament, decode_extra_value, encode_extra_value

logger = logging.getLogger(__name__)

router = APIRouter()

_DEFAULT_FDB_MATERIAL = "Unknown"


# ---------------------------------------------------------------------------
# Ref builders
# ---------------------------------------------------------------------------


def _sm_ref(sm: SpoolmanFilament) -> FilamentRef:
    return FilamentRef(
        spoolman_filament_id=sm.id,
        name=sm.name,
        vendor=sm.vendor.name if sm.vendor else None,
        color=sm.color_hex,
    )


def _fdb_ref(fdb: FDBFilament) -> FilamentRef:
    return FilamentRef(
        filamentdb_filament_id=fdb.id,
        name=fdb.name,
        vendor=fdb.vendor,
        color=fdb.color,
    )


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


@router.post("/wizard/direction", response_model=WizardDecisionAck)
def wizard_direction(payload: WizardDirectionRequest, db: Session = Depends(get_db)) -> WizardDecisionAck:
    persisted = 0
    set_config_value(db, "import_direction", payload.import_direction)
    persisted += 1
    for key in (
        "weight_source_of_truth",
        "material_properties_source_of_truth",
        "new_spool_source_of_truth",
    ):
        value = getattr(payload, key)
        if value is not None:
            set_config_value(db, key, value)
            persisted += 1
    db.commit()
    return WizardDecisionAck(persisted=persisted)


# ---------------------------------------------------------------------------
# FR-3 / FR-4 — auto-matching + review
# ---------------------------------------------------------------------------


@router.get("/wizard/matches", response_model=WizardMatchesResponse)
async def wizard_matches(request: Request) -> WizardMatchesResponse:
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
    return WizardMatchesResponse(
        matched=matched,
        unmatched_spoolman=[_sm_ref(s) for s in mr.unmatched_spoolman],
        unmatched_filamentdb=[_fdb_ref(f) for f in mr.unmatched_fdb],
        ambiguous=ambiguous,
    )


@router.post("/wizard/matches", response_model=WizardDecisionAck)
def wizard_save_matches(payload: WizardMatchesRequest, db: Session = Depends(get_db)) -> WizardDecisionAck:
    set_config_value(db, "wizard_match_decisions", [d.model_dump() for d in payload.decisions])
    db.commit()
    return WizardDecisionAck(persisted=len(payload.decisions))


# ---------------------------------------------------------------------------
# FR-5 — weight conversion preview
# ---------------------------------------------------------------------------


@router.get("/wizard/weights", response_model=WizardWeightsResponse)
async def wizard_weights(request: Request, db: Session = Depends(get_db)) -> WizardWeightsResponse:
    import_direction = get_config_value(db, "import_direction", "spoolman")
    rows: list[WeightPreviewRow] = []

    if import_direction == "spoolman":
        direction = "spoolman_to_filamentdb"
        spools = await request.app.state.spoolman.get_spools()
        for s in spools:
            if s.archived:
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
async def wizard_variants(request: Request) -> WizardVariantsResponse:
    filaments: list[FDBFilament] = await request.app.state.filamentdb.get_filaments()

    groups: dict[tuple[str, str, str], list[FDBFilament]] = {}
    for f in filaments:
        key = (normalize_vendor(f.vendor), _strip_color(f.name, f.color), f.type or "")
        groups.setdefault(key, []).append(f)

    out: list[VariantGroupRow] = []
    for (vendor, base_name, _type), members in groups.items():
        if len(members) < 2:
            continue
        # Heuristic: the shortest name is the most generic → suggested parent.
        ordered = sorted(members, key=lambda f: len(f.name))
        parent, *variants = ordered
        out.append(
            VariantGroupRow(
                base_name=base_name,
                vendor=parent.vendor,
                suggested_parent=_fdb_ref(parent),
                variants=[_fdb_ref(v) for v in variants],
            )
        )
    return WizardVariantsResponse(groups=out)


@router.post("/wizard/variants", response_model=WizardDecisionAck)
def wizard_save_variants(payload: WizardVariantsRequest, db: Session = Depends(get_db)) -> WizardDecisionAck:
    set_config_value(db, "wizard_variant_decisions", [g.model_dump() for g in payload.groups])
    db.commit()
    return WizardDecisionAck(persisted=len(payload.groups))


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


def _fdb_filament_payload_from_sm(sm: SpoolmanFilament) -> dict:
    """Map a Spoolman filament onto the FDB create-filament body (core fields only)."""
    material = sm.material
    if not material:
        logger.warning(
            "SM filament %s (%s) has no material; defaulting to '%s'",
            sm.id, sm.name, _DEFAULT_FDB_MATERIAL,
        )
        material = _DEFAULT_FDB_MATERIAL
    payload: dict = {
        "name": sm.name,
        "vendor": sm.vendor.name if sm.vendor else None,
        "type": material,
        "color": sm.color_hex,
        "density": sm.density,
        "spoolWeight": sm.spool_weight,
    }
    temps: dict = {}
    if sm.settings_extruder_temp is not None:
        temps["nozzle"] = sm.settings_extruder_temp
    if sm.settings_bed_temp is not None:
        temps["bed"] = sm.settings_bed_temp
    if temps:
        payload["temperatures"] = temps
    return {k: v for k, v in payload.items() if v is not None}


def _sm_filament_payload_from_fdb(fdb: FDBFilament, vendor_id: int | None) -> dict:
    """Map an FDB filament onto the Spoolman create-filament body (core fields only)."""
    payload: dict = {
        "name": fdb.name,
        "material": fdb.type,
        "color_hex": (fdb.color or "").lstrip("#") or None,
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


async def _execute_spoolman_to_fdb(
    db: Session,
    res: _ExecResult,
    spoolman,
    filamentdb,
    sm_filaments: list[SpoolmanFilament],
    sm_spools: list,
    fdb_filaments: list[FDBFilament],
    decisions_by_sm: dict[int, dict],
    parent_of_fdb: dict[str, str],
    tare_by_sm_spool: dict[int, float],
    precision: int = 2,
) -> None:
    """Import direction "spoolman": seed Filament DB from Spoolman."""
    fdb_field_name = _settings.filamentdb_spoolman_id_field
    fdb_by_id: dict[str, FDBFilament] = {f.id: f for f in fdb_filaments}

    sm_spools_by_filament: dict[int, list] = {}
    for s in sm_spools:
        if getattr(s, "archived", False):
            continue
        sm_spools_by_filament.setdefault(s.filament.id, []).append(s)

    fil_map_by_sm: dict[int, FilamentMapping] = {
        m.spoolman_filament_id: m for m in db.query(FilamentMapping).all()
    }
    mapped_sm_spool_ids: set[int] = {m.spoolman_spool_id for m in db.query(SpoolMapping).all()}

    # ---- Phase A: resolve each Spoolman filament → an FDB filament id ----
    resolved: list[tuple[SpoolmanFilament, str]] = []
    for sm_fil in sm_filaments:
        existing = fil_map_by_sm.get(sm_fil.id)
        if existing is not None:
            # Already linked by a prior run — idempotent no-op at filament level.
            resolved.append((sm_fil, existing.filamentdb_id))
            res.add(db, "filament", "skipped", detail="already linked",
                    sm_filament_id=sm_fil.id, fdb_filament_id=existing.filamentdb_id)
            continue

        decision = decisions_by_sm.get(sm_fil.id)
        if decision is None or decision.get("action") == "skip":
            res.add(db, "filament", "skipped", detail="no decision" if decision is None else "user skipped",
                    sm_filament_id=sm_fil.id)
            continue

        action = decision.get("action")
        if action == "link":
            fdb_id = decision.get("filamentdb_id")
            if not fdb_id or fdb_id not in fdb_by_id:
                res.add(db, "filament", "failed", error="link target filament not found",
                        sm_filament_id=sm_fil.id, fdb_filament_id=fdb_id)
                continue
            resolved.append((sm_fil, fdb_id))
            res.add(db, "filament", "updated", detail="linked",
                    sm_filament_id=sm_fil.id, fdb_filament_id=fdb_id)
        elif action == "create":
            try:
                created = await filamentdb.create_filament(_fdb_filament_payload_from_sm(sm_fil))
                fdb_by_id[created.id] = created
                resolved.append((sm_fil, created.id))
                res.add(db, "filament", "created", sm_filament_id=sm_fil.id, fdb_filament_id=created.id)
            except Exception as exc:
                logger.error("wizard execute %s: create FDB filament failed (SM %s): %s",
                             res.cycle_id, sm_fil.id, exc)
                res.add(db, "filament", "failed", error=str(exc), sm_filament_id=sm_fil.id)
        else:
            res.add(db, "filament", "failed", error=f"unknown action '{action}'", sm_filament_id=sm_fil.id)

    # ---- Phase B: apply variant groupings (parents already exist by now) ----
    for fdb_id, parent_id in parent_of_fdb.items():
        if fdb_id not in fdb_by_id or parent_id not in fdb_by_id:
            continue  # group references a filament outside this import — skip silently
        try:
            await filamentdb.update_filament(fdb_id, {"parentId": parent_id})
            res.add(db, "filament", "updated", detail="variant parent set",
                    fdb_filament_id=fdb_id)
        except Exception as exc:
            logger.error("wizard execute %s: set parentId %s→%s failed: %s",
                         res.cycle_id, fdb_id, parent_id, exc)
            res.add(db, "filament", "failed", error=str(exc), fdb_filament_id=fdb_id)

    # ---- Phase C: mappings + spool seeding ----
    for sm_fil, fdb_id in resolved:
        parent_id = parent_of_fdb.get(fdb_id)
        fil_map = fil_map_by_sm.get(sm_fil.id)
        if fil_map is None:
            fil_map = FilamentMapping(
                spoolman_filament_id=sm_fil.id,
                filamentdb_id=fdb_id,
                filamentdb_parent_id=parent_id,
            )
            db.add(fil_map)
            db.flush()
            fil_map_by_sm[sm_fil.id] = fil_map
        elif parent_id and fil_map.filamentdb_parent_id != parent_id:
            fil_map.filamentdb_parent_id = parent_id

        for sm_spool in sm_spools_by_filament.get(sm_fil.id, []):
            # Idempotency: already mapped, or the spool already carries the FDB
            # cross-ref upstream (a prior run created it but rolled back the row).
            xref = decode_extra_value(sm_spool.extra.get(_settings.spoolman_field_filamentdb_spool_id))
            if sm_spool.id in mapped_sm_spool_ids or xref:
                res.add(db, "spool", "skipped", detail="already linked",
                        sm_spool_id=sm_spool.id, fdb_filament_id=fdb_id, fdb_spool_id=xref or None)
                continue

            tare = tare_by_sm_spool.get(sm_spool.id)
            if tare is None:
                tare = sm_spool.spool_weight if sm_spool.spool_weight is not None else (
                    sm_spool.filament.spool_weight if sm_spool.filament else None
                )
            gross_res = spoolman_to_fdb_gross(sm_spool.remaining_weight or 0.0, tare, precision=precision)
            try:
                # Seed weight is SET on create — never a usage entry (FR-9 is for decrements).
                raw = await filamentdb.create_spool(fdb_id, {
                    "totalWeight": gross_res.total_weight,
                    fdb_field_name: str(sm_spool.id),
                })
                new_fdb_spool_id = raw.get("_id") or raw.get("id") or ""
                await spoolman.update_spool(
                    sm_spool.id, {"extra": _cross_ref_extra(fdb_id, new_fdb_spool_id, parent_id)}
                )
                db.add(SpoolMapping(
                    spoolman_spool_id=sm_spool.id,
                    filamentdb_filament_id=fdb_id,
                    filamentdb_spool_id=new_fdb_spool_id,
                    filament_mapping_id=fil_map.id,
                ))
                mapped_sm_spool_ids.add(sm_spool.id)
                # Reflect the cross-ref we just wrote in the seeded snapshot.
                sm_spool.extra.update(_cross_ref_extra(fdb_id, new_fdb_spool_id, parent_id))
                _seed_snapshots(db, sm_spool, FDBSpool.model_validate({
                    "_id": new_fdb_spool_id, "label": str(sm_spool.id),
                    "totalWeight": gross_res.total_weight, "retired": False,
                }))
                res.add(db, "spool", "created", sm_spool_id=sm_spool.id,
                        fdb_filament_id=fdb_id, fdb_spool_id=new_fdb_spool_id)
            except Exception as exc:
                logger.error("wizard execute %s: create FDB spool failed (SM spool %s): %s",
                             res.cycle_id, sm_spool.id, exc)
                res.add(db, "spool", "failed", error=str(exc),
                        sm_spool_id=sm_spool.id, fdb_filament_id=fdb_id)


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
    variant_decisions = get_config_value(db, "wizard_variant_decisions", []) or []
    decisions_by_sm = {d["spoolman_filament_id"]: d for d in match_decisions}
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
            decisions_by_sm, parent_of_fdb, tare_by_sm_spool,
            precision=precision,
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
