"""Shared spool-weight write primitive.

Both the conflict-resolution path (``core/conflict_apply.py:_apply_weight``) and
the mobile scan-and-update path converge a spool to an ABSOLUTE net weight on both
systems. The tricky part is Filament DB's weight model:

  * Spoolman ``remaining_weight`` is NET filament; it accepts an absolute set in
    either direction.
  * Filament DB ``totalWeight`` is GROSS (filament + empty-reel tare). You can only
    **raise** it with a direct ``PUT`` — **lowering** it must go through the usage
    endpoint (``log_usage``); FDB has no other way to reduce a spool's weight, and a
    direct PUT to a lower value is silently ignored. (This mirrors the engine's
    ongoing SM→FDB pass: decrease → usage, increase → direct write.)
  * ``tare`` = the FDB filament's ``spoolWeight`` (default
    ``core/weight.py:DEFAULT_TARE_GRAMS`` when missing).
  * ``gross = net + tare`` ; ``net = gross − tare``.

After any write BOTH side snapshots are refreshed to the agreed values so the next
sync cycle does not re-detect the change (anti-ping-pong). All values are rounded to
2 dp and clamped to ≥ 0 before writing.
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
    current_fdb_gross: float,
    cycle_id: str,
    source: str = "conflict_apply",
    job_label: str = "Weight correction",
    old_value: object = "diverged",
) -> float:
    """Converge a spool to an ABSOLUTE net weight ``net_w`` on BOTH systems, then
    refresh both snapshots.

    Spoolman gets ``remaining_weight = net_w`` (absolute set, any direction).

    Filament DB gets ``totalWeight = net_w + tare``, respecting FDB's model
    (``current_fdb_gross`` is the spool's current FDB ``totalWeight``):
      * **increase / refill** (new gross ≥ current) → direct ``PUT {totalWeight}``.
      * **decrease** (new gross < current) → ``log_usage(delta)`` tagged with
        ``source`` / ``job_label`` — FDB reduces ``totalWeight`` itself (a direct
        PUT to a lower value would be a silent no-op).

    Returns the converged net weight ``W`` (Spoolman units). Raises on upstream
    write failure (the caller surfaces the error / leaves the conflict open).
    """
    w = _round_clamp(net_w)
    new_gross = round(w + float(tare), 2)
    cur_gross = round(float(current_fdb_gross), 2)

    # Spoolman: absolute set works in either direction.
    await spoolman.update_spool(sm_spool_id, {"remaining_weight": w})

    # Filament DB: lowering => usage entry (the only way to reduce); raising => PUT.
    if new_gross < cur_gross:
        delta = round(cur_gross - new_gross, 2)
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        await filamentdb.log_usage(
            fdb_fil_id, fdb_spool_id, delta,
            job_label=job_label, source=source, date=now_iso,
        )
    else:
        await filamentdb.update_spool(fdb_fil_id, fdb_spool_id, {"totalWeight": new_gross})

    # Refresh BOTH snapshots to the agreed post-write values (anti-ping-pong).
    _merge_snapshot(db, "spoolman", "spool", str(sm_spool_id), {"remaining_weight": w})
    _merge_snapshot(db, "filamentdb", "spool", fdb_spool_id, {"totalWeight": new_gross})

    _log(
        db, cycle_id, source, "update", "spool",
        spoolman_id=sm_spool_id, fdb_filament_id=fdb_fil_id, fdb_spool_id=fdb_spool_id,
        field_name="weight", old_value=old_value, new_value=w,
    )
    return w
