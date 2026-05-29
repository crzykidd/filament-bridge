"""Async HTTP client for the Filament DB REST API.

Filament DB has two response projections:
  - get_filaments() → list view (trimmed, embedded spools have _id/label/totalWeight/retired)
  - get_filament(id) → detail view (full fields, variant inheritance resolved, full spool history)

Usage:
    async with FilamentDBClient(settings.filamentdb_url) as client:
        filaments = await client.get_filaments()
"""

import logging
from typing import Any

import httpx

from app.schemas.filamentdb import FDBFilament, FDBFilamentDetail, FDBSpoolDetail

logger = logging.getLogger(__name__)

# Computed/Mongoose fields that must be stripped before any PUT to avoid
# overriding variant inheritance or triggering server-side validation errors.
_STRIP_BEFORE_PUT: frozenset[str] = frozenset({
    "_inherited", "_parent", "_variants", "hasVariants", "inherits",
    "settings", "__v", "instanceId", "createdAt", "updatedAt", "_deletedAt",
})


def _strip_computed(payload: dict) -> dict:
    return {k: v for k, v in payload.items() if k not in _STRIP_BEFORE_PUT}


class FilamentDBClient:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "FilamentDBClient":
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(15.0),
        )
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("FilamentDBClient not started — use as async context manager")
        return self._client

    # ------------------------------------------------------------------
    # Read methods
    # ------------------------------------------------------------------

    async def get_filaments(self) -> list[FDBFilament]:
        """Fetch all filaments (list/trimmed projection).

        Use for enumeration and weight/label diffing. For property sync,
        fetch individual records with get_filament() to get the detail projection.
        """
        resp = await self._http.get("/api/filaments")
        resp.raise_for_status()
        return [FDBFilament.model_validate(f) for f in resp.json()]

    async def get_filament(self, filament_id: str) -> FDBFilamentDetail:
        """Fetch a single filament (detail projection with resolved variant inheritance)."""
        resp = await self._http.get(f"/api/filaments/{filament_id}")
        resp.raise_for_status()
        return FDBFilamentDetail.model_validate(resp.json())

    # ------------------------------------------------------------------
    # Write methods
    # ------------------------------------------------------------------

    async def update_filament(self, filament_id: str, payload: dict) -> FDBFilamentDetail:
        """PUT /api/filaments/:id — update filament properties.

        Computed/Mongoose fields are stripped automatically before the request
        so callers do not need to sanitise the payload themselves.
        """
        clean = _strip_computed(payload)
        resp = await self._http.put(f"/api/filaments/{filament_id}", json=clean)
        resp.raise_for_status()
        return FDBFilamentDetail.model_validate(resp.json())

    async def log_usage(
        self,
        filament_id: str,
        spool_id: str,
        grams: float,
        job_label: str,
        source: str,
        date: str,
    ) -> dict:
        """POST /api/filaments/:id/spools/:spoolId/usage — log a usage entry.

        This is the ONLY way the engine decrements FDB spool weight; raw
        totalWeight overwrites are never used for decrements so that Filament DB's
        usage history audit trail is preserved.
        """
        payload = {
            "grams": grams,
            "jobLabel": job_label,
            "source": source,
            "date": date,
        }
        resp = await self._http.post(
            f"/api/filaments/{filament_id}/spools/{spool_id}/usage",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()

    async def update_spool(
        self, filament_id: str, spool_id: str, payload: dict
    ) -> dict:
        """PUT /api/filaments/:id/spools/:spoolId — update spool fields.

        Used for non-weight fields and weight *increases* (totalWeight up).
        Weight decrements must go through log_usage() instead.
        """
        resp = await self._http.put(
            f"/api/filaments/{filament_id}/spools/{spool_id}",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()

    async def create_spool(self, filament_id: str, payload: dict) -> dict:
        """POST /api/filaments/:id/spools — add a new spool subdocument."""
        resp = await self._http.post(
            f"/api/filaments/{filament_id}/spools",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()

    async def create_filament(self, payload: dict) -> FDBFilamentDetail:
        """POST /api/filaments — create a new filament (set parentId for variants)."""
        resp = await self._http.post("/api/filaments", json=payload)
        resp.raise_for_status()
        return FDBFilamentDetail.model_validate(resp.json())

    # ------------------------------------------------------------------
    # Health / connectivity
    # ------------------------------------------------------------------

    async def health(self) -> dict[str, Any]:
        """Probe Filament DB and return record counts.

        Uses the filament list endpoint (no dedicated health/version endpoint exists).
        Raises on network/HTTP errors so the caller can report the system as unreachable.
        """
        filaments = await self.get_filaments()
        spool_count = sum(len(f.spools) for f in filaments)
        return {
            "filament_count": len(filaments),
            "spool_count": spool_count,
        }
