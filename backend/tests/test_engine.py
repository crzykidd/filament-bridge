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


def _seed_weight_config(db, direction: str = "two_way", policy: str = "manual"):
    """Set weight sync direction and conflict policy in BridgeConfig."""
    from app.models.config import BridgeConfig
    db.merge(BridgeConfig(key="weight_sync_direction", value=json.dumps(direction)))
    db.merge(BridgeConfig(key="weight_conflict_policy", value=json.dumps(policy)))
    db.commit()


def _seed_matprop_config(db, direction: str = "filamentdb_to_spoolman", policy: str = "manual"):
    """Set material_properties sync direction and conflict policy in BridgeConfig."""
    from app.models.config import BridgeConfig
    db.merge(BridgeConfig(key="material_properties_sync_direction", value=json.dumps(direction)))
    db.merge(BridgeConfig(key="material_properties_conflict_policy", value=json.dumps(policy)))
    db.commit()


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
    """Weight changed on both sides with two_way+manual → Conflict row, zero API writes."""
    sm_spool = _sm_spool(1, 790.0)  # SM changed
    fdb_fil = _fdb_filament("fil-1", "spool-1", 1050.0)  # FDB also changed
    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 800.0})
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {"totalWeight": 1000.0})
    # two_way + manual → both-changed must queue a conflict
    _seed_weight_config(db, direction="two_way", policy="manual")

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
    # SM-only change must propagate → spoolman_to_filamentdb direction
    _seed_matprop_config(db, direction="spoolman_to_filamentdb", policy="manual")

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
    """Both sides changed multicolor differently with two_way+manual → Conflict row, no writes."""
    sm_fil = _sm_fil(color_hex="93be2f", multi_hexes="cdde1b,68cc16", direction="coaxial")
    fdb_list = _fdb_list_fil(color="#aa0000", secondary=["#00bb00"], opt_tags=[28])
    fdb_detail = _fdb_detail_fil(color="#aa0000", secondary=["#00bb00"], opt_tags=[28])
    _add_filament_mapping(db)
    # Both snapshots reflect an older, shared solid state — both sides have since diverged
    _store_snapshot(db, "spoolman", "filament", str(SM_FIL_ID), {"_mc_sig": "solid|93be2f|"})
    _store_snapshot(db, "filamentdb", "filament", FDB_FIL_ID, {"_mc_sig": "solid|93be2f|"})
    # two_way + manual → both-changed must queue a conflict
    _seed_matprop_config(db, direction="two_way", policy="manual")

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


# ---------------------------------------------------------------------------
# Filament-level cost sync
# ---------------------------------------------------------------------------

COST_SM_FIL_ID = 50
COST_FDB_FIL_ID = "fil-cost"


def _sm_fil_with_cost(price: float | None = None) -> SpoolmanFilament:
    return SpoolmanFilament(
        id=COST_SM_FIL_ID,
        name="Cost PLA",
        vendor=SpoolmanVendor(id=1, name="ELEGOO"),
        price=price,
    )


def _sm_spool_with_price(spool_id: int, price: float | None, sm_fil_id: int = COST_SM_FIL_ID) -> SpoolmanSpool:
    return SpoolmanSpool(
        id=spool_id,
        filament=SpoolmanFilament(id=sm_fil_id, name="Cost PLA", vendor=SpoolmanVendor(id=1, name="ELEGOO")),
        remaining_weight=500.0,
        price=price,
        archived=False,
        extra={},
    )


def _fdb_list_fil_cost(cost: float | None = None) -> FDBFilament:
    return FDBFilament.model_validate({
        "_id": COST_FDB_FIL_ID,
        "name": "Cost PLA",
        "cost": cost,
        "spools": [],
    })


def _add_filament_mapping_cost(db):
    db.add(FilamentMapping(spoolman_filament_id=COST_SM_FIL_ID, filamentdb_id=COST_FDB_FIL_ID))
    db.flush()


def _cost_settings(mock_settings, matprop_sot="spoolman"):
    mock_settings.filamentdb_spoolman_id_field = "label"
    mock_settings.spoolman_field_filamentdb_id = "filamentdb_id"
    mock_settings.spoolman_field_filamentdb_spool_id = "filamentdb_spool_id"
    mock_settings.spoolman_field_filamentdb_parent_id = "filamentdb_parent_id"
    mock_settings.parsed_field_mappings = {}
    mock_settings.parsed_field_mapping_excludes = set()


def _seed_cost_config(db, matprop_sot="spoolman"):
    from app.models.config import BridgeConfig
    import json as _json
    db.merge(BridgeConfig(key="material_properties_source_of_truth", value=_json.dumps(matprop_sot)))
    db.commit()


@pytest.mark.asyncio
async def test_cost_sm_to_fdb_when_matprop_sot_spoolman(db):
    """SM filament price changed → FDB cost updated when direction=spoolman_to_filamentdb."""
    _add_filament_mapping_cost(db)
    _seed_matprop_config(db, direction="spoolman_to_filamentdb", policy="manual")
    sm_fil = _sm_fil_with_cost(price=24.99)
    fdb_list = _fdb_list_fil_cost(cost=20.0)  # FDB unchanged at 20.0
    # Baseline: SM had price 20.0, FDB had cost 20.0; only SM changed
    _store_snapshot(db, "spoolman", "filament", str(COST_SM_FIL_ID), {"_cost": 20.0})
    _store_snapshot(db, "filamentdb", "filament", COST_FDB_FIL_ID, {"_cost": 20.0})

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_filamentdb(filaments=[fdb_list])

    with patch("app.core.engine._settings") as mock_settings, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _cost_settings(mock_settings)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    fdb_client.update_filament.assert_called_once_with(COST_FDB_FIL_ID, {"cost": 24.99})
    assert result.updated == 1
    spoolman.update_filament.assert_not_called()


@pytest.mark.asyncio
async def test_cost_fdb_to_sm_when_matprop_sot_filamentdb(db):
    """FDB cost changed → SM filament price updated when matprop_sot=filamentdb."""
    _add_filament_mapping_cost(db)
    _seed_cost_config(db, matprop_sot="filamentdb")
    sm_fil = _sm_fil_with_cost(price=20.0)
    fdb_list = _fdb_list_fil_cost(cost=29.99)
    # Baseline: SM had 20.0, FDB had 20.0 — FDB changed
    _store_snapshot(db, "spoolman", "filament", str(COST_SM_FIL_ID), {"_cost": 20.0})
    _store_snapshot(db, "filamentdb", "filament", COST_FDB_FIL_ID, {"_cost": 20.0})

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_filamentdb(filaments=[fdb_list])

    with patch("app.core.engine._settings") as mock_settings, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _cost_settings(mock_settings)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    spoolman.update_filament.assert_called_once_with(COST_SM_FIL_ID, {"price": 29.99})
    assert result.updated == 1
    fdb_client.update_filament.assert_not_called()


@pytest.mark.asyncio
async def test_cost_both_changed_creates_conflict(db):
    """Both SM and FDB cost changed with two_way+manual → Conflict row, no writes."""
    _add_filament_mapping_cost(db)
    _seed_matprop_config(db, direction="two_way", policy="manual")
    sm_fil = _sm_fil_with_cost(price=24.99)
    fdb_list = _fdb_list_fil_cost(cost=35.00)
    # Baseline: both had 20.0 — both changed
    _store_snapshot(db, "spoolman", "filament", str(COST_SM_FIL_ID), {"_cost": 20.0})
    _store_snapshot(db, "filamentdb", "filament", COST_FDB_FIL_ID, {"_cost": 20.0})

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_filamentdb(filaments=[fdb_list])

    with patch("app.core.engine._settings") as mock_settings, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _cost_settings(mock_settings)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    assert result.conflicts == 1
    assert result.updated == 0
    fdb_client.update_filament.assert_not_called()
    spoolman.update_filament.assert_not_called()
    conflict = db.query(Conflict).first()
    assert conflict is not None
    assert conflict.field_name == "cost"
    assert conflict.spoolman_id == COST_SM_FIL_ID


@pytest.mark.asyncio
async def test_cost_first_sight_stores_baseline_no_write(db):
    """No prior cost snapshots → store baseline, no upstream writes."""
    _add_filament_mapping_cost(db)
    sm_fil = _sm_fil_with_cost(price=19.99)
    fdb_list = _fdb_list_fil_cost(cost=19.99)
    # No snapshots stored

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_filamentdb(filaments=[fdb_list])

    with patch("app.core.engine._settings") as mock_settings, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _cost_settings(mock_settings)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    fdb_client.update_filament.assert_not_called()
    spoolman.update_filament.assert_not_called()
    assert result.updated == 0
    assert result.conflicts == 0
    # _cost key stored in filament snapshots
    sm_snap = db.query(Snapshot).filter_by(
        source="spoolman", entity_type="filament", entity_id=str(COST_SM_FIL_ID)
    ).first()
    assert sm_snap is not None
    assert json.loads(sm_snap.data).get("_cost") == 19.99


@pytest.mark.asyncio
async def test_cost_and_multicolor_snapshots_coexist(db):
    """After a cycle, _mc_sig and _cost must coexist in the filament snapshot (no clobber)."""
    # Use the multicolor SM/FDB IDs from earlier tests (SM_FIL_ID = 20, FDB_FIL_ID = "fil-mc")
    # Reuse _sm_fil + _fdb_list_fil helpers from the multicolor test block.
    from app.schemas.filamentdb import FDBFilamentDetail

    mc_sm_id = SM_FIL_ID   # 20
    mc_fdb_id = FDB_FIL_ID  # "fil-mc"
    cost_sm_id = COST_SM_FIL_ID  # 50
    cost_fdb_id = COST_FDB_FIL_ID  # "fil-cost"

    # Add both filament mappings
    db.add(FilamentMapping(spoolman_filament_id=mc_sm_id, filamentdb_id=mc_fdb_id))
    db.add(FilamentMapping(spoolman_filament_id=cost_sm_id, filamentdb_id=cost_fdb_id))
    db.flush()

    # Multicolor filament: pre-seed _mc_sig so the multicolor pass stores its key
    mc_sig = "solid|93be2f|"
    _store_snapshot(db, "spoolman", "filament", str(mc_sm_id), {"_mc_sig": mc_sig})
    _store_snapshot(db, "filamentdb", "filament", mc_fdb_id, {"_mc_sig": mc_sig})

    # Cost filament: pre-seed _cost so the cost pass does not trigger a write
    _store_snapshot(db, "spoolman", "filament", str(cost_sm_id), {"_cost": 20.0})
    _store_snapshot(db, "filamentdb", "filament", cost_fdb_id, {"_cost": 20.0})

    # SM filaments: solid for mc, price-bearing for cost
    sm_fil_mc = SpoolmanFilament(
        id=mc_sm_id, name="Multicolor PLA",
        vendor=SpoolmanVendor(id=1, name="ELEGOO"),
        color_hex="93be2f",  # solid, no multi_color_hexes
    )
    sm_fil_cost = _sm_fil_with_cost(price=20.0)

    # FDB filaments
    fdb_list_mc = FDBFilament.model_validate({
        "_id": mc_fdb_id, "name": "Multicolor PLA",
        "color": "#93be2f", "secondaryColors": [], "optTags": [], "spools": [],
    })
    fdb_list_cost = _fdb_list_fil_cost(cost=20.0)
    fdb_detail_mc = FDBFilamentDetail.model_validate({
        "_id": mc_fdb_id, "name": "Multicolor PLA",
        "color": "#93be2f", "secondaryColors": [], "optTags": [], "_inherited": [], "spools": [],
    })

    spoolman = _fake_spoolman(filaments=[sm_fil_mc, sm_fil_cost])
    fdb_client = _fake_filamentdb(filaments=[fdb_list_mc, fdb_list_cost], detail=fdb_detail_mc)

    with patch("app.core.engine._settings") as mock_settings, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _mc_settings(mock_settings)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    # After the cycle, the multicolor filament snapshot must contain _mc_sig
    # AND must not have lost it due to the cost pass (or vice versa).
    # For the cost filament, check that _cost persists after a multicolor refresh.
    cost_sm_snap = db.query(Snapshot).filter_by(
        source="spoolman", entity_type="filament", entity_id=str(cost_sm_id)
    ).first()
    assert cost_sm_snap is not None
    cost_sm_data = json.loads(cost_sm_snap.data)
    assert "_cost" in cost_sm_data, "_cost key missing after cycle"

    # For the multicolor filament snapshot: _mc_sig must survive a fresh cycle run
    # (cost pass skips it because sm+fdb cost is both None → no snapshot write).
    mc_sm_snap = db.query(Snapshot).filter_by(
        source="spoolman", entity_type="filament", entity_id=str(mc_sm_id)
    ).first()
    assert mc_sm_snap is not None
    mc_sm_data = json.loads(mc_sm_snap.data)
    assert "_mc_sig" in mc_sm_data, "_mc_sig key missing after cycle"

    # Now run a second cycle where BOTH filaments have all keys — test merge:
    # Inject both keys into the cost filament snapshot to simulate the merged state.
    # Use _upsert_snapshot (not _store_snapshot) since the row already exists.
    from app.core.engine import _upsert_snapshot as _upsert
    _upsert(db, "spoolman", "filament", str(cost_sm_id), {"_cost": 20.0, "_mc_sig": "irrelevant"})
    _upsert(db, "filamentdb", "filament", cost_fdb_id, {"_cost": 20.0, "_mc_sig": "irrelevant"})

    await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID + "-2")

    cost_sm_snap2 = db.query(Snapshot).filter_by(
        source="spoolman", entity_type="filament", entity_id=str(cost_sm_id)
    ).first()
    cost_sm_data2 = json.loads(cost_sm_snap2.data)
    # Both keys must coexist after the cycle
    assert "_cost" in cost_sm_data2, "_cost key lost after second cycle"
    assert "_mc_sig" in cost_sm_data2, "_mc_sig key lost after second cycle"


@pytest.mark.asyncio
async def test_cost_spool_price_wins_over_filament_price(db):
    """Spool-level price takes precedence over filament-level price in the cost pass."""
    _add_filament_mapping_cost(db)
    _seed_matprop_config(db, direction="spoolman_to_filamentdb", policy="manual")
    # SM filament price = 20 but spool price = 30 (spool wins)
    sm_fil = _sm_fil_with_cost(price=20.0)
    sm_spool_with_p = _sm_spool_with_price(spool_id=99, price=30.0)
    fdb_list = _fdb_list_fil_cost(cost=20.0)
    # Baseline cost = 20 (the filament price); SM effective cost is now 30 (spool)
    _store_snapshot(db, "spoolman", "filament", str(COST_SM_FIL_ID), {"_cost": 20.0})
    _store_snapshot(db, "filamentdb", "filament", COST_FDB_FIL_ID, {"_cost": 20.0})

    spoolman = _fake_spoolman(filaments=[sm_fil], spools=[sm_spool_with_p])
    fdb_client = _fake_filamentdb(filaments=[fdb_list])

    with patch("app.core.engine._settings") as mock_settings, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _cost_settings(mock_settings)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    # Spool price (30) should be used, not filament price (20) — SM changed → FDB updated
    fdb_client.update_filament.assert_called_once_with(COST_FDB_FIL_ID, {"cost": 30.0})
    assert result.updated == 1


# ---------------------------------------------------------------------------
# Verification tests: per-category resolver behaviors (new two-axis model)
# ---------------------------------------------------------------------------

def _weight_settings(mock_settings):
    mock_settings.filamentdb_spoolman_id_field = "label"
    mock_settings.spoolman_field_filamentdb_id = "filamentdb_id"
    mock_settings.spoolman_field_filamentdb_spool_id = "filamentdb_spool_id"
    mock_settings.spoolman_field_filamentdb_parent_id = "filamentdb_parent_id"
    mock_settings.parsed_field_mappings = {}
    mock_settings.parsed_field_mapping_excludes = set()


@pytest.mark.asyncio
async def test_two_way_lone_sm_weight_change_propagates_to_fdb(db):
    """two_way direction: only SM weight changed → FDB usage logged (SM→FDB propagation)."""
    sm_spool = _sm_spool(1, 790.0)  # SM dropped 10g (was 800)
    fdb_fil = _fdb_filament("fil-1", "spool-1", 1000.0)
    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 800.0})
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {"totalWeight": 1000.0})
    _seed_weight_config(db, direction="two_way", policy="manual")

    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])

    with patch("app.core.engine._settings") as mock_settings:
        _weight_settings(mock_settings)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    assert result.updated == 1
    assert result.conflicts == 0
    fdb_client.log_usage.assert_called_once()


@pytest.mark.asyncio
async def test_two_way_lone_fdb_weight_change_propagates_to_sm(db):
    """two_way direction: only FDB weight changed → SM updated (FDB→SM propagation, NEW behavior)."""
    from app.schemas.filamentdb import FDBFilamentDetail
    # FDB spool gained filament (e.g. user refilled): gross=1200, was 1000 (tare=200 so net was 800, now 1000)
    sm_spool = _sm_spool(1, 800.0)  # SM unchanged
    fdb_fil = _fdb_filament("fil-1", "spool-1", 1200.0, tare=200.0)  # FDB increased
    fdb_detail = FDBFilamentDetail.model_validate({
        "_id": "fil-1",
        "name": "PLA",
        "spoolWeight": 200.0,
        "_inherited": [],
        "spools": [{"_id": "spool-1", "totalWeight": 1200.0, "retired": False, "usageHistory": []}],
    })
    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 800.0})
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {"totalWeight": 1000.0})  # FDB changed
    _seed_weight_config(db, direction="two_way", policy="manual")

    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil], detail=fdb_detail)

    with patch("app.core.engine._settings") as mock_settings:
        _weight_settings(mock_settings)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    assert result.updated == 1
    assert result.conflicts == 0
    # SM should receive an update (remaining_weight) — FDB drove the change
    spoolman.update_spool.assert_called_once()


@pytest.mark.asyncio
async def test_two_way_both_changed_spoolman_wins(db):
    """two_way + spoolman_wins: both sides changed → SM wins, no conflict."""
    sm_spool = _sm_spool(1, 790.0)   # SM changed
    fdb_fil = _fdb_filament("fil-1", "spool-1", 1050.0)  # FDB also changed
    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 800.0})
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {"totalWeight": 1000.0})
    _seed_weight_config(db, direction="two_way", policy="spoolman_wins")

    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])

    with patch("app.core.engine._settings") as mock_settings:
        _weight_settings(mock_settings)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    assert result.conflicts == 0
    assert result.updated == 1
    fdb_client.log_usage.assert_called_once()  # SM→FDB write (SM wins)
    spoolman.update_spool.assert_not_called()


@pytest.mark.asyncio
async def test_two_way_both_changed_conflict_dedup_no_requeue(db):
    """two_way + manual: second cycle with same both-changed pair must NOT re-queue conflict."""
    sm_spool = _sm_spool(1, 790.0)
    fdb_fil = _fdb_filament("fil-1", "spool-1", 1050.0)
    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 800.0})
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {"totalWeight": 1000.0})
    _seed_weight_config(db, direction="two_way", policy="manual")

    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])

    with patch("app.core.engine._settings") as mock_settings:
        _weight_settings(mock_settings)
        # First cycle: should queue exactly 1 conflict
        r1 = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    assert r1.conflicts == 1
    assert db.query(Conflict).count() == 1

    with patch("app.core.engine._settings") as mock_settings:
        _weight_settings(mock_settings)
        # Second cycle with same unchanged state: must NOT add another conflict row
        r2 = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID + "-2")

    assert r2.conflicts == 0
    assert db.query(Conflict).count() == 1  # still only one


@pytest.mark.asyncio
async def test_one_way_sm_to_fdb_ignores_lone_fdb_drift(db):
    """spoolman_to_filamentdb direction: lone FDB weight change is NOOP (no conflict, no write)."""
    sm_spool = _sm_spool(1, 800.0)   # SM unchanged
    fdb_fil = _fdb_filament("fil-1", "spool-1", 1100.0)  # FDB changed (locked destination)
    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 800.0})
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {"totalWeight": 1000.0})
    # Default behavior post-migration: spoolman_to_filamentdb + manual
    _seed_weight_config(db, direction="spoolman_to_filamentdb", policy="manual")

    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])

    with patch("app.core.engine._settings") as mock_settings:
        _weight_settings(mock_settings)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    assert result.updated == 0
    assert result.conflicts == 0
    fdb_client.log_usage.assert_not_called()
    spoolman.update_spool.assert_not_called()


@pytest.mark.asyncio
async def test_weight_newest_wins_picks_newer_side(db):
    """newest_wins: SM timestamp is after captured_at and newer → SM wins."""
    import datetime
    from app.models.snapshot import Snapshot as SnapModel

    # Plant a snapshot with captured_at in the past
    old_cap = datetime.datetime(2025, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
    sm_snap = SnapModel(
        source="spoolman", entity_type="spool", entity_id="1",
        data=json.dumps({"remaining_weight": 800.0}),
        captured_at=old_cap,
    )
    fdb_snap = SnapModel(
        source="filamentdb", entity_type="spool", entity_id="spool-1",
        data=json.dumps({"totalWeight": 1000.0}),
        captured_at=old_cap,
    )
    db.add(sm_snap)
    db.add(fdb_snap)
    db.flush()

    # Both sides changed
    sm_spool = _sm_spool(1, 790.0)   # SM weight changed (was 800)
    # SM last_used AFTER captured_at → SM wins
    sm_spool = SpoolmanSpool(
        id=1,
        filament=SpoolmanFilament(id=10, name="PLA", vendor=SpoolmanVendor(id=1, name="ELEGOO")),
        remaining_weight=790.0,
        archived=False,
        extra={},
        last_used="2025-01-01T12:00:00+00:00",  # after old_cap (midnight)
    )
    fdb_fil = _fdb_filament("fil-1", "spool-1", 1050.0)  # FDB also changed
    # FDB updatedAt set to a time BEFORE SM last_used but also after captured_at
    fdb_fil_with_ts = FDBFilament.model_validate({
        "_id": "fil-1",
        "name": "PLA",
        "vendor": "elegoo",
        "spoolWeight": 200.0,
        "updatedAt": "2025-01-01T06:00:00+00:00",  # earlier than SM last_used
        "spools": [{"_id": "spool-1", "totalWeight": 1050.0, "retired": False}],
    })

    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _seed_weight_config(db, direction="two_way", policy="newest_wins")

    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil_with_ts])

    with patch("app.core.engine._settings") as mock_settings:
        _weight_settings(mock_settings)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    # SM was newer → SM wins → FDB usage logged
    assert result.updated == 1
    assert result.conflicts == 0
    fdb_client.log_usage.assert_called_once()
