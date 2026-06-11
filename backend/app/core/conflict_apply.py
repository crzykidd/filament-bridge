"""Apply logic for master_divergence conflict resolution (Phase B).

The three actions (`apply_all`, `variant_override`, `ignore`) each write upstream,
refresh snapshots to prevent ping-pong re-detection, log to sync_log, and
auto-resolve sibling conflicts where appropriate.

Called from api/conflicts.py after a human has chosen an action.
"""

from __future__ import annotations

import datetime
import json
import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.engine import _log, _merge_snapshot
from app.models.conflict import Conflict
from app.models.mapping import FilamentMapping
from app.models.sync_log import SyncLog
from app.models.snapshot import Snapshot
from app.services.filamentdb import FilamentDBClient
from app.services.spoolman import SpoolmanClient

logger = logging.getLogger(__name__)

# Mapping from Spoolman native filament field → FDB filament field path.
# Mirrors MATERIAL_PROP_SCALAR_PAIRS in engine.py.
_SM_TO_FDB_FIELD: dict[str, str] = {
    "material": "type",
    "density": "density",
    "diameter": "diameter",
    "spool_weight": "spoolWeight",
    "weight": "netFilamentWeight",
    # Temp fields (stored with snap key _mp_<sm_field>)
    "settings_bed_temp": "temperatures.bed",
    "settings_extruder_temp": "temperatures.nozzle",
}

# Inverse: FDB field path → Spoolman native filament field.
_FDB_TO_SM_FIELD: dict[str, str] = {v: k for k, v in _SM_TO_FDB_FIELD.items()}

# The snap key used for a given SM field (mirrors engine.py convention).
def _snap_key(sm_field: str) -> str:
    return f"_mp_{sm_field}"


def _sm_field_for_conflict(c: Conflict) -> str | None:
    """Return the Spoolman field name for a master_divergence conflict's field_name.

    The conflict's field_name is the SM field name (e.g. "density", "material").
    Returns None if the field is unrecognized.
    """
    return c.field_name if c.field_name in _SM_TO_FDB_FIELD else None


def _fdb_path_for_sm_field(sm_field: str) -> str:
    """Return the FDB JSON path for a Spoolman field name."""
    return _SM_TO_FDB_FIELD.get(sm_field, sm_field)


def _decode(raw: str | None) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


async def _get_variant_line(
    fdb_variant_id: str,
    filamentdb: FilamentDBClient,
    db: Session,
) -> tuple[str, list[str]]:
    """Fetch (master_id, [variant_fdb_ids]) for a variant filament.

    Returns the master's FDB id and the list of all variant FDB ids that are
    children of that master (from the master's ``_variants`` field).
    Raises on network error (caller should not resolve the conflict on failure).
    """
    variant_detail = await filamentdb.get_filament(fdb_variant_id)
    master_id: str = variant_detail.parentId  # type: ignore[assignment]
    if not master_id:
        raise ValueError(f"FDB filament {fdb_variant_id} has no parentId — not a variant")

    master_detail = await filamentdb.get_filament(master_id)
    # _variants is a list[FDBVariantRef] on FDBFilamentDetail (Pydantic objects with .id).
    raw_variants = getattr(master_detail, "variants", None) or []
    variant_ids: list[str] = [
        v.id if hasattr(v, "id") else str(v)
        for v in raw_variants
    ]
    return master_id, variant_ids


def _find_sm_filament_id_for_fdb(fdb_id: str, db: Session) -> int | None:
    """Return the Spoolman filament id mapped to the given FDB filament id, or None."""
    row = db.query(FilamentMapping).filter(
        FilamentMapping.filamentdb_id == fdb_id,
        FilamentMapping.spoolman_filament_id.isnot(None),
    ).first()
    return row.spoolman_filament_id if row else None


def _resolve_conflict_row(
    c: Conflict,
    resolution: str,
    resolved_value: Any,
    db: Session,
) -> None:
    """Mark a conflict resolved without upstream writes."""
    c.resolution = resolution
    c.resolved_value = json.dumps(resolved_value)
    c.resolved_at = datetime.datetime.now(datetime.timezone.utc)


def _auto_resolve_siblings(
    db: Session,
    cycle_id: str,
    sm_field: str,
    master_id: str,
    exclude_conflict_id: int,
    resolution: str,
    resolved_value: Any,
) -> None:
    """Auto-resolve open master_divergence conflicts for the same field and master line.

    Finds all open master_divergence conflicts for the given sm_field that belong
    to variants of the same master (identified by filamentdb_filament_id matching
    any variant of master_id, or the master itself).
    """
    # Find all FDB filament ids in the line (master + its variants via FilamentMapping).
    # We look up all FilamentMappings where filamentdb_parent_id == master_id OR
    # filamentdb_id == master_id.
    line_fdb_ids: list[str] = [master_id]
    mappings = db.query(FilamentMapping).filter(
        FilamentMapping.filamentdb_id != master_id,
    ).all()
    for m in mappings:
        # Include any mapping whose FDB filament's parent is the master.
        # We can't fetch FDB here (no async), so we use the parent_id stored
        # in FilamentMapping (filamentdb_parent_id).
        if m.filamentdb_parent_id == master_id:
            line_fdb_ids.append(m.filamentdb_id)

    siblings = (
        db.query(Conflict)
        .filter(
            Conflict.id != exclude_conflict_id,
            Conflict.resolved_at.is_(None),
            Conflict.conflict_type == "master_divergence",
            Conflict.field_name == sm_field,
            Conflict.filamentdb_filament_id.in_(line_fdb_ids),
        )
        .all()
    )
    now = datetime.datetime.now(datetime.timezone.utc)
    for sibling in siblings:
        sibling.resolution = resolution
        sibling.resolved_value = json.dumps(resolved_value)
        sibling.resolved_at = now
        _log(
            db, cycle_id, "conflict_apply", "auto_resolve", "filament",
            spoolman_id=sibling.spoolman_id,
            fdb_filament_id=sibling.filamentdb_filament_id,
            field_name=sm_field,
            new_value=resolved_value,
        )


async def apply_master_divergence(
    conflict: Conflict,
    action: str,
    db: Session,
    spoolman: SpoolmanClient,
    filamentdb: FilamentDBClient,
) -> None:
    """Execute the chosen action for a master_divergence conflict.

    Raises ValueError for invalid inputs.
    Raises httpx.HTTPStatusError / other exceptions on upstream failure.
    On upstream failure the conflict is NOT resolved (caller handles the 502).
    """
    if conflict.conflict_type != "master_divergence":
        raise ValueError("apply_master_divergence called for non-master_divergence conflict")
    if action not in ("apply_all", "variant_override", "ignore"):
        raise ValueError(f"Unknown action: {action!r}")

    sm_field = _sm_field_for_conflict(conflict)
    if sm_field is None:
        raise ValueError(f"Unrecognized field_name for master_divergence: {conflict.field_name!r}")

    fdb_path = _fdb_path_for_sm_field(sm_field)
    snap_key = _snap_key(sm_field)

    # The incoming Spoolman value is what the human approved.
    new_value = _decode(conflict.spoolman_value)
    fdb_variant_id: str = conflict.filamentdb_filament_id  # type: ignore[assignment]
    sm_filament_id: int = conflict.spoolman_id  # type: ignore[assignment]

    cycle_id = f"conflict-apply-{conflict.id}-{uuid.uuid4().hex[:8]}"

    if action == "apply_all":
        await _action_apply_all(
            conflict=conflict,
            sm_field=sm_field,
            fdb_path=fdb_path,
            snap_key=snap_key,
            new_value=new_value,
            fdb_variant_id=fdb_variant_id,
            sm_filament_id=sm_filament_id,
            cycle_id=cycle_id,
            db=db,
            spoolman=spoolman,
            filamentdb=filamentdb,
        )

    elif action == "variant_override":
        await _action_variant_override(
            conflict=conflict,
            sm_field=sm_field,
            fdb_path=fdb_path,
            snap_key=snap_key,
            new_value=new_value,
            fdb_variant_id=fdb_variant_id,
            sm_filament_id=sm_filament_id,
            cycle_id=cycle_id,
            db=db,
            spoolman=spoolman,
            filamentdb=filamentdb,
        )

    elif action == "ignore":
        await _action_ignore(
            conflict=conflict,
            sm_field=sm_field,
            snap_key=snap_key,
            new_value=new_value,
            fdb_variant_id=fdb_variant_id,
            sm_filament_id=sm_filament_id,
            cycle_id=cycle_id,
            db=db,
            filamentdb=filamentdb,
        )


async def _action_apply_all(
    *,
    conflict: Conflict,
    sm_field: str,
    fdb_path: str,
    snap_key: str,
    new_value: Any,
    fdb_variant_id: str,
    sm_filament_id: int,
    cycle_id: str,
    db: Session,
    spoolman: SpoolmanClient,
    filamentdb: FilamentDBClient,
) -> None:
    """apply_all: write new_value to master + overridden variants in FDB;
    write new_value to every mapped SM filament in the line.
    """
    master_id, variant_ids = await _get_variant_line(fdb_variant_id, filamentdb, db)

    # --- FDB writes ---
    # 1. Write master.
    _build_fdb_payload_and_write = _make_fdb_write(fdb_path, new_value)
    await filamentdb.update_filament(master_id, _build_fdb_payload_and_write)
    _log(
        db, cycle_id, "conflict_apply", "update", "filament",
        fdb_filament_id=master_id, field_name=sm_field, new_value=new_value,
    )

    # 2. For each variant with its own override, also write.
    for vid in variant_ids:
        try:
            vd = await filamentdb.get_filament(vid)
            # Use Pydantic field name (alias _inherited → inherited_fields)
            inherited = list(getattr(vd, "inherited_fields", None) or [])
            # If fdb_path NOT in _inherited → field is explicitly overridden on this variant.
            # We check the leaf FDB field name (last component for dotted paths).
            leaf = fdb_path.split(".")[-1]
            if fdb_path not in inherited and leaf not in inherited:
                await filamentdb.update_filament(vid, _make_fdb_write(fdb_path, new_value))
                _log(
                    db, cycle_id, "conflict_apply", "update", "filament",
                    fdb_filament_id=vid, field_name=sm_field, new_value=new_value,
                )
        except Exception as exc:
            logger.warning("apply_all: could not write FDB variant %s: %s", vid, exc)
            _log(
                db, cycle_id, "conflict_apply", "error", "filament",
                fdb_filament_id=vid, field_name=sm_field,
                error_message=str(exc),
            )

    # 3. Write master SM filament — the source of new_value — and any other mapped SM filaments
    #    for variants in the line.
    sm_ids_in_line: list[int] = [sm_filament_id]
    for vid in variant_ids:
        sid = _find_sm_filament_id_for_fdb(vid, db)
        if sid is not None and sid not in sm_ids_in_line:
            sm_ids_in_line.append(sid)
    # Also the master itself.
    master_sm_id = _find_sm_filament_id_for_fdb(master_id, db)
    if master_sm_id is not None and master_sm_id not in sm_ids_in_line:
        sm_ids_in_line.append(master_sm_id)

    for sid in sm_ids_in_line:
        try:
            await spoolman.update_filament(sid, {sm_field: new_value})
            _log(
                db, cycle_id, "conflict_apply", "update", "filament",
                spoolman_id=sid, field_name=sm_field, new_value=new_value,
            )
        except Exception as exc:
            logger.warning("apply_all: could not write SM filament %s: %s", sid, exc)
            _log(
                db, cycle_id, "conflict_apply", "error", "filament",
                spoolman_id=sid, field_name=sm_field,
                error_message=str(exc),
            )

    # --- Snapshot refresh (anti-ping-pong) ---
    # Refresh snapshots for master + all variants (both sides) to agreed new_value.
    fdb_ids_to_refresh = [master_id] + list(variant_ids)
    for fid in fdb_ids_to_refresh:
        _merge_snapshot(db, "filamentdb", "filament", fid, {snap_key: new_value})
    for sid in sm_ids_in_line:
        _merge_snapshot(db, "spoolman", "filament", str(sid), {snap_key: new_value})

    # --- Resolve this conflict ---
    _resolve_conflict_row(conflict, "apply_all", new_value, db)

    # --- Auto-resolve sibling same-field/same-line master_divergence conflicts ---
    _auto_resolve_siblings(
        db=db,
        cycle_id=cycle_id,
        sm_field=sm_field,
        master_id=master_id,
        exclude_conflict_id=conflict.id,
        resolution="apply_all",
        resolved_value=new_value,
    )


async def _action_variant_override(
    *,
    conflict: Conflict,
    sm_field: str,
    fdb_path: str,
    snap_key: str,
    new_value: Any,
    fdb_variant_id: str,
    sm_filament_id: int,
    cycle_id: str,
    db: Session,
    spoolman: SpoolmanClient,
    filamentdb: FilamentDBClient,
) -> None:
    """variant_override: write new_value to the variant in FDB only.
    Master + siblings untouched. SM is already the source.
    """
    await filamentdb.update_filament(fdb_variant_id, _make_fdb_write(fdb_path, new_value))
    _log(
        db, cycle_id, "conflict_apply", "update", "filament",
        fdb_filament_id=fdb_variant_id, field_name=sm_field, new_value=new_value,
    )

    # Snapshot refresh for V + S.
    _merge_snapshot(db, "filamentdb", "filament", fdb_variant_id, {snap_key: new_value})
    _merge_snapshot(db, "spoolman", "filament", str(sm_filament_id), {snap_key: new_value})

    _resolve_conflict_row(conflict, "variant_override", new_value, db)


async def _action_ignore(
    *,
    conflict: Conflict,
    sm_field: str,
    snap_key: str,
    new_value: Any,
    fdb_variant_id: str,
    sm_filament_id: int,
    cycle_id: str,
    db: Session,
    filamentdb: FilamentDBClient,
) -> None:
    """ignore: no upstream writes.
    Store current resolved values as baselines so next cycle won't re-queue.
    """
    # Read the current FDB resolved value (live, so baseline matches actual state).
    current_fdb_value = None
    try:
        vd = await filamentdb.get_filament(fdb_variant_id)
        # The resolved (inherited or overridden) value for this field.
        from app.schemas.filamentdb import FDBFilamentDetail
        current_fdb_value = _get_fdb_field_value(vd, sm_field)
    except Exception as exc:
        logger.warning("ignore: could not fetch FDB detail for baseline: %s", exc)
        # Fall back to the stored filamentdb_value in the conflict.
        current_fdb_value = _decode(conflict.filamentdb_value)

    # SM value is what's in the conflict (new incoming value).
    current_sm_value = new_value  # already decoded above

    # Store baselines both sides.
    _merge_snapshot(db, "filamentdb", "filament", fdb_variant_id, {snap_key: current_fdb_value})
    _merge_snapshot(db, "spoolman", "filament", str(sm_filament_id), {snap_key: current_sm_value})

    _log(
        db, cycle_id, "conflict_apply", "ignore", "filament",
        fdb_filament_id=fdb_variant_id,
        spoolman_id=sm_filament_id,
        field_name=sm_field,
        old_value=current_fdb_value,
        new_value=current_sm_value,
    )

    _resolve_conflict_row(conflict, "ignore", None, db)


def _make_fdb_write(fdb_path: str, value: Any) -> dict:
    """Build a FDB PUT payload dict from a field path (dotted → nested dict)."""
    parts = fdb_path.split(".", 1)
    if len(parts) == 1:
        return {fdb_path: value}
    # Nested (e.g. "temperatures.bed")
    return {parts[0]: {parts[1]: value}}


def _get_fdb_field_value(detail: Any, sm_field: str) -> Any:
    """Read the resolved FDB value for a SM field from a FDBFilamentDetail."""
    fdb_path = _fdb_path_for_sm_field(sm_field)
    if fdb_path == "type":
        return getattr(detail, "type", None)
    if fdb_path == "density":
        return getattr(detail, "density", None)
    if fdb_path == "diameter":
        return getattr(detail, "diameter", None)
    if fdb_path == "spoolWeight":
        return getattr(detail, "spoolWeight", None)
    if fdb_path == "netFilamentWeight":
        return getattr(detail, "netFilamentWeight", None)
    if "temperatures" in fdb_path:
        temps = getattr(detail, "temperatures", None)
        if temps is None:
            return None
        attr = fdb_path.split(".", 1)[1]  # "bed" or "nozzle"
        return getattr(temps, attr, None)
    return None


# ---------------------------------------------------------------------------
# Divergence context builder (for GET /conflicts/{id}/divergence-context)
# ---------------------------------------------------------------------------


async def build_divergence_context(
    conflict: Conflict,
    db: Session,
    filamentdb: FilamentDBClient,
) -> dict:
    """Return a dict describing the master + line variants for the UI.

    Shape::
        {
            "master_fdb_id": str,
            "master_name": str | None,
            "master_current_value": Any,
            "field_name": str,           # SM field name
            "fdb_path": str,             # FDB path
            "variants": [
                {
                    "fdb_id": str,
                    "name": str | None,
                    "color_hex": str | None,
                    "spoolman_filament_id": int | None,
                    "current_value": Any,
                    "inherited": bool,
                }
            ]
        }
    """
    sm_field = _sm_field_for_conflict(conflict)
    if sm_field is None:
        raise ValueError(f"Unrecognized field: {conflict.field_name!r}")

    fdb_path = _fdb_path_for_sm_field(sm_field)
    fdb_variant_id: str = conflict.filamentdb_filament_id  # type: ignore[assignment]

    variant_detail = await filamentdb.get_filament(fdb_variant_id)
    master_id: str = getattr(variant_detail, "parentId", None)  # type: ignore[assignment]
    if not master_id:
        raise ValueError(f"FDB filament {fdb_variant_id} has no parentId")

    master_detail = await filamentdb.get_filament(master_id)
    master_name = getattr(master_detail, "name", None)
    master_current_value = _get_fdb_field_value(master_detail, sm_field)

    # variants is list[FDBVariantRef] (Pydantic objects with .id attribute).
    raw_variants = getattr(master_detail, "variants", None) or []
    variant_ids: list[str] = [
        v.id if hasattr(v, "id") else str(v)
        for v in raw_variants
    ]

    variants_out = []
    for vid in variant_ids:
        try:
            vd = await filamentdb.get_filament(vid)
            # Use the Pydantic field name (alias _inherited → inherited_fields)
            inherited_list = list(getattr(vd, "inherited_fields", None) or [])
            leaf = fdb_path.split(".")[-1]
            is_inherited = fdb_path in inherited_list or leaf in inherited_list
            cur_val = _get_fdb_field_value(vd, sm_field)
            color_hex = getattr(vd, "color", None)
            sm_fil_id = _find_sm_filament_id_for_fdb(vid, db)
            variants_out.append({
                "fdb_id": vid,
                "name": getattr(vd, "name", None),
                "color_hex": color_hex,
                "spoolman_filament_id": sm_fil_id,
                "current_value": cur_val,
                "inherited": is_inherited,
            })
        except Exception as exc:
            logger.warning("build_divergence_context: could not fetch FDB variant %s: %s", vid, exc)
            variants_out.append({
                "fdb_id": vid,
                "name": None,
                "color_hex": None,
                "spoolman_filament_id": _find_sm_filament_id_for_fdb(vid, db),
                "current_value": None,
                "inherited": True,
            })

    return {
        "master_fdb_id": master_id,
        "master_name": master_name,
        "master_current_value": master_current_value,
        "field_name": sm_field,
        "fdb_path": fdb_path,
        "variants": variants_out,
    }
