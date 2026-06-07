"""OpenTag cleanup tool — GET /api/openprinttag/matches, POST /api/openprinttag/refresh,
POST /api/openprinttag/apply.

Standalone tool: match Spoolman filaments against the OpenPrintTag dataset
(fetched from FDB's GET /api/openprinttag, cached locally), review per-field,
confirm, and apply writes to Spoolman + push slug/uuid into FDB settings bag.

Route prefix note: the path token "opentag" (without "print") collides with the
Qubit OpenTag web-analytics product on EasyList/uBlock filter lists and is
blocked by ad blockers.  The routes use "openprinttag" instead, which is safe.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.errors import api_error
from app.config import settings as _settings
from app.core.material_tags import DEFAULT_MATERIAL_TAG_IDS
from app.core.matcher import normalize_vendor
from app.core.opentag_cache import get_cache_metadata, load_opentag_dataset
from app.core.opentag_match import (
    find_best_match,
    material_family,
    opt_color_profile,
    opt_to_spoolman_fields,
    profiles_compatible,
    sm_color_profile,
)
from app.db import get_db
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


class OpenTagCacheStatus(BaseModel):
    """Lightweight cache metadata — returned without fetching from FDB."""
    exists: bool
    fetched_at: str | None
    count: int
    stale: bool
    max_age_hours: int


class OpenTagFieldRow(BaseModel):
    """Per-field comparison row for the review step."""
    field: str
    spoolman_value: Any
    opentag_value: Any
    # suggested value = opentag_value by default (caller may override)
    suggested_value: Any


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
    alternates: list[dict[str, Any]]  # top alternate OPTMaterial dicts
    ignored: bool = False


class OpenTagMatchesResponse(BaseModel):
    dataset: OpenTagDatasetMeta
    matches: list[OpenTagFilamentMatch]


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


class OpenTagApplyRequest(BaseModel):
    decisions: list[OpenTagFilamentDecision]


class OpenTagApplyFilamentResult(BaseModel):
    spoolman_filament_id: int
    status: str  # "ok" | "ignored" | "error"
    error: str | None = None
    fields_written: list[str] = []
    fdb_settings_updated: bool = False


class OpenTagApplyResponse(BaseModel):
    applied: int
    ignored: int
    errors: int
    results: list[OpenTagApplyFilamentResult]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _current_spoolman_value(sm_filament: Any, field: str) -> Any:
    """Extract the current value of a Spoolman field (including extra.* fields)."""
    if field.startswith("extra."):
        key = field[len("extra."):]
        raw = sm_filament.extra.get(key)
        return decode_extra_value(raw)
    return getattr(sm_filament, field, None)


def _build_field_rows(
    sm_filament: Any,
    opt_fields: dict[str, Any],
) -> list[OpenTagFieldRow]:
    """Build per-field comparison rows, SM current vs OPT suggested."""
    rows = []
    for field, opt_value in opt_fields.items():
        sm_value = _current_spoolman_value(sm_filament, field)
        rows.append(OpenTagFieldRow(
            field=field,
            spoolman_value=sm_value,
            opentag_value=opt_value,
            suggested_value=opt_value,
        ))
    return rows


def _build_sm_patch(
    decision: OpenTagFilamentDecision,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Build the Spoolman PATCH payload and FDB settings keys from a filament decision.

    Returns (patch_payload, fdb_settings_keys):
    - patch_payload: dict ready to PATCH SM filament (native fields + extra)
    - fdb_settings_keys: {"openprinttag_slug": ..., "openprinttag_uuid": ...}
      — only keys that are non-None
    """
    native: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    fdb_keys: dict[str, str] = {}

    for fd in decision.fields:
        if fd.keep_mine:
            continue
        if fd.value is None:
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

    return native, fdb_keys


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


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
    )


@router.post("/openprinttag/refresh", response_model=OpenTagDatasetMeta)
async def opentag_refresh(request: Request) -> OpenTagDatasetMeta:
    """Force a fresh fetch of the OpenTag dataset from FDB."""
    fdb = request.app.state.filamentdb
    try:
        result = await load_opentag_dataset(
            fdb,
            _settings.data_dir,
            _settings.opentag_cache_max_age_hours,
            force=True,
        )
    except httpx.TimeoutException as exc:
        logger.error("opentag refresh: timed out fetching dataset from FDB: %s", exc)
        raise api_error(
            504,
            "opentag_fetch_timeout",
            "Timed out fetching the OpenTag dataset from Filament DB — "
            "it downloads a large file on first load; try again.",
        ) from exc
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            logger.error("opentag refresh: FDB /api/openprinttag returned 404: %s", exc)
            raise api_error(
                502,
                "opentag_unavailable",
                "This Filament DB version doesn't expose /api/openprinttag — "
                "upgrade Filament DB.",
            ) from exc
        logger.error("opentag refresh: FDB returned HTTP %d: %s", exc.response.status_code, exc)
        raise api_error(
            502,
            "opentag_fetch_failed",
            f"Failed to fetch the OpenTag dataset from Filament DB (HTTP {exc.response.status_code}).",
        ) from exc
    except httpx.RequestError as exc:
        logger.error("opentag refresh: connection error fetching dataset from FDB: %s", exc)
        raise api_error(
            502,
            "opentag_fetch_failed",
            "Failed to connect to Filament DB while fetching the OpenTag dataset.",
        ) from exc
    return OpenTagDatasetMeta(
        fetched_at=result["fetched_at"],
        count=result["count"],
        stale=result["stale"],
    )


@router.get("/openprinttag/matches", response_model=OpenTagMatchesResponse)
async def opentag_matches(request: Request) -> OpenTagMatchesResponse:
    """Return per-Spoolman-filament OpenTag matches with per-field comparison."""
    fdb = request.app.state.filamentdb
    sm: Any = request.app.state.spoolman

    try:
        dataset = await load_opentag_dataset(
            fdb,
            _settings.data_dir,
            _settings.opentag_cache_max_age_hours,
            force=False,
        )
    except httpx.TimeoutException as exc:
        logger.error("opentag matches: timed out fetching dataset from FDB: %s", exc)
        raise api_error(
            504,
            "opentag_fetch_timeout",
            "Timed out fetching the OpenTag dataset from Filament DB — "
            "it downloads a large file on first load; try again.",
        ) from exc
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            logger.error("opentag matches: FDB /api/openprinttag returned 404: %s", exc)
            raise api_error(
                502,
                "opentag_unavailable",
                "This Filament DB version doesn't expose /api/openprinttag — "
                "upgrade Filament DB.",
            ) from exc
        logger.error("opentag matches: FDB returned HTTP %d: %s", exc.response.status_code, exc)
        raise api_error(
            502,
            "opentag_fetch_failed",
            f"Failed to fetch the OpenTag dataset from Filament DB (HTTP {exc.response.status_code}).",
        ) from exc
    except httpx.RequestError as exc:
        logger.error("opentag matches: connection error fetching dataset from FDB: %s", exc)
        raise api_error(
            502,
            "opentag_fetch_failed",
            "Failed to connect to Filament DB while fetching the OpenTag dataset.",
        ) from exc
    materials: list[dict[str, Any]] = dataset["materials"]
    tag_map = _settings.parsed_material_tag_ids

    sm_filaments = await sm.get_filaments()

    # Build a brand index once — keyed by normalize_vendor(brandName) — so each SM
    # filament only scores its own brand's candidates instead of all ~11k materials.
    materials_by_brand: dict[str, list[dict[str, Any]]] = {}
    for m in materials:
        if not isinstance(m, dict):
            continue
        brand_key = normalize_vendor(m.get("brandName"))
        materials_by_brand.setdefault(brand_key, []).append(m)

    n_filaments = len(sm_filaments)
    n_materials = len(materials)
    n_brands = len(materials_by_brand)
    logger.info(
        "opentag matches: scoring %d filaments against %d materials across %d brands",
        n_filaments, n_materials, n_brands,
    )

    matched = 0
    no_match = 0
    matches: list[OpenTagFilamentMatch] = []
    for sm_fil in sm_filaments:
        sm_brand_key = normalize_vendor(sm_fil.vendor.name if sm_fil.vendor else None)
        candidates = materials_by_brand.get(sm_brand_key, [])

        # Color-profile pre-filter: only score candidates whose arrangement is
        # compatible with the SM filament's arrangement (single/coextruded/gradient).
        sm_profile = sm_color_profile(sm_fil)
        candidates = [
            c for c in candidates
            if isinstance(c, dict) and profiles_compatible(sm_profile, opt_color_profile(c, tag_map))
        ]

        # Polymer-family hard gate: a PC filament must never match ASA; ASA must never
        # match PETG, etc.  Only gate when the SM filament has a non-empty / known
        # material (unknown SM material → don't gate, score all candidates).
        sm_fam = material_family(sm_fil.material, tag_map)
        if sm_fam:
            candidates = [
                c for c in candidates
                if material_family(
                    c.get("type") or c.get("abbreviation") or "", tag_map
                ) in ("", sm_fam)
            ]

        match_result = find_best_match(sm_fil, candidates, tag_map)
        best = match_result["best"]
        confidence = match_result["confidence"]
        alternates = match_result["alternates"]

        if best is None:
            # Include low-confidence / no-match filaments with empty field rows
            no_match += 1
            matches.append(OpenTagFilamentMatch(
                spoolman_filament_id=sm_fil.id,
                spoolman_name=sm_fil.name,
                spoolman_vendor=sm_fil.vendor.name if sm_fil.vendor else None,
                spoolman_material=sm_fil.material,
                spoolman_color_hex=sm_fil.color_hex,
                opt_uuid=None,
                opt_slug=None,
                opt_brand=None,
                opt_name=None,
                confidence=confidence,
                fields=[],
                alternates=alternates,
            ))
            continue

        matched += 1
        opt_fields = opt_to_spoolman_fields(best, tag_map)
        field_rows = _build_field_rows(sm_fil, opt_fields)

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
            fields=field_rows,
            alternates=alternates,
        ))

    logger.info("opentag matches: %d matched, %d no-match", matched, no_match)

    dataset_meta = OpenTagDatasetMeta(
        fetched_at=dataset["fetched_at"],
        count=dataset["count"],
        stale=dataset["stale"],
    )
    return OpenTagMatchesResponse(dataset=dataset_meta, matches=matches)


@router.post("/openprinttag/apply", response_model=OpenTagApplyResponse)
async def opentag_apply(
    body: OpenTagApplyRequest,
    request: Request,
) -> OpenTagApplyResponse:
    """Apply user-confirmed field choices to Spoolman, then push slug/uuid to FDB settings bag.

    Each filament decision is applied independently; per-filament errors are
    non-fatal. Only fields not marked keep_mine are written. Only fields with
    a non-None value are written.
    """
    sm: Any = request.app.state.spoolman
    fdb: Any = request.app.state.filamentdb

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

        patch, fdb_keys = _build_sm_patch(decision)
        fields_written: list[str] = []
        fdb_settings_updated = False

        try:
            if patch:
                await sm.update_filament(decision.spoolman_filament_id, patch)
                # Track written fields for the response
                for fd in decision.fields:
                    if not fd.keep_mine and fd.value is not None:
                        fields_written.append(fd.field)
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

            # FDB settings-bag merge (Phase 5 scoped exception)
            if fdb_keys and decision.fdb_filament_id:
                await fdb.merge_filament_settings(decision.fdb_filament_id, fdb_keys)
                fdb_settings_updated = True
                logger.info(
                    "opentag apply: merged OpenTag identity into FDB filament %s: %s",
                    decision.fdb_filament_id, list(fdb_keys.keys()),
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
            logger.error(
                "opentag apply: error for SM filament %d: %s",
                decision.spoolman_filament_id, exc,
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
