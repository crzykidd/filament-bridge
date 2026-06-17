"""Sync engine — FR-8 through FR-14.

Entry point: run_sync_cycle(db, spoolman, filamentdb, *, dry_run, cycle_id)

Design note (see decisions.md): the cycle is a single async def that awaits
client I/O and calls sync SQLAlchemy code inline — no thread, no second sync
HTTP client.  SQLite writes are microseconds; the brief loop stall is harmless
for a single-container homelab service.
"""

from __future__ import annotations

import datetime
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.config import settings as _settings
from app.core.color import (
    apply_finish_tags,
    arrangement_from_tags,
    fdb_multicolor_to_sm,
    multicolor_signature,
    sm_multicolor_signature,
    sm_multicolor_to_fdb,
    to_fdb_color,
    to_sm_color,
)
from app.core.dates import spool_provenance_dates
from app.core.differ import diff_spool_pair
from app.core.fields import FieldMapping, get_fdb_field_value, resolve_effective_cost, resolve_field_map, should_skip_inherited
from app.core.material_tags import MANAGED_FINISH_IDS, finish_ids_from_text, parse_material_tags, serialize_material_tags
from app.core.sync_policy import SyncAction, resolve_sync_action
from app.core.version import MULTICOLOR_MIN_FDB, incompatibilities, version_gte
from app.core.weight import fdb_to_spoolman_net, spoolman_to_fdb_gross
from app.models.config import BridgeConfig
from app.models.conflict import DELETION_FIELD, Conflict
from app.models.mapping import FilamentMapping, SpoolMapping
from app.models.snapshot import Snapshot
from app.models.sync_log import SyncLog
from app.schemas.spoolman import SpoolmanSpool, decode_extra_value, encode_extra_value
from app.schemas.filamentdb import FDBFilament, FDBSpool
from app.services.filamentdb import FilamentDBClient, extract_created_spool_id
from app.services.spoolman import SpoolmanClient

logger = logging.getLogger(__name__)


@dataclass
class CycleResult:
    cycle_id: str
    dry_run: bool
    created: int = 0
    updated: int = 0
    conflicts: int = 0
    skipped: int = 0
    errors: int = 0
    preview: list[dict] = field(default_factory=list)
    # Non-empty when the cycle was refused because an upstream version is below
    # the minimum supported (see core/version.py:incompatibilities). No writes happen.
    blocked_reasons: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal DB helpers
# ---------------------------------------------------------------------------


def _read_config(db: Session) -> dict[str, Any]:
    rows = db.query(BridgeConfig).all()
    return {r.key: json.loads(r.value) for r in rows}


def _parse_iso(ts_str: Any) -> datetime.datetime | None:
    """Parse an ISO-8601 timestamp string to a timezone-aware datetime, or None."""
    if not ts_str:
        return None
    try:
        dt = datetime.datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _get_snapshot(db: Session, source: str, entity_type: str, entity_id: str) -> dict | None:
    row = (
        db.query(Snapshot)
        .filter_by(source=source, entity_type=entity_type, entity_id=entity_id)
        .first()
    )
    return json.loads(row.data) if row else None


def _get_snapshot_captured_at(db: Session, source: str, entity_type: str, entity_id: str) -> datetime.datetime | None:
    """Return the captured_at of an existing snapshot, or None if absent."""
    row = (
        db.query(Snapshot)
        .filter_by(source=source, entity_type=entity_type, entity_id=entity_id)
        .first()
    )
    if row is None or row.captured_at is None:
        return None
    ca = row.captured_at
    if isinstance(ca, str):
        return _parse_iso(ca)
    if isinstance(ca, datetime.datetime):
        if ca.tzinfo is None:
            return ca.replace(tzinfo=datetime.timezone.utc)
        return ca
    return None


def _upsert_snapshot(db: Session, source: str, entity_type: str, entity_id: str, data: dict) -> None:
    data_json = json.dumps(data)
    stmt = (
        sqlite_insert(Snapshot)
        .values(source=source, entity_type=entity_type, entity_id=entity_id, data=data_json)
        .on_conflict_do_update(
            index_elements=["source", "entity_type", "entity_id"],
            set_={"data": data_json, "captured_at": func.now()},
        )
    )
    db.execute(stmt)


def _merge_snapshot(db: Session, source: str, entity_type: str, entity_id: str, updates: dict) -> None:
    """Merge key-value pairs into an existing filament snapshot, preserving other keys.

    Used by the multicolor and cost passes to store their respective keys
    (_mc_sig, _cost) without clobbering each other's data in the shared
    filament-level snapshot row.
    """
    existing = _get_snapshot(db, source, entity_type, entity_id) or {}
    merged = {**existing, **updates}
    _upsert_snapshot(db, source, entity_type, entity_id, merged)


def _log(
    db: Session,
    cycle_id: str,
    direction: str,
    action: str,
    entity_type: str,
    *,
    spoolman_id: int | None = None,
    fdb_filament_id: str | None = None,
    fdb_spool_id: str | None = None,
    field_name: str | None = None,
    old_value: Any = None,
    new_value: Any = None,
    error_message: str | None = None,
) -> None:
    db.add(
        SyncLog(
            cycle_id=cycle_id,
            direction=direction,
            action=action,
            entity_type=entity_type,
            spoolman_id=spoolman_id,
            filamentdb_filament_id=fdb_filament_id,
            filamentdb_spool_id=fdb_spool_id,
            field_name=field_name,
            old_value=json.dumps(old_value) if old_value is not None else None,
            new_value=json.dumps(new_value) if new_value is not None else None,
            error_message=error_message,
        )
    )
    # Mirror mutations to the durable changes.log file sink.
    # record_change filters non-mutations (skip/info/conflict/error) internally.
    from app.core.change_log import record_change
    record_change(
        action=action,
        direction=direction,
        entity_type=entity_type,
        spoolman_id=spoolman_id,
        fdb_filament_id=fdb_filament_id,
        fdb_spool_id=fdb_spool_id,
        field_name=field_name,
        old_value=old_value,
        new_value=new_value,
        cycle_id=cycle_id,
    )


def _queue_conflict(
    db: Session,
    cycle_id: str,
    entity_type: str,
    field_name: str,
    *,
    spoolman_id: int | None = None,
    fdb_filament_id: str | None = None,
    fdb_spool_id: str | None = None,
    spoolman_value: Any = None,
    filamentdb_value: Any = None,
    conflict_type: str = "cross_system",
) -> None:
    db.add(
        Conflict(
            entity_type=entity_type,
            spoolman_id=spoolman_id,
            filamentdb_filament_id=fdb_filament_id,
            filamentdb_spool_id=fdb_spool_id,
            field_name=field_name,
            spoolman_value=json.dumps(spoolman_value) if spoolman_value is not None else None,
            filamentdb_value=json.dumps(filamentdb_value) if filamentdb_value is not None else None,
            conflict_type=conflict_type,
        )
    )
    _log(
        db, cycle_id, "conflict", "conflict", entity_type,
        spoolman_id=spoolman_id,
        fdb_filament_id=fdb_filament_id,
        fdb_spool_id=fdb_spool_id,
        field_name=field_name,
        old_value=spoolman_value,
        new_value=filamentdb_value,
    )


def _queue_deletion_conflict(
    db: Session,
    cycle_id: str,
    mapping: SpoolMapping,
    *,
    deleted_side: str,  # "spoolman" | "filamentdb"
) -> None:
    """Queue a deletion conflict for an orphaned spool mapping, with dedup.

    The surviving side carries a descriptor; the deleted side is null.
    """
    exists = (
        db.query(Conflict)
        .filter(
            Conflict.resolved_at.is_(None),
            Conflict.field_name == DELETION_FIELD,
            Conflict.spoolman_id == mapping.spoolman_spool_id,
            Conflict.filamentdb_spool_id == mapping.filamentdb_spool_id,
        )
        .first()
    )
    if exists:
        return

    descriptor = json.dumps({"exists": True, "deleted_side": deleted_side})
    db.add(
        Conflict(
            entity_type="spool",
            spoolman_id=mapping.spoolman_spool_id,
            filamentdb_filament_id=mapping.filamentdb_filament_id,
            filamentdb_spool_id=mapping.filamentdb_spool_id,
            field_name=DELETION_FIELD,
            spoolman_value=descriptor if deleted_side == "filamentdb" else None,
            filamentdb_value=descriptor if deleted_side == "spoolman" else None,
        )
    )
    _log(
        db, cycle_id, "conflict", "conflict", "spool",
        spoolman_id=mapping.spoolman_spool_id,
        fdb_filament_id=mapping.filamentdb_filament_id,
        fdb_spool_id=mapping.filamentdb_spool_id,
        error_message=f"upstream record deleted ({deleted_side})",
    )


def _purge_stale_mapping(
    db: Session,
    cycle_id: str,
    mapping: SpoolMapping,
    *,
    reason: str,
) -> None:
    """Purge a stale bridge-local SpoolMapping + its Snapshots and auto-resolve
    any open deletion conflict for it.

    Called when BOTH sides are gone OR when FDB is gone and the surviving
    Spoolman spool no longer carries the filamentdb_spool_id cross-reference
    (user cleared it / unlinked).  In both cases there is no live, still-linked
    counterpart to protect so no deletion conflict is warranted — the bridge
    just silently drops its own bookkeeping rows.

    Bridge-local rows ONLY — never deletes upstream records.
    """
    # Delete spool-level Snapshots (mirror _cleanup_orphaned_mapping in conflicts.py).
    db.query(Snapshot).filter_by(
        source="spoolman", entity_type="spool", entity_id=str(mapping.spoolman_spool_id)
    ).delete()
    db.query(Snapshot).filter_by(
        source="filamentdb", entity_type="spool", entity_id=mapping.filamentdb_spool_id
    ).delete()

    # Auto-resolve any open __record_deleted__ conflict for this mapping so the
    # open-conflict queue doesn't accumulate stale entries from previous cycles.
    now = datetime.datetime.now(datetime.timezone.utc)
    stale_conflicts = (
        db.query(Conflict)
        .filter(
            Conflict.resolved_at.is_(None),
            Conflict.field_name == DELETION_FIELD,
            Conflict.spoolman_id == mapping.spoolman_spool_id,
            Conflict.filamentdb_spool_id == mapping.filamentdb_spool_id,
        )
        .all()
    )
    for c in stale_conflicts:
        c.resolved_at = now
        c.resolution = "auto_stale_purge"

    # Delete the SpoolMapping row itself.
    db.delete(mapping)

    # Emit an audit log entry.
    _log(
        db, cycle_id, "auto", "info", "spool",
        spoolman_id=mapping.spoolman_spool_id,
        fdb_filament_id=mapping.filamentdb_filament_id,
        fdb_spool_id=mapping.filamentdb_spool_id,
        error_message=reason,
    )


# ---------------------------------------------------------------------------
# Conflict dedup helper
# ---------------------------------------------------------------------------


def _has_open_conflict(
    db: Session,
    entity_type: str,
    field_name: str,
    *,
    spoolman_id: int | None = None,
    fdb_filament_id: str | None = None,
    fdb_spool_id: str | None = None,
    conflict_type: str | None = None,
) -> bool:
    """Return True if there is already an open (unresolved) conflict for this combination.

    Used by all passes to prevent re-queuing the same conflict every sync cycle
    when a both-changed pair cannot be auto-resolved (policy=manual or newest_wins
    fallback).  Mirrors the existing deletion-conflict dedup in
    ``_queue_deletion_conflict``.

    When ``conflict_type`` is provided, the check is scoped to conflicts of that
    type only — so a ``cross_system`` and a ``master_divergence`` conflict on the
    same field+ids are treated as distinct and deduped independently.
    """
    q = (
        db.query(Conflict)
        .filter(
            Conflict.resolved_at.is_(None),
            Conflict.entity_type == entity_type,
            Conflict.field_name == field_name,
        )
    )
    if spoolman_id is not None:
        q = q.filter(Conflict.spoolman_id == spoolman_id)
    if fdb_filament_id is not None:
        q = q.filter(Conflict.filamentdb_filament_id == fdb_filament_id)
    if fdb_spool_id is not None:
        q = q.filter(Conflict.filamentdb_spool_id == fdb_spool_id)
    if conflict_type is not None:
        q = q.filter(Conflict.conflict_type == conflict_type)
    return q.first() is not None


# ---------------------------------------------------------------------------
# Timestamp helpers for newest_wins
# ---------------------------------------------------------------------------


def _ts_after_captured_at(ts: datetime.datetime | None, captured_at: datetime.datetime | None) -> datetime.datetime | None:
    """Return ts only if it is strictly after captured_at; otherwise None.

    This anchors newest_wins to the bridge's last-sync time so a stale timestamp
    on one side cannot win against a fresh change on the other.  If captured_at
    is unknown (None), any timestamp is considered valid (first sync).
    """
    if ts is None:
        return None
    if captured_at is None:
        return ts
    return ts if ts > captured_at else None


# ---------------------------------------------------------------------------
# Dry-run preview helpers
# ---------------------------------------------------------------------------


def _preview_label(
    *,
    sm_spool: SpoolmanSpool | None = None,
    fdb_filament: FDBFilament | None = None,
) -> str:
    """Build a human-readable label for a dry-run preview entry.

    Degrades gracefully to IDs when names are unavailable.
    """
    if sm_spool is not None:
        fil = sm_spool.filament
        vendor = fil.vendor.name if fil.vendor else ""
        base = " ".join(p for p in [vendor, fil.name, fil.color_hex] if p)
        base = base or f"SM #{sm_spool.id}"
        fdb_part = fdb_filament.name if fdb_filament else ""
        suffix = f" / FDB {fdb_part}" if fdb_part else ""
        return f"{base} (SM #{sm_spool.id}){suffix}"
    if fdb_filament is not None:
        return fdb_filament.name or f"FDB {fdb_filament.id}"
    return "unknown"


# ---------------------------------------------------------------------------
# Field-mapping snapshot helpers
# ---------------------------------------------------------------------------


def _sm_snapshot_dict(
    spool: SpoolmanSpool,
    field_maps: list[FieldMapping],
) -> dict:
    """Build the snapshot dict for a Spoolman spool including decoded extra values."""
    d = spool.model_dump()
    if field_maps:
        d["_extra_decoded"] = {
            fm.sm_key: decode_extra_value(spool.extra.get(fm.sm_key))
            for fm in field_maps
        }
    return d


def _refresh_lifecycle_snapshots(
    db: Session, sm_spool_id: int, fdb_spool_id: str, sm_archived: bool, fdb_retired: bool
) -> None:
    """Converge BOTH lifecycle bits to the agreed value (anti-ping-pong).

    Merges (not full upsert) so the weight / field baselines the weight + field passes
    already wrote in this cycle are preserved.  Same both-sides-refresh rule the weight
    pass uses — see the 2026-06-10 weight ping-pong decision in docs/decisions.md.
    """
    _merge_snapshot(db, "spoolman", "spool", str(sm_spool_id), {"archived": sm_archived})
    _merge_snapshot(db, "filamentdb", "spool", fdb_spool_id, {"retired": fdb_retired})


def _fdb_snapshot_dict(spool: FDBSpool, filament_detail=None, field_maps: list[FieldMapping] | None = None) -> dict:
    """Build the snapshot dict for a FDB spool.  If filament_detail and field_maps
    are provided the mapped FDB field values are embedded under _field_values so the
    differ can compare them next cycle without re-fetching the detail view.
    """
    d = spool.model_dump()
    if filament_detail and field_maps:
        d["_field_values"] = {
            fm.fdb_path: get_fdb_field_value(filament_detail, fm.fdb_path)
            for fm in field_maps
        }
    return d


# ---------------------------------------------------------------------------
# Field-mapping sync helper (FR-11)
# ---------------------------------------------------------------------------


async def _apply_field_changes(
    db: Session,
    cycle_id: str,
    result: CycleResult,
    dry_run: bool,
    sm_spool: SpoolmanSpool,
    fdb_filament_id: str,
    fdb_spool_id: str,
    field_maps: list[FieldMapping],
    spoolman: SpoolmanClient,
    filamentdb: FilamentDBClient,
    sm_snapshot: dict,
    fdb_snapshot: dict,
    *,
    matprop_direction: str = "filamentdb_to_spoolman",
    matprop_policy: str = "manual",
) -> tuple[dict, dict] | None:
    """Evaluate and apply field-mapping changes for one spool pair (FR-11).

    Routes each field through ``resolve_sync_action`` using the material_properties
    direction and conflict policy.  Per-field conflict dedup prevents re-queuing
    on every cycle.

    Returns ``(fdb_field_values_after, sm_extra_decoded_after)`` — the FDB and SM
    field values as they stand *after* any writes this call made.  The caller
    should merge these into the respective spool snapshots so the next cycle sees
    the correct baseline and does not re-detect the same values as changes.
    Returns ``None`` if the FDB detail fetch fails (error already logged).
    """
    # Fetch FDB detail (needed for _inherited[] and full field surface)
    try:
        fdb_detail = await filamentdb.get_filament(fdb_filament_id)
    except Exception as exc:
        logger.error("Cycle %s: could not fetch FDB filament detail %s: %s", cycle_id, fdb_filament_id, exc)
        result.errors += 1
        return None

    # Multicolor filaments: the dedicated multicolor pass owns ``color`` (plus
    # secondaryColors/optTags), so exclude it from the generic field-map sync to
    # avoid the two paths fighting over the same field.
    is_multicolor = (
        bool(sm_spool.filament.multi_color_hexes)
        or bool(fdb_detail.secondaryColors)
        or arrangement_from_tags(fdb_detail.optTags) != "solid"
    )

    sm_extra_decoded = {
        fm.sm_key: decode_extra_value(sm_spool.extra.get(fm.sm_key))
        for fm in field_maps
    }
    fdb_field_values = {
        fm.fdb_path: get_fdb_field_value(fdb_detail, fm.fdb_path)
        for fm in field_maps
    }

    cs = diff_spool_pair(
        sm_spool=sm_spool,
        fdb_spool=FDBSpool(
            **{
                "_id": fdb_spool_id,
                "totalWeight": fdb_snapshot.get("totalWeight"),
                "retired": fdb_snapshot.get("retired", False),
                "label": fdb_snapshot.get("label"),
            }
        ),
        fdb_filament_id=fdb_filament_id,
        sm_snapshot=sm_snapshot,
        fdb_snapshot=fdb_snapshot,
        threshold=0.0,  # fields aren't numeric thresholds
        field_maps=field_maps,
        sm_extra_decoded=sm_extra_decoded,
        fdb_field_values=fdb_field_values,
    )

    if is_multicolor:
        cs.field_conflicts = [f for f in cs.field_conflicts if f != "color"]
        cs.sm_field_changes = [fc for fc in cs.sm_field_changes if fc.field_name != "color"]
        cs.fdb_field_changes = [fc for fc in cs.fdb_field_changes if fc.field_name != "color"]

    # Build a quick lookup: fdb_path → sm_key
    _fm_by_fdb: dict[str, FieldMapping] = {fm.fdb_path: fm for fm in field_maps}

    # Unified per-field processing via the resolver.
    # For each field we determine sm_changed/fdb_changed from the differ output,
    # then call resolve_sync_action with the material_properties category settings.

    # Collect all field names referenced by any change or conflict
    all_field_names: set[str] = (
        set(cs.field_conflicts)
        | {fc.field_name for fc in cs.sm_field_changes}
        | {fc.field_name for fc in cs.fdb_field_changes}
    )

    # Build maps for quick lookup
    sm_changes_by_field = {fc.field_name: fc for fc in cs.sm_field_changes}
    fdb_changes_by_field = {fc.field_name: fc for fc in cs.fdb_field_changes}

    # Collect SM→FDB writes to batch into a single PUT
    fdb_put_payload: dict = {}
    fdb_put_field_changes: list = []
    sm_skipped_fields: set[str] = set()

    for fdb_path in all_field_names:
        fm = _fm_by_fdb.get(fdb_path)
        if fm is None:
            continue

        sm_fc = sm_changes_by_field.get(fdb_path)
        fdb_fc = fdb_changes_by_field.get(fdb_path)
        sm_changed_field = fdb_path in cs.field_conflicts or sm_fc is not None
        fdb_changed_field = fdb_path in cs.field_conflicts or fdb_fc is not None

        action = resolve_sync_action(
            sm_changed=sm_changed_field,
            fdb_changed=fdb_changed_field,
            direction=matprop_direction,
            policy=matprop_policy,
        )

        if action == SyncAction.NOOP:
            continue

        if action == SyncAction.QUEUE_CONFLICT:
            sm_val = sm_extra_decoded.get(fm.sm_key)
            fdb_val = fdb_field_values.get(fdb_path)
            if not dry_run:
                if not _has_open_conflict(
                    db, "filament", fdb_path,
                    spoolman_id=sm_spool.id,
                    fdb_filament_id=fdb_filament_id,
                ):
                    _queue_conflict(
                        db, cycle_id, "filament", fdb_path,
                        spoolman_id=sm_spool.id,
                        fdb_filament_id=fdb_filament_id,
                        spoolman_value=sm_val,
                        filamentdb_value=fdb_val,
                    )
                    result.conflicts += 1
                # If already open — dedup, skip
            else:
                result.preview.append({
                    "action": "conflict",
                    "entity_type": "filament",
                    "direction": None,
                    "label": _preview_label(sm_spool=sm_spool, fdb_filament=fdb_detail),
                    "field": fdb_path,
                    "old": sm_val, "new": fdb_val,
                    "reason": "both sides changed",
                    "spoolman_id": sm_spool.id,
                    "fdb_filament_id": fdb_filament_id,
                    "fdb_spool_id": fdb_spool_id,
                })
                result.conflicts += 1
            continue

        if action == SyncAction.PUSH_FDB_TO_SM:
            fc = fdb_fc
            if fc is None:
                # Conflict resolved as FDB-wins but fdb_fc not in fdb_field_changes —
                # shouldn't happen, but guard defensively.
                continue
            if should_skip_inherited(fdb_detail, fdb_path):
                logger.info(
                    "Cycle %s: skipping inherited field %s on FDB filament %s",
                    cycle_id, fdb_path, fdb_filament_id,
                )
                if dry_run:
                    result.preview.append({
                        "action": "skip",
                        "entity_type": "filament",
                        "direction": "filamentdb_to_spoolman",
                        "label": _preview_label(sm_spool=sm_spool, fdb_filament=fdb_detail),
                        "field": fdb_path,
                        "old": None, "new": None,
                        "reason": "inherited from parent",
                        "spoolman_id": sm_spool.id,
                        "fdb_filament_id": fdb_filament_id,
                        "fdb_spool_id": fdb_spool_id,
                    })
                result.skipped += 1
                continue
            if not dry_run:
                try:
                    write_value = to_sm_color(fc.new_value) if fdb_path == "color" else fc.new_value
                    encoded = encode_extra_value(write_value)
                    await spoolman.update_spool(
                        sm_spool.id, {"extra": {fm.sm_key: encoded}}
                    )
                    _log(
                        db, cycle_id, "filamentdb_to_spoolman", "update", "filament",
                        spoolman_id=sm_spool.id, fdb_filament_id=fdb_filament_id,
                        field_name=fdb_path, old_value=fc.old_value, new_value=fc.new_value,
                    )
                    result.updated += 1
                    # Anti-ping-pong: record the written value so the next cycle
                    # sees it as the baseline and does not re-detect it.
                    sm_extra_decoded[fm.sm_key] = write_value
                except Exception as exc:
                    logger.error("Cycle %s: field sync FDB→SM failed (%s): %s", cycle_id, fdb_path, exc)
                    _log(
                        db, cycle_id, "filamentdb_to_spoolman", "error", "filament",
                        spoolman_id=sm_spool.id, fdb_filament_id=fdb_filament_id,
                        field_name=fdb_path, error_message=str(exc),
                    )
                    result.errors += 1
            else:
                result.preview.append({
                    "action": "update",
                    "entity_type": "filament",
                    "direction": "filamentdb_to_spoolman",
                    "label": _preview_label(sm_spool=sm_spool, fdb_filament=fdb_detail),
                    "field": fdb_path,
                    "old": fc.old_value, "new": fc.new_value,
                    "reason": None,
                    "spoolman_id": sm_spool.id,
                    "fdb_filament_id": fdb_filament_id,
                    "fdb_spool_id": fdb_spool_id,
                })
                result.updated += 1
            continue

        if action == SyncAction.PUSH_SM_TO_FDB:
            fc = sm_fc
            if fc is None:
                continue
            if should_skip_inherited(fdb_detail, fdb_path):
                logger.info(
                    "Cycle %s: skipping inherited field %s on FDB filament %s",
                    cycle_id, fdb_path, fdb_filament_id,
                )
                if dry_run:
                    result.preview.append({
                        "action": "skip",
                        "entity_type": "filament",
                        "direction": "spoolman_to_filamentdb",
                        "label": _preview_label(sm_spool=sm_spool, fdb_filament=fdb_detail),
                        "field": fdb_path,
                        "old": None, "new": None,
                        "reason": "inherited from parent",
                        "spoolman_id": sm_spool.id,
                        "fdb_filament_id": fdb_filament_id,
                        "fdb_spool_id": fdb_spool_id,
                    })
                    sm_skipped_fields.add(fdb_path)
                result.skipped += 1
                continue
            # Collect into a single PUT
            parts = fdb_path.split(".", 1)
            if len(parts) == 1:
                write_value = to_fdb_color(fc.new_value) if fdb_path == "color" else fc.new_value
                fdb_put_payload[fdb_path] = write_value
            else:
                fdb_put_payload.setdefault(parts[0], {})[parts[1]] = fc.new_value
            fdb_put_field_changes.append(fc)

    if fdb_put_payload and not dry_run:
        try:
            await filamentdb.update_filament(fdb_filament_id, fdb_put_payload)
            for fc in fdb_put_field_changes:
                _log(
                    db, cycle_id, "spoolman_to_filamentdb", "update", "filament",
                    spoolman_id=sm_spool.id, fdb_filament_id=fdb_filament_id,
                    field_name=fc.field_name, old_value=fc.old_value, new_value=fc.new_value,
                )
                # Anti-ping-pong: record the written value so the next cycle
                # sees it as the baseline and does not re-detect it.
                fdb_field_values[fc.field_name] = fc.new_value
            result.updated += len(fdb_put_field_changes)
        except Exception as exc:
            logger.error("Cycle %s: field sync SM→FDB failed: %s", cycle_id, exc)
            _log(
                db, cycle_id, "spoolman_to_filamentdb", "error", "filament",
                spoolman_id=sm_spool.id, fdb_filament_id=fdb_filament_id,
                error_message=str(exc),
            )
            result.errors += 1
    elif fdb_put_payload and dry_run:
        for fc in fdb_put_field_changes:
            if fc.field_name in sm_skipped_fields:
                continue
            result.preview.append({
                "action": "update",
                "entity_type": "filament",
                "direction": "spoolman_to_filamentdb",
                "label": _preview_label(sm_spool=sm_spool, fdb_filament=fdb_detail),
                "field": fc.field_name,
                "old": fc.old_value, "new": fc.new_value,
                "reason": None,
                "spoolman_id": sm_spool.id,
                "fdb_filament_id": fdb_filament_id,
                "fdb_spool_id": fdb_spool_id,
            })
        result.updated += len(fdb_put_field_changes) - len(sm_skipped_fields)

    return fdb_field_values, sm_extra_decoded


# ---------------------------------------------------------------------------
# Structured multicolor sync (bidirectional)
# ---------------------------------------------------------------------------


def _mc_label(sm_fil, fdb_fil: FDBFilament | None) -> str:
    """Human label for a multicolor preview/conflict entry."""
    sm_name = getattr(sm_fil, "name", None)
    fdb_name = fdb_fil.name if fdb_fil else None
    return sm_name or fdb_name or "unknown filament"


async def _sync_multicolor(
    db: Session,
    cycle_id: str,
    result: CycleResult,
    dry_run: bool,
    *,
    filament_mappings: list[FilamentMapping],
    sm_filaments: dict[int, Any],
    fdb_filaments: dict[str, FDBFilament],
    spoolman: SpoolmanClient,
    filamentdb: FilamentDBClient,
    multicolor_supported: bool,
    matprop_direction: str = "filamentdb_to_spoolman",
    matprop_policy: str = "manual",
) -> None:
    """Bidirectional structured multicolor sync, one operation per filament pair.

    Multicolor is a filament-level property (FDB ``color``/``secondaryColors``/``optTags``
    ↔ Spoolman ``color_hex``/``multi_color_hexes``/``multi_color_direction``), so this
    runs over filament mappings rather than spool pairs.  A system-agnostic signature is
    stored per filament; the next cycle compares it to detect which side changed —
    routed through ``resolve_sync_action`` with the material_properties category settings.
    Requires Filament DB >= 1.33.0.
    """
    for m in filament_mappings:
        sm_fil = sm_filaments.get(m.spoolman_filament_id)
        fdb_list = fdb_filaments.get(m.filamentdb_id)
        if sm_fil is None or fdb_list is None:
            continue

        sm_is_mc = bool(sm_fil.multi_color_hexes)
        fdb_is_mc = bool(fdb_list.secondaryColors) or arrangement_from_tags(fdb_list.optTags) != "solid"
        if not (sm_is_mc or fdb_is_mc):
            continue  # purely solid — the generic ``color`` field sync handles it

        if not multicolor_supported:
            if dry_run:
                result.preview.append({
                    "action": "skip",
                    "entity_type": "filament",
                    "direction": None,
                    "label": _mc_label(sm_fil, fdb_list),
                    "field": "multicolor",
                    "old": None, "new": None,
                    "reason": "Filament DB < 1.33.0 — upgrade for multicolor sync",
                    "spoolman_id": None,
                    "fdb_filament_id": m.filamentdb_id,
                    "fdb_spool_id": None,
                })
            else:
                logger.warning(
                    "Cycle %s: skipping multicolor sync for filament %s — FDB < 1.33.0",
                    cycle_id, m.filamentdb_id,
                )
            result.skipped += 1
            continue

        # Detail view resolves variant inheritance for secondaryColors/optTags/color.
        try:
            fdb_detail = await filamentdb.get_filament(m.filamentdb_id)
        except Exception as exc:
            logger.error("Cycle %s: multicolor detail fetch failed %s: %s", cycle_id, m.filamentdb_id, exc)
            result.errors += 1
            continue

        sm_sig_now = sm_multicolor_signature(
            sm_fil.color_hex, sm_fil.multi_color_hexes, sm_fil.multi_color_direction
        )
        fdb_sig_now = multicolor_signature(
            fdb_detail.color, fdb_detail.secondaryColors, fdb_detail.optTags
        )

        sm_snap = _get_snapshot(db, "spoolman", "filament", str(m.spoolman_filament_id))
        fdb_snap = _get_snapshot(db, "filamentdb", "filament", m.filamentdb_id)
        sm_sig_then = sm_snap.get("_mc_sig") if sm_snap else None
        fdb_sig_then = fdb_snap.get("_mc_sig") if fdb_snap else None

        # Capture the resolved FDB color hex for the Synced Records display (§3 in Phase A).
        # Stored as _mc_color in the FDB filament snapshot alongside _mc_sig.
        fdb_color_now = fdb_detail.color if fdb_detail else None

        def _store(sm_sig: str, fdb_sig: str) -> None:
            _merge_snapshot(db, "spoolman", "filament", str(m.spoolman_filament_id), {"_mc_sig": sm_sig})
            _merge_snapshot(
                db, "filamentdb", "filament", m.filamentdb_id,
                {"_mc_sig": fdb_sig, "_mc_color": fdb_color_now},
            )

        # First sight — store baseline, no write (matches the spool-pair baseline rule).
        if sm_sig_then is None or fdb_sig_then is None:
            if not dry_run:
                _store(sm_sig_now, fdb_sig_now)
            continue

        sm_changed = sm_sig_then != sm_sig_now
        fdb_changed = fdb_sig_then != fdb_sig_now

        # Both sides changed into agreement → refresh baseline silently.
        if sm_sig_now == fdb_sig_now and (sm_changed or fdb_changed):
            if not dry_run:
                _store(sm_sig_now, fdb_sig_now)
            continue

        action = resolve_sync_action(
            sm_changed=sm_changed,
            fdb_changed=fdb_changed,
            direction=matprop_direction,
            policy=matprop_policy,
        )

        if action == SyncAction.NOOP:
            continue

        if action == SyncAction.QUEUE_CONFLICT:
            if not dry_run:
                if not _has_open_conflict(
                    db, "filament", "multicolor",
                    spoolman_id=m.spoolman_filament_id,
                    fdb_filament_id=m.filamentdb_id,
                ):
                    _queue_conflict(
                        db, cycle_id, "filament", "multicolor",
                        spoolman_id=m.spoolman_filament_id,
                        fdb_filament_id=m.filamentdb_id,
                        spoolman_value=sm_sig_now,
                        filamentdb_value=fdb_sig_now,
                    )
                    result.conflicts += 1
            else:
                result.preview.append({
                    "action": "conflict",
                    "entity_type": "filament",
                    "direction": None,
                    "label": _mc_label(sm_fil, fdb_list),
                    "field": "multicolor",
                    "old": sm_sig_now, "new": fdb_sig_now,
                    "reason": "both sides changed multicolor",
                    "spoolman_id": m.spoolman_filament_id,
                    "fdb_filament_id": m.filamentdb_id,
                    "fdb_spool_id": None,
                })
                result.conflicts += 1
            continue

        if action == SyncAction.PUSH_SM_TO_FDB:
            mc = sm_multicolor_to_fdb(
                sm_fil.color_hex, sm_fil.multi_color_hexes, sm_fil.multi_color_direction,
                existing_opt_tags=fdb_detail.optTags,
            )
            payload = {
                "color": mc["color"],
                "secondaryColors": mc["secondaryColors"],
                "optTags": mc["optTags"],
            }
            if not dry_run:
                try:
                    await filamentdb.update_filament(m.filamentdb_id, payload)
                    _store(sm_sig_now, sm_sig_now)  # FDB now matches SM
                    _log(
                        db, cycle_id, "spoolman_to_filamentdb", "update", "filament",
                        spoolman_id=m.spoolman_filament_id, fdb_filament_id=m.filamentdb_id,
                        field_name="multicolor", old_value=fdb_sig_now, new_value=sm_sig_now,
                    )
                    result.updated += 1
                except Exception as exc:
                    logger.error("Cycle %s: multicolor SM→FDB failed %s: %s", cycle_id, m.filamentdb_id, exc)
                    _log(
                        db, cycle_id, "spoolman_to_filamentdb", "error", "filament",
                        spoolman_id=m.spoolman_filament_id, fdb_filament_id=m.filamentdb_id,
                        field_name="multicolor", error_message=str(exc),
                    )
                    result.errors += 1
            else:
                result.preview.append({
                    "action": "update",
                    "entity_type": "filament",
                    "direction": "spoolman_to_filamentdb",
                    "label": _mc_label(sm_fil, fdb_list),
                    "field": "multicolor",
                    "old": fdb_sig_now, "new": sm_sig_now,
                    "reason": None,
                    "spoolman_id": m.spoolman_filament_id,
                    "fdb_filament_id": m.filamentdb_id,
                    "fdb_spool_id": None,
                })
                result.updated += 1
            continue

        if action == SyncAction.PUSH_FDB_TO_SM:
            sm = fdb_multicolor_to_sm(fdb_detail.color, fdb_detail.secondaryColors, fdb_detail.optTags)
            if not dry_run:
                try:
                    sm_payload: dict = {}
                    if sm["color_hex"] is not None:
                        sm_payload["color_hex"] = sm["color_hex"]
                    if sm["multi_color_hexes"] is not None:
                        sm_payload["multi_color_hexes"] = sm["multi_color_hexes"]
                    if sm["multi_color_direction"] is not None:
                        sm_payload["multi_color_direction"] = sm["multi_color_direction"]
                    await spoolman.update_filament(m.spoolman_filament_id, sm_payload)
                    _store(fdb_sig_now, fdb_sig_now)  # SM now matches FDB
                    _log(
                        db, cycle_id, "filamentdb_to_spoolman", "update", "filament",
                        spoolman_id=m.spoolman_filament_id, fdb_filament_id=m.filamentdb_id,
                        field_name="multicolor", old_value=sm_sig_now, new_value=fdb_sig_now,
                    )
                    result.updated += 1
                except Exception as exc:
                    logger.error("Cycle %s: multicolor FDB→SM failed %s: %s", cycle_id, m.spoolman_filament_id, exc)
                    _log(
                        db, cycle_id, "filamentdb_to_spoolman", "error", "filament",
                        spoolman_id=m.spoolman_filament_id, fdb_filament_id=m.filamentdb_id,
                        field_name="multicolor", error_message=str(exc),
                    )
                    result.errors += 1
            else:
                result.preview.append({
                    "action": "update",
                    "entity_type": "filament",
                    "direction": "filamentdb_to_spoolman",
                    "label": _mc_label(sm_fil, fdb_list),
                    "field": "multicolor",
                    "old": sm_sig_now, "new": fdb_sig_now,
                    "reason": None,
                    "spoolman_id": m.spoolman_filament_id,
                    "fdb_filament_id": m.filamentdb_id,
                    "fdb_spool_id": None,
                })
                result.updated += 1


# ---------------------------------------------------------------------------
# Filament-level cost sync (bidirectional)
# ---------------------------------------------------------------------------


async def _sync_cost(
    db: Session,
    cycle_id: str,
    result: CycleResult,
    dry_run: bool,
    *,
    filament_mappings: list[FilamentMapping],
    sm_filaments: dict[int, Any],
    sm_spools_by_filament: dict[int, list[Any]],
    fdb_filaments: dict[str, Any],
    spoolman: SpoolmanClient,
    filamentdb: FilamentDBClient,
    matprop_direction: str = "filamentdb_to_spoolman",
    matprop_policy: str = "manual",
) -> None:
    """Bidirectional filament-level cost sync, one operation per filament pair.

    Cost follows material_properties direction + policy (same as density/temps).
    Effective SM cost = spool price first (first spool by id with a non-null price),
    falling back to the filament price.  FDB cost is filament-level.

    Routed through resolve_sync_action.  Conflict dedup prevents re-queuing.
    Snapshots store _cost per side; writes merge so _mc_sig survives.
    """
    for m in filament_mappings:
        sm_fil = sm_filaments.get(m.spoolman_filament_id)
        fdb_list = fdb_filaments.get(m.filamentdb_id)
        if sm_fil is None or fdb_list is None:
            continue

        sm_cost_now = resolve_effective_cost(
            sm_fil.price,
            sm_spools_by_filament.get(m.spoolman_filament_id, []),
        )
        fdb_cost_now = fdb_list.cost

        # Both None — nothing to do.
        if sm_cost_now is None and fdb_cost_now is None:
            continue

        sm_snap = _get_snapshot(db, "spoolman", "filament", str(m.spoolman_filament_id))
        fdb_snap = _get_snapshot(db, "filamentdb", "filament", m.filamentdb_id)
        sm_cost_then = sm_snap.get("_cost") if sm_snap else None
        fdb_cost_then = fdb_snap.get("_cost") if fdb_snap else None

        def _store_cost(sm_val: Any, fdb_val: Any) -> None:
            _merge_snapshot(db, "spoolman", "filament", str(m.spoolman_filament_id), {"_cost": sm_val})
            _merge_snapshot(db, "filamentdb", "filament", m.filamentdb_id, {"_cost": fdb_val})

        # First sight — store baseline, no write (matches multicolor / spool-pair rule).
        if sm_cost_then is None and fdb_cost_then is None:
            if not dry_run:
                _store_cost(sm_cost_now, fdb_cost_now)
            else:
                result.preview.append({
                    "action": "skip",
                    "entity_type": "filament",
                    "direction": None,
                    "label": getattr(sm_fil, "name", None) or fdb_list.name,
                    "field": "cost",
                    "old": None, "new": None,
                    "reason": "first sync of this pair — baseline stored, no diff yet",
                    "spoolman_id": m.spoolman_filament_id,
                    "fdb_filament_id": m.filamentdb_id,
                    "fdb_spool_id": None,
                })
                result.skipped += 1
            continue

        sm_changed = sm_cost_then != sm_cost_now
        fdb_changed = fdb_cost_then != fdb_cost_now

        # Nothing changed → no-op.
        if not sm_changed and not fdb_changed:
            continue

        # Both sides changed into agreement → refresh baseline silently.
        if sm_changed and fdb_changed and sm_cost_now == fdb_cost_now:
            if not dry_run:
                _store_cost(sm_cost_now, fdb_cost_now)
            continue

        action = resolve_sync_action(
            sm_changed=sm_changed,
            fdb_changed=fdb_changed,
            direction=matprop_direction,
            policy=matprop_policy,
        )

        if action == SyncAction.NOOP:
            continue

        if action == SyncAction.QUEUE_CONFLICT:
            if not dry_run:
                if not _has_open_conflict(
                    db, "filament", "cost",
                    spoolman_id=m.spoolman_filament_id,
                    fdb_filament_id=m.filamentdb_id,
                ):
                    _queue_conflict(
                        db, cycle_id, "filament", "cost",
                        spoolman_id=m.spoolman_filament_id,
                        fdb_filament_id=m.filamentdb_id,
                        spoolman_value=sm_cost_now,
                        filamentdb_value=fdb_cost_now,
                    )
                    result.conflicts += 1
            else:
                result.preview.append({
                    "action": "conflict",
                    "entity_type": "filament",
                    "direction": None,
                    "label": getattr(sm_fil, "name", None) or fdb_list.name,
                    "field": "cost",
                    "old": sm_cost_now, "new": fdb_cost_now,
                    "reason": "both sides changed cost",
                    "spoolman_id": m.spoolman_filament_id,
                    "fdb_filament_id": m.filamentdb_id,
                    "fdb_spool_id": None,
                })
                result.conflicts += 1
            continue

        if action == SyncAction.PUSH_SM_TO_FDB:
            if not dry_run:
                try:
                    await filamentdb.update_filament(m.filamentdb_id, {"cost": sm_cost_now})
                    _store_cost(sm_cost_now, sm_cost_now)
                    _log(
                        db, cycle_id, "spoolman_to_filamentdb", "update", "filament",
                        spoolman_id=m.spoolman_filament_id, fdb_filament_id=m.filamentdb_id,
                        field_name="cost", old_value=fdb_cost_now, new_value=sm_cost_now,
                    )
                    result.updated += 1
                except Exception as exc:
                    logger.error("Cycle %s: cost SM→FDB failed %s: %s", cycle_id, m.filamentdb_id, exc)
                    _log(
                        db, cycle_id, "spoolman_to_filamentdb", "error", "filament",
                        spoolman_id=m.spoolman_filament_id, fdb_filament_id=m.filamentdb_id,
                        field_name="cost", error_message=str(exc),
                    )
                    result.errors += 1
            else:
                result.preview.append({
                    "action": "update",
                    "entity_type": "filament",
                    "direction": "spoolman_to_filamentdb",
                    "label": getattr(sm_fil, "name", None) or fdb_list.name,
                    "field": "cost",
                    "old": fdb_cost_now, "new": sm_cost_now,
                    "reason": None,
                    "spoolman_id": m.spoolman_filament_id,
                    "fdb_filament_id": m.filamentdb_id,
                    "fdb_spool_id": None,
                })
                result.updated += 1
            continue

        if action == SyncAction.PUSH_FDB_TO_SM:
            # FDB→SM writes the Spoolman FILAMENT price (never per-spool prices).
            if not dry_run:
                try:
                    await spoolman.update_filament(m.spoolman_filament_id, {"price": fdb_cost_now})
                    _store_cost(fdb_cost_now, fdb_cost_now)
                    _log(
                        db, cycle_id, "filamentdb_to_spoolman", "update", "filament",
                        spoolman_id=m.spoolman_filament_id, fdb_filament_id=m.filamentdb_id,
                        field_name="cost", old_value=sm_cost_now, new_value=fdb_cost_now,
                    )
                    result.updated += 1
                except Exception as exc:
                    logger.error("Cycle %s: cost FDB→SM failed %s: %s", cycle_id, m.spoolman_filament_id, exc)
                    _log(
                        db, cycle_id, "filamentdb_to_spoolman", "error", "filament",
                        spoolman_id=m.spoolman_filament_id, fdb_filament_id=m.filamentdb_id,
                        field_name="cost", error_message=str(exc),
                    )
                    result.errors += 1
            else:
                result.preview.append({
                    "action": "update",
                    "entity_type": "filament",
                    "direction": "filamentdb_to_spoolman",
                    "label": getattr(sm_fil, "name", None) or fdb_list.name,
                    "field": "cost",
                    "old": sm_cost_now, "new": fdb_cost_now,
                    "reason": None,
                    "spoolman_id": m.spoolman_filament_id,
                    "fdb_filament_id": m.filamentdb_id,
                    "fdb_spool_id": None,
                })
                result.updated += 1


# ---------------------------------------------------------------------------
# Material-property sync — native filament temperature fields (bidirectional)
# ---------------------------------------------------------------------------

# (label, FDB temperatures.<attr>, Spoolman native filament field).  Bed/nozzle
# temps are NATIVE filament fields on BOTH sides, so they are not covered by the
# spool extra-field mapper (resolve_field_map only matches SM *extra* keys to
# identically-named FDB fields).  This pass owns them, mirroring _sync_cost.
MATERIAL_PROP_TEMP_PAIRS: list[tuple[str, str, str]] = [
    ("bed_temp", "bed", "settings_bed_temp"),
    ("nozzle_temp", "nozzle", "settings_extruder_temp"),
]

# (label, FDB field name, Spoolman native filament field, normalizer).
# These are the five native Spoolman filament fields that have a direct FDB filament
# counterpart — synced as plain scalars (no sub-object read-modify-write needed).
# FDB "type" maps to SM "material" (name remap); all others are same-unit numerics.
# NOTE: the snapshot key for each is "_mp_<sm_field>" (matching the temp convention).
MATERIAL_PROP_SCALAR_PAIRS: list[tuple[str, str, str, Any]] = []  # populated below


def _norm_temp(v: Any) -> int | None:
    """Normalise a temperature for comparison/storage (FDB float ↔ SM int)."""
    if v is None:
        return None
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def _norm_float2(v: Any) -> float | None:
    """Normalise a float to 2 decimal places for stable comparison (density, diameter, etc.)."""
    if v is None:
        return None
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def _norm_str(v: Any) -> str | None:
    """Normalise a string by stripping whitespace; None/empty → None."""
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


# Populate after the normalizer functions are defined.
MATERIAL_PROP_SCALAR_PAIRS = [
    # (label,    fdb_path,           sm_field,           normalizer)
    ("material", "type",             "material",         _norm_str),
    ("density",  "density",          "density",          _norm_float2),
    ("diameter", "diameter",         "diameter",         _norm_float2),
    ("spool_weight", "spoolWeight",  "spool_weight",     _norm_float2),
    ("net_filament_weight", "netFilamentWeight", "weight", _norm_float2),
]


async def _sync_material_props(
    db: Session,
    cycle_id: str,
    result: CycleResult,
    dry_run: bool,
    *,
    filament_mappings: list[FilamentMapping],
    sm_filaments: dict[int, Any],
    fdb_filaments: dict[str, Any],
    spoolman: SpoolmanClient,
    filamentdb: FilamentDBClient,
    matprop_direction: str = "filamentdb_to_spoolman",
    matprop_policy: str = "manual",
) -> None:
    """Bidirectional filament-level sync of native temperature fields (bed/nozzle).

    Per-field snapshot baseline (``_mp_<sm_field>`` per side), routed through
    ``resolve_sync_action`` under the material_properties direction + policy —
    same shape as ``_sync_cost``.  FDB→SM writes the native Spoolman filament
    field; SM→FDB read-modify-writes the FDB ``temperatures`` object so sibling
    temps are preserved.
    """
    for m in filament_mappings:
        sm_fil = sm_filaments.get(m.spoolman_filament_id)
        fdb_fil = fdb_filaments.get(m.filamentdb_id)
        if sm_fil is None or fdb_fil is None:
            continue
        fdb_temps = getattr(fdb_fil, "temperatures", None)
        label_name = getattr(sm_fil, "name", None) or getattr(fdb_fil, "name", None)

        for label, fdb_attr, sm_field in MATERIAL_PROP_TEMP_PAIRS:
            fdb_now = _norm_temp(getattr(fdb_temps, fdb_attr, None) if fdb_temps else None)
            sm_now = _norm_temp(getattr(sm_fil, sm_field, None))
            if fdb_now is None and sm_now is None:
                continue

            snap_key = f"_mp_{sm_field}"
            sm_snap = _get_snapshot(db, "spoolman", "filament", str(m.spoolman_filament_id))
            fdb_snap = _get_snapshot(db, "filamentdb", "filament", m.filamentdb_id)
            sm_then = sm_snap.get(snap_key) if sm_snap else None
            fdb_then = fdb_snap.get(snap_key) if fdb_snap else None

            def _store(sv: Any, fv: Any, _k: str = snap_key) -> None:
                _merge_snapshot(db, "spoolman", "filament", str(m.spoolman_filament_id), {_k: sv})
                _merge_snapshot(db, "filamentdb", "filament", m.filamentdb_id, {_k: fv})

            # First sight — store baseline, no write.
            if sm_then is None and fdb_then is None:
                if not dry_run:
                    _store(sm_now, fdb_now)
                else:
                    result.preview.append({
                        "action": "skip", "entity_type": "filament", "direction": None,
                        "label": label_name, "field": label, "old": None, "new": None,
                        "reason": "first sync of this pair — baseline stored, no diff yet",
                        "spoolman_id": m.spoolman_filament_id,
                        "fdb_filament_id": m.filamentdb_id, "fdb_spool_id": None,
                    })
                    result.skipped += 1
                continue

            sm_changed = sm_then != sm_now
            fdb_changed = fdb_then != fdb_now
            if not sm_changed and not fdb_changed:
                continue
            # Both changed into agreement → refresh baseline silently.
            if sm_changed and fdb_changed and sm_now == fdb_now:
                if not dry_run:
                    _store(sm_now, fdb_now)
                continue

            action = resolve_sync_action(
                sm_changed=sm_changed, fdb_changed=fdb_changed,
                direction=matprop_direction, policy=matprop_policy,
            )

            if action == SyncAction.NOOP:
                continue

            if action == SyncAction.QUEUE_CONFLICT:
                if not dry_run:
                    if not _has_open_conflict(
                        db, "filament", label,
                        spoolman_id=m.spoolman_filament_id, fdb_filament_id=m.filamentdb_id,
                    ):
                        _queue_conflict(
                            db, cycle_id, "filament", label,
                            spoolman_id=m.spoolman_filament_id, fdb_filament_id=m.filamentdb_id,
                            spoolman_value=sm_now, filamentdb_value=fdb_now,
                        )
                        result.conflicts += 1
                else:
                    result.preview.append({
                        "action": "conflict", "entity_type": "filament", "direction": None,
                        "label": label_name, "field": label, "old": sm_now, "new": fdb_now,
                        "reason": f"both sides changed {label}",
                        "spoolman_id": m.spoolman_filament_id,
                        "fdb_filament_id": m.filamentdb_id, "fdb_spool_id": None,
                    })
                    result.conflicts += 1
                continue

            if action == SyncAction.PUSH_SM_TO_FDB:
                if not dry_run:
                    try:
                        temps_payload = fdb_temps.model_dump() if fdb_temps else {}
                        temps_payload[fdb_attr] = sm_now
                        await filamentdb.update_filament(m.filamentdb_id, {"temperatures": temps_payload})
                        _store(sm_now, sm_now)
                        _log(
                            db, cycle_id, "spoolman_to_filamentdb", "update", "filament",
                            spoolman_id=m.spoolman_filament_id, fdb_filament_id=m.filamentdb_id,
                            field_name=label, old_value=fdb_now, new_value=sm_now,
                        )
                        result.updated += 1
                    except Exception as exc:
                        logger.error("Cycle %s: %s SM→FDB failed %s: %s", cycle_id, label, m.filamentdb_id, exc)
                        _log(
                            db, cycle_id, "spoolman_to_filamentdb", "error", "filament",
                            spoolman_id=m.spoolman_filament_id, fdb_filament_id=m.filamentdb_id,
                            field_name=label, error_message=str(exc),
                        )
                        result.errors += 1
                else:
                    result.preview.append({
                        "action": "update", "entity_type": "filament",
                        "direction": "spoolman_to_filamentdb", "label": label_name,
                        "field": label, "old": fdb_now, "new": sm_now, "reason": None,
                        "spoolman_id": m.spoolman_filament_id,
                        "fdb_filament_id": m.filamentdb_id, "fdb_spool_id": None,
                    })
                    result.updated += 1
                continue

            if action == SyncAction.PUSH_FDB_TO_SM:
                if not dry_run:
                    try:
                        await spoolman.update_filament(m.spoolman_filament_id, {sm_field: fdb_now})
                        _store(fdb_now, fdb_now)
                        _log(
                            db, cycle_id, "filamentdb_to_spoolman", "update", "filament",
                            spoolman_id=m.spoolman_filament_id, fdb_filament_id=m.filamentdb_id,
                            field_name=label, old_value=sm_now, new_value=fdb_now,
                        )
                        result.updated += 1
                    except Exception as exc:
                        logger.error("Cycle %s: %s FDB→SM failed %s: %s", cycle_id, label, m.spoolman_filament_id, exc)
                        _log(
                            db, cycle_id, "filamentdb_to_spoolman", "error", "filament",
                            spoolman_id=m.spoolman_filament_id, fdb_filament_id=m.filamentdb_id,
                            field_name=label, error_message=str(exc),
                        )
                        result.errors += 1
                else:
                    result.preview.append({
                        "action": "update", "entity_type": "filament",
                        "direction": "filamentdb_to_spoolman", "label": label_name,
                        "field": label, "old": sm_now, "new": fdb_now, "reason": None,
                        "spoolman_id": m.spoolman_filament_id,
                        "fdb_filament_id": m.filamentdb_id, "fdb_spool_id": None,
                    })
                    result.updated += 1


# ---------------------------------------------------------------------------
# Material scalar sync — material/density/diameter/spool_weight/weight (bidirectional)
# ---------------------------------------------------------------------------


async def _sync_material_scalars(
    db: Session,
    cycle_id: str,
    result: CycleResult,
    dry_run: bool,
    *,
    filament_mappings: list[FilamentMapping],
    sm_filaments: dict[int, Any],
    fdb_filaments: dict[str, Any],
    spoolman: SpoolmanClient,
    filamentdb: FilamentDBClient,
    matprop_direction: str = "filamentdb_to_spoolman",
    matprop_policy: str = "manual",
) -> None:
    """Bidirectional sync of native shared filament scalar fields.

    Covers the five fields with a direct FDB↔SM counterpart that are NOT handled
    by the temperature pass or the extra-field mapper:

        SM ``material``        ↔ FDB ``type``
        SM ``density``         ↔ FDB ``density``
        SM ``diameter``        ↔ FDB ``diameter``
        SM ``spool_weight``    ↔ FDB ``spoolWeight``
        SM ``weight``          ↔ FDB ``netFilamentWeight``

    Per-field baseline keyed ``_mp_<sm_field>`` (coexists with temp/cost/_mc_sig
    keys via ``_merge_snapshot``).  Snapshot stores the resolved FDB value on the
    FDB side.

    **PUSH_SM_TO_FDB master/variant gate:**
    - Standalone (no parentId) OR field already overridden (not in inherited_fields):
      write directly.
    - Inherited AND sm_now == resolved: skip — value already matches the master,
      leave it inherited (no redundant override).
    - Inherited AND sm_now != resolved: queue a ``master_divergence`` conflict
      (record-only; Phase B owns the apply workflow).
    """
    for m in filament_mappings:
        sm_fil = sm_filaments.get(m.spoolman_filament_id)
        fdb_fil = fdb_filaments.get(m.filamentdb_id)
        if sm_fil is None or fdb_fil is None:
            continue
        label_name = getattr(sm_fil, "name", None) or getattr(fdb_fil, "name", None)

        # Fetch the detail view once per filament pair (needed for inherited_fields).
        # We cache it on the first field that needs it to avoid O(fields * n) fetches.
        fdb_detail: Any = None

        for label, fdb_path, sm_field, normalizer in MATERIAL_PROP_SCALAR_PAIRS:
            # Read current SM value.
            sm_now = normalizer(getattr(sm_fil, sm_field, None))

            # We need the detail view to read the resolved FDB value (variant
            # inheritance resolves in the detail view but NOT in the list view).
            if fdb_detail is None:
                try:
                    fdb_detail = await filamentdb.get_filament(m.filamentdb_id)
                except Exception as exc:
                    logger.error(
                        "Cycle %s: material-scalar detail fetch failed %s: %s",
                        cycle_id, m.filamentdb_id, exc,
                    )
                    result.errors += 1
                    break  # Skip all fields for this pair; fetch error.

            from app.core.fields import get_fdb_field_value
            fdb_now = normalizer(get_fdb_field_value(fdb_detail, fdb_path))

            if fdb_now is None and sm_now is None:
                continue

            snap_key = f"_mp_{sm_field}"
            sm_snap = _get_snapshot(db, "spoolman", "filament", str(m.spoolman_filament_id))
            fdb_snap = _get_snapshot(db, "filamentdb", "filament", m.filamentdb_id)
            sm_then = sm_snap.get(snap_key) if sm_snap else None
            fdb_then = fdb_snap.get(snap_key) if fdb_snap else None

            def _store(sv: Any, fv: Any, _k: str = snap_key) -> None:
                _merge_snapshot(db, "spoolman", "filament", str(m.spoolman_filament_id), {_k: sv})
                _merge_snapshot(db, "filamentdb", "filament", m.filamentdb_id, {_k: fv})

            # First sight — store baseline, no write.
            if sm_then is None and fdb_then is None:
                if not dry_run:
                    _store(sm_now, fdb_now)
                else:
                    result.preview.append({
                        "action": "skip", "entity_type": "filament", "direction": None,
                        "label": label_name, "field": label, "old": None, "new": None,
                        "reason": "first sync of this pair — baseline stored, no diff yet",
                        "spoolman_id": m.spoolman_filament_id,
                        "fdb_filament_id": m.filamentdb_id, "fdb_spool_id": None,
                    })
                    result.skipped += 1
                continue

            sm_changed = sm_then != sm_now
            fdb_changed = fdb_then != fdb_now
            if not sm_changed and not fdb_changed:
                continue
            # Both changed into agreement → refresh baseline silently.
            if sm_changed and fdb_changed and sm_now == fdb_now:
                if not dry_run:
                    _store(sm_now, fdb_now)
                continue

            action = resolve_sync_action(
                sm_changed=sm_changed, fdb_changed=fdb_changed,
                direction=matprop_direction, policy=matprop_policy,
            )

            if action == SyncAction.NOOP:
                continue

            if action == SyncAction.QUEUE_CONFLICT:
                if not dry_run:
                    if not _has_open_conflict(
                        db, "filament", label,
                        spoolman_id=m.spoolman_filament_id, fdb_filament_id=m.filamentdb_id,
                        conflict_type="cross_system",
                    ):
                        _queue_conflict(
                            db, cycle_id, "filament", label,
                            spoolman_id=m.spoolman_filament_id, fdb_filament_id=m.filamentdb_id,
                            spoolman_value=sm_now, filamentdb_value=fdb_now,
                            conflict_type="cross_system",
                        )
                        result.conflicts += 1
                else:
                    result.preview.append({
                        "action": "conflict", "entity_type": "filament", "direction": None,
                        "label": label_name, "field": label, "old": sm_now, "new": fdb_now,
                        "reason": f"both sides changed {label}",
                        "spoolman_id": m.spoolman_filament_id,
                        "fdb_filament_id": m.filamentdb_id, "fdb_spool_id": None,
                    })
                    result.conflicts += 1
                continue

            if action == SyncAction.PUSH_SM_TO_FDB:
                # Master/variant gate (see module docstring for the three cases).
                top_field = fdb_path.split(".")[0]
                has_parent = fdb_detail.parentId is not None
                inherited = top_field in fdb_detail.inherited_fields

                if not has_parent or not inherited:
                    # Standalone OR already overridden — write directly.
                    if not dry_run:
                        try:
                            await filamentdb.update_filament(m.filamentdb_id, {fdb_path: sm_now})
                            _store(sm_now, sm_now)
                            _log(
                                db, cycle_id, "spoolman_to_filamentdb", "update", "filament",
                                spoolman_id=m.spoolman_filament_id, fdb_filament_id=m.filamentdb_id,
                                field_name=label, old_value=fdb_now, new_value=sm_now,
                            )
                            result.updated += 1
                        except Exception as exc:
                            logger.error(
                                "Cycle %s: %s SM→FDB failed %s: %s",
                                cycle_id, label, m.filamentdb_id, exc,
                            )
                            _log(
                                db, cycle_id, "spoolman_to_filamentdb", "error", "filament",
                                spoolman_id=m.spoolman_filament_id, fdb_filament_id=m.filamentdb_id,
                                field_name=label, error_message=str(exc),
                            )
                            result.errors += 1
                    else:
                        result.preview.append({
                            "action": "update", "entity_type": "filament",
                            "direction": "spoolman_to_filamentdb", "label": label_name,
                            "field": label, "old": fdb_now, "new": sm_now, "reason": None,
                            "spoolman_id": m.spoolman_filament_id,
                            "fdb_filament_id": m.filamentdb_id, "fdb_spool_id": None,
                        })
                        result.updated += 1
                    continue

                # Field is inherited — compare SM value against the resolved (inherited) value.
                if sm_now == fdb_now:
                    # Matches the inherited master — no redundant override needed.
                    logger.info(
                        "Cycle %s: skip %s SM→FDB for FDB filament %s "
                        "— matches inherited master, left inherited",
                        cycle_id, label, m.filamentdb_id,
                    )
                    if dry_run:
                        result.preview.append({
                            "action": "skip", "entity_type": "filament",
                            "direction": "spoolman_to_filamentdb", "label": label_name,
                            "field": label, "old": None, "new": None,
                            "reason": "matches inherited master — left inherited",
                            "spoolman_id": m.spoolman_filament_id,
                            "fdb_filament_id": m.filamentdb_id, "fdb_spool_id": None,
                        })
                        result.skipped += 1
                    else:
                        result.skipped += 1
                    continue

                # Inherited AND diverges from master — queue master_divergence (no write).
                if not dry_run:
                    if not _has_open_conflict(
                        db, "filament", label,
                        spoolman_id=m.spoolman_filament_id, fdb_filament_id=m.filamentdb_id,
                        conflict_type="master_divergence",
                    ):
                        _queue_conflict(
                            db, cycle_id, "filament", label,
                            spoolman_id=m.spoolman_filament_id, fdb_filament_id=m.filamentdb_id,
                            spoolman_value=sm_now, filamentdb_value=fdb_now,
                            conflict_type="master_divergence",
                        )
                        result.conflicts += 1
                else:
                    result.preview.append({
                        "action": "conflict", "entity_type": "filament", "direction": None,
                        "label": label_name, "field": label, "old": sm_now, "new": fdb_now,
                        "reason": (
                            f"SM→FDB would override inherited master field {label!r} "
                            "— master_divergence queued (approval required, Phase B)"
                        ),
                        "spoolman_id": m.spoolman_filament_id,
                        "fdb_filament_id": m.filamentdb_id, "fdb_spool_id": None,
                    })
                    result.conflicts += 1
                continue

            if action == SyncAction.PUSH_FDB_TO_SM:
                # FDB→SM — write to the native SM filament field.  No master concern:
                # the SM side is flat; any resolved (inherited) FDB value is valid.
                if not dry_run:
                    try:
                        await spoolman.update_filament(m.spoolman_filament_id, {sm_field: fdb_now})
                        _store(fdb_now, fdb_now)
                        _log(
                            db, cycle_id, "filamentdb_to_spoolman", "update", "filament",
                            spoolman_id=m.spoolman_filament_id, fdb_filament_id=m.filamentdb_id,
                            field_name=label, old_value=sm_now, new_value=fdb_now,
                        )
                        result.updated += 1
                    except Exception as exc:
                        logger.error(
                            "Cycle %s: %s FDB→SM failed %s: %s",
                            cycle_id, label, m.spoolman_filament_id, exc,
                        )
                        _log(
                            db, cycle_id, "filamentdb_to_spoolman", "error", "filament",
                            spoolman_id=m.spoolman_filament_id, fdb_filament_id=m.filamentdb_id,
                            field_name=label, error_message=str(exc),
                        )
                        result.errors += 1
                else:
                    result.preview.append({
                        "action": "update", "entity_type": "filament",
                        "direction": "filamentdb_to_spoolman", "label": label_name,
                        "field": label, "old": sm_now, "new": fdb_now, "reason": None,
                        "spoolman_id": m.spoolman_filament_id,
                        "fdb_filament_id": m.filamentdb_id, "fdb_spool_id": None,
                    })
                    result.updated += 1


# ---------------------------------------------------------------------------
# Finish-tag sync (OpenPrintTag model, bidirectional)
# ---------------------------------------------------------------------------


def _fdb_finish_ids(opt_tags: list | None) -> frozenset[int]:
    """Extract the managed finish-tag IDs from a Filament DB ``optTags`` list.

    Only returns IDs in ``MANAGED_FINISH_IDS`` — arrangement tags (28/29) and
    unknown tags are excluded.
    """
    result: set[int] = set()
    for t in opt_tags or []:
        try:
            ti = int(t)
        except (TypeError, ValueError):
            continue
        if ti in MANAGED_FINISH_IDS:
            result.add(ti)
    return frozenset(result)


def _sm_finish_ids_from_filament(sm_fil: Any, tag_map: dict) -> frozenset[int]:
    """Compute finish IDs for a Spoolman filament.

    Resolution order:
    1. Read the ``filamentdb_material_tags`` extra field (structural — if set, trust it).
    2. Fall back to parsing ``name`` + ``material`` via ``finish_ids_from_text``.
    """
    mt_field = _settings.spoolman_field_filamentdb_material_tags
    raw = sm_fil.extra.get(mt_field) if hasattr(sm_fil, "extra") else None
    if raw is not None:
        decoded = decode_extra_value(raw)
        ids = parse_material_tags(decoded)
        return frozenset(set(ids) & MANAGED_FINISH_IDS)
    # Fallback: parse from text
    return frozenset(finish_ids_from_text(getattr(sm_fil, "name", None), getattr(sm_fil, "material", None), tag_map))


async def _sync_finish_tags(
    db: Session,
    cycle_id: str,
    result: CycleResult,
    dry_run: bool,
    *,
    filament_mappings: list[FilamentMapping],
    sm_filaments: dict[int, Any],
    fdb_filaments: dict[str, FDBFilament],
    spoolman: SpoolmanClient,
    filamentdb: FilamentDBClient,
    finish_tags_supported: bool = True,
    matprop_direction: str = "filamentdb_to_spoolman",
    matprop_policy: str = "manual",
) -> None:
    """Bidirectional finish-tag sync, one operation per filament pair.

    Finish tags are the managed subset of FDB ``optTags`` (MANAGED_FINISH_IDS) and
    the Spoolman filament extra field ``filamentdb_material_tags``.  Arrangement tags
    (28/29) are never touched here.

    Governed by ``material_properties`` direction + policy (same as cost/multicolor).
    Snapshot key ``_finish_sig`` coexists with ``_mc_sig`` and ``_cost`` via
    ``_merge_snapshot``.  Baseline-on-first-sight, no write.

    Gated on ``finish_tags_supported`` (FDB >= 1.33.0): ``optTags`` shipped with that
    release, so finish tags cannot be written to older instances.
    """
    if not finish_tags_supported:
        return  # Silently skip — same pattern as multicolor when FDB is too old.
    tag_map = _settings.parsed_material_tag_ids
    mt_field = _settings.spoolman_field_filamentdb_material_tags

    for m in filament_mappings:
        sm_fil = sm_filaments.get(m.spoolman_filament_id)
        fdb_list = fdb_filaments.get(m.filamentdb_id)
        if sm_fil is None or fdb_list is None:
            continue

        # Fetch FDB detail for live optTags (variant inheritance resolves here).
        try:
            fdb_detail = await filamentdb.get_filament(m.filamentdb_id)
            if fdb_detail is None:
                logger.warning("Cycle %s: finish-tag detail fetch returned None for %s — skipping", cycle_id, m.filamentdb_id)
                result.skipped += 1
                continue
        except Exception as exc:
            logger.error("Cycle %s: finish-tag detail fetch failed %s: %s", cycle_id, m.filamentdb_id, exc)
            result.errors += 1
            continue

        sm_ids_now = _sm_finish_ids_from_filament(sm_fil, tag_map)
        fdb_ids_now = _fdb_finish_ids(fdb_detail.optTags)

        # Canonical signature: sorted tuple as a stable string.
        def _sig(ids: frozenset[int]) -> str:
            return ",".join(str(i) for i in sorted(ids))

        sm_sig_now = _sig(sm_ids_now)
        fdb_sig_now = _sig(fdb_ids_now)

        sm_snap = _get_snapshot(db, "spoolman", "filament", str(m.spoolman_filament_id))
        fdb_snap = _get_snapshot(db, "filamentdb", "filament", m.filamentdb_id)
        sm_sig_then = sm_snap.get("_finish_sig") if sm_snap else None
        fdb_sig_then = fdb_snap.get("_finish_sig") if fdb_snap else None

        def _store(sm_sig: str, fdb_sig: str) -> None:
            _merge_snapshot(db, "spoolman", "filament", str(m.spoolman_filament_id), {"_finish_sig": sm_sig})
            _merge_snapshot(db, "filamentdb", "filament", m.filamentdb_id, {"_finish_sig": fdb_sig})

        # First sight — both sides have no _finish_sig baseline yet.
        if sm_sig_then is None or fdb_sig_then is None:
            if not dry_run:
                _store(sm_sig_now, fdb_sig_now)
            else:
                result.preview.append({
                    "action": "skip",
                    "entity_type": "filament",
                    "direction": None,
                    "label": getattr(sm_fil, "name", None) or fdb_list.name,
                    "field": "material_tags",
                    "old": None, "new": None,
                    "reason": "first sync of this pair — baseline stored, no diff yet",
                    "spoolman_id": m.spoolman_filament_id,
                    "fdb_filament_id": m.filamentdb_id,
                    "fdb_spool_id": None,
                })
                result.skipped += 1
            continue

        sm_changed = sm_sig_then != sm_sig_now
        fdb_changed = fdb_sig_then != fdb_sig_now

        # Nothing changed.
        if not sm_changed and not fdb_changed:
            continue

        # Both sides changed into agreement → refresh baseline.
        if sm_changed and fdb_changed and sm_sig_now == fdb_sig_now:
            if not dry_run:
                _store(sm_sig_now, fdb_sig_now)
            continue

        action = resolve_sync_action(
            sm_changed=sm_changed,
            fdb_changed=fdb_changed,
            direction=matprop_direction,
            policy=matprop_policy,
        )

        if action == SyncAction.NOOP:
            continue

        if action == SyncAction.QUEUE_CONFLICT:
            if not dry_run:
                if not _has_open_conflict(
                    db, "filament", "material_tags",
                    spoolman_id=m.spoolman_filament_id,
                    fdb_filament_id=m.filamentdb_id,
                ):
                    _queue_conflict(
                        db, cycle_id, "filament", "material_tags",
                        spoolman_id=m.spoolman_filament_id,
                        fdb_filament_id=m.filamentdb_id,
                        spoolman_value=sm_sig_now,
                        filamentdb_value=fdb_sig_now,
                    )
                    result.conflicts += 1
            else:
                result.preview.append({
                    "action": "conflict",
                    "entity_type": "filament",
                    "direction": None,
                    "label": getattr(sm_fil, "name", None) or fdb_list.name,
                    "field": "material_tags",
                    "old": sm_sig_now, "new": fdb_sig_now,
                    "reason": "both sides changed finish tags",
                    "spoolman_id": m.spoolman_filament_id,
                    "fdb_filament_id": m.filamentdb_id,
                    "fdb_spool_id": None,
                })
                result.conflicts += 1
            continue

        if action == SyncAction.PUSH_SM_TO_FDB:
            # SM → FDB: write finish IDs into FDB optTags (preserve arrangement + unknown).
            new_opt_tags = apply_finish_tags(fdb_detail.optTags, sm_ids_now)
            if not dry_run:
                try:
                    await filamentdb.update_filament(m.filamentdb_id, {"optTags": new_opt_tags})
                    _store(sm_sig_now, sm_sig_now)
                    _log(
                        db, cycle_id, "spoolman_to_filamentdb", "update", "filament",
                        spoolman_id=m.spoolman_filament_id, fdb_filament_id=m.filamentdb_id,
                        field_name="material_tags", old_value=fdb_sig_now, new_value=sm_sig_now,
                    )
                    result.updated += 1
                except Exception as exc:
                    logger.error("Cycle %s: finish-tag SM→FDB failed %s: %s", cycle_id, m.filamentdb_id, exc)
                    _log(
                        db, cycle_id, "spoolman_to_filamentdb", "error", "filament",
                        spoolman_id=m.spoolman_filament_id, fdb_filament_id=m.filamentdb_id,
                        field_name="material_tags", error_message=str(exc),
                    )
                    result.errors += 1
            else:
                result.preview.append({
                    "action": "update",
                    "entity_type": "filament",
                    "direction": "spoolman_to_filamentdb",
                    "label": getattr(sm_fil, "name", None) or fdb_list.name,
                    "field": "material_tags",
                    "old": fdb_sig_now, "new": sm_sig_now,
                    "reason": None,
                    "spoolman_id": m.spoolman_filament_id,
                    "fdb_filament_id": m.filamentdb_id,
                    "fdb_spool_id": None,
                })
                result.updated += 1
            continue

        if action == SyncAction.PUSH_FDB_TO_SM:
            # FDB → SM: write finish IDs into SM filament extra field as a CSV string.
            # Spoolman text fields accept a JSON-quoted string ("17,28"), not a JSON
            # array ("[17, 28]") — the latter 400s. serialize_material_tags produces the
            # CSV string; encode_extra_value JSON-quotes it to '"17,28"' for the wire.
            encoded = encode_extra_value(serialize_material_tags(fdb_ids_now))
            if not dry_run:
                try:
                    await spoolman.update_filament(m.spoolman_filament_id, {"extra": {mt_field: encoded}})
                    _store(fdb_sig_now, fdb_sig_now)
                    _log(
                        db, cycle_id, "filamentdb_to_spoolman", "update", "filament",
                        spoolman_id=m.spoolman_filament_id, fdb_filament_id=m.filamentdb_id,
                        field_name="material_tags", old_value=sm_sig_now, new_value=fdb_sig_now,
                    )
                    result.updated += 1
                except Exception as exc:
                    logger.error("Cycle %s: finish-tag FDB→SM failed %s: %s", cycle_id, m.spoolman_filament_id, exc)
                    _log(
                        db, cycle_id, "filamentdb_to_spoolman", "error", "filament",
                        spoolman_id=m.spoolman_filament_id, fdb_filament_id=m.filamentdb_id,
                        field_name="material_tags", error_message=str(exc),
                    )
                    result.errors += 1
            else:
                result.preview.append({
                    "action": "update",
                    "entity_type": "filament",
                    "direction": "filamentdb_to_spoolman",
                    "label": getattr(sm_fil, "name", None) or fdb_list.name,
                    "field": "material_tags",
                    "old": sm_sig_now, "new": fdb_sig_now,
                    "reason": None,
                    "spoolman_id": m.spoolman_filament_id,
                    "fdb_filament_id": m.filamentdb_id,
                    "fdb_spool_id": None,
                })
                result.updated += 1


# ---------------------------------------------------------------------------
# New-spool detection (FR-12) + new-record policies
# ---------------------------------------------------------------------------


def _sm_filament_identity(sm_fil: Any) -> dict:
    """Extract vendor/name/color_hex/material from a SpoolmanFilament for storage."""
    vendor_obj = getattr(sm_fil, "vendor", None)
    vendor_name = vendor_obj.name if (vendor_obj and hasattr(vendor_obj, "name")) else None
    return {
        "vendor": vendor_name,
        "name": getattr(sm_fil, "name", None),
        "color_hex": getattr(sm_fil, "color_hex", None),
        "material": getattr(sm_fil, "material", None),
    }


def _fdb_filament_identity(fdb_fil: Any) -> dict:
    """Extract vendor/name/color_hex/material from an FDBFilament for storage."""
    return {
        "vendor": getattr(fdb_fil, "vendor", None),
        "name": getattr(fdb_fil, "name", None),
        "color_hex": getattr(fdb_fil, "color", None),
        "material": getattr(fdb_fil, "type", None),
    }


def _upsert_new_record_conflict(
    db: Session,
    cycle_id: str,
    entity_type: str,
    field_name: str,  # "new_filament" | "new_spool"
    *,
    spoolman_id: int | None = None,
    fdb_filament_id: str | None = None,
    fdb_spool_id: str | None = None,
    spoolman_value: Any = None,
    filamentdb_value: Any = None,
) -> None:
    """Upsert a new_filament or new_spool conflict (unconditional replace-on-resync).

    Before inserting, deletes any existing OPEN conflict for the same item+kind so
    there is at most one open conflict per (item, conflict_type) at all times.  This
    prevents the duplicate-accumulation bug where the same unmapped record re-queues
    every cycle.

    The match key is (entity_type, field_name, spoolman_id OR fdb_filament_id OR
    fdb_spool_id) — never item alone, so an unrelated cross_system conflict on the
    same item is never wiped.
    """
    # Delete any existing OPEN conflict for this same item + kind.
    q = (
        db.query(Conflict)
        .filter(
            Conflict.resolved_at.is_(None),
            Conflict.entity_type == entity_type,
            Conflict.field_name == field_name,
        )
    )
    if spoolman_id is not None:
        q = q.filter(Conflict.spoolman_id == spoolman_id)
    if fdb_filament_id is not None:
        q = q.filter(Conflict.filamentdb_filament_id == fdb_filament_id)
    if fdb_spool_id is not None:
        q = q.filter(Conflict.filamentdb_spool_id == fdb_spool_id)
    for old in q.all():
        db.delete(old)

    # Insert the fresh conflict row with a distinct conflict_type for clarity.
    db.add(
        Conflict(
            entity_type=entity_type,
            spoolman_id=spoolman_id,
            filamentdb_filament_id=fdb_filament_id,
            filamentdb_spool_id=fdb_spool_id,
            field_name=field_name,
            spoolman_value=json.dumps(spoolman_value) if spoolman_value is not None else None,
            filamentdb_value=json.dumps(filamentdb_value) if filamentdb_value is not None else None,
            conflict_type=field_name,  # "new_filament" | "new_spool"
        )
    )
    _log(
        db, cycle_id, "conflict", "conflict", entity_type,
        spoolman_id=spoolman_id,
        fdb_filament_id=fdb_filament_id,
        fdb_spool_id=fdb_spool_id,
        field_name=field_name,
        old_value=spoolman_value,
        new_value=filamentdb_value,
    )


def _queue_if_new_filament(db: Session, cycle_id: str, sm_spool: SpoolmanSpool) -> None:
    """Upsert a new_filament conflict for the SM filament that owns sm_spool.

    Used when new_filament_policy == manual_review: the user must choose to link
    or create a FDB filament before the spool can be synced.  Unconditional
    replace-on-resync keeps at most one open conflict per (filament, new_filament).
    """
    sm_fil = sm_spool.filament
    sm_fil_id = sm_fil.id if sm_fil else None
    if sm_fil_id is None:
        return
    identity = _sm_filament_identity(sm_fil) if sm_fil else {}
    _upsert_new_record_conflict(
        db, cycle_id, "filament", "new_filament",
        spoolman_id=sm_fil_id,
        spoolman_value=identity,
    )


async def _handle_new_sm_spool(
    db: Session,
    cycle_id: str,
    result: CycleResult,
    dry_run: bool,
    sm_spool: SpoolmanSpool,
    filament_mappings_by_sm_filament: dict[int, FilamentMapping],
    fdb_filaments: dict[str, FDBFilament],
    filamentdb: FilamentDBClient,
    spoolman: SpoolmanClient,
    fdb_field_name: str,
    precision: int = 2,
    *,
    new_filament_policy: str = "manual_review",
    new_spool_policy: str = "manual_review",
    variant_parent_mode: str = "unset",
    variant_keywords: list[str] | None = None,
    container_parent_marker: str = "(Master)",
) -> None:
    """Handle a Spoolman spool that has no filamentdb_spool_id extra field yet.

    Two-tier policy:
    - Filament tier (no FilamentMapping): if new_filament_policy == auto_import, call
      the single-record import helper (creates the filament + mapping + spools); else
      queue a new_filament conflict + a new_spool conflict (held pending filament).
    - Spool tier (FilamentMapping exists): if new_spool_policy == auto_import, create
      the FDB spool; else queue an actionable new_spool conflict.
    """
    filament_mapping = filament_mappings_by_sm_filament.get(sm_spool.filament.id)

    if filament_mapping is None:
        # No filament mapping — either auto-import the filament or queue for review.
        if dry_run:
            result.preview.append({
                "action": "conflict",
                "entity_type": "spool",
                "direction": None,
                "label": _preview_label(sm_spool=sm_spool),
                "field": "new_spool",
                "old": None, "new": None,
                "reason": "no filament mapping for this Spoolman spool",
                "spoolman_id": sm_spool.id,
                "fdb_filament_id": None,
                "fdb_spool_id": None,
            })
            result.conflicts += 1
            return

        if new_filament_policy == "auto_import":
            # Detect if this SM filament is a potential variant (non-standalone).
            from app.core.matcher import sm_variant_cluster_key
            from app.core.single_record_import import import_single_sm_filament
            sm_fil = sm_spool.filament
            cluster_key = sm_variant_cluster_key(sm_fil, keywords=variant_keywords)
            is_potential_variant = bool(cluster_key[0] or cluster_key[2])  # vendor or finish token

            # Per LOCKED Q2: if unset and this is a variant candidate, HOLD for review.
            if variant_parent_mode == "unset" and is_potential_variant:
                logger.info(
                    "Cycle %s: SM filament %s may be a variant cluster member; "
                    "variant_parent_mode=unset → holding for review (new_filament conflict)",
                    cycle_id, sm_fil.id,
                )
                _queue_if_new_filament(db, cycle_id, sm_spool)
                result.conflicts += 1
                return

            # Auto-import: create the filament + mapping + spools via the shared helper.
            logger.info(
                "Cycle %s: new_filament_policy=auto_import — importing SM filament %s into FDB",
                cycle_id, sm_fil.id,
            )
            try:
                import_res = await import_single_sm_filament(
                    db, cycle_id, spoolman, filamentdb,
                    sm_fil.id,
                    filament_action="create",
                    precision=precision,
                    include_empty_spools=True,
                    variant_parent_mode=variant_parent_mode if variant_parent_mode != "unset" else "promote_color",
                    variant_keywords=variant_keywords,
                    container_parent_marker=container_parent_marker,
                )
                result.created += import_res.created
                result.updated += import_res.updated
                result.errors += import_res.failed
                if import_res.failed > 0:
                    logger.warning(
                        "Cycle %s: auto-import of SM filament %s had %d failure(s)",
                        cycle_id, sm_fil.id, import_res.failed,
                    )
            except Exception as exc:
                logger.error(
                    "Cycle %s: auto-import of SM filament %s failed: %s",
                    cycle_id, sm_fil.id, exc,
                )
                _log(
                    db, cycle_id, "spoolman_to_filamentdb", "error", "filament",
                    spoolman_id=sm_spool.id,
                    error_message=f"auto-import failed: {exc}",
                )
                result.errors += 1
        else:
            # manual_review: queue new_filament + new_spool conflicts (actionable by user).
            _queue_if_new_filament(db, cycle_id, sm_spool)
            result.conflicts += 1
        return

    fdb_filament = fdb_filaments.get(filament_mapping.filamentdb_id)
    if fdb_filament is None:
        if not dry_run:
            _log(
                db, cycle_id, "spoolman_to_filamentdb", "error", "spool",
                spoolman_id=sm_spool.id, fdb_filament_id=filament_mapping.filamentdb_id,
                error_message="Mapped FDB filament not found in current fetch",
            )
        result.errors += 1
        return

    if dry_run:
        result.preview.append({
            "action": "create",
            "entity_type": "spool",
            "direction": "spoolman_to_filamentdb",
            "label": _preview_label(sm_spool=sm_spool, fdb_filament=fdb_filament),
            "field": None,
            "old": None, "new": None,
            "reason": None,
            "spoolman_id": sm_spool.id,
            "fdb_filament_id": fdb_filament.id,
            "fdb_spool_id": None,
        })
        result.created += 1
        return

    # Filament is mapped — apply new_spool_policy.
    if new_spool_policy != "auto_import":
        # manual_review: upsert an actionable new_spool conflict (replaces stale row).
        sm_fil = sm_spool.filament
        identity = _sm_filament_identity(sm_fil) if sm_fil else {}
        _upsert_new_record_conflict(
            db, cycle_id, "spool", "new_spool",
            spoolman_id=sm_spool.id,
            fdb_filament_id=fdb_filament.id,
            spoolman_value=identity,
        )
        result.conflicts += 1
        return

    # auto_import: create the spool now.
    tare = fdb_filament.spoolWeight
    gross, used_default = spoolman_to_fdb_gross(sm_spool.remaining_weight or 0, tare, precision=precision)
    if used_default:
        logger.warning("Cycle %s: using default tare for new FDB spool from SM spool %s", cycle_id, sm_spool.id)

    try:
        spool_payload = {
            "totalWeight": gross,
            fdb_field_name: str(sm_spool.id),
        }
        # Preserve the spool's age (purchase/opened dates) from Spoolman.
        spool_payload.update(spool_provenance_dates(sm_spool))
        raw = await filamentdb.create_spool(fdb_filament.id, spool_payload)
        new_fdb_spool_id = extract_created_spool_id(
            raw,
            label_field=fdb_field_name,
            label_value=str(sm_spool.id),
        )

        # Write cross-ref IDs back to Spoolman spool
        await spoolman.update_spool(sm_spool.id, {
            "extra": {
                _settings.spoolman_field_filamentdb_id: encode_extra_value(fdb_filament.id),
                _settings.spoolman_field_filamentdb_spool_id: encode_extra_value(new_fdb_spool_id),
                _settings.spoolman_field_filamentdb_parent_id: encode_extra_value(
                    filament_mapping.filamentdb_parent_id or ""
                ),
            }
        })

        db.add(SpoolMapping(
            spoolman_spool_id=sm_spool.id,
            filamentdb_filament_id=fdb_filament.id,
            filamentdb_spool_id=new_fdb_spool_id,
            filament_mapping_id=filament_mapping.id,
        ))
        _log(
            db, cycle_id, "spoolman_to_filamentdb", "create", "spool",
            spoolman_id=sm_spool.id, fdb_filament_id=fdb_filament.id,
            fdb_spool_id=new_fdb_spool_id,
        )
        result.created += 1
    except Exception as exc:
        logger.error("Cycle %s: failed to create FDB spool from SM spool %s: %s", cycle_id, sm_spool.id, exc)
        _log(
            db, cycle_id, "spoolman_to_filamentdb", "error", "spool",
            spoolman_id=sm_spool.id, fdb_filament_id=fdb_filament.id,
            error_message=str(exc),
        )
        result.errors += 1


async def _handle_new_fdb_spool(
    db: Session,
    cycle_id: str,
    result: CycleResult,
    dry_run: bool,
    fdb_filament: FDBFilament,
    fdb_spool: FDBSpool,
    filament_mappings_by_fdb: dict[str, FilamentMapping],
    spoolman: SpoolmanClient,
    filamentdb: FilamentDBClient,
    fdb_field_name: str,
    precision: int = 2,
    *,
    new_filament_policy: str = "manual_review",
    new_spool_policy: str = "manual_review",
) -> None:
    """Handle a Filament DB spool that has no Spoolman ID in its label yet.

    Two-tier policy (FDB→SM direction):
    - Filament tier (no FilamentMapping): if new_filament_policy == auto_import, call the
      single-record import helper; else queue a new_filament conflict + new_spool conflict.
    - Spool tier (FilamentMapping exists): if new_spool_policy == auto_import, create the
      SM spool; else queue an actionable new_spool conflict.
    """
    filament_mapping = filament_mappings_by_fdb.get(fdb_filament.id)

    if filament_mapping is None:
        if dry_run:
            result.preview.append({
                "action": "conflict",
                "entity_type": "spool",
                "direction": None,
                "label": _preview_label(fdb_filament=fdb_filament),
                "field": "new_spool",
                "old": None, "new": None,
                "reason": "no filament mapping for this FDB spool",
                "spoolman_id": None,
                "fdb_filament_id": fdb_filament.id,
                "fdb_spool_id": fdb_spool.id,
            })
            result.conflicts += 1
            return

        if new_filament_policy == "auto_import":
            from app.core.single_record_import import import_single_fdb_filament
            logger.info(
                "Cycle %s: new_filament_policy=auto_import — importing FDB filament %s into Spoolman",
                cycle_id, fdb_filament.id,
            )
            try:
                import_res = await import_single_fdb_filament(
                    db, cycle_id, spoolman, filamentdb,
                    fdb_filament.id,
                    precision=precision,
                )
                result.created += import_res.created
                result.updated += import_res.updated
                result.errors += import_res.failed
                if import_res.failed > 0:
                    logger.warning(
                        "Cycle %s: auto-import of FDB filament %s had %d failure(s)",
                        cycle_id, fdb_filament.id, import_res.failed,
                    )
            except Exception as exc:
                logger.error(
                    "Cycle %s: auto-import of FDB filament %s failed: %s",
                    cycle_id, fdb_filament.id, exc,
                )
                _log(
                    db, cycle_id, "filamentdb_to_spoolman", "error", "filament",
                    fdb_filament_id=fdb_filament.id,
                    error_message=f"auto-import failed: {exc}",
                )
                result.errors += 1
        else:
            # manual_review: upsert new_filament conflict (replaces stale row each cycle).
            identity = _fdb_filament_identity(fdb_filament)
            _upsert_new_record_conflict(
                db, cycle_id, "filament", "new_filament",
                fdb_filament_id=fdb_filament.id,
                filamentdb_value=identity,
            )
            result.conflicts += 1
        return

    if dry_run:
        result.preview.append({
            "action": "create",
            "entity_type": "spool",
            "direction": "filamentdb_to_spoolman",
            "label": _preview_label(fdb_filament=fdb_filament),
            "field": None,
            "old": None, "new": None,
            "reason": None,
            "spoolman_id": None,
            "fdb_filament_id": fdb_filament.id,
            "fdb_spool_id": fdb_spool.id,
        })
        result.created += 1
        return

    # Filament is mapped — apply new_spool_policy.
    if new_spool_policy != "auto_import":
        # manual_review: upsert an actionable new_spool conflict (replaces stale row).
        identity = _fdb_filament_identity(fdb_filament)
        _upsert_new_record_conflict(
            db, cycle_id, "spool", "new_spool",
            fdb_filament_id=fdb_filament.id,
            fdb_spool_id=fdb_spool.id,
            filamentdb_value=identity,
        )
        result.conflicts += 1
        return

    # auto_import: create the spool now.
    tare = fdb_filament.spoolWeight
    net, used_default = fdb_to_spoolman_net(fdb_spool.totalWeight or 0, tare, precision=precision)
    if used_default:
        logger.warning("Cycle %s: using default tare for new SM spool from FDB spool %s", cycle_id, fdb_spool.id)

    try:
        new_sm_spool = await spoolman.create_spool({
            "filament_id": filament_mapping.spoolman_filament_id,
            "remaining_weight": net,
            "extra": {
                _settings.spoolman_field_filamentdb_id: encode_extra_value(fdb_filament.id),
                _settings.spoolman_field_filamentdb_spool_id: encode_extra_value(fdb_spool.id),
                _settings.spoolman_field_filamentdb_parent_id: encode_extra_value(
                    filament_mapping.filamentdb_parent_id or ""
                ),
            },
        })

        # Write SM ID back to FDB spool label
        await filamentdb.update_spool(fdb_filament.id, fdb_spool.id, {fdb_field_name: str(new_sm_spool.id)})

        db.add(SpoolMapping(
            spoolman_spool_id=new_sm_spool.id,
            filamentdb_filament_id=fdb_filament.id,
            filamentdb_spool_id=fdb_spool.id,
            filament_mapping_id=filament_mapping.id,
        ))
        _log(
            db, cycle_id, "filamentdb_to_spoolman", "create", "spool",
            spoolman_id=new_sm_spool.id, fdb_filament_id=fdb_filament.id,
            fdb_spool_id=fdb_spool.id,
        )
        result.created += 1
    except Exception as exc:
        logger.error("Cycle %s: failed to create SM spool from FDB spool %s: %s", cycle_id, fdb_spool.id, exc)
        _log(
            db, cycle_id, "filamentdb_to_spoolman", "error", "spool",
            fdb_filament_id=fdb_filament.id, fdb_spool_id=fdb_spool.id,
            error_message=str(exc),
        )
        result.errors += 1


# ---------------------------------------------------------------------------
# Main cycle
# ---------------------------------------------------------------------------


async def run_sync_cycle(
    db: Session,
    spoolman: SpoolmanClient,
    filamentdb: FilamentDBClient,
    *,
    dry_run: bool = False,
    cycle_id: str | None = None,
) -> CycleResult:
    """Run one sync cycle (FR-8).

    dry_run=True computes and returns the full changeset but applies nothing and
    does not advance snapshots (FR-14).

    cycle_id may be injected by tests for determinism; generated internally otherwise.
    """
    if cycle_id is None:
        cycle_id = str(uuid.uuid4())

    result = CycleResult(cycle_id=cycle_id, dry_run=dry_run)
    config = _read_config(db)

    # New two-axis model — read per-category direction and conflict policy.
    weight_direction: str = config.get("weight_sync_direction", "spoolman_to_filamentdb")
    weight_policy: str = config.get("weight_conflict_policy", "manual")
    matprop_direction: str = config.get("material_properties_sync_direction", "filamentdb_to_spoolman")
    matprop_policy: str = config.get("material_properties_conflict_policy", "manual")
    archive_direction: str = config.get("archive_sync_direction", "two_way")
    archive_policy: str = config.get("archive_conflict_policy", "manual")
    new_spool_direction: str = config.get("new_spool_sync_direction", "two_way")
    # New-record handling policies.
    new_filament_policy: str = config.get("new_filament_policy", "manual_review") or "manual_review"
    new_spool_policy: str = config.get("new_spool_policy", "manual_review") or "manual_review"
    # Variant grouping config (needed by new-filament auto-import path).
    _engine_variant_parent_mode: str = config.get("variant_parent_mode", "unset") or "unset"
    _engine_variant_keywords_raw: str = config.get("variant_line_keywords", "") or ""
    _engine_variant_keywords: list[str] = [
        k.strip() for k in _engine_variant_keywords_raw.split(",") if k.strip()
    ] if _engine_variant_keywords_raw else None  # type: ignore[assignment]
    _engine_container_marker: str = config.get("container_parent_marker", "(Master)") or "(Master)"

    threshold: float = float(config.get("sync_weight_threshold_grams", 2.0))
    precision: int = int(config.get("weight_precision_decimals", 2))
    fdb_field_name: str = _settings.filamentdb_spoolman_id_field  # default "label"

    # ---- Upstream version gate ----
    # Refuse to sync against a KNOWN below-minimum upstream (no writes). Skips the
    # whole cycle so auto-sync becomes a no-op until the user upgrades.
    fdb_version = await filamentdb.get_version()
    sm_version: str | None = None
    try:
        sm_version = (await spoolman.health()).get("version")
    except Exception:
        sm_version = None
    blocked = incompatibilities(fdb_version, sm_version)
    if blocked:
        result.blocked_reasons = blocked
        msg = "Sync disabled — " + "; ".join(blocked)
        logger.warning("Cycle %s: %s", cycle_id, msg)
        if not dry_run:
            _log(db, cycle_id, "auto", "skip", "spool", error_message=msg)
            db.commit()
        return result

    # Structured multicolor sync requires Filament DB >= 1.33.0 (color/secondaryColors/optTags).
    multicolor_supported = version_gte(fdb_version, MULTICOLOR_MIN_FDB)

    # ---- Fetch upstream state ----
    try:
        sm_spools_all = await spoolman.get_spools()
        sm_filaments_all = await spoolman.get_filaments()
        fdb_filaments_all = await filamentdb.get_filaments()
    except Exception as exc:
        logger.error("Cycle %s: failed to fetch upstream state: %s", cycle_id, exc)
        if not dry_run:
            _log(db, cycle_id, "spoolman_to_filamentdb", "error", "spool", error_message=str(exc))
            db.commit()
        result.errors += 1
        return result

    # Active-only set: used for NEW-spool detection so an unmapped archived spool is
    # never auto-imported during ongoing sync (preserves the wizard import gate).
    sm_spools: dict[int, SpoolmanSpool] = {s.id: s for s in sm_spools_all if not s.archived}
    # Active + archived set: used for MAPPED-pair diffing so a mapped spool that flips
    # to archived still reaches the differ and its lifecycle state can be mirrored.
    sm_spools_with_archived: dict[int, SpoolmanSpool] = {s.id: s for s in sm_spools_all}
    sm_all_ids: set[int] = {s.id for s in sm_spools_all}  # includes archived
    sm_filaments: dict[int, Any] = {f.id: f for f in sm_filaments_all}
    fdb_filaments: dict[str, FDBFilament] = {f.id: f for f in fdb_filaments_all}

    # Build FDB spool lookup: fdb_spool_id → (fdb_filament_id, FDBSpool)
    fdb_spool_index: dict[str, tuple[str, FDBSpool]] = {}
    for fdb_f in fdb_filaments_all:
        for spool in fdb_f.spools:
            fdb_spool_index[spool.id] = (fdb_f.id, spool)

    # Load mappings
    spool_mappings: list[SpoolMapping] = db.query(SpoolMapping).all()
    filament_mappings: list[FilamentMapping] = db.query(FilamentMapping).all()

    mapped_sm_spool_ids: set[int] = {m.spoolman_spool_id for m in spool_mappings}
    mapped_fdb_spool_ids: set[str] = {m.filamentdb_spool_id for m in spool_mappings}

    # ---- Clear stale new_spool conflicts for now-mapped spools ----
    # A spool may have accumulated open new_spool conflicts before it was mapped
    # (e.g. via the wizard). Auto-resolve them now so the queue stays clean.
    if not dry_run and (mapped_sm_spool_ids or mapped_fdb_spool_ids):
        _now = datetime.datetime.now(datetime.timezone.utc)
        stale_conflicts = (
            db.query(Conflict)
            .filter(
                Conflict.resolved_at.is_(None),
                Conflict.entity_type == "spool",
                Conflict.field_name == "new_spool",
            )
            .all()
        )
        for stale in stale_conflicts:
            if (
                (stale.spoolman_id is not None and stale.spoolman_id in mapped_sm_spool_ids)
                or (stale.filamentdb_spool_id is not None and stale.filamentdb_spool_id in mapped_fdb_spool_ids)
            ):
                stale.resolved_at = _now
                stale.resolution = "resolved_mapped"
                _log(
                    db, cycle_id, "auto", "info", "spool",
                    spoolman_id=stale.spoolman_id,
                    fdb_spool_id=stale.filamentdb_spool_id,
                    field_name="new_spool",
                    error_message="auto-resolved stale new_spool conflict (spool is now mapped)",
                )

    # Synthetic parents (is_synthetic_parent=True) have no Spoolman counterpart.
    # Exclude them from both lookup dicts so the engine never tries to sync them.
    # They are tracked solely for bridge-side parent relationship bookkeeping.
    filament_mappings_by_sm: dict[int, FilamentMapping] = {
        m.spoolman_filament_id: m
        for m in filament_mappings
        if not getattr(m, "is_synthetic_parent", False) and m.spoolman_filament_id is not None
    }
    filament_mappings_by_fdb: dict[str, FilamentMapping] = {
        m.filamentdb_id: m
        for m in filament_mappings
        if not getattr(m, "is_synthetic_parent", False)
    }
    # Set of FDB filament ids that are bridge-owned synthetic container parents.
    # Used to guard the new-FDB-spool detection path.
    _synthetic_parent_fdb_ids: set[str] = {
        m.filamentdb_id
        for m in filament_mappings
        if getattr(m, "is_synthetic_parent", False)
    }

    # ---- Opportunistic identity backfill (OQ-1) ----
    # Self-heal legacy FilamentMapping rows that were created before the identity
    # column existed.  When the SM or FDB filament is in hand during this cycle,
    # set the identity blob so build_mapping_rows can display filament-only rows.
    if not dry_run:
        for fm in filament_mappings:
            if fm.identity is not None or fm.is_synthetic_parent:
                continue
            sm_fil = sm_filaments.get(fm.spoolman_filament_id) if fm.spoolman_filament_id else None
            fdb_fil = fdb_filaments.get(fm.filamentdb_id)
            if sm_fil is not None:
                fm.identity = json.dumps(_sm_filament_identity(sm_fil))
            elif fdb_fil is not None:
                fm.identity = json.dumps(_fdb_filament_identity(fdb_fil))

    # ---- Resolve field mappings (FR-11) ----
    field_maps: list[FieldMapping] = []
    if filament_mappings:
        try:
            sm_field_defs = await spoolman.get_field_definitions("spool")
            sm_extra_keys = {fd.key for fd in sm_field_defs}
        except Exception:
            sm_extra_keys = set()
        field_maps = resolve_field_map(_settings, sm_extra_keys)

    # ---- Process mapped spool pairs ----
    for mapping in spool_mappings:
        # Mapped pairs look up against active + archived so a mapped spool that flips
        # to archived still reaches the diff loop (its archive bit gets mirrored to FDB
        # in the lifecycle pass). Unmapped archived spools never enter this loop.
        sm_spool = sm_spools_with_archived.get(mapping.spoolman_spool_id)
        fdb_entry = fdb_spool_index.get(mapping.filamentdb_spool_id)

        if sm_spool is None:
            if mapping.spoolman_spool_id not in sm_all_ids:
                # Not archived — gone entirely.
                # Branch A stale check: if FDB spool is also absent, both sides are
                # gone → stale connection; purge bridge-local rows instead of
                # surfacing a deletion conflict.
                if mapping.filamentdb_spool_id not in fdb_spool_index:
                    # Both sides gone — stale connection.
                    if dry_run:
                        fdb_fil = fdb_filaments.get(mapping.filamentdb_filament_id)
                        result.preview.append({
                            "action": "skip",
                            "entity_type": "spool",
                            "direction": None,
                            "label": _preview_label(fdb_filament=fdb_fil),
                            "field": None,
                            "old": None, "new": None,
                            "reason": "stale connection — would remove from bridge (upstream deleted, no live link)",
                            "spoolman_id": mapping.spoolman_spool_id,
                            "fdb_filament_id": mapping.filamentdb_filament_id,
                            "fdb_spool_id": mapping.filamentdb_spool_id,
                        })
                    else:
                        _purge_stale_mapping(
                            db, cycle_id, mapping,
                            reason="stale mapping purged: both sides deleted",
                        )
                    result.skipped += 1
                else:
                    # FDB spool present — still linked counterpart to protect.
                    # Queue a deletion conflict as before.
                    if dry_run:
                        fdb_fil = fdb_filaments.get(mapping.filamentdb_filament_id)
                        result.preview.append({
                            "action": "conflict",
                            "entity_type": "spool",
                            "direction": "conflict",
                            "label": _preview_label(fdb_filament=fdb_fil),
                            "field": DELETION_FIELD,
                            "old": None, "new": None,
                            "reason": "record deleted upstream (spoolman)",
                            "spoolman_id": mapping.spoolman_spool_id,
                            "fdb_filament_id": mapping.filamentdb_filament_id,
                            "fdb_spool_id": mapping.filamentdb_spool_id,
                        })
                    else:
                        _queue_deletion_conflict(db, cycle_id, mapping, deleted_side="spoolman")
                    result.conflicts += 1
            else:
                # Defensive: the SM spool id is in sm_all_ids but missing from the
                # combined (active + archived) lookup — should be impossible since the
                # combined dict is keyed by every fetched spool. Treat as a benign skip
                # rather than a deletion. (Mapped archived spools now reach the diff loop
                # and are mirrored by the lifecycle pass; they no longer land here.)
                if dry_run:
                    fdb_fil = fdb_filaments.get(mapping.filamentdb_filament_id)
                    result.preview.append({
                        "action": "skip",
                        "entity_type": "spool",
                        "direction": None,
                        "label": _preview_label(fdb_filament=fdb_fil),
                        "field": None,
                        "old": None, "new": None,
                        "reason": "Spoolman spool not in active set",
                        "spoolman_id": mapping.spoolman_spool_id,
                        "fdb_filament_id": mapping.filamentdb_filament_id,
                        "fdb_spool_id": mapping.filamentdb_spool_id,
                    })
                else:
                    _log(
                        db, cycle_id, "spoolman_to_filamentdb", "skip", "spool",
                        spoolman_id=mapping.spoolman_spool_id,
                        fdb_filament_id=mapping.filamentdb_filament_id,
                        fdb_spool_id=mapping.filamentdb_spool_id,
                        error_message="SM spool not in current fetch set",
                    )
                result.skipped += 1
            continue

        if fdb_entry is None:
            # FDB spool absent from current fetch — deleted upstream.
            # Branch B stale check: read the surviving Spoolman spool's cross-ref.
            # If it is empty/None/blank (user cleared it — unlinked), this is a
            # stale connection → purge bridge-local rows.
            # If it still carries the FDB spool ID (still linked to the now-deleted
            # FDB spool), queue a deletion conflict to protect the SM spool.
            sm_fdb_spool_id_raw = sm_spool.extra.get(_settings.spoolman_field_filamentdb_spool_id)
            sm_fdb_spool_id = decode_extra_value(sm_fdb_spool_id_raw)
            if not sm_fdb_spool_id:
                # Cross-ref cleared — stale connection.
                if dry_run:
                    result.preview.append({
                        "action": "skip",
                        "entity_type": "spool",
                        "direction": None,
                        "label": _preview_label(sm_spool=sm_spool),
                        "field": None,
                        "old": None, "new": None,
                        "reason": "stale connection — would remove from bridge (upstream deleted, no live link)",
                        "spoolman_id": mapping.spoolman_spool_id,
                        "fdb_filament_id": mapping.filamentdb_filament_id,
                        "fdb_spool_id": mapping.filamentdb_spool_id,
                    })
                else:
                    _purge_stale_mapping(
                        db, cycle_id, mapping,
                        reason="stale mapping purged: FDB spool deleted and Spoolman cross-ref cleared",
                    )
                result.skipped += 1
            else:
                # Cross-ref still set — SM spool is still linked to the deleted FDB
                # spool; queue a deletion conflict so the user can decide.
                if dry_run:
                    result.preview.append({
                        "action": "conflict",
                        "entity_type": "spool",
                        "direction": "conflict",
                        "label": _preview_label(sm_spool=sm_spool),
                        "field": DELETION_FIELD,
                        "old": None, "new": None,
                        "reason": "record deleted upstream (filamentdb)",
                        "spoolman_id": mapping.spoolman_spool_id,
                        "fdb_filament_id": mapping.filamentdb_filament_id,
                        "fdb_spool_id": mapping.filamentdb_spool_id,
                    })
                else:
                    _queue_deletion_conflict(db, cycle_id, mapping, deleted_side="filamentdb")
                result.conflicts += 1
            continue

        fdb_filament_id, fdb_spool = fdb_entry

        # Load snapshots
        sm_snap = _get_snapshot(db, "spoolman", "spool", str(sm_spool.id))
        fdb_snap = _get_snapshot(db, "filamentdb", "spool", fdb_spool.id)

        # First time we see this pair — store baseline, no diff yet
        if sm_snap is None or fdb_snap is None:
            if dry_run:
                result.preview.append({
                    "action": "skip",
                    "entity_type": "spool",
                    "direction": None,
                    "label": _preview_label(sm_spool=sm_spool, fdb_filament=fdb_filaments.get(fdb_filament_id)),
                    "field": None,
                    "old": None, "new": None,
                    "reason": "first sync of this pair — baseline stored, no diff yet",
                    "spoolman_id": sm_spool.id,
                    "fdb_filament_id": fdb_filament_id,
                    "fdb_spool_id": fdb_spool.id,
                })
            else:
                _upsert_snapshot(db, "spoolman", "spool", str(sm_spool.id), _sm_snapshot_dict(sm_spool, field_maps))
                # Include _field_values in the FDB baseline when field mappings are
                # active so the very next cycle can compare current vs snapshot
                # values instead of always seeing None as the baseline.
                if field_maps:
                    try:
                        _fdb_baseline_detail = await filamentdb.get_filament(fdb_filament_id)
                        _upsert_snapshot(db, "filamentdb", "spool", fdb_spool.id, _fdb_snapshot_dict(fdb_spool, _fdb_baseline_detail, field_maps))
                    except Exception as _exc:
                        logger.warning("Cycle %s: could not fetch FDB detail for baseline %s: %s", cycle_id, fdb_filament_id, _exc)
                        _upsert_snapshot(db, "filamentdb", "spool", fdb_spool.id, _fdb_snapshot_dict(fdb_spool))
                else:
                    _upsert_snapshot(db, "filamentdb", "spool", fdb_spool.id, _fdb_snapshot_dict(fdb_spool))
            result.skipped += 1
            continue

        # Track preview length before weight + field passes so we can detect
        # whether this pair emitted anything (dry-run only).
        _preview_len_before_pair = len(result.preview)

        # ---- Diff ----
        cs = diff_spool_pair(
            sm_spool=sm_spool,
            fdb_spool=fdb_spool,
            fdb_filament_id=fdb_filament_id,
            sm_snapshot=sm_snap,
            fdb_snapshot=fdb_snap,
            threshold=threshold,
        )

        # ---- Weight sync ----
        today_iso = datetime.date.today().isoformat()

        # Determine weight change flags for the resolver.
        weight_sm_changed = cs.sm_weight_change is not None or cs.weight_conflict
        weight_fdb_changed = cs.fdb_weight_change is not None or cs.weight_conflict

        # For newest_wins: parse and anchor timestamps to captured_at.
        weight_sm_ts: datetime.datetime | None = None
        weight_fdb_ts: datetime.datetime | None = None
        if weight_policy == "newest_wins" and weight_direction == "two_way":
            sm_captured_at = _get_snapshot_captured_at(db, "spoolman", "spool", str(sm_spool.id))
            fdb_captured_at = _get_snapshot_captured_at(db, "filamentdb", "spool", fdb_spool.id)
            # Use the earlier of the two as the "last-sync time" anchor.
            captured_at_anchor: datetime.datetime | None = None
            if sm_captured_at and fdb_captured_at:
                captured_at_anchor = min(sm_captured_at, fdb_captured_at)
            elif sm_captured_at or fdb_captured_at:
                captured_at_anchor = sm_captured_at or fdb_captured_at
            # SM: last_used fallback registered — parse and anchor.
            raw_sm_ts = getattr(sm_spool, "last_used", None) or getattr(sm_spool, "registered", None)
            weight_sm_ts = _ts_after_captured_at(_parse_iso(raw_sm_ts), captured_at_anchor)
            # FDB: updatedAt on the filament (extra="allow" in the schema).
            fdb_filament_for_ts = fdb_filaments.get(fdb_filament_id)
            raw_fdb_ts = getattr(fdb_filament_for_ts, "updatedAt", None) if fdb_filament_for_ts else None
            weight_fdb_ts = _ts_after_captured_at(_parse_iso(raw_fdb_ts), captured_at_anchor)

        weight_action = resolve_sync_action(
            sm_changed=weight_sm_changed,
            fdb_changed=weight_fdb_changed,
            direction=weight_direction,
            policy=weight_policy,
            sm_ts=weight_sm_ts,
            fdb_ts=weight_fdb_ts,
        )

        if weight_action == SyncAction.QUEUE_CONFLICT:
            if not dry_run:
                if not _has_open_conflict(
                    db, "spool", "weight",
                    spoolman_id=sm_spool.id,
                    fdb_spool_id=fdb_spool.id,
                ):
                    _queue_conflict(
                        db, cycle_id, "spool", "weight",
                        spoolman_id=sm_spool.id,
                        fdb_filament_id=fdb_filament_id,
                        fdb_spool_id=fdb_spool.id,
                        spoolman_value=sm_spool.remaining_weight,
                        filamentdb_value=fdb_spool.totalWeight,
                    )
                    result.conflicts += 1
            else:
                result.preview.append({
                    "action": "conflict",
                    "entity_type": "spool",
                    "direction": None,
                    "label": _preview_label(sm_spool=sm_spool, fdb_filament=fdb_filaments.get(fdb_filament_id)),
                    "field": "weight",
                    "old": sm_spool.remaining_weight,
                    "new": fdb_spool.totalWeight,
                    "reason": "both sides changed weight (old=SM remaining, new=FDB totalWeight)",
                    "spoolman_id": sm_spool.id,
                    "fdb_filament_id": fdb_filament_id,
                    "fdb_spool_id": fdb_spool.id,
                })
                result.conflicts += 1

        elif weight_action == SyncAction.PUSH_SM_TO_FDB:
            # SM → FDB weight sync (FR-9)
            old_w = cs.sm_weight_change.old_value if cs.sm_weight_change else (sm_snap or {}).get("remaining_weight")
            new_w = cs.sm_weight_change.new_value if cs.sm_weight_change else sm_spool.remaining_weight
            delta = (old_w or 0.0) - (new_w or 0.0)
            fdb_filament = fdb_filaments.get(fdb_filament_id)
            tare = fdb_filament.spoolWeight if fdb_filament else None

            try:
                if not dry_run:
                    if delta > 0:
                        # Weight decreased → log usage entry (FR-9). Filament DB
                        # reduces totalWeight by `delta` when the usage is logged.
                        await filamentdb.log_usage(
                            fdb_filament_id, fdb_spool.id, delta,
                            job_label=f"spoolman sync {today_iso}",
                            source="spoolman",
                            date=today_iso,
                        )
                        new_fdb_total = (fdb_spool.totalWeight or 0.0) - delta
                    else:
                        # Weight increased → update totalWeight (correction)
                        gross, used_default = spoolman_to_fdb_gross(new_w or 0.0, tare, precision=precision)
                        if used_default:
                            logger.warning("Cycle %s: using default tare for FDB spool %s", cycle_id, fdb_spool.id)
                        await filamentdb.update_spool(fdb_filament_id, fdb_spool.id, {"totalWeight": gross})
                        new_fdb_total = gross
                    # Refresh BOTH snapshots to the post-write agreed state.  Updating
                    # only the SM side left the FDB snapshot stale, so next cycle the
                    # (now-decremented) FDB totalWeight looked like a fresh FDB-side
                    # change and got pushed back to SM → the weight ping-pong loop.
                    _upsert_snapshot(db, "spoolman", "spool", str(sm_spool.id), _sm_snapshot_dict(sm_spool, field_maps))
                    fdb_snap_after = _fdb_snapshot_dict(fdb_spool)
                    fdb_snap_after["totalWeight"] = round(new_fdb_total, precision)
                    _upsert_snapshot(db, "filamentdb", "spool", fdb_spool.id, fdb_snap_after)
                    _log(
                        db, cycle_id, "spoolman_to_filamentdb", "update", "spool",
                        spoolman_id=sm_spool.id, fdb_filament_id=fdb_filament_id,
                        fdb_spool_id=fdb_spool.id, field_name="weight",
                        old_value=old_w, new_value=new_w,
                    )
                else:
                    result.preview.append({
                        "action": "update",
                        "entity_type": "spool",
                        "direction": "spoolman_to_filamentdb",
                        "label": _preview_label(sm_spool=sm_spool, fdb_filament=fdb_filament),
                        "field": "weight",
                        "old": old_w, "new": new_w,
                        "reason": None,
                        "spoolman_id": sm_spool.id,
                        "fdb_filament_id": fdb_filament_id,
                        "fdb_spool_id": fdb_spool.id,
                    })
                result.updated += 1
            except Exception as exc:
                logger.error("Cycle %s: SM→FDB weight sync failed spool %s: %s", cycle_id, sm_spool.id, exc)
                if not dry_run:
                    _log(
                        db, cycle_id, "spoolman_to_filamentdb", "error", "spool",
                        spoolman_id=sm_spool.id, fdb_filament_id=fdb_filament_id,
                        fdb_spool_id=fdb_spool.id, error_message=str(exc),
                    )
                result.errors += 1

        elif weight_action == SyncAction.PUSH_FDB_TO_SM:
            # FDB → SM weight sync (FR-10).  FDB's totalWeight already reflects
            # usage (logging usage reduces it), so net = totalWeight - tare — do
            # NOT re-subtract usageHistory (that double-counted and, with the
            # stale-snapshot loop, compounded the decrement to zero).
            fdb_filament = fdb_filaments.get(fdb_filament_id)
            tare = fdb_filament.spoolWeight if fdb_filament else None
            try:
                new_w = cs.fdb_weight_change.new_value if cs.fdb_weight_change else fdb_spool.totalWeight or 0.0
                net, used_default = fdb_to_spoolman_net(new_w or 0.0, tare, precision=precision)
                if used_default:
                    logger.warning("Cycle %s: using default tare for SM spool %s", cycle_id, sm_spool.id)
                if not dry_run:
                    await spoolman.update_spool(sm_spool.id, {"remaining_weight": net})
                    # Refresh BOTH snapshots to the post-write agreed state so the
                    # value we just wrote to SM is not re-detected as an SM-side
                    # change next cycle (other half of the weight ping-pong loop).
                    _upsert_snapshot(db, "filamentdb", "spool", fdb_spool.id, _fdb_snapshot_dict(fdb_spool))
                    sm_snap_after = _sm_snapshot_dict(sm_spool, field_maps)
                    sm_snap_after["remaining_weight"] = net
                    _upsert_snapshot(db, "spoolman", "spool", str(sm_spool.id), sm_snap_after)
                    _log(
                        db, cycle_id, "filamentdb_to_spoolman", "update", "spool",
                        spoolman_id=sm_spool.id, fdb_filament_id=fdb_filament_id,
                        fdb_spool_id=fdb_spool.id, field_name="remaining_weight",
                        old_value=sm_spool.remaining_weight, new_value=net,
                    )
                else:
                    result.preview.append({
                        "action": "update",
                        "entity_type": "spool",
                        "direction": "filamentdb_to_spoolman",
                        "label": _preview_label(sm_spool=sm_spool, fdb_filament=fdb_filament),
                        "field": "remaining_weight",
                        "old": sm_spool.remaining_weight, "new": net,
                        "reason": None,
                        "spoolman_id": sm_spool.id,
                        "fdb_filament_id": fdb_filament_id,
                        "fdb_spool_id": fdb_spool.id,
                    })
                result.updated += 1
            except Exception as exc:
                logger.error("Cycle %s: FDB→SM weight sync failed spool %s: %s", cycle_id, sm_spool.id, exc)
                if not dry_run:
                    _log(
                        db, cycle_id, "filamentdb_to_spoolman", "error", "spool",
                        spoolman_id=sm_spool.id, fdb_filament_id=fdb_filament_id,
                        fdb_spool_id=fdb_spool.id, error_message=str(exc),
                    )
                result.errors += 1

        else:
            # NOOP — refresh snapshots so they stay current
            if not dry_run:
                _upsert_snapshot(db, "spoolman", "spool", str(sm_spool.id), _sm_snapshot_dict(sm_spool, field_maps))
                _upsert_snapshot(db, "filamentdb", "spool", fdb_spool.id, _fdb_snapshot_dict(fdb_spool))

        # ---- Lifecycle (archive/retire) sync ----
        # Runs AFTER the weight pass on purpose. A spool is usually archived/retired
        # right as it hits ~0 g, so the final weight decrement (and its FDB usage-log
        # audit entry) must settle first — otherwise the far side lands retired/archived
        # carrying a stale weight and missing its final usage entry.
        #
        # The flags come from the changeset computed at the top of the pair (against the
        # pre-cycle snapshot), so the weight pass refreshing the snapshot dicts above
        # (which rebuild ``archived``/``retired`` from the live spool) does NOT clobber
        # the detection — we already captured the flip in ``cs``.
        lifecycle_sm_changed = cs.sm_archive_change is not None
        lifecycle_fdb_changed = cs.fdb_retire_change is not None

        # Target converged boolean for whichever side we push to.
        sm_archived_now = bool(sm_spool.archived)
        fdb_retired_now = bool(fdb_spool.retired)

        # When BOTH sides changed but they landed on the SAME state (e.g. both archived
        # in this cycle), there is no real divergence — converge silently. Only a both-
        # changed-to-OPPOSITE-states case is a genuine conflict. The resolver only sees
        # booleans, so collapse the agreeing-both-changed case to a NOOP up front.
        both_changed_converged = (
            lifecycle_sm_changed and lifecycle_fdb_changed
            and sm_archived_now == fdb_retired_now
        )

        if (lifecycle_sm_changed or lifecycle_fdb_changed) and not both_changed_converged:
            # booleans → never timestamp-eligible (sm_ts/fdb_ts stay None).
            lifecycle_action = resolve_sync_action(
                sm_changed=lifecycle_sm_changed,
                fdb_changed=lifecycle_fdb_changed,
                direction=archive_direction,
                policy=archive_policy,
            )

            if lifecycle_action == SyncAction.QUEUE_CONFLICT:
                if not dry_run:
                    if not _has_open_conflict(
                        db, "spool", "lifecycle",
                        spoolman_id=sm_spool.id,
                        fdb_spool_id=fdb_spool.id,
                        conflict_type="cross_system",
                    ):
                        _queue_conflict(
                            db, cycle_id, "spool", "lifecycle",
                            spoolman_id=sm_spool.id,
                            fdb_filament_id=fdb_filament_id,
                            fdb_spool_id=fdb_spool.id,
                            spoolman_value=sm_archived_now,
                            filamentdb_value=fdb_retired_now,
                            conflict_type="cross_system",
                        )
                        result.conflicts += 1
                else:
                    result.preview.append({
                        "action": "conflict",
                        "entity_type": "spool",
                        "direction": None,
                        "label": _preview_label(sm_spool=sm_spool, fdb_filament=fdb_filaments.get(fdb_filament_id)),
                        "field": "lifecycle",
                        "old": sm_archived_now,
                        "new": fdb_retired_now,
                        "reason": "both sides changed archive/retire (old=SM archived, new=FDB retired)",
                        "spoolman_id": sm_spool.id,
                        "fdb_filament_id": fdb_filament_id,
                        "fdb_spool_id": fdb_spool.id,
                    })
                    result.conflicts += 1

            elif lifecycle_action == SyncAction.PUSH_SM_TO_FDB:
                # SM archived state is authoritative → mirror to FDB.retired.
                target = sm_archived_now
                try:
                    if not dry_run:
                        await filamentdb.update_spool(fdb_filament_id, fdb_spool.id, {"retired": target})
                        _refresh_lifecycle_snapshots(db, sm_spool.id, fdb_spool.id, target, target)
                        _log(
                            db, cycle_id, "spoolman_to_filamentdb", "update", "spool",
                            spoolman_id=sm_spool.id, fdb_filament_id=fdb_filament_id,
                            fdb_spool_id=fdb_spool.id, field_name="lifecycle",
                            old_value="retired" if fdb_retired_now else "live",
                            new_value=(
                                "retired in FDB (archived in Spoolman)" if target
                                else "live in FDB (un-archived in Spoolman)"
                            ),
                        )
                    else:
                        result.preview.append({
                            "action": "update",
                            "entity_type": "spool",
                            "direction": "spoolman_to_filamentdb",
                            "label": _preview_label(sm_spool=sm_spool, fdb_filament=fdb_filaments.get(fdb_filament_id)),
                            "field": "lifecycle",
                            "old": fdb_retired_now, "new": target,
                            "reason": "retired in FDB" if target else "un-retired in FDB",
                            "spoolman_id": sm_spool.id,
                            "fdb_filament_id": fdb_filament_id,
                            "fdb_spool_id": fdb_spool.id,
                        })
                    result.updated += 1
                except Exception as exc:
                    logger.error("Cycle %s: SM→FDB lifecycle sync failed spool %s: %s", cycle_id, sm_spool.id, exc)
                    if not dry_run:
                        _log(
                            db, cycle_id, "spoolman_to_filamentdb", "error", "spool",
                            spoolman_id=sm_spool.id, fdb_filament_id=fdb_filament_id,
                            fdb_spool_id=fdb_spool.id, error_message=str(exc),
                        )
                    result.errors += 1

            elif lifecycle_action == SyncAction.PUSH_FDB_TO_SM:
                # FDB retired state is authoritative → mirror to SM.archived.
                target = fdb_retired_now
                try:
                    if not dry_run:
                        await spoolman.update_spool(sm_spool.id, {"archived": target})
                        _refresh_lifecycle_snapshots(db, sm_spool.id, fdb_spool.id, target, target)
                        _log(
                            db, cycle_id, "filamentdb_to_spoolman", "update", "spool",
                            spoolman_id=sm_spool.id, fdb_filament_id=fdb_filament_id,
                            fdb_spool_id=fdb_spool.id, field_name="lifecycle",
                            old_value="archived" if sm_archived_now else "active",
                            new_value=(
                                "archived in Spoolman (retired in FDB)" if target
                                else "active in Spoolman (un-retired in FDB)"
                            ),
                        )
                    else:
                        result.preview.append({
                            "action": "update",
                            "entity_type": "spool",
                            "direction": "filamentdb_to_spoolman",
                            "label": _preview_label(sm_spool=sm_spool, fdb_filament=fdb_filaments.get(fdb_filament_id)),
                            "field": "lifecycle",
                            "old": sm_archived_now, "new": target,
                            "reason": "archived in Spoolman" if target else "un-archived in Spoolman",
                            "spoolman_id": sm_spool.id,
                            "fdb_filament_id": fdb_filament_id,
                            "fdb_spool_id": fdb_spool.id,
                        })
                    result.updated += 1
                except Exception as exc:
                    logger.error("Cycle %s: FDB→SM lifecycle sync failed spool %s: %s", cycle_id, sm_spool.id, exc)
                    if not dry_run:
                        _log(
                            db, cycle_id, "filamentdb_to_spoolman", "error", "spool",
                            spoolman_id=sm_spool.id, fdb_filament_id=fdb_filament_id,
                            fdb_spool_id=fdb_spool.id, error_message=str(exc),
                        )
                    result.errors += 1

            else:
                # NOOP (e.g. a locked one-way destination drifted) — converge both
                # snapshot lifecycle bits so the change is not re-detected next cycle.
                if not dry_run:
                    _refresh_lifecycle_snapshots(db, sm_spool.id, fdb_spool.id, sm_archived_now, fdb_retired_now)

        elif both_changed_converged and not dry_run:
            # Both sides flipped to the same state in one cycle — no write needed, just
            # converge the snapshot lifecycle bits so it doesn't re-fire next cycle.
            _refresh_lifecycle_snapshots(db, sm_spool.id, fdb_spool.id, sm_archived_now, fdb_retired_now)

        # ---- Field mapping sync (FR-11) ----
        if field_maps:
            fm_for_spool = filament_mappings_by_sm.get(sm_spool.filament.id)
            if fm_for_spool:
                _fr11_result = await _apply_field_changes(
                    db, cycle_id, result, dry_run,
                    sm_spool, fdb_filament_id, fdb_spool.id,
                    field_maps, spoolman, filamentdb, sm_snap, fdb_snap,
                    matprop_direction=matprop_direction,
                    matprop_policy=matprop_policy,
                )
                # Persist the field-mapping baselines so the next cycle can
                # compare current vs snapshot instead of always reading None.
                # Also reflects any writes made above (anti-ping-pong).
                if _fr11_result is not None and not dry_run:
                    _fv_after, _sm_ed_after = _fr11_result
                    _merge_snapshot(
                        db, "filamentdb", "spool", fdb_spool.id,
                        {"_field_values": _fv_after},
                    )
                    _merge_snapshot(
                        db, "spoolman", "spool", str(sm_spool.id),
                        {"_extra_decoded": _sm_ed_after},
                    )

        # ---- Matched / in-sync entry (dry-run only) ----
        # If no preview entry was appended for this pair during the weight and
        # field passes, the pair is in sync.  Emit a single "matched" entry so
        # the dry-run preview is a complete inventory of all paired records, not
        # only a diff.  Suppressed in real (non-dry-run) cycles entirely.
        if dry_run and len(result.preview) == _preview_len_before_pair:
            result.preview.append({
                "action": "matched",
                "entity_type": "spool",
                "direction": None,
                "label": _preview_label(sm_spool=sm_spool, fdb_filament=fdb_filaments.get(fdb_filament_id)),
                "field": None,
                "old": None,
                "new": None,
                "reason": "in sync — no updates",
                "spoolman_id": sm_spool.id,
                "fdb_filament_id": fdb_filament_id,
                "fdb_spool_id": fdb_spool.id,
            })

    # ---- Orphaned FilamentMapping cleanup ----
    # Prune FilamentMapping rows that are clearly orphaned: not a synthetic parent,
    # have no remaining SpoolMapping referencing them, AND whose filamentdb_id is
    # absent from the current FDB fetch.  Also deletes their filament-level Snapshot
    # rows.  Conservative: only purges when all three conditions are met.
    if not dry_run:
        remaining_fm_ids: set[int] = {
            m.filament_mapping_id
            for m in db.query(SpoolMapping).all()
            if m.filament_mapping_id is not None
        }
        for fm in filament_mappings:
            if getattr(fm, "is_synthetic_parent", False):
                continue  # Synthetic parents are managed separately
            if fm.id in remaining_fm_ids:
                continue  # Still has live SpoolMappings
            if fm.filamentdb_id in fdb_filaments:
                continue  # FDB filament still exists
            # Orphaned: no SpoolMappings, FDB filament gone — purge snapshot + mapping.
            if fm.spoolman_filament_id is not None:
                db.query(Snapshot).filter_by(
                    source="spoolman", entity_type="filament", entity_id=str(fm.spoolman_filament_id)
                ).delete()
            db.query(Snapshot).filter_by(
                source="filamentdb", entity_type="filament", entity_id=fm.filamentdb_id
            ).delete()
            db.delete(fm)
            _log(
                db, cycle_id, "auto", "info", "filament",
                fdb_filament_id=fm.filamentdb_id,
                error_message="orphaned FilamentMapping purged: no SpoolMappings and FDB filament absent",
            )

    # ---- Structured multicolor sync (bidirectional, FDB >= 1.33.0) ----
    await _sync_multicolor(
        db, cycle_id, result, dry_run,
        filament_mappings=filament_mappings,
        sm_filaments=sm_filaments,
        fdb_filaments=fdb_filaments,
        spoolman=spoolman,
        filamentdb=filamentdb,
        multicolor_supported=multicolor_supported,
        matprop_direction=matprop_direction,
        matprop_policy=matprop_policy,
    )

    # ---- Filament-level cost sync (bidirectional, follows matprop direction) ----
    # Build spool-by-filament lookup for cost resolution (active spools only).
    sm_spools_by_filament_for_cost: dict[int, list[Any]] = {}
    for s in sm_spools_all:
        if not s.archived:
            sm_spools_by_filament_for_cost.setdefault(s.filament.id, []).append(s)
    await _sync_cost(
        db, cycle_id, result, dry_run,
        filament_mappings=filament_mappings,
        sm_filaments=sm_filaments,
        sm_spools_by_filament=sm_spools_by_filament_for_cost,
        fdb_filaments=fdb_filaments,
        spoolman=spoolman,
        filamentdb=filamentdb,
        matprop_direction=matprop_direction,
        matprop_policy=matprop_policy,
    )

    # ---- Material-property sync (native bed/nozzle temperatures, bidirectional) ----
    await _sync_material_props(
        db, cycle_id, result, dry_run,
        filament_mappings=filament_mappings,
        sm_filaments=sm_filaments,
        fdb_filaments=fdb_filaments,
        spoolman=spoolman,
        filamentdb=filamentdb,
        matprop_direction=matprop_direction,
        matprop_policy=matprop_policy,
    )

    # ---- Native shared-field sync (material/density/diameter/spool_weight/weight) ----
    # These five fields have direct FDB↔SM counterparts that the generic extra-field mapper
    # (FR-11) cannot reach. SM→FDB writes are master/variant-gated; see _sync_material_scalars.
    await _sync_material_scalars(
        db, cycle_id, result, dry_run,
        filament_mappings=filament_mappings,
        sm_filaments=sm_filaments,
        fdb_filaments=fdb_filaments,
        spoolman=spoolman,
        filamentdb=filamentdb,
        matprop_direction=matprop_direction,
        matprop_policy=matprop_policy,
    )

    # ---- Finish-tag sync (OpenPrintTag material-tags, bidirectional) ----
    # Gated on FDB >= 1.33.0: optTags (the FDB finish-tag carrier) shipped with that release.
    await _sync_finish_tags(
        db, cycle_id, result, dry_run,
        filament_mappings=filament_mappings,
        sm_filaments=sm_filaments,
        fdb_filaments=fdb_filaments,
        spoolman=spoolman,
        filamentdb=filamentdb,
        finish_tags_supported=multicolor_supported,
        matprop_direction=matprop_direction,
        matprop_policy=matprop_policy,
    )

    # ---- New spool detection (FR-12) ----
    # new_spool_direction gates which creation paths are active:
    #   two_way                → both SM→FDB and FDB→SM creation
    #   spoolman_to_filamentdb → only SM→FDB creation (new SM spools create in FDB)
    #   filamentdb_to_spoolman → only FDB→SM creation (new FDB spools create in SM)
    if new_spool_direction in ("two_way", "spoolman_to_filamentdb"):
        for sm_spool in sm_spools.values():
            if sm_spool.id in mapped_sm_spool_ids:
                continue
            fdb_spool_id_raw = sm_spool.extra.get(_settings.spoolman_field_filamentdb_spool_id)
            fdb_spool_id = decode_extra_value(fdb_spool_id_raw)
            if fdb_spool_id and fdb_spool_id in fdb_spool_index:
                continue  # has live cross-ref but no SpoolMapping row — orphan, skip
            await _handle_new_sm_spool(
                db, cycle_id, result, dry_run,
                sm_spool, filament_mappings_by_sm, fdb_filaments,
                filamentdb, spoolman, fdb_field_name,
                precision=precision,
                new_filament_policy=new_filament_policy,
                new_spool_policy=new_spool_policy,
                variant_parent_mode=_engine_variant_parent_mode,
                variant_keywords=_engine_variant_keywords,
                container_parent_marker=_engine_container_marker,
            )

    if new_spool_direction in ("two_way", "filamentdb_to_spoolman"):
        for fdb_f in fdb_filaments_all:
            # Synthetic container parents have no Spoolman counterpart.  A spool
            # on a synthetic parent is a user error (should be on a color variant).
            # Warn via the sync log and skip — never invent a Spoolman filament for it.
            if fdb_f.id in _synthetic_parent_fdb_ids:
                for fdb_spool in fdb_f.spools:
                    if fdb_spool.id in mapped_fdb_spool_ids:
                        continue
                    logger.warning(
                        "Cycle %s: spool %s is on synthetic container parent FDB filament %s "
                        "(%s) — move it to a color variant. Skipping.",
                        cycle_id, fdb_spool.id, fdb_f.id, fdb_f.name,
                    )
                    if not dry_run:
                        _log(
                            db, cycle_id, "filamentdb_to_spoolman", "skip", "spool",
                            fdb_filament_id=fdb_f.id,
                            fdb_spool_id=fdb_spool.id,
                            error_message=(
                                f"spool on container parent {fdb_f.name!r} — "
                                "move it to a color variant"
                            ),
                        )
                    result.skipped += 1
                continue
            for fdb_spool in fdb_f.spools:
                if fdb_spool.id in mapped_fdb_spool_ids:
                    continue
                label_val = getattr(fdb_spool, fdb_field_name, None)
                if label_val:
                    continue  # has SM ID in configured field — orphan without SpoolMapping, skip
                await _handle_new_fdb_spool(
                    db, cycle_id, result, dry_run,
                    fdb_f, fdb_spool, filament_mappings_by_fdb,
                    spoolman, filamentdb, fdb_field_name,
                    precision=precision,
                    new_filament_policy=new_filament_policy,
                    new_spool_policy=new_spool_policy,
                )

    # ---- OpenTag identity push (scoped exception: merge slug/uuid into FDB settings bag) ----
    # For each FilamentMapping whose Spoolman filament has openprinttag_slug/uuid extra fields set,
    # ensure the same two keys appear in the FDB filament's settings{} bag.  Idempotent: the
    # merge helper skips the write when FDB already has the same values.  Non-fatal per-pair.
    # Dry-run aware: no writes in dry-run mode.
    if not dry_run:
        await _sync_opentag_identity(
            db, cycle_id, result,
            filament_mappings=filament_mappings,
            sm_filaments=sm_filaments,
            filamentdb=filamentdb,
        )

    if not dry_run:
        db.commit()

    logger.info(
        "Cycle %s (%s) — created=%d updated=%d conflicts=%d skipped=%d errors=%d",
        cycle_id, "dry-run" if dry_run else "live",
        result.created, result.updated, result.conflicts, result.skipped, result.errors,
    )
    return result


async def _sync_opentag_identity(
    db: Session,
    cycle_id: str,
    result: CycleResult,
    *,
    filament_mappings: list[FilamentMapping],
    sm_filaments: dict[int, Any],
    filamentdb: FilamentDBClient,
) -> None:
    """Phase 5 (scoped exception): push openprinttag_slug/uuid from SM extras into FDB settings bag.

    APPROVED SCOPED EXCEPTION — only merges the two OpenTag identity keys into
    FDB's settings{} bag.  Never modifies or removes any other settings key.
    See CLAUDE.md and docs/decisions.md for the approved exception record.

    Logic per pair:
    - Read openprinttag_slug and openprinttag_uuid from Spoolman filament extra fields.
    - If both are absent/empty: skip (nothing to push).
    - Call filamentdb.merge_filament_settings() which:
        * fetches current FDB filament,
        * checks if the values are already equal (idempotent — no HTTP write if equal),
        * merges only those two keys, preserving all other settings keys.
    - Non-fatal per-pair: log and continue on error.
    """
    slug_field = _settings.spoolman_field_openprinttag_slug
    uuid_field = _settings.spoolman_field_openprinttag_uuid

    for m in filament_mappings:
        # Synthetic container parents have no Spoolman counterpart — skip.
        if getattr(m, "is_synthetic_parent", False):
            continue
        sm_fil = sm_filaments.get(m.spoolman_filament_id)
        if sm_fil is None:
            continue

        slug_raw = sm_fil.extra.get(slug_field) if hasattr(sm_fil, "extra") else None
        uuid_raw = sm_fil.extra.get(uuid_field) if hasattr(sm_fil, "extra") else None

        slug = decode_extra_value(slug_raw)
        uuid_val = decode_extra_value(uuid_raw)

        # Only push when at least one key is non-empty
        keys_to_merge: dict[str, str] = {}
        if slug and isinstance(slug, str):
            keys_to_merge["openprinttag_slug"] = slug
        if uuid_val and isinstance(uuid_val, str):
            keys_to_merge["openprinttag_uuid"] = uuid_val

        if not keys_to_merge:
            continue

        try:
            await filamentdb.merge_filament_settings(m.filamentdb_id, keys_to_merge)
        except Exception as exc:
            logger.warning(
                "Cycle %s: opentag identity push to FDB filament %s failed: %s",
                cycle_id, m.filamentdb_id, exc,
            )
