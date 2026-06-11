"""Upstream version compatibility gate.

Sync is hard-blocked when a KNOWN upstream version is below the minimum
supported (see ``core/version.py``). This module is the shared entry point the
API routers and the wizard use to refuse a sync task with a clear message; the
engine's ``run_sync_cycle`` performs the same check inline (reusing the FDB
version it already fetches) so auto-sync is skipped too.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.version import incompatibilities

logger = logging.getLogger(__name__)


async def _spoolman_version(spoolman: Any) -> str | None:
    try:
        return (await spoolman.health()).get("version")
    except Exception:  # pragma: no cover - connectivity handled by health endpoint
        return None


async def _filamentdb_version(filamentdb: Any) -> str | None:
    try:
        return await filamentdb.get_version()
    except Exception:  # pragma: no cover
        return None


async def sync_compatibility_errors(spoolman: Any, filamentdb: Any) -> list[str]:
    """Return blocking incompatibility messages (empty list = OK to sync)."""
    fdb_v = await _filamentdb_version(filamentdb)
    sm_v = await _spoolman_version(spoolman)
    return incompatibilities(fdb_v, sm_v)
