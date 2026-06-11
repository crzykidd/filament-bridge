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
from app.core.color import apply_finish_tags, sm_multicolor_to_fdb
from app.core.fields import resolve_effective_cost
from app.core.material_tags import finish_ids_from_text, strip_finish_words
from app.core.matcher import extract_finish_line, sm_prop_conflicts
from app.core.weight import DEFAULT_TARE_GRAMS, spoolman_to_fdb_gross
from app.models.mapping import FilamentMapping, SpoolMapping
from app.schemas.filamentdb import FDBFilament
from app.schemas.spoolman import SpoolmanFilament, decode_extra_value

logger = logging.getLogger(__name__)

_DEFAULT_FDB_MATERIAL = "Unknown"


def _filament_base_name(
    vendor: str | None,
    raw_material: str,
    sm_name: str,
    variant_keywords: list[str] | None = None,
) -> str:
    """Build the vendor + material + finish base name for an FDB filament (no color, no marker).

    This is the shared logic used by both the container naming path and the variant/standalone
    naming path so master and variant names can never drift.

    E.g. vendor="Hatchbox", raw_material="PLA", sm_name="PLA Light Blue", keywords=[] →
    "Hatchbox PLA"

    E.g. vendor="Prusament", raw_material="PLA Silk", sm_name="Silk Red", keywords=["silk"] →
    "Prusament PLA Silk"
    """
    tag_map = _settings.parsed_material_tag_ids
    finish = extract_finish_line(sm_name or "", raw_material, keywords=variant_keywords)
    base_material = strip_finish_words(raw_material, tag_map)
    if not base_material:
        base_material = _DEFAULT_FDB_MATERIAL
    parts = []
    if vendor:
        parts.append(vendor)
    parts.append(base_material)
    if finish:
        # Capitalize for display (finish comes from normalized lower)
        parts.append(finish.title())
    return " ".join(parts)


def _patch_fdb_name(
    sm: SpoolmanFilament,
    *,
    base_name: str | None = None,
    variant_keywords: list[str] | None = None,
) -> str:
    """Compute the proper FDB filament name: vendor + material[+finish] + color.

    When *base_name* is supplied (e.g. from the master's cluster key) it is used directly;
    otherwise it is derived from *sm*'s vendor/material/name.

    Dedup guards (all case-insensitive):
    1. color already starts with base_name → the SM name already carries vendor+material;
       return color unchanged to avoid doubling.  e.g. "ELEGOO PLA Light Blue" + base "ELEGOO PLA".
    2. base_name already contains or ends with color → color is a material/base substring;
       return base_name as-is.  e.g. name="PLA", base="ELEGOO PLA" → "ELEGOO PLA".
    3. color starts with a material prefix that already appears in base_name → strip the
       duplicate material prefix so we get "ELEGOO PLA Red" not "ELEGOO PLA PLA Red".
       e.g. color="PLA Red", base="ELEGOO PLA" → detect "PLA " prefix → strip → "Red"
       → result "ELEGOO PLA Red".
    """
    vendor = sm.vendor.name if sm.vendor else None
    raw_material = sm.material or _DEFAULT_FDB_MATERIAL
    if base_name is None:
        base_name = _filament_base_name(vendor, raw_material, sm.name, variant_keywords)

    color = sm.name or ""
    color_lo = color.lower().strip()
    base_lo = base_name.lower().strip()

    # Guard 1: SM name already carries the full qualified name (starts with vendor+material).
    if color_lo.startswith(base_lo):
        return color

    # Guard 2: the color token is already part of the base (e.g. "PLA" inside "ELEGOO PLA").
    # This avoids "ELEGOO PLA PLA" when the SM filament name is just the material token.
    if color_lo and (color_lo in base_lo or base_lo.endswith(color_lo)):
        return base_name

    # Guard 3: color starts with the stripped material (or any trailing token of base_name)
    # that is already in base_name — strip it from color to get the pure color suffix.
    # e.g. color="PLA Red", base="ELEGOO PLA" → strip leading "pla " → color_suffix="Red".
    # Only strip if there is a remaining suffix (don't reduce to empty string).
    tag_map = _settings.parsed_material_tag_ids
    base_material_lo = strip_finish_words(raw_material.lower(), tag_map) or raw_material.lower()
    base_material_lo = base_material_lo.strip()
    if base_material_lo and color_lo.startswith(base_material_lo):
        suffix = color[len(base_material_lo):].strip()
        if suffix:
            return f"{base_name} {suffix}"
        # color == material only → return base_name
        return base_name

    if color:
        return f"{base_name} {color}"
    return base_name


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
    # When a FilamentMapping exists but its FDB target is gone, it is recorded here
    # so wizard_execute can delete it before writing the fresh mapping.
    stale_filament_mapping: object = None  # FilamentMapping | None


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
    # When a SpoolMapping exists but its FDB spool target is gone, it is recorded here
    # so wizard_execute can delete it before writing the fresh mapping.
    stale_spool_mapping: object = None  # SpoolMapping | None


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

    OpenPrintTag finish model: ``type`` = finish-STRIPPED base material (e.g. "PLA"
    not "PLA Silk"); finish IDs go into ``optTags`` via ``apply_finish_tags``.
    The multicolor arrangement tags (28/29) in ``mc["optTags"]`` are preserved
    alongside the finish tags — both are merged into the final ``optTags`` list.
    """
    material = sm.material
    if not material:
        logger.warning(
            "SM filament %s (%s) has no material; defaulting to '%s'",
            sm.id, sm.name, _DEFAULT_FDB_MATERIAL,
        )
        material = _DEFAULT_FDB_MATERIAL

    # ---- OpenPrintTag finish model ----
    tag_map = _settings.parsed_material_tag_ids
    # Compute finish tag IDs from the name+material text.
    finish_ids = finish_ids_from_text(sm.name, material, tag_map)
    # Strip finish keywords to get the base material type for FDB's ``type`` field.
    base_type = strip_finish_words(material, tag_map)
    if not base_type:
        base_type = _DEFAULT_FDB_MATERIAL

    mc = sm_multicolor_to_fdb(sm.color_hex, sm.multi_color_hexes, sm.multi_color_direction)
    # Merge finish tags into the arrangement-aware optTags from the multicolor helper.
    # apply_finish_tags preserves arrangement tags (28/29) and unknown tags, then
    # replaces the managed finish-ID set with the newly computed finish_ids.
    opt_tags = apply_finish_tags(mc["optTags"], finish_ids)

    spool_weight = resolved_tare if resolved_tare is not None else sm.spool_weight
    payload: dict = {
        "name": sm.name,
        "vendor": sm.vendor.name if sm.vendor else None,
        "type": base_type,
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
    if opt_tags:
        payload["optTags"] = opt_tags
    temps: dict = {}
    if sm.settings_extruder_temp is not None:
        temps["nozzle"] = sm.settings_extruder_temp
    if sm.settings_bed_temp is not None:
        temps["bed"] = sm.settings_bed_temp
    if temps:
        payload["temperatures"] = temps

    # Stage the finish IDs for the SM filament extra field write-back.
    # The planner stores this in the payload under a sentinel key that the execute
    # path picks up to PATCH the SM filament extra field after FDB create.
    # The key is stripped from the FDB payload before the POST.
    if finish_ids:
        payload["_sm_finish_ids"] = sorted(finish_ids)

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
    variant_keywords: list[str] | None = None,
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
    # Build a lookup of all SpoolMapping rows keyed by SM spool id for stale validation.
    spool_map_by_sm_spool_id: dict[int, SpoolMapping] = {
        m.spoolman_spool_id: m for m in db.query(SpoolMapping).all()
    }
    mapped_sm_spool_ids: set[int] = set(spool_map_by_sm_spool_id.keys())

    # ---- Phase A: resolve each SM filament → planned FDB action ----
    for sm_fil in sm_filaments:
        existing = fil_map_by_sm.get(sm_fil.id)
        if existing is not None:
            # Validate that the mapping's FDB target still exists.
            # If the FDB filament was deleted the mapping is stale: don't skip it,
            # fall through to the normal decision logic and mark it for cleanup.
            if existing.filamentdb_id in fdb_by_id:
                item = _FilamentPlanItem(
                    sm_filament=sm_fil, action="skip",
                    fdb_id=existing.filamentdb_id, resolved=True, detail="already linked",
                )
                plan.filament_items.append(item)
                continue
            # Stale mapping — FDB filament is gone. Fall through to decision logic
            # and flag the stale mapping for removal on execute.
            logger.debug(
                "planner: SM filament %s has FilamentMapping → FDB %s which no longer exists "
                "(stale); routing through decision logic",
                sm_fil.id, existing.filamentdb_id,
            )
            _stale_fil_mapping: FilamentMapping | None = existing
        else:
            _stale_fil_mapping = None

        decision = decisions_by_sm.get(sm_fil.id)
        if decision is None or decision.get("action") == "skip":
            item = _FilamentPlanItem(
                sm_filament=sm_fil, action="skip", resolved=False,
                detail="no decision" if decision is None else "user skipped",
                stale_filament_mapping=_stale_fil_mapping,
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
                    stale_filament_mapping=_stale_fil_mapping,
                )
            else:
                item = _FilamentPlanItem(
                    sm_filament=sm_fil, action="link",
                    fdb_id=fdb_id, resolved=True, detail="linked",
                    stale_filament_mapping=_stale_fil_mapping,
                )
            plan.filament_items.append(item)
        elif action == "create":
            fil_spools = sm_spools_by_filament.get(sm_fil.id, [])
            cost = resolve_effective_cost(sm_fil.price, fil_spools)
            tare = _resolve_filament_tare(sm_fil, fil_spools, tare_by_sm_spool)
            payload = _fdb_filament_payload_from_sm(
                sm_fil, effective_cost=cost, spools=fil_spools, resolved_tare=tare,
            )
            detail = (
                "stale mapping (FDB filament gone) — recreating"
                if _stale_fil_mapping else None
            )
            item = _FilamentPlanItem(
                sm_filament=sm_fil, action="create",
                fdb_id=None, fdb_payload=payload, resolved=True,
                detail=detail,
                stale_filament_mapping=_stale_fil_mapping,
            )
            plan.filament_items.append(item)
        else:
            item = _FilamentPlanItem(
                sm_filament=sm_fil, action="skip", resolved=False,
                error=f"unknown action '{action}'",
                stale_filament_mapping=_stale_fil_mapping,
            )
            plan.filament_items.append(item)

    # ---- Phase B: annotate variants with master SM id + property conflicts ----
    # Also patch the FDB filament name for variant creates: use the master's base name
    # (vendor + material + finish, no marker) + the variant's color (sm.name) so names
    # are unique and never bare-color-only.  This eliminates FDB 409 name collisions
    # when two different lines share a color name (e.g. "Light Blue").
    plan.master_of_sm = dict(master_of_sm)
    sm_by_id: dict[int, SpoolmanFilament] = {f.id: f for f in sm_filaments}
    for item in plan.filament_items:
        master_sm_id = master_of_sm.get(item.sm_filament.id)
        if master_sm_id is not None:
            item.variant_master_sm_id = master_sm_id
            master_sm_fil = sm_by_id.get(master_sm_id)
            if master_sm_fil is not None and not item.error:
                item.prop_conflicts = sm_prop_conflicts(master_sm_fil, item.sm_filament)
            # Patch the create payload name using the master's base name + variant color.
            if item.action == "create" and item.fdb_payload is not None:
                master_for_base = master_sm_fil if master_sm_fil is not None else item.sm_filament
                base = _filament_base_name(
                    master_for_base.vendor.name if master_for_base.vendor else None,
                    master_for_base.material or _DEFAULT_FDB_MATERIAL,
                    master_for_base.name or "",
                    variant_keywords,
                )
                item.fdb_payload = dict(item.fdb_payload)
                item.fdb_payload["name"] = _patch_fdb_name(
                    item.sm_filament, base_name=base, variant_keywords=variant_keywords,
                )

    # ---- Phase B.5: patch standalone (non-variant) create names ----
    # For filaments with no master, ensure the name includes vendor + material so it
    # cannot collide with a bare-color name from a different line.  Items that were
    # already "link" or "skip" (standardized name) are untouched.
    for item in plan.filament_items:
        if item.variant_master_sm_id is not None:
            continue  # already patched above
        if item.action != "create" or item.fdb_payload is None:
            continue
        item.fdb_payload = dict(item.fdb_payload)
        item.fdb_payload["name"] = _patch_fdb_name(
            item.sm_filament, variant_keywords=variant_keywords,
        )

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
            # A live SpoolMapping causes a skip only when its FDB spool target still exists.
            # If the SpoolMapping references a deleted FDB spool, it is stale: treat as
            # create and mark the stale mapping for removal on execute.
            _stale_spool_mapping: SpoolMapping | None = None
            if sm_spool.id in mapped_sm_spool_ids:
                spool_map = spool_map_by_sm_spool_id[sm_spool.id]
                if spool_map.filamentdb_spool_id in _fdb_spool_ids:
                    # Valid mapping — skip as already linked.
                    plan.spool_items.append(_SpoolPlanItem(
                        sm_spool=sm_spool, fil_item=item, action="skip",
                        skip_fdb_spool_id=spool_map.filamentdb_spool_id,
                        fdb_filament_id=item.fdb_id,
                        detail="already linked",
                    ))
                    continue
                # Stale mapping — FDB spool is gone. Flag for cleanup and fall through.
                logger.debug(
                    "planner: SM spool %s has SpoolMapping → FDB spool %s which no longer "
                    "exists (stale); routing through create",
                    sm_spool.id, spool_map.filamentdb_spool_id,
                )
                _stale_spool_mapping = spool_map

            # A cross-ref (filamentdb_spool_id extra) only causes a skip when the
            # referenced FDB spool still exists — a stale xref (pointing at a deleted
            # spool) is treated as a create so the import proceeds normally and the
            # write-back overwrites the stale id automatically.
            xref_is_live = bool(xref) and xref in _fdb_spool_ids
            if xref_is_live:
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
                stale_spool_mapping=_stale_spool_mapping,
            ))

    return plan
