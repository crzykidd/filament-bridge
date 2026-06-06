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
    client.update_filament = AsyncMock(return_value=MagicMock())
    client.create_spool = AsyncMock(return_value=MagicMock(id=999))
    return client


def _fake_filamentdb(filaments=None, detail=None, version="1.33.0") -> AsyncMock:
    client = AsyncMock()
    client.get_filaments = AsyncMock(return_value=filaments or [])
    client.get_filament = AsyncMock(return_value=detail)
    client.get_version = AsyncMock(return_value=version)
    client.log_usage = AsyncMock(return_value={})
    client.update_spool = AsyncMock(return_value={})
    client.update_filament = AsyncMock(return_value={})
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
# Structured multicolor sync (bidirectional, filament-level)
# ---------------------------------------------------------------------------

SM_FIL_ID = 20
FDB_FIL_ID = "fil-mc"


def _sm_fil(color_hex=None, multi_hexes=None, direction=None) -> SpoolmanFilament:
    return SpoolmanFilament(
        id=SM_FIL_ID,
        name="Multicolor PLA",
        vendor=SpoolmanVendor(id=1, name="ELEGOO"),
        color_hex=color_hex,
        multi_color_hexes=multi_hexes,
        multi_color_direction=direction,
    )


def _fdb_list_fil(color=None, secondary=None, opt_tags=None) -> FDBFilament:
    return FDBFilament.model_validate({
        "_id": FDB_FIL_ID,
        "name": "Multicolor PLA",
        "color": color,
        "secondaryColors": secondary or [],
        "optTags": opt_tags or [],
        "spools": [],
    })


def _fdb_detail_fil(color=None, secondary=None, opt_tags=None):
    from app.schemas.filamentdb import FDBFilamentDetail
    return FDBFilamentDetail.model_validate({
        "_id": FDB_FIL_ID,
        "name": "Multicolor PLA",
        "color": color,
        "secondaryColors": secondary or [],
        "optTags": opt_tags or [],
        "_inherited": [],
        "spools": [],
    })


def _add_filament_mapping(db):
    db.add(FilamentMapping(spoolman_filament_id=SM_FIL_ID, filamentdb_id=FDB_FIL_ID))
    db.flush()


def _mc_settings(mock_settings):
    mock_settings.filamentdb_spoolman_id_field = "label"
    mock_settings.spoolman_field_filamentdb_id = "filamentdb_id"
    mock_settings.spoolman_field_filamentdb_spool_id = "filamentdb_spool_id"
    mock_settings.spoolman_field_filamentdb_parent_id = "filamentdb_parent_id"
    mock_settings.parsed_field_mappings = {}
    mock_settings.parsed_field_mapping_excludes = set()


@pytest.mark.asyncio
async def test_multicolor_sm_to_fdb_write(db):
    """SM filament gained coaxial multicolor; FDB unchanged → one structured PUT to FDB."""
    sm_fil = _sm_fil(color_hex="93be2f", multi_hexes="cdde1b,68cc16", direction="coaxial")
    fdb_list = _fdb_list_fil(color="#93be2f")
    fdb_detail = _fdb_detail_fil(color="#93be2f")
    _add_filament_mapping(db)
    _store_snapshot(db, "spoolman", "filament", str(SM_FIL_ID), {"_mc_sig": "solid|93be2f|"})
    _store_snapshot(db, "filamentdb", "filament", FDB_FIL_ID, {"_mc_sig": "solid|93be2f|"})

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_filamentdb(filaments=[fdb_list], detail=fdb_detail)

    with patch("app.core.engine._settings") as mock_settings, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _mc_settings(mock_settings)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    fdb_client.update_filament.assert_called_once()
    fid, payload = fdb_client.update_filament.call_args.args
    assert fid == FDB_FIL_ID
    assert payload["color"] is None
    assert payload["secondaryColors"] == ["#cdde1b", "#68cc16"]
    assert 29 in payload["optTags"]
    assert result.updated == 1
    spoolman.update_filament.assert_not_called()


@pytest.mark.asyncio
async def test_multicolor_sm_to_fdb_idempotent(db):
    """Re-running after the SM→FDB write produces no second write (signatures converged)."""
    sm_fil = _sm_fil(color_hex="93be2f", multi_hexes="cdde1b,68cc16", direction="coaxial")
    fdb_list = _fdb_list_fil(secondary=["#cdde1b", "#68cc16"], opt_tags=[29])
    fdb_detail = _fdb_detail_fil(secondary=["#cdde1b", "#68cc16"], opt_tags=[29])
    _add_filament_mapping(db)
    # Both snapshots already match the coextruded state
    sig = "coextruded||cdde1b,68cc16"
    _store_snapshot(db, "spoolman", "filament", str(SM_FIL_ID), {"_mc_sig": sig})
    _store_snapshot(db, "filamentdb", "filament", FDB_FIL_ID, {"_mc_sig": sig})

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_filamentdb(filaments=[fdb_list], detail=fdb_detail)

    with patch("app.core.engine._settings") as mock_settings, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _mc_settings(mock_settings)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    fdb_client.update_filament.assert_not_called()
    spoolman.update_filament.assert_not_called()
    assert result.updated == 0


@pytest.mark.asyncio
async def test_multicolor_fdb_to_sm_write(db):
    """FDB filament gained gradient multicolor; SM unchanged → one PATCH to Spoolman."""
    sm_fil = _sm_fil(color_hex="93be2f")  # SM still solid
    fdb_list = _fdb_list_fil(color="#aa0000", secondary=["#00bb00"], opt_tags=[28])
    fdb_detail = _fdb_detail_fil(color="#aa0000", secondary=["#00bb00"], opt_tags=[28])
    _add_filament_mapping(db)
    _store_snapshot(db, "spoolman", "filament", str(SM_FIL_ID), {"_mc_sig": "solid|93be2f|"})
    _store_snapshot(db, "filamentdb", "filament", FDB_FIL_ID, {"_mc_sig": "solid|93be2f|"})

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_filamentdb(filaments=[fdb_list], detail=fdb_detail)

    with patch("app.core.engine._settings") as mock_settings, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _mc_settings(mock_settings)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    spoolman.update_filament.assert_called_once()
    sm_id, payload = spoolman.update_filament.call_args.args
    assert sm_id == SM_FIL_ID
    assert payload["color_hex"] == "aa0000"
    assert payload["multi_color_hexes"] == "aa0000,00bb00"
    assert payload["multi_color_direction"] == "longitudinal"
    assert result.updated == 1
    fdb_client.update_filament.assert_not_called()


@pytest.mark.asyncio
async def test_multicolor_both_changed_conflict(db):
    """Both sides changed multicolor differently → Conflict row, no writes."""
    sm_fil = _sm_fil(color_hex="93be2f", multi_hexes="cdde1b,68cc16", direction="coaxial")
    fdb_list = _fdb_list_fil(color="#aa0000", secondary=["#00bb00"], opt_tags=[28])
    fdb_detail = _fdb_detail_fil(color="#aa0000", secondary=["#00bb00"], opt_tags=[28])
    _add_filament_mapping(db)
    # Both snapshots reflect an older, shared solid state — both sides have since diverged
    _store_snapshot(db, "spoolman", "filament", str(SM_FIL_ID), {"_mc_sig": "solid|93be2f|"})
    _store_snapshot(db, "filamentdb", "filament", FDB_FIL_ID, {"_mc_sig": "solid|93be2f|"})

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_filamentdb(filaments=[fdb_list], detail=fdb_detail)

    with patch("app.core.engine._settings") as mock_settings, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _mc_settings(mock_settings)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    assert result.conflicts == 1
    assert result.updated == 0
    fdb_client.update_filament.assert_not_called()
    spoolman.update_filament.assert_not_called()
    conflict_row = db.query(Conflict).first()
    assert conflict_row is not None
    assert conflict_row.field_name == "multicolor"


@pytest.mark.asyncio
async def test_multicolor_first_sight_stores_baseline(db):
    """No prior multicolor snapshots → store baseline, no write."""
    sm_fil = _sm_fil(color_hex="93be2f", multi_hexes="cdde1b,68cc16", direction="coaxial")
    fdb_list = _fdb_list_fil(color="#93be2f")
    fdb_detail = _fdb_detail_fil(color="#93be2f")
    _add_filament_mapping(db)

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_filamentdb(filaments=[fdb_list], detail=fdb_detail)

    with patch("app.core.engine._settings") as mock_settings, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _mc_settings(mock_settings)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    fdb_client.update_filament.assert_not_called()
    assert result.updated == 0
    # Both filament-level baselines stored
    assert db.query(Snapshot).filter_by(source="spoolman", entity_type="filament").count() == 1
    assert db.query(Snapshot).filter_by(source="filamentdb", entity_type="filament").count() == 1


@pytest.mark.asyncio
async def test_multicolor_skipped_when_fdb_too_old(db):
    """FDB < 1.33.0 → multicolor sync skipped, no writes, change recorded as skipped."""
    sm_fil = _sm_fil(color_hex="93be2f", multi_hexes="cdde1b,68cc16", direction="coaxial")
    fdb_list = _fdb_list_fil(color="#93be2f")
    fdb_detail = _fdb_detail_fil(color="#93be2f")
    _add_filament_mapping(db)
    _store_snapshot(db, "spoolman", "filament", str(SM_FIL_ID), {"_mc_sig": "solid|93be2f|"})
    _store_snapshot(db, "filamentdb", "filament", FDB_FIL_ID, {"_mc_sig": "solid|93be2f|"})

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_filamentdb(filaments=[fdb_list], detail=fdb_detail, version="1.32.0")

    with patch("app.core.engine._settings") as mock_settings, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _mc_settings(mock_settings)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    fdb_client.update_filament.assert_not_called()
    fdb_client.get_filament.assert_not_called()  # gated before detail fetch
    assert result.skipped >= 1


# ---------------------------------------------------------------------------
# Upstream deletion detection (FR-16 extension)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fdb_deletion_queues_conflict(db):
    """FDB spool absent from fetch → exactly one deletion conflict queued."""
    sm_spool = _sm_spool(1, 800.0)
    fdb_fil = _fdb_filament("fil-1", "spool-1", 1000.0)
    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 800.0})
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {"totalWeight": 1000.0})

    # FDB returns an empty list — spool is gone.
    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[])

    result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    assert result.conflicts == 1
    assert result.errors == 0
    conflict = db.query(Conflict).filter_by(resolved_at=None).first()
    assert conflict is not None
    assert conflict.field_name == "__record_deleted__"
    assert conflict.spoolman_id == 1
    assert conflict.filamentdb_spool_id == "spool-1"


@pytest.mark.asyncio
async def test_fdb_deletion_no_duplicate(db):
    """Second cycle after FDB deletion does not create a second conflict."""
    sm_spool = _sm_spool(1, 800.0)
    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 800.0})
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {"totalWeight": 1000.0})

    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[])

    await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)
    await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID + "-2")

    assert db.query(Conflict).filter_by(resolved_at=None).count() == 1


@pytest.mark.asyncio
async def test_fdb_deletion_mapping_row_shows_conflict(db):
    """After deletion conflict is queued, build_mapping_rows returns status='conflict'."""
    from app.api.mappings import build_mapping_rows

    sm_spool = _sm_spool(1, 800.0)
    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 800.0})
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {"totalWeight": 1000.0})

    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[])

    await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    rows = build_mapping_rows(db)
    assert len(rows) == 1
    assert rows[0].status == "conflict"


@pytest.mark.asyncio
async def test_sm_deletion_queues_conflict(db):
    """Spoolman spool absent from full fetch (not just non-archived) → deletion conflict."""
    fdb_fil = _fdb_filament("fil-1", "spool-1", 1000.0)
    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 800.0})
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {"totalWeight": 1000.0})

    # Spoolman returns empty list — spool id=1 is gone entirely.
    spoolman = _fake_spoolman(spools=[])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])

    result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    assert result.conflicts == 1
    conflict = db.query(Conflict).filter_by(resolved_at=None).first()
    assert conflict is not None
    assert conflict.field_name == "__record_deleted__"
    assert conflict.spoolman_id == 1


@pytest.mark.asyncio
async def test_archived_sm_spool_logs_skip_no_conflict(db):
    """Archived Spoolman spool is in sm_all_ids → skip logged, no deletion conflict."""
    archived_spool = SpoolmanSpool(
        id=1,
        filament=SpoolmanFilament(id=10, name="PLA", vendor=SpoolmanVendor(id=1, name="ELEGOO")),
        remaining_weight=800.0,
        archived=True,
        extra={},
    )
    fdb_fil = _fdb_filament("fil-1", "spool-1", 1000.0)
    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 800.0})
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {"totalWeight": 1000.0})

    spoolman = _fake_spoolman(spools=[archived_spool])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])

    result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    assert result.conflicts == 0
    assert result.skipped == 1
    assert db.query(Conflict).count() == 0
    skip_log = db.query(SyncLog).filter_by(action="skip").first()
    assert skip_log is not None
