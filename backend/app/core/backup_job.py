"""Shared backup helpers — file-producing logic reused by the HTTP endpoints
(``app/api/backup.py``) and the scheduled nightly job (``_backup_job`` in
``app/main.py``).

What gets backed up (issue #5):
  - **bridge-state** — the bridge's own ``GET /backup/export`` payload
    (mappings, config, open conflicts), written to
    ``{data_dir}/backups/bridge-state-<UTC ts>.json``.
  - **filamentdb-snapshot** — the full Filament DB JSON snapshot
    (``GET /api/snapshot``), written to
    ``{data_dir}/backups/filamentdb-snapshot-<UTC ts>.json``.

Spoolman's server-side backup is deliberately NOT part of the scheduled path:
Spoolman writes its archive into its own volume and the bridge has no way to
prune it, so scheduling it would leak storage with no retention control. The
manual ``POST /backup/spoolman`` button stays as-is.

Old files matching the two known prefixes are pruned to a configurable retention
window. Only those prefixes are ever deleted — Spoolman archives and unrelated
files in the directory are never touched.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import re

logger = logging.getLogger(__name__)

# UTC timestamp format shared with the manual FDB snapshot filename.
_TS_FMT = "%Y%m%dT%H%M%SZ"
_TS_RE = re.compile(r"(\d{8}T\d{6}Z)")

BRIDGE_STATE_PREFIX = "bridge-state-"
FILAMENTDB_SNAPSHOT_PREFIX = "filamentdb-snapshot-"
DEFAULT_PREFIXES = (BRIDGE_STATE_PREFIX, FILAMENTDB_SNAPSHOT_PREFIX)


def _utc_ts() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime(_TS_FMT)


def backups_dir(data_dir: str) -> str:
    """Return ``{data_dir}/backups`` (does not create it)."""
    return os.path.join(data_dir, "backups")


def build_state_export(db) -> dict:
    """Return the bridge-state export payload as a JSON-serialisable dict.

    Delegates to ``app.api.backup.export_backup`` so there is a single source of
    truth for the export shape; the Pydantic model is dumped to a plain dict
    (json mode → datetimes serialised as strings).
    """
    from app.api.backup import export_backup  # local import avoids a cycle

    payload = export_backup(db)
    return payload.model_dump(mode="json")


def write_bridge_state_backup(db, data_dir: str, *, ts: str | None = None) -> str:
    """Write the bridge-state export to ``{data_dir}/backups/`` and return the path."""
    ts = ts or _utc_ts()
    target_dir = backups_dir(data_dir)
    os.makedirs(target_dir, exist_ok=True)
    path = os.path.join(target_dir, f"{BRIDGE_STATE_PREFIX}{ts}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(build_state_export(db), fh)
    return path


async def write_filamentdb_backup(filamentdb, data_dir: str, *, ts: str | None = None) -> str:
    """Fetch the FDB snapshot and write it to ``{data_dir}/backups/``; return the path."""
    ts = ts or _utc_ts()
    snapshot = await filamentdb.get_snapshot()
    target_dir = backups_dir(data_dir)
    os.makedirs(target_dir, exist_ok=True)
    path = os.path.join(target_dir, f"{FILAMENTDB_SNAPSHOT_PREFIX}{ts}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh)
    return path


def _file_age_dt(filename: str, dir_path: str) -> datetime.datetime:
    """Return the UTC datetime for a backup file.

    Prefers the ``YYYYMMDDTHHMMSSZ`` stamp embedded in the filename; falls back to
    the file's mtime when the stamp can't be parsed.
    """
    m = _TS_RE.search(filename)
    if m:
        try:
            return datetime.datetime.strptime(m.group(1), _TS_FMT).replace(
                tzinfo=datetime.timezone.utc
            )
        except ValueError:
            pass
    mtime = os.path.getmtime(os.path.join(dir_path, filename))
    return datetime.datetime.fromtimestamp(mtime, tz=datetime.timezone.utc)


def prune_backups(
    dir_path: str,
    retention_days: int,
    *,
    prefixes: tuple[str, ...] = DEFAULT_PREFIXES,
    now: datetime.datetime | None = None,
) -> list[str]:
    """Delete backup files older than ``retention_days``; return the deleted names.

    Only files whose name starts with one of ``prefixes`` are considered — every
    other file in the directory (Spoolman archives, unrelated data) is left
    untouched. Age is read from the UTC timestamp embedded in the filename, or the
    file mtime when that can't be parsed. ``retention_days <= 0`` is a no-op
    (keep everything). A missing directory is a no-op.
    """
    if retention_days <= 0:
        return []
    if not os.path.isdir(dir_path):
        return []
    now = now or datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(days=retention_days)
    deleted: list[str] = []
    for name in os.listdir(dir_path):
        if not name.startswith(prefixes):
            continue
        full = os.path.join(dir_path, name)
        if not os.path.isfile(full):
            continue
        if _file_age_dt(name, dir_path) < cutoff:
            try:
                os.remove(full)
                deleted.append(name)
            except OSError as exc:  # noqa: PERF203
                logger.warning("backup prune: could not delete %s: %s", name, exc)
    if deleted:
        logger.info(
            "backup prune: deleted %d file(s) older than %d day(s): %s",
            len(deleted),
            retention_days,
            ", ".join(sorted(deleted)),
        )
    return deleted


async def run_scheduled_backup(db, filamentdb, *, settings) -> dict:
    """Run the enabled backups, then prune. Returns a small result summary.

    ``settings`` is the resolved effective config object exposing
    ``backup_bridge_state_enabled``, ``backup_filamentdb_enabled``,
    ``backup_retention_days`` and ``data_dir``. The caller is responsible for the
    master ``backup_schedule_enabled`` gate (mirrors the ``_sync_job`` pattern).

    Each writer is guarded so a failure of one (e.g. FDB unreachable) never
    prevents the other or the prune. Pruning always runs.
    """
    data_dir = settings.data_dir
    result: dict = {"bridge_state": None, "filamentdb": None, "pruned": []}
    ts = _utc_ts()  # one timestamp for the whole run

    if getattr(settings, "backup_bridge_state_enabled", True):
        try:
            result["bridge_state"] = write_bridge_state_backup(db, data_dir, ts=ts)
            logger.info("scheduled backup: wrote bridge-state -> %s", result["bridge_state"])
        except Exception as exc:  # noqa: BLE001
            logger.error("scheduled backup: bridge-state failed: %s", exc, exc_info=True)

    if getattr(settings, "backup_filamentdb_enabled", True):
        try:
            result["filamentdb"] = await write_filamentdb_backup(filamentdb, data_dir, ts=ts)
            logger.info("scheduled backup: wrote filamentdb snapshot -> %s", result["filamentdb"])
        except Exception as exc:  # noqa: BLE001
            logger.error("scheduled backup: filamentdb snapshot failed: %s", exc, exc_info=True)

    result["pruned"] = prune_backups(
        backups_dir(data_dir), int(getattr(settings, "backup_retention_days", 7))
    )
    return result
