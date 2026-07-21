"""Shared filament-mapping status helper.

Extracted from api/sync.py (commit e14f053) so both sync.py and mappings.py
call the same logic — no drift between the dashboard counts and the filament-only
rows in build_mapping_rows.

Status hierarchy (matches spool-level semantics):
  conflict  — an open Conflict row references this filament's filamentdb_id
  pending   — either SM or FDB filament snapshot is absent
  in_sync   — both snapshots present, no open conflict
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.mapping import FilamentMapping
from app.models.snapshot import Snapshot


def filament_mapping_status(
    db: Session,
    fm: FilamentMapping,
    open_conflict_fdb_ids: set[str],
    *,
    sm_filament_snapshot_ids: set[str] | None = None,
    fdb_filament_snapshot_ids: set[str] | None = None,
) -> str:
    """Return 'conflict' | 'pending' | 'in_sync' for a single FilamentMapping.

    ``open_conflict_fdb_ids`` should be pre-computed by the caller (set of
    filamentdb_filament_id values from all open Conflict rows) so this helper
    does not re-query per row.

    Snapshot existence is normally checked with a per-call query. Callers looping
    over many mappings (e.g. the dashboard) can avoid the N+1 by passing the
    pre-loaded sets of existing filament-snapshot ``entity_id`` values for each
    source; when both are given no per-row query is issued.
    """
    if fm.filamentdb_id in open_conflict_fdb_ids:
        return "conflict"

    if sm_filament_snapshot_ids is not None and fdb_filament_snapshot_ids is not None:
        has_sm = str(fm.spoolman_filament_id) in sm_filament_snapshot_ids
        has_fdb = fm.filamentdb_id in fdb_filament_snapshot_ids
    else:
        has_sm = db.query(Snapshot).filter(
            Snapshot.source == "spoolman",
            Snapshot.entity_type == "filament",
            Snapshot.entity_id == str(fm.spoolman_filament_id),
        ).first() is not None
        has_fdb = db.query(Snapshot).filter(
            Snapshot.source == "filamentdb",
            Snapshot.entity_type == "filament",
            Snapshot.entity_id == fm.filamentdb_id,
        ).first() is not None

    if has_sm and has_fdb:
        return "in_sync"
    return "pending"
