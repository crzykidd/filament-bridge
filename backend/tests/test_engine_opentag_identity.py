"""Integration tests for ``_sync_opentag_identity`` — the bidirectional,
stateless reconciliation of the OpenPrintTag identity (``openprinttag_slug`` /
``openprinttag_uuid``) between a Spoolman filament's extra fields and a Filament
DB filament's ``settings{}`` bag.

Covers:
  - FDB→SM fill: FDB has an identity, Spoolman doesn't → SM extras written (the
    new leg, closes #81)
  - SM→FDB push (regression): Spoolman has an identity, FDB doesn't →
    merge_filament_settings called (unchanged one-way behavior)
  - In sync: both sides carry the same uuid → neither write called
  - Divergence → conflict: both set, different uuid, policy=manual → a Conflict
    row is queued (deduped on a second cycle), no overwrite
  - Direction gating: one-way directions suppress the opposite leg's fill
  - Dry-run: no writes, a preview row is produced instead

Mirrors test_engine_opentag_fields.py.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.engine import run_sync_cycle
from app.core.fields import OPENTAG_EXTRA_FIELDS
from app.models.config import BridgeConfig
from app.models.conflict import Conflict
from app.models.mapping import FilamentMapping
from app.schemas.filamentdb import FDBFilament, FDBFilamentDetail
from app.schemas.spoolman import SpoolmanFilament, SpoolmanVendor, encode_extra_value

CYCLE_ID = "opt-identity-test-cycle"
OI_SM_FIL_ID = 90
OI_FDB_FIL_ID = "fil-opt-identity"

SLUG_FIELD = "openprinttag_slug"
UUID_FIELD = "openprinttag_uuid"


def _sm_fil(extra: dict | None = None) -> SpoolmanFilament:
    return SpoolmanFilament(
        id=OI_SM_FIL_ID,
        name="OPT Identity PLA",
        vendor=SpoolmanVendor(id=1, name="ELEGOO"),
        material="PLA",
        extra=extra or {},
    )


def _fdb_list() -> FDBFilament:
    return FDBFilament.model_validate({
        "_id": OI_FDB_FIL_ID, "name": "OPT Identity PLA", "type": "PLA", "spools": [],
    })


def _fdb_detail(*, settings: dict | None = None, parent_id: str | None = None) -> FDBFilamentDetail:
    return FDBFilamentDetail.model_validate({
        "_id": OI_FDB_FIL_ID,
        "name": "OPT Identity PLA",
        "type": "PLA",
        "settings": settings,
        "parentId": parent_id,
        "spools": [],
    })


def _add_fil_mapping(db) -> None:
    db.add(FilamentMapping(
        spoolman_filament_id=OI_SM_FIL_ID, filamentdb_id=OI_FDB_FIL_ID
    ))
    db.flush()


def _identity_settings(mock_settings) -> None:
    """Minimal _settings attrs for an identity-only cycle (real key strings)."""
    mock_settings.filamentdb_spoolman_id_field = "label"
    mock_settings.spoolman_field_filamentdb_id = "filamentdb_id"
    mock_settings.spoolman_field_filamentdb_spool_id = "filamentdb_spool_id"
    mock_settings.spoolman_field_filamentdb_parent_id = "filamentdb_parent_id"
    mock_settings.parsed_field_mappings = {}
    mock_settings.parsed_field_mapping_excludes = set()
    mock_settings.spoolman_field_openprinttag_slug = SLUG_FIELD
    mock_settings.spoolman_field_openprinttag_uuid = UUID_FIELD
    # Real key strings for the seven OPT material extras too, so the sibling
    # material-fields pass doesn't choke on MagicMock dict keys.
    for ef in OPENTAG_EXTRA_FIELDS:
        setattr(mock_settings, ef.config_attr, ef.default_key)


def _seed_matprop(db, direction: str, policy: str = "manual") -> None:
    db.merge(BridgeConfig(key="material_properties_sync_direction", value=json.dumps(direction)))
    db.merge(BridgeConfig(key="material_properties_conflict_policy", value=json.dumps(policy)))
    db.commit()


def _fake_spoolman(filaments=None) -> AsyncMock:
    client = AsyncMock()
    client.get_spools = AsyncMock(return_value=[])
    client.get_filaments = AsyncMock(return_value=filaments or [])
    client.get_field_definitions = AsyncMock(return_value=[])
    client.update_spool = AsyncMock(return_value=MagicMock())
    client.update_filament = AsyncMock(return_value=MagicMock())
    return client


def _fake_fdb(filaments=None, detail=None, version="1.33.0") -> AsyncMock:
    client = AsyncMock()
    client.get_filaments = AsyncMock(return_value=filaments or [])
    client.get_filament = AsyncMock(return_value=detail)
    client.get_version = AsyncMock(return_value=version)
    client.update_filament = AsyncMock(return_value={})
    client.merge_filament_settings = AsyncMock(return_value=None)
    return client


@pytest.mark.asyncio
async def test_identity_fdb_to_sm_fill(db):
    """FDB settings.openprinttag_uuid+slug set, SM extras empty → SM extras written."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="two_way", policy="manual")

    sm_fil = _sm_fil(extra={})
    fdb_detail = _fdb_detail(settings={
        "openprinttag_slug": "elegoo-pla-beige", "openprinttag_uuid": "uuid-123",
    })

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    spoolman.update_filament.assert_any_call(
        OI_SM_FIL_ID,
        {"extra": {
            SLUG_FIELD: encode_extra_value("elegoo-pla-beige"),
            UUID_FIELD: encode_extra_value("uuid-123"),
        }},
    )
    fdb_client.merge_filament_settings.assert_not_called()
    assert result.updated >= 1
    assert result.conflicts == 0


@pytest.mark.asyncio
async def test_identity_sm_to_fdb_push_regression(db):
    """SM extras set, FDB settings empty → merge_filament_settings called (unchanged)."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="two_way", policy="manual")

    sm_fil = _sm_fil(extra={
        SLUG_FIELD: encode_extra_value("elegoo-pla-beige"),
        UUID_FIELD: encode_extra_value("uuid-123"),
    })
    fdb_detail = _fdb_detail(settings=None)

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    fdb_client.merge_filament_settings.assert_any_call(
        OI_FDB_FIL_ID,
        {"openprinttag_slug": "elegoo-pla-beige", "openprinttag_uuid": "uuid-123"},
    )
    spoolman.update_filament.assert_not_called()
    assert result.updated >= 1
    assert result.conflicts == 0


@pytest.mark.asyncio
async def test_identity_in_sync_no_writes(db):
    """Both sides carry the same uuid → neither write called."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="two_way", policy="manual")

    sm_fil = _sm_fil(extra={
        SLUG_FIELD: encode_extra_value("elegoo-pla-beige"),
        UUID_FIELD: encode_extra_value("uuid-123"),
    })
    fdb_detail = _fdb_detail(settings={
        "openprinttag_slug": "elegoo-pla-beige", "openprinttag_uuid": "uuid-123",
    })

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    spoolman.update_filament.assert_not_called()
    fdb_client.merge_filament_settings.assert_not_called()
    assert result.conflicts == 0


@pytest.mark.asyncio
async def test_identity_divergence_queues_conflict_deduped(db):
    """Both set, different uuid, policy=manual → a Conflict is queued, no overwrite.

    A second cycle with the same divergence does NOT duplicate the conflict.
    """
    _add_fil_mapping(db)
    _seed_matprop(db, direction="two_way", policy="manual")

    sm_fil = _sm_fil(extra={
        SLUG_FIELD: encode_extra_value("elegoo-pla-beige"),
        UUID_FIELD: encode_extra_value("uuid-sm"),
    })
    fdb_detail = _fdb_detail(settings={
        "openprinttag_slug": "elegoo-pla-beige-v2", "openprinttag_uuid": "uuid-fdb",
    })

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    spoolman.update_filament.assert_not_called()
    fdb_client.merge_filament_settings.assert_not_called()
    assert result.conflicts >= 1
    conflict = db.query(Conflict).filter_by(field_name="OpenPrintTag identity").first()
    assert conflict is not None
    assert conflict.conflict_type == "cross_system"

    # Second cycle: same divergence — must NOT duplicate the conflict.
    spoolman2 = _fake_spoolman(filaments=[sm_fil])
    fdb_client2 = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)
    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        r2 = await run_sync_cycle(db, spoolman2, fdb_client2, dry_run=False, cycle_id=CYCLE_ID + "-2")

    assert r2.conflicts == 0
    conflicts = db.query(Conflict).filter_by(field_name="OpenPrintTag identity").all()
    assert len(conflicts) == 1


@pytest.mark.asyncio
async def test_identity_direction_gating_sm_to_fdb_only_suppresses_fdb_to_sm_fill(db):
    """direction=spoolman_to_filamentdb → the FDB→SM fill is NOT performed."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="spoolman_to_filamentdb", policy="manual")

    sm_fil = _sm_fil(extra={})
    fdb_detail = _fdb_detail(settings={
        "openprinttag_slug": "elegoo-pla-beige", "openprinttag_uuid": "uuid-123",
    })

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    spoolman.update_filament.assert_not_called()


@pytest.mark.asyncio
async def test_identity_direction_gating_fdb_to_sm_only_suppresses_sm_to_fdb_push(db):
    """direction=filamentdb_to_spoolman → the SM→FDB push is NOT performed."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="filamentdb_to_spoolman", policy="manual")

    sm_fil = _sm_fil(extra={
        SLUG_FIELD: encode_extra_value("elegoo-pla-beige"),
        UUID_FIELD: encode_extra_value("uuid-123"),
    })
    fdb_detail = _fdb_detail(settings=None)

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    fdb_client.merge_filament_settings.assert_not_called()


@pytest.mark.asyncio
async def test_identity_dry_run_fdb_to_sm_fill_no_write_preview_row(db):
    """FDB→SM fill case with dry_run=True → no update_filament write, a preview row present."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="two_way", policy="manual")

    sm_fil = _sm_fil(extra={})
    fdb_detail = _fdb_detail(settings={
        "openprinttag_slug": "elegoo-pla-beige", "openprinttag_uuid": "uuid-123",
    })

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=True, cycle_id=CYCLE_ID)

    spoolman.update_filament.assert_not_called()
    fdb_client.merge_filament_settings.assert_not_called()
    assert result.updated >= 1
    rows = [p for p in result.preview if p.get("field") == "OpenPrintTag identity"]
    assert len(rows) == 1
    assert rows[0]["action"] == "update"
    assert rows[0]["direction"] == "filamentdb_to_spoolman"
    assert rows[0]["new"] == "uuid-123"

    # No Conflict row should have been created either (dry-run never queues).
    assert db.query(Conflict).filter_by(field_name="OpenPrintTag identity").first() is None
