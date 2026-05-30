"""Integration tests for core/engine.py — driven with faked clients."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.engine import run_sync_cycle
from app.models.conflict import Conflict
from app.models.mapping import FilamentMapping, SpoolMapping
from app.models.snapshot import Snapshot
from app.models.sync_log import SyncLog
from app.schemas.filamentdb import FDBFilament, FDBSpool, FDBSpoolDetail, FDBUsageEntry
from app.schemas.spoolman import SpoolmanFilament, SpoolmanSpool, SpoolmanVendor

CYCLE_ID = "test-cycle-001"


# ---------------------------------------------------------------------------
# Client fakes
# ---------------------------------------------------------------------------


def _sm_spool(spool_id: int, remaining: float, extra: dict | None = None) -> SpoolmanSpool:
    return SpoolmanSpool(
        id=spool_id,
        filament=SpoolmanFilament(id=10, name="PLA", vendor=SpoolmanVendor(id=1, name="ELEGOO")),
        remaining_weight=remaining,
        archived=False,
        extra=extra or {},
    )


def _fdb_filament(fid: str, spool_id: str, total_weight: float, tare: float = 200.0) -> FDBFilament:
    return FDBFilament.model_validate({
        "_id": fid,
        "name": "PLA",
        "vendor": "elegoo",
        "spoolWeight": tare,
        "spools": [{"_id": spool_id, "totalWeight": total_weight, "retired": False}],
    })


def _fdb_detail_with_usage(fid: str, spool_id: str, total_weight: float, tare: float, usage: float):
    """FDBFilamentDetail-like object with a spool that has usage history."""
    from app.schemas.filamentdb import FDBFilamentDetail
    return FDBFilamentDetail.model_validate({
        "_id": fid,
        "name": "PLA",
        "spoolWeight": tare,
        "_inherited": [],
        "spools": [
            {
                "_id": spool_id,
                "totalWeight": total_weight,
                "retired": False,
                "usageHistory": [{"grams": usage, "source": "spoolman"}] if usage else [],
            }
        ],
    })


def _fake_spoolman(spools=None, filaments=None, field_defs=None) -> AsyncMock:
    client = AsyncMock()
    client.get_spools = AsyncMock(return_value=spools or [])
    client.get_filaments = AsyncMock(return_value=filaments or [])
    client.get_field_definitions = AsyncMock(return_value=field_defs or [])
    client.update_spool = AsyncMock(return_value=MagicMock())
    client.create_spool = AsyncMock(return_value=MagicMock(id=999))
    return client


def _fake_filamentdb(filaments=None, detail=None) -> AsyncMock:
    client = AsyncMock()
    client.get_filaments = AsyncMock(return_value=filaments or [])
    client.get_filament = AsyncMock(return_value=detail)
    client.log_usage = AsyncMock(return_value={})
    client.update_spool = AsyncMock(return_value={})
    client.create_spool = AsyncMock(return_value={"_id": "new-spool-id"})
    return client


def _store_snapshot(db, source, entity_type, entity_id, data: dict):
    db.add(Snapshot(source=source, entity_type=entity_type, entity_id=entity_id, data=json.dumps(data)))
    db.flush()


def _add_spool_mapping(db, sm_id: int, fdb_fil: str, fdb_spool: str):
    db.add(SpoolMapping(spoolman_spool_id=sm_id, filamentdb_filament_id=fdb_fil, filamentdb_spool_id=fdb_spool))
    db.flush()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_applies_nothing(db):
    """dry_run=True computes changeset but writes no API calls and commits nothing."""
    sm_spool = _sm_spool(1, 795.0)  # dropped 5g
    fdb_fil = _fdb_filament("fil-1", "spool-1", 1000.0)
    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 800.0})
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {"totalWeight": 1000.0})

    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])

    result = await run_sync_cycle(
        db, spoolman, fdb_client, dry_run=True, cycle_id=CYCLE_ID
    )

    assert result.dry_run is True
    assert result.updated == 1
    # No API write calls
    fdb_client.log_usage.assert_not_called()
    spoolman.update_spool.assert_not_called()
    # No SyncLog rows written
    assert db.query(SyncLog).count() == 0
    # Snapshot not advanced
    snap = db.query(Snapshot).filter_by(source="spoolman", entity_type="spool", entity_id="1").first()
    assert json.loads(snap.data)["remaining_weight"] == 800.0


@pytest.mark.asyncio
async def test_weight_decrease_logs_usage(db):
    """A Spoolman weight decrease creates a FDB usage entry (FR-9)."""
    sm_spool = _sm_spool(1, 795.0)
    fdb_fil = _fdb_filament("fil-1", "spool-1", 1000.0, tare=200.0)
    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 800.0})
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {"totalWeight": 1000.0})

    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])

    with patch("app.core.engine._settings") as mock_settings:
        mock_settings.filamentdb_spoolman_id_field = "label"
        mock_settings.spoolman_field_filamentdb_id = "filamentdb_id"
        mock_settings.spoolman_field_filamentdb_spool_id = "filamentdb_spool_id"
        mock_settings.spoolman_field_filamentdb_parent_id = "filamentdb_parent_id"
        mock_settings.parsed_field_mappings = {}
        mock_settings.parsed_field_mapping_excludes = set()
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    assert result.updated == 1
    assert result.errors == 0
    fdb_client.log_usage.assert_called_once()
    call_args = fdb_client.log_usage.call_args
    assert call_args.args[0] == "fil-1"     # filament_id
    assert call_args.args[1] == "spool-1"   # spool_id
    assert call_args.args[2] == pytest.approx(5.0)  # delta grams
    assert call_args.kwargs["source"] == "spoolman"


@pytest.mark.asyncio
async def test_both_sides_changed_creates_conflict_no_writes(db):
    """Weight changed on both sides → Conflict row, zero API writes (FR-13 hard rule)."""
    sm_spool = _sm_spool(1, 790.0)  # SM changed
    fdb_fil = _fdb_filament("fil-1", "spool-1", 1050.0)  # FDB also changed
    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 800.0})
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {"totalWeight": 1000.0})

    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])

    with patch("app.core.engine._settings") as mock_settings:
        mock_settings.filamentdb_spoolman_id_field = "label"
        mock_settings.spoolman_field_filamentdb_id = "filamentdb_id"
        mock_settings.spoolman_field_filamentdb_spool_id = "filamentdb_spool_id"
        mock_settings.spoolman_field_filamentdb_parent_id = "filamentdb_parent_id"
        mock_settings.parsed_field_mappings = {}
        mock_settings.parsed_field_mapping_excludes = set()
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    assert result.conflicts == 1
    assert result.updated == 0
    fdb_client.log_usage.assert_not_called()
    spoolman.update_spool.assert_not_called()
    conflict_row = db.query(Conflict).first()
    assert conflict_row is not None
    assert conflict_row.field_name == "weight"
    assert conflict_row.spoolman_id == 1


@pytest.mark.asyncio
async def test_api_error_is_logged_and_cycle_continues(db):
    """A single-record API error is logged; the cycle returns without aborting."""
    sm_spool = _sm_spool(1, 795.0)
    fdb_fil = _fdb_filament("fil-1", "spool-1", 1000.0)
    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 800.0})
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {"totalWeight": 1000.0})

    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])
    fdb_client.log_usage.side_effect = RuntimeError("API timeout")

    with patch("app.core.engine._settings") as mock_settings:
        mock_settings.filamentdb_spoolman_id_field = "label"
        mock_settings.spoolman_field_filamentdb_id = "filamentdb_id"
        mock_settings.spoolman_field_filamentdb_spool_id = "filamentdb_spool_id"
        mock_settings.spoolman_field_filamentdb_parent_id = "filamentdb_parent_id"
        mock_settings.parsed_field_mappings = {}
        mock_settings.parsed_field_mapping_excludes = set()
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    # Cycle returns — does not raise
    assert result.errors == 1
    assert result.updated == 0
    # Error is logged in SyncLog
    log_row = db.query(SyncLog).filter_by(action="error").first()
    assert log_row is not None
    assert "API timeout" in (log_row.error_message or "")


@pytest.mark.asyncio
async def test_no_snapshot_first_cycle_stores_baseline(db):
    """First time we see a pair — store snapshots, skip diff, no API writes."""
    sm_spool = _sm_spool(1, 800.0)
    fdb_fil = _fdb_filament("fil-1", "spool-1", 1000.0)
    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    # No snapshots stored yet

    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])

    with patch("app.core.engine._settings") as mock_settings:
        mock_settings.filamentdb_spoolman_id_field = "label"
        mock_settings.spoolman_field_filamentdb_id = "filamentdb_id"
        mock_settings.spoolman_field_filamentdb_spool_id = "filamentdb_spool_id"
        mock_settings.spoolman_field_filamentdb_parent_id = "filamentdb_parent_id"
        mock_settings.parsed_field_mappings = {}
        mock_settings.parsed_field_mapping_excludes = set()
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    assert result.skipped == 1
    assert result.updated == 0
    fdb_client.log_usage.assert_not_called()
    # Snapshots stored
    assert db.query(Snapshot).filter_by(source="spoolman").count() == 1
    assert db.query(Snapshot).filter_by(source="filamentdb").count() == 1


# ---------------------------------------------------------------------------
# Multicolor colorName re-derivation and protect tests
# ---------------------------------------------------------------------------


def _sm_spool_multicolor(
    spool_id: int,
    remaining: float,
    color_hex: str = "93be2f",
    multi_hexes: str = "cdde1b,68cc16",
    direction: str = "coaxial",
    extra: dict | None = None,
) -> SpoolmanSpool:
    return SpoolmanSpool(
        id=spool_id,
        filament=SpoolmanFilament(
            id=20,
            name="Multicolor PLA",
            vendor=SpoolmanVendor(id=1, name="ELEGOO"),
            color_hex=color_hex,
            multi_color_hexes=multi_hexes,
            multi_color_direction=direction,
        ),
        remaining_weight=remaining,
        archived=False,
        extra=extra or {},
    )


@pytest.mark.asyncio
async def test_colorname_set_on_sync_for_multicolor_filament(db):
    """Engine should PUT colorName to FDB for multicolor Spoolman filaments (hex fmt)."""
    from app.api.config import set_config_value
    set_config_value(db, "multicolor_colorname_format", "hex")
    set_config_value(db, "protect_multicolor_color_in_spoolman", True)
    db.commit()

    sm_spool = _sm_spool_multicolor(1, 800.0)
    fdb_fil = _fdb_filament("fil-mc", "spool-mc", 1000.0)
    _add_spool_mapping(db, 1, "fil-mc", "spool-mc")
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 800.0})
    _store_snapshot(db, "filamentdb", "spool", "spool-mc", {"totalWeight": 1000.0})

    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])
    fdb_client.update_filament = AsyncMock(return_value=MagicMock())

    with patch("app.core.engine._settings") as mock_settings:
        mock_settings.filamentdb_spoolman_id_field = "label"
        mock_settings.spoolman_field_filamentdb_id = "filamentdb_id"
        mock_settings.spoolman_field_filamentdb_spool_id = "filamentdb_spool_id"
        mock_settings.spoolman_field_filamentdb_parent_id = "filamentdb_parent_id"
        mock_settings.parsed_field_mappings = {}
        mock_settings.parsed_field_mapping_excludes = set()
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    fdb_client.update_filament.assert_called_once_with(
        "fil-mc", {"colorName": "cdde1b/68cc16 (coextruded)"}
    )
    assert result.updated >= 1


@pytest.mark.asyncio
async def test_colorname_rewritten_on_format_change(db):
    """Changing multicolor_colorname_format and re-syncing rewrites colorName in FDB."""
    sm_spool = _sm_spool_multicolor(1, 800.0)
    fdb_fil = _fdb_filament("fil-mc", "spool-mc", 1000.0)
    _add_spool_mapping(db, 1, "fil-mc", "spool-mc")
    # Snapshot records the PREVIOUS colorName (hex format was applied before)
    _store_snapshot(db, "spoolman", "spool", "1", {
        "remaining_weight": 800.0,
        "_colorName": "cdde1b/68cc16 (coextruded)",  # last applied under hex fmt
    })
    _store_snapshot(db, "filamentdb", "spool", "spool-mc", {"totalWeight": 1000.0})

    # Config now says "name" format — different from what's in the snapshot
    from app.api.config import set_config_value
    set_config_value(db, "multicolor_colorname_format", "name")
    set_config_value(db, "protect_multicolor_color_in_spoolman", True)
    db.commit()

    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])
    fdb_client.update_filament = AsyncMock(return_value=MagicMock())

    with patch("app.core.engine._settings") as mock_settings:
        mock_settings.filamentdb_spoolman_id_field = "label"
        mock_settings.spoolman_field_filamentdb_id = "filamentdb_id"
        mock_settings.spoolman_field_filamentdb_spool_id = "filamentdb_spool_id"
        mock_settings.spoolman_field_filamentdb_parent_id = "filamentdb_parent_id"
        mock_settings.parsed_field_mappings = {}
        mock_settings.parsed_field_mapping_excludes = set()
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    # update_filament must have been called with a name-format colorName
    fdb_client.update_filament.assert_called_once()
    call_args = fdb_client.update_filament.call_args
    payload = call_args.args[1] if call_args.args else call_args.kwargs.get("payload", {})
    assert "colorName" in payload
    colorname = payload["colorName"]
    # Name format: no raw hex values, must contain direction label
    assert "cdde1b" not in colorname
    assert "(coextruded)" in colorname


@pytest.mark.asyncio
async def test_protect_multicolor_blocks_color_field_sync_fdb_to_sm(db):
    """protect_multicolor=true must skip FDB→SM sync of the 'color' field for multicolor filaments."""
    from app.core.fields import FieldMapping
    from app.api.config import set_config_value
    set_config_value(db, "multicolor_colorname_format", "hex")
    set_config_value(db, "protect_multicolor_color_in_spoolman", True)
    set_config_value(db, "material_properties_source_of_truth", "filamentdb")
    db.commit()

    sm_spool = _sm_spool_multicolor(1, 800.0)
    fdb_fil = _fdb_filament("fil-mc", "spool-mc", 1000.0)
    _add_spool_mapping(db, 1, "fil-mc", "spool-mc")
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 800.0})
    _store_snapshot(db, "filamentdb", "spool", "spool-mc", {"totalWeight": 1000.0})

    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])
    fdb_client.update_filament = AsyncMock(return_value=MagicMock())

    # Simulate a field map that would push FDB 'color' to SM as an extra field
    color_field_map = FieldMapping(fdb_path="color", sm_key="color_sync_test", direction="fdb_to_sm")

    with patch("app.core.engine._settings") as mock_settings, \
         patch("app.core.engine.resolve_field_map", return_value=[color_field_map]):
        mock_settings.filamentdb_spoolman_id_field = "label"
        mock_settings.spoolman_field_filamentdb_id = "filamentdb_id"
        mock_settings.spoolman_field_filamentdb_spool_id = "filamentdb_spool_id"
        mock_settings.spoolman_field_filamentdb_parent_id = "filamentdb_parent_id"
        mock_settings.parsed_field_mappings = {"color": "color_sync_test"}
        mock_settings.parsed_field_mapping_excludes = set()
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    # spoolman.update_spool must NOT have been called with a color extra field write
    for call in spoolman.update_spool.call_args_list:
        args, kwargs = call
        payload = args[1] if len(args) > 1 else kwargs.get("payload", {})
        extra = payload.get("extra", {})
        assert "color_sync_test" not in extra, "protect_multicolor should block color field sync"
