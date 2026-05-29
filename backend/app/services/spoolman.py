"""Async HTTP client for the Spoolman REST API.

Only read methods are implemented here (Phase 0). Write methods come in Phase 1
alongside the sync engine.

Usage:
    async with SpoolmanClient(settings.spoolman_url) as client:
        spools = await client.get_spools()
"""

import asyncio
import logging
from typing import Any

import httpx

from app.schemas.spoolman import (
    SpoolmanFieldDef,
    SpoolmanFilament,
    SpoolmanInfo,
    SpoolmanSpool,
    SpoolmanVendor,
)

logger = logging.getLogger(__name__)


class SpoolmanClient:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "SpoolmanClient":
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(10.0),
        )
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("SpoolmanClient not started — use as async context manager")
        return self._client

    # ------------------------------------------------------------------
    # Read methods
    # ------------------------------------------------------------------

    async def get_spools(self) -> list[SpoolmanSpool]:
        """Fetch all spools (active + archived).

        Caller is responsible for filtering archived spools:
            active = [s for s in spools if not s.archived]
        """
        resp = await self._http.get("/api/v1/spool", params={"limit": 1000})
        resp.raise_for_status()
        return [SpoolmanSpool.model_validate(s) for s in resp.json()]

    async def get_filaments(self) -> list[SpoolmanFilament]:
        resp = await self._http.get("/api/v1/filament", params={"limit": 1000})
        resp.raise_for_status()
        return [SpoolmanFilament.model_validate(f) for f in resp.json()]

    async def get_vendors(self) -> list[SpoolmanVendor]:
        resp = await self._http.get("/api/v1/vendor", params={"limit": 1000})
        resp.raise_for_status()
        return [SpoolmanVendor.model_validate(v) for v in resp.json()]

    async def get_field_definitions(self, entity_type: str) -> list[SpoolmanFieldDef]:
        """Fetch extra-field definitions for the given entity type (spool, filament, vendor)."""
        resp = await self._http.get(f"/api/v1/field/{entity_type}")
        resp.raise_for_status()
        return [SpoolmanFieldDef.model_validate(f) for f in resp.json()]

    # ------------------------------------------------------------------
    # Health / connectivity
    # ------------------------------------------------------------------

    async def health(self) -> dict[str, Any]:
        """Probe Spoolman and return version + record counts.

        Runs the three API calls concurrently. Raises on network/HTTP errors so
        the caller (health endpoint) can report the system as unreachable.
        The version call is best-effort — if /api/v1/info is absent the rest still succeeds.
        """

        async def _get_version() -> str | None:
            try:
                resp = await self._http.get("/api/v1/info")
                resp.raise_for_status()
                return SpoolmanInfo.model_validate(resp.json()).version
            except Exception:
                return None

        version, spools, filaments = await asyncio.gather(
            _get_version(),
            self.get_spools(),
            self.get_filaments(),
        )

        return {
            "version": version,
            "spool_count": len(spools),
            "active_spool_count": sum(1 for s in spools if not s.archived),
            "filament_count": len(filaments),
        }
