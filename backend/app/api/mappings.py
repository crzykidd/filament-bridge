"""GET/PUT/DELETE /api/mappings — paired records view (FR-19).

Returns the synced spool pairs for the Synced Records table with last-known
weights per side (from snapshots), a status enum, and the IDs to build both deep
links. Relink (PUT) and unlink (DELETE) edit only the bridge's own mapping rows —
they NEVER touch an upstream record (hard rule, CLAUDE.md).

Status enum (see docs/decisions.md for the contract):
  conflict  — an open Conflict row references this spool
  unlinked  — the spool mapping has no parent filament mapping
  pending   — a side has no snapshot yet (not baselined / awaiting first sync)
  in_sync   — both snapshots present, no open conflict
"""

from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.conflict import Conflict
from app.models.mapping import FilamentMapping, SpoolMapping
from app.models.snapshot import Snapshot
from app.schemas.api import MappingRow, MappingStatus, MappingUpdateRequest

router = APIRouter()


def _snapshot(db: Session, source: str, entity_id: str) -> Snapshot | None:
    return (
        db.query(Snapshot)
        .filter_by(source=source, entity_type="spool", entity_id=entity_id)
        .first()
    )


def build_mapping_rows(db: Session) -> list[MappingRow]:
    """Assemble one MappingRow per spool mapping (shared with the dashboard)."""
    spool_mappings: list[SpoolMapping] = db.query(SpoolMapping).all()
    filament_mappings = {m.id: m for m in db.query(FilamentMapping).all()}

    # Open conflicts indexed by the spool ids they reference.
    open_conflicts = db.query(Conflict).filter(Conflict.resolved_at.is_(None)).all()
    conflict_sm_ids = {c.spoolman_id for c in open_conflicts if c.spoolman_id is not None}
    conflict_fdb_spool_ids = {
        c.filamentdb_spool_id for c in open_conflicts if c.filamentdb_spool_id is not None
    }
    # conflict_id lookup: spoolman_spool_id → Conflict.id (first open conflict for that spool)
    conflict_id_by_sm: dict[int, int] = {}
    conflict_id_by_fdb: dict[str, int] = {}
    for c in open_conflicts:
        if c.spoolman_id is not None and c.spoolman_id not in conflict_id_by_sm:
            conflict_id_by_sm[c.spoolman_id] = c.id
        if c.filamentdb_spool_id is not None and c.filamentdb_spool_id not in conflict_id_by_fdb:
            conflict_id_by_fdb[c.filamentdb_spool_id] = c.id

    rows: list[MappingRow] = []
    for m in spool_mappings:
        sm_snap_row = _snapshot(db, "spoolman", str(m.spoolman_spool_id))
        fdb_snap_row = _snapshot(db, "filamentdb", m.filamentdb_spool_id)
        sm_snap = json.loads(sm_snap_row.data) if sm_snap_row else None
        fdb_snap = json.loads(fdb_snap_row.data) if fdb_snap_row else None

        has_conflict = (
            m.spoolman_spool_id in conflict_sm_ids
            or m.filamentdb_spool_id in conflict_fdb_spool_ids
        )

        if has_conflict:
            status: MappingStatus = "conflict"
        elif m.filament_mapping_id is None:
            status = "unlinked"
        elif sm_snap is None or fdb_snap is None:
            status = "pending"
        else:
            status = "in_sync"

        # Display fields + spoolman filament id come from the Spoolman-side snapshot
        # (the FDB spool snapshot is trimmed to id/label/weight only).
        sm_filament = (sm_snap or {}).get("filament") or {}
        sm_vendor = (sm_filament.get("vendor") or {}) if isinstance(sm_filament.get("vendor"), dict) else {}

        fm = filament_mappings.get(m.filament_mapping_id) if m.filament_mapping_id else None

        # last_synced: most recent snapshot capture, else the mapping's updated_at.
        captures = [r.captured_at for r in (sm_snap_row, fdb_snap_row) if r is not None]
        last_synced = max(captures) if captures else m.updated_at

        remaining = (sm_snap or {}).get("remaining_weight")
        conflict_id = (
            conflict_id_by_sm.get(m.spoolman_spool_id)
            or conflict_id_by_fdb.get(m.filamentdb_spool_id)
        ) if has_conflict else None

        rows.append(
            MappingRow(
                id=m.id,
                status=status,
                spoolman_spool_id=m.spoolman_spool_id,
                spoolman_filament_id=sm_filament.get("id"),
                filamentdb_filament_id=m.filamentdb_filament_id,
                filamentdb_spool_id=m.filamentdb_spool_id,
                filamentdb_parent_id=fm.filamentdb_parent_id if fm else None,
                name=sm_filament.get("name"),
                vendor=sm_vendor.get("name"),
                color=sm_filament.get("color_hex"),
                spoolman_weight=remaining,
                filamentdb_weight=(fdb_snap or {}).get("totalWeight"),
                last_synced=last_synced,
                multi_color_hexes=sm_filament.get("multi_color_hexes"),
                multi_color_direction=sm_filament.get("multi_color_direction"),
                remaining_weight=remaining,
                is_empty=(remaining is not None and remaining <= 0),
                conflict_id=conflict_id,
            )
        )
    return rows


@router.get("/mappings", response_model=list[MappingRow])
def list_mappings(
    db: Session = Depends(get_db),
    status: MappingStatus | None = Query(default=None),
    sort: Literal["name", "vendor", "status", "last_synced"] = Query(default="name"),
    order: Literal["asc", "desc"] = Query(default="asc"),
) -> list[MappingRow]:
    rows = build_mapping_rows(db)
    if status is not None:
        rows = [r for r in rows if r.status == status]

    def _key(r: MappingRow):
        if sort == "last_synced":
            # None sorts first ascending; use a sentinel so mixed None/datetime is stable.
            return (r.last_synced is not None, r.last_synced)
        return ((getattr(r, sort) or "").lower(),)

    rows.sort(key=_key, reverse=(order == "desc"))
    return rows


@router.put("/mappings/{mapping_id}", response_model=MappingRow)
def update_mapping(
    mapping_id: int,
    payload: MappingUpdateRequest,
    db: Session = Depends(get_db),
) -> MappingRow:
    """Manual relink — repoint the bridge mapping. Never edits an upstream record."""
    from app.api.errors import api_error

    m = db.query(SpoolMapping).filter_by(id=mapping_id).first()
    if m is None:
        raise api_error(404, "mapping_not_found", f"No spool mapping with id {mapping_id}")

    data = payload.model_dump(exclude_unset=True)
    if "filamentdb_filament_id" in data and data["filamentdb_filament_id"] is not None:
        m.filamentdb_filament_id = data["filamentdb_filament_id"]
    if "filamentdb_spool_id" in data and data["filamentdb_spool_id"] is not None:
        m.filamentdb_spool_id = data["filamentdb_spool_id"]
    if "filamentdb_parent_id" in data and m.filament_mapping_id is not None:
        fm = db.query(FilamentMapping).filter_by(id=m.filament_mapping_id).first()
        if fm is not None:
            fm.filamentdb_parent_id = data["filamentdb_parent_id"]
    db.commit()

    row = next((r for r in build_mapping_rows(db) if r.id == mapping_id), None)
    assert row is not None
    return row


@router.delete("/mappings/{mapping_id}", status_code=204)
def delete_mapping(mapping_id: int, db: Session = Depends(get_db)) -> None:
    """Unlink — sever the bridge mapping only. NEVER deletes an upstream record."""
    from app.api.errors import api_error

    m = db.query(SpoolMapping).filter_by(id=mapping_id).first()
    if m is None:
        raise api_error(404, "mapping_not_found", f"No spool mapping with id {mapping_id}")
    db.delete(m)
    db.commit()
