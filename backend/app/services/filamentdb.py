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

from app.schemas.filamentdb import FDBFilament, FDBFilamentDetail

logger = logging.getLogger(__name__)


def extract_created_spool_id(resp: dict, *, label_field: str, label_value: str) -> str:
    """Return the ``_id`` of the spool that was just created via POST /api/filaments/:id/spools.

    The FDB endpoint returns the *filament* document (with a ``spools`` array), so
    ``resp["_id"]`` is the filament id — NOT the spool id.  This helper finds the
    newly-created spool by matching ``label_field`` against ``label_value`` inside
    ``resp["spools"]``.

    Fall-back order:
    1. Label-match: find the spool whose ``{label_field}`` equals ``label_value``.
    2. Last-spool: if no label match, use the last entry in ``spools`` (most recently added).
    3. Bare spool: if there is no ``spools`` key at all, treat ``resp`` itself as the spool
       (defensive handling for any future FDB variant that returns the spool directly).
    4. Returns ``""`` when the id cannot be determined.
    """
    spools = resp.get("spools")
    if isinstance(spools, list) and spools:
        for sp in spools:
            if str(sp.get(label_field, "")) == str(label_value):
                sid = sp.get("_id") or sp.get("id")
                if sid:
                    return str(sid)
        # Fallback: newest-added spool (last in array).
        last = spools[-1]
        sid = last.get("_id") or last.get("id")
        if sid:
            return str(sid)
    # Response is a bare spool subdocument (defensive / future-proofing).
    sid = resp.get("_id") or resp.get("id")
    return str(sid) if sid else ""


# Computed/Mongoose fields that must be stripped before any PUT to avoid
# overriding variant inheritance or triggering server-side validation errors.
_STRIP_BEFORE_PUT: frozenset[str] = frozenset({
    "_inherited", "_parent", "_variants", "hasVariants", "inherits",
    "settings", "__v", "instanceId", "createdAt", "updatedAt", "_deletedAt",
})


def _strip_computed(payload: dict) -> dict:
    return {k: v for k, v in payload.items() if k not in _STRIP_BEFORE_PUT}


class FilamentDBClient:
    def __init__(self, base_url: str, api_key: str = "") -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key or ""
        self._client: httpx.AsyncClient | None = None
        self._version: str | None = None
        self._version_fetched = False

    async def __aenter__(self) -> "FilamentDBClient":
        # FDB API-key auth (FDB >= 1.39.0): send a Bearer token when configured.
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else None
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(15.0),
            headers=headers,
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

    async def get_locations(self) -> list[dict]:
        """GET /api/locations — list all locations."""
        resp = await self._http.get("/api/locations")
        resp.raise_for_status()
        return resp.json()

    async def create_location(self, name: str) -> dict:
        """POST /api/locations — create a new location by name."""
        resp = await self._http.post("/api/locations", json={"name": name})
        resp.raise_for_status()
        return resp.json()

    async def create_filament(self, payload: dict) -> FDBFilamentDetail:
        """POST /api/filaments — create a new filament (set parentId for variants)."""
        resp = await self._http.post("/api/filaments", json=payload)
        resp.raise_for_status()
        return FDBFilamentDetail.model_validate(resp.json())

    # ------------------------------------------------------------------
    # FDB settings-bag merge (scoped exception)
    # ------------------------------------------------------------------

    async def merge_filament_settings(
        self, filament_id: str, keys: dict[str, str]
    ) -> None:
        """Merge specific keys into a FDB filament's ``settings{}`` bag.

        APPROVED SCOPED EXCEPTION: CLAUDE.md forbids touching the settings bag.
        This method is the only permitted path — it ONLY merges the two OpenTag
        identity keys (``openprinttag_slug`` / ``openprinttag_uuid``) and
        preserves all other settings keys unchanged.  The caller (engine +
        wizard) is responsible for ensuring only those two keys are passed.

        Implementation: fetch the current filament (detail view) → read its
        ``settings`` bag (empty dict if absent) → merge ``keys`` in → write
        back via PUT using the same ``_strip_computed`` stripping that
        ``update_filament`` uses, but re-attaching the merged ``settings`` bag
        AFTER stripping (settings is not a computed field — it is slicer
        passthrough, but we deliberately add only the two identity keys).
        """
        detail_resp = await self._http.get(f"/api/filaments/{filament_id}")
        detail_resp.raise_for_status()
        raw = detail_resp.json()
        current_settings: dict = raw.get("settings") or {}
        # Check if already equal — idempotent (no rewrite if nothing changed).
        if all(current_settings.get(k) == v for k, v in keys.items()):
            return
        merged = {**current_settings, **keys}
        payload = _strip_computed(raw)
        payload["settings"] = merged
        put_resp = await self._http.put(f"/api/filaments/{filament_id}", json=payload)
        put_resp.raise_for_status()

    # ------------------------------------------------------------------
    # Backup
    # ------------------------------------------------------------------

    async def get_snapshot(self) -> dict:
        """GET /api/snapshot — download a full Filament DB JSON snapshot.

        Returns the raw snapshot dict: ``{version, createdAt, collections}``.
        The snapshot includes all collections (filaments, nozzles, printers,
        locations, print history, catalogs, tombstones) at schema v4.

        Restore via ``POST /api/snapshot`` (destructive — not exposed by the bridge).

        Uses a generous 300 s timeout because the snapshot can be large (full DB dump).
        """
        resp = await self._http.get(
            "/api/snapshot",
            timeout=httpx.Timeout(300.0),
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Health / connectivity
    # ------------------------------------------------------------------

    async def get_version(self) -> str | None:
        """Resolve the Filament DB app version (best-effort, cached for the client's life).

        Filament DB has no dedicated version endpoint, but ``GET /api/openapi`` returns
        an OpenAPI document whose ``info.version`` is injected from package.json.
        Returns None if the endpoint is absent or unparseable.
        """
        if self._version_fetched:
            return self._version
        try:
            resp = await self._http.get("/api/openapi")
            resp.raise_for_status()
            self._version = (resp.json().get("info") or {}).get("version")
        except Exception:
            self._version = None
        self._version_fetched = True
        return self._version

    async def health(self) -> dict[str, Any]:
        """Probe Filament DB and return version + record counts.

        Uses the filament list endpoint for counts and ``/api/openapi`` for the version
        (no dedicated health endpoint exists). The version is refreshed on each probe so
        an upstream upgrade is detected without restarting the bridge.
        Raises on network/HTTP errors so the caller can report the system as unreachable.
        """
        self._version_fetched = False  # force a fresh version read per probe
        version = await self.get_version()
        filaments = await self.get_filaments()
        spool_count = sum(len(f.spools) for f in filaments)
        return {
            "version": version,
            "filament_count": len(filaments),
            "spool_count": spool_count,
        }
