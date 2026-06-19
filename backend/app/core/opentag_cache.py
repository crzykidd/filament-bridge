"""Local cache for the OpenPrintTag dataset fetched directly from the OpenPrintTag
GitHub tarball (``https://api.github.com/repos/OpenPrintTag/openprinttag-database/tarball/main``).

Design
------
* A single download fetches the complete dataset: brand names, material properties,
  primary and secondary colors all come from the same tarball.  No FDB dependency.
* The cache is a single JSON file in DATA_DIR (``opentag_cache.json``).
* Re-fetch is gated by a cheap upstream **commit-SHA check** (see
  ``get_upstream_commit_sha``): when the cache is stale (or the caller forces a
  check) the SHA is compared against the cached one — a match bumps the cache age
  WITHOUT re-downloading the heavy tarball; only a differing/absent SHA triggers a
  download.  ``force_pull=True`` skips the SHA check and always downloads.
* Fetch is on-demand (no background job).
* If the network call fails the error propagates to the caller (502/504 in the API layer).
* If the cache file is corrupt/missing and the network call fails the error propagates.
* The SHA check itself is best-effort: any failure (timeout / rate-limit / non-2xx)
  returns ``None`` and the caller falls back to downloading — a failed check never
  hard-fails a refresh.

The top-level cache file shape::

    {
        "fetched_at": "2026-06-06T12:00:00+00:00",
        "count": 1234,
        "commit_sha": "abc123…",          # upstream main HEAD SHA at fetch time (None if unknown)
        "schema_version": 2,              # cache shape version (see CACHE_SCHEMA_VERSION)
        "materials": [ ...OPTMaterial dicts... ],
        "packages_by_material": { "<material_slug>": [ ...OPTPackage dicts... ] },
        "containers_by_slug": { "<container_slug>": { ...OPTContainer dict... } },
        "lexicon": { ... },               # mined modifier/color lexicon
        "lexicon_version": 3
    }

The ``schema_version`` mirrors the ``lexicon_version`` self-heal: bumping
``CACHE_SCHEMA_VERSION`` forces existing caches to re-parse the tarball so the
new keys/shapes are populated without requiring a manual Refresh.

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
        "chamberTemp":        int | None,     # back-compat: min_chamber_temperature or chamber_temperature
        "chamberTempMin":     int | None,     # NEW: min_chamber_temperature (distinct from max)
        "chamberTempMax":     int | None,     # NEW: max_chamber_temperature (distinct from min)
        "preheatTemp":        int | None,
        "dryingTemp":         int | None,
        "dryingTime":         int | None,
        "hardnessShoreD":     float | None,
        "hardnessShoreA":     float | None,   # NEW: hardness_shore_a (soft TPU materials)
        "heatbreakTemperature": int | None,   # NEW: heatbreak_temperature (not in current dataset; forward-compat → None)
        "transmissionDistance": float | None,
        "tags":               list[str],
        "photoUrl":           str | None,
        "productUrl":         str | None,
        "completenessScore":  int | None,     # not in tarball; always None
        "completenessTier":   str | None,     # not in tarball; always None
    }

OPTPackage dict shape (one material has 1→N packages; ``packages_by_material[slug]``):

    {
        "slug":                       str,
        "uuid":                       str | None,    # not all packages carry one
        "gtin":                       str | None,    # barcode; absent for many brands (e.g. ELEGOO)
        "brandSpecificId":            str | None,    # the SKU (yaml.brand_specific_id)
        "url":                        str | None,    # variant/product URL (package-level)
        "nominalNettoFullWeight":     int | None,    # net g of a full package
        "filamentDiameter":           int | None,    # µm (e.g. 1750)
        "filamentDiameterTolerance":  int | None,    # µm; rare
        "containerSlug":              str | None,    # FK into containers_by_slug
    }

OPTContainer dict shape (``containers_by_slug[slug]``):

    {
        "uuid":          str | None,
        "slug":          str,
        "name":          str | None,
        "class":         str | None,
        "brand":         str | None,    # brand slug (yaml.brand.slug)
        "emptyWeight":   int | None,    # tare g — the spool's empty weight (future weight-model win)
        "outerDiameter": int | None,    # mm
        "innerDiameter": int | None,    # mm
        "holeDiameter":  int | None,    # mm
        "width":         int | None,    # mm
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
_COMMITS_URL = (
    "https://api.github.com/repos/OpenPrintTag/openprinttag-database/commits/main"
)
_FETCH_TIMEOUT = httpx.Timeout(120.0)
# The SHA check is a cheap single-line GET — keep its timeout short so a slow/
# unreachable GitHub falls back to a normal download quickly instead of stalling.
_SHA_TIMEOUT = httpx.Timeout(15.0)

#: Version tag for the cache *shape* (top-level keys + parsed dict structure).
#: Mirrors the ``LEXICON_VERSION`` self-heal: bump this whenever the parser
#: produces a structurally different cache (new keys, new sub-dict shapes) so a
#: cache written by an older build is re-parsed from the tarball automatically
#: WITHOUT requiring a manual Refresh.
#: v1: materials-only (implicit / absent key on legacy caches)
#: v2: full schema — adds material chamberTempMin/Max, hardnessShoreA,
#:     heatbreakTemperature + packages_by_material + containers_by_slug
CACHE_SCHEMA_VERSION: int = 2

# ---------------------------------------------------------------------------
# Canonical "supported field" schema
# ---------------------------------------------------------------------------
# Single source of truth for "every OpenPrintTag-supported field the bridge
# ingests".  The completeness report checks emptiness against EXACTLY this set,
# so adding a field to the parser means adding it here (and vice versa).  Each
# entry is (cache_key, human_label).  Identity keys (uuid/slug/brand*/name) are
# intentionally excluded — they are always present and are not "gaps".

#: Material-level supported fields (keys on each OPTMaterial dict).
SUPPORTED_MATERIAL_FIELDS: list[tuple[str, str]] = [
    ("type", "Material type"),
    ("abbreviation", "Abbreviation"),
    ("color", "Primary color"),
    ("secondaryColors", "Secondary colors"),
    ("density", "Density"),
    ("nozzleTempMin", "Nozzle temp (min)"),
    ("nozzleTempMax", "Nozzle temp (max)"),
    ("bedTempMin", "Bed temp (min)"),
    ("bedTempMax", "Bed temp (max)"),
    ("chamberTempMin", "Chamber temp (min)"),
    ("chamberTempMax", "Chamber temp (max)"),
    ("preheatTemp", "Preheat temp"),
    ("dryingTemp", "Drying temp"),
    ("dryingTime", "Drying time"),
    ("hardnessShoreA", "Hardness (Shore A)"),
    ("hardnessShoreD", "Hardness (Shore D)"),
    ("heatbreakTemperature", "Heatbreak temp"),
    ("transmissionDistance", "Transmission distance"),
    ("tags", "Tags"),
    ("photoUrl", "Photo URL"),
    ("productUrl", "Product URL"),
]

#: Package-level supported fields (keys on each OPTPackage dict).
SUPPORTED_PACKAGE_FIELDS: list[tuple[str, str]] = [
    ("gtin", "GTIN / barcode"),
    ("brandSpecificId", "SKU (brand-specific ID)"),
    ("url", "Product URL (package)"),
    ("nominalNettoFullWeight", "Net full weight"),
    ("filamentDiameter", "Filament diameter"),
    ("filamentDiameterTolerance", "Filament diameter tolerance"),
    ("containerSlug", "Container"),
]

#: Container-level supported fields (keys on each OPTContainer dict).
SUPPORTED_CONTAINER_FIELDS: list[tuple[str, str]] = [
    ("name", "Container name"),
    ("class", "Container class"),
    ("brand", "Container brand"),
    ("emptyWeight", "Empty weight (tare)"),
    ("outerDiameter", "Outer diameter"),
    ("innerDiameter", "Inner diameter"),
    ("holeDiameter", "Hole diameter"),
    ("width", "Width"),
]


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
    """Back-compat shim: return just the list of OPTMaterial dicts.

    Existing callers/tests expect a plain materials list.  The full parse
    (materials + packages + containers) lives in :func:`_parse_tarball_full`.
    """
    return _parse_tarball_full(raw_bytes)["materials"]


def _parse_tarball_full(raw_bytes: bytes) -> dict[str, Any]:
    """Parse the OpenPrintTag tarball into the full supported schema.

    Returns a dict with three keys::

        {
            "materials":            [ ...OPTMaterial dicts... ],
            "packages_by_material": { material_slug: [ ...OPTPackage dicts... ] },
            "containers_by_slug":   { container_slug: { ...OPTContainer dict... } },
        }

    Multi-pass algorithm over a SINGLE download:
    1. ``data/brands/<slug>.yaml``           → ``{slug: name}`` index.
    2. ``data/materials/**/*.yaml``          → OPTMaterial list (FFF only).
    3. ``data/material-packages/**/*.yaml``  → packages keyed by ``material.slug``.
    4. ``data/material-containers/*.yaml``   → containers keyed by ``slug``.

    Only ``class: FFF`` materials are included (SLA, etc. are skipped silently).
    Secondary colors are populated in the material pass from
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

            # Chamber temperature: keep distinct min/max AND a collapsed back-compat
            # value (prefer min_chamber_temperature, fall back to the plain key).
            chamber_min = props.get("min_chamber_temperature")
            chamber_max = props.get("max_chamber_temperature")
            chamber = chamber_min or props.get("chamber_temperature")

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
                "chamberTempMin": chamber_min,
                "chamberTempMax": chamber_max,
                "preheatTemp": props.get("preheat_temperature"),
                "dryingTemp": props.get("drying_temperature"),
                "dryingTime": props.get("drying_time"),
                "hardnessShoreD": props.get("hardness_shore_d"),
                "hardnessShoreA": props.get("hardness_shore_a"),
                # heatbreak_temperature is not present in the current upstream
                # dataset; mapped for forward-compat (always None today).
                "heatbreakTemperature": props.get("heatbreak_temperature"),
                "transmissionDistance": doc.get("transmission_distance"),
                "tags": doc.get("tags") or [],
                "photoUrl": photo_url,
                "productUrl": doc.get("url"),
                "completenessScore": None,
                "completenessTier": None,
            }
            materials.append(mat)

    # Pass 3: parse material-packages (1→N per material, keyed by material.slug)
    packages_by_material: dict[str, list[dict[str, Any]]] = {}
    pkg_count = 0
    with tarfile.open(fileobj=io.BytesIO(raw_bytes), mode="r:gz") as tf:
        for member in tf.getmembers():
            path = member.name
            if "/data/material-packages/" not in path or not path.endswith(".yaml"):
                continue
            fobj = tf.extractfile(member)
            if fobj is None:
                continue
            try:
                doc = yaml.safe_load(fobj.read())
            except Exception as exc:
                logger.debug("opentag_cache: YAML parse error in package %s: %s", path, exc)
                continue
            if not isinstance(doc, dict):
                continue
            # Skip non-FFF packages (mirror the material filter).
            pkg_class = doc.get("class")
            if pkg_class and pkg_class != "FFF":
                continue
            mat_slug = (doc.get("material") or {}).get("slug")
            if not mat_slug:
                continue
            container_slug = (doc.get("container") or {}).get("slug")
            pkg: dict[str, Any] = {
                "slug": doc.get("slug"),
                "uuid": doc.get("uuid"),
                "gtin": doc.get("gtin"),
                "brandSpecificId": doc.get("brand_specific_id"),
                "url": doc.get("url"),
                "nominalNettoFullWeight": doc.get("nominal_netto_full_weight"),
                "filamentDiameter": doc.get("filament_diameter"),
                "filamentDiameterTolerance": doc.get("filament_diameter_tolerance"),
                "containerSlug": container_slug,
            }
            packages_by_material.setdefault(mat_slug, []).append(pkg)
            pkg_count += 1

    # Pass 4: parse material-containers (keyed by container slug)
    containers_by_slug: dict[str, dict[str, Any]] = {}
    with tarfile.open(fileobj=io.BytesIO(raw_bytes), mode="r:gz") as tf:
        for member in tf.getmembers():
            path = member.name
            if "/data/material-containers/" not in path or not path.endswith(".yaml"):
                continue
            fobj = tf.extractfile(member)
            if fobj is None:
                continue
            try:
                doc = yaml.safe_load(fobj.read())
            except Exception as exc:
                logger.debug(
                    "opentag_cache: YAML parse error in container %s: %s", path, exc
                )
                continue
            if not isinstance(doc, dict):
                continue
            cslug = doc.get("slug")
            if not cslug:
                continue
            brand_slug = (doc.get("brand") or {}).get("slug")
            containers_by_slug[cslug] = {
                "uuid": doc.get("uuid"),
                "slug": cslug,
                "name": doc.get("name"),
                "class": doc.get("class"),
                "brand": brand_slug,
                "emptyWeight": doc.get("empty_weight"),
                "outerDiameter": doc.get("outer_diameter"),
                "innerDiameter": doc.get("inner_diameter"),
                "holeDiameter": doc.get("hole_diameter"),
                "width": doc.get("width"),
            }

    logger.info(
        "opentag_cache: parsed %d materials, %d packages (%d materials w/ packages), "
        "%d containers from tarball (%d brands indexed)",
        len(materials), pkg_count, len(packages_by_material),
        len(containers_by_slug), len(brand_names),
    )
    return {
        "materials": materials,
        "packages_by_material": packages_by_material,
        "containers_by_slug": containers_by_slug,
    }


async def _fetch_from_tarball(
    http: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Download the OpenPrintTag tarball from GitHub and return the full parsed schema.

    Returns the :func:`_parse_tarball_full` dict
    (``{"materials", "packages_by_material", "containers_by_slug"}``).

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
        return _parse_tarball_full(raw_bytes)
    except tarfile.TarError as exc:
        raise RuntimeError(
            f"OpenPrintTag tarball is not a valid gzip archive: {exc}"
        ) from exc


async def get_upstream_commit_sha(
    http: httpx.AsyncClient | None = None,
) -> str | None:
    """Return the current upstream ``main`` HEAD commit SHA, or ``None`` on failure.

    Cheap single-request signal used to decide whether the heavy tarball needs a
    re-download.  Uses the ``application/vnd.github.sha`` media type so GitHub
    returns just the 40-char SHA as plain text (no JSON body to parse).

    Best-effort by contract: any failure — timeout, connectivity, rate-limit
    (GitHub unauth = 60 req/hr/IP → HTTP 403/429), or an unexpected body — is
    swallowed and ``None`` is returned so the caller can fall back to a download.
    NEVER raises.  Log lines are scrubbed (CWE-117).
    """
    from app.core.log_safe import scrub as _scrub

    own_client = http is None
    client: httpx.AsyncClient = http if http is not None else httpx.AsyncClient()
    try:
        resp = await client.get(
            _COMMITS_URL,
            timeout=_SHA_TIMEOUT,
            follow_redirects=True,
            headers={"Accept": "application/vnd.github.sha"},
        )
        resp.raise_for_status()
        sha = resp.text.strip()
        # A valid SHA is 40 hex chars; anything else (HTML error page, JSON) is junk.
        if len(sha) == 40 and all(c in "0123456789abcdefABCDEF" for c in sha):
            return sha
        logger.warning(
            "opentag_cache: upstream SHA check returned an unexpected body: %s",
            _scrub(sha[:80]),
        )
        return None
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "opentag_cache: upstream SHA check got HTTP %d (rate-limit/unavailable?) — "
            "falling back to download: %s",
            exc.response.status_code, _scrub(exc),
        )
        return None
    except (httpx.TimeoutException, httpx.RequestError) as exc:
        logger.warning(
            "opentag_cache: upstream SHA check failed (network) — falling back to "
            "download: %s",
            _scrub(exc),
        )
        return None
    finally:
        if own_client:
            await client.aclose()


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


def _save_cache(
    data_dir: str,
    materials: list[dict],
    fetched_at: str,
    lexicon: dict | None = None,
    lexicon_version: int = 0,
    commit_sha: str | None = None,
    packages_by_material: dict | None = None,
    containers_by_slug: dict | None = None,
) -> None:
    from app.core.opentag_lexicon import LEXICON_VERSION as _CURRENT_LEXICON_VERSION
    path = Path(data_dir) / _CACHE_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {
        "fetched_at": fetched_at,
        "count": len(materials),
        "commit_sha": commit_sha,
        "schema_version": CACHE_SCHEMA_VERSION,
        "materials": materials,
        "packages_by_material": packages_by_material or {},
        "containers_by_slug": containers_by_slug or {},
        "lexicon_version": lexicon_version or _CURRENT_LEXICON_VERSION,
    }
    if lexicon is not None:
        data["lexicon"] = lexicon
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    logger.info(
        "opentag_cache: saved %d materials, %d package-materials, %d containers to %s "
        "(schema_version=%d, lexicon_version=%d, sha=%s)",
        len(materials), len(data["packages_by_material"]),
        len(data["containers_by_slug"]), path, CACHE_SCHEMA_VERSION,
        data["lexicon_version"], (commit_sha or "")[:12],
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _mine_and_attach_lexicon(
    cache: dict[str, Any],
    data_dir: str,
    save: bool = True,
) -> dict[str, Any]:
    """Mine the lexicon from ``cache["materials"]`` and persist it in-place.

    This is called:
    1. After a fresh network fetch (always).
    2. As a self-heal when the cached ``lexicon_version`` doesn't match the current
       ``LEXICON_VERSION`` constant — recomputes WITHOUT a network re-fetch.

    Returns the updated ``cache`` dict (with ``"lexicon"`` and ``"lexicon_version"``
    keys populated).  Writes the updated cache to disk when ``save=True``.
    """
    from app.core.opentag_lexicon import LEXICON_VERSION, mine_lexicons
    materials = cache.get("materials", [])
    logger.info(
        "opentag_cache: mining lexicon from %d materials (target version %d)",
        len(materials), LEXICON_VERSION,
    )
    lexicon = mine_lexicons(materials)
    cache["lexicon"] = lexicon
    cache["lexicon_version"] = LEXICON_VERSION
    if save and data_dir:
        _save_cache(
            data_dir,
            materials,
            cache.get("fetched_at", ""),
            lexicon=lexicon,
            lexicon_version=LEXICON_VERSION,
            commit_sha=cache.get("commit_sha"),
            packages_by_material=cache.get("packages_by_material"),
            containers_by_slug=cache.get("containers_by_slug"),
        )
    return cache


async def load_opentag_dataset(
    data_dir: str,
    max_age_hours: int,
    *,
    force: bool = False,
    force_pull: bool = False,
    force_check: bool = False,
    http: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Return the cached OpenTag dataset, gating the heavy tarball download behind a
    cheap upstream commit-SHA check.

    Fetches directly from the OpenPrintTag GitHub tarball — no Filament DB dependency.

    Intents (keyword-only flags):

    * **normal** (no flags): serve the cache when fresh; when stale, run the SHA
      check — a matching SHA bumps the cache age WITHOUT a download; a differing or
      unknown SHA (or a failed check) downloads.
    * ``force_check=True``: run the SHA check even when the cache is fresh (manual
      Refresh).  Same SHA-vs-download outcome as the stale path.
    * ``force_pull=True`` (or the legacy ``force=True``): skip the SHA check and
      always download+parse (the "Pull contents anyway" path).
    * missing/invalid cache: always download.

    Returns::

        {
            "fetched_at": "<iso>",
            "count": N,
            "commit_sha": "<sha|None>",
            "schema_version": N,
            "unchanged": bool,        # True iff the SHA matched and NO download happened
            "stale": False,
            "materials": [...OPTMaterial dicts...],
            "packages_by_material": {slug: [...OPTPackage dicts...]},
            "containers_by_slug": {slug: {...OPTContainer dict...}},
            "lexicon": {"modifiers": [...], "colors": [...]},
        }

    The ``lexicon`` key contains the mined modifier/color lexicon, persisted
    alongside the materials in the cache file.  When the cached ``lexicon_version``
    doesn't match ``LEXICON_VERSION`` the lexicon is re-mined in-place WITHOUT a
    network re-fetch (version-bump self-heal).

    ``http`` is an optional ``httpx.AsyncClient`` for the tarball download and SHA
    check (useful in tests to inject a fake client).  When ``None``, a fresh client
    is created.

    The SHA check is best-effort and never raises; on failure it falls back to a
    download.  The tarball download itself still propagates:
    Raises ``httpx.TimeoutException`` on download timeout.
    Raises ``httpx.HTTPStatusError`` for non-2xx from GitHub.
    Raises ``httpx.RequestError`` for connectivity failures.
    """
    from app.core.opentag_lexicon import LEXICON_VERSION

    # Legacy alias: ``force=True`` (old call sites/tests) == "Pull contents anyway".
    force_pull = force_pull or force

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

    # Schema-version self-heal: an old-shape cache (written before
    # CACHE_SCHEMA_VERSION) lacks packages_by_material / containers_by_slug and
    # the extended material keys.  Those can only be (re)populated from the
    # tarball, so treat an outdated schema like a missing cache → force a
    # download.  Mirrors the lexicon_version self-heal pattern.
    cache_schema_outdated = (
        cache is not None
        and cache.get("schema_version", 1) != CACHE_SCHEMA_VERSION
    )

    cache_missing = cache is None or not _materials_valid(cache) or cache_schema_outdated
    cache_stale = _is_stale((cache or {}).get("fetched_at"), max_age_hours)

    async def _download_and_save(reason: str) -> dict[str, Any]:
        logger.info(
            "opentag_cache: downloading fresh dataset from OpenPrintTag GitHub "
            "tarball (%s)",
            reason,
        )
        # Capture the upstream SHA alongside the materials so the next check can
        # short-circuit.  Best-effort — never block a download on the SHA call.
        new_sha = await get_upstream_commit_sha(http)
        parsed = await _fetch_from_tarball(http)
        materials = parsed["materials"]
        fetched_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        fresh = {
            "fetched_at": fetched_at,
            "count": len(materials),
            "commit_sha": new_sha,
            "schema_version": CACHE_SCHEMA_VERSION,
            "materials": materials,
            "packages_by_material": parsed["packages_by_material"],
            "containers_by_slug": parsed["containers_by_slug"],
        }
        _mine_and_attach_lexicon(fresh, data_dir, save=True)
        return fresh

    unchanged = False

    if force_pull:
        # "Pull contents anyway" — no SHA check, always download.
        cache = await _download_and_save("force_pull")
    elif cache_missing:
        reason = (
            "cache schema outdated" if cache_schema_outdated
            else "cache missing/invalid"
        )
        cache = await _download_and_save(reason)
    elif cache_stale or force_check:
        cached_sha = cache.get("commit_sha")
        if not cached_sha:
            # No stored SHA → can't prove "unchanged"; download to learn it.
            cache = await _download_and_save("no stored commit_sha")
        else:
            upstream_sha = await get_upstream_commit_sha(http)
            if upstream_sha is None:
                # Check failed (timeout/rate-limit) → safe fallback: download.
                cache = await _download_and_save("SHA check failed")
            elif upstream_sha == cached_sha:
                # Content unchanged — bump age only, NO tarball download.
                logger.info(
                    "opentag_cache: upstream commit unchanged (%s) — bumping cache "
                    "age, skipping download",
                    cached_sha[:12],
                )
                cache["fetched_at"] = datetime.datetime.now(
                    datetime.timezone.utc
                ).isoformat()
                _save_cache(
                    data_dir,
                    cache.get("materials", []),
                    cache["fetched_at"],
                    lexicon=cache.get("lexicon"),
                    lexicon_version=cache.get("lexicon_version", 0),
                    commit_sha=cached_sha,
                    packages_by_material=cache.get("packages_by_material"),
                    containers_by_slug=cache.get("containers_by_slug"),
                )
                unchanged = True
            else:
                cache = await _download_and_save("upstream commit changed")
    # else: fresh cache, no forced check → serve as-is below.

    # Check whether the cached lexicon needs to be re-mined (version bump / missing).
    # Skip when we just downloaded (mining already happened in _download_and_save).
    cached_version = (cache or {}).get("lexicon_version", 0)
    cached_lexicon = (cache or {}).get("lexicon")
    if cached_version != LEXICON_VERSION or not cached_lexicon:
        logger.info(
            "opentag_cache: lexicon version mismatch (cached=%d, want=%d) — "
            "re-mining in-place without network fetch",
            cached_version, LEXICON_VERSION,
        )
        _mine_and_attach_lexicon(cache, data_dir, save=True)

    return {
        "fetched_at": cache["fetched_at"],
        "count": cache.get("count", len(cache.get("materials", []))),
        "commit_sha": cache.get("commit_sha"),
        "schema_version": cache.get("schema_version", CACHE_SCHEMA_VERSION),
        "unchanged": unchanged,
        "stale": _is_stale(cache.get("fetched_at"), max_age_hours),
        "materials": cache.get("materials", []),
        "packages_by_material": cache.get("packages_by_material", {}),
        "containers_by_slug": cache.get("containers_by_slug", {}),
        "lexicon": cache.get("lexicon"),
    }


def get_cache_metadata(data_dir: str, max_age_hours: int) -> dict[str, Any]:
    """Return metadata about the local cache without triggering a network fetch."""
    cache = _load_cache(data_dir)
    if cache is None:
        return {
            "fetched_at": None,
            "count": 0,
            "stale": True,
            "commit_sha": None,
            "schema_version": None,
            "package_material_count": 0,
            "container_count": 0,
        }
    return {
        "fetched_at": cache.get("fetched_at"),
        "count": cache.get("count", len(cache.get("materials", []))),
        "stale": _is_stale(cache.get("fetched_at"), max_age_hours),
        "commit_sha": cache.get("commit_sha"),
        "schema_version": cache.get("schema_version", 1),
        "package_material_count": len(cache.get("packages_by_material", {})),
        "container_count": len(cache.get("containers_by_slug", {})),
    }
