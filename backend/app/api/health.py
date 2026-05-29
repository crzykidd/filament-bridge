"""GET /api/health — FR-1: connectivity check for both upstream APIs.

Returns 200 in all cases. Overall status is:
  "ok"       — both systems reachable
  "degraded" — one system unreachable
  "error"    — both systems unreachable

Per-system status includes version (where available), record counts, and any error message.
"""

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app import __version__
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


class SystemHealth(BaseModel):
    status: Literal["ok", "error"]
    url: str
    version: str | None = None
    counts: dict[str, int] = {}
    error: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "error"]
    bridge_version: str
    systems: dict[str, SystemHealth]


async def _check_spoolman(request: Request) -> SystemHealth:
    url = settings.spoolman_url
    try:
        info = await request.app.state.spoolman.health()
        return SystemHealth(
            status="ok",
            url=url,
            version=info["version"],
            counts={
                "filaments": info["filament_count"],
                "spools": info["spool_count"],
                "active_spools": info["active_spool_count"],
            },
        )
    except Exception as exc:
        logger.warning("Spoolman health check failed: %s", exc)
        return SystemHealth(status="error", url=url, error=str(exc))


async def _check_filamentdb(request: Request) -> SystemHealth:
    url = settings.filamentdb_url
    try:
        info = await request.app.state.filamentdb.health()
        return SystemHealth(
            status="ok",
            url=url,
            counts={
                "filaments": info["filament_count"],
                "spools": info["spool_count"],
            },
        )
    except Exception as exc:
        logger.warning("Filament DB health check failed: %s", exc)
        return SystemHealth(status="error", url=url, error=str(exc))


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    spoolman_result, filamentdb_result = await asyncio.gather(
        _check_spoolman(request),
        _check_filamentdb(request),
    )

    systems = {
        "spoolman": spoolman_result,
        "filamentdb": filamentdb_result,
    }

    ok_count = sum(1 for s in systems.values() if s.status == "ok")
    if ok_count == 2:
        overall: Literal["ok", "degraded", "error"] = "ok"
    elif ok_count == 1:
        overall = "degraded"
    else:
        overall = "error"

    return HealthResponse(
        status=overall,
        bridge_version=__version__,
        systems=systems,
    )
