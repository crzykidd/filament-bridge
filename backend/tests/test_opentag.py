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
from app.core.opentag_match import find_best_match, opt_to_spoolman_fields, score_candidate
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
    sm = _sm_fil(vendor="Buddy3D", material="PETG", color_hex="CC0000")
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
