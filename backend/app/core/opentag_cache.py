"""Local cache for the OpenPrintTag dataset fetched directly from the OpenPrintTag
GitHub tarball (``https://api.github.com/repos/OpenPrintTag/openprinttag-database/tarball/main``).

Design
------
* A single download fetches the complete dataset: brand names, material properties,
  primary and secondary colors all come from the same tarball.  No FDB dependency.
* The cache is a single JSON file in DATA_DIR (``opentag_cache.json``).
* Re-fetch happens only when the file is missing, when ``fetched_at`` is older
  than ``OPENTAG_CACHE_MAX_AGE_HOURS``, or when the caller passes ``force=True``.
* Fetch is on-demand (no background job).
* If the network call fails the error propagates to the caller (502/504 in the API layer).
* If the cache file is corrupt/missing and the network call fails the error propagates.

The top-level cache file shape::

    {
        "fetched_at": "2026-06-06T12:00:00+00:00",
        "count": 1234,
        "materials": [ ...OPTMaterial dicts... ]
    }

OPTMaterial dict shape (identical to the old FDB feed shape — consumers are unchanged):

    {
        "uuid":               str,
        "slug":               str,
        "brandSlug":          str,
        "brandName":          str,            # from data/brands/<slug>.yaml → name
        "name":               str,
        "type":               str | None,
        "abbreviation":       str | None,
        "color":              str | None,     # "#RRGGBB" (uppercase, with hash)
        "secondaryColors":    list[str],      # ["#RRGGBB", ...] list
        "density":            float | None,
        "nozzleTempMin":      int | None,
        "nozzleTempMax":      int | None,
        "bedTempMin":         int | None,
        "bedTempMax":         int | None,
        "chamberTemp":        int | None,
        "preheatTemp":        int | None,
        "dryingTemp":         int | None,
        "dryingTime":         int | None,
        "hardnessShoreD":     float | None,
        "transmissionDistance": float | None,
        "tags":               list[str],
        "photoUrl":           str | None,
        "productUrl":         str | None,
        "completenessScore":  int | None,     # not in tarball; always None
        "completenessTier":   str | None,     # not in tarball; always None
    }

Field mapping (raw YAML key → feed key):
  yaml.uuid                               → uuid
  yaml.slug                               → slug
  yaml.brand.slug                         → brandSlug
  brand YAML name (by yaml.brand.slug)    → brandName
  yaml.name                               → name
  yaml.type                               → type
  yaml.abbreviation                       → abbreviation
  yaml.primary_color.color_rgba           → color   (rgba→hex: strip #, drop alpha, uppercase, re-add #)
  yaml.secondary_colors[].color_rgba      → secondaryColors  (same conversion, list of "#RRGGBB")
  yaml.properties.density                 → density
  yaml.properties.min_print_temperature   → nozzleTempMin
  yaml.properties.max_print_temperature   → nozzleTempMax
  yaml.properties.min_bed_temperature     → bedTempMin
  yaml.properties.max_bed_temperature     → bedTempMax
  yaml.properties.min_chamber_temperature
    or yaml.properties.chamber_temperature → chamberTemp
  yaml.properties.preheat_temperature     → preheatTemp
  yaml.properties.drying_temperature      → dryingTemp
  yaml.properties.drying_time             → dryingTime
  yaml.properties.hardness_shore_d        → hardnessShoreD
  yaml.transmission_distance              → transmissionDistance  (top-level key)
  yaml.tags                               → tags
  yaml.photos[0].url                      → photoUrl
  yaml.url                                → productUrl
  (absent in tarball)                     → completenessScore = None
  (absent in tarball)                     → completenessTier  = None
"""

from __future__ import annotations

import datetime
import io
import json
import logging
import tarfile
from pathlib import Path
from typing import Any

import httpx
import yaml

logger = logging.getLogger(__name__)

_CACHE_FILENAME = "opentag_cache.json"
_TARBALL_URL = (
    "https://api.github.com/repos/OpenPrintTag/openprinttag-database/tarball/main"
)
_FETCH_TIMEOUT = httpx.Timeout(120.0)


# ---------------------------------------------------------------------------
# RGBA → hex helpers
# (Previously lived in opentag_secondary.py; that module is retired.
#  The _rgba_to_hex helper is kept here for the direct tarball parser.)
# ---------------------------------------------------------------------------


def _rgba_to_hex(rgba: str | None) -> str | None:
    """Convert ``#RRGGBBAA`` (or ``#RRGGBB``) to bare uppercase ``RRGGBB``.

    Strips the leading ``#``, drops the trailing alpha pair if present, upper-cases.
    Returns ``None`` for falsy or too-short input.

    Examples::

        _rgba_to_hex('#000000ff') -> '000000'
        _rgba_to_hex('#98282fff') -> '98282F'
        _rgba_to_hex('#ddb95dff') -> 'DDB95D'
        _rgba_to_hex('#AABBCC')   -> 'AABBCC'
    """
    if not rgba:
        return None
    stripped = rgba.lstrip("#")
    if len(stripped) < 6:
        return None
    return stripped[:6].upper()


# ---------------------------------------------------------------------------
# Tarball parser
# ---------------------------------------------------------------------------


def _parse_tarball(raw_bytes: bytes) -> list[dict[str, Any]]:
    """Parse the OpenPrintTag tarball and return a list of OPTMaterial dicts.

    Two-pass algorithm:
    1. First pass — collect ``data/brands/<slug>.yaml`` → build ``{slug: name}`` map.
    2. Second pass — parse ``data/materials/**/*.yaml`` and emit one material dict
       per file, attaching ``brandName`` from the index built in pass 1.

    Only ``class: FFF`` materials are included (SLA, etc. are skipped silently).

    Secondary colors are populated in the same pass from
    ``secondary_colors[].color_rgba`` — no separate fetch needed.
    """
    # Pass 1: build brand slug → brand name index
    brand_names: dict[str, str] = {}
    with tarfile.open(fileobj=io.BytesIO(raw_bytes), mode="r:gz") as tf:
        for member in tf.getmembers():
            path = member.name
            if "/data/brands/" not in path or not path.endswith(".yaml"):
                continue
            fobj = tf.extractfile(member)
            if fobj is None:
                continue
            try:
                doc: Any = yaml.safe_load(fobj.read())
            except Exception as exc:
                logger.debug("opentag_cache: YAML parse error in brand %s: %s", path, exc)
                continue
            if not isinstance(doc, dict):
                continue
            slug = doc.get("slug")
            bname = doc.get("name")
            if slug and bname:
                brand_names[slug] = bname

    # Pass 2: parse material YAMLs
    materials: list[dict[str, Any]] = []
    with tarfile.open(fileobj=io.BytesIO(raw_bytes), mode="r:gz") as tf:
        for member in tf.getmembers():
            path = member.name
            if "/data/materials/" not in path or not path.endswith(".yaml"):
                continue
            fobj = tf.extractfile(member)
            if fobj is None:
                continue
            try:
                doc = yaml.safe_load(fobj.read())
            except Exception as exc:
                logger.debug("opentag_cache: YAML parse error in %s: %s", path, exc)
                continue
            if not isinstance(doc, dict):
                continue

            # Only include FFF (filament) materials — skip SLA and other classes.
            mat_class = doc.get("class")
            if mat_class and mat_class != "FFF":
                continue

            brand_slug: str = (doc.get("brand") or {}).get("slug") or ""
            brand_name: str = brand_names.get(brand_slug, brand_slug)

            # Primary color: color_rgba → bare uppercase RRGGBB, re-add # prefix
            primary_color_doc = doc.get("primary_color") or {}
            raw_primary = (
                primary_color_doc.get("color_rgba")
                if isinstance(primary_color_doc, dict)
                else None
            )
            color_hex_bare = _rgba_to_hex(raw_primary)
            color_value = f"#{color_hex_bare}" if color_hex_bare else None

            # Secondary colors — parsed in the same pass
            secondary_colors_raw: list[Any] = doc.get("secondary_colors") or []
            secondary_colors: list[str] = []
            if isinstance(secondary_colors_raw, list):
                for sc in secondary_colors_raw:
                    h = _rgba_to_hex(
                        sc.get("color_rgba") if isinstance(sc, dict) else None
                    )
                    if h:
                        secondary_colors.append(f"#{h}")

            props: dict[str, Any] = doc.get("properties") or {}

            # Chamber temperature: prefer min_chamber_temperature, fall back to plain key
            chamber = props.get("min_chamber_temperature") or props.get("chamber_temperature")

            # Photos: first photo URL (if any)
            photos = doc.get("photos") or []
            photo_url: str | None = None
            if photos and isinstance(photos[0], dict):
                photo_url = photos[0].get("url")

            mat: dict[str, Any] = {
                "uuid": doc.get("uuid"),
                "slug": doc.get("slug"),
                "brandSlug": brand_slug,
                "brandName": brand_name,
                "name": doc.get("name"),
                "type": doc.get("type"),
                "abbreviation": doc.get("abbreviation"),
                "color": color_value,
                "secondaryColors": secondary_colors,
                "density": props.get("density"),
                "nozzleTempMin": props.get("min_print_temperature"),
                "nozzleTempMax": props.get("max_print_temperature"),
                "bedTempMin": props.get("min_bed_temperature"),
                "bedTempMax": props.get("max_bed_temperature"),
                "chamberTemp": chamber,
                "preheatTemp": props.get("preheat_temperature"),
                "dryingTemp": props.get("drying_temperature"),
                "dryingTime": props.get("drying_time"),
                "hardnessShoreD": props.get("hardness_shore_d"),
                "transmissionDistance": doc.get("transmission_distance"),
                "tags": doc.get("tags") or [],
                "photoUrl": photo_url,
                "productUrl": doc.get("url"),
                "completenessScore": None,
                "completenessTier": None,
            }
            materials.append(mat)

    logger.info(
        "opentag_cache: parsed %d materials from tarball (%d brands indexed)",
        len(materials), len(brand_names),
    )
    return materials


async def _fetch_from_tarball(
    http: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """Download the OpenPrintTag tarball from GitHub and return parsed OPTMaterial dicts.

    ``http`` must be an ``httpx.AsyncClient`` that supports absolute URLs (no
    ``base_url``).  When ``None``, a fresh client is created and closed internally.

    Raises ``httpx.TimeoutException`` when the download times out.
    Raises ``httpx.HTTPStatusError`` for non-2xx responses (e.g. GitHub 429 / 503).
    Raises ``httpx.RequestError`` for connectivity failures.
    Raises ``RuntimeError`` if the tarball is completely unparseable (not gzip).
    """
    own_client = http is None
    client: httpx.AsyncClient = http if http is not None else httpx.AsyncClient()
    try:
        resp = await client.get(
            _TARBALL_URL, timeout=_FETCH_TIMEOUT, follow_redirects=True
        )
        resp.raise_for_status()
        raw_bytes = resp.content
    finally:
        if own_client:
            await client.aclose()

    try:
        return _parse_tarball(raw_bytes)
    except tarfile.TarError as exc:
        raise RuntimeError(
            f"OpenPrintTag tarball is not a valid gzip archive: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


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
    path = Path(data_dir) / _CACHE_FILENAME
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        logger.warning("opentag_cache: failed to read %s: %s", path, exc)
        return None


def _save_cache(data_dir: str, materials: list[dict], fetched_at: str) -> None:
    path = Path(data_dir) / _CACHE_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"fetched_at": fetched_at, "count": len(materials), "materials": materials}
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    logger.info("opentag_cache: saved %d materials to %s", len(materials), path)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def load_opentag_dataset(
    data_dir: str,
    max_age_hours: int,
    *,
    force: bool = False,
    http: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Return the cached OpenTag dataset, re-fetching from OpenPrintTag when stale or forced.

    Fetches directly from the OpenPrintTag GitHub tarball — no Filament DB dependency.

    Returns::

        {
            "fetched_at": "<iso>",
            "count": N,
            "stale": False,
            "materials": [...OPTMaterial dicts...]
        }

    ``http`` is an optional ``httpx.AsyncClient`` for the tarball download (useful
    in tests to inject a fake client).  When ``None``, a fresh client is created.

    Raises ``httpx.TimeoutException`` on download timeout.
    Raises ``httpx.HTTPStatusError`` for non-2xx from GitHub.
    Raises ``httpx.RequestError`` for connectivity failures.
    """
    cache = _load_cache(data_dir)

    # Self-heal: treat a cached materials list that isn't a non-empty list of
    # dicts as malformed (e.g. written when FDB returned the OPTDatabase wrapper
    # and the bridge iterated its keys as strings).  Re-fetch as if stale so
    # the bad data is replaced without requiring a manual Refresh call.
    def _materials_valid(c: dict) -> bool:
        mats = c.get("materials")
        return (
            isinstance(mats, list)
            and len(mats) > 0
            and all(isinstance(m, dict) for m in mats)
        )

    needs_fetch = force or (cache is None) or _is_stale(
        (cache or {}).get("fetched_at"), max_age_hours
    ) or (cache is not None and not _materials_valid(cache))

    if needs_fetch:
        logger.info(
            "opentag_cache: fetching fresh dataset from OpenPrintTag GitHub tarball"
            " (force=%s)",
            force,
        )
        materials = await _fetch_from_tarball(http)
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
