"""POST /api/debug/* — gated reset tools for clean re-testing.

All endpoints return 403 unless debug_mode is currently true in BridgeConfig.
They are intended for development/testing only and must never be exposed in
production. Debug mode is off by default and must be explicitly enabled via
PUT /api/config.

Endpoints:
  POST /api/debug/clear-spoolman-fdb-refs
    Fetches all Spoolman spools; blanks the three cross-ref extras
    (filamentdb_id / filamentdb_spool_id / filamentdb_parent_id) on each spool
    that has any of them set. Returns {"cleared": <n>, "failed": <n>}.

  POST /api/debug/clear-spoolman-opentag-ids
    Fetches all Spoolman filaments; blanks the three OpenPrintTag identity extras
    (openprinttag_slug / openprinttag_uuid / openprinttag_ignore) on each
    filament that has any of them set. Writes to Spoolman only — does NOT touch
    the bridge DB or Filament DB. Returns {"cleared": <n>, "failed": <n>}.

  POST /api/debug/reset-bridge-state
    Deletes all rows from FilamentMapping, SpoolMapping, Snapshot, Conflict, and
    SyncLog — local only, no upstream writes. Resets wizard_completed to false so
    the user can cleanly re-run the wizard. Does NOT clear BridgeConfig beyond
    wizard_completed. Returns per-table deleted counts.

  POST /api/debug/full-reset
    Performs BOTH cleanups in one call: blanks the Spoolman cross-ref extras
    (Spoolman side) AND deletes all five bridge state tables + resets
    wizard_completed (bridge DB side). Returns combined counts. The Spoolman
    side runs first so that a Spoolman error is reported before the local state
    has been destroyed; if the Spoolman side fails the bridge DB reset still
    runs and the Spoolman error is reported in the response rather than as a
    502.
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

# The three filament-level OpenPrintTag identity/state extra field keys.
_OPENTAG_EXTRAS = [
    settings.spoolman_field_openprinttag_slug,
    settings.spoolman_field_openprinttag_uuid,
    settings.spoolman_field_openprinttag_ignore,
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


class FullResetResponse(BaseModel):
    # Bridge DB side (same fields as ResetStateResponse)
    filament_mappings: int
    spool_mappings: int
    snapshots: int
    conflicts: int
    sync_log: int
    wizard_completed_reset: bool
    # Spoolman cross-ref side (same fields as ClearRefsResponse)
    spoolman_cleared: int
    spoolman_failed: int
    # Non-None when the Spoolman fetch or a per-spool error caused a partial
    # failure — bridge DB reset still completed when this is set.
    spoolman_error: str | None = None


# ---------------------------------------------------------------------------
# Shared helper implementations (called by all three endpoints)
# ---------------------------------------------------------------------------


async def _blank_spoolman_xrefs(spoolman: object) -> tuple[int, int, str | None]:
    """Fetch all Spoolman spools and blank the three cross-ref extras on each.

    Returns ``(cleared, failed, error_message)``.  ``error_message`` is non-None
    only when the initial spool fetch fails (in which case cleared=0, failed=0).
    Per-spool write failures are counted in ``failed`` but do not abort the batch.
    """
    blank = encode_extra_value("")

    try:
        spools = await spoolman.get_spools()  # type: ignore[attr-defined]
    except Exception as exc:
        logger.error("blank-spoolman-xrefs: could not fetch spools: %s", exc)
        return 0, 0, str(exc)

    cleared = 0
    failed = 0

    for spool in spools:
        extra = spool.extra or {}
        keys_to_blank = [
            k for k in _XREF_EXTRAS
            if k in extra and extra[k] not in (None, blank, '""', "")
        ]
        if not keys_to_blank:
            continue
        try:
            await spoolman.update_spool(  # type: ignore[attr-defined]
                spool.id,
                {"extra": {k: blank for k in keys_to_blank}},
            )
            logger.info(
                "blank-spoolman-xrefs: blanked extras %s on spool %d",
                keys_to_blank, spool.id,
            )
            cleared += 1
        except Exception as exc:
            logger.warning(
                "blank-spoolman-xrefs: failed to blank extras on spool %d: %s",
                spool.id, exc,
            )
            failed += 1

    return cleared, failed, None


async def _blank_spoolman_opentag_ids(spoolman: object) -> tuple[int, int, str | None]:
    """Fetch all Spoolman filaments and blank the three OpenPrintTag extras on each.

    Returns ``(cleared, failed, error_message)``.  ``error_message`` is non-None
    only when the initial filament fetch fails (in which case cleared=0, failed=0).
    Per-filament write failures are counted in ``failed`` but do not abort the batch.
    """
    blank = encode_extra_value("")

    try:
        filaments = await spoolman.get_filaments()  # type: ignore[attr-defined]
    except Exception as exc:
        logger.error("blank-spoolman-opentag-ids: could not fetch filaments: %s", exc)
        return 0, 0, str(exc)

    cleared = 0
    failed = 0

    for filament in filaments:
        extra = filament.extra or {}
        keys_to_blank = [
            k for k in _OPENTAG_EXTRAS
            if k in extra and extra[k] not in (None, blank, '""', "")
        ]
        if not keys_to_blank:
            continue
        try:
            await spoolman.update_filament(  # type: ignore[attr-defined]
                filament.id,
                {"extra": {k: blank for k in keys_to_blank}},
            )
            logger.info(
                "blank-spoolman-opentag-ids: blanked extras %s on filament %d",
                keys_to_blank, filament.id,
            )
            cleared += 1
        except Exception as exc:
            logger.warning(
                "blank-spoolman-opentag-ids: failed to blank extras on filament %d: %s",
                filament.id, exc,
            )
            failed += 1

    return cleared, failed, None


def _reset_bridge_tables(db: Session) -> tuple[int, int, int, int, int]:
    """Delete all rows from the five bridge state tables and reset wizard_completed.

    Returns ``(filament_mappings, spool_mappings, snapshots, conflicts, sync_log)``.
    Commits the transaction.
    """
    fm_deleted = db.query(FilamentMapping).delete(synchronize_session=False)
    sm_deleted = db.query(SpoolMapping).delete(synchronize_session=False)
    snap_deleted = db.query(Snapshot).delete(synchronize_session=False)
    conflict_deleted = db.query(Conflict).delete(synchronize_session=False)
    log_deleted = db.query(SyncLog).delete(synchronize_session=False)

    set_config_value(db, "wizard_completed", False)
    db.commit()

    logger.info(
        "reset-bridge-tables: filament_mappings=%d spool_mappings=%d "
        "snapshots=%d conflicts=%d sync_log=%d",
        fm_deleted, sm_deleted, snap_deleted, conflict_deleted, log_deleted,
    )
    return fm_deleted, sm_deleted, snap_deleted, conflict_deleted, log_deleted


# ---------------------------------------------------------------------------
# POST /api/debug/clear-spoolman-fdb-refs
# ---------------------------------------------------------------------------


@router.post("/debug/clear-spoolman-fdb-refs", response_model=ClearRefsResponse)
async def clear_spoolman_fdb_refs(
    request: Request,
    db: Session = Depends(get_db),
) -> ClearRefsResponse:
    """Blank the three FDB cross-ref extras on every Spoolman spool that has any set.

    Writes to Spoolman only — requires debug_mode=true.
    Does NOT touch the bridge DB.
    Errors per spool are logged but do not abort the batch.
    """
    _require_debug_mode(db)

    cleared, failed, error = await _blank_spoolman_xrefs(request.app.state.spoolman)
    if error is not None:
        raise HTTPException(status_code=502, detail=error)

    return ClearRefsResponse(cleared=cleared, failed=failed)


# ---------------------------------------------------------------------------
# POST /api/debug/clear-spoolman-opentag-ids
# ---------------------------------------------------------------------------


@router.post("/debug/clear-spoolman-opentag-ids", response_model=ClearRefsResponse)
async def clear_spoolman_opentag_ids(
    request: Request,
    db: Session = Depends(get_db),
) -> ClearRefsResponse:
    """Blank the three OpenPrintTag extras on every Spoolman filament that has any set.

    Writes to Spoolman only — requires debug_mode=true.
    Does NOT touch the bridge DB or Filament DB.
    Errors per filament are logged but do not abort the batch.
    """
    _require_debug_mode(db)

    cleared, failed, error = await _blank_spoolman_opentag_ids(request.app.state.spoolman)
    if error is not None:
        raise HTTPException(status_code=502, detail=error)

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

    fm_deleted, sm_deleted, snap_deleted, conflict_deleted, log_deleted = (
        _reset_bridge_tables(db)
    )

    return ResetStateResponse(
        filament_mappings=fm_deleted,
        spool_mappings=sm_deleted,
        snapshots=snap_deleted,
        conflicts=conflict_deleted,
        sync_log=log_deleted,
        wizard_completed_reset=True,
    )


# ---------------------------------------------------------------------------
# POST /api/debug/full-reset
# ---------------------------------------------------------------------------


@router.post("/debug/full-reset", response_model=FullResetResponse)
async def full_reset(
    request: Request,
    db: Session = Depends(get_db),
) -> FullResetResponse:
    """Perform BOTH cleanups in one call: blank Spoolman cross-refs AND reset the bridge DB.

    Requires debug_mode=true.  Does NOT delete any records in Spoolman or Filament DB.

    Order of operations:
      1. Blank the Spoolman cross-ref extras (so any failure is reported before the
         local state is destroyed).
      2. Delete all five bridge state tables + reset wizard_completed.

    If the Spoolman fetch fails, the bridge DB reset still runs and the error is
    reported in ``spoolman_error`` rather than returning 502.
    """
    _require_debug_mode(db)

    # Step 1 — Spoolman side (run first; failure is non-fatal for the local reset).
    sm_cleared, sm_failed, sm_error = await _blank_spoolman_xrefs(
        request.app.state.spoolman
    )

    # Step 2 — Bridge DB side (always runs even if Spoolman side had errors).
    fm_deleted, sm_del, snap_deleted, conflict_deleted, log_deleted = (
        _reset_bridge_tables(db)
    )

    logger.info(
        "full-reset: spoolman_cleared=%d spoolman_failed=%d spoolman_error=%s | "
        "filament_mappings=%d spool_mappings=%d snapshots=%d conflicts=%d sync_log=%d",
        sm_cleared, sm_failed, sm_error,
        fm_deleted, sm_del, snap_deleted, conflict_deleted, log_deleted,
    )

    return FullResetResponse(
        filament_mappings=fm_deleted,
        spool_mappings=sm_del,
        snapshots=snap_deleted,
        conflicts=conflict_deleted,
        sync_log=log_deleted,
        wizard_completed_reset=True,
        spoolman_cleared=sm_cleared,
        spoolman_failed=sm_failed,
        spoolman_error=sm_error,
    )
