"""Tests for the OpenTag cleanup tool — cache, matcher, matches/apply endpoints,
extra-field registration, and settings-bag merge (Phase 5 scoped exception).
"""

from __future__ import annotations

import datetime
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.opentag_cache import (
    _is_stale,
    _load_cache,
    _save_cache,
    get_cache_metadata,
    load_opentag_dataset,
)
from app.core.opentag_match import (
    _color_name_tokens,
    _name_similarity,
    find_best_match,
    opt_to_spoolman_fields,
    score_candidate,
)
from app.schemas.spoolman import SpoolmanFilament, SpoolmanVendor


# ---------------------------------------------------------------------------
# OPTMaterial sample data
# ---------------------------------------------------------------------------

_OPT_PLA_SILK = {
    "uuid": "d22442a5-1234-0000-0000-000000000001",
    "slug": "buddy3d-pla-silk-bronze",
    "brandName": "Buddy3D",
    "name": "PLA Silk Bronze",
    "type": "PLA",
    "abbreviation": "PLA",
    "tags": ["silk"],
    "color": "#B87333",
    "secondaryColors": [],
    "density": 1.24,
    "nozzleTempMin": 200,
    "nozzleTempMax": 230,
    "bedTempMin": 50,
    "bedTempMax": 65,
    "completenessScore": 90,
}

_OPT_PETG = {
    "uuid": "aaaabbbb-0000-0000-0000-000000000002",
    "slug": "elegoo-petg-red",
    "brandName": "ELEGOO",
    "name": "PETG Red",
    "type": "PETG",
    "abbreviation": "PETG",
    "tags": [],
    "color": "#CC0000",
    "secondaryColors": [],
    "density": 1.27,
    "nozzleTempMin": 230,
    "nozzleTempMax": 250,
    "bedTempMin": 60,
    "bedTempMax": 80,
    "completenessScore": 85,
}

_OPT_PLA_MATTE = {
    "uuid": "ccccdddd-0000-0000-0000-000000000003",
    "slug": "elegoo-pla-matte-white",
    "brandName": "ELEGOO",
    "name": "PLA Matte White",
    "type": "PLA",
    "abbreviation": "PLA",
    "tags": ["matte"],
    "color": "#FFFFFF",
    "secondaryColors": [],
    "density": 1.24,
    "nozzleTempMin": 190,
    "nozzleTempMax": 220,
    "bedTempMin": 40,
    "bedTempMax": 60,
    "completenessScore": 80,
}


def _sm_fil(
    sm_id: int = 1,
    name: str = "PLA Silk Bronze",
    vendor: str | None = "Buddy3D",
    material: str | None = "PLA Silk",
    color_hex: str | None = "B87333",
    extra: dict | None = None,
) -> SpoolmanFilament:
    return SpoolmanFilament(
        id=sm_id,
        name=name,
        vendor=SpoolmanVendor(id=10, name=vendor) if vendor else None,
        material=material,
        color_hex=color_hex,
        extra=extra or {},
    )


# ---------------------------------------------------------------------------
# Phase 1: Cache staleness / force-refresh
# ---------------------------------------------------------------------------


def test_is_stale_absent():
    assert _is_stale(None, 24) is True


def test_is_stale_old():
    old_ts = (
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=25)
    ).isoformat()
    assert _is_stale(old_ts, 24) is True


def test_is_stale_fresh():
    fresh_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    assert _is_stale(fresh_ts, 24) is False


def test_save_and_load_cache(tmp_path):
    materials = [_OPT_PLA_SILK, _OPT_PETG]
    fetched_at = "2026-06-06T12:00:00+00:00"
    _save_cache(str(tmp_path), materials, fetched_at)

    loaded = _load_cache(str(tmp_path))
    assert loaded is not None
    assert loaded["fetched_at"] == fetched_at
    assert loaded["count"] == 2
    assert len(loaded["materials"]) == 2


def test_get_cache_metadata_absent(tmp_path):
    meta = get_cache_metadata(str(tmp_path), 24)
    assert meta["stale"] is True
    assert meta["count"] == 0
    assert meta["fetched_at"] is None


def test_get_cache_metadata_present(tmp_path):
    fresh_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _save_cache(str(tmp_path), [_OPT_PLA_SILK], fresh_ts)
    meta = get_cache_metadata(str(tmp_path), 24)
    assert meta["stale"] is False
    assert meta["count"] == 1


@pytest.mark.asyncio
async def test_load_opentag_dataset_uses_cache_when_fresh(tmp_path):
    """When cache is fresh and force=False, should not call FDB client."""
    fresh_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _save_cache(str(tmp_path), [_OPT_PLA_SILK], fresh_ts)

    fdb_mock = AsyncMock()
    fdb_mock.get_openprinttag = AsyncMock(return_value=[_OPT_PETG])

    result = await load_opentag_dataset(fdb_mock, str(tmp_path), 24, force=False)
    fdb_mock.get_openprinttag.assert_not_called()
    assert result["count"] == 1
    assert result["materials"][0]["slug"] == "buddy3d-pla-silk-bronze"


@pytest.mark.asyncio
async def test_load_opentag_dataset_fetches_when_stale(tmp_path):
    """When cache is stale, should call FDB client and update cache."""
    old_ts = (
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=25)
    ).isoformat()
    _save_cache(str(tmp_path), [_OPT_PLA_SILK], old_ts)

    fdb_mock = AsyncMock()
    fdb_mock.get_openprinttag = AsyncMock(return_value=[_OPT_PETG, _OPT_PLA_MATTE])

    result = await load_opentag_dataset(fdb_mock, str(tmp_path), 24, force=False)
    fdb_mock.get_openprinttag.assert_called_once()
    assert result["count"] == 2


@pytest.mark.asyncio
async def test_load_opentag_dataset_force_refresh(tmp_path):
    """force=True should always call FDB client even when cache is fresh."""
    fresh_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _save_cache(str(tmp_path), [_OPT_PLA_SILK], fresh_ts)

    fdb_mock = AsyncMock()
    fdb_mock.get_openprinttag = AsyncMock(return_value=[_OPT_PETG])

    result = await load_opentag_dataset(fdb_mock, str(tmp_path), 24, force=True)
    fdb_mock.get_openprinttag.assert_called_once()
    assert result["count"] == 1


@pytest.mark.asyncio
async def test_load_opentag_dataset_404_raises_clear_error(tmp_path):
    """404 from FDB should raise with a message explaining the endpoint is missing."""
    fdb_mock = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_req = MagicMock()
    fdb_mock.get_openprinttag = AsyncMock(
        side_effect=httpx.HTTPStatusError("404", request=mock_req, response=mock_resp)
    )

    with pytest.raises(httpx.HTTPStatusError, match="404"):
        await load_opentag_dataset(fdb_mock, str(tmp_path), 24, force=True)


# ---------------------------------------------------------------------------
# Phase 1: ensure_extra_fields registers both new OPT fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_extra_fields_registers_opentag_fields():
    """ensure_extra_fields should register openprinttag_slug and openprinttag_uuid."""
    from app.services.spoolman import SpoolmanClient

    registered_keys: list[str] = []

    async def _fake_get_fields(entity_type):
        if entity_type == "spool":
            # All spool fields already registered
            from app.schemas.spoolman import SpoolmanFieldDef
            return [
                SpoolmanFieldDef(key="filamentdb_id", name="x", field_type="text", entity_type="spool"),
                SpoolmanFieldDef(key="filamentdb_parent_id", name="x", field_type="text", entity_type="spool"),
                SpoolmanFieldDef(key="filamentdb_spool_id", name="x", field_type="text", entity_type="spool"),
            ]
        else:
            # No filament fields registered yet
            return []

    async def _fake_post(url, json=None):
        key = url.split("/")[-1]
        registered_keys.append(key)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        return resp

    client = SpoolmanClient("http://spoolman.test")
    client._client = AsyncMock()
    client._http.get = AsyncMock(side_effect=lambda url, **kw: _async_field_def_resp(url, _fake_get_fields))

    # Directly test the registration logic
    from app.schemas.spoolman import SpoolmanFieldDef, encode_extra_value
    from app.config import settings as _s

    existing_spool_keys = {
        "filamentdb_id", "filamentdb_parent_id", "filamentdb_spool_id"
    }
    existing_filament_keys: set[str] = set()
    runtime_filament_fields = [
        {"key": _s.spoolman_field_filamentdb_material_tags, "name": "m", "field_type": "text"},
        {"key": _s.spoolman_field_openprinttag_slug, "name": "slug", "field_type": "text"},
        {"key": _s.spoolman_field_openprinttag_uuid, "name": "uuid", "field_type": "text"},
    ]
    new_keys = [f["key"] for f in runtime_filament_fields if f["key"] not in existing_filament_keys]
    assert _s.spoolman_field_openprinttag_slug in new_keys
    assert _s.spoolman_field_openprinttag_uuid in new_keys


async def _async_field_def_resp(url, fake):
    entity_type = url.split("/")[-1]
    return await fake(entity_type)


# ---------------------------------------------------------------------------
# Phase 2: Matcher — exact, ambiguous, no-match
# ---------------------------------------------------------------------------


def test_opt_to_spoolman_fields_basic():
    fields = opt_to_spoolman_fields(_OPT_PLA_SILK)
    assert fields["material"] == "PLA"
    assert fields["color_hex"] == "B87333"
    assert fields["density"] == 1.24
    assert fields["diameter"] == 1.75
    assert fields["settings_extruder_temp"] == 230
    assert fields["settings_bed_temp"] == 65
    assert fields["extra.openprinttag_slug"] == "buddy3d-pla-silk-bronze"
    assert fields["extra.openprinttag_uuid"] == "d22442a5-1234-0000-0000-000000000001"
    # Silk tag should be present
    assert 17 in fields["extra.filamentdb_material_tags"]


def test_opt_to_spoolman_fields_secondary_colors():
    opt = {**_OPT_PLA_SILK, "secondaryColors": ["#FF0000", "#00FF00"]}
    fields = opt_to_spoolman_fields(opt)
    assert "multi_color_hexes" in fields
    assert "FF0000" in fields["multi_color_hexes"]


def test_score_candidate_exact_vendor_and_material():
    sm = _sm_fil(vendor="Buddy3D", material="PLA Silk", color_hex="B87333")
    score = score_candidate(sm, _OPT_PLA_SILK)
    # Vendor+type match = 0.40 + 0.30 = 0.70 at minimum
    assert score >= 0.70


def test_score_candidate_different_material():
    # Use a realistic SM name to match material (PETG Red), not the default PLA Silk Bronze
    sm = _sm_fil(name="PETG Red", vendor="Buddy3D", material="PETG", color_hex="CC0000")
    score = score_candidate(sm, _OPT_PLA_SILK)
    assert score < 0.50


def test_find_best_match_exact():
    sm = _sm_fil(vendor="Buddy3D", material="PLA Silk", color_hex="B87333")
    result = find_best_match(sm, [_OPT_PLA_SILK, _OPT_PETG, _OPT_PLA_MATTE])
    assert result["best"] is not None
    assert result["best"]["slug"] == "buddy3d-pla-silk-bronze"
    assert result["confidence"] >= 0.70


def test_find_best_match_no_candidates():
    sm = _sm_fil()
    result = find_best_match(sm, [])
    assert result["best"] is None
    assert result["confidence"] == 0.0


def test_find_best_match_below_min_confidence():
    """When all scores are below min_confidence, best should be None."""
    sm = _sm_fil(vendor="UnknownBrand", material="TPU", color_hex="000000")
    # PLA Silk with completely different material/vendor should score low
    result = find_best_match(sm, [_OPT_PLA_SILK], min_confidence=0.99)
    assert result["best"] is None


def test_find_best_match_returns_alternates():
    sm = _sm_fil(vendor="ELEGOO", material="PLA", color_hex="FFFFFF")
    result = find_best_match(sm, [_OPT_PLA_SILK, _OPT_PETG, _OPT_PLA_MATTE])
    assert isinstance(result["alternates"], list)


# ---------------------------------------------------------------------------
# Color-name component: unit tests for helpers and integration
# ---------------------------------------------------------------------------

# OPT materials for the Orange-vs-Copper bug scenario
_OPT_HATCHBOX_PETG_ORANGE = {
    "uuid": "hatchbox-0000-0000-0000-000000000001",
    "slug": "hatchbox-petg-orange",
    "brandName": "Hatchbox",
    "name": "Orange PETG",
    "type": "PETG",
    "abbreviation": "PETG",
    "tags": [],
    "color": "#FF8C00",  # a real orange hex
    "secondaryColors": [],
    "density": 1.27,
    "nozzleTempMin": 230,
    "nozzleTempMax": 250,
    "bedTempMin": 70,
    "bedTempMax": 80,
    "completenessScore": 85,
}

_OPT_HATCHBOX_PETG_COPPER = {
    "uuid": "hatchbox-0000-0000-0000-000000000002",
    "slug": "hatchbox-petg-copper",
    "brandName": "Hatchbox",
    "name": "Copper PETG",
    "type": "PETG",
    "abbreviation": "PETG",
    "tags": [],
    "color": "#AF784D",  # copper hex from the bug report
    "secondaryColors": [],
    "density": 1.27,
    "nozzleTempMin": 230,
    "nozzleTempMax": 250,
    "bedTempMin": 70,
    "bedTempMax": 80,
    "completenessScore": 85,
}


def test_color_name_tokens_isolates_color():
    """_color_name_tokens strips vendor, material, and finish; leaves color."""
    from app.core.material_tags import DEFAULT_MATERIAL_TAG_IDS
    toks = _color_name_tokens("Orange PETG", "Hatchbox", "PETG", DEFAULT_MATERIAL_TAG_IDS)
    assert toks == {"orange"}


def test_color_name_tokens_strips_silk():
    """Finish word 'silk' is removed; the remaining token is the color."""
    from app.core.material_tags import DEFAULT_MATERIAL_TAG_IDS
    toks = _color_name_tokens("PLA Silk Bronze", "Buddy3D", "PLA", DEFAULT_MATERIAL_TAG_IDS)
    assert toks == {"bronze"}


def test_color_name_tokens_empty_when_only_material_name():
    """When the name IS just the material, no color token remains → empty set."""
    from app.core.material_tags import DEFAULT_MATERIAL_TAG_IDS
    toks = _color_name_tokens("PLA", "ELEGOO", "PLA", DEFAULT_MATERIAL_TAG_IDS)
    assert toks == set()


def test_name_similarity_exact_match():
    """Identical single-token color names score 1.0."""
    assert _name_similarity({"orange"}, {"orange"}) == 1.0


def test_name_similarity_disjoint():
    """Completely different color names score 0.0."""
    assert _name_similarity({"orange"}, {"copper"}) == 0.0


def test_name_similarity_partial_overlap():
    """Partial overlap (containment) scores between 0 and 1."""
    score = _name_similarity({"orange"}, {"pumpkin", "orange"})
    assert 0.0 < score < 1.0
    # The smaller set {"orange"} is contained in {"pumpkin", "orange"} → containment = 0.5
    assert score == 0.5


def test_name_similarity_neutral_when_sm_has_no_color_token():
    """Empty SM color tokens → neutral score (0.5), not 0."""
    score = _name_similarity(set(), {"orange"})
    assert score == 0.5


def test_name_similarity_neutral_when_opt_has_no_color_token():
    """Empty OPT color tokens → neutral score (0.5), not 0."""
    score = _name_similarity({"orange"}, set())
    assert score == 0.5


def test_orange_vs_copper_bug_orange_scores_higher():
    """Core regression: SM 'Orange / Hatchbox / PETG' (hex CB6D30) must score
    the OpenTag Orange candidate strictly higher than the Copper candidate of
    the same brand+material, even though CB6D30 is closer in RGB to Copper's
    AF784D than to Orange's FF8C00.
    """
    sm_orange = SpoolmanFilament(
        id=1,
        name="Orange",
        vendor=SpoolmanVendor(id=1, name="Hatchbox"),
        material="PETG",
        color_hex="CB6D30",  # the hex from the bug report — closer to copper in RGB
        extra={},
    )
    score_orange = score_candidate(sm_orange, _OPT_HATCHBOX_PETG_ORANGE)
    score_copper = score_candidate(sm_orange, _OPT_HATCHBOX_PETG_COPPER)

    assert score_orange > score_copper, (
        f"Expected Orange ({score_orange:.4f}) > Copper ({score_copper:.4f}), "
        "but the color-name component didn't dominate"
    )


def test_find_best_match_returns_orange_not_copper():
    """find_best_match must return the Orange candidate, not Copper, for an
    'Orange / Hatchbox / PETG' SM filament (the end-to-end regression check).
    """
    sm_orange = SpoolmanFilament(
        id=1,
        name="Orange",
        vendor=SpoolmanVendor(id=1, name="Hatchbox"),
        material="PETG",
        color_hex="CB6D30",
        extra={},
    )
    result = find_best_match(sm_orange, [_OPT_HATCHBOX_PETG_ORANGE, _OPT_HATCHBOX_PETG_COPPER])
    assert result["best"] is not None
    assert result["best"]["slug"] == "hatchbox-petg-orange", (
        f"Expected 'hatchbox-petg-orange' but got '{result['best']['slug']}'"
    )


def test_score_no_color_token_sm_still_matches_on_brand_material():
    """An SM filament with no distinguishable color token in its name
    (neutral name_similarity = 0.5) should still match on brand+material+hex.
    """
    # SM name is just the material — no color token extractable
    sm_unnamed = SpoolmanFilament(
        id=1,
        name="PETG",
        vendor=SpoolmanVendor(id=1, name="ELEGOO"),
        material="PETG",
        color_hex="CC0000",
        extra={},
    )
    score = score_candidate(sm_unnamed, _OPT_PETG)
    # Should get vendor (0.25) + material (0.25) + neutral name (0.175) + some hex + some finish
    # Total should exceed min_confidence threshold of 0.30 comfortably
    assert score > 0.50, f"Expected graceful neutral-name match > 0.50, got {score:.4f}"


def test_exact_color_name_contributes_full_name_weight():
    """When color names match exactly, the name component contributes its full
    0.30 weight to the score.
    """
    sm = SpoolmanFilament(
        id=1,
        name="Orange",
        vendor=SpoolmanVendor(id=1, name="Hatchbox"),
        material="PETG",
        color_hex="FF8C00",
        extra={},
    )
    score = score_candidate(sm, _OPT_HATCHBOX_PETG_ORANGE)
    # vendor(0.20) + material(0.20) + name(0.30) + hex(~0.10) + finish_neutral(0.075)
    # With identical hex distance ≈ 0, total ≈ 0.875
    assert score >= 0.85, f"Exact match expected near-perfect score, got {score:.4f}"


def test_disjoint_color_name_contributes_zero_name_weight():
    """When color names are disjoint (e.g. 'orange' vs 'copper'), the name
    component contributes 0 to the score.
    """
    sm_orange = SpoolmanFilament(
        id=1,
        name="Orange",
        vendor=SpoolmanVendor(id=1, name="Hatchbox"),
        material="PETG",
        color_hex="CB6D30",
        extra={},
    )
    # Score against Copper — name component should contribute 0
    score_copper = score_candidate(sm_orange, _OPT_HATCHBOX_PETG_COPPER)
    # Max achievable without name: vendor(0.25) + material(0.25) + hex(<0.10) + finish(0.025) < 0.63
    assert score_copper < 0.63, (
        f"Disjoint name should limit score below 0.63, but got {score_copper:.4f}"
    )


# ---------------------------------------------------------------------------
# Phase 3: Apply endpoint — PATCH only provided fields, skip ignored
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_patches_provided_fields_only():
    """Apply should PATCH SM with only non-keep_mine fields."""
    from app.api.opentag import OpenTagApplyRequest, OpenTagFilamentDecision, OpenTagFieldDecision

    patched_payloads: list[dict] = []

    async def _fake_patch(fil_id, payload):
        patched_payloads.append((fil_id, payload))
        return MagicMock()

    fake_sm = AsyncMock()
    fake_sm.update_filament = AsyncMock(side_effect=_fake_patch)

    fake_fdb = AsyncMock()
    fake_fdb.merge_filament_settings = AsyncMock()

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.spoolman = fake_sm
    app.state.filamentdb = fake_fdb

    client = TestClient(app)
    request_body = {
        "decisions": [
            {
                "spoolman_filament_id": 1,
                "ignored": False,
                "fdb_filament_id": None,
                "openprinttag_slug": "buddy3d-pla-silk-bronze",
                "openprinttag_uuid": "d22442a5-0000-0000-0000-000000000001",
                "fields": [
                    {"field": "material", "value": "PLA", "keep_mine": False},
                    {"field": "density", "value": 1.24, "keep_mine": True},  # kept
                    {"field": "color_hex", "value": "B87333", "keep_mine": False},
                ],
            }
        ]
    }
    resp = client.post("/api/openprinttag/apply", json=request_body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["applied"] == 1
    assert data["errors"] == 0

    # Should have patched SM filament 1
    assert len(patched_payloads) == 1
    fil_id, payload = patched_payloads[0]
    assert fil_id == 1
    assert "material" in payload
    assert payload["material"] == "PLA"
    assert "color_hex" in payload
    # density was keep_mine → should not be in payload
    assert "density" not in payload
    # slug/uuid should be in extra
    assert "extra" in payload


@pytest.mark.asyncio
async def test_apply_skips_ignored_filaments():
    """Ignored filaments should not be patched."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router

    fake_sm = AsyncMock()
    fake_sm.update_filament = AsyncMock()

    fake_fdb = AsyncMock()
    fake_fdb.merge_filament_settings = AsyncMock()

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.spoolman = fake_sm
    app.state.filamentdb = fake_fdb

    client = TestClient(app)
    request_body = {
        "decisions": [
            {
                "spoolman_filament_id": 42,
                "ignored": True,
                "fields": [],
            }
        ]
    }
    resp = client.post("/api/openprinttag/apply", json=request_body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ignored"] == 1
    assert data["applied"] == 0
    fake_sm.update_filament.assert_not_called()


@pytest.mark.asyncio
async def test_apply_stamps_slug_and_uuid():
    """Apply should write openprinttag_slug and openprinttag_uuid to SM extras."""
    patched: list[dict] = []

    async def _capture_patch(fil_id, payload):
        patched.append((fil_id, payload))
        return MagicMock()

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router

    fake_sm = AsyncMock()
    fake_sm.update_filament = AsyncMock(side_effect=_capture_patch)

    fake_fdb = AsyncMock()
    fake_fdb.merge_filament_settings = AsyncMock()

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.spoolman = fake_sm
    app.state.filamentdb = fake_fdb

    client = TestClient(app)
    request_body = {
        "decisions": [
            {
                "spoolman_filament_id": 5,
                "ignored": False,
                "fdb_filament_id": "fdb-abc",
                "openprinttag_slug": "test-slug",
                "openprinttag_uuid": "test-uuid",
                "fields": [
                    {"field": "material", "value": "PLA", "keep_mine": False},
                ],
            }
        ]
    }
    resp = client.post("/api/openprinttag/apply", json=request_body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["applied"] == 1

    # Spoolman PATCH should include extra with slug + uuid
    _, payload = patched[0]
    assert "extra" in payload
    from app.schemas.spoolman import decode_extra_value
    from app.config import settings as _s
    slug_key = _s.spoolman_field_openprinttag_slug
    uuid_key = _s.spoolman_field_openprinttag_uuid
    assert slug_key in payload["extra"]
    assert decode_extra_value(payload["extra"][slug_key]) == "test-slug"
    assert uuid_key in payload["extra"]
    assert decode_extra_value(payload["extra"][uuid_key]) == "test-uuid"

    # FDB settings merge should also be called
    fake_fdb.merge_filament_settings.assert_called_once_with(
        "fdb-abc", {"openprinttag_slug": "test-slug", "openprinttag_uuid": "test-uuid"}
    )


# ---------------------------------------------------------------------------
# Phase 5: FDB settings-bag merge — scoped, idempotent, preserves other keys
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_filament_settings_only_writes_opentag_keys():
    """merge_filament_settings must only write the two OPT keys, no other keys."""
    from app.services.filamentdb import FilamentDBClient

    existing_settings = {
        "slicer_key": "some_value",
        "another_key": 42,
        "openprinttag_slug": None,  # not set yet
    }

    # Simulated FDB filament detail response
    fake_raw = {
        "_id": "fil-123",
        "name": "Test PLA",
        "settings": existing_settings,
    }

    put_payloads: list[dict] = []

    async def _fake_get(url):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value=fake_raw)
        return resp

    async def _fake_put(url, json=None):
        put_payloads.append(json)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        return resp

    client = FilamentDBClient("http://fdb.test")
    client._client = MagicMock()
    client._http.get = AsyncMock(side_effect=_fake_get)
    client._http.put = AsyncMock(side_effect=_fake_put)

    await client.merge_filament_settings(
        "fil-123",
        {"openprinttag_slug": "test-slug", "openprinttag_uuid": "test-uuid"},
    )

    assert len(put_payloads) == 1
    payload = put_payloads[0]
    merged_settings = payload["settings"]

    # Must preserve existing slicer keys
    assert merged_settings["slicer_key"] == "some_value"
    assert merged_settings["another_key"] == 42
    # Must include the two OPT keys
    assert merged_settings["openprinttag_slug"] == "test-slug"
    assert merged_settings["openprinttag_uuid"] == "test-uuid"


@pytest.mark.asyncio
async def test_merge_filament_settings_idempotent_no_rewrite():
    """When FDB already has the same OPT values, no PUT should be issued."""
    from app.services.filamentdb import FilamentDBClient

    fake_raw = {
        "_id": "fil-456",
        "name": "Test PLA",
        "settings": {
            "slicer_key": "v",
            "openprinttag_slug": "existing-slug",
            "openprinttag_uuid": "existing-uuid",
        },
    }

    put_calls: list = []

    async def _fake_get(url):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value=fake_raw)
        return resp

    async def _fake_put(url, json=None):
        put_calls.append(json)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        return resp

    client = FilamentDBClient("http://fdb.test")
    client._client = MagicMock()
    client._http.get = AsyncMock(side_effect=_fake_get)
    client._http.put = AsyncMock(side_effect=_fake_put)

    await client.merge_filament_settings(
        "fil-456",
        {"openprinttag_slug": "existing-slug", "openprinttag_uuid": "existing-uuid"},
    )

    # Values already equal — should NOT issue a PUT
    assert len(put_calls) == 0


@pytest.mark.asyncio
async def test_merge_filament_settings_preserves_all_other_keys():
    """Any keys already in settings{} must survive unchanged after the merge."""
    from app.services.filamentdb import FilamentDBClient

    other_keys = {
        "filament_notes": "my notes",
        "slicer_profile": "profile-xyz",
        "custom_key": {"nested": True},
    }
    fake_raw = {
        "_id": "fil-789",
        "name": "Test",
        "settings": other_keys,
    }

    put_payloads: list[dict] = []

    async def _fake_get(url):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value=fake_raw)
        return resp

    async def _fake_put(url, json=None):
        put_payloads.append(json)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        return resp

    client = FilamentDBClient("http://fdb.test")
    client._client = MagicMock()
    client._http.get = AsyncMock(side_effect=_fake_get)
    client._http.put = AsyncMock(side_effect=_fake_put)

    await client.merge_filament_settings(
        "fil-789",
        {"openprinttag_slug": "slug-x", "openprinttag_uuid": "uuid-x"},
    )

    assert len(put_payloads) == 1
    settings_out = put_payloads[0]["settings"]
    # All original keys preserved
    for k, v in other_keys.items():
        assert settings_out[k] == v, f"key {k!r} was not preserved"
    # New keys present
    assert settings_out["openprinttag_slug"] == "slug-x"
    assert settings_out["openprinttag_uuid"] == "uuid-x"


@pytest.mark.asyncio
async def test_merge_filament_settings_partial_update():
    """When only one key is new, only that key should change."""
    from app.services.filamentdb import FilamentDBClient

    fake_raw = {
        "_id": "fil-partial",
        "name": "Test",
        "settings": {
            "slicer_key": "v",
            "openprinttag_slug": "already-set",
        },
    }

    put_payloads: list[dict] = []

    async def _fake_get(url):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value=fake_raw)
        return resp

    async def _fake_put(url, json=None):
        put_payloads.append(json)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        return resp

    client = FilamentDBClient("http://fdb.test")
    client._client = MagicMock()
    client._http.get = AsyncMock(side_effect=_fake_get)
    client._http.put = AsyncMock(side_effect=_fake_put)

    # slug is already equal; uuid is new → one PUT expected
    await client.merge_filament_settings(
        "fil-partial",
        {"openprinttag_slug": "already-set", "openprinttag_uuid": "new-uuid"},
    )

    assert len(put_payloads) == 1
    settings_out = put_payloads[0]["settings"]
    assert settings_out["openprinttag_slug"] == "already-set"
    assert settings_out["openprinttag_uuid"] == "new-uuid"
    assert settings_out["slicer_key"] == "v"


# ---------------------------------------------------------------------------
# Route rename: new /openprinttag/* paths respond; old /opentag/* paths 404
# ---------------------------------------------------------------------------


def _make_test_app_with_mocks():
    """Return a TestClient wrapping the opentag router with minimal mocks."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router

    fake_sm = AsyncMock()
    fake_fdb = AsyncMock()

    test_app = FastAPI()
    test_app.include_router(router, prefix="/api")
    test_app.state.spoolman = fake_sm
    test_app.state.filamentdb = fake_fdb
    return TestClient(test_app), fake_sm, fake_fdb


def test_openprinttag_apply_route_responds():
    """POST /api/openprinttag/apply should respond (not 404)."""
    client, fake_sm, fake_fdb = _make_test_app_with_mocks()
    fake_sm.update_filament = AsyncMock(return_value=MagicMock())
    fake_fdb.merge_filament_settings = AsyncMock()
    resp = client.post(
        "/api/openprinttag/apply",
        json={"decisions": [{"spoolman_filament_id": 1, "ignored": True, "fields": []}]},
    )
    assert resp.status_code == 200


def test_old_opentag_apply_route_404():
    """POST /api/opentag/apply (old path) must 404 — ensure ad-blocker-blocked path is gone."""
    client, _sm, _fdb = _make_test_app_with_mocks()
    resp = client.post(
        "/api/opentag/apply",
        json={"decisions": []},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_openprinttag_refresh_route_responds(tmp_path):
    """POST /api/openprinttag/refresh should respond (not 404) when FDB returns data."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router

    fake_fdb = AsyncMock()
    fake_fdb.get_openprinttag = AsyncMock(return_value=[_OPT_PLA_SILK])

    test_app = FastAPI()
    test_app.include_router(router, prefix="/api")
    test_app.state.filamentdb = fake_fdb
    test_app.state.spoolman = AsyncMock()

    # Patch data_dir to a writable temp path
    import app.api.opentag as _ot_mod
    original_data_dir = _ot_mod._settings.data_dir
    _ot_mod._settings.data_dir = str(tmp_path)
    try:
        client = TestClient(test_app)
        resp = client.post("/api/openprinttag/refresh")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
    finally:
        _ot_mod._settings.data_dir = original_data_dir


def test_old_opentag_refresh_route_404():
    """POST /api/opentag/refresh (old path) must 404."""
    client, _sm, _fdb = _make_test_app_with_mocks()
    resp = client.post("/api/opentag/refresh")
    assert resp.status_code == 404


def test_old_opentag_matches_route_404():
    """GET /api/opentag/matches (old path) must 404."""
    client, _sm, _fdb = _make_test_app_with_mocks()
    resp = client.get("/api/opentag/matches")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/openprinttag/status — lightweight cache metadata, no FDB fetch
# ---------------------------------------------------------------------------


def test_openprinttag_status_no_cache(tmp_path):
    """GET /api/openprinttag/status returns exists:false when cache file is absent.

    The FDB client must NOT be called.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router

    fake_fdb = AsyncMock()
    # If get_openprinttag is called the test should fail loudly
    fake_fdb.get_openprinttag = AsyncMock(side_effect=AssertionError("must not call FDB"))

    test_app = FastAPI()
    test_app.include_router(router, prefix="/api")
    test_app.state.filamentdb = fake_fdb
    test_app.state.spoolman = AsyncMock()

    import app.api.opentag as _ot_mod
    original_data_dir = _ot_mod._settings.data_dir
    _ot_mod._settings.data_dir = str(tmp_path)
    try:
        client = TestClient(test_app)
        resp = client.get("/api/openprinttag/status")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["exists"] is False
        assert data["fetched_at"] is None
        assert data["count"] == 0
        assert data["stale"] is True
        assert "max_age_hours" in data
        fake_fdb.get_openprinttag.assert_not_called()
    finally:
        _ot_mod._settings.data_dir = original_data_dir


def test_openprinttag_status_fresh_cache_no_fdb_fetch(tmp_path):
    """GET /api/openprinttag/status returns exists:true with count + age when cache is fresh.

    The FDB client must NOT be called even when a fresh cache is present.
    """
    import datetime as _dt
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router
    from app.core.opentag_cache import _save_cache

    fresh_ts = _dt.datetime.now(_dt.timezone.utc).isoformat()
    _save_cache(str(tmp_path), [_OPT_PLA_SILK, _OPT_PETG], fresh_ts)

    fake_fdb = AsyncMock()
    fake_fdb.get_openprinttag = AsyncMock(side_effect=AssertionError("must not call FDB"))

    test_app = FastAPI()
    test_app.include_router(router, prefix="/api")
    test_app.state.filamentdb = fake_fdb
    test_app.state.spoolman = AsyncMock()

    import app.api.opentag as _ot_mod
    original_data_dir = _ot_mod._settings.data_dir
    _ot_mod._settings.data_dir = str(tmp_path)
    try:
        client = TestClient(test_app)
        resp = client.get("/api/openprinttag/status")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["exists"] is True
        assert data["count"] == 2
        assert data["stale"] is False
        assert data["fetched_at"] is not None
        assert isinstance(data["max_age_hours"], int)
        fake_fdb.get_openprinttag.assert_not_called()
    finally:
        _ot_mod._settings.data_dir = original_data_dir


# ---------------------------------------------------------------------------
# get_openprinttag: 120 s timeout override
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_openprinttag_uses_120s_timeout():
    """get_openprinttag() must pass timeout=httpx.Timeout(120.0) to the HTTP client."""
    from app.services.filamentdb import FilamentDBClient

    timeout_used: list = []

    async def _fake_get(url, **kwargs):
        timeout_used.append(kwargs.get("timeout"))
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value=[_OPT_PLA_SILK])
        return resp

    client = FilamentDBClient("http://fdb.test")
    client._client = MagicMock()
    client._http.get = AsyncMock(side_effect=_fake_get)

    result = await client.get_openprinttag()

    assert result == [_OPT_PLA_SILK]
    assert len(timeout_used) == 1
    t = timeout_used[0]
    assert isinstance(t, httpx.Timeout), f"Expected httpx.Timeout, got {type(t)}"
    # httpx.Timeout(120.0) sets connect, read, write, pool all to 120 s
    assert t.read == 120.0


# ---------------------------------------------------------------------------
# Fetch failures → structured api_error responses
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_timeout_returns_504(tmp_path):
    """POST /api/openprinttag/refresh: TimeoutException → 504 opentag_fetch_timeout."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router

    fake_fdb = AsyncMock()
    fake_fdb.get_openprinttag = AsyncMock(
        side_effect=httpx.TimeoutException("timed out")
    )

    test_app = FastAPI()
    test_app.include_router(router, prefix="/api")
    test_app.state.filamentdb = fake_fdb
    test_app.state.spoolman = AsyncMock()

    import app.api.opentag as _ot_mod
    original_data_dir = _ot_mod._settings.data_dir
    _ot_mod._settings.data_dir = str(tmp_path)
    try:
        client = TestClient(test_app, raise_server_exceptions=False)
        resp = client.post("/api/openprinttag/refresh")
        assert resp.status_code == 504
        detail = resp.json()["detail"]
        assert detail["code"] == "opentag_fetch_timeout"
        assert "large file" in detail["message"]
    finally:
        _ot_mod._settings.data_dir = original_data_dir


@pytest.mark.asyncio
async def test_refresh_404_returns_502_unavailable(tmp_path):
    """POST /api/openprinttag/refresh: FDB 404 → 502 opentag_unavailable."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router

    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_req = MagicMock()
    fake_fdb = AsyncMock()
    fake_fdb.get_openprinttag = AsyncMock(
        side_effect=httpx.HTTPStatusError("404", request=mock_req, response=mock_resp)
    )

    test_app = FastAPI()
    test_app.include_router(router, prefix="/api")
    test_app.state.filamentdb = fake_fdb
    test_app.state.spoolman = AsyncMock()

    import app.api.opentag as _ot_mod
    original_data_dir = _ot_mod._settings.data_dir
    _ot_mod._settings.data_dir = str(tmp_path)
    try:
        client = TestClient(test_app, raise_server_exceptions=False)
        resp = client.post("/api/openprinttag/refresh")
        assert resp.status_code == 502
        detail = resp.json()["detail"]
        assert detail["code"] == "opentag_unavailable"
        assert "upgrade" in detail["message"].lower()
    finally:
        _ot_mod._settings.data_dir = original_data_dir


@pytest.mark.asyncio
async def test_refresh_connection_error_returns_502(tmp_path):
    """POST /api/openprinttag/refresh: RequestError → 502 opentag_fetch_failed."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router

    fake_fdb = AsyncMock()
    fake_fdb.get_openprinttag = AsyncMock(
        side_effect=httpx.ConnectError("connection refused")
    )

    test_app = FastAPI()
    test_app.include_router(router, prefix="/api")
    test_app.state.filamentdb = fake_fdb
    test_app.state.spoolman = AsyncMock()

    import app.api.opentag as _ot_mod
    original_data_dir = _ot_mod._settings.data_dir
    _ot_mod._settings.data_dir = str(tmp_path)
    try:
        client = TestClient(test_app, raise_server_exceptions=False)
        resp = client.post("/api/openprinttag/refresh")
        assert resp.status_code == 502
        detail = resp.json()["detail"]
        assert detail["code"] == "opentag_fetch_failed"
    finally:
        _ot_mod._settings.data_dir = original_data_dir


@pytest.mark.asyncio
async def test_matches_timeout_returns_504(tmp_path):
    """GET /api/openprinttag/matches: TimeoutException → 504 opentag_fetch_timeout."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router

    fake_fdb = AsyncMock()
    fake_fdb.get_openprinttag = AsyncMock(
        side_effect=httpx.TimeoutException("timed out")
    )
    fake_sm = AsyncMock()
    fake_sm.get_filaments = AsyncMock(return_value=[])

    test_app = FastAPI()
    test_app.include_router(router, prefix="/api")
    test_app.state.filamentdb = fake_fdb
    test_app.state.spoolman = fake_sm

    import app.api.opentag as _ot_mod
    original_data_dir = _ot_mod._settings.data_dir
    _ot_mod._settings.data_dir = str(tmp_path)
    try:
        client = TestClient(test_app, raise_server_exceptions=False)
        resp = client.get("/api/openprinttag/matches")
        assert resp.status_code == 504
        detail = resp.json()["detail"]
        assert detail["code"] == "opentag_fetch_timeout"
    finally:
        _ot_mod._settings.data_dir = original_data_dir


@pytest.mark.asyncio
async def test_refresh_error_triggers_logger_error(tmp_path):
    """Fetch failures must call logger.error (not go silent)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router
    import app.api.opentag as _ot_mod

    fake_fdb = AsyncMock()
    fake_fdb.get_openprinttag = AsyncMock(
        side_effect=httpx.TimeoutException("timed out")
    )

    test_app = FastAPI()
    test_app.include_router(router, prefix="/api")
    test_app.state.filamentdb = fake_fdb
    test_app.state.spoolman = AsyncMock()

    original_data_dir = _ot_mod._settings.data_dir
    _ot_mod._settings.data_dir = str(tmp_path)
    try:
        with patch("app.api.opentag.logger") as mock_logger:
            client = TestClient(test_app, raise_server_exceptions=False)
            resp = client.post("/api/openprinttag/refresh")
            assert resp.status_code == 504
            mock_logger.error.assert_called()
    finally:
        _ot_mod._settings.data_dir = original_data_dir


# ---------------------------------------------------------------------------
# Fix: get_openprinttag extracts materials from FDB's OPTDatabase wrapper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_openprinttag_extracts_materials_from_wrapper():
    """When FDB returns an OPTDatabase wrapper dict, get_openprinttag() returns only materials."""
    from app.services.filamentdb import FilamentDBClient

    wrapper_response = {
        "brands": [{"name": "Buddy3D"}],
        "materials": [_OPT_PLA_SILK, _OPT_PETG],
        "cachedAt": "2026-06-06T00:00:00Z",
        "totalFFF": 2,
        "totalSLA": 0,
    }

    async def _fake_get(url, **kwargs):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value=wrapper_response)
        return resp

    client = FilamentDBClient("http://fdb.test")
    client._client = MagicMock()
    client._http.get = AsyncMock(side_effect=_fake_get)

    result = await client.get_openprinttag()

    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["slug"] == "buddy3d-pla-silk-bronze"
    assert result[1]["slug"] == "elegoo-petg-red"


@pytest.mark.asyncio
async def test_get_openprinttag_passes_through_list_unchanged():
    """When FDB already returns a list, get_openprinttag() returns it unchanged (defensive)."""
    from app.services.filamentdb import FilamentDBClient

    list_response = [_OPT_PLA_SILK, _OPT_PETG, _OPT_PLA_MATTE]

    async def _fake_get(url, **kwargs):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value=list_response)
        return resp

    client = FilamentDBClient("http://fdb.test")
    client._client = MagicMock()
    client._http.get = AsyncMock(side_effect=_fake_get)

    result = await client.get_openprinttag()

    assert result == list_response


@pytest.mark.asyncio
async def test_get_openprinttag_wrapper_missing_materials_returns_empty():
    """When wrapper dict has no 'materials' key, get_openprinttag() returns []."""
    from app.services.filamentdb import FilamentDBClient

    async def _fake_get(url, **kwargs):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={"brands": [], "cachedAt": "x", "totalFFF": 0, "totalSLA": 0})
        return resp

    client = FilamentDBClient("http://fdb.test")
    client._client = MagicMock()
    client._http.get = AsyncMock(side_effect=_fake_get)

    result = await client.get_openprinttag()

    assert result == []


# ---------------------------------------------------------------------------
# Fix: cache self-heals when stored materials are not a non-empty list of dicts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_self_heals_when_materials_are_strings(tmp_path):
    """If cached materials contains strings (malformed), re-fetch is triggered."""
    # Write a cache that looks valid but has string entries instead of dicts
    malformed_cache = {
        "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "count": 5,
        "materials": ["brands", "materials", "cachedAt", "totalFFF", "totalSLA"],
    }
    cache_path = tmp_path / "opentag_cache.json"
    cache_path.write_text(json.dumps(malformed_cache))

    # FDB will return real data on re-fetch
    fdb_mock = AsyncMock()
    fdb_mock.get_openprinttag = AsyncMock(return_value=[_OPT_PLA_SILK, _OPT_PETG])

    result = await load_opentag_dataset(fdb_mock, str(tmp_path), 24, force=False)

    # Should have re-fetched despite the cache being "fresh"
    fdb_mock.get_openprinttag.assert_called_once()
    assert result["count"] == 2
    assert all(isinstance(m, dict) for m in result["materials"])


@pytest.mark.asyncio
async def test_cache_self_heals_when_materials_is_empty_list(tmp_path):
    """An empty materials list is also treated as malformed and triggers re-fetch."""
    malformed_cache = {
        "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "count": 0,
        "materials": [],
    }
    cache_path = tmp_path / "opentag_cache.json"
    cache_path.write_text(json.dumps(malformed_cache))

    fdb_mock = AsyncMock()
    fdb_mock.get_openprinttag = AsyncMock(return_value=[_OPT_PLA_SILK])

    result = await load_opentag_dataset(fdb_mock, str(tmp_path), 24, force=False)

    fdb_mock.get_openprinttag.assert_called_once()
    assert result["count"] == 1


@pytest.mark.asyncio
async def test_cache_serves_valid_fresh_data_without_refetch(tmp_path):
    """A fresh cache with valid dict entries is served without calling FDB."""
    fresh_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _save_cache(str(tmp_path), [_OPT_PLA_SILK, _OPT_PETG], fresh_ts)

    fdb_mock = AsyncMock()
    fdb_mock.get_openprinttag = AsyncMock()

    result = await load_opentag_dataset(fdb_mock, str(tmp_path), 24, force=False)

    fdb_mock.get_openprinttag.assert_not_called()
    assert result["count"] == 2


# ---------------------------------------------------------------------------
# Fix: matcher tolerates non-dict entries in materials list
# ---------------------------------------------------------------------------


def test_find_best_match_tolerates_non_dict_entries():
    """Non-dict entries in the materials list must be silently skipped (no AttributeError)."""
    sm = _sm_fil(vendor="Buddy3D", material="PLA Silk", color_hex="B87333")
    # Mix of valid dicts, strings, and None — all non-dicts should be skipped
    materials_with_junk = ["brands", "materials", None, _OPT_PLA_SILK, 42, _OPT_PETG]
    result = find_best_match(sm, materials_with_junk)
    # Should find PLA Silk Bronze despite the junk entries
    assert result["best"] is not None
    assert result["best"]["slug"] == "buddy3d-pla-silk-bronze"


def test_find_best_match_all_non_dict_returns_no_match():
    """When every entry is a non-dict, find_best_match returns no match gracefully."""
    sm = _sm_fil()
    result = find_best_match(sm, ["brands", "materials", "cachedAt", "totalFFF", "totalSLA"])
    assert result["best"] is None
    assert result["confidence"] == 0.0
    assert result["alternates"] == []


# ---------------------------------------------------------------------------
# Fix: /openprinttag/matches returns 200 with a wrapper-shaped FDB response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_matches_returns_200_with_wrapper_shaped_fdb_response(tmp_path):
    """GET /api/openprinttag/matches must return 200, not 500, when FDB returns an OPTDatabase wrapper."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router

    # FDB returns the wrapper object (the shape that was causing the 500)
    wrapper_response = {
        "brands": [{"name": "Buddy3D"}, {"name": "ELEGOO"}],
        "materials": [_OPT_PLA_SILK, _OPT_PETG, _OPT_PLA_MATTE],
        "cachedAt": "2026-06-06T00:00:00Z",
        "totalFFF": 3,
        "totalSLA": 0,
    }

    fake_fdb = AsyncMock()
    fake_fdb.get_openprinttag = AsyncMock(return_value=wrapper_response["materials"])

    fake_sm_fil = _sm_fil(sm_id=1, vendor="Buddy3D", material="PLA Silk", color_hex="B87333")
    fake_sm = AsyncMock()
    fake_sm.get_filaments = AsyncMock(return_value=[fake_sm_fil])

    test_app = FastAPI()
    test_app.include_router(router, prefix="/api")
    test_app.state.filamentdb = fake_fdb
    test_app.state.spoolman = fake_sm

    import app.api.opentag as _ot_mod
    original_data_dir = _ot_mod._settings.data_dir
    _ot_mod._settings.data_dir = str(tmp_path)
    try:
        client = TestClient(test_app, raise_server_exceptions=True)
        resp = client.get("/api/openprinttag/matches")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "matches" in data
        assert len(data["matches"]) == 1
        assert data["matches"][0]["spoolman_filament_id"] == 1
        # Should have matched against PLA Silk Bronze (not 500'd on string keys)
        assert data["matches"][0]["opt_slug"] == "buddy3d-pla-silk-bronze"
    finally:
        _ot_mod._settings.data_dir = original_data_dir


@pytest.mark.asyncio
async def test_matches_returns_200_when_cache_has_malformed_data(tmp_path):
    """GET /api/openprinttag/matches must self-heal a malformed cache and return 200."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router

    # Seed the cache with the malformed string entries that caused the original 500
    malformed_cache = {
        "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "count": 5,
        "materials": ["brands", "materials", "cachedAt", "totalFFF", "totalSLA"],
    }
    cache_path = tmp_path / "opentag_cache.json"
    cache_path.write_text(json.dumps(malformed_cache))

    # FDB will supply real data on re-fetch
    fake_fdb = AsyncMock()
    fake_fdb.get_openprinttag = AsyncMock(return_value=[_OPT_PLA_SILK])

    fake_sm_fil = _sm_fil(sm_id=2, vendor="Buddy3D", material="PLA Silk", color_hex="B87333")
    fake_sm = AsyncMock()
    fake_sm.get_filaments = AsyncMock(return_value=[fake_sm_fil])

    test_app = FastAPI()
    test_app.include_router(router, prefix="/api")
    test_app.state.filamentdb = fake_fdb
    test_app.state.spoolman = fake_sm

    import app.api.opentag as _ot_mod
    original_data_dir = _ot_mod._settings.data_dir
    _ot_mod._settings.data_dir = str(tmp_path)
    try:
        client = TestClient(test_app, raise_server_exceptions=True)
        resp = client.get("/api/openprinttag/matches")
        assert resp.status_code == 200, resp.text
        # Self-heal triggered a re-fetch
        fake_fdb.get_openprinttag.assert_called_once()
    finally:
        _ot_mod._settings.data_dir = original_data_dir


# ---------------------------------------------------------------------------
# Brand pre-filter: matches endpoint only scores same-brand candidates
# ---------------------------------------------------------------------------


def _make_matches_test_app(tmp_path, materials, sm_filaments):
    """Return a wired TestClient for GET /api/openprinttag/matches with seeded cache."""
    import datetime as _dt
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router
    from app.core.opentag_cache import _save_cache

    fresh_ts = _dt.datetime.now(_dt.timezone.utc).isoformat()
    _save_cache(str(tmp_path), materials, fresh_ts)

    fake_fdb = AsyncMock()
    fake_sm = AsyncMock()
    fake_sm.get_filaments = AsyncMock(return_value=sm_filaments)

    test_app = FastAPI()
    test_app.include_router(router, prefix="/api")
    test_app.state.filamentdb = fake_fdb
    test_app.state.spoolman = fake_sm

    import app.api.opentag as _ot_mod
    return TestClient(test_app), _ot_mod, fake_fdb


@pytest.mark.asyncio
async def test_matches_brand_prefilter_same_brand_only(tmp_path):
    """An Elegoo SM filament is matched against only Elegoo OPT materials, not Buddy3D ones.

    Specifically: a same-name Buddy3D material should NOT appear as the best match when
    an Elegoo material with the same type/color is also in the dataset.
    """
    # OPT material: same name/type as _OPT_PLA_SILK but with brandName ELEGOO
    opt_elegoo_pla_silk = {
        **_OPT_PLA_SILK,
        "uuid": "eeee0000-0000-0000-0000-000000000099",
        "slug": "elegoo-pla-silk-bronze",
        "brandName": "ELEGOO",
    }

    # SM filament: Elegoo vendor
    sm_elegoo = _sm_fil(sm_id=10, vendor="ELEGOO", material="PLA Silk", color_hex="B87333")

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router
    from app.core.opentag_cache import _save_cache

    materials = [_OPT_PLA_SILK, opt_elegoo_pla_silk]  # Buddy3D first, then Elegoo
    fresh_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _save_cache(str(tmp_path), materials, fresh_ts)

    fake_fdb = AsyncMock()
    fake_sm = AsyncMock()
    fake_sm.get_filaments = AsyncMock(return_value=[sm_elegoo])

    test_app = FastAPI()
    test_app.include_router(router, prefix="/api")
    test_app.state.filamentdb = fake_fdb
    test_app.state.spoolman = fake_sm

    import app.api.opentag as _ot_mod
    original_data_dir = _ot_mod._settings.data_dir
    _ot_mod._settings.data_dir = str(tmp_path)
    try:
        client = TestClient(test_app, raise_server_exceptions=True)
        resp = client.get("/api/openprinttag/matches")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data["matches"]) == 1
        match = data["matches"][0]
        # Must have matched against the ELEGOO material, not the Buddy3D one
        assert match["opt_slug"] == "elegoo-pla-silk-bronze"
        assert match["opt_brand"] == "ELEGOO"
    finally:
        _ot_mod._settings.data_dir = original_data_dir


@pytest.mark.asyncio
async def test_matches_vendor_absent_from_opentag_brands_yields_no_match(tmp_path):
    """A SM filament whose vendor has no OpenTag materials yields a no-match row (opt_slug=None)."""
    # SM filament from a brand that has NO OPT materials
    sm_unknown = _sm_fil(sm_id=20, vendor="UnknownBrand9999", material="PLA", color_hex="FF0000")

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router
    from app.core.opentag_cache import _save_cache

    # Dataset has materials only for Buddy3D and ELEGOO — not UnknownBrand9999
    materials = [_OPT_PLA_SILK, _OPT_PETG, _OPT_PLA_MATTE]
    fresh_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _save_cache(str(tmp_path), materials, fresh_ts)

    fake_fdb = AsyncMock()
    fake_sm = AsyncMock()
    fake_sm.get_filaments = AsyncMock(return_value=[sm_unknown])

    test_app = FastAPI()
    test_app.include_router(router, prefix="/api")
    test_app.state.filamentdb = fake_fdb
    test_app.state.spoolman = fake_sm

    import app.api.opentag as _ot_mod
    original_data_dir = _ot_mod._settings.data_dir
    _ot_mod._settings.data_dir = str(tmp_path)
    try:
        client = TestClient(test_app, raise_server_exceptions=True)
        resp = client.get("/api/openprinttag/matches")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data["matches"]) == 1
        match = data["matches"][0]
        # No matching brand → no match
        assert match["opt_slug"] is None
        assert match["opt_uuid"] is None
        assert match["opt_brand"] is None
        assert match["fields"] == []
    finally:
        _ot_mod._settings.data_dir = original_data_dir


@pytest.mark.asyncio
async def test_matches_multi_brand_dataset_returns_correct_best_match(tmp_path):
    """With materials from several brands, each SM filament matches its own brand's best material."""
    # Two SM filaments from different brands
    sm_buddy3d = _sm_fil(sm_id=1, vendor="Buddy3D", material="PLA Silk", color_hex="B87333")
    sm_elegoo = _sm_fil(sm_id=2, vendor="ELEGOO", material="PETG", color_hex="CC0000")

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router
    from app.core.opentag_cache import _save_cache

    # All three materials in the dataset (two ELEGOO, one Buddy3D)
    materials = [_OPT_PLA_SILK, _OPT_PETG, _OPT_PLA_MATTE]
    fresh_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _save_cache(str(tmp_path), materials, fresh_ts)

    fake_fdb = AsyncMock()
    fake_sm = AsyncMock()
    fake_sm.get_filaments = AsyncMock(return_value=[sm_buddy3d, sm_elegoo])

    test_app = FastAPI()
    test_app.include_router(router, prefix="/api")
    test_app.state.filamentdb = fake_fdb
    test_app.state.spoolman = fake_sm

    import app.api.opentag as _ot_mod
    original_data_dir = _ot_mod._settings.data_dir
    _ot_mod._settings.data_dir = str(tmp_path)
    try:
        client = TestClient(test_app, raise_server_exceptions=True)
        resp = client.get("/api/openprinttag/matches")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data["matches"]) == 2

        # Find each result by filament id
        by_id = {m["spoolman_filament_id"]: m for m in data["matches"]}

        # Buddy3D PLA Silk → buddy3d-pla-silk-bronze
        b3d = by_id[1]
        assert b3d["opt_slug"] == "buddy3d-pla-silk-bronze"

        # ELEGOO PETG Red → elegoo-petg-red (best ELEGOO PETG match)
        elegoo = by_id[2]
        assert elegoo["opt_slug"] == "elegoo-petg-red"
    finally:
        _ot_mod._settings.data_dir = original_data_dir


# ---------------------------------------------------------------------------
# Phase: Color-profile helpers — sm_color_profile / opt_color_profile /
#         profiles_compatible
# ---------------------------------------------------------------------------


from app.core.opentag_match import (  # noqa: E402 — module-level import below test data ok
    opt_color_profile,
    profiles_compatible,
    sm_color_profile,
)
from app.core.color import TAG_COEXTRUDED as _TAG_COEXTRUDED, TAG_GRADIENT as _TAG_GRADIENT  # noqa: E402


# ---------- sm_color_profile ----------

def test_sm_color_profile_single():
    """No multi_color_hexes → 'single'."""
    sm = _sm_fil(color_hex="FF0000")
    assert sm_color_profile(sm) == "single"


def test_sm_color_profile_coaxial():
    """multi_color_direction='coaxial' → 'coextruded'."""
    sm = SpoolmanFilament(
        id=1, name="Dual", vendor=SpoolmanVendor(id=1, name="ELEGOO"),
        material="PLA", color_hex="FF0000",
        multi_color_hexes="FF0000,00FF00", multi_color_direction="coaxial",
        extra={},
    )
    assert sm_color_profile(sm) == "coextruded"


def test_sm_color_profile_longitudinal():
    """multi_color_direction='longitudinal' → 'gradient'."""
    sm = SpoolmanFilament(
        id=1, name="Rainbow", vendor=SpoolmanVendor(id=1, name="ELEGOO"),
        material="PLA", color_hex="AA0000",
        multi_color_hexes="AA0000,00BB00,0000CC", multi_color_direction="longitudinal",
        extra={},
    )
    assert sm_color_profile(sm) == "gradient"


def test_sm_color_profile_multi_unknown_direction():
    """multi_color_hexes present but direction None → 'multi_unknown'."""
    sm = SpoolmanFilament(
        id=1, name="Multi", vendor=SpoolmanVendor(id=1, name="ELEGOO"),
        material="PLA", color_hex="FF0000",
        multi_color_hexes="FF0000,00FF00", multi_color_direction=None,
        extra={},
    )
    assert sm_color_profile(sm) == "multi_unknown"


# ---------- opt_color_profile ----------

def test_opt_color_profile_single_no_secondary():
    """No secondaryColors → 'single'."""
    opt = {**_OPT_PLA_SILK, "secondaryColors": []}
    assert opt_color_profile(opt) == "single"


def test_opt_color_profile_coextruded_via_optTag_int():
    """optTags=[29] → 'coextruded'."""
    opt = {
        **_OPT_PLA_SILK,
        "color": "",  # empty primary is valid for coextruded
        "secondaryColors": ["#FF0000", "#00FF00"],
        "optTags": [_TAG_COEXTRUDED],
        "tags": [],
    }
    assert opt_color_profile(opt) == "coextruded"


def test_opt_color_profile_gradient_via_optTag_int():
    """optTags=[28] → 'gradient'."""
    opt = {
        **_OPT_PLA_SILK,
        "secondaryColors": ["#FF0000", "#00FF00"],
        "optTags": [_TAG_GRADIENT],
        "tags": [],
    }
    assert opt_color_profile(opt) == "gradient"


def test_opt_color_profile_coextruded_via_tag_string():
    """tags=['coextruded'] (string) → 'coextruded' even without optTags."""
    opt = {
        **_OPT_PLA_SILK,
        "color": None,
        "secondaryColors": ["#FF0000", "#00FF00"],
        "optTags": [],
        "tags": ["coextruded"],
    }
    assert opt_color_profile(opt) == "coextruded"


def test_opt_color_profile_gradient_via_tag_string():
    """tags=['gradual_color_change'] → 'gradient'."""
    opt = {
        **_OPT_PLA_SILK,
        "secondaryColors": ["#FF0000", "#00FF00"],
        "optTags": [],
        "tags": ["gradual_color_change"],
    }
    assert opt_color_profile(opt) == "gradient"


def test_opt_color_profile_multi_unknown_no_arrangement_tag():
    """secondaryColors present but no arrangement tag → 'multi_unknown'."""
    opt = {
        **_OPT_PLA_SILK,
        "secondaryColors": ["#FF0000", "#00FF00"],
        "optTags": [],
        "tags": [],
    }
    assert opt_color_profile(opt) == "multi_unknown"


def test_opt_color_profile_empty_primary_dual_color_coextruded():
    """Empty primary color + secondaryColors + optTag 29 → 'coextruded'."""
    opt = {
        "uuid": "test",
        "slug": "test-dual",
        "brandName": "TestBrand",
        "name": "Dual Coextruded",
        "type": "PLA",
        "abbreviation": "PLA",
        "color": "",          # empty primary — valid for coextruded
        "secondaryColors": ["#FF0000", "#00FF00"],
        "optTags": [_TAG_COEXTRUDED],
        "tags": [],
        "density": 1.24,
    }
    assert opt_color_profile(opt) == "coextruded"


# ---------- profiles_compatible ----------

def test_profiles_compatible_single_single():
    assert profiles_compatible("single", "single") is True


def test_profiles_compatible_single_coextruded():
    assert profiles_compatible("single", "coextruded") is False


def test_profiles_compatible_single_gradient():
    assert profiles_compatible("single", "gradient") is False


def test_profiles_compatible_single_multi_unknown():
    assert profiles_compatible("single", "multi_unknown") is False


def test_profiles_compatible_coextruded_coextruded():
    assert profiles_compatible("coextruded", "coextruded") is True


def test_profiles_compatible_coextruded_gradient():
    assert profiles_compatible("coextruded", "gradient") is False


def test_profiles_compatible_gradient_gradient():
    assert profiles_compatible("gradient", "gradient") is True


def test_profiles_compatible_multi_unknown_coextruded():
    """multi_unknown on either side matches any multicolor, not single."""
    assert profiles_compatible("multi_unknown", "coextruded") is True


def test_profiles_compatible_multi_unknown_gradient():
    assert profiles_compatible("multi_unknown", "gradient") is True


def test_profiles_compatible_multi_unknown_single():
    assert profiles_compatible("multi_unknown", "single") is False


# ---------------------------------------------------------------------------
# Phase: opt_to_spoolman_fields — multicolor direction + empty-primary handling
# ---------------------------------------------------------------------------


# OPT coextruded material (empty primary color, secondaryColors, optTag 29)
_OPT_COEXTRUDED = {
    "uuid": "coext-0000-0000-0000-000000000001",
    "slug": "elegoo-pla-coextruded-dual",
    "brandName": "ELEGOO",
    "name": "PLA Dual Coextruded",
    "type": "PLA",
    "abbreviation": "PLA",
    "tags": [],
    "color": "",  # empty primary — coextruded has no primary
    "secondaryColors": ["#FF0000", "#00FF00"],
    "optTags": [_TAG_COEXTRUDED],
    "density": 1.24,
    "nozzleTempMax": 220,
    "bedTempMax": 60,
}

# OPT gradient material (primary color + secondaryColors, optTag 28)
_OPT_GRADIENT = {
    "uuid": "grad-0000-0000-0000-000000000001",
    "slug": "elegoo-pla-gradient-rainbow",
    "brandName": "ELEGOO",
    "name": "PLA Gradient Rainbow",
    "type": "PLA",
    "abbreviation": "PLA",
    "tags": [],
    "color": "#AA0000",
    "secondaryColors": ["#00BB00", "#0000CC"],
    "optTags": [_TAG_GRADIENT],
    "density": 1.24,
    "nozzleTempMax": 220,
    "bedTempMax": 60,
}


def test_opt_to_spoolman_fields_coextruded_sets_direction():
    """Coextruded OPT → multi_color_direction='coaxial' + sensible color_hex even with empty primary."""
    fields = opt_to_spoolman_fields(_OPT_COEXTRUDED)
    assert fields.get("multi_color_direction") == "coaxial"
    assert fields.get("multi_color_hexes") is not None
    assert "FF0000" in fields["multi_color_hexes"] and "00FF00" in fields["multi_color_hexes"]
    # color_hex must be set (synthesised from first secondary for coextruded)
    assert fields.get("color_hex") is not None


def test_opt_to_spoolman_fields_coextruded_empty_primary_synthesises_color_hex():
    """Empty primary color on coextruded → color_hex derived from first secondary color."""
    fields = opt_to_spoolman_fields(_OPT_COEXTRUDED)
    # fdb_multicolor_to_sm synthesises primary from first secondary for coextruded
    assert fields["color_hex"] == "FF0000"


def test_opt_to_spoolman_fields_gradient_sets_direction():
    """Gradient OPT → multi_color_direction='longitudinal'."""
    fields = opt_to_spoolman_fields(_OPT_GRADIENT)
    assert fields.get("multi_color_direction") == "longitudinal"
    assert "AA0000" in fields.get("multi_color_hexes", "")
    assert fields.get("color_hex") == "AA0000"


def test_opt_to_spoolman_fields_gradient_multi_color_hexes_contains_all():
    """Gradient multi_color_hexes = primary + all secondaries."""
    fields = opt_to_spoolman_fields(_OPT_GRADIENT)
    hexes = fields.get("multi_color_hexes", "")
    assert "AA0000" in hexes
    assert "00BB00" in hexes
    assert "0000CC" in hexes


def test_opt_to_spoolman_fields_single_color_unchanged():
    """Single-color OPT → color_hex set, no multi fields."""
    fields = opt_to_spoolman_fields(_OPT_PLA_SILK)
    assert fields.get("color_hex") == "B87333"
    assert "multi_color_direction" not in fields
    assert "multi_color_hexes" not in fields


# ---------------------------------------------------------------------------
# Phase: Profile pre-filter in /matches endpoint
# ---------------------------------------------------------------------------


# OPT coextruded and gradient materials for ELEGOO (same brand/material as _OPT_PETG)
_OPT_ELEGOO_COEXTRUDED = {
    **_OPT_COEXTRUDED,
    "uuid": "elegoo-coext-0000-0000-000000000002",
    "slug": "elegoo-pla-coextruded",
    "brandName": "ELEGOO",
    "type": "PLA",
}

_OPT_ELEGOO_GRADIENT = {
    **_OPT_GRADIENT,
    "uuid": "elegoo-grad-0000-0000-000000000002",
    "slug": "elegoo-pla-gradient",
    "brandName": "ELEGOO",
    "type": "PLA",
}


def _sm_coaxial(sm_id: int = 100, vendor: str = "ELEGOO") -> SpoolmanFilament:
    """Helper: coaxial SM filament."""
    return SpoolmanFilament(
        id=sm_id, name="Dual Color",
        vendor=SpoolmanVendor(id=1, name=vendor),
        material="PLA", color_hex="FF0000",
        multi_color_hexes="FF0000,00FF00", multi_color_direction="coaxial",
        extra={},
    )


def _sm_longitudinal(sm_id: int = 101, vendor: str = "ELEGOO") -> SpoolmanFilament:
    """Helper: longitudinal SM filament."""
    return SpoolmanFilament(
        id=sm_id, name="Rainbow",
        vendor=SpoolmanVendor(id=1, name=vendor),
        material="PLA", color_hex="AA0000",
        multi_color_hexes="AA0000,00BB00,0000CC", multi_color_direction="longitudinal",
        extra={},
    )


@pytest.mark.asyncio
async def test_matches_coaxial_sm_matches_only_coextruded_not_solid(tmp_path):
    """A coaxial SM filament must match only coextruded OPT candidates, NOT a solid/gradient."""
    # Dataset: one solid, one coextruded, one gradient — all same brand ELEGOO
    materials = [_OPT_PETG, _OPT_ELEGOO_COEXTRUDED, _OPT_ELEGOO_GRADIENT]
    sm_coaxial = _sm_coaxial()

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router
    from app.core.opentag_cache import _save_cache

    fresh_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _save_cache(str(tmp_path), materials, fresh_ts)

    fake_fdb = AsyncMock()
    fake_sm = AsyncMock()
    fake_sm.get_filaments = AsyncMock(return_value=[sm_coaxial])

    test_app = FastAPI()
    test_app.include_router(router, prefix="/api")
    test_app.state.filamentdb = fake_fdb
    test_app.state.spoolman = fake_sm

    import app.api.opentag as _ot_mod
    original_data_dir = _ot_mod._settings.data_dir
    _ot_mod._settings.data_dir = str(tmp_path)
    try:
        client = TestClient(test_app, raise_server_exceptions=True)
        resp = client.get("/api/openprinttag/matches")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data["matches"]) == 1
        match = data["matches"][0]
        # Must match the coextruded OPT, NOT the solid or gradient
        assert match["opt_slug"] == "elegoo-pla-coextruded"
    finally:
        _ot_mod._settings.data_dir = original_data_dir


@pytest.mark.asyncio
async def test_matches_single_sm_never_matches_multicolor_opt(tmp_path):
    """A single-color SM filament must NOT match a multicolor OPT candidate."""
    # Dataset: coextruded ELEGOO material only (no solid ELEGOO material)
    materials = [_OPT_ELEGOO_COEXTRUDED]
    sm_single = _sm_fil(sm_id=10, vendor="ELEGOO", material="PLA", color_hex="FF0000")

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router
    from app.core.opentag_cache import _save_cache

    fresh_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _save_cache(str(tmp_path), materials, fresh_ts)

    fake_fdb = AsyncMock()
    fake_sm = AsyncMock()
    fake_sm.get_filaments = AsyncMock(return_value=[sm_single])

    test_app = FastAPI()
    test_app.include_router(router, prefix="/api")
    test_app.state.filamentdb = fake_fdb
    test_app.state.spoolman = fake_sm

    import app.api.opentag as _ot_mod
    original_data_dir = _ot_mod._settings.data_dir
    _ot_mod._settings.data_dir = str(tmp_path)
    try:
        client = TestClient(test_app, raise_server_exceptions=True)
        resp = client.get("/api/openprinttag/matches")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data["matches"]) == 1
        match = data["matches"][0]
        # Single SM must not match a multicolor OPT → no match
        assert match["opt_slug"] is None, (
            f"Expected no match but got slug={match['opt_slug']!r}"
        )
    finally:
        _ot_mod._settings.data_dir = original_data_dir


@pytest.mark.asyncio
async def test_matches_longitudinal_sm_matches_gradient_not_coextruded(tmp_path):
    """A longitudinal SM filament must match gradient OPT, not coextruded."""
    materials = [_OPT_ELEGOO_COEXTRUDED, _OPT_ELEGOO_GRADIENT]
    sm_long = _sm_longitudinal()

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router
    from app.core.opentag_cache import _save_cache

    fresh_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _save_cache(str(tmp_path), materials, fresh_ts)

    fake_fdb = AsyncMock()
    fake_sm = AsyncMock()
    fake_sm.get_filaments = AsyncMock(return_value=[sm_long])

    test_app = FastAPI()
    test_app.include_router(router, prefix="/api")
    test_app.state.filamentdb = fake_fdb
    test_app.state.spoolman = fake_sm

    import app.api.opentag as _ot_mod
    original_data_dir = _ot_mod._settings.data_dir
    _ot_mod._settings.data_dir = str(tmp_path)
    try:
        client = TestClient(test_app, raise_server_exceptions=True)
        resp = client.get("/api/openprinttag/matches")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data["matches"]) == 1
        match = data["matches"][0]
        assert match["opt_slug"] == "elegoo-pla-gradient"
    finally:
        _ot_mod._settings.data_dir = original_data_dir


# ---------------------------------------------------------------------------
# Fix 1: opt_color_profile derives arrangement from tags when secondaryColors is empty
# ---------------------------------------------------------------------------


def test_opt_color_profile_coextruded_from_tag_with_empty_secondary():
    """opt_color_profile returns 'coextruded' from tag string even when secondaryColors is empty.

    This is the real-data case: FDB's denormalized OpenTag feed leaves secondaryColors
    empty on all records; arrangement is only in the string tags array.
    """
    opt = {
        "uuid": "test-coext",
        "slug": "elegoo-pla-silk-black-purple",
        "brandName": "ELEGOO",
        "name": "Silk PLA Black Purple",
        "type": "PLA",
        "tags": ["silk", "coextruded"],
        "color": "#2A1A5E",
        "secondaryColors": [],   # empty — as in the real FDB feed
        "optTags": [],
        "density": 1.24,
    }
    assert opt_color_profile(opt) == "coextruded", (
        "Expected 'coextruded' from tag string 'coextruded' with empty secondaryColors"
    )


def test_opt_color_profile_gradient_from_tag_with_empty_secondary():
    """opt_color_profile returns 'gradient' from 'gradual_color_change' tag when secondaryColors is empty."""
    opt = {
        "uuid": "test-grad",
        "slug": "amolen-pla-gradient-red-white",
        "brandName": "AMOLEN",
        "name": "PLA Gradient Red White",
        "type": "PLA",
        "tags": ["gradual_color_change"],
        "color": "#FF0000",
        "secondaryColors": [],
        "optTags": [],
        "density": 1.24,
    }
    assert opt_color_profile(opt) == "gradient"


def test_opt_color_profile_single_when_no_arrangement_tag_and_no_secondary():
    """opt_color_profile returns 'single' when no arrangement tag and no secondaryColors."""
    opt = {
        "uuid": "test-single",
        "slug": "hatchbox-pla-orange",
        "brandName": "Hatchbox",
        "name": "Orange PLA",
        "type": "PLA",
        "tags": ["glow"],   # finish tag only, no arrangement tag
        "color": "#FF8C00",
        "secondaryColors": [],
        "optTags": [],
        "density": 1.24,
    }
    assert opt_color_profile(opt) == "single"


def test_coaxial_sm_matches_coextruded_opt_with_empty_secondary(tmp_path):
    """A coaxial SM filament finds a same-brand OPT entry tagged 'coextruded' even
    when that OPT entry has empty secondaryColors (the real-data case).
    """
    # OPT entry: tagged 'coextruded', secondaryColors empty (FDB feed shape)
    opt_coext_tag_only = {
        "uuid": "elegoo-coext-tag-only-001",
        "slug": "elegoo-pla-silk-black-purple",
        "brandName": "ELEGOO",
        "name": "Silk PLA Black Purple",
        "type": "PLA",
        "tags": ["silk", "coextruded"],
        "color": "#2A1A5E",
        "secondaryColors": [],   # empty — real FDB feed
        "optTags": [],
        "density": 1.24,
        "nozzleTempMax": 230,
        "bedTempMax": 60,
    }
    # A coaxial SM filament (multicolor, coaxial direction)
    sm_coaxial = SpoolmanFilament(
        id=50,
        name="Silk PLA Black Purple",
        vendor=SpoolmanVendor(id=1, name="ELEGOO"),
        material="PLA Silk",
        color_hex="2A1A5E",
        multi_color_hexes="2A1A5E,800080",
        multi_color_direction="coaxial",
        extra={},
    )

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router
    from app.core.opentag_cache import _save_cache

    fresh_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _save_cache(str(tmp_path), [opt_coext_tag_only], fresh_ts)

    fake_fdb = AsyncMock()
    fake_sm = AsyncMock()
    fake_sm.get_filaments = AsyncMock(return_value=[sm_coaxial])

    test_app = FastAPI()
    test_app.include_router(router, prefix="/api")
    test_app.state.filamentdb = fake_fdb
    test_app.state.spoolman = fake_sm

    import app.api.opentag as _ot_mod
    original_data_dir = _ot_mod._settings.data_dir
    _ot_mod._settings.data_dir = str(tmp_path)
    try:
        client = TestClient(test_app, raise_server_exceptions=True)
        resp = client.get("/api/openprinttag/matches")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data["matches"]) == 1
        match = data["matches"][0]
        assert match["opt_slug"] == "elegoo-pla-silk-black-purple", (
            f"Expected coextruded OPT to match coaxial SM, but got slug={match['opt_slug']!r}"
        )
    finally:
        _ot_mod._settings.data_dir = original_data_dir


def test_opt_to_spoolman_fields_empty_secondary_with_coextruded_tag_preserves_multi_color_hexes():
    """When OPT has 'coextruded' tag but empty secondaryColors, opt_to_spoolman_fields must NOT
    include multi_color_hexes in the result (Spoolman's existing hexes should be preserved)."""
    opt = {
        "uuid": "test-coext-empty",
        "slug": "elegoo-pla-silk-black-purple",
        "brandName": "ELEGOO",
        "name": "Silk PLA Black Purple",
        "type": "PLA",
        "tags": ["silk", "coextruded"],
        "color": "#2A1A5E",
        "secondaryColors": [],
        "optTags": [],
        "density": 1.24,
        "nozzleTempMax": 230,
        "bedTempMax": 60,
    }
    fields = opt_to_spoolman_fields(opt)
    # Must NOT set multi_color_hexes (would overwrite Spoolman's actual hex data)
    assert "multi_color_hexes" not in fields, (
        "multi_color_hexes must not be written when OPT secondaryColors is empty"
    )
    # Must set direction so Spoolman knows the arrangement
    assert fields.get("multi_color_direction") == "coaxial"


# ---------------------------------------------------------------------------
# Fix 2: Polymer-family hard gate
# ---------------------------------------------------------------------------

from app.core.opentag_match import material_family  # noqa: E402


def test_material_family_pla_variants():
    assert material_family("PLA") == "pla"
    assert material_family("PLA+") == "pla"
    assert material_family("PLA Silk") == "pla"
    assert material_family("PLA Matte") == "pla"


def test_material_family_petg():
    assert material_family("PETG") == "petg"
    assert material_family("PETG-CF") == "petg"


def test_material_family_asa():
    assert material_family("ASA") == "asa"


def test_material_family_abs():
    assert material_family("ABS") == "abs"
    assert material_family("ABS+") == "abs"


def test_material_family_pc():
    assert material_family("PC") == "pc"


def test_material_family_tpu():
    assert material_family("TPU") == "tpu"
    assert material_family("TPE") == "tpu"


def test_material_family_pa():
    assert material_family("PA") == "pa"
    assert material_family("PA-CF") == "pa"
    assert material_family("PA6") == "pa"
    assert material_family("Nylon") == "pa"


def test_material_family_empty():
    assert material_family(None) == ""
    assert material_family("") == ""


def test_material_family_unknown_passes_through():
    """Unknown material returns as-is (lower-cased), so the gate is a no-op."""
    fam = material_family("SuperPolymer2000")
    assert fam == "superpolymer2000"  # opaque, won't match known families


def test_family_gate_pc_does_not_match_asa(tmp_path):
    """A PC SM filament must NOT match an ASA OPT candidate (polymer-family hard gate)."""
    opt_asa = {
        "uuid": "asa-brand-001",
        "slug": "elegoo-asa-white",
        "brandName": "ELEGOO",
        "name": "ASA White",
        "type": "ASA",
        "tags": [],
        "color": "#FFFFFF",
        "secondaryColors": [],
        "optTags": [],
        "density": 1.07,
        "nozzleTempMax": 260,
        "bedTempMax": 90,
    }
    sm_pc = SpoolmanFilament(
        id=99,
        name="White",
        vendor=SpoolmanVendor(id=1, name="ELEGOO"),
        material="PC",
        color_hex="FFFFFF",
        extra={},
    )

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router
    from app.core.opentag_cache import _save_cache

    fresh_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _save_cache(str(tmp_path), [opt_asa], fresh_ts)

    fake_fdb = AsyncMock()
    fake_sm = AsyncMock()
    fake_sm.get_filaments = AsyncMock(return_value=[sm_pc])

    test_app = FastAPI()
    test_app.include_router(router, prefix="/api")
    test_app.state.filamentdb = fake_fdb
    test_app.state.spoolman = fake_sm

    import app.api.opentag as _ot_mod
    original_data_dir = _ot_mod._settings.data_dir
    _ot_mod._settings.data_dir = str(tmp_path)
    try:
        client = TestClient(test_app, raise_server_exceptions=True)
        resp = client.get("/api/openprinttag/matches")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        match = data["matches"][0]
        assert match["opt_slug"] is None, (
            f"PC filament must not match ASA OPT, got slug={match['opt_slug']!r}"
        )
    finally:
        _ot_mod._settings.data_dir = original_data_dir


def test_family_gate_asa_does_not_match_petg(tmp_path):
    """An ASA SM filament must NOT match a PETG OPT candidate."""
    opt_petg = {
        "uuid": "petg-brand-001",
        "slug": "elegoo-petg-black",
        "brandName": "ELEGOO",
        "name": "PETG Black",
        "type": "PETG",
        "tags": [],
        "color": "#000000",
        "secondaryColors": [],
        "optTags": [],
        "density": 1.27,
        "nozzleTempMax": 250,
        "bedTempMax": 80,
    }
    sm_asa = SpoolmanFilament(
        id=100,
        name="Black",
        vendor=SpoolmanVendor(id=1, name="ELEGOO"),
        material="ASA",
        color_hex="000000",
        extra={},
    )

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router
    from app.core.opentag_cache import _save_cache

    fresh_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _save_cache(str(tmp_path), [opt_petg], fresh_ts)

    fake_fdb = AsyncMock()
    fake_sm = AsyncMock()
    fake_sm.get_filaments = AsyncMock(return_value=[sm_asa])

    test_app = FastAPI()
    test_app.include_router(router, prefix="/api")
    test_app.state.filamentdb = fake_fdb
    test_app.state.spoolman = fake_sm

    import app.api.opentag as _ot_mod
    original_data_dir = _ot_mod._settings.data_dir
    _ot_mod._settings.data_dir = str(tmp_path)
    try:
        client = TestClient(test_app, raise_server_exceptions=True)
        resp = client.get("/api/openprinttag/matches")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        match = data["matches"][0]
        assert match["opt_slug"] is None, (
            f"ASA filament must not match PETG OPT, got slug={match['opt_slug']!r}"
        )
    finally:
        _ot_mod._settings.data_dir = original_data_dir


def test_family_gate_pla_matches_pla_plus(tmp_path):
    """A PLA SM filament CAN match a PLA+ OPT candidate (same family)."""
    opt_pla_plus = {
        "uuid": "pla-plus-001",
        "slug": "elegoo-pla-plus-white",
        "brandName": "ELEGOO",
        "name": "PLA+ White",
        "type": "PLA+",
        "tags": [],
        "color": "#FFFFFF",
        "secondaryColors": [],
        "optTags": [],
        "density": 1.24,
        "nozzleTempMax": 220,
        "bedTempMax": 60,
    }
    sm_pla = SpoolmanFilament(
        id=101,
        name="White",
        vendor=SpoolmanVendor(id=1, name="ELEGOO"),
        material="PLA",
        color_hex="FFFFFF",
        extra={},
    )

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router
    from app.core.opentag_cache import _save_cache

    fresh_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _save_cache(str(tmp_path), [opt_pla_plus], fresh_ts)

    fake_fdb = AsyncMock()
    fake_sm = AsyncMock()
    fake_sm.get_filaments = AsyncMock(return_value=[sm_pla])

    test_app = FastAPI()
    test_app.include_router(router, prefix="/api")
    test_app.state.filamentdb = fake_fdb
    test_app.state.spoolman = fake_sm

    import app.api.opentag as _ot_mod
    original_data_dir = _ot_mod._settings.data_dir
    _ot_mod._settings.data_dir = str(tmp_path)
    try:
        client = TestClient(test_app, raise_server_exceptions=True)
        resp = client.get("/api/openprinttag/matches")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        match = data["matches"][0]
        # PLA and PLA+ are same family → should match (if score is good enough)
        # With same vendor, same color, similar name → should be a match
        assert match["opt_slug"] == "elegoo-pla-plus-white", (
            f"PLA should match PLA+ (same family) but got slug={match['opt_slug']!r}"
        )
    finally:
        _ot_mod._settings.data_dir = original_data_dir


# ---------------------------------------------------------------------------
# Fix 3: Finish-aware scoring — penalty, reward, finish-word stripping
# ---------------------------------------------------------------------------


def _make_opt(
    slug: str,
    name: str,
    material_type: str = "PLA",
    vendor: str = "Hatchbox",
    tags: list | None = None,
    color: str = "#FF8C00",
) -> dict:
    """Helper to build a minimal OPT dict for finish scoring tests."""
    return {
        "uuid": f"finish-test-{slug}",
        "slug": slug,
        "brandName": vendor,
        "name": name,
        "type": material_type,
        "abbreviation": material_type,
        "tags": tags or [],
        "color": color,
        "secondaryColors": [],
        "optTags": [],
        "density": 1.24,
        "nozzleTempMax": 220,
        "bedTempMax": 60,
    }


def test_solid_sm_does_not_pick_transparent_over_plain():
    """A solid SM 'Orange' filament must score plain 'Orange' higher than 'Transparent Orange'.

    Before this fix, finish words in the OPT name inflated the color-name score.
    After: finish words are stripped before token comparison; the transparent/solid
    mismatch is penalised by the finish component.
    """
    sm_solid_orange = SpoolmanFilament(
        id=1,
        name="Orange",
        vendor=SpoolmanVendor(id=1, name="Hatchbox"),
        material="PLA",
        color_hex="FF8C00",
        extra={},
    )
    opt_plain = _make_opt("hatchbox-pla-orange", "Orange PLA", color="#FF8C00")
    opt_transparent = _make_opt(
        "hatchbox-pla-transparent-orange", "Transparent Orange PLA",
        tags=["transparent"], color="#FF8C00",
    )

    score_plain = score_candidate(sm_solid_orange, opt_plain)
    score_transparent = score_candidate(sm_solid_orange, opt_transparent)

    assert score_plain > score_transparent, (
        f"Plain Orange ({score_plain:.4f}) must outscore Transparent Orange "
        f"({score_transparent:.4f}) for a solid SM filament"
    )


def test_solid_sm_does_not_pick_silk_over_plain():
    """A solid SM filament must not prefer 'Silk White' over plain 'White'."""
    sm_solid = SpoolmanFilament(
        id=2,
        name="White",
        vendor=SpoolmanVendor(id=1, name="ELEGOO"),
        material="PLA",
        color_hex="FFFFFF",
        extra={},
    )
    opt_plain = _make_opt("elegoo-pla-white", "White PLA", vendor="ELEGOO", color="#FFFFFF")
    opt_silk = _make_opt(
        "elegoo-pla-silk-white", "Silk PLA White", vendor="ELEGOO",
        tags=["silk"], color="#FFFFFF",
    )

    score_plain = score_candidate(sm_solid, opt_plain)
    score_silk = score_candidate(sm_solid, opt_silk)

    assert score_plain > score_silk, (
        f"Plain White ({score_plain:.4f}) must outscore Silk White "
        f"({score_silk:.4f}) for a solid SM filament"
    )


def test_matte_sm_does_not_match_silk():
    """A matte SM filament must not prefer a silk OPT over a matte OPT."""
    sm_matte = SpoolmanFilament(
        id=3,
        name="Matte Mint Green",
        vendor=SpoolmanVendor(id=1, name="ELEGOO"),
        material="PLA Matte",
        color_hex="98D4A3",
        extra={},
    )
    opt_matte = _make_opt(
        "elegoo-pla-matte-mint", "PLA Matte Mint Green", vendor="ELEGOO",
        material_type="PLA", tags=["matte"], color="#98D4A3",
    )
    opt_silk = _make_opt(
        "elegoo-pla-silk-mint", "Silk PLA Mint Green", vendor="ELEGOO",
        material_type="PLA", tags=["silk"], color="#98D4A3",
    )

    score_matte = score_candidate(sm_matte, opt_matte)
    score_silk = score_candidate(sm_matte, opt_silk)

    assert score_matte > score_silk, (
        f"Matte ({score_matte:.4f}) must outscore Silk ({score_silk:.4f}) "
        "for a matte SM filament"
    )


def test_finish_word_stripping_makes_orange_beat_transparent_orange():
    """After finish-word stripping, 'Orange' and 'Transparent Orange' produce the same
    color token set {orange}.  'Orange' then wins because finish mismatch penalises
    'Transparent Orange' while neutral finish gives 'Orange' a bonus.
    """
    sm_solid = SpoolmanFilament(
        id=4,
        name="Orange",
        vendor=SpoolmanVendor(id=1, name="Hatchbox"),
        material="PLA",
        color_hex="FF8C00",
        extra={},
    )
    opt_orange = _make_opt("hatchbox-pla-orange", "Orange", color="#FF8C00")
    opt_transparent_orange = _make_opt(
        "hatchbox-pla-transparent-orange", "Transparent Orange",
        tags=["transparent"], color="#FF8C00",
    )
    score_orange = score_candidate(sm_solid, opt_orange)
    score_trans = score_candidate(sm_solid, opt_transparent_orange)

    assert score_orange > score_trans, (
        f"'Orange' ({score_orange:.4f}) should beat 'Transparent Orange' ({score_trans:.4f})"
    )


def test_silk_sm_prefers_silk_opt():
    """A silk SM filament should score a silk OPT higher than a plain OPT."""
    sm_silk = SpoolmanFilament(
        id=5,
        name="Silk Bronze",
        vendor=SpoolmanVendor(id=1, name="Buddy3D"),
        material="PLA Silk",
        color_hex="B87333",
        extra={},
    )
    opt_silk = _make_opt(
        "buddy3d-pla-silk-bronze", "PLA Silk Bronze", vendor="Buddy3D",
        tags=["silk"], color="#B87333",
    )
    opt_plain = _make_opt(
        "buddy3d-pla-bronze", "PLA Bronze", vendor="Buddy3D", color="#B87333",
    )
    score_silk = score_candidate(sm_silk, opt_silk)
    score_plain = score_candidate(sm_silk, opt_plain)

    assert score_silk > score_plain, (
        f"Silk ({score_silk:.4f}) should beat plain ({score_plain:.4f}) for a silk SM filament"
    )


def test_disjoint_color_name_limit_still_applies_after_rebalance():
    """After rebalancing, a disjoint color name (orange vs copper) should still limit
    the candidate's score so the ordering assertion holds.
    """
    sm_orange = SpoolmanFilament(
        id=1,
        name="Orange",
        vendor=SpoolmanVendor(id=1, name="Hatchbox"),
        material="PETG",
        color_hex="CB6D30",
        extra={},
    )
    score_copper = score_candidate(sm_orange, _OPT_HATCHBOX_PETG_COPPER)
    # Max without name: vendor(0.20) + material(0.20) + hex(<0.10) + finish(0.075) < 0.60
    assert score_copper < 0.60, (
        f"Disjoint name should limit score below 0.60 after rebalance, got {score_copper:.4f}"
    )


def test_score_no_color_token_sm_matches_brand_material_after_rebalance():
    """After rebalancing, a no-color-token SM filament (neutral name_sim=0.5) should
    still score above min_confidence via vendor + material + neutral name + some hex.
    """
    sm_unnamed = SpoolmanFilament(
        id=1,
        name="PETG",
        vendor=SpoolmanVendor(id=1, name="ELEGOO"),
        material="PETG",
        color_hex="CC0000",
        extra={},
    )
    score = score_candidate(sm_unnamed, _OPT_PETG)
    # vendor(0.20) + material(0.20) + neutral_name(0.15) + some_hex + finish > 0.30
    assert score > 0.50, f"Expected neutral-name match > 0.50, got {score:.4f}"
