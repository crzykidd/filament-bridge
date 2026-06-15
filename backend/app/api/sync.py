"""Sync controls — FR-8 / FR-14 / FR-18 and the dashboard payload (FR-15).

All sync logic is delegated to core/engine.run_sync_cycle; this router only
triggers it and shapes the responses.
"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.api.config import _effective_sync_interval, get_config_value, set_config_value
from app.api.errors import api_error
from app.api.health import _check_filamentdb, _check_spoolman
from app.api.mappings import build_mapping_rows
from app.core.compat import sync_compatibility_errors
from app.core.dryrun import plan_dry_run
from app.core.engine import run_sync_cycle
from app.core.filament_status import filament_mapping_status
from app.core.version import incompatibilities
from app.db import get_db
from app.models.conflict import Conflict
from app.models.mapping import FilamentMapping
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


async def _require_compatible_upstreams(request: Request) -> None:
    """Raise 409 when a known upstream version is below the minimum supported.

    Hard-gates every sync task (trigger, dry-run, auto-sync enable, wizard
    execute) so nothing runs against an unsupported Filament DB / Spoolman.
    """
    blocked = await sync_compatibility_errors(
        request.app.state.spoolman, request.app.state.filamentdb
    )
    if blocked:
        raise api_error(
            409, "upstream_version_unsupported",
            "Sync disabled — " + "; ".join(blocked) + ".",
        )


@router.post("/sync/trigger", response_model=CycleResultResponse)
async def trigger_sync(request: Request, db: Session = Depends(get_db)) -> CycleResultResponse:
    """Run one live sync cycle now (FR-18)."""
    await _require_compatible_upstreams(request)
    result = await run_sync_cycle(
        db, request.app.state.spoolman, request.app.state.filamentdb, dry_run=False
    )
    return _to_response(result)


@router.post("/sync/dry-run", response_model=CycleResultResponse)
async def dry_run_sync(request: Request, db: Session = Depends(get_db)) -> CycleResultResponse:
    """Compute the full changeset without applying anything (FR-14).

    Uses the unified matcher-driven planner so it reports created/updated/
    conflicted/skipped regardless of bridge state (empty or linked).
    """
    await _require_compatible_upstreams(request)
    result = await plan_dry_run(
        db, request.app.state.spoolman, request.app.state.filamentdb
    )
    return _to_response(result)


@router.post("/sync/auto", response_model=AutoSyncResponse)
async def set_auto_sync(
    payload: AutoSyncRequest, request: Request, db: Session = Depends(get_db)
) -> AutoSyncResponse:
    """Enable/disable scheduled auto-sync.

    Refuses to enable until the initial sync wizard has completed (FR-8), and
    refuses to enable while an upstream version is below the minimum supported.
    """
    if payload.enabled and not get_config_value(db, "wizard_completed", False):
        raise api_error(
            409,
            "wizard_incomplete",
            "Auto-sync cannot be enabled until the initial sync wizard has completed.",
        )
    if payload.enabled:
        await _require_compatible_upstreams(request)
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
    # Derive the sync-block state from the versions already fetched above.
    blocked_reasons = incompatibilities(filamentdb_health.version, spoolman_health.version)

    rows = build_mapping_rows(db)
    counts = {"in_sync": 0, "pending": 0, "conflict": 0, "unlinked": 0, "total": len(rows)}
    for r in rows:
        counts[r.status] += 1

    # Filament-level counts: iterate real (non-synthetic) FilamentMappings.
    # Exclude rows where spoolman_filament_id IS NULL (synthetic container parents
    # created in generic_container mode — they have no real cross-system counterpart).
    filament_counts: dict[str, int] = {"in_sync": 0, "pending": 0, "conflict": 0, "total": 0}
    open_conflict_fdb_ids: set[str] = {
        c.filamentdb_filament_id
        for c in db.query(Conflict).filter(
            Conflict.resolved_at.is_(None),
            Conflict.filamentdb_filament_id.is_not(None),
        ).all()
        if c.filamentdb_filament_id
    }
    real_filament_mappings = (
        db.query(FilamentMapping)
        .filter(FilamentMapping.spoolman_filament_id.is_not(None))
        .all()
    )
    for fm in real_filament_mappings:
        filament_counts["total"] += 1
        status = filament_mapping_status(db, fm, open_conflict_fdb_ids)
        filament_counts[status] += 1

    pending_conflicts = db.query(Conflict).filter(Conflict.resolved_at.is_(None)).count()
    last_sync_at = db.query(func.max(SyncLog.timestamp)).scalar()

    auto_enabled = bool(get_config_value(db, "auto_sync_enabled", False))
    # next_sync_at is approximated as last_sync + interval when auto-sync is on;
    # the APScheduler job is the real authority (see docs/decisions.md).
    # Use _effective_sync_interval so the DB-overridden interval (from Settings) is
    # reflected rather than the env-var default.
    next_sync_at: datetime.datetime | None = None
    if auto_enabled and last_sync_at is not None:
        next_sync_at = last_sync_at + datetime.timedelta(seconds=_effective_sync_interval(db))

    return SyncStatusResponse(
        last_sync_at=last_sync_at,
        next_sync_at=next_sync_at,
        auto_sync_enabled=auto_enabled,
        wizard_completed=bool(get_config_value(db, "wizard_completed", False)),
        pending_conflicts=pending_conflicts,
        counts=counts,
        filament_counts=filament_counts,
        systems=systems,
        sync_blocked=bool(blocked_reasons),
        sync_blocked_reasons=blocked_reasons,
    )
