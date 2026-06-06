"""Local cache for the OpenPrintTag dataset fetched from FDB's GET /api/openprinttag.

Design
------
* The cache is a single JSON file in DATA_DIR (``opentag_cache.json``).
* Re-fetch happens only when the file is missing, when ``fetched_at`` is older
  than ``OPENTAG_CACHE_MAX_AGE_HOURS``, or when the caller passes ``force=True``.
* Fetch is on-demand (no background job).
* If FDB returns 404 the endpoint is absent (too-old FDB); a clear error is raised.
* If the cache file is corrupt/missing and the network call fails the error
  propagates to the caller.

The top-level cache file shape::

    {
        "fetched_at": "2026-06-06T12:00:00+00:00",
        "count": 1234,
        "materials": [ ...OPTMaterial dicts... ]
    }
"""

from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_CACHE_FILENAME = "opentag_cache.json"


def _cache_path(data_dir: str) -> Path:
    return Path(data_dir) / _CACHE_FILENAME


def _is_stale(fetched_at_iso: str | None, max_age_hours: int) -> bool:
    """Return True when the cache timestamp is absent or older than max_age_hours."""
    if not fetched_at_iso:
        return True
    try:
        ts = datetime.datetime.fromisoformat(fetched_at_iso.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=datetime.timezone.utc)
        age = datetime.datetime.now(datetime.timezone.utc) - ts
        return age.total_seconds() > max_age_hours * 3600
    except (ValueError, TypeError):
        return True


def _load_cache(data_dir: str) -> dict[str, Any] | None:
    """Load the raw cache dict from disk; returns None if file is absent/corrupt."""
    path = _cache_path(data_dir)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        logger.warning("opentag_cache: failed to read %s: %s", path, exc)
        return None


def _save_cache(data_dir: str, materials: list[dict], fetched_at: str) -> None:
    path = _cache_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"fetched_at": fetched_at, "count": len(materials), "materials": materials}
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    logger.info("opentag_cache: saved %d materials to %s", len(materials), path)


async def load_opentag_dataset(
    fdb_client: Any,
    data_dir: str,
    max_age_hours: int,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Return the cached OpenTag dataset, re-fetching when stale or forced.

    Returns::

        {
            "fetched_at": "<iso>",
            "count": N,
            "stale": False,
            "materials": [...OPTMaterial dicts...]
        }

    Raises ``httpx.HTTPStatusError`` (404) when FDB lacks the endpoint.
    Raises ``RuntimeError`` for other unexpected HTTP errors.
    """
    cache = _load_cache(data_dir)
    needs_fetch = force or (cache is None) or _is_stale(
        (cache or {}).get("fetched_at"), max_age_hours
    )

    if needs_fetch:
        logger.info("opentag_cache: fetching fresh dataset from FDB (force=%s)", force)
        try:
            materials = await fdb_client.get_openprinttag()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise httpx.HTTPStatusError(
                    "FDB /api/openprinttag returned 404 — "
                    "upgrade Filament DB to a version that includes the OpenPrintTag endpoint",
                    request=exc.request,
                    response=exc.response,
                ) from exc
            raise
        fetched_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        _save_cache(data_dir, materials, fetched_at)
        cache = {"fetched_at": fetched_at, "count": len(materials), "materials": materials}

    return {
        "fetched_at": cache["fetched_at"],
        "count": cache.get("count", len(cache.get("materials", []))),
        "stale": _is_stale(cache.get("fetched_at"), max_age_hours),
        "materials": cache.get("materials", []),
    }


def get_cache_metadata(data_dir: str, max_age_hours: int) -> dict[str, Any]:
    """Return metadata about the local cache without triggering a network fetch."""
    cache = _load_cache(data_dir)
    if cache is None:
        return {"fetched_at": None, "count": 0, "stale": True}
    return {
        "fetched_at": cache.get("fetched_at"),
        "count": cache.get("count", len(cache.get("materials", []))),
        "stale": _is_stale(cache.get("fetched_at"), max_age_hours),
    }
