"""Sync controls — FR-8 / FR-14 / FR-18 and the dashboard payload (FR-15).

All sync logic is delegated to core/engine.run_sync_cycle; this router only
triggers it and shapes the responses.
"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.api.config import get_config_value, set_config_value
from app.api.errors import api_error
from app.api.health import _check_filamentdb, _check_spoolman
from app.api.mappings import build_mapping_rows
from app.config import settings
from app.core.engine import run_sync_cycle
from app.db import get_db
from app.models.conflict import Conflict
from app.models.sync_log import SyncLog
from app.schemas.api import (
    AutoSyncRequest,
    AutoSyncResponse,
    CycleResultResponse,
    SyncStatusResponse,
    SystemStatus,
)

router = APIRouter()


def _to_response(result) -> CycleResultResponse:
    return CycleResultResponse(
        cycle_id=result.cycle_id,
        dry_run=result.dry_run,
        created=result.created,
        updated=result.updated,
        conflicts=result.conflicts,
        skipped=result.skipped,
        errors=result.errors,
        preview=result.preview,
    )


@router.post("/sync/trigger", response_model=CycleResultResponse)
async def trigger_sync(request: Request, db: Session = Depends(get_db)) -> CycleResultResponse:
    """Run one live sync cycle now (FR-18)."""
    result = await run_sync_cycle(
        db, request.app.state.spoolman, request.app.state.filamentdb, dry_run=False
    )
    return _to_response(result)


@router.post("/sync/dry-run", response_model=CycleResultResponse)
async def dry_run_sync(request: Request, db: Session = Depends(get_db)) -> CycleResultResponse:
    """Compute the next cycle's full changeset without applying anything (FR-14)."""
    result = await run_sync_cycle(
        db, request.app.state.spoolman, request.app.state.filamentdb, dry_run=True
    )
    return _to_response(result)


@router.post("/sync/auto", response_model=AutoSyncResponse)
def set_auto_sync(payload: AutoSyncRequest, db: Session = Depends(get_db)) -> AutoSyncResponse:
    """Enable/disable scheduled auto-sync.

    Refuses to enable until the initial sync wizard has completed (FR-8: auto-sync
    is off by default and requires explicit user action after initial sync).
    """
    if payload.enabled and not get_config_value(db, "wizard_completed", False):
        raise api_error(
            409,
            "wizard_incomplete",
            "Auto-sync cannot be enabled until the initial sync wizard has completed.",
        )
    set_config_value(db, "auto_sync_enabled", payload.enabled)
    db.commit()
    return AutoSyncResponse(auto_sync_enabled=payload.enabled)


@router.get("/sync/status", response_model=SyncStatusResponse)
async def sync_status(request: Request, db: Session = Depends(get_db)) -> SyncStatusResponse:
    """Dashboard payload: connectivity, counts, last/next sync, pending conflicts (FR-15)."""
    spoolman_health = await _check_spoolman(request)
    filamentdb_health = await _check_filamentdb(request)
    systems = {
        "spoolman": SystemStatus(**spoolman_health.model_dump()),
        "filamentdb": SystemStatus(**filamentdb_health.model_dump()),
    }

    rows = build_mapping_rows(db)
    counts = {"in_sync": 0, "pending": 0, "conflict": 0, "unlinked": 0, "total": len(rows)}
    for r in rows:
        counts[r.status] += 1

    pending_conflicts = db.query(Conflict).filter(Conflict.resolved_at.is_(None)).count()
    last_sync_at = db.query(func.max(SyncLog.timestamp)).scalar()

    auto_enabled = bool(get_config_value(db, "auto_sync_enabled", False))
    # next_sync_at is approximated as last_sync + interval when auto-sync is on;
    # the APScheduler job is the real authority (see docs/decisions.md).
    next_sync_at: datetime.datetime | None = None
    if auto_enabled and last_sync_at is not None:
        next_sync_at = last_sync_at + datetime.timedelta(seconds=settings.sync_interval_seconds)

    return SyncStatusResponse(
        last_sync_at=last_sync_at,
        next_sync_at=next_sync_at,
        auto_sync_enabled=auto_enabled,
        wizard_completed=bool(get_config_value(db, "wizard_completed", False)),
        pending_conflicts=pending_conflicts,
        counts=counts,
        systems=systems,
    )
