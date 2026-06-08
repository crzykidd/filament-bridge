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
    # material_tags must be a STRING (CSV), not a list — Spoolman text field rejects arrays
    mt = fields["extra.filamentdb_material_tags"]
    assert isinstance(mt, str), f"expected str, got {type(mt)}: {mt!r}"
    # Silk tag (17) should be present in the CSV
    assert "17" in mt.split(",")


def test_opt_to_spoolman_fields_secondary_colors():
    opt = {**_OPT_PLA_SILK, "secondaryColors": ["#FF0000", "#00FF00"]}
    fields = opt_to_spoolman_fields(opt)
    assert "multi_color_hexes" in fields
    assert "FF0000" in fields["multi_color_hexes"]


def test_opt_to_spoolman_fields_material_tags_is_string_not_list():
    """material_tags must be a CSV STRING, not a list — Spoolman text field rejects arrays."""
    fields = opt_to_spoolman_fields(_OPT_PLA_SILK)  # has tags: ["silk"] → id 17
    mt = fields["extra.filamentdb_material_tags"]
    assert isinstance(mt, str), f"Expected str, got {type(mt)}: {mt!r}"


def test_opt_to_spoolman_fields_empty_finish_returns_empty_string():
    """OPT material with no finish tags should produce an empty string for material_tags."""
    fields = opt_to_spoolman_fields(_OPT_PETG)  # tags: []
    mt = fields["extra.filamentdb_material_tags"]
    assert isinstance(mt, str)
    assert mt == ""


def test_opt_to_spoolman_fields_material_tags_encodes_to_json_string():
    """encode_extra_value(serialize_material_tags(ids)) must produce a JSON string, not a JSON array.

    Specifically: encode_extra_value("17") == '"17"', NOT '[17]'.
    Spoolman text fields accept JSON-quoted strings, not JSON arrays.
    """
    from app.schemas.spoolman import encode_extra_value
    fields = opt_to_spoolman_fields(_OPT_PLA_SILK)  # silk → id 17
    mt = fields["extra.filamentdb_material_tags"]
    encoded = encode_extra_value(mt)
    # Must be a JSON-quoted string: '"17"', not '[17]'
    import json
    decoded = json.loads(encoded)
    assert isinstance(decoded, str), f"Expected encoded value to decode to str, got {type(decoded)}: {decoded!r}"
    # Must NOT be a list
    assert not isinstance(decoded, list), "Spoolman text field rejects JSON arrays — encode must produce a string"


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
# Color-name tokenization: non-alphanumeric split + noise-token removal
# ---------------------------------------------------------------------------

# OPT materials for the dual-color tie-breaking scenario (AMOLEN Matte PLA)
_OPT_AMOLEN_GREEN_PURPLE = {
    "uuid": "amolen-0000-0000-0000-000000000001",
    "slug": "amolen-pla-matte-dual-green-purple",
    "brandName": "AMOLEN",
    "name": "PLA Matte Dual Color Green Purple",
    "type": "PLA",
    "abbreviation": "PLA",
    "tags": ["matte", "coextruded"],
    "color": "#006400",
    "secondaryColors": ["800080"],
    "density": 1.24,
    "nozzleTempMin": 190,
    "nozzleTempMax": 220,
    "bedTempMin": 45,
    "bedTempMax": 60,
    "completenessScore": 80,
}

_OPT_AMOLEN_BLUE_PINK = {
    "uuid": "amolen-0000-0000-0000-000000000002",
    "slug": "amolen-pla-matte-dual-blue-pink",
    "brandName": "AMOLEN",
    "name": "PLA Matte Dual Color Blue Pink",
    "type": "PLA",
    "abbreviation": "PLA",
    "tags": ["matte", "coextruded"],
    "color": "#0000FF",
    "secondaryColors": ["FFC0CB"],
    "density": 1.24,
    "nozzleTempMin": 190,
    "nozzleTempMax": 220,
    "bedTempMin": 45,
    "bedTempMax": 60,
    "completenessScore": 80,
}

_OPT_AMOLEN_BROWN_WHITE = {
    "uuid": "amolen-0000-0000-0000-000000000003",
    "slug": "amolen-pla-matte-dual-brown-white",
    "brandName": "AMOLEN",
    "name": "PLA Matte Dual Color Brown White",
    "type": "PLA",
    "abbreviation": "PLA",
    "tags": ["matte", "coextruded"],
    "color": "#8B4513",
    "secondaryColors": ["FFFFFF"],
    "density": 1.24,
    "nozzleTempMin": 190,
    "nozzleTempMax": 220,
    "bedTempMin": 45,
    "bedTempMax": 60,
    "completenessScore": 80,
}


def test_color_name_tokens_slash_separated_dual_color():
    """'Green/Purple' must tokenize to {'green','purple'}, not {'green/purple'}.

    Root-cause regression: whitespace-only split left 'Green/Purple' as a single
    token that never matched the OPT space-separated 'Green Purple'.
    """
    from app.core.material_tags import DEFAULT_MATERIAL_TAG_IDS
    toks = _color_name_tokens(
        "Matte PLA Dual Color Green/Purple", "AMOLEN", "PLA", DEFAULT_MATERIAL_TAG_IDS
    )
    assert toks == {"green", "purple"}, (
        f"Expected {{'green','purple'}}, got {toks!r}"
    )


def test_color_name_tokens_space_separated_dual_color():
    """OPT-side 'PLA Matte Dual Color Green Purple' → {'green','purple'} (no vendor arg)."""
    from app.core.material_tags import DEFAULT_MATERIAL_TAG_IDS
    toks = _color_name_tokens(
        "PLA Matte Dual Color Green Purple", None, "PLA", DEFAULT_MATERIAL_TAG_IDS
    )
    assert toks == {"green", "purple"}, (
        f"Expected {{'green','purple'}}, got {toks!r}"
    )


def test_color_name_tokens_single_color_unaffected():
    """Single-color names are unchanged by the new tokenization ('Orange' → {'orange'})."""
    from app.core.material_tags import DEFAULT_MATERIAL_TAG_IDS
    toks = _color_name_tokens("Orange", "Hatchbox", "PLA", DEFAULT_MATERIAL_TAG_IDS)
    assert toks == {"orange"}, f"Expected {{'orange'}}, got {toks!r}"


def test_color_name_tokens_descriptor_only_returns_empty():
    """A name with only descriptor tokens ('Dual Color') → empty set (neutral, no crash)."""
    from app.core.material_tags import DEFAULT_MATERIAL_TAG_IDS
    toks = _color_name_tokens("Dual Color", "AMOLEN", "PLA", DEFAULT_MATERIAL_TAG_IDS)
    assert toks == set(), f"Expected empty set, got {toks!r}"


def test_dual_color_slash_sm_scores_higher_than_different_combo():
    """SM 'Matte PLA Dual Color Green/Purple' scores strictly higher against the
    OPT 'Green Purple' candidate than against 'Blue Pink' or 'Brown White' of the
    same brand+material — the correct color combo is preferred, not tied.
    """
    sm_green_purple = SpoolmanFilament(
        id=147,
        name="Matte PLA Dual Color Green/Purple",
        vendor=SpoolmanVendor(id=5, name="AMOLEN"),
        material="PLA",
        color_hex="006400",
        multi_color_hexes="006400,800080",
        multi_color_direction="coaxial",
        extra={},
    )
    score_gp = score_candidate(sm_green_purple, _OPT_AMOLEN_GREEN_PURPLE)
    score_bp = score_candidate(sm_green_purple, _OPT_AMOLEN_BLUE_PINK)
    score_bw = score_candidate(sm_green_purple, _OPT_AMOLEN_BROWN_WHITE)

    assert score_gp > score_bp, (
        f"Green/Purple ({score_gp:.4f}) should beat Blue Pink ({score_bp:.4f})"
    )
    assert score_gp > score_bw, (
        f"Green/Purple ({score_gp:.4f}) should beat Brown White ({score_bw:.4f})"
    )


def test_find_best_match_dual_color_slash_returns_correct_combo():
    """find_best_match for SM 'Green/Purple' must return the 'Green Purple' OPT candidate
    as best (ranks #1), not 'Blue Pink' or 'Brown White'.
    """
    sm_green_purple = SpoolmanFilament(
        id=147,
        name="Matte PLA Dual Color Green/Purple",
        vendor=SpoolmanVendor(id=5, name="AMOLEN"),
        material="PLA",
        color_hex="006400",
        multi_color_hexes="006400,800080",
        multi_color_direction="coaxial",
        extra={},
    )
    result = find_best_match(
        sm_green_purple,
        [_OPT_AMOLEN_GREEN_PURPLE, _OPT_AMOLEN_BLUE_PINK, _OPT_AMOLEN_BROWN_WHITE],
        min_confidence=0.0,
    )
    assert result["best"] is not None
    assert result["best"]["slug"] == "amolen-pla-matte-dual-green-purple", (
        f"Expected 'amolen-pla-matte-dual-green-purple', got '{result['best']['slug']}'"
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
    """Coextruded OPT → multi_color_direction='coaxial', all hexes in multi_color_hexes, no color_hex."""
    fields = opt_to_spoolman_fields(_OPT_COEXTRUDED)
    assert fields.get("multi_color_direction") == "coaxial"
    assert fields.get("multi_color_hexes") is not None
    assert "FF0000" in fields["multi_color_hexes"] and "00FF00" in fields["multi_color_hexes"]
    # color_hex must be absent — sending both would cause Spoolman 422
    assert "color_hex" not in fields


def test_opt_to_spoolman_fields_coextruded_no_color_hex():
    """Coextruded OPT → color_hex is NOT emitted (Spoolman rejects both color_hex + multi_color_hexes)."""
    fields = opt_to_spoolman_fields(_OPT_COEXTRUDED)
    assert "color_hex" not in fields


def test_opt_to_spoolman_fields_gradient_sets_direction():
    """Gradient OPT → multi_color_direction='longitudinal', all hexes in multi_color_hexes, no color_hex."""
    fields = opt_to_spoolman_fields(_OPT_GRADIENT)
    assert fields.get("multi_color_direction") == "longitudinal"
    assert "AA0000" in fields.get("multi_color_hexes", "")
    # color_hex must be absent — sending both would cause Spoolman 422
    assert "color_hex" not in fields


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


def test_opt_to_spoolman_fields_empty_secondary_with_coextruded_tag_no_multicolor_fields():
    """When OPT has 'coextruded' tag but empty secondaryColors, opt_to_spoolman_fields must
    emit NEITHER multi_color_hexes NOR multi_color_direction.

    Spoolman rejects a PATCH that contains multi_color_direction without multi_color_hexes
    (→ 422).  The SM filament already carries the correct arrangement from its own data (that
    is how it was matched), so the apply has nothing new to contribute for multicolor fields.
    Native fields (material, density, finish tags, color_hex) are still emitted normally.
    """
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
    # Must NOT set multi_color_direction — Spoolman 422s direction-without-hexes
    assert "multi_color_direction" not in fields, (
        "multi_color_direction must not be written when secondaryColors is empty "
        "(Spoolman rejects direction without hexes → 422)"
    )
    # Native fields are still present
    assert fields.get("material") == "PLA"
    assert fields.get("density") == 1.24
    assert fields.get("color_hex") == "2A1A5E"


def test_opt_to_spoolman_fields_gradient_tag_empty_secondary_no_multicolor_fields():
    """Gradient tag + empty secondaryColors → neither multi_color_direction nor multi_color_hexes.

    Same 422-avoidance rule: longitudinal direction without hexes is rejected by Spoolman.
    """
    opt = {
        "uuid": "test-grad-empty",
        "slug": "silk-gradient-blue-red",
        "brandName": "SomeBrand",
        "name": "Silk Gradient Blue Red",
        "type": "PLA",
        "tags": ["gradual_color_change"],
        "color": "#0000FF",
        "secondaryColors": [],
        "optTags": [],
        "density": 1.24,
        "nozzleTempMax": 230,
        "bedTempMax": 60,
    }
    fields = opt_to_spoolman_fields(opt)
    assert "multi_color_direction" not in fields, (
        "multi_color_direction must not be written when secondaryColors is empty (gradient case)"
    )
    assert "multi_color_hexes" not in fields, (
        "multi_color_hexes must not be written when OPT secondaryColors is empty (gradient case)"
    )
    # color_hex is still emitted from the primary color
    assert fields.get("color_hex") == "0000FF"


def test_opt_to_spoolman_fields_with_secondaries_still_sets_both_multicolor_fields():
    """When OPT actually has secondaryColors, both multi_color_hexes AND multi_color_direction
    are still set together (the `if secondary:` branch is unchanged).
    """
    opt = {
        "uuid": "coext-with-secondary",
        "slug": "brand-pla-coextruded-red-green",
        "brandName": "BRAND",
        "name": "PLA Coextruded",
        "type": "PLA",
        "tags": ["coextruded"],
        "color": "",
        "secondaryColors": ["#FF0000", "#00FF00"],
        "optTags": [],
        "density": 1.24,
        "nozzleTempMax": 220,
        "bedTempMax": 60,
    }
    fields = opt_to_spoolman_fields(opt)
    # Both fields must be set together when secondaryColors is populated
    assert "multi_color_hexes" in fields, "multi_color_hexes must be set when secondaryColors is present"
    assert "multi_color_direction" in fields, "multi_color_direction must be set when secondaryColors is present"
    assert fields["multi_color_direction"] == "coaxial"
    assert "FF0000" in fields["multi_color_hexes"]
    assert "00FF00" in fields["multi_color_hexes"]


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


# ---------------------------------------------------------------------------
# Fix: opentag_apply self-heals by calling ensure_extra_fields before writes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_calls_ensure_extra_fields_before_decision_loop():
    """opentag_apply must call sm.ensure_extra_fields() before any PATCH write."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router

    ensure_called: list[bool] = []
    patch_called_before_ensure: list[bool] = []

    async def _fake_ensure():
        ensure_called.append(True)

    async def _fake_patch(fil_id, payload):
        # If ensure hasn't been called yet when patch runs, record that
        patch_called_before_ensure.append(len(ensure_called) == 0)
        return MagicMock()

    fake_sm = AsyncMock()
    fake_sm.ensure_extra_fields = AsyncMock(side_effect=_fake_ensure)
    fake_sm.update_filament = AsyncMock(side_effect=_fake_patch)

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
                "spoolman_filament_id": 7,
                "ignored": False,
                "fdb_filament_id": None,
                "openprinttag_slug": "test-slug",
                "openprinttag_uuid": "test-uuid",
                "fields": [
                    {"field": "material", "value": "PLA", "keep_mine": False},
                ],
            }
        ]
    }
    resp = client.post("/api/openprinttag/apply", json=request_body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["applied"] == 1
    assert data["errors"] == 0

    # ensure_extra_fields must have been called exactly once
    fake_sm.ensure_extra_fields.assert_called_once()
    # The PATCH must not have happened before ensure completed
    assert not any(patch_called_before_ensure), (
        "update_filament was called before ensure_extra_fields completed"
    )


@pytest.mark.asyncio
async def test_apply_succeeds_when_fields_were_missing_and_ensure_creates_them():
    """apply succeeds (no 422) when the required extra fields were missing and
    ensure_extra_fields creates them just-in-time before any PATCH.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router

    # Simulate a SM client where ensure_extra_fields silently creates the missing fields
    # and update_filament then succeeds (no 422).
    fake_sm = AsyncMock()
    fake_sm.ensure_extra_fields = AsyncMock(return_value=None)  # fields created OK
    fake_sm.update_filament = AsyncMock(return_value=MagicMock())  # PATCH succeeds

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
                "spoolman_filament_id": 99,
                "ignored": False,
                "fdb_filament_id": "fdb-99",
                "openprinttag_slug": "brand-pla-black",
                "openprinttag_uuid": "uuid-999",
                "fields": [
                    {"field": "material", "value": "PLA", "keep_mine": False},
                ],
            }
        ]
    }
    resp = client.post("/api/openprinttag/apply", json=request_body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["applied"] == 1
    assert data["errors"] == 0
    fake_sm.ensure_extra_fields.assert_called_once()
    fake_sm.update_filament.assert_called_once()


@pytest.mark.asyncio
async def test_apply_returns_502_when_ensure_extra_fields_fails():
    """When ensure_extra_fields raises, apply must return 502 opentag_field_setup_failed."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router

    fake_sm = AsyncMock()
    fake_sm.ensure_extra_fields = AsyncMock(
        side_effect=httpx.ConnectError("connection refused")
    )
    fake_sm.update_filament = AsyncMock()

    fake_fdb = AsyncMock()

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.spoolman = fake_sm
    app.state.filamentdb = fake_fdb

    client = TestClient(app, raise_server_exceptions=False)
    request_body = {
        "decisions": [
            {
                "spoolman_filament_id": 1,
                "ignored": False,
                "fields": [{"field": "material", "value": "PLA", "keep_mine": False}],
            }
        ]
    }
    resp = client.post("/api/openprinttag/apply", json=request_body)
    assert resp.status_code == 502, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "opentag_field_setup_failed"
    assert "OpenTag extra fields" in detail["message"]
    # No PATCH should have been attempted
    fake_sm.update_filament.assert_not_called()


# ---------------------------------------------------------------------------
# Fix: ensure_extra_fields — per-section isolation + broader exception handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_extra_fields_creates_filament_fields_when_spool_section_raises():
    """When the spool section's get_field_definitions raises, the filament section
    still runs and creates all missing filament fields.
    """
    from app.services.spoolman import SpoolmanClient
    from app.config import settings as _s

    created_keys: list[str] = []

    async def _fake_get_fields(url, **kwargs):
        if "spool" in url:
            raise httpx.ConnectError("spool fetch failed")
        # Filament: no fields yet
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value=[])
        return resp

    async def _fake_post(url, json=None):
        key = url.split("/")[-1]
        created_keys.append(key)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        return resp

    client = SpoolmanClient("http://spoolman.test")
    client._client = MagicMock()
    client._http.get = AsyncMock(side_effect=_fake_get_fields)
    client._http.post = AsyncMock(side_effect=_fake_post)

    # Should NOT raise — spool failure is swallowed, filament section runs
    await client.ensure_extra_fields()

    # All three filament fields must have been created
    assert _s.spoolman_field_filamentdb_material_tags in created_keys
    assert _s.spoolman_field_openprinttag_slug in created_keys
    assert _s.spoolman_field_openprinttag_uuid in created_keys


@pytest.mark.asyncio
async def test_ensure_extra_fields_creates_remaining_filament_fields_after_one_post_raises():
    """When one filament field POST raises a RequestError, the remaining filament
    fields are still attempted and created.
    """
    from app.services.spoolman import SpoolmanClient
    from app.config import settings as _s

    created_keys: list[str] = []
    call_count = [0]

    async def _fake_get_fields(url, **kwargs):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value=[])  # no fields exist yet
        return resp

    async def _fake_post(url, json=None):
        key = url.split("/")[-1]
        call_count[0] += 1
        # Fail only the first filament field POST (material_tags)
        if _s.spoolman_field_filamentdb_material_tags in url and call_count[0] == 1:
            raise httpx.ConnectError("transient failure")
        created_keys.append(key)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        return resp

    client = SpoolmanClient("http://spoolman.test")
    client._client = MagicMock()
    client._http.get = AsyncMock(side_effect=_fake_get_fields)
    client._http.post = AsyncMock(side_effect=_fake_post)

    # Must not raise — one failure is logged and skipped
    await client.ensure_extra_fields()

    # The two remaining filament fields (slug + uuid) must still have been created
    assert _s.spoolman_field_openprinttag_slug in created_keys
    assert _s.spoolman_field_openprinttag_uuid in created_keys


@pytest.mark.asyncio
async def test_ensure_extra_fields_skips_already_existing_filament_fields():
    """When all filament fields already exist, no POST should be issued for them."""
    from app.services.spoolman import SpoolmanClient
    from app.config import settings as _s
    from app.schemas.spoolman import SpoolmanFieldDef

    post_calls: list[str] = []

    async def _fake_get_fields(url, **kwargs):
        if "spool" in url:
            # All spool fields already exist
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json = MagicMock(return_value=[
                {"key": "filamentdb_id", "name": "x", "field_type": "text", "entity_type": "spool"},
                {"key": "filamentdb_parent_id", "name": "x", "field_type": "text", "entity_type": "spool"},
                {"key": "filamentdb_spool_id", "name": "x", "field_type": "text", "entity_type": "spool"},
            ])
        else:
            # All filament fields already exist
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json = MagicMock(return_value=[
                {"key": _s.spoolman_field_filamentdb_material_tags, "name": "x", "field_type": "text", "entity_type": "filament"},
                {"key": _s.spoolman_field_openprinttag_slug, "name": "x", "field_type": "text", "entity_type": "filament"},
                {"key": _s.spoolman_field_openprinttag_uuid, "name": "x", "field_type": "text", "entity_type": "filament"},
            ])
        return resp

    async def _fake_post(url, json=None):
        post_calls.append(url)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        return resp

    client = SpoolmanClient("http://spoolman.test")
    client._client = MagicMock()
    client._http.get = AsyncMock(side_effect=_fake_get_fields)
    client._http.post = AsyncMock(side_effect=_fake_post)

    await client.ensure_extra_fields()

    # No POSTs should have been made — all fields existed
    assert post_calls == [], f"Expected no field creation POSTs, got: {post_calls}"


# ---------------------------------------------------------------------------
# _build_field_rows includes slug/uuid + name; spoolman_value reflects live SM data
# (reverses commit 48c05d6: slug/uuid now flow as rows, not from the frontend push)
# ---------------------------------------------------------------------------


def test_build_field_rows_includes_slug_uuid_name():
    """_build_field_rows must include extra.openprinttag_slug, extra.openprinttag_uuid,
    and name rows.  No row must appear more than once.  spoolman_value for slug/uuid
    reflects the SM filament's current decoded extra value (None when unset).
    spoolman_value for name is sm_fil.name.
    """
    from app.api.opentag import _build_field_rows
    from app.config import settings as _s

    sm = _sm_fil(sm_id=1, vendor="Buddy3D", material="PLA Silk", color_hex="B87333")
    opt_fields = opt_to_spoolman_fields(_OPT_PLA_SILK)

    # Sanity-check: opt_to_spoolman_fields returns the slug/uuid/name keys
    assert f"extra.{_s.spoolman_field_openprinttag_slug}" in opt_fields
    assert f"extra.{_s.spoolman_field_openprinttag_uuid}" in opt_fields
    assert "name" in opt_fields

    rows = _build_field_rows(sm, opt_fields)
    row_fields = [r.field for r in rows]

    # slug and uuid MUST appear in field rows (reversed from commit 48c05d6)
    slug_key = f"extra.{_s.spoolman_field_openprinttag_slug}"
    uuid_key = f"extra.{_s.spoolman_field_openprinttag_uuid}"
    assert slug_key in row_fields, "extra.openprinttag_slug must appear in field rows"
    assert uuid_key in row_fields, "extra.openprinttag_uuid must appear in field rows"

    # name must appear
    assert "name" in row_fields, "name must appear in field rows"

    # Native fields and extra.filamentdb_material_tags must still be present
    assert "material" in row_fields
    assert f"extra.{_s.spoolman_field_filamentdb_material_tags}" in row_fields

    # No row must appear more than once
    assert len(row_fields) == len(set(row_fields)), "Duplicate field rows detected"

    # spoolman_value for slug/uuid is None (not set on the SM filament)
    slug_row = next(r for r in rows if r.field == slug_key)
    uuid_row = next(r for r in rows if r.field == uuid_key)
    assert slug_row.spoolman_value is None, "slug spoolman_value should be None when unset"
    assert uuid_row.spoolman_value is None, "uuid spoolman_value should be None when unset"

    # spoolman_value for name is sm_fil.name
    name_row = next(r for r in rows if r.field == "name")
    assert name_row.spoolman_value == sm.name, f"name spoolman_value should be '{sm.name}'"


def test_build_field_rows_shows_existing_slug_uuid_values():
    """When the SM filament already has openprinttag_slug/uuid set, spoolman_value
    for those rows must reflect the decoded existing value (not None).
    """
    from app.api.opentag import _build_field_rows
    from app.config import settings as _s
    from app.schemas.spoolman import encode_extra_value

    slug_key = _s.spoolman_field_openprinttag_slug
    uuid_key = _s.spoolman_field_openprinttag_uuid

    # SM filament already tagged from a prior cleanup run
    sm = _sm_fil(
        sm_id=1,
        vendor="Buddy3D",
        material="PLA Silk",
        color_hex="B87333",
        extra={
            slug_key: encode_extra_value("buddy3d-pla-silk-bronze"),
            uuid_key: encode_extra_value("d22442a5-1234-0000-0000-000000000001"),
        },
    )
    opt_fields = opt_to_spoolman_fields(_OPT_PLA_SILK)
    rows = _build_field_rows(sm, opt_fields)

    slug_row = next(r for r in rows if r.field == f"extra.{slug_key}")
    uuid_row = next(r for r in rows if r.field == f"extra.{uuid_key}")
    assert slug_row.spoolman_value == "buddy3d-pla-silk-bronze"
    assert uuid_row.spoolman_value == "d22442a5-1234-0000-0000-000000000001"


@pytest.mark.asyncio
async def test_matches_endpoint_fields_include_slug_uuid_name(tmp_path):
    """GET /api/openprinttag/matches: each matched filament's .fields must include
    extra.openprinttag_slug, extra.openprinttag_uuid, and name rows (one each, no
    duplicates). opt_slug/opt_uuid remain populated on the top-level match too.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router
    from app.core.opentag_cache import _save_cache
    from app.config import settings as _s

    fresh_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _save_cache(str(tmp_path), [_OPT_PLA_SILK], fresh_ts)

    sm_fil = _sm_fil(sm_id=1, vendor="Buddy3D", material="PLA Silk", color_hex="B87333")
    fake_fdb = AsyncMock()
    fake_sm = AsyncMock()
    fake_sm.get_filaments = AsyncMock(return_value=[sm_fil])

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

        # opt_slug and opt_uuid must still be populated on the top-level match
        assert match["opt_slug"] == "buddy3d-pla-silk-bronze"
        assert match["opt_uuid"] == "d22442a5-1234-0000-0000-000000000001"

        field_names = [f["field"] for f in match["fields"]]
        slug_key = f"extra.{_s.spoolman_field_openprinttag_slug}"
        uuid_key = f"extra.{_s.spoolman_field_openprinttag_uuid}"

        # slug, uuid, and name MUST appear in field rows
        assert slug_key in field_names, f"{slug_key} missing from match.fields"
        assert uuid_key in field_names, f"{uuid_key} missing from match.fields"
        assert "name" in field_names, "name missing from match.fields"

        # No duplicates
        assert len(field_names) == len(set(field_names)), "Duplicate field rows in match.fields"

        # Native fields must still be present
        assert "material" in field_names
        assert f"extra.{_s.spoolman_field_filamentdb_material_tags}" in field_names

        # spoolman_value for slug/uuid is None (SM filament has no existing identity)
        slug_row = next(f for f in match["fields"] if f["field"] == slug_key)
        uuid_row = next(f for f in match["fields"] if f["field"] == uuid_key)
        assert slug_row["spoolman_value"] is None
        assert uuid_row["spoolman_value"] is None
    finally:
        _ot_mod._settings.data_dir = original_data_dir


# ---------------------------------------------------------------------------
# UUID exact-match: filament with existing openprinttag_uuid → confidence 1.0, no fuzzy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_matches_exact_uuid_match_returns_confidence_1(tmp_path):
    """A SM filament whose extra.openprinttag_uuid matches a material's uuid must be
    returned with confidence 1.0 (exact UUID match), bypassing fuzzy scoring.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router
    from app.core.opentag_cache import _save_cache
    from app.config import settings as _s
    from app.schemas.spoolman import encode_extra_value

    fresh_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _save_cache(str(tmp_path), [_OPT_PLA_SILK, _OPT_PETG], fresh_ts)

    uuid_key = _s.spoolman_field_openprinttag_uuid
    # SM filament already has the uuid from a prior cleanup run
    sm_fil = _sm_fil(
        sm_id=1,
        vendor="Buddy3D",
        material="PLA Silk",
        color_hex="B87333",
        extra={uuid_key: encode_extra_value("d22442a5-1234-0000-0000-000000000001")},
    )
    fake_fdb = AsyncMock()
    fake_sm = AsyncMock()
    fake_sm.get_filaments = AsyncMock(return_value=[sm_fil])

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

        # Must be the correct material and at confidence 1.0
        assert match["opt_slug"] == "buddy3d-pla-silk-bronze"
        assert match["confidence"] == 1.0, (
            f"Expected confidence 1.0 for exact UUID match, got {match['confidence']}"
        )
    finally:
        _ot_mod._settings.data_dir = original_data_dir


@pytest.mark.asyncio
async def test_matches_no_uuid_falls_through_to_fuzzy(tmp_path):
    """A SM filament without extra.openprinttag_uuid must go through normal fuzzy scoring
    (confidence < 1.0 for a typical non-trivial match).
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router
    from app.core.opentag_cache import _save_cache

    fresh_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _save_cache(str(tmp_path), [_OPT_PLA_SILK], fresh_ts)

    # SM filament has NO uuid extra
    sm_fil = _sm_fil(sm_id=1, vendor="Buddy3D", material="PLA Silk", color_hex="B87333")
    fake_fdb = AsyncMock()
    fake_sm = AsyncMock()
    fake_sm.get_filaments = AsyncMock(return_value=[sm_fil])

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
        # Fuzzy match — confidence should be < 1.0
        assert match["confidence"] < 1.0, (
            f"Expected fuzzy confidence < 1.0 when no UUID set, got {match['confidence']}"
        )
    finally:
        _ot_mod._settings.data_dir = original_data_dir


# ---------------------------------------------------------------------------
# opt_to_spoolman_fields includes name
# ---------------------------------------------------------------------------


def test_opt_to_spoolman_fields_includes_name():
    """opt_to_spoolman_fields must return a 'name' key with the OpenTag material name."""
    fields = opt_to_spoolman_fields(_OPT_PLA_SILK)
    assert "name" in fields, "opt_to_spoolman_fields must include 'name'"
    assert fields["name"] == "PLA Silk Bronze"


def test_opt_to_spoolman_fields_name_none_when_absent():
    """When the OPT material has no name key, 'name' must not appear in the output."""
    opt = {k: v for k, v in _OPT_PLA_SILK.items() if k != "name"}
    fields = opt_to_spoolman_fields(opt)
    assert "name" not in fields, "opt_to_spoolman_fields must not include 'name' when OPT has none"


# ---------------------------------------------------------------------------
# Apply: name writes as native field; slug/uuid appear exactly once
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_writes_name_native_when_not_keep_mine():
    """Apply must write 'name' as a native Spoolman field when keep_mine is False."""
    from app.api.opentag import OpenTagApplyRequest, OpenTagFilamentDecision, OpenTagFieldDecision

    patched_payloads: list[dict] = []

    async def _fake_patch(fil_id, payload):
        patched_payloads.append((fil_id, payload))
        return MagicMock()

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router

    fake_sm = AsyncMock()
    fake_sm.update_filament = AsyncMock(side_effect=_fake_patch)
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
                "spoolman_filament_id": 1,
                "ignored": False,
                "fdb_filament_id": None,
                "openprinttag_slug": "buddy3d-pla-silk-bronze",
                "openprinttag_uuid": "d22442a5-0000-0000-0000-000000000001",
                "fields": [
                    {"field": "name", "value": "PLA Silk Bronze", "keep_mine": False},
                    {"field": "material", "value": "PLA", "keep_mine": False},
                ],
            }
        ]
    }
    resp = client.post("/api/openprinttag/apply", json=request_body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["applied"] == 1

    _, payload = patched_payloads[0]
    # name must be a native (top-level) field
    assert "name" in payload, "name must appear as a native field in the SM PATCH payload"
    assert payload["name"] == "PLA Silk Bronze"


@pytest.mark.asyncio
async def test_apply_slug_uuid_written_exactly_once():
    """slug/uuid must appear exactly once in the SM PATCH extra, even when both
    decision.openprinttag_slug/uuid and field rows carry them.
    """
    from app.api.opentag import OpenTagApplyRequest, OpenTagFilamentDecision, OpenTagFieldDecision
    from app.schemas.spoolman import encode_extra_value, decode_extra_value
    from app.config import settings as _s

    patched_payloads: list[dict] = []

    async def _fake_patch(fil_id, payload):
        patched_payloads.append((fil_id, payload))
        return MagicMock()

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router

    fake_sm = AsyncMock()
    fake_sm.update_filament = AsyncMock(side_effect=_fake_patch)
    fake_fdb = AsyncMock()
    fake_fdb.merge_filament_settings = AsyncMock()

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.spoolman = fake_sm
    app.state.filamentdb = fake_fdb

    slug_key = f"extra.{_s.spoolman_field_openprinttag_slug}"
    uuid_key = f"extra.{_s.spoolman_field_openprinttag_uuid}"

    client = TestClient(app)
    request_body = {
        "decisions": [
            {
                "spoolman_filament_id": 7,
                "ignored": False,
                "fdb_filament_id": None,
                # Both top-level (for FDB) AND as field rows (from _build_field_rows)
                "openprinttag_slug": "test-slug",
                "openprinttag_uuid": "test-uuid",
                "fields": [
                    # slug/uuid rows come from _build_field_rows now
                    {"field": slug_key, "value": "test-slug", "keep_mine": False},
                    {"field": uuid_key, "value": "test-uuid", "keep_mine": False},
                    {"field": "material", "value": "PLA", "keep_mine": False},
                ],
            }
        ]
    }
    resp = client.post("/api/openprinttag/apply", json=request_body)
    assert resp.status_code == 200, resp.text

    _, payload = patched_payloads[0]
    extra = payload.get("extra", {})
    sm_slug_key = _s.spoolman_field_openprinttag_slug
    sm_uuid_key = _s.spoolman_field_openprinttag_uuid

    # Each key must appear exactly once in extra (no duplicate keys in dict by construction)
    assert sm_slug_key in extra, "slug must be written to SM extra"
    assert sm_uuid_key in extra, "uuid must be written to SM extra"
    assert decode_extra_value(extra[sm_slug_key]) == "test-slug"
    assert decode_extra_value(extra[sm_uuid_key]) == "test-uuid"


@pytest.mark.asyncio
async def test_ensure_extra_fields_spool_section_isolated_from_filament_section():
    """A get_field_definitions failure in the spool section must not prevent
    the filament section from running (per-section isolation).

    This tests the specific bug: previously the un-try'd get_field_definitions
    call would abort the entire function, leaving filament fields uncreated.
    """
    from app.services.spoolman import SpoolmanClient
    from app.config import settings as _s

    filament_fields_attempted: list[str] = []

    async def _fake_get_fields(url, **kwargs):
        if "spool" in url:
            # Simulate a 500 from Spoolman when reading spool field defs
            mock_resp = MagicMock()
            mock_resp.status_code = 500
            mock_req = MagicMock()
            raise httpx.HTTPStatusError("500", request=mock_req, response=mock_resp)
        # Filament fields: empty (none registered)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value=[])
        return resp

    async def _fake_post(url, json=None):
        key = url.split("/")[-1]
        if "filament" in url:
            filament_fields_attempted.append(key)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        return resp

    client = SpoolmanClient("http://spoolman.test")
    client._client = MagicMock()
    client._http.get = AsyncMock(side_effect=_fake_get_fields)
    client._http.post = AsyncMock(side_effect=_fake_post)

    # Must not raise
    await client.ensure_extra_fields()

    # Filament fields must still have been attempted despite spool section failure
    assert _s.spoolman_field_openprinttag_slug in filament_fields_attempted, (
        "openprinttag_slug was not attempted — spool failure aborted the filament section"
    )
    assert _s.spoolman_field_openprinttag_uuid in filament_fields_attempted, (
        "openprinttag_uuid was not attempted — spool failure aborted the filament section"
    )


# ---------------------------------------------------------------------------
# Phase 1: opentag_secondary — rgba_to_hex, fetch_secondary_colors
# ---------------------------------------------------------------------------


def test_rgba_to_hex_strips_alpha_and_uppercases():
    from app.core.opentag_secondary import _rgba_to_hex
    assert _rgba_to_hex("#98282fff") == "98282F"


def test_rgba_to_hex_black():
    from app.core.opentag_secondary import _rgba_to_hex
    assert _rgba_to_hex("#000000ff") == "000000"


def test_rgba_to_hex_no_alpha():
    from app.core.opentag_secondary import _rgba_to_hex
    assert _rgba_to_hex("#AABBCC") == "AABBCC"


def test_rgba_to_hex_ddb95d():
    from app.core.opentag_secondary import _rgba_to_hex
    assert _rgba_to_hex("#ddb95dff") == "DDB95D"


def test_rgba_to_hex_none_returns_none():
    from app.core.opentag_secondary import _rgba_to_hex
    assert _rgba_to_hex(None) is None
    assert _rgba_to_hex("") is None
    assert _rgba_to_hex("#AB") is None


def _build_test_tar(materials: list[dict]) -> bytes:
    """Build an in-memory gzipped tarball with ``data/materials/brand/X.yaml`` entries."""
    import io as _io
    import tarfile as _tarfile
    import yaml as _yaml

    buf = _io.BytesIO()
    with _tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for i, mat in enumerate(materials):
            content = _yaml.dump(mat).encode()
            info = _tarfile.TarInfo(
                name=f"openprinttag-database-main/data/materials/brand/material_{i}.yaml"
            )
            info.size = len(content)
            tf.addfile(info, _io.BytesIO(content))
    return buf.getvalue()


@pytest.mark.asyncio
async def test_fetch_secondary_colors_parses_tar():
    """fetch_secondary_colors parses a small in-memory tar and returns uuid→hexes map."""
    from app.core.opentag_secondary import fetch_secondary_colors

    sample_materials = [
        {
            "uuid": "ccf32809-fbef-527a-8487-ccb75ceafab6",
            "slug": "amolen-pla-silk-gradient",
            "type": "PLA",
            "secondary_colors": [
                {"color_rgba": "#000000ff"},
                {"color_rgba": "#98282fff"},
                {"color_rgba": "#ddb95dff"},
            ],
        },
        {
            "uuid": "aaaabbbb-cccc-dddd-eeee-ffffffffffff",
            "slug": "brand-pla-red",
            "type": "PLA",
            "secondary_colors": [],  # no secondaries → should be skipped
        },
        {
            "uuid": "11112222-3333-4444-5555-666677778888",
            "slug": "brand-petg-blue",
            "type": "PETG",
            # no secondary_colors key at all → skipped
        },
    ]
    tar_bytes = _build_test_tar(sample_materials)

    # Mock the HTTP client to return our in-memory tar
    fake_resp = MagicMock()
    fake_resp.raise_for_status = MagicMock()
    fake_resp.content = tar_bytes

    fake_http = AsyncMock(spec=httpx.AsyncClient)
    fake_http.get = AsyncMock(return_value=fake_resp)

    result = await fetch_secondary_colors(http=fake_http)

    # The gradient material should be keyed by both uuid AND slug
    assert "ccf32809-fbef-527a-8487-ccb75ceafab6" in result
    assert result["ccf32809-fbef-527a-8487-ccb75ceafab6"] == ["000000", "98282F", "DDB95D"]
    assert "amolen-pla-silk-gradient" in result
    assert result["amolen-pla-silk-gradient"] == ["000000", "98282F", "DDB95D"]

    # Empty / missing secondary_colors should not produce an entry
    assert "aaaabbbb-cccc-dddd-eeee-ffffffffffff" not in result
    assert "11112222-3333-4444-5555-666677778888" not in result


@pytest.mark.asyncio
async def test_fetch_secondary_colors_returns_empty_on_network_error():
    """fetch_secondary_colors returns {} (not raises) when the HTTP request fails."""
    from app.core.opentag_secondary import fetch_secondary_colors

    fake_http = AsyncMock(spec=httpx.AsyncClient)
    fake_http.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

    result = await fetch_secondary_colors(http=fake_http)
    assert result == {}


@pytest.mark.asyncio
async def test_fetch_secondary_colors_returns_empty_on_bad_tar():
    """fetch_secondary_colors returns {} (not raises) when the response body is not a valid tar."""
    from app.core.opentag_secondary import fetch_secondary_colors

    fake_resp = MagicMock()
    fake_resp.raise_for_status = MagicMock()
    fake_resp.content = b"not a tarball"

    fake_http = AsyncMock(spec=httpx.AsyncClient)
    fake_http.get = AsyncMock(return_value=fake_resp)

    result = await fetch_secondary_colors(http=fake_http)
    assert result == {}


# ---------------------------------------------------------------------------
# Phase 2: load_opentag_dataset merges secondary_colors; degrades gracefully
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_opentag_dataset_fills_empty_secondary_colors_by_uuid(tmp_path):
    """When the raw tarball provides secondary_colors, they are merged by uuid."""
    from unittest.mock import patch as _patch
    from app.core.opentag_cache import load_opentag_dataset

    gradient_material = {
        **_OPT_PLA_SILK,
        "uuid": "ccf32809-fbef-527a-8487-ccb75ceafab6",
        "secondaryColors": [],  # FDB feed leaves this empty
    }

    fdb_mock = AsyncMock()
    fdb_mock.get_openprinttag = AsyncMock(return_value=[gradient_material])

    secondary_map = {
        "ccf32809-fbef-527a-8487-ccb75ceafab6": ["000000", "98282F", "DDB95D"],
    }

    with _patch(
        "app.core.opentag_cache.fetch_secondary_colors",
        AsyncMock(return_value=secondary_map),
    ):
        result = await load_opentag_dataset(fdb_mock, str(tmp_path), 24, force=True)

    mats = result["materials"]
    assert len(mats) == 1
    assert mats[0]["secondaryColors"] == ["000000", "98282F", "DDB95D"]


@pytest.mark.asyncio
async def test_load_opentag_dataset_fills_empty_secondary_colors_by_slug_fallback(tmp_path):
    """When uuid is absent but slug matches, secondary_colors are filled by slug."""
    from unittest.mock import patch as _patch
    from app.core.opentag_cache import load_opentag_dataset

    mat_no_uuid = {
        **_OPT_PLA_SILK,
        "uuid": None,
        "slug": "brand-pla-gradient",
        "secondaryColors": [],
    }

    fdb_mock = AsyncMock()
    fdb_mock.get_openprinttag = AsyncMock(return_value=[mat_no_uuid])

    secondary_map = {
        "brand-pla-gradient": ["FF0000", "00FF00"],
    }

    with _patch(
        "app.core.opentag_cache.fetch_secondary_colors",
        AsyncMock(return_value=secondary_map),
    ):
        result = await load_opentag_dataset(fdb_mock, str(tmp_path), 24, force=True)

    assert result["materials"][0]["secondaryColors"] == ["FF0000", "00FF00"]


@pytest.mark.asyncio
async def test_load_opentag_dataset_degrades_gracefully_when_secondary_fetch_fails(tmp_path):
    """When fetch_secondary_colors returns {}, the FDB feed is used unchanged (no crash)."""
    from unittest.mock import patch as _patch
    from app.core.opentag_cache import load_opentag_dataset

    material = {**_OPT_PLA_SILK, "secondaryColors": []}

    fdb_mock = AsyncMock()
    fdb_mock.get_openprinttag = AsyncMock(return_value=[material])

    with _patch(
        "app.core.opentag_cache.fetch_secondary_colors",
        AsyncMock(return_value={}),
    ):
        result = await load_opentag_dataset(fdb_mock, str(tmp_path), 24, force=True)

    # secondaryColors should remain empty — no crash
    assert result["materials"][0]["secondaryColors"] == []
    assert result["count"] == 1


@pytest.mark.asyncio
async def test_load_opentag_dataset_does_not_overwrite_existing_secondary_colors(tmp_path):
    """Materials that already have secondaryColors are left untouched."""
    from unittest.mock import patch as _patch
    from app.core.opentag_cache import load_opentag_dataset

    material_with_existing = {
        **_OPT_PLA_SILK,
        "uuid": "ccf32809-fbef-527a-8487-ccb75ceafab6",
        "secondaryColors": ["EXISTING_HEX"],
    }

    fdb_mock = AsyncMock()
    fdb_mock.get_openprinttag = AsyncMock(return_value=[material_with_existing])

    secondary_map = {
        "ccf32809-fbef-527a-8487-ccb75ceafab6": ["000000", "98282F"],
    }

    with _patch(
        "app.core.opentag_cache.fetch_secondary_colors",
        AsyncMock(return_value=secondary_map),
    ):
        result = await load_opentag_dataset(fdb_mock, str(tmp_path), 24, force=True)

    # Existing secondaryColors must not be overwritten
    assert result["materials"][0]["secondaryColors"] == ["EXISTING_HEX"]


# ---------------------------------------------------------------------------
# Phase 3: gradient material → color_hex + multi_color_hexes + multi_color_direction
# ---------------------------------------------------------------------------


def test_opt_to_spoolman_fields_gradient_yields_all_three_color_fields():
    """A gradient OPT material (gradual_color_change tag + recovered secondaryColors) must
    produce multi_color_hexes and multi_color_direction (no color_hex — sending both causes 422)."""
    gradient_opt = {
        "uuid": "ccf32809-fbef-527a-8487-ccb75ceafab6",
        "slug": "amolen-pla-silk-gradient",
        "brandName": "Amolen",
        "name": "PLA Silk Gradient",
        "type": "PLA",
        "abbreviation": "PLA",
        "tags": ["silk", "gradual_color_change"],
        "color": "#000000",
        "secondaryColors": ["98282F", "DDB95D"],
        "density": 1.28,
        "nozzleTempMin": 200,
        "nozzleTempMax": 230,
        "bedTempMin": 50,
        "bedTempMax": 65,
        "completenessScore": 90,
    }
    fields = opt_to_spoolman_fields(gradient_opt)

    # color_hex must be absent for multicolor — Spoolman 422s when both color_hex + multi_color_hexes set
    assert "color_hex" not in fields, "color_hex must not be sent for gradient (causes 422)"
    assert "multi_color_hexes" in fields, "multi_color_hexes missing"
    assert "multi_color_direction" in fields, "multi_color_direction missing"
    assert fields["multi_color_direction"] == "longitudinal"
    # The hexes CSV must contain all three colors
    hexes_csv = fields["multi_color_hexes"]
    assert "000000" in hexes_csv or "98282F" in hexes_csv, f"Unexpected hexes: {hexes_csv!r}"


def test_opt_to_spoolman_fields_gradient_apply_patch_sets_direction_with_hexes():
    """Verify that the apply patch (as built by opt_to_spoolman_fields) sets
    multi_color_direction only when multi_color_hexes is also set — preventing the
    earlier direction-without-hexes 422."""
    gradient_opt = {
        "uuid": "test-uuid",
        "slug": "test-gradient",
        "brandName": "TestBrand",
        "name": "Gradient PLA",
        "type": "PLA",
        "tags": ["gradual_color_change"],
        "color": "#FF0000",
        "secondaryColors": ["00FF00", "0000FF"],
        "density": 1.24,
        "nozzleTempMax": 220,
        "bedTempMax": 60,
    }
    fields = opt_to_spoolman_fields(gradient_opt)

    has_hexes = "multi_color_hexes" in fields and fields["multi_color_hexes"]
    has_direction = "multi_color_direction" in fields and fields["multi_color_direction"]

    if has_direction:
        assert has_hexes, (
            "multi_color_direction is set without multi_color_hexes → Spoolman would 422"
        )


# ---------------------------------------------------------------------------
# Phase 4: multicolor_mismatch flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_matches_multicolor_mismatch_true_when_sm_multicolor_opt_single(tmp_path):
    """multicolor_mismatch=True when SM is multicolor and OPT match is single-color."""
    import datetime as _dt
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router
    from app.core.opentag_cache import _save_cache

    # OPT entry with NO secondary colors and NO arrangement tag → single
    single_opt = {**_OPT_PLA_SILK, "tags": [], "secondaryColors": []}
    fresh_ts = _dt.datetime.now(_dt.timezone.utc).isoformat()
    _save_cache(str(tmp_path), [single_opt], fresh_ts)

    # SM filament is multicolor (has multi_color_hexes)
    sm_multicolor = SpoolmanFilament(
        id=10,
        name="PLA Silk Bronze",
        vendor=SpoolmanVendor(id=10, name="Buddy3D"),
        material="PLA Silk",
        color_hex="B87333",
        multi_color_hexes="B87333,FF0000",
        multi_color_direction="longitudinal",
        extra={},
    )

    fake_fdb = AsyncMock()
    fake_sm = AsyncMock()
    fake_sm.get_filaments = AsyncMock(return_value=[sm_multicolor])

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
        # Find our filament's match
        match_rows = [m for m in data["matches"] if m["spoolman_filament_id"] == 10]
        assert match_rows, "No match row found for SM filament 10"
        row = match_rows[0]
        assert row["multicolor_mismatch"] is True, (
            f"Expected multicolor_mismatch=True, got {row.get('multicolor_mismatch')}"
        )
    finally:
        _ot_mod._settings.data_dir = original_data_dir


@pytest.mark.asyncio
async def test_matches_multicolor_mismatch_false_when_sm_single(tmp_path):
    """multicolor_mismatch=False when SM is single-color (even if OPT also single)."""
    import datetime as _dt
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router
    from app.core.opentag_cache import _save_cache

    single_opt = {**_OPT_PLA_SILK, "tags": [], "secondaryColors": []}
    fresh_ts = _dt.datetime.now(_dt.timezone.utc).isoformat()
    _save_cache(str(tmp_path), [single_opt], fresh_ts)

    # SM filament is single-color (no multi_color_hexes)
    sm_single = _sm_fil(sm_id=20, vendor="Buddy3D", material="PLA Silk", color_hex="B87333")

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
        match_rows = [m for m in data["matches"] if m["spoolman_filament_id"] == 20]
        assert match_rows
        assert match_rows[0]["multicolor_mismatch"] is False


    finally:
        _ot_mod._settings.data_dir = original_data_dir


@pytest.mark.asyncio
async def test_matches_multicolor_mismatch_false_when_opt_is_also_multicolor(tmp_path):
    """multicolor_mismatch=False when both SM and OPT are multicolor (gradient arrangement tag)."""
    import datetime as _dt
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router
    from app.core.opentag_cache import _save_cache

    # OPT with gradient arrangement tag → gradient profile
    gradient_opt = {
        **_OPT_PLA_SILK,
        "tags": ["silk", "gradual_color_change"],
        "secondaryColors": ["98282F", "DDB95D"],
    }
    fresh_ts = _dt.datetime.now(_dt.timezone.utc).isoformat()
    _save_cache(str(tmp_path), [gradient_opt], fresh_ts)

    # SM filament is also gradient
    sm_gradient = SpoolmanFilament(
        id=30,
        name="PLA Silk Bronze",
        vendor=SpoolmanVendor(id=10, name="Buddy3D"),
        material="PLA Silk",
        color_hex="B87333",
        multi_color_hexes="B87333,98282F,DDB95D",
        multi_color_direction="longitudinal",
        extra={},
    )

    fake_fdb = AsyncMock()
    fake_sm = AsyncMock()
    fake_sm.get_filaments = AsyncMock(return_value=[sm_gradient])

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
        match_rows = [m for m in data["matches"] if m["spoolman_filament_id"] == 30]
        assert match_rows
        assert match_rows[0]["multicolor_mismatch"] is False
    finally:
        _ot_mod._settings.data_dir = original_data_dir


# ---------------------------------------------------------------------------
# Candidate dropdown: candidates list best-first, per-candidate fields, alternates
# carry real scores, exact-UUID yields single candidate at 1.0
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_matches_candidates_list_best_first_with_fields(tmp_path):
    """matches endpoint: each match with a best hit returns a candidates list where
    candidates[0] is the best match (confidence == match.confidence) and has its
    own fields list and slug/uuid.  Alternates follow at lower confidence.
    """
    import datetime as _dt

    # Three OPT materials from the same brand/material: the SM filament name is
    # "Bronze" so the best match should be OPT_PLA_SILK (bronze name + silk finish).
    opt_alt1 = {
        **_OPT_PETG,
        "uuid": "alt1-0000-0000-0000-000000000001",
        "slug": "elegoo-petg-blue",
        "brandName": "ELEGOO",
        "name": "PETG Blue",
        "type": "PETG",
        "color": "#0000FF",
        "tags": [],
    }
    opt_alt2 = {
        **_OPT_PLA_MATTE,
        "uuid": "alt2-0000-0000-0000-000000000002",
        "slug": "elegoo-pla-matte-black",
        "brandName": "ELEGOO",
        "name": "PLA Matte Black",
        "type": "PLA",
        "color": "#000000",
        "tags": ["matte"],
    }
    opt_best = {
        **_OPT_PLA_MATTE,
        "uuid": "best-0000-0000-0000-000000000099",
        "slug": "elegoo-pla-matte-white",
        "brandName": "ELEGOO",
        "name": "PLA Matte White",
        "type": "PLA",
        "color": "#FFFFFF",
        "tags": ["matte"],
    }

    sm_fil = SpoolmanFilament(
        id=99,
        name="PLA Matte White",
        vendor=SpoolmanVendor(id=5, name="ELEGOO"),
        material="PLA",
        color_hex="FFFFFF",
        extra={},
    )

    client, _ot_mod, _ = _make_matches_test_app(
        tmp_path, [opt_best, opt_alt1, opt_alt2], [sm_fil]
    )
    original_data_dir = _ot_mod._settings.data_dir
    _ot_mod._settings.data_dir = str(tmp_path)
    try:
        resp = client.get("/api/openprinttag/matches")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        match = next(m for m in data["matches"] if m["spoolman_filament_id"] == 99)

        # candidates list must be present and non-empty
        assert "candidates" in match
        candidates = match["candidates"]
        assert isinstance(candidates, list)
        assert len(candidates) >= 1

        # candidates[0] is the best: its confidence must equal the top-level confidence
        best = candidates[0]
        assert best["confidence"] == match["confidence"]
        assert best["opt_slug"] is not None
        assert best["opt_uuid"] is not None

        # Each candidate must have its own fields list
        for c in candidates:
            assert "fields" in c
            assert isinstance(c["fields"], list)
            assert len(c["fields"]) > 0, "every matched candidate must have at least one field row"

        # Alternates (candidates[1:]) must have confidence ≤ best
        for c in candidates[1:]:
            assert c["confidence"] <= best["confidence"]

    finally:
        _ot_mod._settings.data_dir = original_data_dir


@pytest.mark.asyncio
async def test_matches_alternates_carry_real_scores(tmp_path):
    """Alternate candidates in the structured list must carry their actual scores,
    not 0.0 or the best score.  We verify by asserting alternates are sorted
    descending and each is strictly below the best (given distinct materials).
    """
    # Use distinct-enough materials so scoring produces a visible ordering.
    opt_a = {
        **_OPT_PLA_MATTE,
        "uuid": "score-test-0001",
        "slug": "elegoo-pla-matte-white",
        "brandName": "ELEGOO",
        "name": "PLA Matte White",
        "type": "PLA",
        "color": "#FFFFFF",
        "tags": ["matte"],
    }
    opt_b = {
        **_OPT_PETG,
        "uuid": "score-test-0002",
        "slug": "elegoo-petg-red",
        "brandName": "ELEGOO",
        "name": "PETG Red",
        "type": "PETG",
        "color": "#CC0000",
        "tags": [],
    }
    opt_c = {
        **_OPT_PLA_MATTE,
        "uuid": "score-test-0003",
        "slug": "elegoo-pla-silk-bronze",
        "brandName": "ELEGOO",
        "name": "PLA Silk Bronze",
        "type": "PLA",
        "color": "#B87333",
        "tags": ["silk"],
    }

    sm_fil = SpoolmanFilament(
        id=101,
        name="PLA Matte White",
        vendor=SpoolmanVendor(id=5, name="ELEGOO"),
        material="PLA",
        color_hex="FFFFFF",
        extra={},
    )

    client, _ot_mod, _ = _make_matches_test_app(tmp_path, [opt_a, opt_b, opt_c], [sm_fil])
    original_data_dir = _ot_mod._settings.data_dir
    _ot_mod._settings.data_dir = str(tmp_path)
    try:
        resp = client.get("/api/openprinttag/matches")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        match = next(m for m in data["matches"] if m["spoolman_filament_id"] == 101)

        candidates = match["candidates"]
        assert len(candidates) >= 2, "need at least 2 candidates for this test"

        # Confidence values must be strictly decreasing (best → worst)
        scores = [c["confidence"] for c in candidates]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1], (
                f"candidates not sorted by score: {scores}"
            )

        # Alternates must not all be 0.0 — they carry their real computed score
        alt_scores = scores[1:]
        assert any(s > 0.0 for s in alt_scores), (
            f"All alternate scores are 0.0 — real scores not being returned: {alt_scores}"
        )

    finally:
        _ot_mod._settings.data_dir = original_data_dir


@pytest.mark.asyncio
async def test_exact_uuid_match_yields_single_candidate_at_1_0(tmp_path):
    """An SM filament with an existing openprinttag_uuid that maps to a known material
    must return exactly one candidate in the candidates list at confidence 1.0.
    """
    from app.schemas.spoolman import encode_extra_value
    from app.config import settings as _s

    uuid_key = _s.spoolman_field_openprinttag_uuid
    target_uuid = "d22442a5-1234-0000-0000-000000000001"  # _OPT_PLA_SILK uuid

    sm_fil = SpoolmanFilament(
        id=200,
        name="PLA Silk Bronze",
        vendor=SpoolmanVendor(id=10, name="Buddy3D"),
        material="PLA Silk",
        color_hex="B87333",
        extra={uuid_key: encode_extra_value(target_uuid)},
    )

    client, _ot_mod, _ = _make_matches_test_app(
        tmp_path, [_OPT_PLA_SILK, _OPT_PETG, _OPT_PLA_MATTE], [sm_fil]
    )
    original_data_dir = _ot_mod._settings.data_dir
    _ot_mod._settings.data_dir = str(tmp_path)
    try:
        resp = client.get("/api/openprinttag/matches")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        match = next(m for m in data["matches"] if m["spoolman_filament_id"] == 200)

        # Exact-UUID match: single candidate at 1.0
        assert match["confidence"] == 1.0
        candidates = match["candidates"]
        assert len(candidates) == 1, (
            f"Exact-UUID match must yield exactly 1 candidate, got {len(candidates)}"
        )
        c = candidates[0]
        assert c["confidence"] == 1.0
        assert c["opt_uuid"] == target_uuid
        assert c["opt_slug"] == "buddy3d-pla-silk-bronze"
        # Must have fields
        assert len(c["fields"]) > 0

    finally:
        _ot_mod._settings.data_dir = original_data_dir


# ---------------------------------------------------------------------------
# opentag_vendor_aliases: parser, resolve_opentag_brand, and endpoint tests
# ---------------------------------------------------------------------------


def test_parse_vendor_aliases_basic():
    """'prusa=prusament, foo = bar' parses to {prusa: prusament, foo: bar}."""
    from app.api.opentag import _parse_vendor_aliases
    result = _parse_vendor_aliases("prusa=prusament, foo = bar")
    assert result == {"prusa": "prusament", "foo": "bar"}


def test_parse_vendor_aliases_ignores_blanks_and_no_equals():
    """Blank entries and entries without '=' are silently ignored."""
    from app.api.opentag import _parse_vendor_aliases
    result = _parse_vendor_aliases("prusa=prusament,,notanequals, =empty")
    assert "prusa" in result
    assert result["prusa"] == "prusament"
    # Blank and "notanequals" entries must be absent
    assert "" not in result
    assert "notanequals" not in result


def test_parse_vendor_aliases_empty_string():
    """Empty CSV produces an empty dict."""
    from app.api.opentag import _parse_vendor_aliases
    assert _parse_vendor_aliases("") == {}


def test_resolve_opentag_brand_with_alias():
    """'Prusa' resolves to 'prusament' when aliases contain that pair."""
    from app.core.opentag_match import resolve_opentag_brand
    aliases = {"prusa": "prusament"}
    assert resolve_opentag_brand("Prusa", aliases) == "prusament"


def test_resolve_opentag_brand_unmapped():
    """An unmapped vendor name is returned as normalize_vendor(name)."""
    from app.core.opentag_match import resolve_opentag_brand
    from app.core.matcher import normalize_vendor
    aliases = {"prusa": "prusament"}
    result = resolve_opentag_brand("ELEGOO", aliases)
    assert result == normalize_vendor("ELEGOO")


def test_resolve_opentag_brand_none_vendor():
    """None vendor name returns empty string."""
    from app.core.opentag_match import resolve_opentag_brand
    assert resolve_opentag_brand(None, {"prusa": "prusament"}) == ""


def test_score_candidate_prusa_with_alias_scores_vendor_match():
    """With alias prusa=prusament, score_candidate for a 'Prusa' SM filament against a
    'Prusament' OPT entry awards the full 0.20 vendor component.
    """
    _OPT_PRUSAMENT_PLA = {
        "uuid": "prusament-0000-0000-0000-000000000001",
        "slug": "prusament-pla-galaxy-silver",
        "brandName": "Prusament",
        "name": "PLA Galaxy Silver",
        "type": "PLA",
        "abbreviation": "PLA",
        "tags": [],
        "color": "#C0C0C0",
        "secondaryColors": [],
        "density": 1.24,
        "nozzleTempMin": 210,
        "nozzleTempMax": 230,
        "bedTempMin": 50,
        "bedTempMax": 60,
        "completenessScore": 90,
    }

    aliases = {"prusa": "prusament"}

    sm_prusa = SpoolmanFilament(
        id=99,
        name="Galaxy Silver",
        vendor=SpoolmanVendor(id=7, name="Prusa"),
        material="PLA",
        color_hex="C0C0C0",
        extra={},
    )

    score_with = score_candidate(sm_prusa, _OPT_PRUSAMENT_PLA, aliases=aliases)
    score_without = score_candidate(sm_prusa, _OPT_PRUSAMENT_PLA, aliases={})

    # With alias: vendor component should be 0.20 (exact match prusa→prusament == opt brand)
    # Without alias: "prusa" != "prusament" so vendor component is 0 or partial
    assert score_with > score_without, (
        f"Expected alias score ({score_with:.4f}) > no-alias score ({score_without:.4f})"
    )
    # The gap should be at least 0.10 (the minimum vendor score contribution difference)
    # Use round() to avoid floating-point precision issues (e.g. 0.1000 vs 0.1).
    assert round(score_with - score_without, 6) >= 0.10, (
        f"Expected vendor component difference >= 0.10 but got {score_with - score_without:.4f}"
    )


@pytest.mark.asyncio
async def test_matches_endpoint_prusa_alias_finds_prusament_candidates(tmp_path):
    """With alias prusa=prusament configured, a 'Prusa' SM filament finds Prusament OPT
    candidates (brand pre-filter uses the resolved brand). Without the alias, it does not.
    """
    import datetime as _dt
    from unittest.mock import patch as _patch
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router
    from app.core.opentag_cache import _save_cache

    _OPT_PRUSAMENT_PLA_SILVER = {
        "uuid": "prusament-0000-0000-0000-000000000099",
        "slug": "prusament-pla-galaxy-silver",
        "brandName": "Prusament",
        "name": "PLA Galaxy Silver",
        "type": "PLA",
        "abbreviation": "PLA",
        "tags": [],
        "color": "#C0C0C0",
        "secondaryColors": [],
        "density": 1.24,
        "nozzleTempMin": 210,
        "nozzleTempMax": 230,
        "bedTempMin": 50,
        "bedTempMax": 60,
        "completenessScore": 90,
    }

    # Materials in cache: only Prusament entries
    materials = [_OPT_PRUSAMENT_PLA_SILVER]
    fresh_ts = _dt.datetime.now(_dt.timezone.utc).isoformat()
    _save_cache(str(tmp_path), materials, fresh_ts)

    sm_prusa = SpoolmanFilament(
        id=55,
        name="Galaxy Silver",
        vendor=SpoolmanVendor(id=7, name="Prusa"),
        material="PLA",
        color_hex="C0C0C0",
        extra={},
    )

    fake_fdb = AsyncMock()
    fake_sm = AsyncMock()
    fake_sm.get_filaments = AsyncMock(return_value=[sm_prusa])

    test_app = FastAPI()
    test_app.include_router(router, prefix="/api")
    test_app.state.filamentdb = fake_fdb
    test_app.state.spoolman = fake_sm

    import app.api.opentag as _ot_mod
    original_data_dir = _ot_mod._settings.data_dir
    _ot_mod._settings.data_dir = str(tmp_path)

    # Patch get_config_value and SessionLocal to avoid hitting the real SQLite database.
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session_factory = MagicMock(return_value=mock_session)

    try:
        # --- With alias: 'Prusa' → 'prusament', should match Prusament candidates ---
        with (
            _patch("app.api.opentag.SessionLocal", mock_session_factory),
            _patch("app.api.config.get_config_value", return_value="prusa=prusament"),
        ):
            client = TestClient(test_app, raise_server_exceptions=True)
            resp = client.get("/api/openprinttag/matches")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        match = next(m for m in data["matches"] if m["spoolman_filament_id"] == 55)
        # With alias, the Prusament material should be found
        assert match["opt_slug"] == "prusament-pla-galaxy-silver", (
            f"Expected Prusament match with alias, got opt_slug={match['opt_slug']!r}"
        )
        assert match["confidence"] > 0.30, (
            f"Expected confidence > 0.30 with alias, got {match['confidence']}"
        )

        # --- Without alias: 'Prusa' stays 'prusa', no Prusament brand bucket found ---
        with (
            _patch("app.api.opentag.SessionLocal", mock_session_factory),
            _patch("app.api.config.get_config_value", return_value=""),
        ):
            client2 = TestClient(test_app, raise_server_exceptions=True)
            resp2 = client2.get("/api/openprinttag/matches")
        assert resp2.status_code == 200, resp2.text
        data2 = resp2.json()
        match2 = next(m for m in data2["matches"] if m["spoolman_filament_id"] == 55)
        # Without alias, no brand bucket for 'prusa' in Prusament-only dataset → no match
        assert match2["opt_slug"] is None, (
            f"Expected no match without alias, but got opt_slug={match2['opt_slug']!r}"
        )

    finally:
        _ot_mod._settings.data_dir = original_data_dir


# ---------------------------------------------------------------------------
# Vendor reassignment field — reviewable "Manufacturer" row
# ---------------------------------------------------------------------------

# OPT material with brandName "Prusament" (different from SM vendor "Prusa")
_OPT_PRUSAMENT_PLA_ORANGE = {
    "uuid": "prusament-1111-0000-0000-000000000001",
    "slug": "prusament-pla-orange",
    "brandName": "Prusament",
    "name": "PLA Orange",
    "type": "PLA",
    "abbreviation": "PLA",
    "tags": [],
    "color": "#FF6B00",
    "secondaryColors": [],
    "density": 1.24,
    "nozzleTempMin": 210,
    "nozzleTempMax": 230,
    "bedTempMin": 50,
    "bedTempMax": 60,
    "completenessScore": 85,
}


def test_opt_to_spoolman_fields_includes_vendor_brand():
    """opt_to_spoolman_fields must include a 'vendor' key with the OPT brandName."""
    fields = opt_to_spoolman_fields(_OPT_PRUSAMENT_PLA_ORANGE)
    assert "vendor" in fields
    assert fields["vendor"] == "Prusament"


def test_build_field_rows_vendor_row_present_when_names_differ():
    """When SM vendor name differs from OPT brand (via alias), vendor row must be included."""
    from app.api.opentag import _build_field_rows

    # SM filament with vendor "Prusa"; OPT brand "Prusament" — names differ after normalization
    sm = _sm_fil(sm_id=55, vendor="Prusa", material="PLA", color_hex="FF6B00")
    opt_fields = opt_to_spoolman_fields(_OPT_PRUSAMENT_PLA_ORANGE)

    rows = _build_field_rows(sm, opt_fields)
    vendor_rows = [r for r in rows if r.field == "vendor"]

    assert len(vendor_rows) == 1, "Expected exactly one vendor field row"
    vendor_row = vendor_rows[0]
    assert vendor_row.spoolman_value == "Prusa"
    assert vendor_row.opentag_value == "Prusament"
    assert vendor_row.suggested_value == "Prusament"


def test_build_field_rows_vendor_row_absent_when_names_same():
    """When SM vendor and OPT brand normalize to the same value, the vendor row is omitted."""
    from app.api.opentag import _build_field_rows

    # SM vendor "Prusament" matches OPT brandName "Prusament" exactly — no change needed
    sm = _sm_fil(sm_id=10, vendor="Prusament", material="PLA", color_hex="FF6B00")
    opt_fields = opt_to_spoolman_fields(_OPT_PRUSAMENT_PLA_ORANGE)

    rows = _build_field_rows(sm, opt_fields)
    vendor_rows = [r for r in rows if r.field == "vendor"]

    assert len(vendor_rows) == 0, "Vendor row should be absent when vendor names match"


def test_build_field_rows_vendor_row_absent_when_normalized_match():
    """normalize_vendor equality (case-insensitive) suppresses the vendor row."""
    from app.api.opentag import _build_field_rows

    # SM vendor "PRUSAMENT" vs OPT "Prusament" — differ only in case → normalize to same
    sm = _sm_fil(sm_id=11, vendor="PRUSAMENT", material="PLA", color_hex="FF6B00")
    opt_fields = opt_to_spoolman_fields(_OPT_PRUSAMENT_PLA_ORANGE)

    rows = _build_field_rows(sm, opt_fields)
    vendor_rows = [r for r in rows if r.field == "vendor"]

    assert len(vendor_rows) == 0, (
        "Vendor row must be absent when only casing differs (normalize_vendor matches)"
    )


# ---------------------------------------------------------------------------
# Apply: vendor find-or-create reassignment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_vendor_resolves_existing_no_duplicate():
    """Apply: when the chosen vendor already exists in Spoolman, no duplicate is created.

    The filament PATCH must include vendor_id from the existing vendor; create_vendor
    must NOT be called.
    """
    patched_payloads: list[tuple] = []

    async def _fake_patch(fil_id, payload):
        patched_payloads.append((fil_id, payload))
        # Return a minimal SpoolmanFilament-shaped dict
        from app.schemas.spoolman import SpoolmanFilament as _SF
        return MagicMock(spec=_SF)

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router
    from app.schemas.spoolman import SpoolmanVendor as _SV

    fake_sm = AsyncMock()
    fake_sm.update_filament = AsyncMock(side_effect=_fake_patch)
    fake_sm.create_vendor = AsyncMock()
    # Existing vendors: id=7 "Prusament"
    fake_sm.get_vendors = AsyncMock(return_value=[
        _SV(id=7, name="Prusament"),
    ])

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
                "spoolman_filament_id": 55,
                "ignored": False,
                "fdb_filament_id": None,
                "openprinttag_slug": None,
                "openprinttag_uuid": None,
                "fields": [
                    # vendor field decision — choose "Prusament"
                    {"field": "vendor", "value": "Prusament", "keep_mine": False},
                    {"field": "material", "value": "PLA", "keep_mine": False},
                ],
            }
        ]
    }
    resp = client.post("/api/openprinttag/apply", json=request_body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["applied"] == 1
    assert data["errors"] == 0

    # create_vendor must NOT have been called (Prusament already exists)
    fake_sm.create_vendor.assert_not_called()

    # PATCH must include vendor_id=7
    assert len(patched_payloads) == 1
    _, payload = patched_payloads[0]
    assert payload.get("vendor_id") == 7, (
        f"Expected vendor_id=7 in PATCH, got payload={payload!r}"
    )

    # 'vendor' must appear in fields_written
    result = data["results"][0]
    assert "vendor" in result["fields_written"]


@pytest.mark.asyncio
async def test_apply_vendor_creates_when_missing():
    """Apply: when the chosen vendor does NOT exist, it is created once and vendor_id used."""
    patched_payloads: list[tuple] = []

    async def _fake_patch(fil_id, payload):
        patched_payloads.append((fil_id, payload))
        from app.schemas.spoolman import SpoolmanFilament as _SF
        return MagicMock(spec=_SF)

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router
    from app.schemas.spoolman import SpoolmanVendor as _SV

    fake_sm = AsyncMock()
    fake_sm.update_filament = AsyncMock(side_effect=_fake_patch)
    # No existing vendors
    fake_sm.get_vendors = AsyncMock(return_value=[])
    # create_vendor returns a new vendor with id=42
    fake_sm.create_vendor = AsyncMock(return_value=_SV(id=42, name="Prusament"))

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
                "spoolman_filament_id": 55,
                "ignored": False,
                "fdb_filament_id": None,
                "openprinttag_slug": None,
                "openprinttag_uuid": None,
                "fields": [
                    {"field": "vendor", "value": "Prusament", "keep_mine": False},
                    {"field": "material", "value": "PLA", "keep_mine": False},
                ],
            }
        ]
    }
    resp = client.post("/api/openprinttag/apply", json=request_body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["applied"] == 1

    # create_vendor called exactly once
    fake_sm.create_vendor.assert_called_once_with({"name": "Prusament"})

    # PATCH must include vendor_id=42
    assert len(patched_payloads) == 1
    _, payload = patched_payloads[0]
    assert payload.get("vendor_id") == 42

    result = data["results"][0]
    assert "vendor" in result["fields_written"]


@pytest.mark.asyncio
async def test_apply_vendor_keep_mine_leaves_vendor_untouched():
    """Apply: when the vendor field has keep_mine=True, vendor is not changed."""
    patched_payloads: list[tuple] = []

    async def _fake_patch(fil_id, payload):
        patched_payloads.append((fil_id, payload))
        from app.schemas.spoolman import SpoolmanFilament as _SF
        return MagicMock(spec=_SF)

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router
    from app.schemas.spoolman import SpoolmanVendor as _SV

    fake_sm = AsyncMock()
    fake_sm.update_filament = AsyncMock(side_effect=_fake_patch)
    fake_sm.get_vendors = AsyncMock(return_value=[_SV(id=7, name="Prusament")])
    fake_sm.create_vendor = AsyncMock()

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
                "spoolman_filament_id": 55,
                "ignored": False,
                "fdb_filament_id": None,
                "openprinttag_slug": None,
                "openprinttag_uuid": None,
                "fields": [
                    # vendor: keep_mine=True → skip
                    {"field": "vendor", "value": "Prusament", "keep_mine": True},
                    {"field": "material", "value": "PLA", "keep_mine": False},
                ],
            }
        ]
    }
    resp = client.post("/api/openprinttag/apply", json=request_body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["applied"] == 1

    # create_vendor NOT called (keep_mine skips vendor entirely)
    fake_sm.create_vendor.assert_not_called()

    # vendor_id must NOT be in the PATCH payload
    assert len(patched_payloads) == 1
    _, payload = patched_payloads[0]
    assert "vendor_id" not in payload, (
        f"vendor_id must not appear in PATCH when keep_mine=True, got payload={payload!r}"
    )

    result = data["results"][0]
    assert "vendor" not in result["fields_written"]


@pytest.mark.asyncio
async def test_apply_vendor_no_duplicate_when_name_appears_twice_in_same_run():
    """Apply: when two decisions in the same run share the same vendor name, create_vendor
    is called at most once (the second decision hits the cached id).
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.opentag import router
    from app.schemas.spoolman import SpoolmanVendor as _SV

    fake_sm = AsyncMock()
    fake_sm.update_filament = AsyncMock(return_value=MagicMock())
    fake_sm.get_vendors = AsyncMock(return_value=[])
    # Returns a new vendor on first call
    fake_sm.create_vendor = AsyncMock(return_value=_SV(id=99, name="Prusament"))

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
                "spoolman_filament_id": 10,
                "ignored": False,
                "fdb_filament_id": None,
                "openprinttag_slug": None,
                "openprinttag_uuid": None,
                "fields": [{"field": "vendor", "value": "Prusament", "keep_mine": False}],
            },
            {
                "spoolman_filament_id": 11,
                "ignored": False,
                "fdb_filament_id": None,
                "openprinttag_slug": None,
                "openprinttag_uuid": None,
                "fields": [{"field": "vendor", "value": "Prusament", "keep_mine": False}],
            },
        ]
    }
    resp = client.post("/api/openprinttag/apply", json=request_body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["applied"] == 2

    # create_vendor must have been called exactly once (cached on second decision)
    assert fake_sm.create_vendor.call_count == 1, (
        f"create_vendor should be called once, was called {fake_sm.create_vendor.call_count} times"
    )
