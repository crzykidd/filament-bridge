"""Shared spool-weight write primitives.

Both the conflict-resolution path (``core/conflict_apply.py:_apply_weight``) and
the mobile scan-and-update path need the same two operations:

  * an ABSOLUTE true-up that writes the agreed net weight to Spoolman and the
    matching gross weight to Filament DB, then refreshes BOTH side snapshots so
    the next sync cycle does not re-detect the change (anti-ping-pong), and
  * a USAGE-mode write that, on a *decrease*, logs an FDB usage entry (preserving
    the audit trail) instead of overwriting ``totalWeight`` directly — and falls
    back to the absolute path on an *increase*.

The weight model (see CLAUDE.md):
  * Spoolman ``remaining_weight`` is NET filament.
  * Filament DB ``totalWeight`` is GROSS (filament + empty-reel tare).
  * ``tare`` = the FDB filament's ``spoolWeight`` (default
    ``core/weight.py:DEFAULT_TARE_GRAMS`` when missing).
  * ``gross = net + tare`` ; ``net = gross − tare``.

All values are rounded to 2 dp and clamped to ≥ 0 before writing.
"""

from __future__ import annotations

import datetime

from sqlalchemy.orm import Session

from app.core.engine import _log, _merge_snapshot
from app.services.filamentdb import FilamentDBClient
from app.services.spoolman import SpoolmanClient


def _round_clamp(value: float) -> float:
    return round(max(float(value), 0.0), 2)


async def apply_absolute_weight(
    db: Session,
    spoolman: SpoolmanClient,
    filamentdb: FilamentDBClient,
    *,
    sm_spool_id: int,
    fdb_fil_id: str,
    fdb_spool_id: str,
    net_w: float,
    tare: float,
    cycle_id: str,
    source: str = "conflict_apply",
    old_value: object = "diverged",
) -> float:
    """Write an ABSOLUTE agreed net weight to both systems and refresh both snapshots.

    Spoolman gets ``remaining_weight = net_w``; Filament DB gets
    ``totalWeight = net_w + tare`` (both rounded/clamped). Snapshots on both sides
    advance to the converged values so the engine doesn't re-detect the change.

    Returns the converged net weight ``W`` (Spoolman units).

    Raises on upstream write failure (the caller leaves the conflict open / surfaces
    the error). This is the exact behaviour the #21 conflict path relied on.
    """
    w = _round_clamp(net_w)
    fdb_total = round(w + float(tare), 2)

    await spoolman.update_spool(sm_spool_id, {"remaining_weight": w})
    await filamentdb.update_spool(fdb_fil_id, fdb_spool_id, {"totalWeight": fdb_total})

    _merge_snapshot(db, "spoolman", "spool", str(sm_spool_id), {"remaining_weight": w})
    _merge_snapshot(db, "filamentdb", "spool", fdb_spool_id, {"totalWeight": fdb_total})

    _log(
        db, cycle_id, source, "update", "spool",
        spoolman_id=sm_spool_id, fdb_filament_id=fdb_fil_id, fdb_spool_id=fdb_spool_id,
        field_name="weight", old_value=old_value, new_value=w,
    )
    return w


async def apply_usage_weight(
    db: Session,
    spoolman: SpoolmanClient,
    filamentdb: FilamentDBClient,
    *,
    sm_spool_id: int,
    fdb_fil_id: str,
    fdb_spool_id: str,
    net_w: float,
    tare: float,
    current_fdb_gross: float,
    cycle_id: str,
    source: str = "mobile-scale",
) -> float:
    """Converge to an agreed net weight, preferring an FDB usage entry on a DECREASE.

    On a **decrease** (new gross < current FDB ``totalWeight``): log the consumed
    delta as an FDB usage entry (``filamentdb.log_usage(..., source=source)``) — this
    preserves the audit trail and FDB reduces ``totalWeight`` itself — then set the
    Spoolman ``remaining_weight`` directly and refresh both snapshots to the agreed
    converged values.

    On an **increase** (or no change): fall back to :func:`apply_absolute_weight`
    (a correction / refill is a direct write, never a negative usage entry).

    Returns the converged net weight ``W`` (Spoolman units).
    """
    w = _round_clamp(net_w)
    new_gross = round(w + float(tare), 2)
    cur_gross = round(float(current_fdb_gross), 2)

    if new_gross >= cur_gross:
        # Increase or no change → direct absolute write (no negative usage).
        return await apply_absolute_weight(
            db, spoolman, filamentdb,
            sm_spool_id=sm_spool_id, fdb_fil_id=fdb_fil_id, fdb_spool_id=fdb_spool_id,
            net_w=w, tare=tare, cycle_id=cycle_id, source=source, old_value=cur_gross,
        )

    # Decrease → log usage for the consumed grams; FDB reduces totalWeight itself.
    delta = round(cur_gross - new_gross, 2)
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    await filamentdb.log_usage(
        fdb_fil_id, fdb_spool_id, delta,
        job_label="Mobile scale update", source=source, date=now_iso,
    )
    await spoolman.update_spool(sm_spool_id, {"remaining_weight": w})

    _merge_snapshot(db, "spoolman", "spool", str(sm_spool_id), {"remaining_weight": w})
    _merge_snapshot(db, "filamentdb", "spool", fdb_spool_id, {"totalWeight": new_gross})

    _log(
        db, cycle_id, source, "update", "spool",
        spoolman_id=sm_spool_id, fdb_filament_id=fdb_fil_id, fdb_spool_id=fdb_spool_id,
        field_name="weight", old_value=cur_gross, new_value=w,
    )
    return w
