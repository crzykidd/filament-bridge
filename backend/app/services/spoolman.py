"""Async HTTP client for the Spoolman REST API.

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
    decode_extra_value,
    encode_extra_value,
)

logger = logging.getLogger(__name__)

# Cross-ref extra fields the bridge requires on the Spoolman spool entity
_REQUIRED_SPOOL_FIELDS = [
    {"key": "filamentdb_id", "name": "Filament DB ID", "field_type": "text"},
    {"key": "filamentdb_parent_id", "name": "Filament DB Parent ID", "field_type": "text"},
    {"key": "filamentdb_spool_id", "name": "Filament DB Spool ID", "field_type": "text"},
]

# Extra fields the bridge requires on the Spoolman FILAMENT entity.
# Key names are config-overridable; defaults are used here for startup registration
# (the runtime path reads the key from settings at write time).
_REQUIRED_FILAMENT_FIELDS = [
    {
        "key": "filamentdb_material_tags",
        "name": "Filament DB Material Tags",
        "field_type": "text",
    },
]


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
    # Extra-field value encoding (centralized — callers never touch raw)
    # ------------------------------------------------------------------

    @staticmethod
    def decode_extra(raw: str | None) -> Any:
        return decode_extra_value(raw)

    @staticmethod
    def encode_extra(value: Any) -> str:
        return encode_extra_value(value)

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

    async def get_spool(self, spool_id: int) -> SpoolmanSpool:
        resp = await self._http.get(f"/api/v1/spool/{spool_id}")
        resp.raise_for_status()
        return SpoolmanSpool.model_validate(resp.json())

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
    # Write methods
    # ------------------------------------------------------------------

    async def update_spool(self, spool_id: int, payload: dict) -> SpoolmanSpool:
        """PATCH /api/v1/spool/{id} — update weight, extra fields, location, etc."""
        resp = await self._http.patch(f"/api/v1/spool/{spool_id}", json=payload)
        resp.raise_for_status()
        return SpoolmanSpool.model_validate(resp.json())

    async def create_spool(self, payload: dict) -> SpoolmanSpool:
        """POST /api/v1/spool — create a new spool (requires filament_id)."""
        resp = await self._http.post("/api/v1/spool", json=payload)
        resp.raise_for_status()
        return SpoolmanSpool.model_validate(resp.json())

    async def update_filament(self, filament_id: int, payload: dict) -> SpoolmanFilament:
        """PATCH /api/v1/filament/{id} — update filament fields (color, multi_color, etc.)."""
        resp = await self._http.patch(f"/api/v1/filament/{filament_id}", json=payload)
        resp.raise_for_status()
        return SpoolmanFilament.model_validate(resp.json())

    async def create_filament(self, payload: dict) -> SpoolmanFilament:
        """POST /api/v1/filament — create a new filament record."""
        resp = await self._http.post("/api/v1/filament", json=payload)
        resp.raise_for_status()
        return SpoolmanFilament.model_validate(resp.json())

    async def create_vendor(self, payload: dict) -> SpoolmanVendor:
        """POST /api/v1/vendor — create a new vendor record."""
        resp = await self._http.post("/api/v1/vendor", json=payload)
        resp.raise_for_status()
        return SpoolmanVendor.model_validate(resp.json())

    async def ensure_extra_fields(self) -> None:
        """Create the bridge's required extra fields on spool and filament if they don't exist.

        Called once on startup and before any OpenTag apply writes. Idempotent —
        only POSTs fields not yet registered in Spoolman. Spoolman stores extra
        field values JSON-double-quoted; default_value for a text field is '""'.

        Spool fields: filamentdb_id, filamentdb_parent_id, filamentdb_spool_id
        Filament fields: filamentdb_material_tags, openprinttag_slug, openprinttag_uuid

        The spool section and filament section run independently — a failure in one
        (including a transient error on get_field_definitions) does not abort the other.
        """
        # ---- Spool fields ----
        try:
            existing_spool = await self.get_field_definitions("spool")
            existing_spool_keys = {f.key for f in existing_spool}
        except Exception as exc:
            logger.warning(
                "ensure_extra_fields: could not read spool field definitions, "
                "skipping spool section: %s", exc,
            )
            existing_spool_keys = set()

        for field_def in _REQUIRED_SPOOL_FIELDS:
            key = field_def["key"]
            if key in existing_spool_keys:
                continue
            payload = {
                "name": field_def["name"],
                "field_type": field_def["field_type"],
                "default_value": encode_extra_value(""),  # '""'
            }
            try:
                resp = await self._http.post(f"/api/v1/field/spool/{key}", json=payload)
                resp.raise_for_status()
                logger.info("Created Spoolman extra field: spool.%s", key)
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                body = exc.response.text if isinstance(exc, httpx.HTTPStatusError) else str(exc)
                logger.warning(
                    "Could not create Spoolman extra field spool.%s: %s %s",
                    key, status, body,
                )

        # ---- Filament fields ----
        from app.config import settings as _settings
        try:
            existing_filament = await self.get_field_definitions("filament")
            existing_filament_keys = {f.key for f in existing_filament}
        except Exception as exc:
            logger.warning(
                "ensure_extra_fields: could not read filament field definitions, "
                "will attempt to create all filament fields: %s", exc,
            )
            existing_filament_keys = set()

        # Build the runtime field list, substituting the config-overridable keys.
        runtime_filament_fields = [
            {
                "key": _settings.spoolman_field_filamentdb_material_tags,
                "name": "Filament DB Material Tags",
                "field_type": "text",
            },
            {
                "key": _settings.spoolman_field_openprinttag_slug,
                "name": "OpenPrintTag Slug",
                "field_type": "text",
            },
            {
                "key": _settings.spoolman_field_openprinttag_uuid,
                "name": "OpenPrintTag UUID",
                "field_type": "text",
            },
        ]

        for field_def in runtime_filament_fields:
            key = field_def["key"]
            if key in existing_filament_keys:
                continue
            payload = {
                "name": field_def["name"],
                "field_type": field_def["field_type"],
                "default_value": encode_extra_value(""),  # '""'
            }
            try:
                resp = await self._http.post(f"/api/v1/field/filament/{key}", json=payload)
                resp.raise_for_status()
                logger.info("Created Spoolman extra field: filament.%s", key)
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                body = exc.response.text if isinstance(exc, httpx.HTTPStatusError) else str(exc)
                logger.warning(
                    "Could not create Spoolman extra field filament.%s: %s %s",
                    key, status, body,
                )

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
