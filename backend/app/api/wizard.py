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

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app import __version__
from app.api.config import get_config_value, set_config_value
from app.api.health import _check_filamentdb, _check_spoolman
from app.core.matcher import match_filaments, normalize_name, normalize_vendor
from app.core.weight import fdb_to_spoolman_net, spoolman_to_fdb_gross
from app.db import get_db
from app.schemas.api import (
    AmbiguousRow,
    FilamentRef,
    MatchPairRow,
    SystemStatus,
    WeightPreviewRow,
    WizardConnectivityResponse,
    WizardDecisionAck,
    WizardDirectionRequest,
    WizardMatchesRequest,
    WizardMatchesResponse,
    WizardVariantsRequest,
    WizardVariantsResponse,
    WizardWeightsResponse,
    VariantGroupRow,
)
from app.schemas.filamentdb import FDBFilament
from app.schemas.spoolman import SpoolmanFilament

router = APIRouter()


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
