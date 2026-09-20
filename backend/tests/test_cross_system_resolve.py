"""End-to-end proof tests for GitHub #21 — resolving a cross_system conflict
CONVERGES instead of re-queuing.

For each cross_system field family the test:
  1. Runs cycle 1 with both sides changed → a conflict is queued.
  2. Resolves it via the resolve endpoint (TestClient → apply_cross_system_conflict).
  3. Updates the mock upstream state to the post-write converged values.
  4. Runs a SECOND run_sync_cycle and asserts:
       (a) NO new open conflict is re-queued, and
       (b) both sides hold the converged value (snapshots agree).

The conflict-resolution endpoint and the engine share the same SQLite session, so
the resolve advances the very snapshots the second cycle reads.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import conflicts as conflicts_router
from app.api.config import set_config_value
from app.core.conflict_apply import apply_cross_system_conflict
from app.core.engine import run_sync_cycle
from app.db import Base, get_db
from app.models.config import seed_defaults
from app.models.conflict import Conflict
from app.models.mapping import FilamentMapping, SpoolMapping
from app.models.snapshot import Snapshot
from app.schemas.filamentdb import FDBFilament, FDBFilamentDetail
from app.schemas.spoolman import SpoolmanFilament, SpoolmanSpool, SpoolmanVendor, encode_extra_value

CYCLE1 = "xres-c1"
CYCLE2 = "xres-c2"


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def _make_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    seed_defaults(session)
    set_config_value(session, "variant_parent_mode", "promote_color")
    session.commit()
    return session


def _client(db, spoolman, filamentdb) -> TestClient:
    app = FastAPI()
    app.include_router(conflicts_router.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.state.spoolman = spoolman
    app.state.filamentdb = filamentdb
    return TestClient(app)


def _fake_spoolman(spools=None, filaments=None) -> AsyncMock:
    client = AsyncMock()
    # Spoolman never returns a spool without a live filament — union the filaments
    # embedded on the spools with any explicit ones so the engine's stale-mapping GC
    # doesn't treat a mapped filament as deleted.
    fils = {f.id: f for f in (filaments or [])}
    for s in spools or []:
        f = getattr(s, "filament", None)
        if f is not None and f.id not in fils:
            fils[f.id] = f
    live_filaments = list(fils.values())
    client.get_spools = AsyncMock(return_value=spools or [])
    client.get_filaments = AsyncMock(return_value=live_filaments)
    client.get_filament = AsyncMock(return_value=(live_filaments or [None])[0])
    client.get_field_definitions = AsyncMock(return_value=[])
    client.update_spool = AsyncMock(return_value=MagicMock())
    client.update_filament = AsyncMock(return_value=MagicMock())
    return client


def _fake_filamentdb(filaments=None, detail=None, version="1.33.0") -> AsyncMock:
    client = AsyncMock()
    client.get_filaments = AsyncMock(return_value=filaments or [])
    client.get_filament = AsyncMock(return_value=detail)
    client.get_version = AsyncMock(return_value=version)
    client.log_usage = AsyncMock(return_value={})
    client.update_spool = AsyncMock(return_value={})
    client.update_filament = AsyncMock(return_value={})
    return client


def _snap(db, source, etype, eid, data):
    db.add(Snapshot(source=source, entity_type=etype, entity_id=eid, data=json.dumps(data)))
    db.flush()


def _seed_weight_cfg(db, direction="two_way", policy="manual"):
    set_config_value(db, "weight_sync_direction", direction)
    set_config_value(db, "weight_conflict_policy", policy)
    db.commit()


def _seed_matprop_cfg(db, direction="two_way", policy="manual"):
    set_config_value(db, "material_properties_sync_direction", direction)
    set_config_value(db, "material_properties_conflict_policy", policy)
    db.commit()


def _engine_settings(mock_settings):
    """Minimal _settings stub for the engine cycle, deferring extra-field key
    names + parsed config to the real Settings object so the OPT/material_tags
    passes resolve their keys correctly."""
    from app.config import settings as real

    mock_settings.filamentdb_spoolman_id_field = "label"
    mock_settings.spoolman_field_filamentdb_id = "filamentdb_id"
    mock_settings.spoolman_field_filamentdb_spool_id = "filamentdb_spool_id"
    mock_settings.spoolman_field_filamentdb_parent_id = "filamentdb_parent_id"
    mock_settings.parsed_field_mappings = {}
    mock_settings.parsed_field_mapping_excludes = set()
    mock_settings.spoolman_field_filamentdb_material_tags = real.spoolman_field_filamentdb_material_tags
    mock_settings.parsed_material_tag_ids = real.parsed_material_tag_ids
    for ef_attr in (
        "spoolman_field_openprinttag_nozzle_temp_min",
        "spoolman_field_openprinttag_nozzle_temp_max",
        "spoolman_field_openprinttag_drying_temp",
        "spoolman_field_openprinttag_drying_time",
        "spoolman_field_openprinttag_hardness_shore_a",
        "spoolman_field_openprinttag_hardness_shore_d",
        "spoolman_field_openprinttag_transmission_distance",
    ):
        setattr(mock_settings, ef_attr, getattr(real, ef_attr))


def _open_conflicts(db):
    return db.query(Conflict).filter(Conflict.resolved_at.is_(None)).all()


# ===========================================================================
# weight (spool)
# ===========================================================================


@pytest.mark.asyncio
async def test_weight_resolve_converges_no_requeue():
    db = _make_db()
    _seed_weight_cfg(db)
    db.add(SpoolMapping(spoolman_spool_id=1, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    # Both sides diverged from the baseline.
    _snap(db, "spoolman", "spool", "1", {"remaining_weight": 800.0})
    _snap(db, "filamentdb", "spool", "spool-1", {"totalWeight": 1000.0})
    db.commit()

    sm_spool = SpoolmanSpool(
        id=1, filament=SpoolmanFilament(id=10, name="PLA", vendor=SpoolmanVendor(id=1, name="ELEGOO")),
        remaining_weight=790.0, archived=False,
    )
    fdb_fil = FDBFilament.model_validate({
        "_id": "fil-1", "name": "PLA", "vendor": "elegoo", "spoolWeight": 200.0,
        "spools": [{"_id": "spool-1", "totalWeight": 1050.0, "retired": False}],
    })
    fdb_detail = FDBFilamentDetail.model_validate({
        "_id": "fil-1", "name": "PLA", "spoolWeight": 200.0, "_inherited": [],
        "spools": [{"_id": "spool-1", "totalWeight": 1050.0, "retired": False}],
    })
    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb = _fake_filamentdb(filaments=[fdb_fil], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, patch("app.core.engine.resolve_field_map", return_value=[]):
        _engine_settings(ms)
        r1 = await run_sync_cycle(db, spoolman, fdb, dry_run=False, cycle_id=CYCLE1)
    assert r1.conflicts == 1
    conflict = _open_conflicts(db)[0]
    assert conflict.field_name == "weight"

    # Resolve via the endpoint — adopt SM net (790) on both sides.
    client = _client(db, spoolman, fdb)
    resp = client.post(f"/api/conflicts/{conflict.id}/resolve", json={"resolution": "spoolman"})
    assert resp.status_code == 200
    # SM net 790 set directly; FDB gross 1050 → 990 is a DECREASE, so FDB is lowered
    # via a usage entry (it can't drop totalWeight with a direct PUT, #28).
    spoolman.update_spool.assert_awaited_with(1, {"remaining_weight": 790.0})
    fdb.log_usage.assert_awaited_once()
    assert fdb.log_usage.await_args.args[2] == 60.0

    # Second cycle with the converged live state — must NOT re-queue.
    sm_spool.remaining_weight = 790.0
    fdb_fil = FDBFilament.model_validate({
        "_id": "fil-1", "name": "PLA", "vendor": "elegoo", "spoolWeight": 200.0,
        "spools": [{"_id": "spool-1", "totalWeight": 990.0, "retired": False}],
    })
    spoolman.get_spools = AsyncMock(return_value=[sm_spool])
    fdb.get_filaments = AsyncMock(return_value=[fdb_fil])

    with patch("app.core.engine._settings") as ms, patch("app.core.engine.resolve_field_map", return_value=[]):
        _engine_settings(ms)
        r2 = await run_sync_cycle(db, spoolman, fdb, dry_run=False, cycle_id=CYCLE2)
    assert r2.conflicts == 0
    assert len(_open_conflicts(db)) == 0
    sm_snap = json.loads(db.query(Snapshot).filter_by(source="spoolman", entity_id="1").first().data)
    fdb_snap = json.loads(db.query(Snapshot).filter_by(source="filamentdb", entity_id="spool-1").first().data)
    assert sm_snap["remaining_weight"] == 790.0
    assert fdb_snap["totalWeight"] == 990.0


# ===========================================================================
# cost (filament)
# ===========================================================================


@pytest.mark.asyncio
async def test_cost_resolve_converges_no_requeue():
    db = _make_db()
    _seed_matprop_cfg(db)
    db.add(FilamentMapping(spoolman_filament_id=50, filamentdb_id="fil-cost"))
    _snap(db, "spoolman", "filament", "50", {"_cost": 20.0})
    _snap(db, "filamentdb", "filament", "fil-cost", {"_cost": 20.0})
    db.commit()

    sm_fil = SpoolmanFilament(id=50, name="Cost PLA", vendor=SpoolmanVendor(id=1, name="E"), price=24.99)
    fdb_list = FDBFilament.model_validate({"_id": "fil-cost", "name": "Cost PLA", "cost": 35.0, "spools": []})
    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb = _fake_filamentdb(filaments=[fdb_list])

    with patch("app.core.engine._settings") as ms, patch("app.core.engine.resolve_field_map", return_value=[]):
        _engine_settings(ms)
        r1 = await run_sync_cycle(db, spoolman, fdb, dry_run=False, cycle_id=CYCLE1)
    assert r1.conflicts == 1
    conflict = next(c for c in _open_conflicts(db) if c.field_name == "cost")

    client = _client(db, spoolman, fdb)
    resp = client.post(f"/api/conflicts/{conflict.id}/resolve", json={"resolution": "filamentdb"})
    assert resp.status_code == 200
    fdb.update_filament.assert_awaited_with("fil-cost", {"cost": 35.0})
    spoolman.update_filament.assert_awaited_with(50, {"price": 35.0})

    # Converged state: both 35.0.
    sm_fil.price = 35.0
    fdb_list = FDBFilament.model_validate({"_id": "fil-cost", "name": "Cost PLA", "cost": 35.0, "spools": []})
    spoolman.get_filaments = AsyncMock(return_value=[sm_fil])
    fdb.get_filaments = AsyncMock(return_value=[fdb_list])

    with patch("app.core.engine._settings") as ms, patch("app.core.engine.resolve_field_map", return_value=[]):
        _engine_settings(ms)
        r2 = await run_sync_cycle(db, spoolman, fdb, dry_run=False, cycle_id=CYCLE2)
    assert r2.conflicts == 0
    assert not _open_conflicts(db)
    assert json.loads(db.query(Snapshot).filter_by(source="spoolman", entity_id="50").first().data)["_cost"] == 35.0
    assert json.loads(db.query(Snapshot).filter_by(source="filamentdb", entity_id="fil-cost").first().data)["_cost"] == 35.0


# ===========================================================================
# temperature (filament) — nozzle_temp
# ===========================================================================


@pytest.mark.asyncio
async def test_nozzle_temp_resolve_converges_no_requeue():
    db = _make_db()
    _seed_matprop_cfg(db)
    db.add(FilamentMapping(spoolman_filament_id=60, filamentdb_id="fil-temp"))
    _snap(db, "spoolman", "filament", "60", {"_mp_settings_extruder_temp": 210})
    _snap(db, "filamentdb", "filament", "fil-temp", {"_mp_settings_extruder_temp": 210})
    db.commit()

    sm_fil = SpoolmanFilament(id=60, name="Temp PLA", vendor=SpoolmanVendor(id=1, name="E"), settings_extruder_temp=215)
    fdb_list = FDBFilament.model_validate({
        "_id": "fil-temp", "name": "Temp PLA", "temperatures": {"nozzle": 220, "bed": 60}, "spools": [],
    })
    fdb_detail = FDBFilamentDetail.model_validate({
        "_id": "fil-temp", "name": "Temp PLA", "_inherited": [],
        "temperatures": {"nozzle": 220, "bed": 60}, "spools": [],
    })
    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb = _fake_filamentdb(filaments=[fdb_list], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, patch("app.core.engine.resolve_field_map", return_value=[]):
        _engine_settings(ms)
        r1 = await run_sync_cycle(db, spoolman, fdb, dry_run=False, cycle_id=CYCLE1)
    assert r1.conflicts == 1
    conflict = next(c for c in _open_conflicts(db) if c.field_name == "nozzle_temp")

    client = _client(db, spoolman, fdb)
    resp = client.post(f"/api/conflicts/{conflict.id}/resolve", json={"resolution": "spoolman"})
    assert resp.status_code == 200
    # Bed temp (sibling) survives the RMW; nozzle adopts SM value 215.
    fdb_call = fdb.update_filament.await_args
    assert fdb_call.args[0] == "fil-temp"
    temps = fdb_call.args[1]["temperatures"]
    assert temps["nozzle"] == 215
    assert temps["bed"] == 60.0  # sibling preserved by the read-modify-write
    spoolman.update_filament.assert_awaited_with(60, {"settings_extruder_temp": 215})

    fdb_list = FDBFilament.model_validate({
        "_id": "fil-temp", "name": "Temp PLA", "temperatures": {"nozzle": 215, "bed": 60}, "spools": [],
    })
    fdb_detail = FDBFilamentDetail.model_validate({
        "_id": "fil-temp", "name": "Temp PLA", "_inherited": [],
        "temperatures": {"nozzle": 215, "bed": 60}, "spools": [],
    })
    spoolman.get_filaments = AsyncMock(return_value=[sm_fil])
    fdb.get_filaments = AsyncMock(return_value=[fdb_list])
    fdb.get_filament = AsyncMock(return_value=fdb_detail)

    with patch("app.core.engine._settings") as ms, patch("app.core.engine.resolve_field_map", return_value=[]):
        _engine_settings(ms)
        r2 = await run_sync_cycle(db, spoolman, fdb, dry_run=False, cycle_id=CYCLE2)
    assert r2.conflicts == 0
    assert not _open_conflicts(db)


# ===========================================================================
# native scalar (filament) — density
# ===========================================================================


@pytest.mark.asyncio
async def test_density_resolve_converges_no_requeue():
    db = _make_db()
    _seed_matprop_cfg(db)
    db.add(FilamentMapping(spoolman_filament_id=70, filamentdb_id="fil-den"))
    _snap(db, "spoolman", "filament", "70", {"_mp_density": 1.24})
    _snap(db, "filamentdb", "filament", "fil-den", {"_mp_density": 1.24})
    db.commit()

    sm_fil = SpoolmanFilament(id=70, name="Den PLA", vendor=SpoolmanVendor(id=1, name="E"), density=1.25)
    fdb_list = FDBFilament.model_validate({"_id": "fil-den", "name": "Den PLA", "density": 1.30, "spools": []})
    fdb_detail = FDBFilamentDetail.model_validate({
        "_id": "fil-den", "name": "Den PLA", "density": 1.30, "_inherited": [], "spools": [],
    })
    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb = _fake_filamentdb(filaments=[fdb_list], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, patch("app.core.engine.resolve_field_map", return_value=[]):
        _engine_settings(ms)
        r1 = await run_sync_cycle(db, spoolman, fdb, dry_run=False, cycle_id=CYCLE1)
    assert r1.conflicts == 1
    conflict = next(c for c in _open_conflicts(db) if c.field_name == "density")

    client = _client(db, spoolman, fdb)
    resp = client.post(f"/api/conflicts/{conflict.id}/resolve", json={"resolution": "spoolman"})
    assert resp.status_code == 200
    fdb.update_filament.assert_awaited_with("fil-den", {"density": 1.25})
    spoolman.update_filament.assert_awaited_with(70, {"density": 1.25})

    sm_fil.density = 1.25
    fdb_list = FDBFilament.model_validate({"_id": "fil-den", "name": "Den PLA", "density": 1.25, "spools": []})
    fdb_detail = FDBFilamentDetail.model_validate({
        "_id": "fil-den", "name": "Den PLA", "density": 1.25, "_inherited": [], "spools": [],
    })
    spoolman.get_filaments = AsyncMock(return_value=[sm_fil])
    fdb.get_filaments = AsyncMock(return_value=[fdb_list])
    fdb.get_filament = AsyncMock(return_value=fdb_detail)

    with patch("app.core.engine._settings") as ms, patch("app.core.engine.resolve_field_map", return_value=[]):
        _engine_settings(ms)
        r2 = await run_sync_cycle(db, spoolman, fdb, dry_run=False, cycle_id=CYCLE2)
    assert r2.conflicts == 0
    assert not _open_conflicts(db)


# ===========================================================================
# material remap (SM material ↔ FDB type) — manual resolution
# ===========================================================================


@pytest.mark.asyncio
async def test_material_manual_resolve_converges():
    db = _make_db()
    _seed_matprop_cfg(db)
    db.add(FilamentMapping(spoolman_filament_id=75, filamentdb_id="fil-mat"))
    _snap(db, "spoolman", "filament", "75", {"_mp_material": "PLA"})
    _snap(db, "filamentdb", "filament", "fil-mat", {"_mp_material": "PLA"})
    db.commit()

    sm_fil = SpoolmanFilament(id=75, name="Mat", vendor=SpoolmanVendor(id=1, name="E"), material="PLA+")
    fdb_list = FDBFilament.model_validate({"_id": "fil-mat", "name": "Mat", "type": "PETG", "spools": []})
    fdb_detail = FDBFilamentDetail.model_validate({
        "_id": "fil-mat", "name": "Mat", "type": "PETG", "_inherited": [], "spools": [],
    })
    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb = _fake_filamentdb(filaments=[fdb_list], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, patch("app.core.engine.resolve_field_map", return_value=[]):
        _engine_settings(ms)
        await run_sync_cycle(db, spoolman, fdb, dry_run=False, cycle_id=CYCLE1)
    conflict = next(c for c in _open_conflicts(db) if c.field_name == "material")

    client = _client(db, spoolman, fdb)
    resp = client.post(f"/api/conflicts/{conflict.id}/resolve", json={"resolution": "manual", "value": "ABS"})
    assert resp.status_code == 200
    # SM material ↔ FDB type remap.
    fdb.update_filament.assert_awaited_with("fil-mat", {"type": "ABS"})
    spoolman.update_filament.assert_awaited_with(75, {"material": "ABS"})
    db.expire_all()
    assert db.query(Conflict).filter_by(id=conflict.id).first().resolved_at is not None


# ===========================================================================
# OpenPrintTag material-setting extra — drying_time
# ===========================================================================


@pytest.mark.asyncio
async def test_opentag_field_resolve_converges_no_requeue():
    db = _make_db()
    _seed_matprop_cfg(db)
    from app.config import settings as real
    sm_key = real.spoolman_field_openprinttag_drying_time

    db.add(FilamentMapping(spoolman_filament_id=80, filamentdb_id="fil-opt"))
    _snap(db, "spoolman", "filament", "80", {f"_mp_{sm_key}": 6})
    _snap(db, "filamentdb", "filament", "fil-opt", {f"_mp_{sm_key}": 6})
    db.commit()

    from app.schemas.spoolman import encode_extra_value
    sm_fil = SpoolmanFilament(
        id=80, name="OPT", vendor=SpoolmanVendor(id=1, name="E"),
        extra={sm_key: encode_extra_value(8)},
    )
    fdb_list = FDBFilament.model_validate({"_id": "fil-opt", "name": "OPT", "dryingTime": 10, "spools": []})
    fdb_detail = FDBFilamentDetail.model_validate({
        "_id": "fil-opt", "name": "OPT", "dryingTime": 10, "_inherited": [], "spools": [],
    })
    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb = _fake_filamentdb(filaments=[fdb_list], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, patch("app.core.engine.resolve_field_map", return_value=[]):
        _engine_settings(ms)
        r1 = await run_sync_cycle(db, spoolman, fdb, dry_run=False, cycle_id=CYCLE1)
    assert r1.conflicts == 1
    conflict = _open_conflicts(db)[0]

    client = _client(db, spoolman, fdb)
    resp = client.post(f"/api/conflicts/{conflict.id}/resolve", json={"resolution": "filamentdb"})
    assert resp.status_code == 200
    fdb.update_filament.assert_awaited_with("fil-opt", {"dryingTime": 10})
    spoolman.update_filament.assert_awaited_with(80, {"extra": {sm_key: encode_extra_value(10)}})

    sm_fil.extra = {sm_key: encode_extra_value(10)}
    fdb_list = FDBFilament.model_validate({"_id": "fil-opt", "name": "OPT", "dryingTime": 10, "spools": []})
    fdb_detail = FDBFilamentDetail.model_validate({
        "_id": "fil-opt", "name": "OPT", "dryingTime": 10, "_inherited": [], "spools": [],
    })
    spoolman.get_filaments = AsyncMock(return_value=[sm_fil])
    fdb.get_filaments = AsyncMock(return_value=[fdb_list])
    fdb.get_filament = AsyncMock(return_value=fdb_detail)

    with patch("app.core.engine._settings") as ms, patch("app.core.engine.resolve_field_map", return_value=[]):
        _engine_settings(ms)
        r2 = await run_sync_cycle(db, spoolman, fdb, dry_run=False, cycle_id=CYCLE2)
    assert r2.conflicts == 0
    assert not _open_conflicts(db)


# ===========================================================================
# multicolor (filament) — signature-based, spoolman/filamentdb only
# ===========================================================================


@pytest.mark.asyncio
async def test_multicolor_resolve_converges_no_requeue():
    db = _make_db()
    _seed_matprop_cfg(db)
    db.add(FilamentMapping(spoolman_filament_id=90, filamentdb_id="fil-mc"))
    # Baselines so both sides register as CHANGED this cycle.
    _snap(db, "spoolman", "filament", "90", {"_mc_sig": "solid|aaaaaa|"})
    _snap(db, "filamentdb", "filament", "fil-mc", {"_mc_sig": "solid|aaaaaa|"})
    db.commit()

    # SM now coaxial; FDB now gradient → both changed → conflict.
    sm_fil = SpoolmanFilament(
        id=90, name="MC", vendor=SpoolmanVendor(id=1, name="E"),
        multi_color_hexes="ff0000,00ff00", multi_color_direction="coaxial",
    )
    fdb_list = FDBFilament.model_validate({
        "_id": "fil-mc", "name": "MC", "color": "#0000ff",
        "secondaryColors": ["#123456"], "optTags": [28], "spools": [],
    })
    fdb_detail = FDBFilamentDetail.model_validate({
        "_id": "fil-mc", "name": "MC", "color": "#0000ff",
        "secondaryColors": ["#123456"], "optTags": [28], "_inherited": [], "spools": [],
    })
    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb = _fake_filamentdb(filaments=[fdb_list], detail=fdb_detail)
    spoolman.get_filament = AsyncMock(return_value=sm_fil)

    with patch("app.core.engine._settings") as ms, patch("app.core.engine.resolve_field_map", return_value=[]):
        _engine_settings(ms)
        r1 = await run_sync_cycle(db, spoolman, fdb, dry_run=False, cycle_id=CYCLE1)
    assert r1.conflicts == 1
    conflict = next(c for c in _open_conflicts(db) if c.field_name == "multicolor")

    client = _client(db, spoolman, fdb)
    # Adopt SM color state on both sides.
    resp = client.post(f"/api/conflicts/{conflict.id}/resolve", json={"resolution": "spoolman"})
    assert resp.status_code == 200
    fdb.update_filament.assert_awaited()  # FDB got the SM-derived structured color

    # Converged: FDB now reflects the coaxial SM state.
    fdb_list = FDBFilament.model_validate({
        "_id": "fil-mc", "name": "MC", "color": None,
        "secondaryColors": ["#ff0000", "#00ff00"], "optTags": [29], "spools": [],
    })
    fdb_detail = FDBFilamentDetail.model_validate({
        "_id": "fil-mc", "name": "MC", "color": None,
        "secondaryColors": ["#ff0000", "#00ff00"], "optTags": [29], "_inherited": [], "spools": [],
    })
    spoolman.get_filaments = AsyncMock(return_value=[sm_fil])
    fdb.get_filaments = AsyncMock(return_value=[fdb_list])
    fdb.get_filament = AsyncMock(return_value=fdb_detail)

    with patch("app.core.engine._settings") as ms, patch("app.core.engine.resolve_field_map", return_value=[]):
        _engine_settings(ms)
        r2 = await run_sync_cycle(db, spoolman, fdb, dry_run=False, cycle_id=CYCLE2)
    assert r2.conflicts == 0
    assert not _open_conflicts(db)


def test_multicolor_manual_resolution_returns_422():
    db = _make_db()
    c = Conflict(
        entity_type="filament", field_name="multicolor", conflict_type="cross_system",
        spoolman_id=90, filamentdb_filament_id="fil-mc",
        spoolman_value=json.dumps("coextruded|x|"), filamentdb_value=json.dumps("gradient|y|"),
    )
    db.add(c)
    db.commit()
    spoolman = _fake_spoolman()
    fdb = _fake_filamentdb()
    client = _client(db, spoolman, fdb)
    resp = client.post(f"/api/conflicts/{c.id}/resolve", json={"resolution": "manual", "value": "x"})
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "unsupported_conflict_field"


# ===========================================================================
# material_tags (filament) — signature-based
# ===========================================================================


@pytest.mark.asyncio
async def test_material_tags_resolve_converges_no_requeue():
    db = _make_db()
    _seed_matprop_cfg(db)
    from app.config import settings as real
    mt_field = real.spoolman_field_filamentdb_material_tags
    from app.core.material_tags import MANAGED_FINISH_IDS
    a_tag, b_tag = sorted(MANAGED_FINISH_IDS)[:2]

    db.add(FilamentMapping(spoolman_filament_id=95, filamentdb_id="fil-ft"))
    _snap(db, "spoolman", "filament", "95", {"_finish_sig": ""})
    _snap(db, "filamentdb", "filament", "fil-ft", {"_finish_sig": ""})
    db.commit()

    from app.schemas.spoolman import encode_extra_value
    # SM gained finish tag a; FDB gained finish tag b → both changed.
    sm_fil = SpoolmanFilament(
        id=95, name="FT", vendor=SpoolmanVendor(id=1, name="E"),
        extra={mt_field: encode_extra_value(str(a_tag))},
    )
    fdb_list = FDBFilament.model_validate({"_id": "fil-ft", "name": "FT", "optTags": [b_tag], "spools": []})
    fdb_detail = FDBFilamentDetail.model_validate({
        "_id": "fil-ft", "name": "FT", "optTags": [b_tag], "_inherited": [], "spools": [],
    })
    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb = _fake_filamentdb(filaments=[fdb_list], detail=fdb_detail)
    spoolman.get_filament = AsyncMock(return_value=sm_fil)

    with patch("app.core.engine._settings") as ms, patch("app.core.engine.resolve_field_map", return_value=[]):
        _engine_settings(ms)
        r1 = await run_sync_cycle(db, spoolman, fdb, dry_run=False, cycle_id=CYCLE1)
    assert r1.conflicts == 1
    conflict = next(c for c in _open_conflicts(db) if c.field_name == "material_tags")

    client = _client(db, spoolman, fdb)
    resp = client.post(f"/api/conflicts/{conflict.id}/resolve", json={"resolution": "spoolman"})
    assert resp.status_code == 200
    # Both sides now carry finish tag a.
    fdb.update_filament.assert_awaited_with("fil-ft", {"optTags": [a_tag]})

    fdb_list = FDBFilament.model_validate({"_id": "fil-ft", "name": "FT", "optTags": [a_tag], "spools": []})
    fdb_detail = FDBFilamentDetail.model_validate({
        "_id": "fil-ft", "name": "FT", "optTags": [a_tag], "_inherited": [], "spools": [],
    })
    spoolman.get_filaments = AsyncMock(return_value=[sm_fil])
    fdb.get_filaments = AsyncMock(return_value=[fdb_list])
    fdb.get_filament = AsyncMock(return_value=fdb_detail)

    with patch("app.core.engine._settings") as ms, patch("app.core.engine.resolve_field_map", return_value=[]):
        _engine_settings(ms)
        r2 = await run_sync_cycle(db, spoolman, fdb, dry_run=False, cycle_id=CYCLE2)
    assert r2.conflicts == 0
    assert not _open_conflicts(db)


# ===========================================================================
# dynamic FIELD_MAPPINGS extra field — generic SM spool extra ↔ FDB field
# ===========================================================================


@pytest.mark.asyncio
async def test_field_mapping_resolve_converges_no_requeue():
    db = _make_db()
    _seed_matprop_cfg(db)
    # Map FDB tdsUrl ↔ SM spool extra "tdsUrl".
    field_maps = [__import__("app.core.fields", fromlist=["FieldMapping"]).FieldMapping(
        fdb_path="tdsUrl", sm_key="tdsUrl", direction="fdb_to_sm")]

    db.add(SpoolMapping(spoolman_spool_id=100, filamentdb_filament_id="fil-fm", filamentdb_spool_id="spool-fm"))
    db.add(FilamentMapping(spoolman_filament_id=10, filamentdb_id="fil-fm"))
    from app.schemas.spoolman import encode_extra_value
    _snap(db, "spoolman", "spool", "100", {
        "remaining_weight": 500.0, "archived": False,
        "_extra_decoded": {"tdsUrl": "http://old"},
    })
    _snap(db, "filamentdb", "spool", "spool-fm", {
        "totalWeight": 700.0, "retired": False, "_field_values": {"tdsUrl": "http://old"},
    })
    db.commit()

    sm_spool = SpoolmanSpool(
        id=100,
        filament=SpoolmanFilament(id=10, name="PLA", vendor=SpoolmanVendor(id=1, name="E")),
        remaining_weight=500.0, archived=False,
        extra={"tdsUrl": encode_extra_value("http://sm-new")},
    )
    fdb_fil = FDBFilament.model_validate({
        "_id": "fil-fm", "name": "PLA", "vendor": "e", "spoolWeight": 200.0,
        "spools": [{"_id": "spool-fm", "totalWeight": 700.0, "retired": False}],
    })
    fdb_detail = FDBFilamentDetail.model_validate({
        "_id": "fil-fm", "name": "PLA", "spoolWeight": 200.0, "_inherited": [],
        "tdsUrl": "http://fdb-new",
        "spools": [{"_id": "spool-fm", "totalWeight": 700.0, "retired": False}],
    })
    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb = _fake_filamentdb(filaments=[fdb_fil], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, patch("app.core.engine.resolve_field_map", return_value=field_maps):
        _engine_settings(ms)
        r1 = await run_sync_cycle(db, spoolman, fdb, dry_run=False, cycle_id=CYCLE1)
    assert r1.conflicts == 1
    conflict = next(c for c in _open_conflicts(db) if c.field_name == "tdsUrl")

    # Resolve filamentdb-wins via the apply dispatcher (mirror the explicit mapping).
    with patch("app.config.settings") as cfg:
        cfg.parsed_field_mappings = {"tdsUrl": "tdsUrl"}
        cfg.parsed_field_mapping_excludes = set()
        client = _client(db, spoolman, fdb)
        resp = client.post(f"/api/conflicts/{conflict.id}/resolve", json={"resolution": "filamentdb"})
    assert resp.status_code == 200
    fdb.update_filament.assert_awaited_with("fil-fm", {"tdsUrl": "http://fdb-new"})
    spoolman.update_spool.assert_awaited_with(100, {"extra": {"tdsUrl": encode_extra_value("http://fdb-new")}})

    # Converged: both carry the FDB value.
    sm_spool.extra = {"tdsUrl": encode_extra_value("http://fdb-new")}
    fdb_detail = FDBFilamentDetail.model_validate({
        "_id": "fil-fm", "name": "PLA", "spoolWeight": 200.0, "_inherited": [],
        "tdsUrl": "http://fdb-new",
        "spools": [{"_id": "spool-fm", "totalWeight": 700.0, "retired": False}],
    })
    spoolman.get_spools = AsyncMock(return_value=[sm_spool])
    fdb.get_filament = AsyncMock(return_value=fdb_detail)

    with patch("app.core.engine._settings") as ms, patch("app.core.engine.resolve_field_map", return_value=field_maps):
        _engine_settings(ms)
        r2 = await run_sync_cycle(db, spoolman, fdb, dry_run=False, cycle_id=CYCLE2)
    assert r2.conflicts == 0
    assert not _open_conflicts(db)


# ===========================================================================
# OpenPrintTag identity (filament) — GitHub #94, apply_cross_system_conflict
# had no branch for this field until now.  Exercised directly against
# ``apply_cross_system_conflict`` (rather than a full engine cycle) since the
# queueing side of this conflict is already covered end-to-end by
# test_engine_opentag_identity.py.
# ===========================================================================

IDENTITY_SM_FIL_ID = 70
IDENTITY_FDB_FIL_ID = "fil-identity"
SLUG_FIELD = "openprinttag_slug"
UUID_FIELD = "openprinttag_uuid"


def _identity_conflict(sm_uuid: str | None, fdb_uuid: str | None) -> Conflict:
    return Conflict(
        entity_type="filament",
        spoolman_id=IDENTITY_SM_FIL_ID,
        filamentdb_filament_id=IDENTITY_FDB_FIL_ID,
        field_name="OpenPrintTag identity",
        spoolman_value=json.dumps(sm_uuid) if sm_uuid is not None else None,
        filamentdb_value=json.dumps(fdb_uuid) if fdb_uuid is not None else None,
        conflict_type="cross_system",
    )


def _identity_sm_filament(uuid: str | None, slug: str | None) -> SpoolmanFilament:
    return SpoolmanFilament(
        id=IDENTITY_SM_FIL_ID, name="Identity PLA", vendor=SpoolmanVendor(id=1, name="E"),
        extra={
            UUID_FIELD: encode_extra_value(uuid or ""),
            SLUG_FIELD: encode_extra_value(slug or ""),
        },
    )


def _identity_fdb_detail(uuid: str | None, slug: str | None) -> FDBFilamentDetail:
    return FDBFilamentDetail.model_validate({
        "_id": IDENTITY_FDB_FIL_ID, "name": "Identity PLA",
        "settings": {"openprinttag_uuid": uuid, "openprinttag_slug": slug} if uuid else None,
        "spools": [],
    })


def _identity_baseline(db, source: str, entity_id: str) -> dict:
    row = db.query(Snapshot).filter_by(source=source, entity_type="filament", entity_id=entity_id).first()
    return json.loads(row.data) if row else {}


@pytest.mark.asyncio
async def test_identity_apply_resolve_to_spoolman():
    """resolve=spoolman: Spoolman's uuid+slug win, written to BOTH sides,
    both baselines refreshed, conflict resolved."""
    db = _make_db()
    conflict = _identity_conflict("uuid-SM", "uuid-FDB")
    db.add(conflict)
    db.commit()

    spoolman = _fake_spoolman(filaments=[_identity_sm_filament("uuid-SM", "slug-sm")])
    fdb = _fake_filamentdb(detail=_identity_fdb_detail("uuid-FDB", "slug-fdb"))

    value = await apply_cross_system_conflict(conflict, "spoolman", None, db, spoolman, fdb)

    assert value == "uuid-SM"
    spoolman.update_filament.assert_awaited_with(
        IDENTITY_SM_FIL_ID,
        {"extra": {UUID_FIELD: encode_extra_value("uuid-SM"), SLUG_FIELD: encode_extra_value("slug-sm")}},
    )
    fdb.merge_filament_settings.assert_awaited_with(
        IDENTITY_FDB_FIL_ID, {"openprinttag_uuid": "uuid-SM", "openprinttag_slug": "slug-sm"},
    )
    fdb.remove_filament_settings_keys.assert_not_called()

    sm_base = _identity_baseline(db, "spoolman", str(IDENTITY_SM_FIL_ID))
    fdb_base = _identity_baseline(db, "filamentdb", IDENTITY_FDB_FIL_ID)
    assert sm_base["_opt_uuid"] == "uuid-SM" and sm_base["_opt_slug"] == "slug-sm"
    assert fdb_base["_opt_uuid"] == "uuid-SM" and fdb_base["_opt_slug"] == "slug-sm"

    assert conflict.resolved_at is not None
    assert conflict.resolution == "spoolman"
    assert json.loads(conflict.resolved_value) == "uuid-SM"


@pytest.mark.asyncio
async def test_identity_apply_resolve_to_filamentdb():
    """resolve=filamentdb: Filament DB's uuid+slug win, written to BOTH
    sides via the scoped ``merge_filament_settings`` exception, both
    baselines refreshed, conflict resolved."""
    db = _make_db()
    conflict = _identity_conflict("uuid-SM", "uuid-FDB")
    db.add(conflict)
    db.commit()

    spoolman = _fake_spoolman(filaments=[_identity_sm_filament("uuid-SM", "slug-sm")])
    fdb = _fake_filamentdb(detail=_identity_fdb_detail("uuid-FDB", "slug-fdb"))

    value = await apply_cross_system_conflict(conflict, "filamentdb", None, db, spoolman, fdb)

    assert value == "uuid-FDB"
    spoolman.update_filament.assert_awaited_with(
        IDENTITY_SM_FIL_ID,
        {"extra": {UUID_FIELD: encode_extra_value("uuid-FDB"), SLUG_FIELD: encode_extra_value("slug-fdb")}},
    )
    fdb.merge_filament_settings.assert_awaited_with(
        IDENTITY_FDB_FIL_ID, {"openprinttag_uuid": "uuid-FDB", "openprinttag_slug": "slug-fdb"},
    )
    fdb.remove_filament_settings_keys.assert_not_called()

    sm_base = _identity_baseline(db, "spoolman", str(IDENTITY_SM_FIL_ID))
    fdb_base = _identity_baseline(db, "filamentdb", IDENTITY_FDB_FIL_ID)
    assert sm_base["_opt_uuid"] == "uuid-FDB" and sm_base["_opt_slug"] == "slug-fdb"
    assert fdb_base["_opt_uuid"] == "uuid-FDB" and fdb_base["_opt_slug"] == "slug-fdb"

    assert conflict.resolved_at is not None
    assert conflict.resolution == "filamentdb"
    assert json.loads(conflict.resolved_value) == "uuid-FDB"


@pytest.mark.asyncio
async def test_identity_apply_resolve_to_empty_removes_both_sides():
    """resolve=manual with an empty value: the removal path — both SM
    extras blanked, FDB's two settings keys removed via
    ``remove_filament_settings_keys``, both baselines cleared, conflict
    resolved with no value chosen."""
    db = _make_db()
    conflict = _identity_conflict("uuid-SM", "uuid-FDB")
    db.add(conflict)
    db.commit()

    spoolman = _fake_spoolman(filaments=[_identity_sm_filament("uuid-SM", "slug-sm")])
    fdb = _fake_filamentdb(detail=_identity_fdb_detail("uuid-FDB", "slug-fdb"))

    value = await apply_cross_system_conflict(conflict, "manual", "", db, spoolman, fdb)

    assert value is None
    spoolman.update_filament.assert_awaited_with(
        IDENTITY_SM_FIL_ID,
        {"extra": {SLUG_FIELD: encode_extra_value(""), UUID_FIELD: encode_extra_value("")}},
    )
    fdb.remove_filament_settings_keys.assert_awaited_with(
        IDENTITY_FDB_FIL_ID, ["openprinttag_slug", "openprinttag_uuid"],
    )
    fdb.merge_filament_settings.assert_not_called()

    sm_base = _identity_baseline(db, "spoolman", str(IDENTITY_SM_FIL_ID))
    fdb_base = _identity_baseline(db, "filamentdb", IDENTITY_FDB_FIL_ID)
    assert sm_base["_opt_uuid"] == "" and sm_base["_opt_slug"] == ""
    assert fdb_base["_opt_uuid"] == "" and fdb_base["_opt_slug"] == ""

    assert conflict.resolved_at is not None
    assert conflict.resolution == "manual"
    assert json.loads(conflict.resolved_value) is None
