"""Sync planner — pure planning functions with no upstream I/O writes.

Shared by wizard_execute (FR-7) and plan_dry_run (FR-14) so preview ≡ execute
by construction. Neither function writes to either upstream system.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from dataclasses import field as dc_field

from sqlalchemy.orm import Session

from app.config import settings as _settings
from app.core.color import sm_multicolor_to_fdb
from app.core.fields import resolve_effective_cost
from app.core.matcher import sm_prop_conflicts
from app.core.weight import DEFAULT_TARE_GRAMS, spoolman_to_fdb_gross
from app.models.mapping import FilamentMapping, SpoolMapping
from app.schemas.filamentdb import FDBFilament
from app.schemas.spoolman import SpoolmanFilament, decode_extra_value

logger = logging.getLogger(__name__)

_DEFAULT_FDB_MATERIAL = "Unknown"


def _resolve_filament_tare(
    sm_filament: SpoolmanFilament,
    fil_spools: list,
    tare_by_sm_spool: dict[int, float],
) -> float:
    """Resolve the wizard-canonical tare for a Spoolman filament.

    Resolution order (mirrors Phase-C spool tare logic, lifted to the filament level):
    1. User override from tare_by_sm_spool for any spool of this filament (first spool
       by id, same deterministic tie-break used elsewhere).
    2. Spoolman spool-level spool_weight (first spool by id with a non-null value).
    3. Spoolman filament-level spool_weight.
    4. DEFAULT_TARE_GRAMS (200 g).

    This is the same tare the Phase-C gross-weight computation uses, so the value
    written to FDB spoolWeight always matches what drove the spool totalWeight.
    """
    # Sort spools by id for deterministic selection (mirrors resolve_effective_cost).
    sorted_spools = sorted(fil_spools, key=lambda s: s.id)
    # 1. Per-spool user override from the wizard tare_by_sm_spool map.
    for s in sorted_spools:
        if s.id in tare_by_sm_spool:
            return tare_by_sm_spool[s.id]
    # 2. Spool-level spool_weight.
    for s in sorted_spools:
        if getattr(s, "spool_weight", None) is not None:
            return s.spool_weight
    # 3. Filament-level spool_weight.
    if sm_filament.spool_weight is not None:
        return sm_filament.spool_weight
    # 4. Default.
    return DEFAULT_TARE_GRAMS


@dataclass
class _FilamentPlanItem:
    sm_filament: SpoolmanFilament
    action: str  # "create" | "link" | "skip"
    fdb_id: str | None = None
    fdb_payload: dict | None = None  # for "create" action
    parent_id: str | None = None
    resolved: bool = False  # True = has/will-have an fdb_id; spool items are planned
    detail: str | None = None
    error: str | None = None
    variant_master_sm_id: int | None = None  # set when this SM filament is a variant
    prop_conflicts: list = dc_field(default_factory=list)  # list[dict] from sm_prop_conflicts


@dataclass
class _SpoolPlanItem:
    sm_spool: object  # SpoolmanSpool
    fil_item: object  # _FilamentPlanItem back-ref
    action: str = "create"  # "create" | "skip"
    skip_fdb_spool_id: str | None = None  # xref for already-linked spools
    fdb_filament_id: str | None = None  # known (link/skip-linked), None for create
    planned_gross: float = 0.0
    tare_source: str = "default"  # "spoolman" | "default"
    used_tare: float = 0.0
    detail: str | None = None


@dataclass
class _SyncPlan:
    direction: str = "spoolman_to_filamentdb"
    filament_items: list = dc_field(default_factory=list)
    spool_items: list = dc_field(default_factory=list)
    master_of_sm: dict = dc_field(default_factory=dict)  # variant_sm_id → master_sm_id


def _fdb_filament_payload_from_sm(
    sm: SpoolmanFilament,
    *,
    effective_cost: float | None = None,
    spools: list | None = None,
    resolved_tare: float | None = None,
) -> dict:
    """Map a Spoolman filament onto the FDB create-filament body (core fields only).

    Structured multicolor (color/secondaryColors/optTags) is included for v1.33.0+
    Filament DB; on older instances the unknown keys are harmless extras.

    effective_cost: pre-resolved spool-first cost (pass from _plan_spoolman_to_fdb);
    included in the payload only when non-null.

    spools: non-archived spools for this filament; used to resolve netFilamentWeight
    when sm.weight is None (mirrors resolve_effective_cost selection style).

    resolved_tare: the wizard-resolved tare used for gross-weight computation (user
    override → spool spool_weight → filament spool_weight → DEFAULT_TARE_GRAMS).
    When provided, sets spoolWeight from this resolved value instead of raw
    sm.spool_weight (which is often NULL for Spoolman filaments).
    """
    material = sm.material
    if not material:
        logger.warning(
            "SM filament %s (%s) has no material; defaulting to '%s'",
            sm.id, sm.name, _DEFAULT_FDB_MATERIAL,
        )
        material = _DEFAULT_FDB_MATERIAL
    mc = sm_multicolor_to_fdb(sm.color_hex, sm.multi_color_hexes, sm.multi_color_direction)
    spool_weight = resolved_tare if resolved_tare is not None else sm.spool_weight
    payload: dict = {
        "name": sm.name,
        "vendor": sm.vendor.name if sm.vendor else None,
        "type": material,
        "color": mc["color"],
        "density": sm.density,
        "diameter": sm.diameter,
        "spoolWeight": spool_weight,
    }
    if effective_cost is not None:
        payload["cost"] = effective_cost
    # Resolve net filament weight (full spool capacity) for the FDB % bar.
    # Primary: Spoolman filament-level weight. Fallback: first spool (by id)
    # with a non-null initial_weight (mirrors resolve_effective_cost style).
    net_filament_weight: float | None = sm.weight
    if net_filament_weight is None and spools:
        for s in sorted(spools, key=lambda s: s.id):
            if s.initial_weight is not None:
                net_filament_weight = s.initial_weight
                break
    if net_filament_weight is not None:
        payload["netFilamentWeight"] = net_filament_weight
    if mc["secondaryColors"]:
        payload["secondaryColors"] = mc["secondaryColors"]
    if mc["optTags"]:
        payload["optTags"] = mc["optTags"]
    temps: dict = {}
    if sm.settings_extruder_temp is not None:
        temps["nozzle"] = sm.settings_extruder_temp
    if sm.settings_bed_temp is not None:
        temps["bed"] = sm.settings_bed_temp
    if temps:
        payload["temperatures"] = temps
    return {k: v for k, v in payload.items() if v is not None}


def _plan_spoolman_to_fdb(
    db: Session,
    sm_filaments: list[SpoolmanFilament],
    sm_spools: list,
    fdb_filaments: list[FDBFilament],
    decisions_by_sm: dict[int, dict],
    master_of_sm: dict[int, int],
    tare_by_sm_spool: dict[int, float],
    precision: int = 2,
    include_empty_spools: bool = True,
    existing_fdb_spool_ids: set[str] | None = None,
) -> _SyncPlan:
    """Compute what _execute_spoolman_to_fdb would do — no writes, no upstream I/O.

    Returns a _SyncPlan with filament_items + spool_items that wizard_execute
    then drives through the actual API calls. The preview endpoint calls this
    same function and reports without executing, so the two cannot drift.
    """
    plan = _SyncPlan()

    fdb_by_id: dict[str, FDBFilament] = {f.id: f for f in fdb_filaments}

    sm_spools_by_filament: dict[int, list] = {}
    for s in sm_spools:
        if not getattr(s, "archived", False):
            sm_spools_by_filament.setdefault(s.filament.id, []).append(s)

    fil_map_by_sm: dict[int, FilamentMapping] = {
        m.spoolman_filament_id: m for m in db.query(FilamentMapping).all()
    }
    mapped_sm_spool_ids: set[int] = {m.spoolman_spool_id for m in db.query(SpoolMapping).all()}

    # ---- Phase A: resolve each SM filament → planned FDB action ----
    for sm_fil in sm_filaments:
        existing = fil_map_by_sm.get(sm_fil.id)
        if existing is not None:
            item = _FilamentPlanItem(
                sm_filament=sm_fil, action="skip",
                fdb_id=existing.filamentdb_id, resolved=True, detail="already linked",
            )
            plan.filament_items.append(item)
            continue

        decision = decisions_by_sm.get(sm_fil.id)
        if decision is None or decision.get("action") == "skip":
            item = _FilamentPlanItem(
                sm_filament=sm_fil, action="skip", resolved=False,
                detail="no decision" if decision is None else "user skipped",
            )
            plan.filament_items.append(item)
            continue

        action = decision.get("action")
        if action == "link":
            fdb_id = decision.get("filamentdb_id")
            if not fdb_id or fdb_id not in fdb_by_id:
                item = _FilamentPlanItem(
                    sm_filament=sm_fil, action="skip", fdb_id=fdb_id, resolved=False,
                    error="link target filament not found",
                )
            else:
                item = _FilamentPlanItem(
                    sm_filament=sm_fil, action="link",
                    fdb_id=fdb_id, resolved=True, detail="linked",
                )
            plan.filament_items.append(item)
        elif action == "create":
            fil_spools = sm_spools_by_filament.get(sm_fil.id, [])
            cost = resolve_effective_cost(sm_fil.price, fil_spools)
            tare = _resolve_filament_tare(sm_fil, fil_spools, tare_by_sm_spool)
            payload = _fdb_filament_payload_from_sm(
                sm_fil, effective_cost=cost, spools=fil_spools, resolved_tare=tare,
            )
            item = _FilamentPlanItem(
                sm_filament=sm_fil, action="create",
                fdb_id=None, fdb_payload=payload, resolved=True,
            )
            plan.filament_items.append(item)
        else:
            item = _FilamentPlanItem(
                sm_filament=sm_fil, action="skip", resolved=False,
                error=f"unknown action '{action}'",
            )
            plan.filament_items.append(item)

    # ---- Phase B: annotate variants with master SM id + property conflicts ----
    plan.master_of_sm = dict(master_of_sm)
    sm_by_id: dict[int, SpoolmanFilament] = {f.id: f for f in sm_filaments}
    for item in plan.filament_items:
        master_sm_id = master_of_sm.get(item.sm_filament.id)
        if master_sm_id is not None:
            item.variant_master_sm_id = master_sm_id
            master_sm_fil = sm_by_id.get(master_sm_id)
            if master_sm_fil is not None and not item.error:
                item.prop_conflicts = sm_prop_conflicts(master_sm_fil, item.sm_filament)

    # Build set of all current FDB spool ids for stale-xref validation.
    # A cross-ref only causes a skip when the referenced spool actually exists.
    _fdb_spool_ids: set[str] = existing_fdb_spool_ids if existing_fdb_spool_ids is not None else {
        spool.id for f in fdb_filaments for spool in f.spools
    }

    # ---- Phase C: plan spool creates for each resolved filament ----
    for item in plan.filament_items:
        if not item.resolved:
            continue
        for sm_spool in sm_spools_by_filament.get(item.sm_filament.id, []):
            if not include_empty_spools and (sm_spool.remaining_weight or 0.0) == 0.0:
                continue  # D4: skip empty spool records when toggle is off
            xref = decode_extra_value(
                sm_spool.extra.get(_settings.spoolman_field_filamentdb_spool_id)
            )
            # A live SpoolMapping always causes a skip (the spool is already paired).
            # A cross-ref (filamentdb_spool_id extra) only causes a skip when the
            # referenced FDB spool still exists — a stale xref (pointing at a deleted
            # spool) is treated as a create so the import proceeds normally and the
            # write-back overwrites the stale id automatically.
            xref_is_live = bool(xref) and xref in _fdb_spool_ids
            if sm_spool.id in mapped_sm_spool_ids or xref_is_live:
                plan.spool_items.append(_SpoolPlanItem(
                    sm_spool=sm_spool, fil_item=item, action="skip",
                    skip_fdb_spool_id=xref or None,
                    fdb_filament_id=item.fdb_id,
                    detail="already linked",
                ))
                continue

            tare = tare_by_sm_spool.get(sm_spool.id)
            if tare is None:
                tare = sm_spool.spool_weight if sm_spool.spool_weight is not None else (
                    sm_spool.filament.spool_weight if sm_spool.filament else None
                )
            gross_res = spoolman_to_fdb_gross(sm_spool.remaining_weight or 0.0, tare, precision=precision)
            plan.spool_items.append(_SpoolPlanItem(
                sm_spool=sm_spool, fil_item=item, action="create",
                fdb_filament_id=item.fdb_id,  # None for new creates; filled post-write in execute
                planned_gross=gross_res.total_weight,
                tare_source="default" if gross_res.used_default_tare else "spoolman",
                used_tare=gross_res.total_weight - (sm_spool.remaining_weight or 0.0),
            ))

    return plan
