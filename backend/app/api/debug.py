"""POST /api/debug/* — gated reset tools for clean re-testing.

Both endpoints return 403 unless debug_mode is currently true in BridgeConfig.
They are intended for development/testing only and must never be exposed in
production. Debug mode is off by default and must be explicitly enabled via
PUT /api/config.

Endpoints:
  POST /api/debug/clear-spoolman-fdb-refs
    Fetches all Spoolman spools; blanks the three cross-ref extras
    (filamentdb_id / filamentdb_spool_id / filamentdb_parent_id) on each spool
    that has any of them set. Returns {"cleared": <n>, "failed": <n>}.

  POST /api/debug/reset-bridge-state
    Deletes all rows from FilamentMapping, SpoolMapping, Snapshot, Conflict, and
    SyncLog — local only, no upstream writes. Resets wizard_completed to false so
    the user can cleanly re-run the wizard. Does NOT clear BridgeConfig beyond
    wizard_completed. Returns per-table deleted counts.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.config import get_config_value, set_config_value
from app.config import settings
from app.db import get_db
from app.models.conflict import Conflict
from app.models.mapping import FilamentMapping, SpoolMapping
from app.models.snapshot import Snapshot
from app.models.sync_log import SyncLog
from app.schemas.spoolman import encode_extra_value

logger = logging.getLogger(__name__)

router = APIRouter()

# The three spool-level cross-ref extra field keys.
_XREF_EXTRAS = [
    settings.spoolman_field_filamentdb_id,
    settings.spoolman_field_filamentdb_spool_id,
    settings.spoolman_field_filamentdb_parent_id,
]


def _require_debug_mode(db: Session) -> None:
    """Raise 403 if debug_mode is not currently true."""
    if not get_config_value(db, "debug_mode", False):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "debug_mode_required",
                "message": (
                    "This endpoint is only available when debug_mode is enabled. "
                    "Enable it via PUT /api/config with debug_mode=true."
                ),
            },
        )


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class ClearRefsResponse(BaseModel):
    cleared: int
    failed: int


class ResetStateResponse(BaseModel):
    filament_mappings: int
    spool_mappings: int
    snapshots: int
    conflicts: int
    sync_log: int
    wizard_completed_reset: bool


# ---------------------------------------------------------------------------
# POST /api/debug/clear-spoolman-fdb-refs
# ---------------------------------------------------------------------------


@router.post("/debug/clear-spoolman-fdb-refs", response_model=ClearRefsResponse)
async def clear_spoolman_fdb_refs(
    request: Request,
    db: Session = Depends(get_db),
) -> ClearRefsResponse:
    """Blank the three FDB cross-ref extras on every Spoolman spool that has any set.

    Writes to Spoolman — requires debug_mode=true.
    Errors per spool are logged but do not abort the batch.
    """
    _require_debug_mode(db)

    spoolman = request.app.state.spoolman
    blank = encode_extra_value("")

    try:
        spools = await spoolman.get_spools()
    except Exception as exc:
        logger.error("clear-spoolman-fdb-refs: could not fetch spools: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    cleared = 0
    failed = 0

    for spool in spools:
        extra = spool.extra or {}
        # Collect which of the three keys are present and non-blank.
        keys_to_blank = [
            k for k in _XREF_EXTRAS
            if k in extra and extra[k] not in (None, blank, '""', "")
        ]
        if not keys_to_blank:
            continue
        try:
            await spoolman.update_spool(
                spool.id,
                {"extra": {k: blank for k in keys_to_blank}},
            )
            logger.info(
                "clear-spoolman-fdb-refs: blanked extras %s on spool %d",
                keys_to_blank, spool.id,
            )
            cleared += 1
        except Exception as exc:
            logger.warning(
                "clear-spoolman-fdb-refs: failed to blank extras on spool %d: %s",
                spool.id, exc,
            )
            failed += 1

    return ClearRefsResponse(cleared=cleared, failed=failed)


# ---------------------------------------------------------------------------
# POST /api/debug/reset-bridge-state
# ---------------------------------------------------------------------------


@router.post("/debug/reset-bridge-state", response_model=ResetStateResponse)
def reset_bridge_state(
    db: Session = Depends(get_db),
) -> ResetStateResponse:
    """Delete all rows from the five bridge state tables (local only).

    Does not write to Spoolman or Filament DB.
    Resets wizard_completed to false so the wizard can be re-run.
    BridgeConfig (all other keys including debug_mode) is preserved.
    """
    _require_debug_mode(db)

    fm_deleted = db.query(FilamentMapping).delete(synchronize_session=False)
    sm_deleted = db.query(SpoolMapping).delete(synchronize_session=False)
    snap_deleted = db.query(Snapshot).delete(synchronize_session=False)
    conflict_deleted = db.query(Conflict).delete(synchronize_session=False)
    log_deleted = db.query(SyncLog).delete(synchronize_session=False)

    # Reset wizard_completed so the user can cleanly re-run the wizard.
    set_config_value(db, "wizard_completed", False)
    db.commit()

    logger.info(
        "reset-bridge-state: filament_mappings=%d spool_mappings=%d "
        "snapshots=%d conflicts=%d sync_log=%d",
        fm_deleted, sm_deleted, snap_deleted, conflict_deleted, log_deleted,
    )

    return ResetStateResponse(
        filament_mappings=fm_deleted,
        spool_mappings=sm_deleted,
        snapshots=snap_deleted,
        conflicts=conflict_deleted,
        sync_log=log_deleted,
        wizard_completed_reset=True,
    )
