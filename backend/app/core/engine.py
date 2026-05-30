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
from app.core.differ import diff_spool_pair
from app.core.fields import FieldMapping, get_fdb_field_value, resolve_field_map, should_skip_inherited
from app.core.matcher import match_filaments
from app.core.weight import fdb_to_spoolman_net, spoolman_to_fdb_gross, weight_changed
from app.models.config import BridgeConfig
from app.models.conflict import Conflict
from app.models.mapping import FilamentMapping, SpoolMapping
from app.models.snapshot import Snapshot
from app.models.sync_log import SyncLog
from app.schemas.spoolman import SpoolmanSpool, decode_extra_value, encode_extra_value
from app.schemas.filamentdb import FDBFilament, FDBSpool
from app.services.filamentdb import FilamentDBClient
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


# ---------------------------------------------------------------------------
# Internal DB helpers
# ---------------------------------------------------------------------------


def _read_config(db: Session) -> dict[str, Any]:
    rows = db.query(BridgeConfig).all()
    return {r.key: json.loads(r.value) for r in rows}


def _get_snapshot(db: Session, source: str, entity_type: str, entity_id: str) -> dict | None:
    row = (
        db.query(Snapshot)
        .filter_by(source=source, entity_type=entity_type, entity_id=entity_id)
        .first()
    )
    return json.loads(row.data) if row else None


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


# ---------------------------------------------------------------------------
# Field-mapping snapshot helpers
# ---------------------------------------------------------------------------


def _sm_snapshot_dict(spool: SpoolmanSpool, field_maps: list[FieldMapping]) -> dict:
    """Build the snapshot dict for a Spoolman spool including decoded extra values."""
    d = spool.model_dump()
    if field_maps:
        d["_extra_decoded"] = {
            fm.sm_key: decode_extra_value(spool.extra.get(fm.sm_key))
            for fm in field_maps
        }
    return d


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
) -> None:
    """Evaluate and apply field-mapping changes for one spool pair (FR-11)."""
    # Fetch FDB detail (needed for _inherited[] and full field surface)
    try:
        fdb_detail = await filamentdb.get_filament(fdb_filament_id)
    except Exception as exc:
        logger.error("Cycle %s: could not fetch FDB filament detail %s: %s", cycle_id, fdb_filament_id, exc)
        result.errors += 1
        return

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

    # Conflict fields — never auto-resolve
    for fdb_path in cs.field_conflicts:
        sm_val = sm_extra_decoded.get(next(fm.sm_key for fm in field_maps if fm.fdb_path == fdb_path))
        fdb_val = fdb_field_values.get(fdb_path)
        if not dry_run:
            _queue_conflict(
                db, cycle_id, "filament", fdb_path,
                spoolman_id=sm_spool.id,
                fdb_filament_id=fdb_filament_id,
                spoolman_value=sm_val,
                filamentdb_value=fdb_val,
            )
        else:
            result.preview.append({
                "action": "conflict", "field": fdb_path,
                "spoolman_id": sm_spool.id, "fdb_filament_id": fdb_filament_id,
            })
        result.conflicts += 1

    # FDB → SM changes
    for fc in cs.fdb_field_changes:
        fm = next((m for m in field_maps if m.fdb_path == fc.field_name), None)
        if fm is None:
            continue
        if should_skip_inherited(fdb_detail, fc.field_name):
            logger.info(
                "Cycle %s: skipping inherited field %s on FDB filament %s",
                cycle_id, fc.field_name, fdb_filament_id,
            )
            result.skipped += 1
            continue
        if not dry_run:
            try:
                encoded = encode_extra_value(fc.new_value)
                await spoolman.update_spool(
                    sm_spool.id, {"extra": {fm.sm_key: encoded}}
                )
                _log(
                    db, cycle_id, "filamentdb_to_spoolman", "update", "filament",
                    spoolman_id=sm_spool.id, fdb_filament_id=fdb_filament_id,
                    field_name=fc.field_name, old_value=fc.old_value, new_value=fc.new_value,
                )
                result.updated += 1
            except Exception as exc:
                logger.error("Cycle %s: field sync FDB→SM failed (%s): %s", cycle_id, fc.field_name, exc)
                _log(
                    db, cycle_id, "filamentdb_to_spoolman", "error", "filament",
                    spoolman_id=sm_spool.id, fdb_filament_id=fdb_filament_id,
                    field_name=fc.field_name, error_message=str(exc),
                )
                result.errors += 1
        else:
            result.preview.append({
                "action": "update", "direction": "filamentdb_to_spoolman",
                "field": fc.field_name, "spoolman_id": sm_spool.id, "old": fc.old_value, "new": fc.new_value,
            })
            result.updated += 1

    # SM → FDB changes
    fdb_put_payload: dict = {}
    for fc in cs.sm_field_changes:
        fm = next((m for m in field_maps if m.fdb_path == fc.field_name), None)
        if fm is None:
            continue
        if should_skip_inherited(fdb_detail, fc.field_name):
            logger.info(
                "Cycle %s: skipping inherited field %s on FDB filament %s",
                cycle_id, fc.field_name, fdb_filament_id,
            )
            result.skipped += 1
            continue
        # Collect into a single PUT
        parts = fc.field_name.split(".", 1)
        if len(parts) == 1:
            fdb_put_payload[fc.field_name] = fc.new_value
        else:
            fdb_put_payload.setdefault(parts[0], {})[parts[1]] = fc.new_value

    if fdb_put_payload and not dry_run:
        try:
            await filamentdb.update_filament(fdb_filament_id, fdb_put_payload)
            for fc in cs.sm_field_changes:
                _log(
                    db, cycle_id, "spoolman_to_filamentdb", "update", "filament",
                    spoolman_id=sm_spool.id, fdb_filament_id=fdb_filament_id,
                    field_name=fc.field_name, old_value=fc.old_value, new_value=fc.new_value,
                )
            result.updated += len(cs.sm_field_changes)
        except Exception as exc:
            logger.error("Cycle %s: field sync SM→FDB failed: %s", cycle_id, exc)
            _log(
                db, cycle_id, "spoolman_to_filamentdb", "error", "filament",
                spoolman_id=sm_spool.id, fdb_filament_id=fdb_filament_id,
                error_message=str(exc),
            )
            result.errors += 1
    elif fdb_put_payload and dry_run:
        for fc in cs.sm_field_changes:
            result.preview.append({
                "action": "update", "direction": "spoolman_to_filamentdb",
                "field": fc.field_name, "spoolman_id": sm_spool.id, "old": fc.old_value, "new": fc.new_value,
            })
        result.updated += len(cs.sm_field_changes)


# ---------------------------------------------------------------------------
# New-spool detection (FR-12)
# ---------------------------------------------------------------------------


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
) -> None:
    """Handle a Spoolman spool that has no filamentdb_spool_id extra field yet."""
    filament_mapping = filament_mappings_by_sm_filament.get(sm_spool.filament.id)

    if filament_mapping is None:
        # No filament mapping — queue as conflict for user resolution
        if not dry_run:
            _queue_conflict(
                db, cycle_id, "spool", "new_spool",
                spoolman_id=sm_spool.id,
                spoolman_value=f"Spoolman spool {sm_spool.id} has no FDB filament match",
            )
        else:
            result.preview.append({
                "action": "conflict", "reason": "no_filament_mapping",
                "spoolman_id": sm_spool.id,
            })
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
            "action": "create", "direction": "spoolman_to_filamentdb",
            "entity_type": "spool", "spoolman_id": sm_spool.id,
            "fdb_filament_id": fdb_filament.id,
        })
        result.created += 1
        return

    tare = fdb_filament.spoolWeight
    gross, used_default = spoolman_to_fdb_gross(sm_spool.remaining_weight or 0, tare, precision=precision)
    if used_default:
        logger.warning("Cycle %s: using default tare for new FDB spool from SM spool %s", cycle_id, sm_spool.id)

    try:
        spool_payload = {
            "totalWeight": gross,
            fdb_field_name: str(sm_spool.id),
        }
        raw = await filamentdb.create_spool(fdb_filament.id, spool_payload)
        new_fdb_spool_id = raw.get("_id") or raw.get("id", "")

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
) -> None:
    """Handle a Filament DB spool that has no Spoolman ID in its label yet."""
    filament_mapping = filament_mappings_by_fdb.get(fdb_filament.id)

    if filament_mapping is None:
        if not dry_run:
            _queue_conflict(
                db, cycle_id, "spool", "new_spool",
                fdb_filament_id=fdb_filament.id,
                fdb_spool_id=fdb_spool.id,
                filamentdb_value=f"FDB spool {fdb_spool.id} has no Spoolman filament match",
            )
        else:
            result.preview.append({
                "action": "conflict", "reason": "no_filament_mapping",
                "fdb_filament_id": fdb_filament.id, "fdb_spool_id": fdb_spool.id,
            })
        result.conflicts += 1
        return

    if dry_run:
        result.preview.append({
            "action": "create", "direction": "filamentdb_to_spoolman",
            "entity_type": "spool", "fdb_filament_id": fdb_filament.id, "fdb_spool_id": fdb_spool.id,
        })
        result.created += 1
        return

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

    weight_sot: str = config.get("weight_source_of_truth", "spoolman")
    matprop_sot: str = config.get("material_properties_source_of_truth", "filamentdb")
    threshold: float = float(config.get("sync_weight_threshold_grams", 2.0))
    precision: int = int(config.get("weight_precision_decimals", 2))
    fdb_field_name: str = _settings.filamentdb_spoolman_id_field  # default "label"

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

    sm_spools: dict[int, SpoolmanSpool] = {s.id: s for s in sm_spools_all if not s.archived}
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

    filament_mappings_by_sm: dict[int, FilamentMapping] = {
        m.spoolman_filament_id: m for m in filament_mappings
    }
    filament_mappings_by_fdb: dict[str, FilamentMapping] = {
        m.filamentdb_id: m for m in filament_mappings
    }

    # ---- Resolve field mappings (FR-11) ----
    field_maps: list[FieldMapping] = []
    if filament_mappings:
        try:
            sm_field_defs = await spoolman.get_field_definitions("spool")
            sm_extra_keys = {fd.key for fd in sm_field_defs}
        except Exception:
            sm_extra_keys = set()
        field_maps = resolve_field_map(_settings, sm_extra_keys, matprop_sot)

    # ---- Process mapped spool pairs ----
    for mapping in spool_mappings:
        sm_spool = sm_spools.get(mapping.spoolman_spool_id)
        fdb_entry = fdb_spool_index.get(mapping.filamentdb_spool_id)

        if sm_spool is None:
            if not dry_run:
                _log(
                    db, cycle_id, "spoolman_to_filamentdb", "skip", "spool",
                    spoolman_id=mapping.spoolman_spool_id,
                    fdb_filament_id=mapping.filamentdb_filament_id,
                    fdb_spool_id=mapping.filamentdb_spool_id,
                    error_message="SM spool not in active set (archived?)",
                )
            result.skipped += 1
            continue

        if fdb_entry is None:
            if not dry_run:
                _log(
                    db, cycle_id, "filamentdb_to_spoolman", "error", "spool",
                    spoolman_id=mapping.spoolman_spool_id,
                    fdb_filament_id=mapping.filamentdb_filament_id,
                    fdb_spool_id=mapping.filamentdb_spool_id,
                    error_message="FDB spool not found in current fetch",
                )
            result.errors += 1
            continue

        fdb_filament_id, fdb_spool = fdb_entry

        # Load snapshots
        sm_snap = _get_snapshot(db, "spoolman", "spool", str(sm_spool.id))
        fdb_snap = _get_snapshot(db, "filamentdb", "spool", fdb_spool.id)

        # First time we see this pair — store baseline, no diff yet
        if sm_snap is None or fdb_snap is None:
            if not dry_run:
                _upsert_snapshot(db, "spoolman", "spool", str(sm_spool.id), _sm_snapshot_dict(sm_spool, field_maps))
                _upsert_snapshot(db, "filamentdb", "spool", fdb_spool.id, _fdb_snapshot_dict(fdb_spool))
            result.skipped += 1
            continue

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

        if cs.weight_conflict:
            # Both sides changed — never auto-resolve (FR-13 hard rule)
            if not dry_run:
                _queue_conflict(
                    db, cycle_id, "spool", "weight",
                    spoolman_id=sm_spool.id,
                    fdb_filament_id=fdb_filament_id,
                    fdb_spool_id=fdb_spool.id,
                    spoolman_value=sm_spool.remaining_weight,
                    filamentdb_value=fdb_spool.totalWeight,
                )
            else:
                result.preview.append({
                    "action": "conflict", "field": "weight",
                    "spoolman_id": sm_spool.id, "fdb_spool_id": fdb_spool.id,
                })
            result.conflicts += 1

        elif cs.sm_weight_change and weight_sot == "spoolman":
            # SM → FDB weight sync (FR-9)
            old_w = cs.sm_weight_change.old_value
            new_w = cs.sm_weight_change.new_value
            delta = (old_w or 0.0) - (new_w or 0.0)
            fdb_filament = fdb_filaments.get(fdb_filament_id)
            tare = fdb_filament.spoolWeight if fdb_filament else None

            try:
                if not dry_run:
                    if delta > 0:
                        # Weight decreased → log usage entry (FR-9)
                        await filamentdb.log_usage(
                            fdb_filament_id, fdb_spool.id, delta,
                            job_label=f"spoolman sync {today_iso}",
                            source="spoolman",
                            date=today_iso,
                        )
                    else:
                        # Weight increased → update totalWeight (correction)
                        gross, used_default = spoolman_to_fdb_gross(new_w or 0.0, tare, precision=precision)
                        if used_default:
                            logger.warning("Cycle %s: using default tare for FDB spool %s", cycle_id, fdb_spool.id)
                        await filamentdb.update_spool(fdb_filament_id, fdb_spool.id, {"totalWeight": gross})
                    _upsert_snapshot(db, "spoolman", "spool", str(sm_spool.id), _sm_snapshot_dict(sm_spool, field_maps))
                    _log(
                        db, cycle_id, "spoolman_to_filamentdb", "update", "spool",
                        spoolman_id=sm_spool.id, fdb_filament_id=fdb_filament_id,
                        fdb_spool_id=fdb_spool.id, field_name="weight",
                        old_value=old_w, new_value=new_w,
                    )
                else:
                    result.preview.append({
                        "action": "update", "direction": "spoolman_to_filamentdb",
                        "field": "weight", "spoolman_id": sm_spool.id,
                        "fdb_spool_id": fdb_spool.id, "old": old_w, "new": new_w,
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

        elif cs.fdb_weight_change and weight_sot == "filamentdb":
            # FDB → SM weight sync (FR-10) — need detail for usage sum
            fdb_filament = fdb_filaments.get(fdb_filament_id)
            tare = fdb_filament.spoolWeight if fdb_filament else None
            try:
                fdb_detail = await filamentdb.get_filament(fdb_filament_id)
                detail_spool = next((s for s in fdb_detail.spools if s.id == fdb_spool.id), None)
                if detail_spool is None:
                    raise ValueError(f"FDB spool {fdb_spool.id} absent in detail view")
                usage_sum = sum(u.grams for u in detail_spool.usageHistory if u.grams > 0)
                new_w = cs.fdb_weight_change.new_value or 0.0
                net, used_default = fdb_to_spoolman_net(new_w, tare, usage_sum, precision=precision)
                if used_default:
                    logger.warning("Cycle %s: using default tare for SM spool %s", cycle_id, sm_spool.id)
                if not dry_run:
                    await spoolman.update_spool(sm_spool.id, {"remaining_weight": net})
                    _upsert_snapshot(db, "filamentdb", "spool", fdb_spool.id, _fdb_snapshot_dict(fdb_spool))
                    _log(
                        db, cycle_id, "filamentdb_to_spoolman", "update", "spool",
                        spoolman_id=sm_spool.id, fdb_filament_id=fdb_filament_id,
                        fdb_spool_id=fdb_spool.id, field_name="remaining_weight",
                        old_value=sm_spool.remaining_weight, new_value=net,
                    )
                else:
                    result.preview.append({
                        "action": "update", "direction": "filamentdb_to_spoolman",
                        "field": "remaining_weight", "spoolman_id": sm_spool.id,
                        "fdb_spool_id": fdb_spool.id, "old": sm_spool.remaining_weight, "new": net,
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
            # No weight change — refresh snapshots so they stay current
            if not dry_run:
                _upsert_snapshot(db, "spoolman", "spool", str(sm_spool.id), _sm_snapshot_dict(sm_spool, field_maps))
                _upsert_snapshot(db, "filamentdb", "spool", fdb_spool.id, _fdb_snapshot_dict(fdb_spool))

        # ---- Field mapping sync (FR-11) ----
        if field_maps:
            fm_for_spool = filament_mappings_by_sm.get(sm_spool.filament.id)
            if fm_for_spool:
                await _apply_field_changes(
                    db, cycle_id, result, dry_run,
                    sm_spool, fdb_filament_id, fdb_spool.id,
                    field_maps, spoolman, filamentdb, sm_snap, fdb_snap,
                )

    # ---- New spool detection (FR-12) ----
    for sm_spool in sm_spools.values():
        if sm_spool.id in mapped_sm_spool_ids:
            continue
        fdb_spool_id_raw = sm_spool.extra.get(_settings.spoolman_field_filamentdb_spool_id)
        fdb_spool_id = decode_extra_value(fdb_spool_id_raw)
        if fdb_spool_id:
            continue  # has cross-ref but no SpoolMapping row — orphan, skip
        await _handle_new_sm_spool(
            db, cycle_id, result, dry_run,
            sm_spool, filament_mappings_by_sm, fdb_filaments,
            filamentdb, spoolman, fdb_field_name,
            precision=precision,
        )

    for fdb_f in fdb_filaments_all:
        for fdb_spool in fdb_f.spools:
            if fdb_spool.id in mapped_fdb_spool_ids:
                continue
            label_val = getattr(fdb_spool, fdb_field_name, None) if fdb_field_name == "label" else None
            if label_val:
                continue  # has SM ID in label — orphan without SpoolMapping, skip
            await _handle_new_fdb_spool(
                db, cycle_id, result, dry_run,
                fdb_f, fdb_spool, filament_mappings_by_fdb,
                spoolman, filamentdb, fdb_field_name,
                precision=precision,
            )

    if not dry_run:
        db.commit()

    logger.info(
        "Cycle %s (%s) — created=%d updated=%d conflicts=%d skipped=%d errors=%d",
        cycle_id, "dry-run" if dry_run else "live",
        result.created, result.updated, result.conflicts, result.skipped, result.errors,
    )
    return result
