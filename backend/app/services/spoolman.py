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

    _PAGE_SIZE = 1000  # records per page for paginated list endpoints

    async def _paginate(self, path: str, extra_params: dict | None = None) -> list[dict]:
        """Fetch all pages from a Spoolman list endpoint using offset pagination.

        Requests pages of _PAGE_SIZE until a page shorter than _PAGE_SIZE is returned,
        then concatenates all pages.  ``extra_params`` are merged into every request.
        """
        base_params = dict(extra_params or {})
        results: list[dict] = []
        offset = 0
        while True:
            params = {**base_params, "limit": self._PAGE_SIZE, "offset": offset}
            resp = await self._http.get(path, params=params)
            resp.raise_for_status()
            page: list[dict] = resp.json()
            results.extend(page)
            if len(page) < self._PAGE_SIZE:
                break
            offset += self._PAGE_SIZE
        return results

    async def get_spools(self) -> list[SpoolmanSpool]:
        """Fetch all spools (active + archived), handling pagination transparently.

        Spoolman's ``/api/v1/spool`` EXCLUDES archived spools by default. The only
        supported way to include them is the ``allow_archived=true`` query param, which
        returns active AND archived in a single listing — there is NO ``archived`` filter
        param. (An unknown ``?archived=true`` is silently ignored by Spoolman and returns
        the active-only list, which made every archived mapped spool look deleted to the
        bridge and hid archived spools from wizard import — fixed 2026-06-22.)
        Callers that want active-only still filter:
            active = [s for s in spools if not s.archived]
        """
        rows = await self._paginate("/api/v1/spool", extra_params={"allow_archived": "true"})
        return [SpoolmanSpool.model_validate(s) for s in rows]

    async def get_spool(self, spool_id: int) -> SpoolmanSpool:
        resp = await self._http.get(f"/api/v1/spool/{spool_id}")
        resp.raise_for_status()
        return SpoolmanSpool.model_validate(resp.json())

    async def get_filaments(self) -> list[SpoolmanFilament]:
        rows = await self._paginate("/api/v1/filament")
        return [SpoolmanFilament.model_validate(f) for f in rows]

    async def get_filament(self, filament_id: int) -> SpoolmanFilament:
        """GET /api/v1/filament/{id} — single filament with nested vendor."""
        resp = await self._http.get(f"/api/v1/filament/{filament_id}")
        resp.raise_for_status()
        return SpoolmanFilament.model_validate(resp.json())

    async def get_vendors(self) -> list[SpoolmanVendor]:
        rows = await self._paginate("/api/v1/vendor")
        return [SpoolmanVendor.model_validate(v) for v in rows]

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
        from app.config import settings as _settings
        try:
            existing_spool = await self.get_field_definitions("spool")
            existing_spool_keys = {f.key for f in existing_spool}
        except Exception as exc:
            logger.warning(
                "ensure_extra_fields: could not read spool field definitions, "
                "skipping spool section: %s", exc,
            )
            existing_spool_keys = set()

        # Build the runtime spool field list from the config-overridable keys so that
        # users who override SPOOLMAN_FIELD_FILAMENTDB_ID / _PARENT_ID / _SPOOL_ID get
        # their custom keys registered instead of the hard-coded defaults.
        runtime_spool_fields = [
            {
                "key": _settings.spoolman_field_filamentdb_id,
                "name": "Filament DB ID",
                "field_type": "text",
            },
            {
                "key": _settings.spoolman_field_filamentdb_parent_id,
                "name": "Filament DB Parent ID",
                "field_type": "text",
            },
            {
                "key": _settings.spoolman_field_filamentdb_spool_id,
                "name": "Filament DB Spool ID",
                "field_type": "text",
            },
        ]

        for field_def in runtime_spool_fields:
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
        # Text fields get an empty-string default; typed (integer/float) fields are
        # registered WITHOUT a default_value (Spoolman rejects a '""' default on a
        # numeric field).
        from app.core.fields import OPENTAG_EXTRA_FIELDS

        # Human-readable names for the seven OpenPrintTag material-setting extras.
        _OPENTAG_FIELD_NAMES: dict[str, str] = {
            "openprinttag_nozzle_temp_min": "OpenPrintTag Nozzle Temp (min)",
            "openprinttag_nozzle_temp_max": "OpenPrintTag Nozzle Temp (max)",
            "openprinttag_drying_temp": "OpenPrintTag Drying Temp",
            "openprinttag_drying_time": "OpenPrintTag Drying Time (h)",
            "openprinttag_hardness_shore_a": "OpenPrintTag Hardness (Shore A)",
            "openprinttag_hardness_shore_d": "OpenPrintTag Hardness (Shore D)",
            "openprinttag_transmission_distance": "OpenPrintTag Transmission Distance",
        }

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
            {
                "key": _settings.spoolman_field_openprinttag_ignore,
                "name": "OpenPrintTag Ignore Updates",
                "field_type": "text",
            },
        ]
        # Append the seven TYPED OpenPrintTag material-setting extras.
        for ef in OPENTAG_EXTRA_FIELDS:
            key = getattr(_settings, ef.config_attr)
            runtime_filament_fields.append({
                "key": key,
                "name": _OPENTAG_FIELD_NAMES.get(ef.default_key, ef.default_key),
                "field_type": ef.field_type,
            })

        for field_def in runtime_filament_fields:
            key = field_def["key"]
            if key in existing_filament_keys:
                continue
            payload = {
                "name": field_def["name"],
                "field_type": field_def["field_type"],
            }
            # Text fields carry an empty-string default; numeric fields must NOT
            # (Spoolman 422s on a string default for an integer/float field).
            if field_def["field_type"] == "text":
                payload["default_value"] = encode_extra_value("")  # '""'
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

    async def trigger_backup(self) -> dict:
        """POST /api/v1/backup — trigger a server-side backup on the Spoolman instance.

        Spoolman writes the backup archive into its own data volume; the bridge
        does not receive or store the file.  Returns the JSON response body
        (typically ``{"path": "/home/user/.local/share/spoolman/backups/..."}``),
        or ``{}`` if Spoolman returns an empty body.
        """
        resp = await self._http.post("/api/v1/backup")
        resp.raise_for_status()
        try:
            return resp.json()
        except Exception:
            return {}

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
