"""GET /api/sync-log — audit log viewer (FR-17).

Paginated, newest-first, filterable by entity_type / direction / action. Each
entry carries the deep-link IDs where applicable.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.sync_log import SyncLog
from app.schemas.api import SyncLogEntry, SyncLogResponse

router = APIRouter()


def _decode(raw: str | None):
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


@router.get("/sync-log", response_model=SyncLogResponse)
def get_sync_log(
    db: Session = Depends(get_db),
    entity_type: str | None = Query(default=None),
    direction: str | None = Query(default=None),
    action: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> SyncLogResponse:
    q = db.query(SyncLog)
    if entity_type is not None:
        q = q.filter(SyncLog.entity_type == entity_type)
    if direction is not None:
        q = q.filter(SyncLog.direction == direction)
    if action is not None:
        q = q.filter(SyncLog.action == action)

    total = q.count()
    rows = (
        q.order_by(SyncLog.timestamp.desc(), SyncLog.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    items = [
        SyncLogEntry(
            id=r.id,
            cycle_id=r.cycle_id,
            timestamp=r.timestamp,
            direction=r.direction,
            action=r.action,
            entity_type=r.entity_type,
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
