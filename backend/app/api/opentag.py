"""OpenTag cleanup tool — GET /api/openprinttag/matches, POST /api/openprinttag/refresh,
POST /api/openprinttag/apply.

Standalone tool: match Spoolman filaments against the OpenPrintTag dataset
(fetched directly from the OpenPrintTag GitHub tarball, cached locally), review
per-field, confirm, and apply writes to Spoolman + push slug/uuid into FDB
settings bag.

Route prefix note: the path token "opentag" (without "print") collides with the
Qubit OpenTag web-analytics product on EasyList/uBlock filter lists and is
blocked by ad blockers.  The routes use "openprinttag" instead, which is safe.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.errors import api_error
from app.config import settings as _settings
from app.core.change_log import record_change as _record_change
from app.core.log_safe import scrub as _scrub
from app.core.matcher import normalize_vendor
from app.core.opentag_cache import _load_cache, get_cache_metadata, load_opentag_dataset
from app.core.opentag_match_cache import (
    build_fingerprint,
    inputs_stale,
    load_match_cache,
    save_match_cache,
)
from app.core.opentag_match import (
    build_ngram_index,
    color_profile_compatible_soft,
    decompose_name,
    families_gate_compatible,
    find_best_match,
    material_family,
    opt_color_profile,
    opt_to_spoolman_fields,
    resolve_opentag_brand,
    score_candidate,
    sm_color_profile,
)
from app.schemas.spoolman import SpoolmanFilament as _SpoolmanFilament, SpoolmanVendor as _SpoolmanVendor
from app.db import SessionLocal
from app.schemas.spoolman import decode_extra_value, encode_extra_value

logger = logging.getLogger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# Response / request models
# ---------------------------------------------------------------------------


class OpenTagDatasetMeta(BaseModel):
    fetched_at: str | None
    count: int
    stale: bool
    # Upstream OpenPrintTag main HEAD commit SHA captured at fetch time (None if
    # unknown — e.g. a pre-SHA cache or a failed SHA check on the last download).
    commit_sha: str | None = None
    # True when a refresh found the upstream commit unchanged and only bumped the
    # cache age (no tarball download). Always False on a normal compute.
    unchanged: bool = False


class OpenTagCacheStatus(BaseModel):
    """Lightweight cache metadata — returned without fetching from FDB."""
    exists: bool
    fetched_at: str | None
    count: int
    stale: bool
    max_age_hours: int
    # Upstream commit SHA of the cached dataset (None if unknown / pre-SHA cache).
    commit_sha: str | None = None
    # Largest record count seen on any prior successful grab, persisted in
    # BridgeConfig so the "first load downloads ~N records" hint stays accurate
    # (and survives cache-file deletion) as the upstream dataset grows.
    last_count: int = 0


class OpenTagFieldRow(BaseModel):
    """Per-field comparison row for the review step."""
    field: str
    spoolman_value: Any
    opentag_value: Any
    # suggested value = opentag_value by default (caller may override)
    suggested_value: Any


class OpenTagCandidate(BaseModel):
    """One candidate match for a Spoolman filament — best or alternate."""
    opt_uuid: str | None
    opt_slug: str | None
    opt_brand: str | None
    opt_name: str | None
    opt_color_hex: str | None
    confidence: float
    multicolor_mismatch: bool = False
    fields: list[OpenTagFieldRow]


class OpenTagFilamentMatch(BaseModel):
    """Comparison entry for one Spoolman filament."""
    spoolman_filament_id: int
    spoolman_name: str
    spoolman_vendor: str | None
    spoolman_material: str | None
    spoolman_color_hex: str | None
    opt_uuid: str | None
    opt_slug: str | None
    opt_brand: str | None
    opt_name: str | None
    confidence: float
    fields: list[OpenTagFieldRow]
    alternates: list[dict[str, Any]]  # top alternate OPTMaterial dicts (kept for compat)
    # Structured candidates list: candidates[0] is the best match, followed by up to 5
    # alternates.  Each carries its own per-field comparison and identity (slug/uuid).
    candidates: list[OpenTagCandidate] = []
    ignored: bool = False
    # True when SM filament is multicolor but the matched OPT entry is NOT
    # (no secondaryColors AND no arrangement tag).  Also set on no-match rows
    # when the SM filament is multicolor but no compatible OPT entry was found.
    multicolor_mismatch: bool = False
    # Human-readable reason why a no-match row has no match.  None on matched rows.
    no_match_reason: str | None = None
    # True when the filament already has an openprinttag_uuid and at least one
    # non-identity field differs (data drift).  Excludes filaments that the user
    # has suppressed via the openprinttag_ignore extra field.
    has_update: bool = False
    # True when the user has set openprinttag_ignore="1" to suppress future update
    # flagging for this filament.
    ignored_updates: bool = False


class OpenTagMatchesResponse(BaseModel):
    dataset: OpenTagDatasetMeta
    matches: list[OpenTagFilamentMatch]
    # Count of already-tagged filaments with data drift (excluding ignored ones)
    updates_count: int = 0
    # ISO timestamp the match was computed. None for a freshly-computed response
    # that has not yet been read back from cache; set on cached/served results.
    computed_at: str | None = None
    # True when the live inputs (dataset identity / SM filament count / config)
    # differ from the cached result's inputs — the UI should prompt for a Refresh.
    # Always False on a freshly-recomputed result.
    stale_inputs: bool = False


# Completeness report ---------------------------------------------------------


class OpenTagMissingAttribute(BaseModel):
    """One OpenPrintTag attribute that is empty on the matched record."""
    key: str            # raw OPTMaterial key, e.g. "nozzleTempMin"
    label: str          # human label, e.g. "Nozzle temp (min)"
    opt_value: Any      # the (empty) OPT value — always None/""/[] for a missing attr
    your_value: Any     # best-effort hint from the SM filament, or None


class OpenTagCompletenessItem(BaseModel):
    """Completeness assessment for one tagged Spoolman filament."""
    spoolman_filament_id: int
    brand: str | None
    name: str | None
    opt_slug: str | None
    opt_uuid: str | None
    opt_url: str | None
    missing_count: int
    attributes: list[OpenTagMissingAttribute]
    # True when the SM filament carries an openprinttag_uuid that is NOT present in the
    # current dataset (stale tag) — surfaced distinctly rather than silently dropped.
    stale_match: bool = False


class OpenTagCompletenessResponse(BaseModel):
    dataset: OpenTagDatasetMeta
    items: list[OpenTagCompletenessItem]
    # Count of tagged filaments whose uuid is not in the dataset (stale tags).
    stale_count: int = 0


# Apply request ---------------------------------------------------------------


class OpenTagFieldDecision(BaseModel):
    """User's final choice for one field of one filament."""
    field: str               # e.g. "material", "color_hex", "extra.openprinttag_slug"
    value: Any               # the value to write (may be edited vs OpenTag default)
    keep_mine: bool = False  # True → skip this field entirely


class OpenTagFilamentDecision(BaseModel):
    spoolman_filament_id: int
    ignored: bool = False
    fields: list[OpenTagFieldDecision] = []
    # FDB filament id for settings-bag merge (None if no mapping yet)
    fdb_filament_id: str | None = None
    # Slug/uuid always carried separately for FDB settings-bag write
    openprinttag_slug: str | None = None
    openprinttag_uuid: str | None = None
    # When True, this decision is an UNMATCH: clear the OpenTag identity instead of
    # writing one.  Blanks the SM openprinttag_slug/uuid extras and removes those two
    # keys from the linked FDB settings{} bag.  Takes precedence over field writes.
    clear_identity: bool = False


class OpenTagApplyRequest(BaseModel):
    decisions: list[OpenTagFilamentDecision]


class OpenTagApplyFilamentResult(BaseModel):
    spoolman_filament_id: int
    status: str  # "ok" | "ignored" | "error" | "cleared"
    error: str | None = None
    fields_written: list[str] = []
    fdb_settings_updated: bool = False
    # True when this decision cleared the OpenTag identity (unmatch).
    identity_cleared: bool = False


class OpenTagApplyResponse(BaseModel):
    applied: int
    ignored: int
    errors: int
    results: list[OpenTagApplyFilamentResult]


class OpenTagIgnoreResponse(BaseModel):
    spoolman_filament_id: int
    ignored_updates: bool


class OpenTagSearchResponse(BaseModel):
    """Response from the manual search endpoint."""
    results: list[OpenTagCandidate]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_vendor_aliases(aliases_csv: str) -> dict[str, str]:
    """Parse a ``spoolman_vendor=opentag_brand`` CSV string into a normalized dict.

    Both sides are passed through ``normalize_vendor`` so casing/whitespace are
    handled consistently.  Blank entries and entries without ``=`` are ignored.
    """
    result: dict[str, str] = {}
    for pair in aliases_csv.split(","):
        pair = pair.strip()
        if "=" not in pair:
            continue
        sm_raw, opentag_raw = pair.split("=", 1)
        sm_key = normalize_vendor(sm_raw.strip())
        opentag_val = normalize_vendor(opentag_raw.strip())
        if sm_key and opentag_val:
            result[sm_key] = opentag_val
    return result


def _current_spoolman_value(sm_filament: Any, field: str) -> Any:
    """Extract the current value of a Spoolman field (including extra.* fields).

    The special ``vendor`` field returns the filament's current vendor name
    (``sm_filament.vendor.name``) rather than a direct attribute lookup, because
    ``vendor`` on a SpoolmanFilament is a nested object, not a scalar.
    """
    if field.startswith("extra."):
        key = field[len("extra."):]
        raw = sm_filament.extra.get(key)
        return decode_extra_value(raw)
    if field == "vendor":
        return sm_filament.vendor.name if sm_filament.vendor else None
    return getattr(sm_filament, field, None)


def _build_field_rows(
    sm_filament: Any,
    opt_fields: dict[str, Any],
) -> list[OpenTagFieldRow]:
    """Build per-field comparison rows, SM current vs OPT suggested.

    Each row's spoolman_value is the filament's CURRENT live value (native attr
    for native fields, decoded extra[key] for extra.* fields), so the "old" column
    in the review UI reflects reality.

    openprinttag_slug and openprinttag_uuid are included as rows (their spoolman_value
    shows any existing identity), NOT excluded. The frontend must NOT push them
    separately — they flow through the generic field-rows path. _build_sm_patch
    deduplicates them if decision.openprinttag_slug/uuid also sets them.

    The ``vendor`` field is ONLY included when the Spoolman vendor name and the
    OpenTag brand name differ after a plain ``.strip()`` comparison (case-sensitive).
    A case-only difference like "Elegoo" vs "ELEGOO" DOES surface the row so the
    apply path can re-point this filament to a vendor with OpenTag's exact canonical
    name.  Exact-equal strings (same brand, same casing) suppress the row.
    """
    rows = []
    for field, opt_value in opt_fields.items():
        sm_value = _current_spoolman_value(sm_filament, field)
        if field == "vendor":
            # Omit the vendor row only when the raw strings are identical after
            # stripping surrounding whitespace (case-sensitive equality).  A
            # case-only difference deliberately surfaces the row so _ensure_vendor
            # can find-or-create a vendor with OpenTag's exact canonical spelling
            # and re-point this filament.  Accepted trade-off: a case-only diff
            # may create a near-duplicate vendor in Spoolman (e.g. "ELEGOO"
            # alongside "Elegoo"); only this filament is re-pointed, others
            # are never touched.
            if (sm_value or "").strip() == (opt_value or "").strip():
                continue
        rows.append(OpenTagFieldRow(
            field=field,
            spoolman_value=sm_value,
            opentag_value=opt_value,
            suggested_value=opt_value,
        ))
    return rows


_IDENTITY_FIELDS = frozenset(["extra.openprinttag_slug", "extra.openprinttag_uuid"])


def _normalize_field_value(v: Any) -> str:
    """Normalize a field value for comparison (mirrors frontend normalizeFieldValue)."""
    if v is None:
        return ""
    s = str(v).strip().lower()
    if s in ("", "—"):
        return ""
    return s


def _data_differs(candidate: OpenTagCandidate) -> bool:
    """Return True when any non-identity field in this candidate has a different
    normalized value between Spoolman and OpenTag."""
    return any(
        _normalize_field_value(row.spoolman_value) != _normalize_field_value(row.opentag_value)
        for row in candidate.fields
        if row.field not in _IDENTITY_FIELDS
    )


def _build_candidate(
    sm_fil: Any,
    material: dict[str, Any],
    confidence: float,
    tag_map: dict[str, Any],
) -> OpenTagCandidate:
    """Build an OpenTagCandidate from a material dict for a given SM filament.

    Computes the per-field comparison (SM current vs this candidate's OPT values),
    the multicolor_mismatch flag, and assembles the identity fields.
    """
    opt_fields = opt_to_spoolman_fields(material, tag_map)
    field_rows = _build_field_rows(sm_fil, opt_fields)
    opt_profile = opt_color_profile(material, tag_map)
    sm_profile = sm_color_profile(sm_fil)
    mismatch = sm_profile != "single" and opt_profile == "single"
    return OpenTagCandidate(
        opt_uuid=material.get("uuid"),
        opt_slug=material.get("slug"),
        opt_brand=material.get("brandName"),
        opt_name=material.get("name"),
        opt_color_hex=material.get("color"),
        confidence=confidence,
        multicolor_mismatch=mismatch,
        fields=field_rows,
    )


def _build_sm_patch(
    decision: OpenTagFilamentDecision,
) -> tuple[dict[str, Any], dict[str, str], str | None]:
    """Build the Spoolman PATCH payload, FDB settings keys, and optional vendor name.

    Returns (patch_payload, fdb_settings_keys, vendor_name):
    - patch_payload: dict ready to PATCH SM filament (native fields + extra).
      The ``vendor`` field is NEVER put here — it is a relation (vendor_id) that
      requires a find-or-create resolution step in the caller.
    - fdb_settings_keys: {"openprinttag_slug": ..., "openprinttag_uuid": ...}
      — only keys that are non-None
    - vendor_name: the chosen vendor NAME string when the vendor field decision is
      non-keep_mine and non-null; None otherwise.  The caller must resolve this to a
      vendor_id via find-or-create and include vendor_id in the filament PATCH.
    """
    native: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    fdb_keys: dict[str, str] = {}
    vendor_name: str | None = None

    for fd in decision.fields:
        if fd.keep_mine:
            continue
        if fd.value is None:
            continue
        if fd.field == "vendor":
            # vendor is a relation — extract the name; caller resolves to vendor_id
            vendor_name = str(fd.value)
            continue
        if fd.field.startswith("extra."):
            key = fd.field[len("extra."):]
            extra[key] = encode_extra_value(fd.value)
        else:
            native[fd.field] = fd.value

    if extra:
        native["extra"] = extra

    # Slug/uuid always written to SM extra AND to FDB settings bag
    slug_field = _settings.spoolman_field_openprinttag_slug
    uuid_field = _settings.spoolman_field_openprinttag_uuid

    if decision.openprinttag_slug:
        # Ensure it's in the SM patch too (may already be there from fields)
        if "extra" not in native:
            native["extra"] = {}
        if slug_field not in native["extra"]:
            native["extra"][slug_field] = encode_extra_value(decision.openprinttag_slug)
        fdb_keys["openprinttag_slug"] = decision.openprinttag_slug

    if decision.openprinttag_uuid:
        if "extra" not in native:
            native["extra"] = {}
        if uuid_field not in native["extra"]:
            native["extra"][uuid_field] = encode_extra_value(decision.openprinttag_uuid)
        fdb_keys["openprinttag_uuid"] = decision.openprinttag_uuid

    return native, fdb_keys, vendor_name


async def _clear_opentag_identity(
    sm: Any,
    fdb: Any,
    spoolman_filament_id: int,
    fdb_filament_id: str | None,
) -> bool:
    """Clear the OpenTag identity for one Spoolman filament (unmatch).

    Blanks the ``openprinttag_slug`` + ``openprinttag_uuid`` extras on the Spoolman
    filament (reusing the same blanking convention as the debug bulk-clear) and, when a
    linked FDB filament id is known, removes ONLY those two keys from the FDB filament's
    ``settings{}`` bag via ``remove_filament_settings_keys`` (the approved scoped
    exception).  Deliberately does NOT touch ``openprinttag_ignore`` — that is a
    separate suppression concern.

    Returns True when the FDB settings bag was modified, False otherwise.  Raises on
    Spoolman write failure (caller maps to an error result / 502); the FDB removal is
    best-effort and never aborts the Spoolman blank.
    """
    slug_field = _settings.spoolman_field_openprinttag_slug
    uuid_field = _settings.spoolman_field_openprinttag_uuid
    blank = encode_extra_value("")
    await sm.update_filament(
        spoolman_filament_id,
        {"extra": {slug_field: blank, uuid_field: blank}},
    )
    logger.info(
        "opentag clear: blanked %s/%s on SM filament %d",
        _scrub(slug_field), _scrub(uuid_field), spoolman_filament_id,
    )

    fdb_cleared = False
    if fdb_filament_id:
        try:
            fdb_cleared = await fdb.remove_filament_settings_keys(
                fdb_filament_id, ["openprinttag_slug", "openprinttag_uuid"]
            )
            logger.info(
                "opentag clear: removed OpenTag identity keys from FDB filament %s (changed=%s)",
                _scrub(fdb_filament_id), fdb_cleared,
            )
        except Exception as exc:
            logger.warning(
                "opentag clear: could not remove identity keys from FDB filament %s: %s",
                _scrub(fdb_filament_id), _scrub(exc),
            )
    return fdb_cleared


async def _resolve_fdb_filament_id(sm: Any, spoolman_filament_id: int) -> str | None:
    """Look up the FDB filament id from a Spoolman filament's ``filamentdb_id`` cross-ref
    extra.  Best-effort — returns None when the filament is not found or has no cross-ref."""
    id_field = _settings.spoolman_field_filamentdb_id
    try:
        fil = await sm.get_filament(spoolman_filament_id)
    except Exception as exc:
        logger.warning(
            "opentag clear: could not fetch SM filament %d to resolve FDB id: %s",
            spoolman_filament_id, _scrub(exc),
        )
        return None
    raw = (fil.extra or {}).get(id_field)
    return decode_extra_value(raw) or None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


_LAST_COUNT_KEY = "opentag_last_count"


def _record_last_count(count: int) -> None:
    """Persist the most recent dataset record count to BridgeConfig.

    Lets the UI show an accurate "first load downloads ~N records" hint that
    tracks the growing upstream dataset and survives cache-file deletion.
    Best-effort: never let a persistence hiccup fail the fetch.
    """
    if count <= 0:
        return
    from app.api.config import set_config_value
    try:
        with SessionLocal() as _db:
            set_config_value(_db, _LAST_COUNT_KEY, int(count))
            _db.commit()
    except Exception:  # pragma: no cover - best-effort persistence
        logger.warning("opentag: failed to persist last record count", exc_info=True)


def _read_last_count() -> int:
    """Read the persisted last record count from BridgeConfig (0 if never set)."""
    from app.api.config import get_config_value
    try:
        with SessionLocal() as _db:
            return int(get_config_value(_db, _LAST_COUNT_KEY, 0) or 0)
    except Exception:  # pragma: no cover - tests without a real DB
        return 0


@router.get("/openprinttag/status", response_model=OpenTagCacheStatus)
async def opentag_status() -> OpenTagCacheStatus:
    """Return local cache metadata WITHOUT fetching from FDB.

    Fast and side-effect free — the page can call this on mount to show the
    dataset state (count, age, stale) instantly, before any slow fetch begins.
    """
    meta = get_cache_metadata(_settings.data_dir, _settings.opentag_cache_max_age_hours)
    return OpenTagCacheStatus(
        exists=meta["fetched_at"] is not None,
        fetched_at=meta["fetched_at"],
        count=meta["count"],
        stale=meta["stale"],
        max_age_hours=_settings.opentag_cache_max_age_hours,
        last_count=max(meta["count"], _read_last_count()),
        commit_sha=meta.get("commit_sha"),
    )


@router.post("/openprinttag/refresh", response_model=OpenTagDatasetMeta)
async def opentag_refresh(request: Request, pull: bool = False) -> OpenTagDatasetMeta:
    """Refresh the OpenTag dataset, gated by a cheap upstream commit-SHA check.

    Default (``pull=false``): run the SHA check. If the upstream commit is
    unchanged, only the cache age is bumped (no heavy tarball download) and the
    response carries ``unchanged=True``; if it changed (or the SHA can't be read)
    the tarball is re-downloaded.

    ``pull=true`` ("Pull contents anyway"): skip the SHA check and force a full
    download+parse regardless of the upstream commit.
    """
    try:
        result = await load_opentag_dataset(
            _settings.data_dir,
            _settings.opentag_cache_max_age_hours,
            force_pull=pull,
            force_check=not pull,
        )
    except httpx.TimeoutException as exc:
        logger.error("opentag refresh: timed out downloading dataset from OpenPrintTag: %s", exc)
        raise api_error(
            504,
            "opentag_fetch_timeout",
            "Timed out downloading the OpenTag dataset from OpenPrintTag — "
            "it downloads a large tarball; try again.",
        ) from exc
    except httpx.HTTPStatusError as exc:
        logger.error(
            "opentag refresh: OpenPrintTag/GitHub returned HTTP %d: %s",
            exc.response.status_code, exc,
        )
        raise api_error(
            502,
            "opentag_fetch_failed",
            f"Failed to download the OpenTag dataset from OpenPrintTag "
            f"(HTTP {exc.response.status_code} — GitHub may be rate-limiting or unavailable).",
        ) from exc
    except httpx.RequestError as exc:
        logger.error("opentag refresh: connection error downloading dataset from OpenPrintTag: %s", exc)
        raise api_error(
            502,
            "opentag_fetch_failed",
            "Could not reach api.github.com to download the OpenTag dataset — "
            "check that the bridge container has outbound HTTPS access.",
        ) from exc
    _record_last_count(result["count"])
    return OpenTagDatasetMeta(
        fetched_at=result["fetched_at"],
        count=result["count"],
        stale=result["stale"],
        commit_sha=result.get("commit_sha"),
        unchanged=result.get("unchanged", False),
    )


def _resolve_match_config() -> tuple[str, dict[str, int], dict[str, str], dict[str, str]]:
    """Resolve the match-affecting config off the event loop's data sources.

    Returns ``(aliases_raw, tag_map, vendor_aliases, field_names)``.  The
    BridgeConfig read is wrapped so tests without a real DB fall back to the env
    default.  ``field_names`` carries the openprinttag extra-field names used for
    the cache fingerprint.
    """
    from app.api.config import get_config_value
    tag_map = _settings.parsed_material_tag_ids
    try:
        with SessionLocal() as _db:
            aliases_raw: str = get_config_value(
                _db, "opentag_vendor_aliases", _settings.opentag_vendor_aliases
            ) or ""
    except Exception:
        aliases_raw = _settings.opentag_vendor_aliases
    vendor_aliases = _parse_vendor_aliases(aliases_raw)
    field_names = {
        "uuid": _settings.spoolman_field_openprinttag_uuid,
        "ignore": _settings.spoolman_field_openprinttag_ignore,
        "slug": _settings.spoolman_field_openprinttag_slug,
    }
    return aliases_raw, tag_map, vendor_aliases, field_names


def _compute_matches(
    sm_filaments: list[Any],
    materials: list[dict[str, Any]],
    dataset_lexicon: dict[str, list[str]] | None,
    tag_map: dict[str, int],
    vendor_aliases: dict[str, str],
    uuid_field: str,
    ignore_field: str,
) -> list[OpenTagFilamentMatch]:
    """Pure-CPU OpenTag match computation — safe to run in a worker thread.

    Takes already-fetched plain data (SM filaments, OPT materials, resolved config)
    and returns the per-filament match list.  Performs NO I/O — no httpx, no
    SQLAlchemy session, no ``request`` access — so it can be offloaded off the
    FastAPI event loop via ``run_in_threadpool`` without blocking other requests.
    """
    from app.core.opentag_match import DEFAULT_COLOR_KEYWORDS
    color_map: dict[str, str] = dict(DEFAULT_COLOR_KEYWORDS)

    # Build ngram_index and effective_synonyms ONCE — used by both the color-profile
    # gate (color_profile_compatible_soft → opt_color_arity → decompose_name) and
    # find_best_match → score_candidate → decompose_name.  Building them once ensures
    # consistency and avoids O(candidates) rebuilds inside the gate.
    ngram_index = build_ngram_index(dataset_lexicon)
    effective_synonyms: dict[str, str] = dict(color_map)

    # Build a brand index once — keyed by normalize_vendor(brandName) — so each SM
    # filament only scores its own brand's candidates instead of all ~11k materials.
    # normalize_vendor now treats hyphens as spaces, so "VOXEL-pla" and "Voxel PLA"
    # both produce "voxel pla" and map to the same bucket.
    materials_by_brand: dict[str, list[dict[str, Any]]] = {}
    # Also build a UUID index for exact-match bypass (filament already tagged by a prior run).
    by_uuid: dict[str, dict[str, Any]] = {}
    for m in materials:
        if not isinstance(m, dict):
            continue
        brand_key = normalize_vendor(m.get("brandName"))
        materials_by_brand.setdefault(brand_key, []).append(m)
        if m.get("uuid"):
            by_uuid[m["uuid"]] = m

    n_filaments = len(sm_filaments)
    n_materials = len(materials)
    n_brands = len(materials_by_brand)
    logger.info(
        "opentag matches: scoring %d filaments against %d materials across %d brands",
        n_filaments, n_materials, n_brands,
    )

    def _gated_candidates_for(sm_fil: Any) -> tuple[str, list[dict[str, Any]]]:
        """Run the brand pre-filter + color-profile + polymer-family gates for one SM
        filament and return ``(sm_brand_key, gated_candidate_dicts)``.

        Shared by the untagged branch (full fuzzy scoring) and the tagged branch
        (computing alternates beside the pinned exact-UUID match) so the gate logic
        is defined exactly once.
        """
        # Resolve the SM vendor name through the alias map before looking up brand candidates.
        # This allows e.g. "Prusa" to find "Prusament" entries when aliases contain that pair.
        brand_key = resolve_opentag_brand(
            sm_fil.vendor.name if sm_fil.vendor else None, vendor_aliases
        )
        candidates = materials_by_brand.get(brand_key, [])

        # Color-profile gate (v2.1 — name-aware + soft):
        # When the OPT entry has complete arrangement + hex data, apply the strict
        # profiles_compatible check.  When data is incomplete/absent, use effective
        # color arity (max of hex count and name-decomposed color count) so that OPT
        # entries with descriptive multi-color names but missing hex data (e.g.
        # "Temperature Color Change Purple to Red") are not incorrectly dropped.
        profile = sm_color_profile(sm_fil)
        # Compute SM arity: max of name-decomposed color count and hex field count.
        parsed_gate = decompose_name(
            sm_fil.name, sm_fil.vendor.name if sm_fil.vendor else None, sm_fil.material,
            tag_map=tag_map, ngram_index=ngram_index, color_synonyms=effective_synonyms,
        )
        arity_gate = sum(parsed_gate.colors.values())
        if sm_fil.multi_color_hexes:
            hex_arity = 1 + len([h for h in sm_fil.multi_color_hexes.split(",") if h.strip()])
            arity_gate = max(arity_gate, hex_arity)
        candidates = [
            c for c in candidates
            if isinstance(c, dict) and color_profile_compatible_soft(
                profile, arity_gate, c, tag_map, ngram_index, effective_synonyms
            )
        ]

        # Polymer-family gate (v2.1 — widened by PLA-biopolymer bucket):
        # PLA/PHA/LW-PLA/HTPLA/rPLA are mutually gate-compatible (ColorFabb composites
        # are inconsistently typed in OPT as PHA even when sold as "PLA" blends).
        # All other cross-family pairs (ASA≠PETG, PC≠PETG, etc.) remain strictly gated.
        # Only gate when the SM filament has a non-empty / known material
        # (unknown SM material → don't gate, score all candidates).
        fam = material_family(sm_fil.material, tag_map)
        if fam:
            candidates = [
                c for c in candidates
                if families_gate_compatible(
                    fam,
                    material_family(c.get("type") or c.get("abbreviation") or "", tag_map),
                )
            ]
        return brand_key, candidates

    matched = 0
    no_match = 0
    matches: list[OpenTagFilamentMatch] = []
    for sm_fil in sm_filaments:
        # Read per-filament flags from Spoolman extra fields.
        existing_uuid = decode_extra_value(sm_fil.extra.get(uuid_field))
        ignored_updates = bool(decode_extra_value(sm_fil.extra.get(ignore_field)))

        # Exact-UUID match: if the SM filament already carries an openprinttag_uuid that
        # maps to a known material, pin that material at confidence 1.0 (no fuzzy scoring
        # for the BEST slot).  But still run the gate pipeline + find_best_match to surface
        # alternates the user can re-point to via the dropdown (e.g. to fix a wrong tag).
        if existing_uuid and existing_uuid in by_uuid:
            best = by_uuid[existing_uuid]
            confidence = 1.0
            matched += 1
            best_candidate = _build_candidate(sm_fil, best, confidence, tag_map)

            # Compute alternates (un-bypass): gate this filament's brand candidates and
            # score them, excluding the already-pinned exact match.
            _, gated = _gated_candidates_for(sm_fil)
            alt_result = find_best_match(
                sm_fil, gated, tag_map, vendor_aliases,
                color_map=color_map, lexicon=dataset_lexicon, top_n=10,
            )
            tagged_candidates: list[OpenTagCandidate] = [best_candidate]
            if alt_result["best"] is not None:
                alt_pairs = [(alt_result["best"], alt_result["confidence"])]
                alt_pairs += list(zip(alt_result["alternates"], alt_result["alternate_scores"]))
                for alt_mat, alt_score in alt_pairs:
                    if alt_mat.get("uuid") == existing_uuid:
                        continue  # already pinned as best
                    tagged_candidates.append(_build_candidate(sm_fil, alt_mat, alt_score, tag_map))

            differs = _data_differs(best_candidate)
            has_update = differs and not ignored_updates
            matches.append(OpenTagFilamentMatch(
                spoolman_filament_id=sm_fil.id,
                spoolman_name=sm_fil.name,
                spoolman_vendor=sm_fil.vendor.name if sm_fil.vendor else None,
                spoolman_material=sm_fil.material,
                spoolman_color_hex=sm_fil.color_hex,
                opt_uuid=best.get("uuid"),
                opt_slug=best.get("slug"),
                opt_brand=best.get("brandName"),
                opt_name=best.get("name"),
                confidence=confidence,
                fields=best_candidate.fields,
                alternates=[],
                candidates=tagged_candidates,
                multicolor_mismatch=best_candidate.multicolor_mismatch,
                has_update=has_update,
                ignored_updates=ignored_updates,
            ))
            continue

        sm_brand_key, filtered_candidates = _gated_candidates_for(sm_fil)
        sm_profile = sm_color_profile(sm_fil)

        match_result = find_best_match(sm_fil, filtered_candidates, tag_map, vendor_aliases, color_map=color_map, lexicon=dataset_lexicon)
        best = match_result["best"]
        confidence = match_result["confidence"]
        alternates = match_result["alternates"]
        alternate_scores = match_result["alternate_scores"]

        if best is None:
            # Include low-confidence / no-match filaments with empty field rows.
            # Flag multicolor_mismatch when SM is multicolor but no match was found
            # (the color-profile pre-filter means incompatible OPT entries were excluded,
            # but the SM side was multicolor — signal that to the user).
            no_match += 1
            mismatch = sm_profile != "single"
            sm_vendor = sm_fil.vendor.name if sm_fil.vendor else None
            sm_material = sm_fil.material

            # Compute a human-readable explanation for the no-match condition.
            if sm_brand_key not in materials_by_brand:
                no_match_reason: str | None = (
                    f'Manufacturer "{sm_vendor}" not found in OpenTag '
                    f'(add a mapping in Settings)'
                )
            elif not filtered_candidates:
                no_match_reason = (
                    f'No {sm_material or "matching"} match for {sm_vendor} in OpenTag'
                )
            elif mismatch:
                no_match_reason = "Spoolman is multicolor; no multicolor OpenTag match"
            else:
                best_conf = confidence  # confidence == best_score seen (below threshold)
                no_match_reason = f"No confident match (best {round(best_conf * 100)}%)"

            matches.append(OpenTagFilamentMatch(
                spoolman_filament_id=sm_fil.id,
                spoolman_name=sm_fil.name,
                spoolman_vendor=sm_vendor,
                spoolman_material=sm_material,
                spoolman_color_hex=sm_fil.color_hex,
                opt_uuid=None,
                opt_slug=None,
                opt_brand=None,
                opt_name=None,
                confidence=confidence,
                fields=[],
                alternates=alternates,
                candidates=[],
                multicolor_mismatch=mismatch,
                no_match_reason=no_match_reason,
                ignored_updates=ignored_updates,
            ))
            continue

        matched += 1

        # multicolor_mismatch: SM is multicolor but the matched OPT entry is NOT
        # (no secondaryColors AND no arrangement tag).
        best_candidate = _build_candidate(sm_fil, best, confidence, tag_map)

        # Build structured candidates list: best first, then up to 5 alternates.
        structured_candidates: list[OpenTagCandidate] = [best_candidate]
        for alt_mat, alt_score in zip(alternates, alternate_scores):
            structured_candidates.append(_build_candidate(sm_fil, alt_mat, alt_score, tag_map))

        # has_update: already tagged (has existing_uuid) and data has drifted,
        # but the user has not suppressed this filament via openprinttag_ignore.
        differs = _data_differs(best_candidate)
        has_update = bool(existing_uuid) and differs and not ignored_updates

        matches.append(OpenTagFilamentMatch(
            spoolman_filament_id=sm_fil.id,
            spoolman_name=sm_fil.name,
            spoolman_vendor=sm_fil.vendor.name if sm_fil.vendor else None,
            spoolman_material=sm_fil.material,
            spoolman_color_hex=sm_fil.color_hex,
            opt_uuid=best.get("uuid"),
            opt_slug=best.get("slug"),
            opt_brand=best.get("brandName"),
            opt_name=best.get("name"),
            confidence=confidence,
            fields=best_candidate.fields,
            alternates=alternates,
            candidates=structured_candidates,
            multicolor_mismatch=best_candidate.multicolor_mismatch,
            has_update=has_update,
            ignored_updates=ignored_updates,
        ))

    logger.info("opentag matches: %d matched, %d no-match", matched, no_match)
    return matches


@router.get("/openprinttag/matches", response_model=OpenTagMatchesResponse)
async def opentag_matches(request: Request, recompute: bool = False) -> OpenTagMatchesResponse:
    """Return per-Spoolman-filament OpenTag matches with per-field comparison.

    Serves the last cached match result instantly when present (no compute), with
    ``computed_at`` and a ``stale_inputs`` flag set when the live dataset / Spoolman
    filament count / config differ from the cached inputs.  Pass ``recompute=true``
    to force a fresh (offloaded) match and re-cache.

    The heavy scoring runs in a worker thread (``run_in_threadpool``) so a match in
    flight never blocks other API requests on the event loop.
    """
    sm: Any = request.app.state.spoolman

    # Resolve config off the data sources (sync, but cheap) before any compute.
    aliases_raw, tag_map, vendor_aliases, field_names = _resolve_match_config()

    # Fast path: serve the cached result when present and recompute was NOT requested.
    if not recompute:
        cached = load_match_cache(_settings.data_dir)
        if cached is not None:
            meta = get_cache_metadata(
                _settings.data_dir, _settings.opentag_cache_max_age_hours
            )
            current_fp = build_fingerprint(
                dataset_count=meta.get("count", 0),
                dataset_fetched_at=meta.get("fetched_at"),
                dataset_commit_sha=meta.get("commit_sha"),
                sm_count=await _safe_sm_count(sm),
                aliases_raw=aliases_raw,
                tag_map=tag_map,
                field_names=field_names,
            )
            resp = OpenTagMatchesResponse.model_validate(cached["response"])
            resp.computed_at = cached.get("computed_at")
            resp.stale_inputs = inputs_stale(cached.get("fingerprint"), current_fp)
            return resp

    # Compute path: load the dataset (network if stale), fetch SM filaments, then
    # offload the pure scoring to a worker thread.
    try:
        dataset = await load_opentag_dataset(
            _settings.data_dir,
            _settings.opentag_cache_max_age_hours,
            force=False,
        )
    except httpx.TimeoutException as exc:
        logger.error("opentag matches: timed out downloading dataset from OpenPrintTag: %s", exc)
        raise api_error(
            504,
            "opentag_fetch_timeout",
            "Timed out downloading the OpenTag dataset from OpenPrintTag — "
            "it downloads a large tarball; try again.",
        ) from exc
    except httpx.HTTPStatusError as exc:
        logger.error(
            "opentag matches: OpenPrintTag/GitHub returned HTTP %d: %s",
            exc.response.status_code, exc,
        )
        raise api_error(
            502,
            "opentag_fetch_failed",
            f"Failed to download the OpenTag dataset from OpenPrintTag "
            f"(HTTP {exc.response.status_code} — GitHub may be rate-limiting or unavailable).",
        ) from exc
    except httpx.RequestError as exc:
        logger.error("opentag matches: connection error downloading dataset from OpenPrintTag: %s", exc)
        raise api_error(
            502,
            "opentag_fetch_failed",
            "Could not reach api.github.com to download the OpenTag dataset — "
            "check that the bridge container has outbound HTTPS access.",
        ) from exc

    materials: list[dict[str, Any]] = dataset["materials"]
    dataset_lexicon: dict[str, list[str]] | None = dataset.get("lexicon")
    _record_last_count(dataset["count"])

    sm_filaments = await sm.get_filaments()

    # Offload the pure-CPU scoring to a worker thread — no I/O happens inside.
    matches = await run_in_threadpool(
        _compute_matches,
        sm_filaments,
        materials,
        dataset_lexicon,
        tag_map,
        vendor_aliases,
        field_names["uuid"],
        field_names["ignore"],
    )

    updates_count = sum(1 for m in matches if m.has_update)
    dataset_meta = OpenTagDatasetMeta(
        fetched_at=dataset["fetched_at"],
        count=dataset["count"],
        stale=dataset["stale"],
        commit_sha=dataset.get("commit_sha"),
    )
    computed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    response = OpenTagMatchesResponse(
        dataset=dataset_meta,
        matches=matches,
        updates_count=updates_count,
        computed_at=computed_at,
        stale_inputs=False,
    )

    # Persist for the instant fast-path on the next visit.
    fingerprint = build_fingerprint(
        dataset_count=dataset["count"],
        dataset_fetched_at=dataset["fetched_at"],
        dataset_commit_sha=dataset.get("commit_sha"),
        sm_count=len(sm_filaments),
        aliases_raw=aliases_raw,
        tag_map=tag_map,
        field_names=field_names,
    )
    save_match_cache(
        _settings.data_dir,
        response.model_dump(mode="json"),
        computed_at,
        fingerprint,
    )
    return response


async def _safe_sm_count(sm: Any) -> int:
    """Best-effort Spoolman filament count for stale-input detection.

    Used only by the cached fast path to decide ``stale_inputs``; a failure here
    must never block serving the cache, so it returns -1 (which simply forces
    ``stale_inputs`` true) on error.
    """
    try:
        return len(await sm.get_filaments())
    except Exception:
        return -1


@router.post("/openprinttag/apply", response_model=OpenTagApplyResponse)
async def opentag_apply(
    body: OpenTagApplyRequest,
    request: Request,
) -> OpenTagApplyResponse:
    """Apply user-confirmed field choices to Spoolman, then push slug/uuid to FDB settings bag.

    Each filament decision is applied independently; per-filament errors are
    non-fatal. Only fields not marked keep_mine are written. Only fields with
    a non-None value are written.

    Before the decision loop, ensure the required Spoolman extra fields exist so that
    PATCH writes to openprinttag_slug / openprinttag_uuid / filamentdb_material_tags
    never 422 due to undefined field keys.
    """
    sm: Any = request.app.state.spoolman
    fdb: Any = request.app.state.filamentdb

    # Self-heal: create any missing Spoolman extra fields before any write attempt.
    # ensure_extra_fields is idempotent — it only POSTs fields that are not yet defined.
    try:
        await sm.ensure_extra_fields()
    except Exception as exc:
        logger.error("opentag apply: could not ensure Spoolman extra fields: %s", exc)
        raise api_error(
            502,
            "opentag_field_setup_failed",
            f"Could not ensure the OpenTag extra fields exist in Spoolman: {exc}",
        ) from exc

    # Build vendor index once per apply call (exact trimmed name → vendor_id).
    # Exact-name matching (not normalize_vendor) is intentional: standardizing on
    # OpenTag's canonical spelling requires distinguishing "Elegoo" from "ELEGOO".
    # A case-only diff therefore creates a separate canonical vendor and re-points
    # only this filament — the accepted trade-off documented in decisions.md.
    # First occurrence wins when two existing vendors share the same trimmed name.
    # New vendors created during this run are cached here to avoid duplicates.
    try:
        existing_vendors = await sm.get_vendors()
    except Exception:
        existing_vendors = []
    vendor_id_by_name: dict[str, int] = {}
    for v in existing_vendors:
        key = v.name.strip()
        if key not in vendor_id_by_name:
            vendor_id_by_name[key] = v.id

    async def _ensure_vendor(name: str) -> int | None:
        """Resolve a vendor name to a Spoolman vendor_id, creating it if missing.

        Uses exact (trimmed) name matching so "ELEGOO" and "Elegoo" are treated as
        distinct vendors.  New vendors are cached in ``vendor_id_by_name`` within
        this apply call so no duplicate is created even if the same name appears
        multiple times in one batch.
        """
        key = name.strip()
        if not key:
            return None
        if key in vendor_id_by_name:
            return vendor_id_by_name[key]
        created = await sm.create_vendor({"name": name})
        vendor_id_by_name[key] = created.id
        logger.info("opentag apply: created Spoolman vendor %r (id=%d)", name, created.id)
        return created.id

    results: list[OpenTagApplyFilamentResult] = []
    applied = 0
    ignored = 0
    errors = 0

    for decision in body.decisions:
        if decision.ignored:
            ignored += 1
            results.append(OpenTagApplyFilamentResult(
                spoolman_filament_id=decision.spoolman_filament_id,
                status="ignored",
            ))
            continue

        # Unmatch: clear the OpenTag identity instead of writing one.  Resolve the FDB
        # filament id from the decision (preferred) or by reading the SM cross-ref extra.
        if decision.clear_identity:
            try:
                fdb_id = decision.fdb_filament_id or await _resolve_fdb_filament_id(
                    sm, decision.spoolman_filament_id
                )
                fdb_cleared = await _clear_opentag_identity(
                    sm, fdb, decision.spoolman_filament_id, fdb_id
                )
                _record_change(
                    action="update",
                    direction="filamentdb_to_spoolman",
                    entity_type="filament",
                    fdb_filament_id=fdb_id,
                    spoolman_id=decision.spoolman_filament_id,
                    field_name="opentag_clear",
                    new_value=[],
                    cycle_id="opentag-apply",
                )
                applied += 1
                results.append(OpenTagApplyFilamentResult(
                    spoolman_filament_id=decision.spoolman_filament_id,
                    status="cleared",
                    identity_cleared=True,
                    fdb_settings_updated=fdb_cleared,
                ))
            except Exception as exc:
                errors += 1
                resp_body = ""
                if hasattr(exc, "response") and exc.response is not None:
                    try:
                        resp_body = f" — response: {exc.response.text}"
                    except Exception:
                        pass
                logger.error(
                    "opentag apply: clear failed for SM filament %d: %s%s",
                    decision.spoolman_filament_id, _scrub(exc), _scrub(resp_body),
                )
                results.append(OpenTagApplyFilamentResult(
                    spoolman_filament_id=decision.spoolman_filament_id,
                    status="error",
                    error=str(exc),
                ))
            continue

        patch, fdb_keys, vendor_name = _build_sm_patch(decision)
        fields_written: list[str] = []
        fdb_settings_updated = False

        try:
            # Resolve vendor find-or-create and add vendor_id to the PATCH payload.
            if vendor_name:
                vendor_id = await _ensure_vendor(vendor_name)
                if vendor_id is not None:
                    patch["vendor_id"] = vendor_id

            if patch:
                await sm.update_filament(decision.spoolman_filament_id, patch)
                # Track written fields for the response
                for fd in decision.fields:
                    if not fd.keep_mine and fd.value is not None:
                        fields_written.append(fd.field)
                if vendor_name and "vendor_id" in patch:
                    # Ensure "vendor" appears exactly once in fields_written
                    if "vendor" not in fields_written:
                        fields_written.append("vendor")
                if decision.openprinttag_slug:
                    fields_written.append(f"extra.{_settings.spoolman_field_openprinttag_slug}")
                if decision.openprinttag_uuid:
                    fields_written.append(f"extra.{_settings.spoolman_field_openprinttag_uuid}")
                # dedupe
                fields_written = list(dict.fromkeys(fields_written))
                logger.info(
                    "opentag apply: patched SM filament %d fields=%s",
                    decision.spoolman_filament_id, fields_written,
                )
                _record_change(
                    action="update",
                    direction="filamentdb_to_spoolman",
                    entity_type="filament",
                    spoolman_id=decision.spoolman_filament_id,
                    field_name="opentag_apply",
                    new_value=fields_written,
                    cycle_id="opentag-apply",
                )

            # FDB settings-bag merge (Phase 5 scoped exception)
            if fdb_keys and decision.fdb_filament_id:
                await fdb.merge_filament_settings(decision.fdb_filament_id, fdb_keys)
                fdb_settings_updated = True
                logger.info(
                    "opentag apply: merged OpenTag identity into FDB filament %s: %s",
                    decision.fdb_filament_id, list(fdb_keys.keys()),
                )
                _record_change(
                    action="update",
                    direction="spoolman_to_filamentdb",
                    entity_type="filament",
                    fdb_filament_id=decision.fdb_filament_id,
                    spoolman_id=decision.spoolman_filament_id,
                    field_name="opentag_identity",
                    new_value=list(fdb_keys.keys()),
                    cycle_id="opentag-apply",
                )

            applied += 1
            results.append(OpenTagApplyFilamentResult(
                spoolman_filament_id=decision.spoolman_filament_id,
                status="ok",
                fields_written=fields_written,
                fdb_settings_updated=fdb_settings_updated,
            ))
        except Exception as exc:
            errors += 1
            # Include Spoolman's response body when available so the error log
            # shows Spoolman's detail message (e.g. field type mismatch) rather
            # than just the HTTP status code.
            resp_body: str = ""
            if hasattr(exc, "response") and exc.response is not None:
                try:
                    resp_body = f" — response: {exc.response.text}"
                except Exception:
                    pass
            logger.error(
                "opentag apply: error for SM filament %d: %s%s",
                decision.spoolman_filament_id, exc, resp_body,
            )
            results.append(OpenTagApplyFilamentResult(
                spoolman_filament_id=decision.spoolman_filament_id,
                status="error",
                error=str(exc),
            ))

    return OpenTagApplyResponse(
        applied=applied,
        ignored=ignored,
        errors=errors,
        results=results,
    )


class OpenTagClearResponse(BaseModel):
    spoolman_filament_id: int
    spoolman_cleared: bool
    fdb_settings_updated: bool
    fdb_filament_id: str | None = None


@router.post("/openprinttag/clear/{filament_id}", response_model=OpenTagClearResponse)
async def opentag_clear_identity(
    filament_id: int,
    request: Request,
) -> OpenTagClearResponse:
    """Clear the OpenTag identity on a single Spoolman filament (unmatch).

    Blanks ``openprinttag_slug`` + ``openprinttag_uuid`` on the Spoolman filament and
    removes only those two keys from the linked FDB filament's ``settings{}`` bag (the
    approved scoped exception).  Does NOT touch ``openprinttag_ignore``.  Idempotent —
    clearing an already-untagged filament is a no-op write.

    Standalone counterpart to the Apply-flow unmatch path; usable directly if a caller
    wants an immediate clear without staging through Apply.
    """
    sm: Any = request.app.state.spoolman
    fdb: Any = request.app.state.filamentdb

    try:
        await sm.ensure_extra_fields()
    except Exception as exc:
        logger.warning("opentag clear: ensure_extra_fields failed: %s", _scrub(exc))

    fdb_id = await _resolve_fdb_filament_id(sm, filament_id)
    try:
        fdb_cleared = await _clear_opentag_identity(sm, fdb, filament_id, fdb_id)
    except Exception as exc:
        resp_body = ""
        if hasattr(exc, "response") and exc.response is not None:
            try:
                resp_body = f" — response: {exc.response.text}"
            except Exception:
                pass
        logger.error(
            "opentag clear: could not clear SM filament %d: %s%s",
            filament_id, _scrub(exc), _scrub(resp_body),
        )
        raise api_error(
            502,
            "opentag_clear_failed",
            f"Could not clear OpenTag identity on Spoolman filament {filament_id}: {exc}",
        ) from exc

    return OpenTagClearResponse(
        spoolman_filament_id=filament_id,
        spoolman_cleared=True,
        fdb_settings_updated=fdb_cleared,
        fdb_filament_id=fdb_id,
    )


@router.post("/openprinttag/ignore/{filament_id}", response_model=OpenTagIgnoreResponse)
async def opentag_set_ignore(
    filament_id: int,
    request: Request,
    ignored: bool = True,
) -> OpenTagIgnoreResponse:
    """Set or clear the openprinttag_ignore flag on a Spoolman filament.

    When ignored=true (default), the filament is excluded from the "updates available"
    count and banner.  Call with ignored=false to un-ignore.

    The flag is stored as a Spoolman extra field (``openprinttag_ignore``) on the filament,
    so it travels with the record and persists across bridge restarts and cache clears.
    """
    sm: Any = request.app.state.spoolman

    # Ensure the extra field exists before writing.
    try:
        await sm.ensure_extra_fields()
    except Exception as exc:
        logger.warning("opentag ignore: ensure_extra_fields failed: %s", exc)

    ignore_field = _settings.spoolman_field_openprinttag_ignore
    # Spoolman text extras are JSON-quoted; "1" = ignored, "" = not ignored.
    value = encode_extra_value("1") if ignored else encode_extra_value("")
    try:
        await sm.update_filament(filament_id, {"extra": {ignore_field: value}})
        logger.info(
            "opentag ignore: set %s=%s on SM filament %d",
            _scrub(ignore_field), _scrub(ignored), filament_id,
        )
    except Exception as exc:
        resp_body = ""
        if hasattr(exc, "response") and exc.response is not None:
            try:
                resp_body = f" — response: {exc.response.text}"
            except Exception:
                pass
        logger.error(
            "opentag ignore: could not update SM filament %d: %s%s",
            filament_id, _scrub(exc), _scrub(resp_body),
        )
        raise api_error(
            502,
            "opentag_ignore_failed",
            f"Could not update Spoolman filament {filament_id}: {exc}",
        ) from exc

    return OpenTagIgnoreResponse(spoolman_filament_id=filament_id, ignored_updates=ignored)


@router.get("/openprinttag/search", response_model=OpenTagSearchResponse)
async def opentag_search(
    brand: str = "",
    material: str = "",
    q: str = "",
    limit: int = 20,
) -> OpenTagSearchResponse:
    """Manual free-text search within the cached OpenTag dataset.

    Scores a synthetic SpoolmanFilament (built from ``brand``, ``material``, ``q``)
    through the same ``score_candidate`` as the automatic matcher — no duplicate scorer.

    Query params:
    - ``brand``:    Optional brand name to pre-filter (same logic as automatic brand pre-filter).
    - ``material``: Optional material type (polymer) to pre-filter.
    - ``q``:        Free-text query (usually the color/modifier part of a filament name).
    - ``limit``:    Max results (default 20, max 50).

    Returns the top ``limit`` scored candidates sorted by score descending.
    """
    # Load cached dataset (no network fetch — must already be cached)
    cache = _load_cache(_settings.data_dir)
    if cache is None or not cache.get("materials"):
        return OpenTagSearchResponse(results=[])

    materials: list[dict[str, Any]] = [m for m in cache.get("materials", []) if isinstance(m, dict)]
    dataset_lexicon: dict[str, list[str]] | None = cache.get("lexicon")

    # Resolve config off the data sources, then offload the pure scoring loop.
    _aliases_raw, tag_map, vendor_aliases, _field_names = _resolve_match_config()

    results = await run_in_threadpool(
        _compute_search,
        materials, dataset_lexicon, tag_map, vendor_aliases, brand, material, q, limit,
    )
    return OpenTagSearchResponse(results=results)


def _compute_search(
    materials: list[dict[str, Any]],
    dataset_lexicon: dict[str, list[str]] | None,
    tag_map: dict[str, int],
    vendor_aliases: dict[str, str],
    brand: str,
    material: str,
    q: str,
    limit: int,
) -> list[OpenTagCandidate]:
    """Pure-CPU manual-search scoring — safe to run in a worker thread (no I/O)."""
    from app.core.opentag_match import DEFAULT_COLOR_KEYWORDS
    color_map = dict(DEFAULT_COLOR_KEYWORDS)

    limit = min(limit, 50)

    # Brand pre-filter (same logic as automatic matcher)
    if brand:
        resolved_brand = resolve_opentag_brand(brand, vendor_aliases)
        materials_by_brand: dict[str, list[dict[str, Any]]] = {}
        for m in materials:
            bk = normalize_vendor(m.get("brandName"))
            materials_by_brand.setdefault(bk, []).append(m)
        materials = materials_by_brand.get(resolved_brand, [])

    # Material (polymer family) pre-filter
    if material:
        sm_fam = material_family(material, tag_map)
        if sm_fam:
            materials = [
                c for c in materials
                if material_family(c.get("type") or c.get("abbreviation") or "", tag_map) in ("", sm_fam)
            ]

    if not materials:
        return []

    # Build a synthetic SM filament from the query params so we can reuse score_candidate
    # unchanged (no duplicate scorer — as per plan).
    synthetic_sm = _SpoolmanFilament(
        id=0,
        name=q or "",
        vendor=_SpoolmanVendor(id=0, name=brand) if brand else None,
        material=material or None,
        color_hex=None,
        extra={},
    )

    scored = [
        (score_candidate(synthetic_sm, opt, tag_map, vendor_aliases, color_map, dataset_lexicon), opt)
        for opt in materials
    ]
    scored.sort(key=lambda x: x[0], reverse=True)

    results: list[OpenTagCandidate] = []
    for conf, mat in scored[:limit]:
        opt_fields = opt_to_spoolman_fields(mat, tag_map)
        sm_for_fields = _SpoolmanFilament(
            id=0,
            name=q or "",
            vendor=_SpoolmanVendor(id=0, name=brand) if brand else None,
            material=material or None,
            color_hex=None,
            extra={},
        )
        field_rows = _build_field_rows(sm_for_fields, opt_fields)
        results.append(OpenTagCandidate(
            opt_uuid=mat.get("uuid"),
            opt_slug=mat.get("slug"),
            opt_brand=mat.get("brandName"),
            opt_name=mat.get("name"),
            opt_color_hex=mat.get("color"),
            confidence=conf,
            multicolor_mismatch=False,
            fields=field_rows,
        ))

    return results


# ---------------------------------------------------------------------------
# Completeness report — which matched OpenPrintTag records are missing data
# ---------------------------------------------------------------------------

# (key, label) pairs counted as "missing" when the OPT record's VALUE is empty.
# Identity (uuid/slug/brandSlug/brandName/name) is excluded — always present.
# completenessScore/completenessTier are dead (always None) — excluded.
# secondaryColors is handled separately (conditional on multicolor).
_COMPLETENESS_FIELDS: list[tuple[str, str]] = [
    # Core
    ("type", "Material type"),
    ("abbreviation", "Abbreviation"),
    ("color", "Primary color"),
    ("density", "Density"),
    ("nozzleTempMin", "Nozzle temp (min)"),
    ("nozzleTempMax", "Nozzle temp (max)"),
    ("bedTempMin", "Bed temp (min)"),
    ("bedTempMax", "Bed temp (max)"),
    ("tags", "Tags"),
    ("photoUrl", "Photo URL"),
    ("productUrl", "Product URL"),
    # Extended
    ("chamberTemp", "Chamber temp"),
    ("preheatTemp", "Preheat temp"),
    ("dryingTemp", "Drying temp"),
    ("dryingTime", "Drying time"),
    ("hardnessShoreD", "Hardness (Shore D)"),
    ("transmissionDistance", "Transmission distance"),
]

# Arrangement tag strings on an OPT record that imply a multicolor filament.
_MULTICOLOR_TAG_STRINGS = {"coextruded", "gradient", "gradual_color_change"}


def _opt_value_missing(value: Any) -> bool:
    """A field is *missing* when its VALUE is empty — never because the key is absent
    (all OPTMaterial keys are always present).  Empty = None, "", or []."""
    return value in (None, "", [])


def _is_multicolor(sm_fil: _SpoolmanFilament, opt: dict[str, Any]) -> bool:
    """True when this filament should be treated as multicolor — so secondaryColors
    counts toward completeness.  Driven by SM ``multi_color_hexes`` OR an OPT
    arrangement tag (coextruded / gradient / gradual_color_change)."""
    if sm_fil.multi_color_hexes:
        return True
    tags = opt.get("tags") or []
    return any(str(t).strip().lower() in _MULTICOLOR_TAG_STRINGS for t in tags)


def _your_value_hint(key: str, sm_fil: _SpoolmanFilament) -> Any:
    """Best-effort "you have this to contribute" hint from the SM filament.
    Returns None when no sensible SM source exists (blank hint is fine)."""
    if key == "type":
        return sm_fil.material
    if key == "color":
        return sm_fil.color_hex
    if key == "density":
        return sm_fil.density
    if key in ("nozzleTempMin", "nozzleTempMax"):
        return sm_fil.settings_extruder_temp
    if key in ("bedTempMin", "bedTempMax"):
        return sm_fil.settings_bed_temp
    if key == "secondaryColors":
        return sm_fil.multi_color_hexes
    # tags ← SM finish/material tags: SM filaments carry no first-class tag list the
    # bridge ingests, so leave blank rather than guess.
    return None


@router.get("/openprinttag/completeness", response_model=OpenTagCompletenessResponse)
async def opentag_completeness(request: Request) -> OpenTagCompletenessResponse:
    """Report OpenPrintTag record completeness for every tagged Spoolman filament.

    For each SM filament carrying a non-empty ``openprinttag_uuid``, resolve its raw
    OPTMaterial via the ``by_uuid`` index and report which schema attributes that record
    leaves EMPTY (the user can then go enrich and contribute them upstream).  This measures
    OPT-record completeness, NOT a diff against the user's data — the SM value is only a
    best-effort "you have this to contribute" hint.

    The raw OPTMaterial dict is inspected directly (NOT through opt_to_spoolman_fields /
    _build_candidate, which are lossy for self-completeness).

    Known limitation: the bridge's dataset parser does not ingest every upstream OPT schema
    field (e.g. hardness_shore_a, heatbreak_temperature, max_chamber_temperature, typed/
    multiple photos).  This report covers only ingested attributes.
    """
    sm: Any = request.app.state.spoolman

    # Load the cached dataset only (no network fetch — same as the search endpoint).
    cache = _load_cache(_settings.data_dir)
    meta = get_cache_metadata(_settings.data_dir, _settings.opentag_cache_max_age_hours)
    dataset_meta = OpenTagDatasetMeta(
        fetched_at=meta.get("fetched_at"),
        count=meta.get("count", 0),
        stale=meta.get("stale", True),
        commit_sha=meta.get("commit_sha"),
    )
    if cache is None or not cache.get("materials"):
        return OpenTagCompletenessResponse(dataset=dataset_meta, items=[], stale_count=0)

    uuid_field = _settings.spoolman_field_openprinttag_uuid
    slug_field = _settings.spoolman_field_openprinttag_slug

    sm_filaments = await sm.get_filaments()
    materials = cache.get("materials", [])

    # Offload the pure-CPU per-filament completeness scan to a worker thread.
    items, stale_count = await run_in_threadpool(
        _compute_completeness, sm_filaments, materials, uuid_field, slug_field
    )

    return OpenTagCompletenessResponse(
        dataset=dataset_meta,
        items=items,
        stale_count=stale_count,
    )


def _compute_completeness(
    sm_filaments: list[Any],
    materials: list[dict[str, Any]],
    uuid_field: str,
    slug_field: str,
) -> tuple[list[OpenTagCompletenessItem], int]:
    """Pure-CPU completeness scan — safe to run in a worker thread (no I/O)."""
    by_uuid: dict[str, dict[str, Any]] = {}
    for m in materials:
        if isinstance(m, dict) and m.get("uuid"):
            by_uuid[m["uuid"]] = m

    items: list[OpenTagCompletenessItem] = []
    stale_count = 0
    for sm_fil in sm_filaments:
        opt_uuid = decode_extra_value(sm_fil.extra.get(uuid_field))
        if not opt_uuid:
            continue  # untagged — no OPT record to assess

        brand = sm_fil.vendor.name if sm_fil.vendor else None
        opt = by_uuid.get(opt_uuid)
        if opt is None:
            # Stale tag: uuid no longer in the dataset. Surface distinctly, don't drop.
            stale_count += 1
            items.append(OpenTagCompletenessItem(
                spoolman_filament_id=sm_fil.id,
                brand=brand,
                name=sm_fil.name,
                opt_slug=decode_extra_value(sm_fil.extra.get(slug_field)) or None,
                opt_uuid=opt_uuid,
                opt_url=None,
                missing_count=0,
                attributes=[],
                stale_match=True,
            ))
            continue

        attributes: list[OpenTagMissingAttribute] = []
        for key, label in _COMPLETENESS_FIELDS:
            if _opt_value_missing(opt.get(key)):
                attributes.append(OpenTagMissingAttribute(
                    key=key,
                    label=label,
                    opt_value=opt.get(key),
                    your_value=_your_value_hint(key, sm_fil),
                ))
        # secondaryColors only counts for multicolor filaments.
        if _is_multicolor(sm_fil, opt) and _opt_value_missing(opt.get("secondaryColors")):
            attributes.append(OpenTagMissingAttribute(
                key="secondaryColors",
                label="Secondary colors",
                opt_value=opt.get("secondaryColors"),
                your_value=_your_value_hint("secondaryColors", sm_fil),
            ))

        items.append(OpenTagCompletenessItem(
            spoolman_filament_id=sm_fil.id,
            brand=brand,
            name=sm_fil.name,
            opt_slug=opt.get("slug"),
            opt_uuid=opt.get("uuid"),
            opt_url=opt.get("productUrl") or None,
            missing_count=len(attributes),
            attributes=attributes,
            stale_match=False,
        ))

    return items, stale_count
