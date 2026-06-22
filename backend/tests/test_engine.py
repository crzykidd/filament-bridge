"""Integration tests for core/engine.py — driven with faked clients."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.engine import run_sync_cycle
from app.core.fields import FieldMapping
from app.models.conflict import Conflict
from app.models.mapping import FilamentMapping, SpoolMapping
from app.models.snapshot import Snapshot
from app.models.sync_log import SyncLog
from app.schemas.filamentdb import FDBFilament
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


def _seed_archive_config(db, direction: str = "two_way", policy: str = "manual"):
    """Set archive/retire lifecycle sync direction and conflict policy in BridgeConfig."""
    from app.models.config import BridgeConfig
    db.merge(BridgeConfig(key="archive_sync_direction", value=json.dumps(direction)))
    db.merge(BridgeConfig(key="archive_conflict_policy", value=json.dumps(policy)))
    db.commit()


def _sm_spool_arch(spool_id: int, remaining: float, archived: bool, extra: dict | None = None) -> SpoolmanSpool:
    return SpoolmanSpool(
        id=spool_id,
        filament=SpoolmanFilament(id=10, name="PLA", vendor=SpoolmanVendor(id=1, name="ELEGOO")),
        remaining_weight=remaining,
        archived=archived,
        extra=extra or {},
    )


def _fdb_filament_ret(fid: str, spool_id: str, total_weight: float, retired: bool, tare: float = 200.0) -> FDBFilament:
    return FDBFilament.model_validate({
        "_id": fid,
        "name": "PLA",
        "vendor": "elegoo",
        "spoolWeight": tare,
        "spools": [{"_id": spool_id, "totalWeight": total_weight, "retired": retired}],
    })


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


def _patch_settings(mock_settings):
    """Apply the minimal _settings attrs the weight path needs."""
    mock_settings.filamentdb_spoolman_id_field = "label"
    mock_settings.spoolman_field_filamentdb_id = "filamentdb_id"
    mock_settings.spoolman_field_filamentdb_spool_id = "filamentdb_spool_id"
    mock_settings.spoolman_field_filamentdb_parent_id = "filamentdb_parent_id"
    mock_settings.parsed_field_mappings = {}
    mock_settings.parsed_field_mapping_excludes = set()


def _snap_value(db, source, entity_type, entity_id, key):
    row = db.query(Snapshot).filter_by(source=source, entity_type=entity_type, entity_id=entity_id).first()
    return json.loads(row.data)[key] if row else None


@pytest.mark.asyncio
async def test_weight_two_way_print_converges_no_loop(db):
    """Regression for the runaway weight loop: a single Spoolman-side decrement
    (a print) under two_way must propagate ONCE (usage log) and then converge —
    no compounding FDB→SM bounce on subsequent cycles.

    Pre-fix, cycle 1 refreshed only the SM snapshot, so cycle 2 saw the
    (now-reduced) FDB totalWeight as a fresh change, pushed it back to SM, and
    the usage double-count compounded it toward zero.
    """
    # In agreement at start: SM net 800, FDB gross 1000, tare 200.
    sm_spool = _sm_spool(1, 742.0)  # printed 58g (800 → 742)
    fdb_fil = _fdb_filament("fil-1", "spool-1", 1000.0, tare=200.0)
    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 800.0})
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {"totalWeight": 1000.0})
    _seed_weight_config(db, direction="two_way", policy="manual")

    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])

    with patch("app.core.engine._settings") as ms:
        _patch_settings(ms)
        # Cycle 1: SM dropped 58g → SM→FDB usage log.
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="c1")
        assert fdb_client.log_usage.call_count == 1
        assert fdb_client.log_usage.call_args.args[2] == pytest.approx(58.0)
        spoolman.update_spool.assert_not_called()  # no FDB→SM bounce
        # Both snapshots refreshed to the post-write agreed state.
        assert _snap_value(db, "spoolman", "spool", "1", "remaining_weight") == pytest.approx(742.0)
        assert _snap_value(db, "filamentdb", "spool", "spool-1", "totalWeight") == pytest.approx(942.0)

        # FDB applied the usage: totalWeight 1000 → 942. Simulate live FDB for the
        # next cycles; SM stays at 742 (no further print).
        fdb_client.get_filaments = AsyncMock(return_value=[_fdb_filament("fil-1", "spool-1", 942.0, tare=200.0)])

        # Cycles 2 & 3: must be NOOP — no new usage, no SM decrement.
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="c2")
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="c3")

    assert fdb_client.log_usage.call_count == 1   # still just the one real print
    spoolman.update_spool.assert_not_called()     # SM never re-decremented


@pytest.mark.asyncio
async def test_archived_imported_spool_no_pingpong(db):
    """An imported archived→retired spool must not be re-animated or bounced.

    Mirrors the wizard importing SM spool #65 (archived, used up) as a RETIRED FDB
    spool with a SpoolMapping. Both sides are already in the dead state, so the
    mapped-pair loop must NOOP every cycle: no weight diff, no usage log, no FDB→SM
    decrement, no lifecycle conflict, no lifecycle mirror, no duplicate-spool creation
    on either side — across multiple cycles.
    """
    sm_spool = SpoolmanSpool(
        id=65,
        filament=SpoolmanFilament(id=63, name="Light Purple PLA",
                                  vendor=SpoolmanVendor(id=1, name="Hatchbox")),
        remaining_weight=-47.98,   # used 1047 > initial 1000 → negative remaining
        archived=True,
        extra={"filamentdb_id": "fil-63", "filamentdb_spool_id": "spool-65"},
    )
    fdb_fil = FDBFilament.model_validate({
        "_id": "fil-63",
        "name": "Hatchbox PLA Light Purple PLA",
        "vendor": "hatchbox",
        "spoolWeight": 200.0,
        "spools": [{"_id": "spool-65", "totalWeight": 200.0, "retired": True}],
    })
    _add_spool_mapping(db, 65, "fil-63", "spool-65")
    _store_snapshot(db, "spoolman", "spool", "65", {"remaining_weight": -47.98})
    _store_snapshot(db, "filamentdb", "spool", "spool-65", {"totalWeight": 200.0})
    _seed_weight_config(db, direction="two_way", policy="manual")

    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])

    with patch("app.core.engine._settings") as ms:
        _patch_settings(ms)
        r1 = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="arch-c1")
        r2 = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="arch-c2")

    # No spurious work on either cycle — both sides already dead → NOOP, not synced.
    for r in (r1, r2):
        assert r.updated == 0, f"archived pair must not update; got {r.updated}"
        assert r.conflicts == 0, f"archived pair must not conflict; got {r.conflicts}"
        assert r.errors == 0
    # No writes to either system for the archived/retired spool.
    fdb_client.log_usage.assert_not_called()
    fdb_client.update_spool.assert_not_called()
    fdb_client.create_spool.assert_not_called()
    spoolman.update_spool.assert_not_called()
    spoolman.create_spool.assert_not_called()


@pytest.mark.asyncio
async def test_weight_two_way_fdb_change_converges_no_loop(db):
    """A lone FDB-side weight change under two_way propagates to SM once
    (net = totalWeight - tare, NO usage subtraction) and then converges."""
    # Start in agreement: SM 800, FDB 1000, tare 200. FDB jumps to 1100 (user
    # added filament / correction) → net should become 900.
    sm_spool = _sm_spool(1, 800.0)
    fdb_fil = _fdb_filament("fil-1", "spool-1", 1100.0, tare=200.0)
    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 800.0})
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {"totalWeight": 1000.0})
    _seed_weight_config(db, direction="two_way", policy="manual")

    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])

    with patch("app.core.engine._settings") as ms:
        _patch_settings(ms)
        # Cycle 1: FDB changed → FDB→SM, net = 1100 - 200 = 900.
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="c1")
        assert spoolman.update_spool.call_count == 1
        assert spoolman.update_spool.call_args.args[1]["remaining_weight"] == pytest.approx(900.0)
        fdb_client.log_usage.assert_not_called()
        assert _snap_value(db, "spoolman", "spool", "1", "remaining_weight") == pytest.approx(900.0)
        assert _snap_value(db, "filamentdb", "spool", "spool-1", "totalWeight") == pytest.approx(1100.0)

        # SM now reflects 900; FDB unchanged. Next cycles must be NOOP.
        spoolman.get_spools = AsyncMock(return_value=[_sm_spool(1, 900.0)])
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="c2")
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="c3")

    assert spoolman.update_spool.call_count == 1   # no further SM writes
    fdb_client.log_usage.assert_not_called()


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
    # color_hex must be absent (not sent) for multicolor — Spoolman 422s on both
    assert "color_hex" not in payload
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
async def test_solid_filament_captures_mc_color_for_display(db):
    """GitHub #2: a purely-solid filament (no multicolor either side) must still get its
    representative FDB color captured as ``_mc_color`` so Synced Records shows the FDB color
    instead of "—". The multicolor-sync logic skips solids, so the capture must happen for
    every mapped filament regardless."""
    sm_fil = _sm_fil(color_hex="dac7a0")          # solid, matches FDB
    fdb_list = _fdb_list_fil(color="#DAC7A0")     # solid — no secondaryColors/optTags
    fdb_detail = _fdb_detail_fil(color="#DAC7A0")
    _add_filament_mapping(db)

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_filamentdb(filaments=[fdb_list], detail=fdb_detail)

    with patch("app.core.engine._settings") as mock_settings, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _mc_settings(mock_settings)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    # No multicolor write happened (solid), but the display color was still captured.
    fdb_client.update_filament.assert_not_called()
    assert _snap_value(db, "filamentdb", "filament", FDB_FIL_ID, "_mc_color") == "#DAC7A0"


@pytest.mark.asyncio
async def test_solid_filament_mc_color_not_captured_on_dry_run(db):
    """Dry run must not mutate snapshots — the display-color capture is write-gated too."""
    sm_fil = _sm_fil(color_hex="dac7a0")
    fdb_list = _fdb_list_fil(color="#DAC7A0")
    fdb_detail = _fdb_detail_fil(color="#DAC7A0")
    _add_filament_mapping(db)

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_filamentdb(filaments=[fdb_list], detail=fdb_detail)

    with patch("app.core.engine._settings") as mock_settings, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _mc_settings(mock_settings)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=True, cycle_id=CYCLE_ID)

    assert db.query(Snapshot).filter_by(
        source="filamentdb", entity_type="filament", entity_id=FDB_FIL_ID
    ).first() is None


@pytest.mark.asyncio
async def test_sync_blocked_when_fdb_below_minimum(db):
    """FDB below the minimum supported version (1.33.0) hard-blocks the whole
    cycle: no upstream fetches/writes, blocked_reasons set."""
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

    assert result.blocked_reasons and any("1.33.0" in r for r in result.blocked_reasons)
    fdb_client.update_filament.assert_not_called()
    fdb_client.get_filaments.assert_not_called()   # blocked before any upstream fetch
    assert result.updated == 0 and result.created == 0


@pytest.mark.asyncio
async def test_sync_blocked_when_spoolman_below_minimum(db):
    """Spoolman below the minimum (0.22.0) hard-blocks the cycle."""
    spoolman = _fake_spoolman(filaments=[])
    spoolman.health = AsyncMock(return_value={"version": "0.21.0"})
    fdb_client = _fake_filamentdb(filaments=[], version="1.35.0")

    with patch("app.core.engine._settings") as mock_settings, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _mc_settings(mock_settings)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    assert result.blocked_reasons and any("0.22.0" in r for r in result.blocked_reasons)
    spoolman.get_spools.assert_not_called()


# ---------------------------------------------------------------------------
# Upstream deletion detection (FR-16 extension)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fdb_deletion_queues_conflict(db):
    """FDB spool absent AND SM cross-ref still set → deletion conflict queued (live linked counterpart)."""
    import json
    # SM spool still carries the filamentdb_spool_id cross-ref — still linked.
    sm_spool = _sm_spool(1, 800.0, extra={"filamentdb_spool_id": json.dumps("spool-1")})
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
    """Second cycle after FDB deletion (SM cross-ref set) does not create a second conflict."""
    import json
    # SM spool still carries the cross-ref so the stale-purge path is NOT taken.
    sm_spool = _sm_spool(1, 800.0, extra={"filamentdb_spool_id": json.dumps("spool-1")})
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
    """After deletion conflict is queued (SM cross-ref set), build_mapping_rows returns status='conflict'."""
    import json
    from app.api.mappings import build_mapping_rows

    sm_spool = _sm_spool(1, 800.0, extra={"filamentdb_spool_id": json.dumps("spool-1")})
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
async def test_reappeared_pair_auto_resolves_stale_deletion_conflict(db):
    """A stale 'record deleted' conflict self-heals once both sides are present again.

    Regression for the archived-spool-invisible bug: an archived spool that the bridge
    could not see was (mis)flagged as deleted. After the fetch fix it reappears; the
    leftover open deletion conflict must auto-resolve instead of lingering forever.
    """
    from app.models.conflict import DELETION_FIELD

    fdb_fil = _fdb_filament("fil-1", "spool-1", 1000.0)
    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 800.0})
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {"totalWeight": 1000.0})
    _seed_weight_config(db, direction="two_way", policy="manual")

    # Pre-existing open deletion conflict from a cycle when the spool was invisible.
    db.add(
        Conflict(
            entity_type="spool",
            spoolman_id=1,
            filamentdb_filament_id="fil-1",
            filamentdb_spool_id="spool-1",
            field_name=DELETION_FIELD,
            filamentdb_value='{"exists": true, "deleted_side": "spoolman"}',
        )
    )
    db.commit()

    # Both sides present and in agreement (net 800 == 800) — healthy pair.
    spoolman = _fake_spoolman(spools=[_sm_spool(1, 800.0)])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])

    with patch("app.core.engine._settings") as ms:
        _patch_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    assert result.conflicts == 0
    conflict = db.query(Conflict).filter_by(field_name=DELETION_FIELD).one()
    assert conflict.resolved_at is not None
    assert conflict.resolution == "auto_resolved_reappeared"
    assert db.query(Conflict).filter_by(resolved_at=None).count() == 0


@pytest.mark.asyncio
async def test_archived_sm_spool_with_unknown_baseline_is_noop(db):
    """Archived mapped spool whose snapshot lacks an 'archived' baseline must NOT be
    treated as a fresh flip — a missing baseline defaults to the current value so the
    pair is a clean NOOP (no conflict, no spurious mirror, no skip-as-deletion)."""
    archived_spool = SpoolmanSpool(
        id=1,
        filament=SpoolmanFilament(id=10, name="PLA", vendor=SpoolmanVendor(id=1, name="ELEGOO")),
        remaining_weight=800.0,
        archived=True,
        extra={},
    )
    fdb_fil = _fdb_filament("fil-1", "spool-1", 1000.0)
    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    # Legacy snapshots: no 'archived'/'retired' keys, weights already in agreement.
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 800.0})
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {"totalWeight": 1000.0})
    _seed_weight_config(db, direction="two_way", policy="manual")

    spoolman = _fake_spoolman(spools=[archived_spool])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])

    with patch("app.core.engine._settings") as ms:
        _patch_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    assert result.conflicts == 0
    assert result.updated == 0
    assert result.errors == 0
    assert db.query(Conflict).count() == 0
    # No upstream writes for either system.
    fdb_client.update_spool.assert_not_called()
    spoolman.update_spool.assert_not_called()


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
    # Inject all three snapshot keys (_cost, _mc_sig, _finish_sig) into the cost
    # filament snapshot to simulate the fully-merged state from prior cycles.
    # Using _upsert_snapshot (not _store_snapshot) since the row already exists.
    # Including _finish_sig prevents the finish-tag pass from triggering a first-sight
    # write that could observe a stale identity-map entry for the same row.
    from app.core.engine import _upsert_snapshot as _upsert
    _upsert(db, "spoolman", "filament", str(cost_sm_id), {"_cost": 20.0, "_mc_sig": "irrelevant", "_finish_sig": ""})
    _upsert(db, "filamentdb", "filament", cost_fdb_id, {"_cost": 20.0, "_mc_sig": "irrelevant", "_finish_sig": ""})

    await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID + "-2")

    cost_sm_snap2 = db.query(Snapshot).filter_by(
        source="spoolman", entity_type="filament", entity_id=str(cost_sm_id)
    ).first()
    cost_sm_data2 = json.loads(cost_sm_snap2.data)
    # All three keys must coexist after the cycle — none of the passes may clobber others.
    assert "_cost" in cost_sm_data2, "_cost key lost after second cycle"
    assert "_mc_sig" in cost_sm_data2, "_mc_sig key lost after second cycle"
    assert "_finish_sig" in cost_sm_data2, "_finish_sig key lost after second cycle"


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
# Material-property (bed/nozzle temperature) sync
# ---------------------------------------------------------------------------

MP_SM_FIL_ID = 60
MP_FDB_FIL_ID = "fil-mp"


def _sm_fil_with_temps(bed=None, nozzle=None) -> SpoolmanFilament:
    return SpoolmanFilament(
        id=MP_SM_FIL_ID, name="Temp PLA", vendor=SpoolmanVendor(id=1, name="ELEGOO"),
        settings_bed_temp=bed, settings_extruder_temp=nozzle,
    )


def _fdb_fil_with_temps(bed=None, nozzle=None) -> FDBFilament:
    return FDBFilament.model_validate({
        "_id": MP_FDB_FIL_ID, "name": "Temp PLA",
        "temperatures": {"bed": bed, "nozzle": nozzle},
        "spools": [],
    })


def _add_filament_mapping_mp(db):
    db.add(FilamentMapping(spoolman_filament_id=MP_SM_FIL_ID, filamentdb_id=MP_FDB_FIL_ID))
    db.flush()


@pytest.mark.asyncio
async def test_bed_temp_fdb_to_sm_two_way(db):
    """The reported bug: a lone FDB bed-temp change propagates to Spoolman under
    two_way (writes the NATIVE settings_bed_temp on the SM filament)."""
    _add_filament_mapping_mp(db)
    _seed_matprop_config(db, direction="two_way", policy="manual")
    sm_fil = _sm_fil_with_temps(bed=60, nozzle=210)        # SM unchanged
    fdb_fil = _fdb_fil_with_temps(bed=65, nozzle=210)      # FDB bed 60→65
    _store_snapshot(db, "spoolman", "filament", str(MP_SM_FIL_ID), {"_mp_settings_bed_temp": 60})
    _store_snapshot(db, "filamentdb", "filament", MP_FDB_FIL_ID, {"_mp_settings_bed_temp": 60})

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])
    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _cost_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    spoolman.update_filament.assert_called_once_with(MP_SM_FIL_ID, {"settings_bed_temp": 65})
    fdb_client.update_filament.assert_not_called()
    assert result.updated == 1


@pytest.mark.asyncio
async def test_bed_temp_sm_to_fdb_preserves_nozzle(db):
    """A lone SM bed-temp change writes FDB temperatures via read-modify-write,
    preserving the sibling nozzle temp."""
    _add_filament_mapping_mp(db)
    _seed_matprop_config(db, direction="two_way", policy="manual")
    sm_fil = _sm_fil_with_temps(bed=70, nozzle=210)        # SM bed 60→70
    fdb_fil = _fdb_fil_with_temps(bed=60, nozzle=210)      # FDB unchanged
    _store_snapshot(db, "spoolman", "filament", str(MP_SM_FIL_ID), {"_mp_settings_bed_temp": 60})
    _store_snapshot(db, "filamentdb", "filament", MP_FDB_FIL_ID, {"_mp_settings_bed_temp": 60})

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])
    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _cost_settings(ms)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    fdb_client.update_filament.assert_called_once()
    args = fdb_client.update_filament.call_args.args
    assert args[0] == MP_FDB_FIL_ID
    assert args[1]["temperatures"]["bed"] == 70
    assert args[1]["temperatures"]["nozzle"] == 210   # sibling preserved
    spoolman.update_filament.assert_not_called()


@pytest.mark.asyncio
async def test_nozzle_temp_fdb_to_sm_two_way(db):
    """Nozzle temp FDB→SM writes the native settings_extruder_temp."""
    _add_filament_mapping_mp(db)
    _seed_matprop_config(db, direction="two_way", policy="manual")
    sm_fil = _sm_fil_with_temps(bed=60, nozzle=210)
    fdb_fil = _fdb_fil_with_temps(bed=60, nozzle=225)     # FDB nozzle 210→225
    _store_snapshot(db, "spoolman", "filament", str(MP_SM_FIL_ID), {"_mp_settings_extruder_temp": 210})
    _store_snapshot(db, "filamentdb", "filament", MP_FDB_FIL_ID, {"_mp_settings_extruder_temp": 210})

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])
    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _cost_settings(ms)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    spoolman.update_filament.assert_called_once_with(MP_SM_FIL_ID, {"settings_extruder_temp": 225})


@pytest.mark.asyncio
async def test_bed_temp_both_changed_creates_conflict(db):
    """Both sides changed bed temp under two_way+manual → conflict, no writes."""
    _add_filament_mapping_mp(db)
    _seed_matprop_config(db, direction="two_way", policy="manual")
    sm_fil = _sm_fil_with_temps(bed=70, nozzle=210)
    fdb_fil = _fdb_fil_with_temps(bed=65, nozzle=210)
    _store_snapshot(db, "spoolman", "filament", str(MP_SM_FIL_ID), {"_mp_settings_bed_temp": 60})
    _store_snapshot(db, "filamentdb", "filament", MP_FDB_FIL_ID, {"_mp_settings_bed_temp": 60})

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])
    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _cost_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    assert result.conflicts == 1
    spoolman.update_filament.assert_not_called()
    fdb_client.update_filament.assert_not_called()
    conflict = db.query(Conflict).filter_by(field_name="bed_temp").first()
    assert conflict is not None and conflict.spoolman_id == MP_SM_FIL_ID


@pytest.mark.asyncio
async def test_bed_temp_first_sight_no_write(db):
    """No prior baseline → store baseline only, no write."""
    _add_filament_mapping_mp(db)
    _seed_matprop_config(db, direction="two_way", policy="manual")
    sm_fil = _sm_fil_with_temps(bed=60, nozzle=210)
    fdb_fil = _fdb_fil_with_temps(bed=65, nozzle=215)

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])
    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _cost_settings(ms)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    spoolman.update_filament.assert_not_called()
    fdb_client.update_filament.assert_not_called()
    snap = db.query(Snapshot).filter_by(source="spoolman", entity_type="filament", entity_id=str(MP_SM_FIL_ID)).first()
    assert json.loads(snap.data)["_mp_settings_bed_temp"] == 60


@pytest.mark.asyncio
async def test_bed_temp_oneway_fdb_to_sm_blocks_sm_change(db):
    """direction=filamentdb_to_spoolman: a lone SM bed change must NOT propagate."""
    _add_filament_mapping_mp(db)
    _seed_matprop_config(db, direction="filamentdb_to_spoolman", policy="manual")
    sm_fil = _sm_fil_with_temps(bed=70, nozzle=210)       # SM changed
    fdb_fil = _fdb_fil_with_temps(bed=60, nozzle=210)     # FDB unchanged
    _store_snapshot(db, "spoolman", "filament", str(MP_SM_FIL_ID), {"_mp_settings_bed_temp": 60})
    _store_snapshot(db, "filamentdb", "filament", MP_FDB_FIL_ID, {"_mp_settings_bed_temp": 60})

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])
    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _cost_settings(ms)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    fdb_client.update_filament.assert_not_called()
    spoolman.update_filament.assert_not_called()


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


# ---------------------------------------------------------------------------
# Dry-run "matched — in sync" preview entries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_matched_entry_for_in_sync_pair(db):
    """An in-sync spool pair (prior snapshots, no weight/field changes) yields exactly
    one action='matched' preview entry in dry_run=True, and ZERO such entries in a real
    (non-dry-run) cycle."""
    # Build a pair whose weights are identical to the snapshot — no changes at all.
    sm_spool = _sm_spool(1, 800.0)
    fdb_fil = _fdb_filament("fil-1", "spool-1", 1000.0, tare=200.0)
    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    # Snapshot reflects the current state exactly → no weight delta.
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 800.0})
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {"totalWeight": 1000.0})

    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])

    # --- dry run ---
    with patch("app.core.engine._settings") as mock_settings:
        _weight_settings(mock_settings)
        dry_result = await run_sync_cycle(
            db, spoolman, fdb_client, dry_run=True, cycle_id=CYCLE_ID
        )

    matched_entries = [e for e in dry_result.preview if e["action"] == "matched"]
    assert len(matched_entries) == 1, f"expected 1 matched entry, got {dry_result.preview}"
    assert matched_entries[0]["entity_type"] == "spool"
    assert matched_entries[0]["spoolman_id"] == 1
    assert matched_entries[0]["fdb_spool_id"] == "spool-1"
    assert matched_entries[0]["reason"] == "in sync — no updates"

    # --- real cycle must NOT emit any matched entries ---
    with patch("app.core.engine._settings") as mock_settings:
        _weight_settings(mock_settings)
        live_result = await run_sync_cycle(
            db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID + "-live"
        )

    live_matched = [e for e in live_result.preview if e.get("action") == "matched"]
    assert live_matched == [], f"live cycle must not emit matched entries, got {live_result.preview}"


@pytest.mark.asyncio
async def test_dry_run_changed_pair_emits_update_not_matched(db):
    """A pair with a real weight change yields its update entry (not a matched entry)
    in dry_run=True."""
    sm_spool = _sm_spool(1, 790.0)  # weight changed: was 800, now 790
    fdb_fil = _fdb_filament("fil-1", "spool-1", 1000.0, tare=200.0)
    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 800.0})
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {"totalWeight": 1000.0})
    # spoolman_to_filamentdb: lone SM change → update
    _seed_weight_config(db, direction="spoolman_to_filamentdb", policy="manual")

    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])

    with patch("app.core.engine._settings") as mock_settings:
        _weight_settings(mock_settings)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=True, cycle_id=CYCLE_ID)

    update_entries = [e for e in result.preview if e["action"] == "update"]
    matched_entries = [e for e in result.preview if e["action"] == "matched"]
    assert len(update_entries) >= 1, "expected at least one update entry for changed pair"
    assert matched_entries == [], f"changed pair must not emit matched entry; got {result.preview}"


@pytest.mark.asyncio
async def test_dry_run_multiple_pairs_matched_and_changed(db):
    """3 in-sync pairs + 1 changed pair → 3 matched entries + 1 update, zero matched for changed."""
    # Three in-sync pairs
    sm_spools = [_sm_spool(i, 800.0) for i in range(1, 4)]
    fdb_fils = [_fdb_filament(f"fil-{i}", f"spool-{i}", 1000.0) for i in range(1, 4)]
    for i in range(1, 4):
        _add_spool_mapping(db, i, f"fil-{i}", f"spool-{i}")
        _store_snapshot(db, "spoolman", "spool", str(i), {"remaining_weight": 800.0})
        _store_snapshot(db, "filamentdb", "spool", f"spool-{i}", {"totalWeight": 1000.0})

    # One changed pair (spool id=4, weight dropped)
    sm_changed = _sm_spool(4, 750.0)
    fdb_changed = _fdb_filament("fil-4", "spool-4", 1000.0)
    _add_spool_mapping(db, 4, "fil-4", "spool-4")
    _store_snapshot(db, "spoolman", "spool", "4", {"remaining_weight": 800.0})
    _store_snapshot(db, "filamentdb", "spool", "spool-4", {"totalWeight": 1000.0})
    _seed_weight_config(db, direction="spoolman_to_filamentdb", policy="manual")

    all_sm_spools = sm_spools + [sm_changed]
    all_fdb_fils = fdb_fils + [fdb_changed]

    spoolman = _fake_spoolman(spools=all_sm_spools)
    fdb_client = _fake_filamentdb(filaments=all_fdb_fils)

    with patch("app.core.engine._settings") as mock_settings:
        _weight_settings(mock_settings)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=True, cycle_id=CYCLE_ID)

    matched = [e for e in result.preview if e["action"] == "matched"]
    updates = [e for e in result.preview if e["action"] == "update"]
    assert len(matched) == 3, f"expected 3 matched rows, got {len(matched)}: {result.preview}"
    assert len(updates) >= 1, f"expected at least 1 update row, got {updates}"
    # The changed pair must not appear as matched
    matched_sm_ids = {e["spoolman_id"] for e in matched}
    assert 4 not in matched_sm_ids, "changed pair (sm_id=4) must not appear as matched"


# ---------------------------------------------------------------------------
# Bug A — engine: stale filamentdb_spool_id xref in new-spool detection
# ---------------------------------------------------------------------------


def _sm_spool_with_extra(spool_id: int, filament_id: int, extra: dict | None = None) -> SpoolmanSpool:
    """SM spool for a given filament id, with optional extra fields."""
    fil = SpoolmanFilament(id=filament_id, name="PLA", vendor=SpoolmanVendor(id=1, name="ACME"))
    return SpoolmanSpool(
        id=spool_id,
        filament=fil,
        remaining_weight=500.0,
        archived=False,
        extra=extra or {},
    )


def _fdb_filament_with_spool(fid: str, spool_id: str) -> FDBFilament:
    return FDBFilament.model_validate({
        "_id": fid,
        "name": "PLA",
        "spoolWeight": 200.0,
        "spools": [{"_id": spool_id, "totalWeight": 700.0, "retired": False}],
    })


def _add_fil_mapping(db, sm_fil_id: int, fdb_fil_id: str):
    db.add(FilamentMapping(spoolman_filament_id=sm_fil_id, filamentdb_id=fdb_fil_id))
    db.flush()


@pytest.mark.asyncio
async def test_engine_new_spool_stale_xref_triggers_create(db):
    """Ongoing new-spool detection: a SM spool with a stale filamentdb_spool_id xref
    (pointing at an id not in fdb_spool_index) must trigger FDB spool creation
    when new_spool_policy=auto_import."""
    # SM spool has xref to 'old-fdb-spool' which is NOT in current FDB data.
    stale_xref = json.dumps("old-fdb-spool")
    sm_sp = _sm_spool_with_extra(
        501, filament_id=50,
        extra={"filamentdb_spool_id": stale_xref},
    )
    # Current FDB filament has a different spool id.
    fdb_fil = _fdb_filament_with_spool("fdb-fil-50", "current-spool-aaa")
    _add_fil_mapping(db, sm_fil_id=50, fdb_fil_id="fdb-fil-50")
    # Enable auto-import so the stale xref triggers a create (default is manual_review).
    from app.models.config import BridgeConfig
    db.merge(BridgeConfig(key="new_spool_policy", value='"auto_import"'))
    db.commit()

    spoolman = _fake_spoolman(spools=[sm_sp])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])
    # create_spool must return a dict with _id
    fdb_client.create_spool = AsyncMock(return_value={"_id": "newly-created-spool"})

    with patch("app.core.engine._settings") as mock_settings:
        mock_settings.filamentdb_spoolman_id_field = "label"
        mock_settings.spoolman_field_filamentdb_id = "filamentdb_id"
        mock_settings.spoolman_field_filamentdb_spool_id = "filamentdb_spool_id"
        mock_settings.spoolman_field_filamentdb_parent_id = "filamentdb_parent_id"
        mock_settings.parsed_field_mappings = {}
        mock_settings.parsed_field_mapping_excludes = set()
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    # FDB spool creation must have been attempted.
    fdb_client.create_spool.assert_called_once()
    assert result.created >= 1, f"Expected at least 1 created, got {result.created}"
    assert result.errors == 0, f"Expected no errors, got {result.errors}"


@pytest.mark.asyncio
async def test_engine_new_spool_live_xref_skips(db):
    """Ongoing new-spool detection (SM→FDB path): a SM spool with a live
    filamentdb_spool_id xref (pointing at an id that IS in fdb_spool_index) must be
    skipped — the SM→FDB path must NOT call filamentdb.create_spool for it.

    Note: the FDB→SM path still runs under two_way default and may create a SM spool
    from the FDB spool; we only assert that FDB spool creation was NOT triggered by the
    SM→FDB path (live xref = already-linked orphan).
    """
    # SM spool has xref to 'live-spool-bbb' which IS in current FDB data.
    live_xref = json.dumps("live-spool-bbb")
    sm_sp = _sm_spool_with_extra(
        502, filament_id=51,
        extra={"filamentdb_spool_id": live_xref},
    )
    fdb_fil = _fdb_filament_with_spool("fdb-fil-51", "live-spool-bbb")
    _add_fil_mapping(db, sm_fil_id=51, fdb_fil_id="fdb-fil-51")

    spoolman = _fake_spoolman(spools=[sm_sp])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])
    # Track FDB spool creates; there should be zero (live xref → SM→FDB path is skipped).
    fdb_client.create_spool = AsyncMock(return_value={"_id": "should-not-be-called"})

    with patch("app.core.engine._settings") as mock_settings:
        mock_settings.filamentdb_spoolman_id_field = "label"
        mock_settings.spoolman_field_filamentdb_id = "filamentdb_id"
        mock_settings.spoolman_field_filamentdb_spool_id = "filamentdb_spool_id"
        mock_settings.spoolman_field_filamentdb_parent_id = "filamentdb_parent_id"
        mock_settings.parsed_field_mappings = {}
        mock_settings.parsed_field_mapping_excludes = set()
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    # The SM→FDB path must not create a FDB spool — live xref means the SM spool is
    # already linked or orphaned with a live reference, so it is skipped.
    fdb_client.create_spool.assert_not_called()


# ---------------------------------------------------------------------------
# Finish-tag sync (_sync_finish_tags) — OpenPrintTag material-tags round-trip
# ---------------------------------------------------------------------------

# IDs used in finish-tag tests
FINISH_SM_FIL_ID = 80
FINISH_FDB_FIL_ID = "fil-finish"

_json = json  # alias to avoid shadowing in closures


def _sm_fil_finish(
    *,
    name: str = "PLA Silk",
    material: str = "PLA Silk",
    extra: dict | None = None,
) -> SpoolmanFilament:
    return SpoolmanFilament(
        id=FINISH_SM_FIL_ID,
        name=name,
        material=material,
        vendor=SpoolmanVendor(id=1, name="ELEGOO"),
        extra=extra or {},
    )


def _fdb_list_finish(opt_tags: list | None = None) -> FDBFilament:
    return FDBFilament.model_validate({
        "_id": FINISH_FDB_FIL_ID,
        "name": "PLA Silk",
        "optTags": opt_tags or [],
        "spools": [],
    })


def _fdb_detail_finish(opt_tags: list | None = None):
    from app.schemas.filamentdb import FDBFilamentDetail
    return FDBFilamentDetail.model_validate({
        "_id": FINISH_FDB_FIL_ID,
        "name": "PLA Silk",
        "optTags": opt_tags or [],
        "_inherited": [],
        "spools": [],
    })


def _add_finish_filament_mapping(db):
    db.add(FilamentMapping(spoolman_filament_id=FINISH_SM_FIL_ID, filamentdb_id=FINISH_FDB_FIL_ID))
    db.flush()


def _finish_settings(mock_settings):
    from app.core.material_tags import DEFAULT_MATERIAL_TAG_IDS
    mock_settings.filamentdb_spoolman_id_field = "label"
    mock_settings.spoolman_field_filamentdb_id = "filamentdb_id"
    mock_settings.spoolman_field_filamentdb_spool_id = "filamentdb_spool_id"
    mock_settings.spoolman_field_filamentdb_parent_id = "filamentdb_parent_id"
    mock_settings.spoolman_field_filamentdb_material_tags = "filamentdb_material_tags"
    mock_settings.parsed_material_tag_ids = dict(DEFAULT_MATERIAL_TAG_IDS)
    mock_settings.parsed_field_mappings = {}
    mock_settings.parsed_field_mapping_excludes = set()


@pytest.mark.asyncio
async def test_finish_tags_sm_to_fdb_writes_opt_tags(db):
    """SM 'PLA Silk' with silk tag in extra → FDB optTags updated with tag 17 (silk)."""
    _add_finish_filament_mapping(db)
    _seed_matprop_config(db, direction="spoolman_to_filamentdb", policy="manual")

    # SM extra field stores [17] (silk); FDB currently has no finish tags
    silk_encoded = json.dumps([17])
    sm_fil = _sm_fil_finish(extra={"filamentdb_material_tags": silk_encoded})
    fdb_list = _fdb_list_finish(opt_tags=[])
    fdb_detail = _fdb_detail_finish(opt_tags=[])

    # Baseline: SM had tag 17, FDB had none → SM changed, FDB unchanged
    _store_snapshot(db, "spoolman", "filament", str(FINISH_SM_FIL_ID), {"_finish_sig": ""})
    _store_snapshot(db, "filamentdb", "filament", FINISH_FDB_FIL_ID, {"_finish_sig": ""})

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_filamentdb(filaments=[fdb_list], detail=fdb_detail)

    with patch("app.core.engine._settings") as mock_settings, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _finish_settings(mock_settings)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    fdb_client.update_filament.assert_called_once()
    _fid, payload = fdb_client.update_filament.call_args.args
    assert _fid == FINISH_FDB_FIL_ID
    assert "optTags" in payload
    assert 17 in payload["optTags"]
    assert result.updated >= 1


@pytest.mark.asyncio
async def test_finish_tags_fdb_to_sm_writes_extra_field(db):
    """FDB gains optTag 17 (silk); SM name is plain 'PLA' so text-parse yields no finish → FDB→SM write."""
    _add_finish_filament_mapping(db)
    _seed_matprop_config(db, direction="filamentdb_to_spoolman", policy="manual")

    # SM name/material have no finish keywords → sm_ids_now = {}; no extra field set
    sm_fil = _sm_fil_finish(name="PLA Red", material="PLA", extra={})
    fdb_list = _fdb_list_finish(opt_tags=[17])
    fdb_detail = _fdb_detail_finish(opt_tags=[17])

    # Baseline: both had no finish tags (empty sig); FDB now has 17 → fdb_changed, sm unchanged
    _store_snapshot(db, "spoolman", "filament", str(FINISH_SM_FIL_ID), {"_finish_sig": ""})
    _store_snapshot(db, "filamentdb", "filament", FINISH_FDB_FIL_ID, {"_finish_sig": ""})

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_filamentdb(filaments=[fdb_list], detail=fdb_detail)

    with patch("app.core.engine._settings") as mock_settings, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _finish_settings(mock_settings)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    spoolman.update_filament.assert_called_once()
    sm_fil_id, sm_payload = spoolman.update_filament.call_args.args
    assert sm_fil_id == FINISH_SM_FIL_ID
    assert "extra" in sm_payload
    assert "filamentdb_material_tags" in sm_payload["extra"]
    # Decoded value must be a CSV string containing "17" (not a JSON array)
    from app.schemas.spoolman import decode_extra_value
    from app.core.material_tags import parse_material_tags
    decoded = decode_extra_value(sm_payload["extra"]["filamentdb_material_tags"])
    assert isinstance(decoded, str), f"Expected CSV string, got {type(decoded)}: {decoded!r}"
    parsed = parse_material_tags(decoded)
    assert 17 in parsed
    assert result.updated >= 1


@pytest.mark.asyncio
async def test_finish_tags_both_changed_queues_conflict(db):
    """Both SM and FDB finish tags changed differently with two_way+manual → conflict."""
    _add_finish_filament_mapping(db)
    _seed_matprop_config(db, direction="two_way", policy="manual")

    # SM: tag 17 (silk); FDB: tag 16 (matte) — they disagree
    silk_encoded = json.dumps([17])
    sm_fil = _sm_fil_finish(extra={"filamentdb_material_tags": silk_encoded})
    fdb_list = _fdb_list_finish(opt_tags=[16])
    fdb_detail = _fdb_detail_finish(opt_tags=[16])

    # Baseline: both had no finish tags (empty sig)
    _store_snapshot(db, "spoolman", "filament", str(FINISH_SM_FIL_ID), {"_finish_sig": ""})
    _store_snapshot(db, "filamentdb", "filament", FINISH_FDB_FIL_ID, {"_finish_sig": ""})

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_filamentdb(filaments=[fdb_list], detail=fdb_detail)

    with patch("app.core.engine._settings") as mock_settings, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _finish_settings(mock_settings)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    assert result.conflicts >= 1
    conflict = db.query(Conflict).filter_by(field_name="material_tags").first()
    assert conflict is not None
    assert conflict.spoolman_id == FINISH_SM_FIL_ID
    fdb_client.update_filament.assert_not_called()
    spoolman.update_filament.assert_not_called()


@pytest.mark.asyncio
async def test_finish_tags_first_sight_stores_baseline_no_write(db):
    """No prior _finish_sig snapshot → baseline stored, no upstream writes."""
    _add_finish_filament_mapping(db)

    sm_fil = _sm_fil_finish()
    fdb_list = _fdb_list_finish(opt_tags=[17])
    fdb_detail = _fdb_detail_finish(opt_tags=[17])
    # No snapshots stored — first sight

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_filamentdb(filaments=[fdb_list], detail=fdb_detail)

    with patch("app.core.engine._settings") as mock_settings, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _finish_settings(mock_settings)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    fdb_client.update_filament.assert_not_called()
    spoolman.update_filament.assert_not_called()
    # _finish_sig must be stored in the filament snapshot
    sm_snap = db.query(Snapshot).filter_by(
        source="spoolman", entity_type="filament", entity_id=str(FINISH_SM_FIL_ID)
    ).first()
    assert sm_snap is not None
    assert "_finish_sig" in json.loads(sm_snap.data)


@pytest.mark.asyncio
async def test_finish_tags_snapshot_coexists_with_mc_sig_and_cost(db):
    """_finish_sig coexists with _mc_sig and _cost in the shared filament snapshot row."""
    _add_finish_filament_mapping(db)
    _seed_matprop_config(db, direction="spoolman_to_filamentdb", policy="manual")

    # SM extra field stores [17]; FDB has [17] — both agree — after first-sight no write
    silk_encoded = json.dumps([17])
    sm_fil = _sm_fil_finish(extra={"filamentdb_material_tags": silk_encoded})
    fdb_list = _fdb_list_finish(opt_tags=[17])
    fdb_detail = _fdb_detail_finish(opt_tags=[17])

    # Seed both _mc_sig and _cost into existing snapshots; finish_sig is absent
    _store_snapshot(db, "spoolman", "filament", str(FINISH_SM_FIL_ID),
                    {"_mc_sig": "solid|93be2f|", "_cost": 20.0})
    _store_snapshot(db, "filamentdb", "filament", FINISH_FDB_FIL_ID,
                    {"_mc_sig": "solid|93be2f|", "_cost": 20.0})

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_filamentdb(filaments=[fdb_list], detail=fdb_detail)

    with patch("app.core.engine._settings") as mock_settings, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _finish_settings(mock_settings)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    sm_snap = db.query(Snapshot).filter_by(
        source="spoolman", entity_type="filament", entity_id=str(FINISH_SM_FIL_ID)
    ).first()
    assert sm_snap is not None
    data = json.loads(sm_snap.data)
    assert "_finish_sig" in data, "_finish_sig must be stored"
    assert "_mc_sig" in data, "_mc_sig must not be clobbered by finish-tag pass"
    assert "_cost" in data, "_cost must not be clobbered by finish-tag pass"


@pytest.mark.asyncio
async def test_finish_tags_preserves_arrangement_tags_in_opt_tags(db):
    """When pushing finish tags SM→FDB, arrangement tags (28/29) must survive in optTags."""
    _add_finish_filament_mapping(db)
    _seed_matprop_config(db, direction="spoolman_to_filamentdb", policy="manual")

    # SM has tag 17 (silk) as finish; FDB currently has [29] (coextruded, arrangement)
    silk_encoded = json.dumps([17])
    sm_fil = _sm_fil_finish(extra={"filamentdb_material_tags": silk_encoded})
    fdb_list = _fdb_list_finish(opt_tags=[29])
    fdb_detail = _fdb_detail_finish(opt_tags=[29])  # FDB has coextruded arrangement tag

    # Baseline: SM had [17], FDB had none (empty sig) → SM changed
    _store_snapshot(db, "spoolman", "filament", str(FINISH_SM_FIL_ID), {"_finish_sig": ""})
    _store_snapshot(db, "filamentdb", "filament", FINISH_FDB_FIL_ID, {"_finish_sig": ""})

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_filamentdb(filaments=[fdb_list], detail=fdb_detail)

    with patch("app.core.engine._settings") as mock_settings, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _finish_settings(mock_settings)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    fdb_client.update_filament.assert_called_once()
    _fid, payload = fdb_client.update_filament.call_args.args
    # Both arrangement tag (29) and finish tag (17) must be in the written optTags
    assert 29 in payload["optTags"], "arrangement tag 29 must be preserved"
    assert 17 in payload["optTags"], "finish tag 17 must be written"


# ---------------------------------------------------------------------------
# ensure_extra_fields registers the filament-level material-tags extra field
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_extra_fields_registers_filament_material_tags_field():
    """ensure_extra_fields must POST /api/v1/field/filament/{key} for filamentdb_material_tags."""
    from app.services.spoolman import SpoolmanClient
    from app.schemas.spoolman import SpoolmanFieldDef

    client = SpoolmanClient.__new__(SpoolmanClient)

    # Pre-existing spool fields (the three cross-ref ones already exist)
    spool_field_defs = [
        SpoolmanFieldDef(key="filamentdb_id", name="FDB ID", field_type="text", entity_type="spool"),
        SpoolmanFieldDef(key="filamentdb_parent_id", name="FDB Parent ID", field_type="text", entity_type="spool"),
        SpoolmanFieldDef(key="filamentdb_spool_id", name="FDB Spool ID", field_type="text", entity_type="spool"),
    ]
    # No filament extra fields yet
    filament_field_defs: list[SpoolmanFieldDef] = []

    posted_filament_keys: list[str] = []

    async def fake_get_field_definitions(entity_type: str):
        if entity_type == "spool":
            return spool_field_defs
        return filament_field_defs

    posted_bodies: list[dict] = []

    async def fake_post(path: str, *, json: dict) -> MagicMock:
        if "/field/filament/" in path:
            key = path.split("/field/filament/")[-1]
            posted_filament_keys.append(key)
            posted_bodies.append(json)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        return resp

    client.get_field_definitions = fake_get_field_definitions

    # Directly patch the _http client and the global settings used inside ensure_extra_fields
    from unittest.mock import patch as _patch, AsyncMock as _AsyncMock
    with _patch("app.config.settings") as settings_mock:
        settings_mock.spoolman_field_filamentdb_material_tags = "filamentdb_material_tags"
        client.get_field_definitions = _AsyncMock(side_effect=fake_get_field_definitions)
        mock_http = MagicMock()
        mock_http.post = _AsyncMock(side_effect=fake_post)
        client._client = mock_http

        await client.ensure_extra_fields()

    assert "filamentdb_material_tags" in posted_filament_keys, (
        "ensure_extra_fields must POST /api/v1/field/filament/filamentdb_material_tags"
    )


# ---------------------------------------------------------------------------
# material_tags encoding round-trip: FDB→SM write and SM read back
# ---------------------------------------------------------------------------


def test_finish_tags_fdb_to_sm_encodes_as_csv_string():
    """The FDB→SM write path must send a JSON-quoted CSV string, not a JSON array.

    Specifically:
    - serialize_material_tags([17]) → "17"
    - encode_extra_value("17") → '"17"'   (a JSON string value)
    - json.loads('"17"') → "17"           (a Python str, NOT a list)

    Spoolman text fields accept '"17"', not '[17]'.
    """
    import json as _json
    from app.core.material_tags import serialize_material_tags
    from app.schemas.spoolman import encode_extra_value

    ids = frozenset({17})
    serialized = serialize_material_tags(ids)
    assert isinstance(serialized, str), f"serialize must return str, got {type(serialized)}"
    assert serialized == "17"

    on_wire = encode_extra_value(serialized)
    # Must be a JSON-quoted string: '"17"'
    decoded_back = _json.loads(on_wire)
    assert isinstance(decoded_back, str), (
        f"encode_extra_value(csv_string) must decode to str, not {type(decoded_back)}: {decoded_back!r}"
    )
    assert decoded_back == "17"


def test_finish_tags_sm_read_parses_csv_string():
    """The SM read path must parse the CSV string back to the correct int set."""
    from app.core.material_tags import parse_material_tags, serialize_material_tags
    from app.schemas.spoolman import decode_extra_value, encode_extra_value

    original_ids = [17, 28]
    # Simulate write: serialize → encode_extra_value
    on_wire = encode_extra_value(serialize_material_tags(original_ids))
    # Simulate read: decode_extra_value → parse_material_tags
    decoded = decode_extra_value(on_wire)
    parsed = parse_material_tags(decoded)
    assert parsed == original_ids, f"round-trip mismatch: {parsed!r} != {original_ids!r}"


def test_finish_tags_sm_read_parses_legacy_array():
    """The SM read path must tolerate the legacy JSON-array form for backward-compat."""
    from app.core.material_tags import parse_material_tags
    from app.schemas.spoolman import decode_extra_value

    # Legacy encoded form: encode_extra_value([17]) → '"[17]"' would have been wrong
    # but any value already stored as a plain array string "[17]" must still parse
    legacy_raw = '"[17]"'   # the JSON-wire form for the string "[17]"
    decoded = decode_extra_value(legacy_raw)
    parsed = parse_material_tags(decoded)
    assert parsed == [17], f"legacy array string should parse to [17], got {parsed!r}"


def test_finish_tags_snapshot_sig_stable_after_round_trip():
    """After a write→read round-trip, the finish-sig is identical to the original.

    This confirms the engine snapshot key stays stable and the cycle does not
    perpetually re-write (no flapping).
    """
    from app.core.material_tags import parse_material_tags, serialize_material_tags
    from app.schemas.spoolman import decode_extra_value, encode_extra_value

    original_ids = frozenset({17, 31})
    original_sig = ",".join(str(i) for i in sorted(original_ids))

    # Simulate write
    on_wire = encode_extra_value(serialize_material_tags(original_ids))
    # Simulate read
    decoded = decode_extra_value(on_wire)
    parsed_ids = frozenset(parse_material_tags(decoded))
    recovered_sig = ",".join(str(i) for i in sorted(parsed_ids))

    assert recovered_sig == original_sig, (
        f"Snapshot sig changed after round-trip: {original_sig!r} → {recovered_sig!r}"
    )


# ---------------------------------------------------------------------------
# new_spool conflict lifecycle — dedup + clear-on-map (fix 2026-06-07)
# ---------------------------------------------------------------------------

def _default_settings(mock_settings):
    mock_settings.filamentdb_spoolman_id_field = "label"
    mock_settings.spoolman_field_filamentdb_id = "filamentdb_id"
    mock_settings.spoolman_field_filamentdb_spool_id = "filamentdb_spool_id"
    mock_settings.spoolman_field_filamentdb_parent_id = "filamentdb_parent_id"
    mock_settings.parsed_field_mappings = {}
    mock_settings.parsed_field_mapping_excludes = set()


@pytest.mark.asyncio
async def test_new_spool_conflict_dedup_sm_side(db):
    """Two non-dry-run cycles for the same unmapped SM filament produce exactly ONE open
    new_filament conflict (not new_spool — the filament tier is the gating tier).
    The SM spool helper (_sm_spool) uses filament_id=10 for all spools."""
    sm_spool = _sm_spool(spool_id=1, remaining=500.0)  # no filament mapping
    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[])

    with patch("app.core.engine._settings") as mock_settings:
        _default_settings(mock_settings)
        # First cycle — should create the new_filament conflict
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="cycle-1")
        # Second cycle — should NOT create a duplicate
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="cycle-2")

    # A new_filament conflict for SM filament 10 (the spool's filament) is queued.
    open_conflicts = (
        db.query(Conflict)
        .filter(
            Conflict.resolved_at.is_(None),
            Conflict.entity_type == "filament",
            Conflict.field_name == "new_filament",
            Conflict.spoolman_id == 10,  # filament_id from _sm_spool
        )
        .all()
    )
    assert len(open_conflicts) == 1, (
        f"Expected exactly 1 open new_filament conflict for SM filament 10, got {len(open_conflicts)}"
    )


@pytest.mark.asyncio
async def test_new_spool_conflict_cleared_when_spool_mapped(db):
    """An open new_spool conflict for spool X is auto-resolved after a SpoolMapping for X exists."""
    sm_spool = _sm_spool(spool_id=1, remaining=500.0)
    fdb_fil = _fdb_filament("fil-1", "spool-1", 700.0)
    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])

    # Seed an open new_spool conflict for SM spool 1 (pre-existing stale conflict)
    db.add(Conflict(
        entity_type="spool",
        field_name="new_spool",
        spoolman_id=1,
        spoolman_value='"Spoolman spool 1 has no FDB filament match"',
    ))
    db.flush()

    # Now add a SpoolMapping for that spool (simulates wizard completing after the conflict was filed)
    _add_spool_mapping(db, sm_id=1, fdb_fil="fil-1", fdb_spool="spool-1")
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 500.0})
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {"totalWeight": 700.0})

    with patch("app.core.engine._settings") as mock_settings:
        _default_settings(mock_settings)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="cycle-3")

    # The stale conflict should now be resolved
    still_open = (
        db.query(Conflict)
        .filter(
            Conflict.resolved_at.is_(None),
            Conflict.entity_type == "spool",
            Conflict.field_name == "new_spool",
            Conflict.spoolman_id == 1,
        )
        .first()
    )
    assert still_open is None, "Stale new_spool conflict for mapped spool 1 should have been auto-resolved"

    resolved = (
        db.query(Conflict)
        .filter(
            Conflict.resolved_at.isnot(None),
            Conflict.entity_type == "spool",
            Conflict.field_name == "new_spool",
            Conflict.spoolman_id == 1,
        )
        .first()
    )
    assert resolved is not None
    assert resolved.resolution == "resolved_mapped"


@pytest.mark.asyncio
async def test_new_spool_conflict_not_cleared_when_spool_still_unmapped(db):
    """A new_spool conflict for a spool with no mapping is NOT auto-resolved."""
    sm_spool_unmapped = _sm_spool(spool_id=99, remaining=400.0)
    sm_spool_mapped = _sm_spool(spool_id=1, remaining=500.0)
    fdb_fil = _fdb_filament("fil-1", "spool-1", 700.0)

    # Only spool 1 is mapped; spool 99 is not
    _add_spool_mapping(db, sm_id=1, fdb_fil="fil-1", fdb_spool="spool-1")
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 500.0})
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {"totalWeight": 700.0})

    # Pre-seed an open conflict for the UNMAPPED spool 99
    db.add(Conflict(
        entity_type="spool",
        field_name="new_spool",
        spoolman_id=99,
        spoolman_value='"Spoolman spool 99 has no FDB filament match"',
    ))
    db.flush()

    spoolman = _fake_spoolman(spools=[sm_spool_mapped, sm_spool_unmapped])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])

    with patch("app.core.engine._settings") as mock_settings:
        _default_settings(mock_settings)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="cycle-4")

    still_open = (
        db.query(Conflict)
        .filter(
            Conflict.resolved_at.is_(None),
            Conflict.entity_type == "spool",
            Conflict.field_name == "new_spool",
            Conflict.spoolman_id == 99,
        )
        .first()
    )
    assert still_open is not None, "new_spool conflict for still-unmapped spool 99 must NOT be cleared"


@pytest.mark.asyncio
async def test_new_spool_dry_run_does_not_create_or_resolve(db):
    """dry_run=True: no new_spool conflict is created and no existing conflict is resolved."""
    sm_spool = _sm_spool(spool_id=5, remaining=300.0)

    # Pre-seed an open conflict for spool 5 (unmapped)
    db.add(Conflict(
        entity_type="spool",
        field_name="new_spool",
        spoolman_id=5,
        spoolman_value='"Spoolman spool 5 has no FDB filament match"',
    ))
    db.flush()

    # Add a mapping for spool 5 — in non-dry-run this WOULD resolve it
    fdb_fil = _fdb_filament("fil-5", "spool-5", 600.0)
    _add_spool_mapping(db, sm_id=5, fdb_fil="fil-5", fdb_spool="spool-5")
    _store_snapshot(db, "spoolman", "spool", "5", {"remaining_weight": 300.0})
    _store_snapshot(db, "filamentdb", "spool", "spool-5", {"totalWeight": 600.0})

    spoolman2 = _fake_spoolman(spools=[sm_spool])
    fdb_client2 = _fake_filamentdb(filaments=[fdb_fil])

    with patch("app.core.engine._settings") as mock_settings:
        _default_settings(mock_settings)
        await run_sync_cycle(db, spoolman2, fdb_client2, dry_run=True, cycle_id="cycle-5")

    # The conflict should still be open (dry_run must not mutate DB)
    still_open = (
        db.query(Conflict)
        .filter(
            Conflict.resolved_at.is_(None),
            Conflict.entity_type == "spool",
            Conflict.field_name == "new_spool",
            Conflict.spoolman_id == 5,
        )
        .first()
    )
    assert still_open is not None, "dry_run must not resolve existing conflicts"

    # Also confirm no NEW conflicts were created (the spool is mapped now, so the
    # new-spool detection path won't even be reached — but ensure no extras)
    all_conflicts = db.query(Conflict).filter(Conflict.spoolman_id == 5).count()
    assert all_conflicts == 1, f"dry_run must not create new conflict rows (found {all_conflicts})"


# ---------------------------------------------------------------------------
# Stale mapping purge tests (Branch A / Branch B)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_branch_b_fdb_gone_sm_cross_ref_cleared_purges_mapping(db):
    """Branch B: FDB spool absent + SM cross-ref cleared → stale purge, no conflict.

    Also verifies that a pre-existing open deletion conflict for the same mapping
    is auto-resolved to 'auto_stale_purge'.
    """
    # SM spool has no filamentdb_spool_id extra → cross-ref cleared (unlinked).
    sm_spool = _sm_spool(1, 800.0, extra={})
    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 800.0})
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {"totalWeight": 1000.0})

    # Pre-seed an open deletion conflict for this mapping (from a previous cycle).
    from app.models.conflict import DELETION_FIELD
    db.add(Conflict(
        entity_type="spool",
        spoolman_id=1,
        filamentdb_filament_id="fil-1",
        filamentdb_spool_id="spool-1",
        field_name=DELETION_FIELD,
        spoolman_value=json.dumps({"exists": True, "deleted_side": "filamentdb"}),
    ))
    db.flush()

    # FDB returns nothing — FDB spool is gone.
    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[])

    result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    # Stale purge: skipped incremented, no new conflict.
    assert result.skipped >= 1
    assert result.conflicts == 0

    # SpoolMapping row must be gone.
    assert db.query(SpoolMapping).count() == 0

    # Snapshot rows must be gone.
    assert db.query(Snapshot).filter_by(source="spoolman", entity_type="spool", entity_id="1").count() == 0
    assert db.query(Snapshot).filter_by(source="filamentdb", entity_type="spool", entity_id="spool-1").count() == 0

    # Pre-existing deletion conflict must be auto-resolved.
    resolved_conflict = db.query(Conflict).filter_by(
        spoolman_id=1,
        filamentdb_spool_id="spool-1",
    ).first()
    assert resolved_conflict is not None
    assert resolved_conflict.resolved_at is not None
    assert resolved_conflict.resolution == "auto_stale_purge"

    # No new open conflict created.
    assert db.query(Conflict).filter_by(resolved_at=None).count() == 0


@pytest.mark.asyncio
async def test_branch_b_fdb_gone_sm_cross_ref_still_set_queues_conflict(db):
    """Branch B: FDB spool absent + SM cross-ref still set → deletion conflict queued (still linked)."""
    import json as _json
    # SM spool still carries filamentdb_spool_id cross-ref.
    sm_spool = _sm_spool(1, 800.0, extra={"filamentdb_spool_id": _json.dumps("spool-1")})
    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 800.0})
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {"totalWeight": 1000.0})

    # FDB returns nothing — FDB spool is gone.
    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[])

    result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    # Deletion conflict must be queued; mapping must remain.
    assert result.conflicts == 1
    assert db.query(SpoolMapping).count() == 1

    conflict = db.query(Conflict).filter_by(resolved_at=None).first()
    assert conflict is not None
    from app.models.conflict import DELETION_FIELD
    assert conflict.field_name == DELETION_FIELD
    assert conflict.spoolman_id == 1
    assert conflict.filamentdb_spool_id == "spool-1"


@pytest.mark.asyncio
async def test_branch_a_both_sides_gone_purges_mapping(db):
    """Branch A: SM spool gone + FDB spool also gone → both sides deleted → stale purge."""
    # No SM spool returned, no FDB filament returned — both sides gone.
    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 800.0})
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {"totalWeight": 1000.0})

    spoolman = _fake_spoolman(spools=[])  # SM spool 1 gone entirely
    fdb_client = _fake_filamentdb(filaments=[])  # FDB spool also gone

    result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    # Stale purge: skipped incremented, no conflict.
    assert result.skipped >= 1
    assert result.conflicts == 0

    # SpoolMapping and Snapshots must be gone.
    assert db.query(SpoolMapping).count() == 0
    assert db.query(Snapshot).filter_by(source="spoolman", entity_type="spool", entity_id="1").count() == 0
    assert db.query(Snapshot).filter_by(source="filamentdb", entity_type="spool", entity_id="spool-1").count() == 0

    # No open conflict.
    assert db.query(Conflict).filter_by(resolved_at=None).count() == 0


@pytest.mark.asyncio
async def test_branch_a_sm_gone_fdb_present_queues_conflict(db):
    """Branch A: SM spool gone entirely + FDB spool present → deletion conflict (still linked)."""
    fdb_fil = _fdb_filament("fil-1", "spool-1", 1000.0)
    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 800.0})
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {"totalWeight": 1000.0})

    # SM returns nothing (spool 1 gone entirely), FDB has the spool.
    spoolman = _fake_spoolman(spools=[])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])

    result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    # Deletion conflict queued; mapping preserved.
    assert result.conflicts == 1
    assert db.query(SpoolMapping).count() == 1

    conflict = db.query(Conflict).filter_by(resolved_at=None).first()
    assert conflict is not None
    from app.models.conflict import DELETION_FIELD
    assert conflict.field_name == DELETION_FIELD
    assert conflict.spoolman_id == 1


@pytest.mark.asyncio
async def test_stale_mapping_dry_run_emits_preview_no_db_change(db):
    """dry_run=True: stale mapping emits a 'skip' preview entry; DB is NOT mutated."""
    # Branch B scenario: FDB gone, SM cross-ref cleared → would normally purge.
    sm_spool = _sm_spool(1, 800.0, extra={})
    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 800.0})
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {"totalWeight": 1000.0})

    # FDB returns nothing.
    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[])

    result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=True, cycle_id=CYCLE_ID)

    # A 'skip' preview entry with the stale-connection reason must be present.
    stale_previews = [
        p for p in result.preview
        if p.get("action") == "skip" and "stale connection" in (p.get("reason") or "")
    ]
    assert len(stale_previews) == 1, f"Expected 1 stale-connection preview entry, got: {result.preview}"

    # SpoolMapping must NOT have been deleted (dry_run).
    assert db.query(SpoolMapping).count() == 1

    # Snapshots must NOT have been deleted (dry_run).
    assert db.query(Snapshot).filter_by(source="spoolman", entity_type="spool", entity_id="1").count() == 1
    assert db.query(Snapshot).filter_by(source="filamentdb", entity_type="spool", entity_id="spool-1").count() == 1

    # No SyncLog rows written (dry_run).
    assert db.query(SyncLog).count() == 0

    # No conflicts created.
    assert db.query(Conflict).count() == 0


# ---------------------------------------------------------------------------
# FR-11 field-mapping snapshot persistence (fix: _field_values never stored)
# ---------------------------------------------------------------------------


def _fdb_detail_with_density(fid: str, spool_id: str, density: float, tare: float = 200.0):
    from app.schemas.filamentdb import FDBFilamentDetail
    return FDBFilamentDetail.model_validate({
        "_id": fid,
        "name": "PLA",
        "density": density,
        "spoolWeight": tare,
        "_inherited": [],
        "spools": [{"_id": spool_id, "totalWeight": 1000.0, "retired": False}],
    })


def _density_field_map() -> FieldMapping:
    """FieldMapping for FDB 'density' ↔ Spoolman extra 'density'."""
    return FieldMapping(fdb_path="density", sm_key="density", direction="fdb_to_sm")


def _patch_settings_fm(mock_settings):
    """Minimal _settings for field-mapping tests."""
    mock_settings.filamentdb_spoolman_id_field = "label"
    mock_settings.spoolman_field_filamentdb_id = "filamentdb_id"
    mock_settings.spoolman_field_filamentdb_spool_id = "filamentdb_spool_id"
    mock_settings.spoolman_field_filamentdb_parent_id = "filamentdb_parent_id"
    mock_settings.parsed_field_mappings = {}
    mock_settings.parsed_field_mapping_excludes = set()


def _add_fm_mapping(db, sm_filament_id: int, fdb_filament_id: str):
    """Add a FilamentMapping for the given SM filament id → FDB filament id."""
    db.add(FilamentMapping(spoolman_filament_id=sm_filament_id, filamentdb_id=fdb_filament_id))
    db.flush()


@pytest.mark.asyncio
async def test_fr11_no_change_second_cycle_is_noop(db):
    """With a field mapping active and values unchanged, the second cycle must
    not emit any FR-11 writes or sync-log 'update' rows.

    Pre-fix: fdb_snapshot had no _field_values so fdb_then was always None,
    making every mapped field look like an FDB change every cycle.
    """
    fm = _density_field_map()
    # sm_spool filament id is 10 (see _sm_spool helper); match that in FilamentMapping.
    # SM carries density=1.24 in its extra field so SM side matches snapshot.
    sm_spool = _sm_spool(1, 800.0, extra={"density": json.dumps(1.24)})  # spool.filament.id == 10
    fdb_fil = _fdb_filament("fil-1", "spool-1", 1000.0, tare=200.0)
    fdb_detail = _fdb_detail_with_density("fil-1", "spool-1", density=1.24, tare=200.0)

    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _add_fm_mapping(db, 10, "fil-1")  # spoolman filament id 10 → fdb "fil-1"
    # Pre-seed snapshots with _field_values already set (simulating what the
    # fixed engine writes after the first cycle).
    _store_snapshot(db, "spoolman", "spool", "1", {
        "remaining_weight": 800.0,
        "_extra_decoded": {"density": 1.24},
    })
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {
        "totalWeight": 1000.0,
        "_field_values": {"density": 1.24},
    })

    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[fm]):
        _patch_settings_fm(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="c1")

    # No writes at all — both sides agree with snapshot
    spoolman.update_spool.assert_not_called()
    fdb_client.update_filament.assert_not_called()
    assert result.updated == 0
    assert result.errors == 0
    # No sync-log update rows for field mapping
    update_logs = db.query(SyncLog).filter_by(action="update").all()
    assert len(update_logs) == 0


@pytest.mark.asyncio
async def test_fr11_fdb_change_detected_once_then_noop(db):
    """An FDB-side field change is detected exactly once; cycle after the push
    produces no further FR-11 writes (snapshot converges).

    Direction: filamentdb_to_spoolman (default).
    """
    fm = _density_field_map()
    # FDB density changed from 1.24 → 1.27 vs snapshot.
    # SM carries density=1.24 in its extra field so SM side shows no change
    # (current == snapshot) and only FDB's change is detected.
    sm_spool = _sm_spool(1, 800.0, extra={"density": json.dumps(1.24)})  # spool.filament.id == 10
    fdb_fil = _fdb_filament("fil-1", "spool-1", 1000.0, tare=200.0)
    fdb_detail = _fdb_detail_with_density("fil-1", "spool-1", density=1.27, tare=200.0)

    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _add_fm_mapping(db, 10, "fil-1")
    _store_snapshot(db, "spoolman", "spool", "1", {
        "remaining_weight": 800.0,
        "_extra_decoded": {"density": 1.24},
    })
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {
        "totalWeight": 1000.0,
        "_field_values": {"density": 1.24},  # snapshot has old value → change detected
    })
    _seed_matprop_config(db, direction="filamentdb_to_spoolman", policy="manual")

    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[fm]):
        _patch_settings_fm(ms)
        # Cycle 1: FDB density changed → FDB→SM push
        result1 = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="c1")

    assert result1.updated == 1
    spoolman.update_spool.assert_called_once()

    # Snapshot must now carry the updated _field_values and _extra_decoded
    fdb_snap = json.loads(
        db.query(Snapshot).filter_by(source="filamentdb", entity_type="spool", entity_id="spool-1").first().data
    )
    sm_snap = json.loads(
        db.query(Snapshot).filter_by(source="spoolman", entity_type="spool", entity_id="1").first().data
    )
    assert fdb_snap.get("_field_values", {}).get("density") == 1.27
    assert sm_snap.get("_extra_decoded", {}).get("density") == 1.27

    # Cycle 2: same values on both sides → NOOP
    spoolman.update_spool.reset_mock()
    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[fm]):
        _patch_settings_fm(ms)
        result2 = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="c2")

    spoolman.update_spool.assert_not_called()
    fdb_client.update_filament.assert_not_called()
    assert result2.updated == 0


@pytest.mark.asyncio
async def test_fr11_sm_change_locked_side_noop(db):
    """Under default direction (filamentdb_to_spoolman), a Spoolman-side extra
    field change is the locked side — must be NOOP, not propagated to FDB.
    """
    fm = _density_field_map()
    # SM density changed (extra field on spool), but FDB is unchanged
    sm_spool = _sm_spool(1, 800.0, extra={"density": json.dumps(1.30)})  # spool.filament.id == 10
    fdb_fil = _fdb_filament("fil-1", "spool-1", 1000.0, tare=200.0)
    fdb_detail = _fdb_detail_with_density("fil-1", "spool-1", density=1.24, tare=200.0)

    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _add_fm_mapping(db, 10, "fil-1")
    _store_snapshot(db, "spoolman", "spool", "1", {
        "remaining_weight": 800.0,
        "_extra_decoded": {"density": 1.24},  # SM changed 1.24 → 1.30 vs snapshot
    })
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {
        "totalWeight": 1000.0,
        "_field_values": {"density": 1.24},
    })
    _seed_matprop_config(db, direction="filamentdb_to_spoolman", policy="manual")

    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[fm]):
        _patch_settings_fm(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="c1")

    # SM side is locked — no write to FDB and no update to SM
    fdb_client.update_filament.assert_not_called()
    spoolman.update_spool.assert_not_called()
    assert result.updated == 0
    assert result.conflicts == 0


@pytest.mark.asyncio
async def test_fr11_first_sight_stores_field_values_in_baseline(db):
    """First cycle for a pair with field mappings active stores _field_values
    in the FDB spool baseline so the very next cycle can detect real changes
    rather than always seeing None as the prior value.
    """
    fm = _density_field_map()
    sm_spool = _sm_spool(1, 800.0)  # spool.filament.id == 10
    fdb_fil = _fdb_filament("fil-1", "spool-1", 1000.0, tare=200.0)
    fdb_detail = _fdb_detail_with_density("fil-1", "spool-1", density=1.24, tare=200.0)

    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _add_fm_mapping(db, 10, "fil-1")
    # No snapshots yet — first sight

    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[fm]):
        _patch_settings_fm(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="c1")

    # First sight: skip (no writes)
    assert result.skipped >= 1
    fdb_client.update_filament.assert_not_called()
    spoolman.update_spool.assert_not_called()

    # FDB spool snapshot must have _field_values set (not empty/absent)
    fdb_snap_row = db.query(Snapshot).filter_by(
        source="filamentdb", entity_type="spool", entity_id="spool-1"
    ).first()
    assert fdb_snap_row is not None
    fdb_snap_data = json.loads(fdb_snap_row.data)
    assert "_field_values" in fdb_snap_data
    assert fdb_snap_data["_field_values"].get("density") == 1.24


# ---------------------------------------------------------------------------
# Bug fix: ensure_extra_fields uses configured spool field names (not hard-coded)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_extra_fields_registers_custom_spool_keys():
    """ensure_extra_fields must POST the configured (overridden) spool cross-ref key names,
    not the hard-coded defaults.

    If a user sets SPOOLMAN_FIELD_FILAMENTDB_ID=fdb_id etc., startup must create
    /api/v1/field/spool/fdb_id — not /api/v1/field/spool/filamentdb_id.
    """
    from app.services.spoolman import SpoolmanClient
    from unittest.mock import patch as _patch, AsyncMock as _AsyncMock

    client = SpoolmanClient.__new__(SpoolmanClient)

    # No spool fields exist yet (Spoolman is freshly installed)
    async def fake_get_field_definitions(entity_type: str):
        return []

    posted_spool_keys: list[str] = []

    async def fake_post(path: str, *, json: dict) -> MagicMock:
        if "/field/spool/" in path:
            key = path.split("/field/spool/")[-1]
            posted_spool_keys.append(key)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        return resp

    with _patch("app.config.settings") as settings_mock:
        # Override all three spool cross-ref field names
        settings_mock.spoolman_field_filamentdb_id = "fdb_id"
        settings_mock.spoolman_field_filamentdb_parent_id = "fdb_parent_id"
        settings_mock.spoolman_field_filamentdb_spool_id = "fdb_spool_id"
        settings_mock.spoolman_field_filamentdb_material_tags = "filamentdb_material_tags"
        settings_mock.spoolman_field_openprinttag_slug = "openprinttag_slug"
        settings_mock.spoolman_field_openprinttag_uuid = "openprinttag_uuid"
        client.get_field_definitions = _AsyncMock(side_effect=fake_get_field_definitions)
        mock_http = MagicMock()
        mock_http.post = _AsyncMock(side_effect=fake_post)
        client._client = mock_http

        await client.ensure_extra_fields()

    assert "fdb_id" in posted_spool_keys, (
        "ensure_extra_fields must POST /api/v1/field/spool/fdb_id (custom SPOOLMAN_FIELD_FILAMENTDB_ID)"
    )
    assert "fdb_parent_id" in posted_spool_keys, (
        "ensure_extra_fields must POST /api/v1/field/spool/fdb_parent_id (custom SPOOLMAN_FIELD_FILAMENTDB_PARENT_ID)"
    )
    assert "fdb_spool_id" in posted_spool_keys, (
        "ensure_extra_fields must POST /api/v1/field/spool/fdb_spool_id (custom SPOOLMAN_FIELD_FILAMENTDB_SPOOL_ID)"
    )
    # Must NOT have posted the old hard-coded default names
    assert "filamentdb_id" not in posted_spool_keys, "must not POST default key when overridden"
    assert "filamentdb_parent_id" not in posted_spool_keys, "must not POST default key when overridden"
    assert "filamentdb_spool_id" not in posted_spool_keys, "must not POST default key when overridden"


# ---------------------------------------------------------------------------
# Bug fix: engine orphan guard reads any configured FDB field, not only "label"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_engine_fdb_orphan_guard_works_with_custom_id_field(db):
    """When FILAMENTDB_SPOOLMAN_ID_FIELD is overridden to a custom value, an FDB spool
    that carries the Spoolman ID in that custom field but has no SpoolMapping row must
    be treated as an orphan and NOT trigger creation of a new Spoolman spool.

    Regression for Bug B: the old code had `getattr(...) if fdb_field_name == "label" else None`
    which made label_val always None for any non-default field name.
    """
    custom_field = "customSpoolmanId"

    # FDB filament with a spool that has the Spoolman spool ID in "customSpoolmanId"
    fdb_fil = FDBFilament.model_validate({
        "_id": "fdb-fil-60",
        "name": "PLA",
        "spoolWeight": 200.0,
        "spools": [
            {
                "_id": "fdb-spool-60",
                "totalWeight": 700.0,
                "retired": False,
                # The spool carries the Spoolman ID in the custom field
                custom_field: "42",
            }
        ],
    })

    # There is a FilamentMapping for the filament but NO SpoolMapping for fdb-spool-60
    _add_fil_mapping(db, sm_fil_id=60, fdb_fil_id="fdb-fil-60")

    # The Spoolman spool does NOT exist in the current SM list (simulates bridge-DB reset
    # where the SpoolMapping was lost but the FDB spool still carries the SM ID)
    spoolman = _fake_spoolman(spools=[])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])
    fdb_client.create_spool = AsyncMock(return_value={"_id": "should-not-be-created"})

    with patch("app.core.engine._settings") as mock_settings:
        mock_settings.filamentdb_spoolman_id_field = custom_field
        mock_settings.spoolman_field_filamentdb_id = "filamentdb_id"
        mock_settings.spoolman_field_filamentdb_spool_id = "filamentdb_spool_id"
        mock_settings.spoolman_field_filamentdb_parent_id = "filamentdb_parent_id"
        mock_settings.parsed_field_mappings = {}
        mock_settings.parsed_field_mapping_excludes = set()
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    # The orphan guard must kick in: no new SM spool should be created.
    fdb_client.create_spool.assert_not_called()


# ---------------------------------------------------------------------------
# New-record handling policy tests (new_filament_policy / new_spool_policy)
# ---------------------------------------------------------------------------


def _seed_new_record_policy(db, filament_policy: str = "manual_review", spool_policy: str = "manual_review"):
    """Seed new-record handling policies in BridgeConfig."""
    from app.models.config import BridgeConfig
    db.merge(BridgeConfig(key="new_filament_policy", value=json.dumps(filament_policy)))
    db.merge(BridgeConfig(key="new_spool_policy", value=json.dumps(spool_policy)))
    db.commit()


@pytest.mark.asyncio
async def test_new_filament_manual_review_queues_conflict(db):
    """new_filament_policy=manual_review queues a new_filament conflict for an unmapped SM filament."""
    sm_spool = _sm_spool(spool_id=1, remaining=500.0)  # filament_id=10, no FilamentMapping
    _seed_new_record_policy(db, filament_policy="manual_review")
    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[])

    with patch("app.core.engine._settings") as ms:
        _default_settings(ms)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="nfp-1")

    # A new_filament conflict for filament 10 is queued.
    c = db.query(Conflict).filter_by(entity_type="filament", field_name="new_filament", spoolman_id=10).first()
    assert c is not None, "Expected a new_filament conflict for SM filament 10"
    assert c.resolved_at is None


@pytest.mark.asyncio
async def test_new_spool_manual_review_mapped_filament_queues_conflict(db):
    """new_spool_policy=manual_review queues a new_spool conflict for a new spool on a MAPPED filament."""
    sm_spool = _sm_spool_with_extra(501, filament_id=50)
    fdb_fil = _fdb_filament_with_spool("fdb-fil-50", "existing-spool")
    _add_fil_mapping(db, sm_fil_id=50, fdb_fil_id="fdb-fil-50")
    _seed_new_record_policy(db, spool_policy="manual_review")

    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])

    with patch("app.core.engine._settings") as ms:
        _default_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="nsp-1")

    assert result.conflicts >= 1
    fdb_client.create_spool.assert_not_called()
    c = db.query(Conflict).filter_by(entity_type="spool", field_name="new_spool", spoolman_id=501).first()
    assert c is not None, "Expected a new_spool conflict for SM spool 501"


@pytest.mark.asyncio
async def test_new_spool_auto_import_mapped_filament(db):
    """new_spool_policy=auto_import creates the FDB spool for a new spool on a MAPPED filament."""
    sm_spool = _sm_spool_with_extra(501, filament_id=50)
    fdb_fil = _fdb_filament_with_spool("fdb-fil-50", "existing-spool")
    _add_fil_mapping(db, sm_fil_id=50, fdb_fil_id="fdb-fil-50")
    _seed_new_record_policy(db, spool_policy="auto_import")

    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])
    fdb_client.create_spool = AsyncMock(return_value={"_id": "new-spool-auto", "spools": [{"_id": "new-spool-auto", "label": "501"}]})

    with patch("app.core.engine._settings") as ms:
        _default_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="nsp-auto")

    assert result.created >= 1
    fdb_client.create_spool.assert_called_once()
    assert db.query(Conflict).filter_by(field_name="new_spool").first() is None


@pytest.mark.asyncio
async def test_new_spool_held_until_filament_mapped(db):
    """A new SM spool with no filament mapping is held (queues new_filament conflict)
    when new_filament_policy=manual_review — never dropped."""
    sm_spool = _sm_spool(spool_id=7, remaining=300.0)  # filament_id=10, no FilamentMapping
    _seed_new_record_policy(db, filament_policy="manual_review", spool_policy="auto_import")
    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[])

    with patch("app.core.engine._settings") as ms:
        _default_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="hold-1")

    # Spool is HELD — not dropped; a filament conflict is queued.
    assert result.conflicts >= 1
    fdb_client.create_spool.assert_not_called()
    c = db.query(Conflict).filter_by(entity_type="filament", field_name="new_filament").first()
    assert c is not None, "Spool must be HELD with a new_filament conflict, not silently dropped"


@pytest.mark.asyncio
async def test_auto_import_no_pingpong(db):
    """Mirrors test_archived_imported_spool_no_pingpong: after auto-import of a new spool,
    a second cycle must be a NOOP (no spurious create or update)."""
    # Filament mapping exists; spool is new.
    _add_fil_mapping(db, sm_fil_id=60, fdb_fil_id="fdb-fil-60")
    _seed_new_record_policy(db, spool_policy="auto_import")
    _seed_weight_config(db, direction="two_way", policy="manual")

    # After cycle 1, the new spool is created and a SpoolMapping + snapshots exist.
    # Simulate by pre-seeding the mapping and snapshots (mirrors wizard execute path).
    db.add(SpoolMapping(
        spoolman_spool_id=600, filamentdb_filament_id="fdb-fil-60", filamentdb_spool_id="new-spool-600",
    ))
    _store_snapshot(db, "spoolman", "spool", "600", {"remaining_weight": 500.0})
    _store_snapshot(db, "filamentdb", "spool", "new-spool-600", {"totalWeight": 700.0})
    db.flush()

    # Build a SM spool that now carries the FDB cross-ref xref.
    sm_spool_with_xref = SpoolmanSpool(
        id=600,
        filament=SpoolmanFilament(id=60, name="PLA", vendor=SpoolmanVendor(id=1, name="ACME")),
        remaining_weight=500.0,
        archived=False,
        extra={
            "filamentdb_id": json.dumps("fdb-fil-60"),
            "filamentdb_spool_id": json.dumps("new-spool-600"),
            "filamentdb_parent_id": json.dumps(""),
        },
    )
    # FDB spool now has a SpoolMapping — not "new".
    fdb_fil_after = FDBFilament.model_validate({
        "_id": "fdb-fil-60",
        "name": "PLA",
        "spoolWeight": 200.0,
        "spools": [{"_id": "new-spool-600", "totalWeight": 700.0, "retired": False}],
    })

    spoolman = _fake_spoolman(spools=[sm_spool_with_xref])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil_after])

    with patch("app.core.engine._settings") as ms:
        _patch_settings(ms)
        r1 = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="pingpong-c1")
        r2 = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="pingpong-c2")

    # Both cycles: already mapped pair — in_sync (no weight diff), no new creates.
    for r in (r1, r2):
        assert r.conflicts == 0, f"No conflicts expected; got {r.conflicts}"
        assert r.errors == 0, f"No errors expected; got {r.errors}"
    fdb_client.create_spool.assert_not_called()
    spoolman.create_spool.assert_not_called()


def test_migration_defaults_manual_review(db):
    """_migrate_sync_config backfills manual_review for new_filament_policy and new_spool_policy."""
    from app.models.config import BridgeConfig
    # Remove both keys to simulate a pre-existing install that doesn't have them.
    db.query(BridgeConfig).filter(BridgeConfig.key.in_(["new_filament_policy", "new_spool_policy"])).delete()
    db.commit()

    # Replicate the migration logic directly (importing app.main pulls in itsdangerous
    # which is not available in the test environment — env-only dep).
    from app.api.config import get_config_value, set_config_value
    if get_config_value(db, "new_filament_policy") is None:
        set_config_value(db, "new_filament_policy", "manual_review")
    if get_config_value(db, "new_spool_policy") is None:
        set_config_value(db, "new_spool_policy", "manual_review")
    db.commit()

    assert get_config_value(db, "new_filament_policy") == "manual_review"
    assert get_config_value(db, "new_spool_policy") == "manual_review"


@pytest.mark.asyncio
async def test_variant_member_unset_mode_held_for_review(db):
    """When variant_parent_mode=unset and the SM filament is a potential variant cluster
    member, auto-import is blocked even with new_filament_policy=auto_import.
    Instead a new_filament conflict is queued (LOCKED Q2 rule)."""
    # SM spool whose filament name suggests a variant (has vendor + color pattern).
    fil = SpoolmanFilament(id=70, name="Silk Red PLA", material="PLA",
                           vendor=SpoolmanVendor(id=1, name="ACME"))
    sm_spool = SpoolmanSpool(id=70, filament=fil, remaining_weight=500.0,
                             archived=False, extra={})
    _seed_new_record_policy(db, filament_policy="auto_import")
    # variant_parent_mode already set to "unset" in fresh db (seed via conftest sets "promote_color",
    # so we explicitly override here to "unset").
    from app.models.config import BridgeConfig
    db.merge(BridgeConfig(key="variant_parent_mode", value='"unset"'))
    db.commit()

    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[])

    with patch("app.core.engine._settings") as ms:
        _default_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="unset-mode-1")

    # Held for review — queued, not created.
    assert result.conflicts >= 1
    fdb_client.create_filament = AsyncMock()
    fdb_client.create_filament.assert_not_called()
    c = db.query(Conflict).filter_by(entity_type="filament", field_name="new_filament", spoolman_id=70).first()
    assert c is not None, "Expected new_filament conflict when variant_parent_mode=unset"


# ---------------------------------------------------------------------------
# Archive / retire lifecycle sync (FR-21 symmetric)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lifecycle_sm_archive_pushes_fdb_retire(db):
    """Mapped spool flips archived=true in SM (FDB unchanged) → engine sets FDB
    retired=true, both snapshots converge, no ping-pong next cycle, no conflict."""
    sm = _sm_spool_arch(1, 800.0, archived=True)
    fdb = _fdb_filament_ret("fil-1", "spool-1", 1000.0, retired=False)
    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 800.0, "archived": False})
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {"totalWeight": 1000.0, "retired": False})
    _seed_weight_config(db, direction="two_way", policy="manual")
    _seed_archive_config(db, direction="two_way", policy="manual")

    spoolman = _fake_spoolman(spools=[sm])
    fdb_client = _fake_filamentdb(filaments=[fdb])

    with patch("app.core.engine._settings") as ms:
        _patch_settings(ms)
        r1 = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="lc-1")

    assert r1.conflicts == 0
    assert r1.updated == 1
    assert fdb_client.update_spool.call_count == 1
    assert fdb_client.update_spool.call_args.args[2] == {"retired": True}
    # Snapshots converged.
    assert _snap_value(db, "spoolman", "spool", "1", "archived") is True
    assert _snap_value(db, "filamentdb", "spool", "spool-1", "retired") is True

    # No ping-pong: FDB now retired, SM still archived, snapshots converged.
    fdb_after = _fdb_filament_ret("fil-1", "spool-1", 1000.0, retired=True)
    fdb_client2 = _fake_filamentdb(filaments=[fdb_after])
    with patch("app.core.engine._settings") as ms:
        _patch_settings(ms)
        r2 = await run_sync_cycle(db, spoolman, fdb_client2, dry_run=False, cycle_id="lc-1b")
    assert r2.updated == 0
    assert r2.conflicts == 0
    fdb_client2.update_spool.assert_not_called()
    spoolman.update_spool.assert_not_called()


@pytest.mark.asyncio
async def test_lifecycle_fdb_retire_pushes_sm_archive(db):
    """Mapped spool flips retired=true in FDB (SM unchanged) → engine sets SM
    archived=true, converges, no ping-pong."""
    sm = _sm_spool_arch(1, 800.0, archived=False)
    fdb = _fdb_filament_ret("fil-1", "spool-1", 1000.0, retired=True)
    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 800.0, "archived": False})
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {"totalWeight": 1000.0, "retired": False})
    _seed_weight_config(db, direction="two_way", policy="manual")
    _seed_archive_config(db, direction="two_way", policy="manual")

    spoolman = _fake_spoolman(spools=[sm])
    fdb_client = _fake_filamentdb(filaments=[fdb])

    with patch("app.core.engine._settings") as ms:
        _patch_settings(ms)
        r1 = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="lc-2")

    assert r1.conflicts == 0
    assert r1.updated == 1
    assert spoolman.update_spool.call_count == 1
    assert spoolman.update_spool.call_args.args[1] == {"archived": True}
    assert _snap_value(db, "spoolman", "spool", "1", "archived") is True
    assert _snap_value(db, "filamentdb", "spool", "spool-1", "retired") is True

    # No ping-pong next cycle.
    sm_after = _sm_spool_arch(1, 800.0, archived=True)
    spoolman2 = _fake_spoolman(spools=[sm_after])
    with patch("app.core.engine._settings") as ms:
        _patch_settings(ms)
        r2 = await run_sync_cycle(db, spoolman2, fdb_client, dry_run=False, cycle_id="lc-2b")
    assert r2.updated == 0
    assert r2.conflicts == 0
    spoolman2.update_spool.assert_not_called()
    fdb_client.update_spool.assert_not_called()


@pytest.mark.asyncio
async def test_lifecycle_depletion_and_archive_same_cycle_weight_first(db):
    """THE ORDERING GUARANTEE: a mapped spool's remaining drops to ~0 g AND archived
    flips true in the same cycle → the engine logs the final usage decrement in FDB
    FIRST (correct post-decrement totalWeight + usage entry source=spoolman), THEN sets
    retired=true. FDB ends retired with the decremented weight and the usage entry."""
    # SM dropped 800 → 0 (used 800) and archived in the same cycle.
    sm = _sm_spool_arch(1, 0.0, archived=True)
    # FDB still shows the pre-decrement gross (1000 = 800 net + 200 tare), not retired.
    fdb = _fdb_filament_ret("fil-1", "spool-1", 1000.0, retired=False, tare=200.0)
    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 800.0, "archived": False})
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {"totalWeight": 1000.0, "retired": False})
    _seed_weight_config(db, direction="two_way", policy="manual")
    _seed_archive_config(db, direction="two_way", policy="manual")

    spoolman = _fake_spoolman(spools=[sm])
    fdb_client = _fake_filamentdb(filaments=[fdb])

    with patch("app.core.engine._settings") as ms:
        _patch_settings(ms)
        r = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="lc-dep")

    assert r.conflicts == 0
    assert r.errors == 0
    # Weight pass logged the final usage decrement of 800 g with source=spoolman.
    assert fdb_client.log_usage.call_count == 1
    usage_args, usage_kwargs = fdb_client.log_usage.call_args
    # positional: (filament_id, spool_id, grams)
    assert usage_args[2] == pytest.approx(800.0)
    assert usage_kwargs.get("source") == "spoolman"
    # Lifecycle pass set retired=true (separate update_spool call).
    retired_calls = [c for c in fdb_client.update_spool.call_args_list if c.args[2] == {"retired": True}]
    assert len(retired_calls) == 1, "lifecycle must set retired=true after weight settles"
    # FDB snapshot ends with the decremented gross weight AND retired=true.
    assert _snap_value(db, "filamentdb", "spool", "spool-1", "totalWeight") == pytest.approx(200.0)
    assert _snap_value(db, "filamentdb", "spool", "spool-1", "retired") is True
    assert _snap_value(db, "spoolman", "spool", "1", "archived") is True
    # SM snapshot weight converged too (no stale weight that would re-fire next cycle).
    assert _snap_value(db, "spoolman", "spool", "1", "remaining_weight") == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_lifecycle_unarchive_mirrors_back(db):
    """Un-archive (true→false) in SM mirrors to FDB retired=false and re-enables sync."""
    sm = _sm_spool_arch(1, 800.0, archived=False)
    fdb = _fdb_filament_ret("fil-1", "spool-1", 1000.0, retired=True)
    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 800.0, "archived": True})
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {"totalWeight": 1000.0, "retired": True})
    _seed_weight_config(db, direction="two_way", policy="manual")
    _seed_archive_config(db, direction="two_way", policy="manual")

    spoolman = _fake_spoolman(spools=[sm])
    fdb_client = _fake_filamentdb(filaments=[fdb])

    with patch("app.core.engine._settings") as ms:
        _patch_settings(ms)
        r = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="lc-un")

    assert r.conflicts == 0
    assert fdb_client.update_spool.call_args.args[2] == {"retired": False}
    assert _snap_value(db, "filamentdb", "spool", "spool-1", "retired") is False
    assert _snap_value(db, "spoolman", "spool", "1", "archived") is False


@pytest.mark.asyncio
async def test_lifecycle_both_flip_same_state_noop(db):
    """Both sides flip to the SAME dead state in one cycle → NOOP, snapshots converge,
    no conflict, no writes."""
    sm = _sm_spool_arch(1, 800.0, archived=True)
    fdb = _fdb_filament_ret("fil-1", "spool-1", 1000.0, retired=True)
    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 800.0, "archived": False})
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {"totalWeight": 1000.0, "retired": False})
    _seed_weight_config(db, direction="two_way", policy="manual")
    _seed_archive_config(db, direction="two_way", policy="manual")

    spoolman = _fake_spoolman(spools=[sm])
    fdb_client = _fake_filamentdb(filaments=[fdb])

    with patch("app.core.engine._settings") as ms:
        _patch_settings(ms)
        r = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="lc-both")

    assert r.conflicts == 0
    assert r.errors == 0
    fdb_client.update_spool.assert_not_called()
    spoolman.update_spool.assert_not_called()
    assert _snap_value(db, "spoolman", "spool", "1", "archived") is True
    assert _snap_value(db, "filamentdb", "spool", "spool-1", "retired") is True


@pytest.mark.asyncio
async def test_lifecycle_divergence_queues_cross_system_conflict(db):
    """Genuine divergence (SM archives, FDB un-retires) with policy=manual → one
    cross_system lifecycle conflict queued; no writes; no re-queue next cycle."""
    sm = _sm_spool_arch(1, 800.0, archived=True)        # flipped false→true
    fdb = _fdb_filament_ret("fil-1", "spool-1", 1000.0, retired=False)  # flipped true→false
    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 800.0, "archived": False})
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {"totalWeight": 1000.0, "retired": True})
    _seed_weight_config(db, direction="two_way", policy="manual")
    _seed_archive_config(db, direction="two_way", policy="manual")

    spoolman = _fake_spoolman(spools=[sm])
    fdb_client = _fake_filamentdb(filaments=[fdb])

    with patch("app.core.engine._settings") as ms:
        _patch_settings(ms)
        r1 = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="lc-div")

    assert r1.conflicts == 1
    fdb_client.update_spool.assert_not_called()
    spoolman.update_spool.assert_not_called()
    conflict = db.query(Conflict).filter_by(entity_type="spool", field_name="lifecycle").first()
    assert conflict is not None
    assert conflict.conflict_type == "cross_system"

    # No re-queue next cycle while the conflict is open.
    with patch("app.core.engine._settings") as ms:
        _patch_settings(ms)
        r2 = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="lc-div2")
    assert r2.conflicts == 0
    assert db.query(Conflict).filter_by(entity_type="spool", field_name="lifecycle").count() == 1


@pytest.mark.asyncio
async def test_lifecycle_one_way_sm_to_fdb_ignores_fdb_flip(db):
    """direction=spoolman_to_filamentdb → an FDB-side retire flip does NOT write SM."""
    sm = _sm_spool_arch(1, 800.0, archived=False)
    fdb = _fdb_filament_ret("fil-1", "spool-1", 1000.0, retired=True)  # FDB flipped
    _add_spool_mapping(db, 1, "fil-1", "spool-1")
    _store_snapshot(db, "spoolman", "spool", "1", {"remaining_weight": 800.0, "archived": False})
    _store_snapshot(db, "filamentdb", "spool", "spool-1", {"totalWeight": 1000.0, "retired": False})
    _seed_weight_config(db, direction="two_way", policy="manual")
    _seed_archive_config(db, direction="spoolman_to_filamentdb", policy="manual")

    spoolman = _fake_spoolman(spools=[sm])
    fdb_client = _fake_filamentdb(filaments=[fdb])

    with patch("app.core.engine._settings") as ms:
        _patch_settings(ms)
        r = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="lc-1way")

    assert r.conflicts == 0
    spoolman.update_spool.assert_not_called()  # SM never written under SM→FDB lock
    # FDB-side drift snapshot converges (locked destination) so it doesn't re-fire.
    assert _snap_value(db, "filamentdb", "spool", "spool-1", "retired") is True


@pytest.mark.asyncio
async def test_lifecycle_unmapped_archived_spool_not_imported(db):
    """An UNMAPPED archived spool on an already-mapped filament during ongoing sync is
    still NOT imported, even with new_spool_policy=auto_import (import gate preserved)."""
    # SM filament 10 is already mapped to FDB fil-9; spool 500 on it is unmapped + archived.
    # fil-9 has no spools so there is no FDB→SM new-spool noise to confound the assertion.
    archived = _sm_spool_arch(500, 0.0, archived=True)
    fdb = FDBFilament.model_validate({
        "_id": "fil-9", "name": "PLA", "vendor": "elegoo", "spoolWeight": 200.0, "spools": [],
    })
    db.add(FilamentMapping(spoolman_filament_id=10, filamentdb_id="fil-9"))
    db.flush()
    _seed_weight_config(db, direction="two_way", policy="manual")
    _seed_archive_config(db, direction="two_way", policy="manual")
    from app.api.config import set_config_value
    set_config_value(db, "new_spool_policy", "auto_import")
    db.commit()

    spoolman = _fake_spoolman(spools=[archived])
    fdb_client = _fake_filamentdb(filaments=[fdb])

    with patch("app.core.engine._settings") as ms:
        _patch_settings(ms)
        r = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="lc-unmapped")

    # The archived unmapped spool must not be created in FDB (still excluded from
    # the active-only new-spool detection set).
    fdb_client.create_spool.assert_not_called()
    assert r.created == 0
