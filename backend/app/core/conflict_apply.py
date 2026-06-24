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
from app.core.fields import OPENTAG_EXTRA_FIELDS
from app.core.weight_ops import apply_absolute_weight
from app.models.conflict import Conflict
from app.models.mapping import FilamentMapping
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


async def apply_lifecycle_conflict(
    conflict: Conflict,
    resolution: str,
    db: Session,
    spoolman: SpoolmanClient,
    filamentdb: FilamentDBClient,
) -> None:
    """Apply a human-chosen resolution for a boolean archive/retire lifecycle conflict.

    Lifecycle conflicts are ``cross_system`` conflicts with ``field_name == "lifecycle"``.
    Unlike other ``cross_system`` conflicts (which resolve record-only), the user's choice
    here is a concrete boolean state that we converge by writing it to BOTH systems, then
    refreshing both spool snapshots so the engine does not re-queue the conflict next cycle.

    ``resolution``:
      - "spoolman"   → adopt the Spoolman archived state on both sides.
      - "filamentdb" → adopt the Filament DB retired state on both sides.
      - "manual"     → adopt the explicit boolean stored in ``conflict.resolved_value``
                       (already set by the caller before this is invoked).

    Raises on upstream failure (caller leaves the conflict open).
    """
    spoolman_archived = bool(_decode(conflict.spoolman_value))
    fdb_retired = bool(_decode(conflict.filamentdb_value))

    if resolution == "spoolman":
        target = spoolman_archived
    elif resolution == "filamentdb":
        target = fdb_retired
    else:  # manual — explicit boolean recorded on the row
        target = bool(_decode(conflict.resolved_value))

    sm_spool_id: int = conflict.spoolman_id  # type: ignore[assignment]
    fdb_filament_id: str = conflict.filamentdb_filament_id  # type: ignore[assignment]
    fdb_spool_id: str = conflict.filamentdb_spool_id  # type: ignore[assignment]

    cycle_id = f"conflict-apply-{conflict.id}-{uuid.uuid4().hex[:8]}"

    # Write the converged state to BOTH systems. Either may already match `target`;
    # the writes are idempotent.
    await spoolman.update_spool(sm_spool_id, {"archived": target})
    await filamentdb.update_spool(fdb_filament_id, fdb_spool_id, {"retired": target})

    # Refresh both snapshot lifecycle bits to the converged value (anti-ping-pong).
    _merge_snapshot(db, "spoolman", "spool", str(sm_spool_id), {"archived": target})
    _merge_snapshot(db, "filamentdb", "spool", fdb_spool_id, {"retired": target})

    _log(
        db, cycle_id, "conflict_apply", "update", "spool",
        spoolman_id=sm_spool_id,
        fdb_filament_id=fdb_filament_id,
        fdb_spool_id=fdb_spool_id,
        field_name="lifecycle",
        old_value="diverged",
        new_value=("retired/archived" if target else "live/active"),
    )

    conflict.resolution = resolution
    conflict.resolved_value = json.dumps(target)
    conflict.resolved_at = datetime.datetime.now(datetime.timezone.utc)


async def _apply_location(
    conflict: Conflict, resolution: str, manual_value: Any,
    db: Session, spoolman: SpoolmanClient, filamentdb: FilamentDBClient, cycle_id: str,
) -> Any:
    """Converge a spool ``location`` cross_system conflict to a single location NAME.

    Compare-by-name model (mirrors engine's location pass): Spoolman stores the
    location as a free-text string; Filament DB stores a ``locationId`` resolved
    (or created) from the name via ``ensure_fdb_location``.

    ``resolution``:
      - "spoolman"   → adopt the Spoolman location name on both sides.
      - "filamentdb" → adopt the Filament DB location name on both sides.
      - "manual"     → adopt ``manual_value`` (a location name string, or None/"" to clear).

    Writes the chosen name to BOTH systems (idempotent — one side may already match),
    then refreshes both spool snapshot ``location`` keys so the engine does not re-queue
    the conflict next cycle.  Raises on upstream failure (caller leaves the conflict open).
    """
    from app.core.locations import ensure_fdb_location

    name = _resolve_value(conflict, resolution, manual_value)
    # Normalise an empty string to None so a cleared location compares cleanly.
    target = name if (name is not None and str(name).strip() != "") else None

    sm_spool_id: int = conflict.spoolman_id  # type: ignore[assignment]
    fdb_filament_id: str = conflict.filamentdb_filament_id  # type: ignore[assignment]
    fdb_spool_id: str = conflict.filamentdb_spool_id  # type: ignore[assignment]

    # FDB: find-or-create the location id for the chosen name (None clears it).
    loc_id = await ensure_fdb_location(filamentdb, target) if target else None
    await filamentdb.update_spool(fdb_filament_id, fdb_spool_id, {"locationId": loc_id})
    await spoolman.update_spool(sm_spool_id, {"location": target})

    # Refresh both snapshot location names to the converged value (anti-ping-pong).
    _merge_snapshot(db, "spoolman", "spool", str(sm_spool_id), {"location": target})
    _merge_snapshot(db, "filamentdb", "spool", fdb_spool_id, {"location": target})

    _log(
        db, cycle_id, "conflict_apply", "update", "spool",
        spoolman_id=sm_spool_id,
        fdb_filament_id=fdb_filament_id,
        fdb_spool_id=fdb_spool_id,
        field_name="location",
        old_value="diverged",
        new_value=target,
    )

    _resolve_conflict_row(conflict, resolution, target, db)
    return target


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

    failed_fdb_ids: set[str] = set()
    failed_sm_ids: set[int] = set()

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
            failed_fdb_ids.add(vid)
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
            failed_sm_ids.add(sid)
            _log(
                db, cycle_id, "conflict_apply", "error", "filament",
                spoolman_id=sid, field_name=sm_field,
                error_message=str(exc),
            )

    # --- Snapshot refresh (anti-ping-pong) ---
    # Refresh snapshots for master + all variants (both sides) to agreed new_value.
    # Records whose upstream write failed are skipped: they keep their old baseline so the
    # next sync cycle re-detects and retries the write. Inherited variants (never written
    # directly) still resolve to the master's new_value via inheritance, so refreshing
    # their snapshot here is correct even though no individual write was made for them.
    fdb_ids_to_refresh = [master_id] + list(variant_ids)
    for fid in fdb_ids_to_refresh:
        if fid in failed_fdb_ids:
            continue
        _merge_snapshot(db, "filamentdb", "filament", fid, {snap_key: new_value})
    for sid in sm_ids_in_line:
        if sid in failed_sm_ids:
            continue
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


# ===========================================================================
# Generalized cross_system conflict resolution (GitHub #21)
# ---------------------------------------------------------------------------
# Resolving a cross_system conflict was previously record-only: it wrote nothing
# upstream and never advanced the snapshot baseline, so the next sync cycle
# re-detected the unchanged divergence and re-queued a fresh conflict every
# cycle.  This dispatcher generalizes the lifecycle resolve path to ALL
# cross_system field types: compute the chosen value, write it to BOTH systems
# (idempotent — one side may already match), then refresh BOTH snapshot keys to
# the converged value so the differ does not re-detect it next cycle.
#
# Each field type below MIRRORS the upstream write + conversion + snapshot key of
# the corresponding engine pass.  See backend/app/core/engine.py.
# ===========================================================================


class UnsupportedConflictField(Exception):
    """Raised when a cross_system conflict's field_name has no known apply path.

    The endpoint maps this to a 422 so a never-converging conflict is visible,
    not silently recorded.
    """


# Material-property temperature labels → (FDB temperatures attr, SM native field).
# Mirrors engine.MATERIAL_PROP_TEMP_PAIRS.  Conflict field_name is the *label*.
_TEMP_LABELS: dict[str, tuple[str, str]] = {
    "bed_temp": ("bed", "settings_bed_temp"),
    "nozzle_temp": ("nozzle", "settings_extruder_temp"),
}

# Native scalar labels → (FDB field path, SM native field).
# Mirrors engine.MATERIAL_PROP_SCALAR_PAIRS.  Conflict field_name is the *label*.
_SCALAR_LABELS: dict[str, tuple[str, str]] = {
    "material": ("type", "material"),
    "density": ("density", "density"),
    "diameter": ("diameter", "diameter"),
    "spool_weight": ("spoolWeight", "spool_weight"),
    "net_filament_weight": ("netFilamentWeight", "weight"),
}


def _resolve_value(conflict: Conflict, resolution: str, manual_value: Any) -> Any:
    """Pick the converged target value for a value-based field.

    ``spoolman``   → the value stored from the Spoolman side.
    ``filamentdb`` → the value stored from the Filament DB side.
    ``manual``     → the explicit value supplied by the caller.
    """
    if resolution == "spoolman":
        return _decode(conflict.spoolman_value)
    if resolution == "filamentdb":
        return _decode(conflict.filamentdb_value)
    return manual_value


async def apply_cross_system_conflict(
    conflict: Conflict,
    resolution: str,
    manual_value: Any,
    db: Session,
    spoolman: SpoolmanClient,
    filamentdb: FilamentDBClient,
) -> Any:
    """Converge a ``cross_system`` conflict by writing the chosen value to BOTH
    systems and refreshing BOTH snapshot keys (anti-ping-pong).

    Dispatches on ``conflict.field_name`` to the matching engine-pass write path.
    Raises :class:`UnsupportedConflictField` for an unmappable field_name (the
    endpoint maps it to 422).  Raises on any upstream write failure so the
    endpoint returns 502 and the conflict stays open with no partial snapshot
    advance.

    Returns the converged value recorded on the conflict row.
    """
    field = conflict.field_name
    cycle_id = f"conflict-apply-{conflict.id}-{uuid.uuid4().hex[:8]}"

    if field == "lifecycle":
        # Pre-record the manual boolean so apply_lifecycle_conflict can read it.
        if resolution == "manual":
            conflict.resolved_value = json.dumps(bool(manual_value))
        await apply_lifecycle_conflict(conflict, resolution, db, spoolman, filamentdb)
        return _decode(conflict.resolved_value)

    if field == "location":
        return await _apply_location(conflict, resolution, manual_value, db, spoolman, filamentdb, cycle_id)

    if field == "weight":
        return await _apply_weight(conflict, resolution, manual_value, db, spoolman, filamentdb, cycle_id)

    if field == "multicolor":
        return await _apply_multicolor(conflict, resolution, db, spoolman, filamentdb, cycle_id)

    if field == "material_tags":
        return await _apply_material_tags(conflict, resolution, db, spoolman, filamentdb, cycle_id)

    if field == "cost":
        return await _apply_cost(conflict, resolution, manual_value, db, spoolman, filamentdb, cycle_id)

    if field in _TEMP_LABELS:
        fdb_attr, sm_field = _TEMP_LABELS[field]
        return await _apply_temperature(
            conflict, resolution, manual_value, db, spoolman, filamentdb, cycle_id,
            fdb_attr=fdb_attr, sm_field=sm_field,
        )

    if field in _SCALAR_LABELS:
        fdb_path, sm_field = _SCALAR_LABELS[field]
        return await _apply_native_scalar(
            conflict, resolution, manual_value, db, spoolman, filamentdb, cycle_id,
            fdb_path=fdb_path, sm_field=sm_field,
        )

    # OpenPrintTag material-setting extras (conflict field_name == ef.label).
    opt_field = next((ef for ef in OPENTAG_EXTRA_FIELDS if ef.label == field), None)
    if opt_field is not None:
        return await _apply_opentag_field(
            conflict, resolution, manual_value, db, spoolman, filamentdb, cycle_id, opt_field,
        )

    # Dynamic FIELD_MAPPINGS extra fields: field_name is the FDB field path; the
    # SM side is a spool extra key resolved from the configured mapping.
    sm_key = _resolve_field_mapping_sm_key(field)
    if sm_key is not None:
        return await _apply_field_mapping(
            conflict, resolution, manual_value, db, spoolman, filamentdb, cycle_id,
            fdb_path=field, sm_key=sm_key,
        )

    raise UnsupportedConflictField(
        f"cross_system conflict field {field!r} has no known apply path"
    )


def _resolve_field_mapping_sm_key(fdb_path: str) -> str | None:
    """Resolve the Spoolman extra key for a dynamic FIELD_MAPPINGS FDB path.

    Mirrors engine's use of ``resolve_field_map``: an explicit ``FIELD_MAPPINGS``
    pair maps ``fdb_path → sm_key``; otherwise an auto-matched syncable field maps
    to a same-named SM extra key.  Returns None if the path is not a configured
    syncable field.
    """
    from app.config import settings as _settings
    from app.core.fields import FDB_SYNCABLE_FIELDS

    excludes = _settings.parsed_field_mapping_excludes
    explicit = _settings.parsed_field_mappings  # {fdb_path: sm_key}

    if fdb_path in explicit:
        sm_key = explicit[fdb_path]
        if fdb_path in excludes or sm_key in excludes:
            return None
        return sm_key
    if fdb_path in FDB_SYNCABLE_FIELDS and fdb_path not in excludes:
        return fdb_path  # auto-match: SM extra key == FDB field name
    return None


# ---------------------------------------------------------------------------
# Per-field apply helpers
# ---------------------------------------------------------------------------


async def _apply_weight(
    conflict: Conflict, resolution: str, manual_value: Any,
    db: Session, spoolman: SpoolmanClient, filamentdb: FilamentDBClient, cycle_id: str,
) -> float:
    """Converge a spool ``weight`` conflict to an absolute net weight on both sides.

    The converged value ``W`` is the net remaining weight (Spoolman units).
      - resolution=spoolman   → W = stored SM remaining_weight (already net).
      - resolution=filamentdb → W = stored FDB totalWeight − tare.
      - resolution=manual     → manual_value interpreted as net remaining weight.
    SM gets ``remaining_weight = W``; FDB gets ``totalWeight = W + tare`` (a direct
    write on an increase, a usage entry on a decrease — FDB can only lower via usage;
    see ``core/weight_ops.py``). Snapshots refresh to the converged values.
    """
    from app.config import settings as _settings  # noqa: F401  (kept for parity)

    sm_spool_id: int = conflict.spoolman_id  # type: ignore[assignment]
    fdb_filament_id: str = conflict.filamentdb_filament_id  # type: ignore[assignment]
    fdb_spool_id: str = conflict.filamentdb_spool_id  # type: ignore[assignment]

    # Tare = FDB filament.spoolWeight (default 200 g if missing — same as the engine).
    from app.core.weight import DEFAULT_TARE_GRAMS

    fdb_detail = await filamentdb.get_filament(fdb_filament_id)
    tare = getattr(fdb_detail, "spoolWeight", None)
    if tare is None:
        tare = DEFAULT_TARE_GRAMS

    sm_net = _decode(conflict.spoolman_value)
    fdb_gross = _decode(conflict.filamentdb_value)

    if resolution == "spoolman":
        w = float(sm_net)
    elif resolution == "filamentdb":
        w = float(fdb_gross) - float(tare)
    else:  # manual — net remaining weight in Spoolman units
        w = float(manual_value)

    # Converge both sides + dual-snapshot refresh (shared with the mobile path,
    # core/weight_ops.py).  Filament DB can only RAISE totalWeight directly; a LOWER
    # target is applied via a usage entry — so pass the current FDB gross (the
    # conflict's stored filamentdb_value) for the increase/decrease split (#28).
    w = await apply_absolute_weight(
        db, spoolman, filamentdb,
        sm_spool_id=sm_spool_id, fdb_fil_id=fdb_filament_id, fdb_spool_id=fdb_spool_id,
        net_w=w, tare=float(tare), current_fdb_gross=float(fdb_gross),
        cycle_id=cycle_id, source="conflict_apply", job_label="Conflict resolution",
        old_value="diverged",
    )
    _resolve_conflict_row(conflict, resolution, w, db)
    return w


async def _apply_cost(
    conflict: Conflict, resolution: str, manual_value: Any,
    db: Session, spoolman: SpoolmanClient, filamentdb: FilamentDBClient, cycle_id: str,
) -> Any:
    """Converge a filament ``cost`` conflict.  FDB ``cost`` / SM filament ``price``.
    Snapshot key ``_cost`` on both filament snapshots.  Mirrors engine._sync_cost.
    """
    sm_fil_id: int = conflict.spoolman_id  # type: ignore[assignment]
    fdb_fil_id: str = conflict.filamentdb_filament_id  # type: ignore[assignment]
    value = _resolve_value(conflict, resolution, manual_value)

    await filamentdb.update_filament(fdb_fil_id, {"cost": value})
    await spoolman.update_filament(sm_fil_id, {"price": value})

    _merge_snapshot(db, "spoolman", "filament", str(sm_fil_id), {"_cost": value})
    _merge_snapshot(db, "filamentdb", "filament", fdb_fil_id, {"_cost": value})

    _log(
        db, cycle_id, "conflict_apply", "update", "filament",
        spoolman_id=sm_fil_id, fdb_filament_id=fdb_fil_id,
        field_name="cost", new_value=value,
    )
    _resolve_conflict_row(conflict, resolution, value, db)
    return value


async def _apply_temperature(
    conflict: Conflict, resolution: str, manual_value: Any,
    db: Session, spoolman: SpoolmanClient, filamentdb: FilamentDBClient, cycle_id: str,
    *, fdb_attr: str, sm_field: str,
) -> Any:
    """Converge a bed/nozzle temperature conflict.  FDB ``temperatures`` object is
    read-modify-written so sibling temps survive; SM writes the native filament
    field.  Snapshot key ``_mp_<sm_field>``.  Mirrors engine._sync_material_props.
    """
    sm_fil_id: int = conflict.spoolman_id  # type: ignore[assignment]
    fdb_fil_id: str = conflict.filamentdb_filament_id  # type: ignore[assignment]
    value = _resolve_value(conflict, resolution, manual_value)
    snap_key = f"_mp_{sm_field}"

    # FDB temperatures read-modify-write (preserve siblings).
    fdb_detail = await filamentdb.get_filament(fdb_fil_id)
    temps = getattr(fdb_detail, "temperatures", None)
    temps_payload = temps.model_dump() if temps is not None else {}
    temps_payload[fdb_attr] = value
    await filamentdb.update_filament(fdb_fil_id, {"temperatures": temps_payload})

    await spoolman.update_filament(sm_fil_id, {sm_field: value})

    _merge_snapshot(db, "spoolman", "filament", str(sm_fil_id), {snap_key: value})
    _merge_snapshot(db, "filamentdb", "filament", fdb_fil_id, {snap_key: value})

    _log(
        db, cycle_id, "conflict_apply", "update", "filament",
        spoolman_id=sm_fil_id, fdb_filament_id=fdb_fil_id,
        field_name=conflict.field_name, new_value=value,
    )
    _resolve_conflict_row(conflict, resolution, value, db)
    return value


async def _apply_native_scalar(
    conflict: Conflict, resolution: str, manual_value: Any,
    db: Session, spoolman: SpoolmanClient, filamentdb: FilamentDBClient, cycle_id: str,
    *, fdb_path: str, sm_field: str,
) -> Any:
    """Converge a native scalar filament conflict (material/density/diameter/
    spool_weight/net_filament_weight).  FDB field path / SM native field (note the
    SM ``material`` ↔ FDB ``type`` and SM ``weight`` ↔ FDB ``netFilamentWeight``
    remaps).  Snapshot key ``_mp_<sm_field>``.  Mirrors engine._sync_material_scalars.
    """
    sm_fil_id: int = conflict.spoolman_id  # type: ignore[assignment]
    fdb_fil_id: str = conflict.filamentdb_filament_id  # type: ignore[assignment]
    value = _resolve_value(conflict, resolution, manual_value)
    snap_key = f"_mp_{sm_field}"

    await filamentdb.update_filament(fdb_fil_id, _make_fdb_write(fdb_path, value))
    await spoolman.update_filament(sm_fil_id, {sm_field: value})

    _merge_snapshot(db, "spoolman", "filament", str(sm_fil_id), {snap_key: value})
    _merge_snapshot(db, "filamentdb", "filament", fdb_fil_id, {snap_key: value})

    _log(
        db, cycle_id, "conflict_apply", "update", "filament",
        spoolman_id=sm_fil_id, fdb_filament_id=fdb_fil_id,
        field_name=conflict.field_name, new_value=value,
    )
    _resolve_conflict_row(conflict, resolution, value, db)
    return value


async def _apply_opentag_field(
    conflict: Conflict, resolution: str, manual_value: Any,
    db: Session, spoolman: SpoolmanClient, filamentdb: FilamentDBClient, cycle_id: str,
    opt_field: Any,
) -> Any:
    """Converge an OpenPrintTag material-setting extra conflict (one of seven).

    FDB first-class field (read-modify-write for dotted temperature paths) / SM
    TYPED extra field.  Snapshot key ``_mp_<sm_extra_key>``.
    Mirrors engine._sync_opentag_material_fields.
    """
    from app.config import settings as _settings
    from app.schemas.spoolman import encode_extra_value

    sm_fil_id: int = conflict.spoolman_id  # type: ignore[assignment]
    fdb_fil_id: str = conflict.filamentdb_filament_id  # type: ignore[assignment]
    value = _resolve_value(conflict, resolution, manual_value)

    sm_key = getattr(_settings, opt_field.config_attr)
    snap_key = f"_mp_{sm_key}"

    # FDB write — dotted temperature paths need the object read-modify-written.
    fdb_detail = await filamentdb.get_filament(fdb_fil_id)
    fdb_payload = _fdb_field_payload_rmw(fdb_detail, opt_field.fdb_path, value)
    await filamentdb.update_filament(fdb_fil_id, fdb_payload)

    await spoolman.update_filament(sm_fil_id, {"extra": {sm_key: encode_extra_value(value)}})

    _merge_snapshot(db, "spoolman", "filament", str(sm_fil_id), {snap_key: value})
    _merge_snapshot(db, "filamentdb", "filament", fdb_fil_id, {snap_key: value})

    _log(
        db, cycle_id, "conflict_apply", "update", "filament",
        spoolman_id=sm_fil_id, fdb_filament_id=fdb_fil_id,
        field_name=opt_field.label, new_value=value,
    )
    _resolve_conflict_row(conflict, resolution, value, db)
    return value


def _fdb_field_payload_rmw(fdb_detail: Any, fdb_path: str, value: Any) -> dict:
    """Build an FDB update payload, read-modify-writing dotted object paths so
    siblings survive (mirrors engine._fdb_field_payload)."""
    parts = fdb_path.split(".", 1)
    if len(parts) == 1:
        return {fdb_path: value}
    obj_name, attr = parts
    current = getattr(fdb_detail, obj_name, None)
    obj_payload = current.model_dump() if current is not None else {}
    obj_payload[attr] = value
    return {obj_name: obj_payload}


async def _apply_field_mapping(
    conflict: Conflict, resolution: str, manual_value: Any,
    db: Session, spoolman: SpoolmanClient, filamentdb: FilamentDBClient, cycle_id: str,
    *, fdb_path: str, sm_key: str,
) -> Any:
    """Converge a dynamic FIELD_MAPPINGS conflict (generic SM spool extra ↔ FDB
    filament field).  The conflict's ``spoolman_id`` is the SM SPOOL id; the FDB
    spool id is resolved from SpoolMapping for the snapshot refresh.  Mirrors
    engine._apply_field_changes + its spool-snapshot baselines.
    """
    from app.core.color import to_fdb_color, to_sm_color
    from app.models.mapping import SpoolMapping
    from app.schemas.spoolman import encode_extra_value

    sm_spool_id: int = conflict.spoolman_id  # type: ignore[assignment]
    fdb_fil_id: str = conflict.filamentdb_filament_id  # type: ignore[assignment]
    value = _resolve_value(conflict, resolution, manual_value)

    # FDB write — single PUT for a (possibly dotted) field; `color` is normalized.
    if fdb_path == "color":
        fdb_value = to_fdb_color(value)
        sm_value = to_sm_color(value)
    else:
        fdb_value = value
        sm_value = value
    await filamentdb.update_filament(fdb_fil_id, _make_fdb_write(fdb_path, fdb_value))

    # SM write — the mapped extra on the SPOOL.
    await spoolman.update_spool(sm_spool_id, {"extra": {sm_key: encode_extra_value(sm_value)}})

    # Snapshot refresh — baselines live on the SPOOL snapshots under nested keys.
    mapping = (
        db.query(SpoolMapping)
        .filter(SpoolMapping.spoolman_spool_id == sm_spool_id)
        .first()
    )
    _merge_nested_snapshot(db, "spoolman", "spool", str(sm_spool_id), "_extra_decoded", sm_key, sm_value)
    if mapping is not None:
        _merge_nested_snapshot(
            db, "filamentdb", "spool", mapping.filamentdb_spool_id, "_field_values", fdb_path, fdb_value
        )

    _log(
        db, cycle_id, "conflict_apply", "update", "filament",
        spoolman_id=sm_spool_id, fdb_filament_id=fdb_fil_id,
        field_name=fdb_path, new_value=value,
    )
    _resolve_conflict_row(conflict, resolution, value, db)
    return value


def _merge_nested_snapshot(
    db: Session, source: str, entity_type: str, entity_id: str,
    container_key: str, leaf_key: str, value: Any,
) -> None:
    """Merge ``{leaf_key: value}`` into a nested dict ``container_key`` of a snapshot,
    preserving the container's other keys (and the snapshot's other top-level keys)."""
    from app.core.engine import _get_snapshot
    existing = _get_snapshot(db, source, entity_type, entity_id) or {}
    container = dict(existing.get(container_key) or {})
    container[leaf_key] = value
    _merge_snapshot(db, source, entity_type, entity_id, {container_key: container})


async def _apply_multicolor(
    conflict: Conflict, resolution: str,
    db: Session, spoolman: SpoolmanClient, filamentdb: FilamentDBClient, cycle_id: str,
) -> Any:
    """Converge a multicolor conflict by adopting the chosen side's LIVE color state
    on both systems.  The conflict stores signatures (not raw values), so the write
    payload is re-derived from live data via core/color (mirrors engine._sync_multicolor).

    Only ``spoolman`` / ``filamentdb`` are supported — a multicolor state has no
    single scalar ``manual`` representation, so ``manual`` raises 422.
    """
    from app.core.color import (
        fdb_multicolor_to_sm,
        multicolor_signature,
        sm_multicolor_signature,
        sm_multicolor_to_fdb,
    )

    if resolution == "manual":
        raise UnsupportedConflictField(
            "multicolor conflicts cannot be resolved manually — choose spoolman or filamentdb"
        )

    sm_fil_id: int = conflict.spoolman_id  # type: ignore[assignment]
    fdb_fil_id: str = conflict.filamentdb_filament_id  # type: ignore[assignment]

    sm_fil = await spoolman.get_filament(sm_fil_id)
    fdb_detail = await filamentdb.get_filament(fdb_fil_id)

    if resolution == "spoolman":
        # Adopt SM color state → write to FDB; SM already holds it.
        mc = sm_multicolor_to_fdb(
            sm_fil.color_hex, sm_fil.multi_color_hexes, sm_fil.multi_color_direction,
            existing_opt_tags=fdb_detail.optTags,
        )
        await filamentdb.update_filament(fdb_fil_id, {
            "color": mc["color"], "secondaryColors": mc["secondaryColors"], "optTags": mc["optTags"],
        })
        sig = sm_multicolor_signature(
            sm_fil.color_hex, sm_fil.multi_color_hexes, sm_fil.multi_color_direction
        )
        recorded = sig
    else:  # filamentdb
        sm = fdb_multicolor_to_sm(fdb_detail.color, fdb_detail.secondaryColors, fdb_detail.optTags)
        sm_payload: dict = {}
        if sm["color_hex"] is not None:
            sm_payload["color_hex"] = sm["color_hex"]
        if sm["multi_color_hexes"] is not None:
            sm_payload["multi_color_hexes"] = sm["multi_color_hexes"]
        if sm["multi_color_direction"] is not None:
            sm_payload["multi_color_direction"] = sm["multi_color_direction"]
        await spoolman.update_filament(sm_fil_id, sm_payload)
        sig = multicolor_signature(fdb_detail.color, fdb_detail.secondaryColors, fdb_detail.optTags)
        recorded = sig

    _merge_snapshot(db, "spoolman", "filament", str(sm_fil_id), {"_mc_sig": sig})
    _merge_snapshot(db, "filamentdb", "filament", fdb_fil_id, {"_mc_sig": sig})

    _log(
        db, cycle_id, "conflict_apply", "update", "filament",
        spoolman_id=sm_fil_id, fdb_filament_id=fdb_fil_id,
        field_name="multicolor", new_value=sig,
    )
    _resolve_conflict_row(conflict, resolution, recorded, db)
    return recorded


async def _apply_material_tags(
    conflict: Conflict, resolution: str,
    db: Session, spoolman: SpoolmanClient, filamentdb: FilamentDBClient, cycle_id: str,
) -> Any:
    """Converge a material_tags (finish-tag) conflict by adopting the chosen side's
    LIVE finish-tag set on both systems.  The conflict stores signatures, so the
    write payload is re-derived from live data (mirrors engine._sync_finish_tags).

    SM extra ``filamentdb_material_tags`` (CSV of ints) / FDB ``optTags`` (managed
    finish subset merged, arrangement + unknown tags preserved).  ``manual`` is
    unsupported (the value is a tag set, not a scalar) → 422.
    """
    from app.config import settings as _settings
    from app.core.color import apply_finish_tags
    from app.core.material_tags import (
        MANAGED_FINISH_IDS,
        finish_ids_from_text,
        parse_material_tags,
        serialize_material_tags,
    )
    from app.schemas.spoolman import decode_extra_value, encode_extra_value

    if resolution == "manual":
        raise UnsupportedConflictField(
            "material_tags conflicts cannot be resolved manually — choose spoolman or filamentdb"
        )

    sm_fil_id: int = conflict.spoolman_id  # type: ignore[assignment]
    fdb_fil_id: str = conflict.filamentdb_filament_id  # type: ignore[assignment]
    mt_field = _settings.spoolman_field_filamentdb_material_tags
    tag_map = _settings.parsed_material_tag_ids

    sm_fil = await spoolman.get_filament(sm_fil_id)
    fdb_detail = await filamentdb.get_filament(fdb_fil_id)

    def _fdb_ids(opt_tags: list | None) -> frozenset[int]:
        out: set[int] = set()
        for t in opt_tags or []:
            try:
                ti = int(t)
            except (TypeError, ValueError):
                continue
            if ti in MANAGED_FINISH_IDS:
                out.add(ti)
        return frozenset(out)

    def _sm_ids() -> frozenset[int]:
        raw = sm_fil.extra.get(mt_field) if hasattr(sm_fil, "extra") else None
        if raw is not None:
            ids = parse_material_tags(decode_extra_value(raw))
            return frozenset(set(ids) & MANAGED_FINISH_IDS)
        return frozenset(
            finish_ids_from_text(getattr(sm_fil, "name", None), getattr(sm_fil, "material", None), tag_map)
        )

    if resolution == "spoolman":
        ids = _sm_ids()
    else:  # filamentdb
        ids = _fdb_ids(fdb_detail.optTags)

    # Write the chosen ID set to BOTH sides (idempotent).
    new_opt_tags = apply_finish_tags(fdb_detail.optTags, ids)
    await filamentdb.update_filament(fdb_fil_id, {"optTags": new_opt_tags})
    encoded = encode_extra_value(serialize_material_tags(ids))
    await spoolman.update_filament(sm_fil_id, {"extra": {mt_field: encoded}})

    sig = ",".join(str(i) for i in sorted(ids))
    _merge_snapshot(db, "spoolman", "filament", str(sm_fil_id), {"_finish_sig": sig})
    _merge_snapshot(db, "filamentdb", "filament", fdb_fil_id, {"_finish_sig": sig})

    _log(
        db, cycle_id, "conflict_apply", "update", "filament",
        spoolman_id=sm_fil_id, fdb_filament_id=fdb_fil_id,
        field_name="material_tags", new_value=sig,
    )
    _resolve_conflict_row(conflict, resolution, sig, db)
    return sig


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
