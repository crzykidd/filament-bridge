"""GET /api/sync-log — audit log viewer (FR-17).

Paginated, newest-first, filterable by entity_type / direction / action. Each
entry carries the deep-link IDs where applicable.

windows= mode: when set, return only entries from the most recent N distinct
non-null cycle_ids (ordered by max timestamp). Entries with a null cycle_id
(wizard/opentag) are excluded from window filtering — they won't appear in
window mode since they don't belong to a sync cycle.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.mapping import FilamentMapping, SpoolMapping
from app.models.sync_log import SyncLog
from app.schemas.api import SyncLogDeleteResponse, SyncLogEntry, SyncLogResponse

logger = logging.getLogger(__name__)

router = APIRouter()


def _decode(raw: str | None):
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


def _identity_label(identity_raw: str | None) -> str | None:
    """Render a FilamentMapping.identity JSON blob ({vendor, name, ...}) as 'Vendor Name'."""
    if not identity_raw:
        return None
    try:
        ident = json.loads(identity_raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(ident, dict):
        return None
    parts = [str(ident.get(k)).strip() for k in ("vendor", "name") if ident.get(k)]
    label = " ".join(p for p in parts if p)
    return label or None


def _vendor_name_label(vendor: str | None, name: str | None) -> str | None:
    label = " ".join(p for p in [(vendor or "").strip(), (name or "").strip()] if p)
    return label or None


def _build_label_resolver(
    db: Session,
    sm_fil_labels: dict[int, str | None] | None = None,
    sm_spool_labels: dict[int, str | None] | None = None,
):
    """Resolve a human-readable record name for sync_log rows.

    Primary source is FilamentMapping.identity (a {vendor, name, color_hex, material}
    blob written at mapping creation) — authoritative for already-synced records, works
    for existing rows, no schema change. For UNMAPPED records (e.g. new_filament conflicts
    on filaments not yet imported), there is no mapping, so the caller may pass best-effort
    live-Spoolman name maps (sm_fil_labels by SM filament id, sm_spool_labels by SM spool id)
    as a fallback. Returns None when nothing resolves.
    """
    sm_fil_labels = sm_fil_labels or {}
    sm_spool_labels = sm_spool_labels or {}
    fil_by_fdb_id: dict[str, str | None] = {}
    fil_by_sm_id: dict[int, str | None] = {}
    fil_by_pk: dict[int, str | None] = {}
    for m in db.query(FilamentMapping).all():
        label = _identity_label(m.identity)
        fil_by_pk[m.id] = label
        if m.filamentdb_id:
            fil_by_fdb_id[m.filamentdb_id] = label
        if m.spoolman_filament_id is not None:
            fil_by_sm_id[m.spoolman_filament_id] = label

    # spool id → owning filament-mapping label (for spool rows with no fdb filament id)
    spool_label_by_sm_spool: dict[int, str | None] = {}
    for s in db.query(SpoolMapping).all():
        spool_label_by_sm_spool[s.spoolman_spool_id] = fil_by_pk.get(s.filament_mapping_id)

    def resolve(row: SyncLog) -> str | None:
        # 1) Mapping identity (authoritative for synced records).
        if row.filamentdb_filament_id and fil_by_fdb_id.get(row.filamentdb_filament_id):
            return fil_by_fdb_id[row.filamentdb_filament_id]
        if row.entity_type == "filament" and fil_by_sm_id.get(row.spoolman_id):
            return fil_by_sm_id[row.spoolman_id]
        if row.entity_type == "spool" and spool_label_by_sm_spool.get(row.spoolman_id):
            return spool_label_by_sm_spool[row.spoolman_id]
        if fil_by_sm_id.get(row.spoolman_id):  # unmapped spool on a mapped filament
            return fil_by_sm_id[row.spoolman_id]
        # 2) Best-effort live Spoolman fallback (unmapped records — e.g. new_filament conflicts).
        if row.entity_type == "filament" and sm_fil_labels.get(row.spoolman_id):
            return sm_fil_labels[row.spoolman_id]
        if row.entity_type == "spool" and sm_spool_labels.get(row.spoolman_id):
            return sm_spool_labels[row.spoolman_id]
        return None

    return resolve


async def _live_spoolman_labels(request: Request) -> tuple[dict[int, str | None], dict[int, str | None]]:
    """Best-effort id→name maps from live Spoolman, to label rows for records that aren't
    mapped yet (e.g. new_filament conflicts). Never raises — returns empty maps on any error."""
    fil_labels: dict[int, str | None] = {}
    spool_labels: dict[int, str | None] = {}
    spoolman = getattr(request.app.state, "spoolman", None)
    if spoolman is None:
        return fil_labels, spool_labels
    try:
        for f in await spoolman.get_filaments():
            fil_labels[f.id] = _vendor_name_label(f.vendor.name if f.vendor else None, f.name)
        for s in await spoolman.get_spools():
            fil = s.filament
            spool_labels[s.id] = _vendor_name_label(fil.vendor.name if fil.vendor else None, fil.name)
    except Exception as exc:  # noqa: BLE001 — labels are a best-effort convenience
        from app.core.log_safe import scrub
        logger.info("sync-log: live Spoolman label lookup failed (using mappings only): %s", scrub(exc))
    return fil_labels, spool_labels


@router.get("/sync-log", response_model=SyncLogResponse)
async def get_sync_log(
    request: Request,
    db: Session = Depends(get_db),
    entity_type: str | None = Query(default=None),
    direction: str | None = Query(default=None),
    action: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    windows: int | None = Query(default=None, ge=1),
) -> SyncLogResponse:
    q = db.query(SyncLog)
    if entity_type is not None:
        q = q.filter(SyncLog.entity_type == entity_type)
    if direction is not None:
        q = q.filter(SyncLog.direction == direction)
    if action is not None:
        q = q.filter(SyncLog.action == action)

    if windows is not None:
        # Find the most recent N distinct non-null cycle_ids (by max timestamp).
        # Entries with null cycle_id are excluded from window mode.
        recent_cycles_subq = (
            db.query(SyncLog.cycle_id)
            .filter(SyncLog.cycle_id.isnot(None))
            .group_by(SyncLog.cycle_id)
            .order_by(func.max(SyncLog.timestamp).desc())
            .limit(windows)
            .scalar_subquery()
        )
        q = q.filter(SyncLog.cycle_id.in_(recent_cycles_subq))
        total = q.count()
        rows = q.order_by(SyncLog.timestamp.desc(), SyncLog.id.desc()).all()
    else:
        total = q.count()
        rows = (
            q.order_by(SyncLog.timestamp.desc(), SyncLog.id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    sm_fil_labels, sm_spool_labels = await _live_spoolman_labels(request)
    resolve_label = _build_label_resolver(db, sm_fil_labels, sm_spool_labels)
    items = [
        SyncLogEntry(
            id=r.id,
            cycle_id=r.cycle_id,
            timestamp=r.timestamp,
            direction=r.direction,
            action=r.action,
            entity_type=r.entity_type,
            label=resolve_label(r),
            spoolman_id=r.spoolman_id,
            filamentdb_filament_id=r.filamentdb_filament_id,
            filamentdb_spool_id=r.filamentdb_spool_id,
            field_name=r.field_name,
            old_value=_decode(r.old_value),
            new_value=_decode(r.new_value),
            error_message=r.error_message,
        )
        for r in rows
    ]
    return SyncLogResponse(items=items, total=total, limit=limit, offset=offset)


@router.delete("/sync-log", response_model=SyncLogDeleteResponse)
def delete_sync_log(db: Session = Depends(get_db)) -> SyncLogDeleteResponse:
    """Clear all sync log entries; returns the count of deleted rows."""
    count = db.query(SyncLog).delete()
    db.commit()
    return SyncLogDeleteResponse(deleted=count)
