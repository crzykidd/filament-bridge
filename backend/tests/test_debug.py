"""Tests for the /api/debug/* endpoints.

Verifies:
  - Both endpoints return 403 when debug_mode is false (default).
  - clear-spoolman-fdb-refs: with debug_mode true, blanks the three xref extras on
    spools that have any set; leaves spools without xrefs untouched; returns correct counts.
  - reset-bridge-state: with debug_mode true, empties all five state tables and resets
    wizard_completed to false; returns per-table deleted counts.
  - Config round-trip: debug_mode can be set/cleared via PUT /api/config.
"""

import json
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import config, debug
from app.api.config import get_config_value, set_config_value
from app.db import Base, get_db
from app.models.config import seed_defaults
from app.models.conflict import Conflict
from app.models.mapping import FilamentMapping, SpoolMapping
from app.models.snapshot import Snapshot
from app.models.sync_log import SyncLog
from app.schemas.spoolman import SpoolmanFilament, SpoolmanSpool, SpoolmanVendor, encode_extra_value


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def _fresh_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    seed_defaults(session)
    return session


def _fake_spoolman(spools=None) -> AsyncMock:
    client = AsyncMock()
    client.get_spools = AsyncMock(return_value=spools or [])
    client.update_spool = AsyncMock(return_value=MagicMock())
    return client


def _client(db, spoolman=None) -> TestClient:
    app = FastAPI()
    app.include_router(debug.router, prefix="/api")
    app.include_router(config.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.state.spoolman = spoolman or _fake_spoolman()
    return TestClient(app)


def _sm_spool(spool_id: int, extra: dict | None = None) -> SpoolmanSpool:
    return SpoolmanSpool(
        id=spool_id,
        filament=SpoolmanFilament(id=10, name="PLA", vendor=SpoolmanVendor(id=1, name="ELEGOO")),
        extra=extra or {},
    )


# ---------------------------------------------------------------------------
# 403 when debug_mode is false (default)
# ---------------------------------------------------------------------------


def test_clear_refs_403_when_debug_mode_off(db):
    client = _client(db)
    resp = client.post("/api/debug/clear-spoolman-fdb-refs")
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "debug_mode_required"


def test_reset_state_403_when_debug_mode_off(db):
    client = _client(db)
    resp = client.post("/api/debug/reset-bridge-state")
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "debug_mode_required"


# ---------------------------------------------------------------------------
# Config round-trip: debug_mode via PUT /api/config
# ---------------------------------------------------------------------------


def test_config_debug_mode_round_trips(db):
    client = _client(db)

    # Default is false
    body = client.get("/api/config").json()
    assert body["debug_mode"] is False

    # Enable
    resp = client.put("/api/config", json={"debug_mode": True})
    assert resp.status_code == 200
    assert resp.json()["debug_mode"] is True

    # Disable
    resp2 = client.put("/api/config", json={"debug_mode": False})
    assert resp2.status_code == 200
    assert resp2.json()["debug_mode"] is False


# ---------------------------------------------------------------------------
# clear-spoolman-fdb-refs with debug_mode=true
# ---------------------------------------------------------------------------


def test_clear_refs_blanks_xrefs_on_matching_spools(db):
    """Spools with at least one xref extra set get all three blanked; others untouched."""
    set_config_value(db, "debug_mode", True)
    db.commit()

    blank = encode_extra_value("")
    # Spool 1: has all three xrefs set
    spool1 = _sm_spool(1, extra={
        "filamentdb_id": encode_extra_value("fil-1"),
        "filamentdb_spool_id": encode_extra_value("sp-1"),
        "filamentdb_parent_id": encode_extra_value(""),
    })
    # Spool 2: has one xref set
    spool2 = _sm_spool(2, extra={
        "filamentdb_id": encode_extra_value("fil-2"),
    })
    # Spool 3: no xrefs
    spool3 = _sm_spool(3, extra={})

    spoolman = _fake_spoolman(spools=[spool1, spool2, spool3])
    client = _client(db, spoolman)

    resp = client.post("/api/debug/clear-spoolman-fdb-refs")
    assert resp.status_code == 200
    body = resp.json()
    # Spool 1 has filamentdb_id and filamentdb_spool_id set (filamentdb_parent_id is already blank)
    # Spool 2 has filamentdb_id set
    # So 2 spools get updated
    assert body["cleared"] == 2
    assert body["failed"] == 0

    # Assert update_spool was called twice (once for spool 1, once for spool 2)
    assert spoolman.update_spool.await_count == 2

    # Verify the call for spool 1 blanked the two non-blank keys
    calls_by_id = {call.args[0]: call.args[1] for call in spoolman.update_spool.await_args_list}
    assert 1 in calls_by_id
    assert 2 in calls_by_id
    # Spool 1: filamentdb_id and filamentdb_spool_id should be blanked
    spool1_extra = calls_by_id[1]["extra"]
    assert spool1_extra["filamentdb_id"] == blank
    assert spool1_extra["filamentdb_spool_id"] == blank
    # Spool 2: filamentdb_id should be blanked
    spool2_extra = calls_by_id[2]["extra"]
    assert spool2_extra["filamentdb_id"] == blank


def test_clear_refs_counts_failures_without_aborting(db):
    """Per-spool errors are logged and counted; the batch continues."""
    set_config_value(db, "debug_mode", True)
    db.commit()

    spool1 = _sm_spool(1, extra={"filamentdb_id": encode_extra_value("x")})
    spool2 = _sm_spool(2, extra={"filamentdb_id": encode_extra_value("y")})
    spoolman = _fake_spoolman(spools=[spool1, spool2])

    call_count = 0

    async def _update_side_effect(spool_id, payload):
        nonlocal call_count
        call_count += 1
        if spool_id == 1:
            raise RuntimeError("Spoolman unavailable")
        return MagicMock()

    spoolman.update_spool = AsyncMock(side_effect=_update_side_effect)
    client = _client(db, spoolman)

    resp = client.post("/api/debug/clear-spoolman-fdb-refs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["cleared"] == 1
    assert body["failed"] == 1


def test_clear_refs_no_xrefs_returns_zero(db):
    """When no spools have xrefs, cleared and failed are both 0."""
    set_config_value(db, "debug_mode", True)
    db.commit()

    spoolman = _fake_spoolman(spools=[_sm_spool(1), _sm_spool(2)])
    client = _client(db, spoolman)

    resp = client.post("/api/debug/clear-spoolman-fdb-refs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["cleared"] == 0
    assert body["failed"] == 0
    spoolman.update_spool.assert_not_called()


# ---------------------------------------------------------------------------
# reset-bridge-state with debug_mode=true
# ---------------------------------------------------------------------------


def test_reset_bridge_state_empties_all_five_tables(db):
    """All five state tables are cleared; counts in response match seeded rows."""
    set_config_value(db, "debug_mode", True)
    set_config_value(db, "wizard_completed", True)
    db.commit()

    # Seed some rows in each table
    fm = FilamentMapping(spoolman_filament_id=10, filamentdb_id="fil-1")
    db.add(fm)
    db.flush()
    db.add(SpoolMapping(spoolman_spool_id=1, filamentdb_filament_id="fil-1",
                        filamentdb_spool_id="sp-1", filament_mapping_id=fm.id))
    db.add(SpoolMapping(spoolman_spool_id=2, filamentdb_filament_id="fil-1",
                        filamentdb_spool_id="sp-2"))
    db.add(Snapshot(source="spoolman", entity_type="spool", entity_id="1",
                    data=json.dumps({"remaining_weight": 500})))
    db.add(Snapshot(source="filamentdb", entity_type="spool", entity_id="sp-1",
                    data=json.dumps({"totalWeight": 700})))
    db.add(Conflict(entity_type="spool", spoolman_id=1, field_name="weight"))
    db.add(SyncLog(cycle_id="c1", direction="spoolman_to_filamentdb",
                   action="update", entity_type="spool"))
    db.commit()

    client = _client(db)
    resp = client.post("/api/debug/reset-bridge-state")
    assert resp.status_code == 200
    body = resp.json()

    # All five tables emptied
    assert body["filament_mappings"] == 1
    assert body["spool_mappings"] == 2
    assert body["snapshots"] == 2
    assert body["conflicts"] == 1
    assert body["sync_log"] == 1
    assert body["wizard_completed_reset"] is True

    # Verify DB is actually empty
    assert db.query(FilamentMapping).count() == 0
    assert db.query(SpoolMapping).count() == 0
    assert db.query(Snapshot).count() == 0
    assert db.query(Conflict).count() == 0
    assert db.query(SyncLog).count() == 0

    # wizard_completed should be reset to False
    assert get_config_value(db, "wizard_completed") is False


def test_reset_bridge_state_preserves_bridge_config(db):
    """BridgeConfig (including debug_mode and other settings) is not touched."""
    set_config_value(db, "debug_mode", True)
    set_config_value(db, "sync_weight_threshold_grams", 5.0)
    set_config_value(db, "wizard_completed", True)
    db.commit()

    client = _client(db)
    resp = client.post("/api/debug/reset-bridge-state")
    assert resp.status_code == 200

    # debug_mode and other settings preserved
    assert get_config_value(db, "debug_mode") is True
    assert float(get_config_value(db, "sync_weight_threshold_grams")) == 5.0
    # wizard_completed is reset to False (by design)
    assert get_config_value(db, "wizard_completed") is False


def test_reset_bridge_state_works_on_empty_tables(db):
    """Reset on already-empty tables returns zeros without error."""
    set_config_value(db, "debug_mode", True)
    db.commit()

    client = _client(db)
    resp = client.post("/api/debug/reset-bridge-state")
    assert resp.status_code == 200
    body = resp.json()
    assert body["filament_mappings"] == 0
    assert body["spool_mappings"] == 0
    assert body["snapshots"] == 0
    assert body["conflicts"] == 0
    assert body["sync_log"] == 0
