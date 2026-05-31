"""Route tests for the Phase 3 bridge API — driven with faked upstream clients.

No live network: the Spoolman/Filament DB clients are AsyncMocks set on
app.state. Each test builds a minimal FastAPI app with just the routers and
overrides get_db to use the in-memory session from the `db` fixture.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import (
    backup,
    config,
    conflicts,
    health,
    mappings,
    sync,
    sync_log,
    wizard,
)
from app.api.config import get_config_value, set_config_value
from app.db import Base, get_db
from app.models.config import BridgeConfig, seed_defaults
from app.models.conflict import Conflict
from app.models.mapping import FilamentMapping, SpoolMapping
from app.models.snapshot import Snapshot
from app.models.sync_log import SyncLog
from app.schemas.filamentdb import FDBFilament
from app.schemas.spoolman import SpoolmanFilament, SpoolmanSpool, SpoolmanVendor

_ROUTERS = (health, sync, conflicts, mappings, config, wizard, backup, sync_log)


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


def _fake_spoolman(spools=None, filaments=None, vendors=None) -> AsyncMock:
    client = AsyncMock()
    client.get_spools = AsyncMock(return_value=spools or [])
    client.get_filaments = AsyncMock(return_value=filaments or [])
    client.get_vendors = AsyncMock(return_value=vendors or [])
    client.get_field_definitions = AsyncMock(return_value=[])
    client.ensure_extra_fields = AsyncMock(return_value=None)
    client.update_spool = AsyncMock(return_value=MagicMock())
    client.create_spool = AsyncMock(return_value=MagicMock(id=999))
    client.create_filament = AsyncMock(return_value=MagicMock(id=888))
    client.create_vendor = AsyncMock(return_value=MagicMock(id=1))
    client.health = AsyncMock(
        return_value={"version": "1.0", "filament_count": 1, "spool_count": 1, "active_spool_count": 1}
    )
    return client


def _fake_filamentdb(filaments=None, detail=None) -> AsyncMock:
    client = AsyncMock()
    client.get_filaments = AsyncMock(return_value=filaments or [])
    client.get_filament = AsyncMock(return_value=detail)
    client.get_version = AsyncMock(return_value="1.33.0")
    client.log_usage = AsyncMock(return_value={})
    client.update_spool = AsyncMock(return_value={})
    client.update_filament = AsyncMock(return_value=MagicMock(id="fil-x"))
    client.create_spool = AsyncMock(return_value={"_id": "new-spool-id"})
    client.create_filament = AsyncMock(return_value=MagicMock(id="new-fil-id"))
    client.health = AsyncMock(return_value={"filament_count": 1, "spool_count": 1})
    return client


def _client(db, spoolman=None, filamentdb=None) -> TestClient:
    app = FastAPI()
    for mod in _ROUTERS:
        app.include_router(mod.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.state.spoolman = spoolman or _fake_spoolman()
    app.state.filamentdb = filamentdb or _fake_filamentdb()
    return TestClient(app)


def _sm_spool(spool_id: int, remaining: float, extra=None) -> SpoolmanSpool:
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


def _snap(db, source, entity_id, data):
    db.add(Snapshot(source=source, entity_type="spool", entity_id=entity_id, data=json.dumps(data)))
    db.flush()


# ---------------------------------------------------------------------------
# Sync — dry run (FR-14)
# ---------------------------------------------------------------------------


def test_dry_run_returns_preview_and_applies_nothing(db):
    # Pair 1: SM weight changed (795 < 800 snapshot) → one update entry
    db.add(SpoolMapping(spoolman_spool_id=1, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    _snap(db, "spoolman", "1", {"remaining_weight": 800.0})
    _snap(db, "filamentdb", "spool-1", {"totalWeight": 1000.0})

    # Pair 2: no snapshots (first baseline) → skip entry
    db.add(SpoolMapping(spoolman_spool_id=2, filamentdb_filament_id="fil-2", filamentdb_spool_id="spool-2"))

    # Pair 3: SM spool not in active set (archived) → skip entry
    db.add(SpoolMapping(spoolman_spool_id=99, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-99"))

    # Pair 4: both weights changed → conflict entry
    db.add(SpoolMapping(spoolman_spool_id=3, filamentdb_filament_id="fil-3", filamentdb_spool_id="spool-3"))
    _snap(db, "spoolman", "3", {"remaining_weight": 900.0})
    _snap(db, "filamentdb", "spool-3", {"totalWeight": 1200.0})
    db.commit()

    spoolman = _fake_spoolman(spools=[
        _sm_spool(1, 795.0),
        _sm_spool(2, 500.0),
        _sm_spool(3, 850.0),   # changed from 900 snapshot → weight conflict
        # sm_id=99 absent → archived skip
    ])
    filamentdb = _fake_filamentdb(filaments=[
        _fdb_filament("fil-1", "spool-1", 1000.0),
        _fdb_filament("fil-2", "spool-2", 600.0),
        _fdb_filament("fil-3", "spool-3", 1300.0),  # changed from 1200 snapshot → weight conflict
    ])
    client = _client(db, spoolman, filamentdb)

    resp = client.post("/api/sync/dry-run")
    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run"] is True
    assert body["updated"] == 1
    assert body["skipped"] == 2    # archived (pair 3) + first-baseline (pair 2)
    assert body["conflicts"] == 1  # weight conflict (pair 4)
    assert len(body["preview"]) >= 4

    # All entries have action in the 4 categories and a non-empty label.
    valid_actions = {"create", "update", "conflict", "skip"}
    for entry in body["preview"]:
        assert entry["action"] in valid_actions, f"unexpected action: {entry}"
        assert entry.get("label"), f"missing label in {entry}"

    # Skip entry for archived spool (sm_id=99 not in active set).
    archived_skips = [p for p in body["preview"] if p["action"] == "skip" and p.get("spoolman_id") == 99]
    assert len(archived_skips) == 1
    assert "archived" in archived_skips[0]["reason"].lower()

    # Skip entry for first-baseline pair (sm_id=2, no prior snapshot).
    baseline_skips = [p for p in body["preview"] if p["action"] == "skip" and p.get("spoolman_id") == 2]
    assert len(baseline_skips) == 1
    reason = baseline_skips[0]["reason"].lower()
    assert "baseline" in reason or "first" in reason

    # Weight conflict entry carries both conflicting values and a reason.
    weight_conflicts = [p for p in body["preview"] if p["action"] == "conflict" and p.get("field") == "weight"]
    assert len(weight_conflicts) == 1
    wc = weight_conflicts[0]
    assert wc["old"] is not None   # SM remaining_weight
    assert wc["new"] is not None   # FDB totalWeight
    assert wc.get("reason")

    # Nothing applied / logged, snapshot not advanced.
    filamentdb.log_usage.assert_not_called()
    spoolman.update_spool.assert_not_called()
    assert db.query(SyncLog).count() == 0
    snap = db.query(Snapshot).filter_by(source="spoolman", entity_id="1").first()
    assert json.loads(snap.data)["remaining_weight"] == 800.0


# ---------------------------------------------------------------------------
# Conflicts — resolve records the choice, never auto-applies (FR-13/FR-16)
# ---------------------------------------------------------------------------


def test_resolve_conflict_records_choice_and_does_not_apply(db):
    db.add(Conflict(
        entity_type="spool",
        spoolman_id=1,
        filamentdb_filament_id="fil-1",
        filamentdb_spool_id="spool-1",
        field_name="weight",
        spoolman_value=json.dumps(790.0),
        filamentdb_value=json.dumps(1050.0),
    ))
    db.commit()
    conflict_id = db.query(Conflict).first().id

    spoolman = _fake_spoolman()
    filamentdb = _fake_filamentdb()
    client = _client(db, spoolman, filamentdb)

    resp = client.post(f"/api/conflicts/{conflict_id}/resolve", json={"resolution": "spoolman"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "resolved"
    assert body["resolution"] == "spoolman"
    assert body["resolved_value"] == 790.0  # recorded the chosen side

    # Never auto-applied to the other system.
    spoolman.update_spool.assert_not_called()
    filamentdb.log_usage.assert_not_called()
    filamentdb.update_spool.assert_not_called()

    # Leaves the open queue.
    assert client.get("/api/conflicts?status=open").json() == []
    assert len(client.get("/api/conflicts?status=resolved").json()) == 1


def test_resolve_manual_requires_value(db):
    db.add(Conflict(entity_type="spool", spoolman_id=1, field_name="weight"))
    db.commit()
    cid = db.query(Conflict).first().id
    client = _client(db)

    resp = client.post(f"/api/conflicts/{cid}/resolve", json={"resolution": "manual"})
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "manual_value_required"


def test_bulk_resolve(db):
    for sid in (1, 2, 3):
        db.add(Conflict(entity_type="spool", spoolman_id=sid, field_name="weight",
                        filamentdb_value=json.dumps(sid)))
    db.commit()
    ids = [c.id for c in db.query(Conflict).all()]
    client = _client(db)

    resp = client.post("/api/conflicts/bulk-resolve",
                       json={"ids": ids + [999], "resolution": "filamentdb"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["resolved"] == 3
    assert body["skipped"] == [999]


# ---------------------------------------------------------------------------
# Auto-sync guard (FR-8)
# ---------------------------------------------------------------------------


def test_auto_enable_refused_before_wizard_completed(db):
    client = _client(db)
    resp = client.post("/api/sync/auto", json={"enabled": True})
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "wizard_incomplete"


def test_auto_enable_allowed_after_wizard_completed(db):
    set_config_value(db, "wizard_completed", True)
    db.commit()
    client = _client(db)

    resp = client.post("/api/sync/auto", json={"enabled": True})
    assert resp.status_code == 200
    assert resp.json()["auto_sync_enabled"] is True


def test_auto_disable_always_allowed(db):
    client = _client(db)
    resp = client.post("/api/sync/auto", json={"enabled": False})
    assert resp.status_code == 200
    assert resp.json()["auto_sync_enabled"] is False


# ---------------------------------------------------------------------------
# Mappings status enums (FR-19)
# ---------------------------------------------------------------------------


def test_mappings_status_enums(db):
    fm = FilamentMapping(spoolman_filament_id=10, filamentdb_id="fil-in")
    db.add(fm)
    db.flush()

    sm_filament = {"id": 10, "name": "PLA", "vendor": {"name": "ELEGOO"}, "color_hex": "#fff"}

    # in_sync — both snapshots present, has filament mapping, no conflict
    db.add(SpoolMapping(spoolman_spool_id=1, filamentdb_filament_id="fil-in",
                        filamentdb_spool_id="s1", filament_mapping_id=fm.id))
    _snap(db, "spoolman", "1", {"remaining_weight": 800.0, "filament": sm_filament})
    _snap(db, "filamentdb", "s1", {"totalWeight": 1000.0})

    # pending — has filament mapping but FDB snapshot missing
    db.add(SpoolMapping(spoolman_spool_id=2, filamentdb_filament_id="fil-in",
                        filamentdb_spool_id="s2", filament_mapping_id=fm.id))
    _snap(db, "spoolman", "2", {"remaining_weight": 700.0, "filament": sm_filament})

    # conflict — open conflict references the spool
    db.add(SpoolMapping(spoolman_spool_id=3, filamentdb_filament_id="fil-in",
                        filamentdb_spool_id="s3", filament_mapping_id=fm.id))
    _snap(db, "spoolman", "3", {"remaining_weight": 600.0, "filament": sm_filament})
    _snap(db, "filamentdb", "s3", {"totalWeight": 900.0})
    db.add(Conflict(entity_type="spool", spoolman_id=3, filamentdb_spool_id="s3", field_name="weight"))

    # unlinked — no parent filament mapping
    db.add(SpoolMapping(spoolman_spool_id=4, filamentdb_filament_id="fil-x",
                        filamentdb_spool_id="s4", filament_mapping_id=None))
    db.commit()

    client = _client(db)
    rows = client.get("/api/mappings").json()
    by_spool = {r["spoolman_spool_id"]: r for r in rows}

    assert by_spool[1]["status"] == "in_sync"
    assert by_spool[1]["spoolman_weight"] == 800.0
    assert by_spool[1]["filamentdb_weight"] == 1000.0
    assert by_spool[1]["name"] == "PLA"
    assert by_spool[1]["vendor"] == "ELEGOO"
    assert by_spool[2]["status"] == "pending"
    assert by_spool[3]["status"] == "conflict"
    assert by_spool[4]["status"] == "unlinked"


def test_mappings_status_filter(db):
    db.add(SpoolMapping(spoolman_spool_id=4, filamentdb_filament_id="fil-x",
                        filamentdb_spool_id="s4", filament_mapping_id=None))
    db.commit()
    client = _client(db)
    rows = client.get("/api/mappings?status=unlinked").json()
    assert len(rows) == 1
    assert client.get("/api/mappings?status=in_sync").json() == []


def test_delete_mapping_unlinks_only(db):
    db.add(SpoolMapping(spoolman_spool_id=5, filamentdb_filament_id="fil-x", filamentdb_spool_id="s5"))
    db.commit()
    mid = db.query(SpoolMapping).first().id
    client = _client(db)

    resp = client.delete(f"/api/mappings/{mid}")
    assert resp.status_code == 204
    assert db.query(SpoolMapping).count() == 0


# ---------------------------------------------------------------------------
# Config (FR-2)
# ---------------------------------------------------------------------------


def test_config_get_and_update(db):
    client = _client(db)
    body = client.get("/api/config").json()
    assert body["weight_source_of_truth"] == "spoolman"
    assert body["wizard_completed"] is False

    resp = client.put("/api/config", json={
        "weight_source_of_truth": "filamentdb",
        "sync_weight_threshold_grams": 5.0,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["weight_source_of_truth"] == "filamentdb"
    assert body["sync_weight_threshold_grams"] == 5.0


def test_config_rejects_bad_enum(db):
    client = _client(db)
    resp = client.put("/api/config", json={"weight_source_of_truth": "nonsense"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Wizard (FR-1 … FR-6)
# ---------------------------------------------------------------------------


def test_wizard_direction_persists_choices(db):
    client = _client(db)
    resp = client.post("/api/wizard/direction", json={
        "import_direction": "filamentdb",
        "weight_source_of_truth": "filamentdb",
    })
    assert resp.status_code == 200
    cfg = client.get("/api/config").json()
    assert cfg["import_direction"] == "filamentdb"
    assert cfg["weight_source_of_truth"] == "filamentdb"
    # wizard not flipped complete by this phase
    assert cfg["wizard_completed"] is False


def test_wizard_matches_buckets_and_vendor_hint(db):
    sm = [SpoolmanFilament(id=10, name="PLA", color_hex="red", material="PLA",
                           vendor=SpoolmanVendor(id=1, name="ELEGOO"))]
    fdb = [FDBFilament.model_validate({"_id": "f1", "name": "PLA", "color": "red", "vendor": "Elegoo",
                                       "type": "PLA"})]
    client = _client(db, _fake_spoolman(filaments=sm), _fake_filamentdb(filaments=fdb))

    body = client.get("/api/wizard/matches").json()
    assert len(body["matched"]) == 1
    pair = body["matched"][0]
    assert pair["spoolman"]["spoolman_filament_id"] == 10
    assert pair["filamentdb"]["filamentdb_filament_id"] == "f1"
    assert pair["vendor_dedup_hint"] is not None  # ELEGOO vs Elegoo
    assert pair["spoolman"]["material"] == "PLA"
    assert pair["filamentdb"]["material"] == "PLA"


def test_wizard_matches_ref_material_fields(db):
    sm = [SpoolmanFilament(id=5, name="PETG", material="PETG", color_hex=None)]
    fdb = [FDBFilament.model_validate({"_id": "f2", "name": "PETG", "type": "PETG"})]
    client = _client(db, _fake_spoolman(filaments=sm), _fake_filamentdb(filaments=fdb))

    body = client.get("/api/wizard/matches").json()
    pair = body["matched"][0]
    assert pair["spoolman"]["material"] == "PETG"
    assert pair["filamentdb"]["material"] == "PETG"

    # Material is None when not set
    sm2 = [SpoolmanFilament(id=6, name="TPU")]
    fdb2 = [FDBFilament.model_validate({"_id": "f3", "name": "TPU"})]
    client2 = _client(db, _fake_spoolman(filaments=sm2), _fake_filamentdb(filaments=fdb2))
    body2 = client2.get("/api/wizard/matches").json()
    pair2 = body2["matched"][0]
    assert pair2["spoolman"]["material"] is None
    assert pair2["filamentdb"]["material"] is None


def test_wizard_matches_saved_decisions_empty(db):
    sm = [SpoolmanFilament(id=10, name="PLA", vendor=SpoolmanVendor(id=1, name="X"))]
    fdb = [FDBFilament.model_validate({"_id": "f1", "name": "PLA", "vendor": "X"})]
    client = _client(db, _fake_spoolman(filaments=sm), _fake_filamentdb(filaments=fdb))

    body = client.get("/api/wizard/matches").json()
    assert body["saved_decisions"] == []


def test_wizard_matches_saved_decisions_echoed(db):
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "link", "filamentdb_id": "f1"},
        {"spoolman_filament_id": 11, "action": "skip", "filamentdb_id": None},
    ])
    db.commit()

    sm = [SpoolmanFilament(id=10, name="PLA", vendor=SpoolmanVendor(id=1, name="X"))]
    fdb = [FDBFilament.model_validate({"_id": "f1", "name": "PLA", "vendor": "X"})]
    client = _client(db, _fake_spoolman(filaments=sm), _fake_filamentdb(filaments=fdb))

    body = client.get("/api/wizard/matches").json()
    saved = body["saved_decisions"]
    assert len(saved) == 2
    assert saved[0] == {"spoolman_filament_id": 10, "action": "link", "filamentdb_id": "f1"}
    assert saved[1]["spoolman_filament_id"] == 11
    assert saved[1]["action"] == "skip"


def test_wizard_save_matches_persists(db):
    client = _client(db)
    resp = client.post("/api/wizard/matches", json={"decisions": [
        {"spoolman_filament_id": 10, "action": "link", "filamentdb_id": "f1"},
        {"spoolman_filament_id": 11, "action": "skip"},
    ]})
    assert resp.status_code == 200
    assert resp.json()["persisted"] == 2


def test_wizard_weights_spoolman_direction(db):
    set_config_value(db, "import_direction", "spoolman")
    db.commit()
    spools = [_sm_spool(1, 800.0)]
    spools[0].spool_weight = 250.0
    client = _client(db, _fake_spoolman(spools=spools), _fake_filamentdb())

    body = client.get("/api/wizard/weights").json()
    assert body["direction"] == "spoolman_to_filamentdb"
    row = body["rows"][0]
    assert row["net_weight"] == 800.0
    assert row["gross_weight"] == 1050.0  # 800 + 250 tare
    assert row["tare"] == 250.0
    assert row["tare_source"] == "spoolman"


def test_wizard_connectivity_blocked_when_down(db):
    spoolman = _fake_spoolman()
    spoolman.health = AsyncMock(side_effect=RuntimeError("unreachable"))
    client = _client(db, spoolman, _fake_filamentdb())

    body = client.get("/api/wizard/connectivity").json()
    assert body["blocked"] is True
    assert body["systems"]["spoolman"]["status"] == "error"
    assert body["systems"]["filamentdb"]["status"] == "ok"


# ---------------------------------------------------------------------------
# Wizard execute (FR-7) — initial-sync write
# ---------------------------------------------------------------------------


def _setup_link_execute(db):
    """One Spoolman filament (id 10) + spool (id 1), linked to FDB 'fil-1'."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions",
                     [{"spoolman_filament_id": 10, "action": "link", "filamentdb_id": "fil-1"}])
    db.commit()
    spoolman = _fake_spoolman(
        filaments=[SpoolmanFilament(id=10, name="PLA", color_hex="red",
                                    vendor=SpoolmanVendor(id=1, name="ELEGOO"))],
        spools=[_sm_spool(1, 800.0)],
    )
    filamentdb = _fake_filamentdb(filaments=[_fdb_filament("fil-1", "ignored", 0.0)])
    filamentdb.create_spool = AsyncMock(return_value={"_id": "fdb-spool-1"})
    return spoolman, filamentdb


def test_wizard_execute_clean_links_creates_spool_and_maps(db):
    spoolman, filamentdb = _setup_link_execute(db)
    client = _client(db, spoolman, filamentdb)

    resp = client.post("/api/wizard/execute")
    assert resp.status_code == 200
    body = resp.json()
    assert body["wizard_completed"] is True
    assert body["direction"] == "spoolman_to_filamentdb"
    assert body["created"] == 1  # the FDB spool
    assert body["failed"] == 0

    # FDB spool created with the seed weight SET (net 800 + 200 default tare).
    filamentdb.create_spool.assert_awaited_once()
    f_args = filamentdb.create_spool.await_args
    assert f_args.args[0] == "fil-1"
    assert f_args.args[1]["totalWeight"] == 1000.0
    assert f_args.args[1]["label"] == "1"  # Spoolman spool id stored in FDB label

    # Cross-ref IDs written back to the Spoolman spool extra fields (JSON-encoded).
    spoolman.update_spool.assert_awaited_once()
    extra = spoolman.update_spool.await_args.args[1]["extra"]
    assert extra["filamentdb_id"] == json.dumps("fil-1")
    assert extra["filamentdb_spool_id"] == json.dumps("fdb-spool-1")

    # Mapping rows on both sides.
    fm = db.query(FilamentMapping).one()
    assert fm.spoolman_filament_id == 10 and fm.filamentdb_id == "fil-1"
    sm_map = db.query(SpoolMapping).one()
    assert sm_map.spoolman_spool_id == 1 and sm_map.filamentdb_spool_id == "fdb-spool-1"

    # wizard_completed persisted; snapshots seeded for the pair.
    assert get_config_value(db, "wizard_completed") is True
    assert db.query(Snapshot).filter_by(source="spoolman", entity_id="1").count() == 1
    assert db.query(Snapshot).filter_by(source="filamentdb", entity_id="fdb-spool-1").count() == 1


def test_wizard_execute_seed_weight_is_set_not_logged_as_usage(db):
    spoolman, filamentdb = _setup_link_execute(db)
    client = _client(db, spoolman, filamentdb)

    client.post("/api/wizard/execute")
    # Seed weights are SET on create — never decremented via usage entries (FR-9).
    filamentdb.log_usage.assert_not_called()
    assert db.query(SyncLog).filter_by(action="create", entity_type="spool").count() == 1


def test_wizard_execute_creates_missing_fdb_filament(db):
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions",
                     [{"spoolman_filament_id": 10, "action": "create"}])
    db.commit()
    spoolman = _fake_spoolman(
        filaments=[SpoolmanFilament(id=10, name="PLA", vendor=SpoolmanVendor(id=1, name="ELEGOO"))],
        spools=[_sm_spool(1, 500.0)],
    )
    filamentdb = _fake_filamentdb(filaments=[])
    filamentdb.create_filament = AsyncMock(return_value=MagicMock(id="new-fil"))
    filamentdb.create_spool = AsyncMock(return_value={"_id": "new-spool"})
    client = _client(db, spoolman, filamentdb)

    body = client.post("/api/wizard/execute").json()
    filamentdb.create_filament.assert_awaited_once()
    assert body["created"] == 2  # filament + spool
    assert db.query(FilamentMapping).one().filamentdb_id == "new-fil"


def test_wizard_execute_idempotent_rerun_no_duplicates(db):
    """A re-run over already-linked records creates nothing new."""
    spoolman, filamentdb = _setup_link_execute(db)
    # Simulate a prior (partial) run that already persisted the mappings.
    fm = FilamentMapping(spoolman_filament_id=10, filamentdb_id="fil-1")
    db.add(fm)
    db.flush()
    db.add(SpoolMapping(spoolman_spool_id=1, filamentdb_filament_id="fil-1",
                        filamentdb_spool_id="fdb-spool-1", filament_mapping_id=fm.id))
    db.commit()

    body = client = _client(db, spoolman, filamentdb).post("/api/wizard/execute").json()
    assert body["created"] == 0
    assert body["failed"] == 0
    filamentdb.create_spool.assert_not_called()
    spoolman.update_spool.assert_not_called()
    # No duplicate mapping rows.
    assert db.query(FilamentMapping).count() == 1
    assert db.query(SpoolMapping).count() == 1


def test_wizard_execute_per_record_error_isolation(db):
    """One spool's API error → a failed entry; the rest still import; flag stays false."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions",
                     [{"spoolman_filament_id": 10, "action": "link", "filamentdb_id": "fil-1"}])
    db.commit()
    spoolman = _fake_spoolman(
        filaments=[SpoolmanFilament(id=10, name="PLA", vendor=SpoolmanVendor(id=1, name="ELEGOO"))],
        spools=[_sm_spool(1, 800.0), _sm_spool(2, 600.0)],
    )
    filamentdb = _fake_filamentdb(filaments=[_fdb_filament("fil-1", "ignored", 0.0)])

    async def _create_spool(filament_id, payload):
        if payload["label"] == "2":
            raise RuntimeError("boom")
        return {"_id": "fdb-spool-1"}

    filamentdb.create_spool = AsyncMock(side_effect=_create_spool)
    client = _client(db, spoolman, filamentdb)

    body = client.post("/api/wizard/execute").json()
    assert body["created"] == 1
    assert body["failed"] == 1
    # wizard_completed stays false when any record fails — user must re-run after fixing
    assert body["wizard_completed"] is False
    assert get_config_value(db, "wizard_completed") is False
    # Only the good spool got a mapping row.
    assert db.query(SpoolMapping).count() == 1
    assert db.query(SyncLog).filter_by(action="error", entity_type="spool").count() == 1


def test_wizard_execute_fatal_fetch_does_not_complete(db):
    set_config_value(db, "import_direction", "spoolman")
    db.commit()
    spoolman = _fake_spoolman()
    spoolman.get_filaments = AsyncMock(side_effect=RuntimeError("unreachable"))
    client = _client(db, spoolman, _fake_filamentdb())

    resp = client.post("/api/wizard/execute")
    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "upstream_fetch_failed"
    # A fatal fetch failure must NOT flip the wizard-complete flag.
    assert get_config_value(db, "wizard_completed") is False


def test_wizard_execute_filamentdb_direction_seeds_spoolman(db):
    """Smoke test for the reverse import: create Spoolman records from FDB."""
    set_config_value(db, "import_direction", "filamentdb")
    db.commit()
    fdb = [_fdb_filament("fil-1", "fdb-spool-1", 1000.0, tare=200.0)]
    spoolman = _fake_spoolman(filaments=[], vendors=[])
    spoolman.create_vendor = AsyncMock(return_value=SpoolmanVendor(id=5, name="elegoo"))
    spoolman.create_filament = AsyncMock(
        return_value=SpoolmanFilament(id=20, name="PLA", vendor=SpoolmanVendor(id=5, name="elegoo")))
    spoolman.create_spool = AsyncMock(return_value=_sm_spool(50, 800.0))
    filamentdb = _fake_filamentdb(filaments=fdb)
    client = _client(db, spoolman, filamentdb)

    body = client.post("/api/wizard/execute").json()
    assert body["direction"] == "filamentdb_to_spoolman"
    assert body["wizard_completed"] is True
    assert body["created"] == 2  # Spoolman filament + spool
    spoolman.create_filament.assert_awaited_once()
    spoolman.create_spool.assert_awaited_once()
    # net = 1000 gross - 200 tare = 800
    assert spoolman.create_spool.await_args.args[0]["remaining_weight"] == 800.0
    # SM id written back into the FDB spool label.
    filamentdb.update_spool.assert_awaited_once()
    assert filamentdb.update_spool.await_args.args[2]["label"] == "50"
    sm_map = db.query(SpoolMapping).one()
    assert sm_map.spoolman_spool_id == 50 and sm_map.filamentdb_spool_id == "fdb-spool-1"


# ---------------------------------------------------------------------------
# Sync status (FR-15)
# ---------------------------------------------------------------------------


def test_sync_status_payload(db):
    db.add(SpoolMapping(spoolman_spool_id=4, filamentdb_filament_id="fil-x",
                        filamentdb_spool_id="s4", filament_mapping_id=None))
    db.commit()
    client = _client(db)

    body = client.get("/api/sync/status").json()
    assert body["auto_sync_enabled"] is False
    assert body["wizard_completed"] is False
    assert body["counts"]["total"] == 1
    assert body["counts"]["unlinked"] == 1
    assert set(body["systems"].keys()) == {"spoolman", "filamentdb"}


# ---------------------------------------------------------------------------
# Sync log (FR-17)
# ---------------------------------------------------------------------------


def test_sync_log_pagination_and_filter(db):
    for i in range(5):
        db.add(SyncLog(cycle_id="c1", direction="spoolman_to_filamentdb",
                       action="update" if i % 2 == 0 else "error", entity_type="spool",
                       spoolman_id=i))
    db.commit()
    client = _client(db)

    body = client.get("/api/sync-log?limit=2").json()
    assert body["total"] == 5
    assert body["limit"] == 2
    assert len(body["items"]) == 2

    errors = client.get("/api/sync-log?action=error").json()
    assert errors["total"] == 2
    assert all(it["action"] == "error" for it in errors["items"])


# ---------------------------------------------------------------------------
# Backup round-trip (FR-24/FR-25)
# ---------------------------------------------------------------------------


def test_backup_export_import_roundtrip(db):
    fm = FilamentMapping(spoolman_filament_id=10, filamentdb_id="fil-1", filamentdb_parent_id="par-1")
    db.add(fm)
    db.flush()
    db.add(SpoolMapping(spoolman_spool_id=1, filamentdb_filament_id="fil-1",
                        filamentdb_spool_id="s1", filament_mapping_id=fm.id))
    db.add(Conflict(entity_type="spool", spoolman_id=1, filamentdb_spool_id="s1",
                    field_name="weight", spoolman_value=json.dumps(790.0),
                    filamentdb_value=json.dumps(1050.0)))
    set_config_value(db, "weight_source_of_truth", "filamentdb")
    db.commit()

    export = _client(db).get("/api/backup/export").json()
    assert export["schema_version"] == 1
    assert len(export["filament_mappings"]) == 1
    assert len(export["spool_mappings"]) == 1
    assert len(export["open_conflicts"]) == 1

    # Restore into a fresh database.
    fresh = _fresh_db()
    resp = _client(fresh).post("/api/backup/import", json=export)
    assert resp.status_code == 200
    counts = resp.json()
    assert counts["filament_mappings"] == 1
    assert counts["spool_mappings"] == 1
    assert counts["conflicts"] == 1

    assert fresh.query(FilamentMapping).count() == 1
    assert fresh.query(SpoolMapping).count() == 1
    assert fresh.query(Conflict).filter(Conflict.resolved_at.is_(None)).count() == 1
    restored_cfg = {r.key: json.loads(r.value) for r in fresh.query(BridgeConfig).all()}
    assert restored_cfg["weight_source_of_truth"] == "filamentdb"

    # Idempotent: importing again adds nothing new.
    resp2 = _client(fresh).post("/api/backup/import", json=export)
    assert resp2.json()["conflicts"] == 0
    assert fresh.query(SpoolMapping).count() == 1
    assert fresh.query(Conflict).filter(Conflict.resolved_at.is_(None)).count() == 1


def test_backup_import_rejects_bad_version(db):
    client = _client(db)
    resp = client.post("/api/backup/import", json={
        "schema_version": 999, "exported_at": "2026-05-29T00:00:00Z",
        "config": {}, "filament_mappings": [], "spool_mappings": [], "open_conflicts": [],
    })
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "unsupported_schema_version"


# ---------------------------------------------------------------------------
# Fix A — update_spool uses PATCH not PUT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spoolman_update_spool_uses_patch():
    """update_spool must call PATCH, not PUT (Spoolman v0.23.1 returns 405 on PUT)."""
    from app.services.spoolman import SpoolmanClient

    spool_response = {
        "id": 1, "filament": {"id": 1, "name": "PLA", "vendor": {"id": 1, "name": "ELEGOO"},
                               "color_hex": None, "material": "PLA", "density": None,
                               "spool_weight": None, "settings_extruder_temp": None,
                               "settings_bed_temp": None, "extra": {}},
        "remaining_weight": 500.0, "used_weight": 0.0, "archived": False,
        "spool_weight": None, "extra": {},
    }

    # Inject a mock directly — bypass __aenter__/__aexit__ to avoid real httpx connections
    client = SpoolmanClient("http://spoolman.test")
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = spool_response
    mock_http = AsyncMock()
    mock_http.patch = AsyncMock(return_value=mock_response)
    mock_http.put = AsyncMock()
    client._client = mock_http

    await client.update_spool(1, {"remaining_weight": 500.0})

    mock_http.patch.assert_awaited_once_with("/api/v1/spool/1", json={"remaining_weight": 500.0})
    mock_http.put.assert_not_called()


# ---------------------------------------------------------------------------
# Fix B — null material falls back to "Unknown" with a warning
# ---------------------------------------------------------------------------


def test_wizard_execute_null_material_uses_default(db):
    """A Spoolman filament with no material imports with 'Unknown' instead of 400-failing."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions",
                     [{"spoolman_filament_id": 10, "action": "create"}])
    db.commit()
    spoolman = _fake_spoolman(
        # material=None (the default) — FDB would reject this without the fallback
        filaments=[SpoolmanFilament(id=10, name="Silk Pumpkin Orange",
                                    vendor=SpoolmanVendor(id=1, name="eSUN"), material=None)],
        spools=[_sm_spool(1, 400.0)],
    )
    filamentdb = _fake_filamentdb(filaments=[])
    filamentdb.create_filament = AsyncMock(return_value=MagicMock(id="new-fil"))
    filamentdb.create_spool = AsyncMock(return_value={"_id": "new-spool"})
    client = _client(db, spoolman, filamentdb)

    body = client.post("/api/wizard/execute").json()
    assert body["failed"] == 0
    filamentdb.create_filament.assert_awaited_once()
    payload = filamentdb.create_filament.await_args.args[0]
    assert payload["type"] == "Unknown"


def test_wizard_execute_null_material_warning_logged(db, caplog):
    """A warning naming the Spoolman filament id must be emitted when material is missing."""
    import logging
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions",
                     [{"spoolman_filament_id": 77, "action": "create"}])
    db.commit()
    spoolman = _fake_spoolman(
        filaments=[SpoolmanFilament(id=77, name="No Material",
                                    vendor=SpoolmanVendor(id=1, name="X"), material=None)],
        spools=[],
    )
    filamentdb = _fake_filamentdb(filaments=[])
    filamentdb.create_filament = AsyncMock(return_value=MagicMock(id="fil-77"))
    client = _client(db, spoolman, filamentdb)

    with caplog.at_level(logging.WARNING, logger="app.api.wizard"):
        client.post("/api/wizard/execute")

    assert any("77" in r.message and "Unknown" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Fix C — weight precision config round-trips and is applied
# ---------------------------------------------------------------------------


def test_config_weight_precision_default_is_two(db):
    body = _client(db).get("/api/config").json()
    assert body["weight_precision_decimals"] == 2


def test_config_weight_precision_update_and_bounds(db):
    client = _client(db)
    resp = client.put("/api/config", json={"weight_precision_decimals": 0})
    assert resp.status_code == 200
    assert resp.json()["weight_precision_decimals"] == 0

    # Out-of-bounds (le=4)
    assert client.put("/api/config", json={"weight_precision_decimals": 5}).status_code == 422
    # Negative (ge=0)
    assert client.put("/api/config", json={"weight_precision_decimals": -1}).status_code == 422


def test_wizard_execute_weight_precision_applied(db):
    """Configured precision rounds the seed weight in the FDB spool create."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "weight_precision_decimals", 0)  # whole grams
    set_config_value(db, "wizard_match_decisions",
                     [{"spoolman_filament_id": 10, "action": "link", "filamentdb_id": "fil-1"}])
    db.commit()
    # remaining_weight with many decimals — will be rounded to whole gram
    spoolman = _fake_spoolman(
        filaments=[SpoolmanFilament(id=10, name="PLA", vendor=SpoolmanVendor(id=1, name="ELEGOO"))],
        spools=[_sm_spool(1, 539.4936014320408)],
    )
    spoolman.get_spools.return_value[0].spool_weight = None  # trigger default 200 tare
    filamentdb = _fake_filamentdb(filaments=[_fdb_filament("fil-1", "ignored", 0.0)])
    filamentdb.create_spool = AsyncMock(return_value={"_id": "fdb-spool-1"})
    client = _client(db, spoolman, filamentdb)

    client.post("/api/wizard/execute")
    payload = filamentdb.create_spool.await_args.args[1]
    # 539.4936... + 200 tare = 739.4936... → rounded to 0 decimals = 739.0
    assert payload["totalWeight"] == 739.0


# ---------------------------------------------------------------------------
# Fix D — wizard_completed only flips on zero failures
# ---------------------------------------------------------------------------


def test_wizard_completed_flips_true_on_zero_failures(db):
    spoolman, filamentdb = _setup_link_execute(db)
    body = _client(db, spoolman, filamentdb).post("/api/wizard/execute").json()
    assert body["wizard_completed"] is True
    assert get_config_value(db, "wizard_completed") is True


def test_wizard_completed_stays_false_on_any_failure(db):
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions",
                     [{"spoolman_filament_id": 10, "action": "link", "filamentdb_id": "fil-1"}])
    db.commit()
    spoolman = _fake_spoolman(
        filaments=[SpoolmanFilament(id=10, name="PLA", vendor=SpoolmanVendor(id=1, name="ELEGOO"))],
        spools=[_sm_spool(1, 800.0)],
    )
    filamentdb = _fake_filamentdb(filaments=[_fdb_filament("fil-1", "ignored", 0.0)])
    filamentdb.create_spool = AsyncMock(side_effect=RuntimeError("boom"))
    client = _client(db, spoolman, filamentdb)

    body = client.post("/api/wizard/execute").json()
    assert body["failed"] == 1
    assert body["wizard_completed"] is False
    assert get_config_value(db, "wizard_completed") is False


# ---------------------------------------------------------------------------
# Wizard preview (FR-4 foundation)
# ---------------------------------------------------------------------------


def _setup_preview(db, *, sm_filaments=None, sm_spools=None, fdb_filaments=None, decisions=None):
    set_config_value(db, "import_direction", "spoolman")
    if decisions is not None:
        set_config_value(db, "wizard_match_decisions", decisions)
    db.commit()
    spoolman = _fake_spoolman(filaments=sm_filaments or [], spools=sm_spools or [])
    filamentdb = _fake_filamentdb(filaments=fdb_filaments or [])
    return _client(db, spoolman, filamentdb), spoolman, filamentdb


def test_preview_makes_no_writes(db):
    """GET /api/wizard/preview must not call any mutating upstream method."""
    sm_fil = SpoolmanFilament(id=10, name="PLA", vendor=SpoolmanVendor(id=1, name="ELEGOO"))
    _, spoolman, filamentdb = _setup_preview(
        db,
        sm_filaments=[sm_fil],
        sm_spools=[_sm_spool(1, 800.0)],
        decisions=[{"spoolman_filament_id": 10, "action": "create"}],
    )
    client = _client(db, spoolman, filamentdb)

    resp = client.get("/api/wizard/preview")
    assert resp.status_code == 200

    spoolman.create_spool.assert_not_called()
    spoolman.update_spool.assert_not_called()
    spoolman.create_filament.assert_not_called()
    filamentdb.create_spool.assert_not_called()
    filamentdb.create_filament.assert_not_called()
    filamentdb.update_spool.assert_not_called()
    filamentdb.update_filament.assert_not_called()


def test_preview_name_collision_vs_existing_and_intra_batch(db):
    """Name collisions: vs_existing when FDB already has the name, intra_batch when SM batch duplicates it."""
    # Three SM filaments all named "Black PLA" → intra-batch collision among themselves
    # One of them also collides with an existing FDB filament named "Black PLA"
    sm_filaments = [
        SpoolmanFilament(id=10, name="Black PLA", vendor=SpoolmanVendor(id=1, name="ELEGOO")),
        SpoolmanFilament(id=11, name="Black PLA", vendor=SpoolmanVendor(id=2, name="Bambu")),
        SpoolmanFilament(id=12, name="White PLA", vendor=SpoolmanVendor(id=1, name="ELEGOO")),
    ]
    fdb_filaments = [
        FDBFilament.model_validate({"_id": "existing", "name": "Black PLA"}),
    ]
    decisions = [
        {"spoolman_filament_id": 10, "action": "create"},
        {"spoolman_filament_id": 11, "action": "create"},
        {"spoolman_filament_id": 12, "action": "create"},
    ]
    client, _, _ = _setup_preview(db, sm_filaments=sm_filaments, fdb_filaments=fdb_filaments, decisions=decisions)

    body = client.get("/api/wizard/preview").json()
    collisions = body["name_collisions"]

    # "black pla" collision (vs_existing=True and intra_batch=True)
    black_entry = next(c for c in collisions if c["normalized_name"] == "black pla")
    assert black_entry["vs_existing"] is True
    assert black_entry["intra_batch"] is True
    assert black_entry["existing_fdb_filament_id"] == "existing"
    assert set(black_entry["sm_filament_ids"]) == {10, 11}

    # "white pla" is unique — no collision entry
    assert not any(c["normalized_name"] == "white pla" for c in collisions)
    assert body["flag_counts"]["name_collision"] == 1


def test_preview_empty_active_flags_zero_weight_not_archived(db):
    """empty_active: flags remaining_weight==0 AND not archived; ignores archived-and-empty."""
    sm_fil = SpoolmanFilament(id=10, name="PLA", vendor=SpoolmanVendor(id=1, name="ELEGOO"))
    spools = [
        SpoolmanSpool(id=1, filament=sm_fil, remaining_weight=0.0, archived=False, extra={}),
        SpoolmanSpool(id=2, filament=sm_fil, remaining_weight=0.0, archived=True, extra={}),
        SpoolmanSpool(id=3, filament=sm_fil, remaining_weight=100.0, archived=False, extra={}),
    ]
    client, _, _ = _setup_preview(db, sm_filaments=[sm_fil], sm_spools=spools)

    body = client.get("/api/wizard/preview").json()
    empty = body["empty_active"]
    assert len(empty) == 1
    assert empty[0]["spoolman_spool_id"] == 1
    assert body["flag_counts"]["empty_active"] == 1


def test_preview_default_tare_reports_200g_substitution(db):
    """default_tare: flags planned spool creates where no spool_weight was set → 200 g used."""
    sm_fil = SpoolmanFilament(id=10, name="PLA", vendor=SpoolmanVendor(id=1, name="ELEGOO"),
                               spool_weight=None)
    spool = _sm_spool(1, 500.0)  # no spool_weight set
    decisions = [{"spoolman_filament_id": 10, "action": "create"}]
    client, _, _ = _setup_preview(db, sm_filaments=[sm_fil], sm_spools=[spool], decisions=decisions)

    body = client.get("/api/wizard/preview").json()
    tare_flags = body["default_tare"]
    assert len(tare_flags) == 1
    assert tare_flags[0]["spoolman_spool_id"] == 1
    assert tare_flags[0]["default_tare_used"] == 200.0
    assert tare_flags[0]["planned_gross"] == 700.0  # 500 + 200
    assert body["flag_counts"]["default_tare"] == 1


def test_preview_variant_group_on_empty_fdb(db):
    """variant_group: groups to-be-created filaments by vendor + material + base_name (color stripped)."""
    # Three SM filaments from the same vendor + material; names differ only in color-like suffix.
    # Because _strip_color uses color_hex (hex code), stripping won't remove the word,
    # so they'll only group if their normalized names match exactly. Use identical names here
    # to guarantee grouping (the real data has identical base names once the color part varies).
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_filaments = [
        SpoolmanFilament(id=10, name="PLA", vendor=elegoo, material="PLA", color_hex="#000000"),
        SpoolmanFilament(id=11, name="PLA", vendor=elegoo, material="PLA", color_hex="#ffffff"),
        SpoolmanFilament(id=12, name="PETG", vendor=elegoo, material="PETG", color_hex="#ff0000"),
    ]
    decisions = [
        {"spoolman_filament_id": 10, "action": "create"},
        {"spoolman_filament_id": 11, "action": "create"},
        {"spoolman_filament_id": 12, "action": "create"},
    ]
    client, _, _ = _setup_preview(db, sm_filaments=sm_filaments, decisions=decisions)

    body = client.get("/api/wizard/preview").json()
    groups = body["variant_groups"]
    # ids 10 and 11 share normalized name "pla" + vendor "elegoo" + material "pla"
    pla_group = next(g for g in groups if g["material"] == "PLA" and "pla" in g["base_name"])
    assert set(pla_group["sm_filament_ids"]) == {10, 11}
    # PETG is unique → no group
    assert not any(g["material"] == "PETG" for g in groups)
    assert body["flag_counts"]["variant_group"] == 1


# ---------------------------------------------------------------------------
# Health endpoint — FDB version + multicolor upgrade warning
# ---------------------------------------------------------------------------


def test_health_reports_fdb_version_and_no_warning_when_current(db):
    fdb = _fake_filamentdb()
    fdb.health = AsyncMock(return_value={"version": "1.33.0", "filament_count": 2, "spool_count": 3})
    client = _client(db, filamentdb=fdb)

    body = client.get("/api/health").json()
    fdb_sys = body["systems"]["filamentdb"]
    assert fdb_sys["version"] == "1.33.0"
    assert fdb_sys["warnings"] == []


def test_health_warns_when_fdb_too_old_for_multicolor(db):
    fdb = _fake_filamentdb()
    fdb.health = AsyncMock(return_value={"version": "1.32.5", "filament_count": 1, "spool_count": 1})
    client = _client(db, filamentdb=fdb)

    body = client.get("/api/health").json()
    fdb_sys = body["systems"]["filamentdb"]
    assert fdb_sys["version"] == "1.32.5"
    assert any("1.33.0" in w for w in fdb_sys["warnings"])


# ---------------------------------------------------------------------------
# SM variant grouping — pure unit tests (no HTTP)
# ---------------------------------------------------------------------------


def test_sm_prop_conflicts_agreement_returns_empty():
    from app.core.matcher import sm_prop_conflicts
    a = SpoolmanFilament(id=1, name="PLA", material="PLA", density=1.24,
                         spool_weight=200.0, settings_extruder_temp=210, settings_bed_temp=60)
    b = SpoolmanFilament(id=2, name="PLA Red", material="PLA", density=1.24,
                         spool_weight=200.0, settings_extruder_temp=210, settings_bed_temp=60)
    assert sm_prop_conflicts(a, b) == []


def test_sm_prop_conflicts_each_field_independently():
    from app.core.matcher import sm_prop_conflicts
    base = SpoolmanFilament(id=1, name="PLA", material="PLA", density=1.24,
                            spool_weight=200.0, settings_extruder_temp=210, settings_bed_temp=60)

    diff_material = SpoolmanFilament(id=2, name="PLA Red", material="PETG", density=1.24,
                                     spool_weight=200.0, settings_extruder_temp=210, settings_bed_temp=60)
    c = sm_prop_conflicts(base, diff_material)
    assert len(c) == 1 and c[0]["field"] == "material"

    diff_density = SpoolmanFilament(id=3, name="PLA Blue", material="PLA", density=1.27,
                                    spool_weight=200.0, settings_extruder_temp=210, settings_bed_temp=60)
    c = sm_prop_conflicts(base, diff_density)
    assert len(c) == 1 and c[0]["field"] == "density"

    diff_nozzle = SpoolmanFilament(id=4, name="PLA Green", material="PLA", density=1.24,
                                   spool_weight=200.0, settings_extruder_temp=220, settings_bed_temp=60)
    c = sm_prop_conflicts(base, diff_nozzle)
    assert len(c) == 1 and c[0]["field"] == "settings_extruder_temp"


def test_sm_prop_conflicts_none_vs_value_is_conflict():
    from app.core.matcher import sm_prop_conflicts
    a = SpoolmanFilament(id=1, name="A", density=1.24)
    b = SpoolmanFilament(id=2, name="B", density=None)
    c = sm_prop_conflicts(a, b)
    assert any(x["field"] == "density" for x in c)


def test_sm_prop_conflicts_both_none_not_conflict():
    from app.core.matcher import sm_prop_conflicts
    a = SpoolmanFilament(id=1, name="A", density=None, spool_weight=None)
    b = SpoolmanFilament(id=2, name="B", density=None, spool_weight=None)
    assert sm_prop_conflicts(a, b) == []


def test_strip_color_and_words_removes_hex_and_words():
    from app.core.matcher import strip_color_and_words
    assert strip_color_and_words("ELEGOO PLA Red", None) == "elegoo pla"
    assert strip_color_and_words("Silk PLA Black #000000", "#000000") == "silk pla"
    assert strip_color_and_words("PLA", None) == "pla"
    # Falls back to original normalized when stripping empties it
    assert strip_color_and_words("Red", None) == "red"


def test_sm_variant_cluster_key():
    from app.core.matcher import sm_variant_cluster_key
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    a = SpoolmanFilament(id=1, name="PLA Red", vendor=elegoo, material="PLA", color_hex="#ff0000")
    b = SpoolmanFilament(id=2, name="PLA Blue", vendor=elegoo, material="PLA", color_hex="#0000ff")
    c = SpoolmanFilament(id=3, name="PETG Red", vendor=elegoo, material="PETG", color_hex="#ff0000")
    assert sm_variant_cluster_key(a) == sm_variant_cluster_key(b), "same base → same cluster key"
    assert sm_variant_cluster_key(a) != sm_variant_cluster_key(c), "different material → different key"


# ---------------------------------------------------------------------------
# SM variant grouping — wizard/variants GET endpoint
# ---------------------------------------------------------------------------


def test_wizard_variants_spoolman_direction_clusters_by_base_name(db):
    set_config_value(db, "import_direction", "spoolman")
    db.commit()
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_filaments = [
        SpoolmanFilament(id=10, name="PLA Red", vendor=elegoo, material="PLA", color_hex="#ff0000"),
        SpoolmanFilament(id=11, name="PLA Blue", vendor=elegoo, material="PLA", color_hex="#0000ff"),
        SpoolmanFilament(id=12, name="PETG Red", vendor=elegoo, material="PETG", color_hex="#ff0000"),
    ]
    sm_spools = [_sm_spool(1, 500.0)]  # spool_id=1 belongs to filament 10 (default fixture)
    sm_spools[0].filament = SpoolmanFilament(id=10, name="PLA Red", vendor=elegoo, material="PLA")
    client = _client(db, _fake_spoolman(filaments=sm_filaments, spools=sm_spools), _fake_filamentdb())

    body = client.get("/api/wizard/variants").json()
    assert body["direction"] == "spoolman"
    groups = body["sm_groups"]
    # PLA Red + PLA Blue should cluster; PETG Red is a singleton
    pla_group = next((g for g in groups if "pla" in g["base_name"]), None)
    assert pla_group is not None
    member_ids = [m["ref"]["spoolman_filament_id"] for m in pla_group["members"]]
    assert set(member_ids) == {10, 11}
    assert not any("petg" in g["base_name"].lower() for g in groups)


def test_wizard_variants_spoolman_master_heuristic_most_spools(db):
    """Master = filament with most spools; tie-break = shortest name."""
    set_config_value(db, "import_direction", "spoolman")
    db.commit()
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_filaments = [
        SpoolmanFilament(id=10, name="PLA Red", vendor=elegoo, material="PLA"),
        SpoolmanFilament(id=11, name="PLA Blue", vendor=elegoo, material="PLA"),
    ]
    spool_for_10 = _sm_spool(1, 500.0)
    spool_for_10.filament = SpoolmanFilament(id=10, name="PLA Red", vendor=elegoo)
    spool_for_10b = _sm_spool(2, 300.0)
    spool_for_10b.filament = SpoolmanFilament(id=10, name="PLA Red", vendor=elegoo)
    client = _client(db,
        _fake_spoolman(filaments=sm_filaments, spools=[spool_for_10, spool_for_10b]),
        _fake_filamentdb())

    body = client.get("/api/wizard/variants").json()
    groups = body["sm_groups"]
    assert len(groups) == 1
    # filament 10 has 2 spools → should be master
    assert groups[0]["suggested_master"]["spoolman_filament_id"] == 10


def test_wizard_variants_spoolman_conflict_flags(db):
    """Members with differing material/density get conflict entries."""
    set_config_value(db, "import_direction", "spoolman")
    db.commit()
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_filaments = [
        SpoolmanFilament(id=10, name="PLA Red", vendor=elegoo, material="PLA", density=1.24),
        SpoolmanFilament(id=11, name="PLA Blue", vendor=elegoo, material="PLA", density=1.27),
    ]
    client = _client(db, _fake_spoolman(filaments=sm_filaments, spools=[]), _fake_filamentdb())

    body = client.get("/api/wizard/variants").json()
    groups = body["sm_groups"]
    assert len(groups) == 1
    master_id = groups[0]["suggested_master"]["spoolman_filament_id"]
    non_master = next(m for m in groups[0]["members"] if m["ref"]["spoolman_filament_id"] != master_id)
    assert any(c["field"] == "density" for c in non_master["conflicts"])


def test_wizard_variants_filamentdb_direction_returns_fdb_groups(db):
    """FDB direction still returns fdb_groups (legacy behavior)."""
    set_config_value(db, "import_direction", "filamentdb")
    db.commit()
    fdb_filaments = [
        FDBFilament.model_validate({"_id": "f1", "name": "PLA", "vendor": "ELEGOO"}),
        FDBFilament.model_validate({"_id": "f2", "name": "PLA RED", "vendor": "ELEGOO"}),
    ]
    client = _client(db, _fake_spoolman(), _fake_filamentdb(filaments=fdb_filaments))
    body = client.get("/api/wizard/variants").json()
    assert body["direction"] == "filamentdb"
    assert "fdb_groups" in body
    assert "sm_groups" in body


# ---------------------------------------------------------------------------
# SM variant decisions persistence — POST /wizard/variants/sm
# ---------------------------------------------------------------------------


def test_wizard_save_sm_variants_persists_to_new_key(db):
    client = _client(db)
    resp = client.post("/api/wizard/variants/sm", json={"groups": [
        {"master_spoolman_filament_id": 10, "variant_spoolman_filament_ids": [11, 12]},
    ]})
    assert resp.status_code == 200
    assert resp.json()["persisted"] == 1
    from app.api.config import get_config_value
    stored = get_config_value(db, "wizard_sm_variant_decisions", [])
    assert stored[0]["master_spoolman_filament_id"] == 10
    assert set(stored[0]["variant_spoolman_filament_ids"]) == {11, 12}


def test_wizard_save_variants_legacy_key_unchanged(db):
    """POST /wizard/variants still writes to the legacy FDB-keyed key."""
    client = _client(db)
    resp = client.post("/api/wizard/variants", json={"groups": [
        {"parent_filamentdb_id": "fil-1", "variant_filamentdb_ids": ["fil-2", "fil-3"]},
    ]})
    assert resp.status_code == 200
    from app.api.config import get_config_value
    stored = get_config_value(db, "wizard_variant_decisions", [])
    assert stored[0]["parent_filamentdb_id"] == "fil-1"
    # SM key is untouched
    assert get_config_value(db, "wizard_sm_variant_decisions", []) == []


def test_wizard_save_sm_variants_rejects_skipped_master(db):
    set_config_value(db, "wizard_match_decisions",
                     [{"spoolman_filament_id": 10, "action": "skip"}])
    db.commit()
    client = _client(db)
    resp = client.post("/api/wizard/variants/sm", json={"groups": [
        {"master_spoolman_filament_id": 10, "variant_spoolman_filament_ids": [11]},
    ]})
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "master_is_skipped"


def test_wizard_save_sm_and_legacy_variants_coexist(db):
    """Both SM and FDB decisions can be saved independently."""
    client = _client(db)
    client.post("/api/wizard/variants/sm", json={"groups": [
        {"master_spoolman_filament_id": 5, "variant_spoolman_filament_ids": [6]},
    ]})
    client.post("/api/wizard/variants", json={"groups": [
        {"parent_filamentdb_id": "fil-p", "variant_filamentdb_ids": ["fil-v"]},
    ]})
    from app.api.config import get_config_value
    assert get_config_value(db, "wizard_sm_variant_decisions", []) != []
    assert get_config_value(db, "wizard_variant_decisions", []) != []


# ---------------------------------------------------------------------------
# Planner with master_of_sm
# ---------------------------------------------------------------------------


def test_planner_master_of_sm_annotates_variants():
    """Variant items get variant_master_sm_id; master item stays None."""
    from app.core.planner import _plan_spoolman_to_fdb
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_filaments = [
        SpoolmanFilament(id=10, name="PLA", vendor=elegoo, material="PLA"),   # master
        SpoolmanFilament(id=11, name="PLA Red", vendor=elegoo, material="PLA"),  # variant
    ]
    decisions = {
        10: {"action": "create"},
        11: {"action": "create"},
    }
    master_of_sm = {11: 10}
    db = _fresh_db()
    plan = _plan_spoolman_to_fdb(db, sm_filaments, [], [], decisions, master_of_sm, {})
    items_by_id = {i.sm_filament.id: i for i in plan.filament_items}
    assert items_by_id[10].variant_master_sm_id is None, "master should have no parent"
    assert items_by_id[11].variant_master_sm_id == 10, "variant should point to master"


def test_planner_master_of_sm_skip_preserves_flat():
    """A group with no variants in master_of_sm → all items are ungrouped (flat)."""
    from app.core.planner import _plan_spoolman_to_fdb
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_filaments = [
        SpoolmanFilament(id=10, name="PLA", vendor=elegoo),
        SpoolmanFilament(id=11, name="PLA Red", vendor=elegoo),
    ]
    decisions = {10: {"action": "create"}, 11: {"action": "create"}}
    db = _fresh_db()
    plan = _plan_spoolman_to_fdb(db, sm_filaments, [], [], decisions, {}, {})
    for item in plan.filament_items:
        assert item.variant_master_sm_id is None, "no grouping → all flat"


def test_planner_prop_conflicts_populated():
    """Variant items with differing density get prop_conflicts filled."""
    from app.core.planner import _plan_spoolman_to_fdb
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_filaments = [
        SpoolmanFilament(id=10, name="PLA", vendor=elegoo, material="PLA", density=1.24),
        SpoolmanFilament(id=11, name="PLA Red", vendor=elegoo, material="PLA", density=1.27),
    ]
    decisions = {10: {"action": "create"}, 11: {"action": "create"}}
    master_of_sm = {11: 10}
    db = _fresh_db()
    plan = _plan_spoolman_to_fdb(db, sm_filaments, [], [], decisions, master_of_sm, {})
    items_by_id = {i.sm_filament.id: i for i in plan.filament_items}
    assert any(c["field"] == "density" for c in items_by_id[11].prop_conflicts)
    assert items_by_id[10].prop_conflicts == []


def test_planner_echoes_master_of_sm_on_plan():
    from app.core.planner import _plan_spoolman_to_fdb
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_filaments = [
        SpoolmanFilament(id=10, name="PLA", vendor=elegoo),
        SpoolmanFilament(id=11, name="PLA Red", vendor=elegoo),
    ]
    decisions = {10: {"action": "create"}, 11: {"action": "create"}}
    master_of_sm = {11: 10}
    db = _fresh_db()
    plan = _plan_spoolman_to_fdb(db, sm_filaments, [], [], decisions, master_of_sm, {})
    assert plan.master_of_sm == {11: 10}


# ---------------------------------------------------------------------------
# Executor — variant grouping end-to-end
# ---------------------------------------------------------------------------


def test_wizard_execute_variant_group_creates_with_parent_id(db):
    """Greenfield group: master create + 2 variant creates; variants get parentId injected."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
        {"spoolman_filament_id": 11, "action": "create"},
        {"spoolman_filament_id": 12, "action": "create"},
    ])
    set_config_value(db, "wizard_sm_variant_decisions", [
        {"master_spoolman_filament_id": 10, "variant_spoolman_filament_ids": [11, 12]},
    ])
    db.commit()

    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_filaments = [
        SpoolmanFilament(id=10, name="PLA", vendor=elegoo, material="PLA"),
        SpoolmanFilament(id=11, name="PLA Red", vendor=elegoo, material="PLA"),
        SpoolmanFilament(id=12, name="PLA Blue", vendor=elegoo, material="PLA"),
    ]
    spoolman = _fake_spoolman(filaments=sm_filaments, spools=[])
    filamentdb = _fake_filamentdb(filaments=[])

    create_calls = []
    async def _create_filament(payload):
        create_calls.append(payload)
        return MagicMock(id=f"fdb-fil-{len(create_calls)}")

    filamentdb.create_filament = AsyncMock(side_effect=_create_filament)
    client = _client(db, spoolman, filamentdb)

    body = client.post("/api/wizard/execute").json()
    assert body["failed"] == 0
    assert body["created"] == 3  # 3 filament creates

    # Master (id=10) must be created without parentId
    master_call = next(c for c in create_calls if c.get("name") == "PLA" and "parentId" not in c)
    assert master_call is not None

    # Both variants must have parentId in their create payload
    variant_calls = [c for c in create_calls if "parentId" in c]
    assert len(variant_calls) == 2
    assert all(c["parentId"] is not None for c in variant_calls)

    # FilamentMapping for variants has filamentdb_parent_id set
    maps = {m.spoolman_filament_id: m for m in db.query(FilamentMapping).all()}
    assert maps[11].filamentdb_parent_id is not None
    assert maps[12].filamentdb_parent_id is not None
    assert maps[10].filamentdb_parent_id is None


def test_wizard_execute_link_variant_calls_update_filament(db):
    """Link variant: update_filament called with parentId on the existing FDB record."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "link", "filamentdb_id": "fdb-master"},
        {"spoolman_filament_id": 11, "action": "link", "filamentdb_id": "fdb-variant"},
    ])
    set_config_value(db, "wizard_sm_variant_decisions", [
        {"master_spoolman_filament_id": 10, "variant_spoolman_filament_ids": [11]},
    ])
    db.commit()

    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_filaments = [
        SpoolmanFilament(id=10, name="PLA", vendor=elegoo),
        SpoolmanFilament(id=11, name="PLA Red", vendor=elegoo),
    ]
    fdb_filaments = [
        _fdb_filament("fdb-master", "s-master", 0.0),
        _fdb_filament("fdb-variant", "s-variant", 0.0),
    ]
    spoolman = _fake_spoolman(filaments=sm_filaments, spools=[])
    filamentdb = _fake_filamentdb(filaments=fdb_filaments)
    client = _client(db, spoolman, filamentdb)

    client.post("/api/wizard/execute")

    update_calls = filamentdb.update_filament.call_args_list
    parent_set = [c for c in update_calls if c.args[1].get("parentId") == "fdb-master"]
    assert len(parent_set) == 1
    assert parent_set[0].args[0] == "fdb-variant"


def test_wizard_execute_master_skip_fails_variant(db):
    """When master has skip decision, variants get a failed record (no orphan parentId)."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "skip"},
        {"spoolman_filament_id": 11, "action": "create"},
    ])
    set_config_value(db, "wizard_sm_variant_decisions", [
        {"master_spoolman_filament_id": 10, "variant_spoolman_filament_ids": [11]},
    ])
    db.commit()

    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_filaments = [
        SpoolmanFilament(id=10, name="PLA", vendor=elegoo),
        SpoolmanFilament(id=11, name="PLA Red", vendor=elegoo),
    ]
    spoolman = _fake_spoolman(filaments=sm_filaments, spools=[])
    filamentdb = _fake_filamentdb(filaments=[])
    client = _client(db, spoolman, filamentdb)

    body = client.post("/api/wizard/execute").json()
    assert body["failed"] >= 1
    failed_records = [r for r in body["records"] if r["action"] == "failed"
                      and r["spoolman_filament_id"] == 11]
    assert len(failed_records) == 1


def test_wizard_execute_variant_spool_cross_ref_has_parent_id(db):
    """Spool extra filamentdb_parent_id is set to the master's FDB id."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
        {"spoolman_filament_id": 11, "action": "create"},
    ])
    set_config_value(db, "wizard_sm_variant_decisions", [
        {"master_spoolman_filament_id": 10, "variant_spoolman_filament_ids": [11]},
    ])
    db.commit()

    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_filaments = [
        SpoolmanFilament(id=10, name="PLA", vendor=elegoo, material="PLA"),
        SpoolmanFilament(id=11, name="PLA Red", vendor=elegoo, material="PLA"),
    ]
    spool_for_11 = _sm_spool(101, 500.0)
    spool_for_11.filament = SpoolmanFilament(id=11, name="PLA Red", vendor=elegoo)
    spoolman = _fake_spoolman(filaments=sm_filaments, spools=[spool_for_11])

    created_fdb_ids = []
    async def _create_filament(payload):
        fid = f"fdb-{10 + len(created_fdb_ids)}"
        created_fdb_ids.append(fid)
        return MagicMock(id=fid)

    filamentdb = _fake_filamentdb(filaments=[])
    filamentdb.create_filament = AsyncMock(side_effect=_create_filament)
    filamentdb.create_spool = AsyncMock(return_value={"_id": "fdb-spool-101"})
    client = _client(db, spoolman, filamentdb)

    client.post("/api/wizard/execute")

    # The cross-ref extra on SM spool 101 should have a non-empty filamentdb_parent_id
    update_calls = spoolman.update_spool.call_args_list
    spool_update = next(c for c in update_calls if c.args[0] == 101)
    extra = spool_update.args[1]["extra"]
    assert extra["filamentdb_parent_id"] != json.dumps("")


def test_wizard_execute_variant_idempotent_rerun(db):
    """Re-running after partial failure on variants does not create duplicates."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
        {"spoolman_filament_id": 11, "action": "create"},
    ])
    set_config_value(db, "wizard_sm_variant_decisions", [
        {"master_spoolman_filament_id": 10, "variant_spoolman_filament_ids": [11]},
    ])
    db.commit()

    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_filaments = [
        SpoolmanFilament(id=10, name="PLA", vendor=elegoo, material="PLA"),
        SpoolmanFilament(id=11, name="PLA Red", vendor=elegoo, material="PLA"),
    ]
    # Pre-seed the mapping as if a prior partial run created the master
    db.add(FilamentMapping(spoolman_filament_id=10, filamentdb_id="fdb-master"))
    db.commit()

    spoolman = _fake_spoolman(filaments=sm_filaments, spools=[])
    filamentdb = _fake_filamentdb(filaments=[])
    filamentdb.create_filament = AsyncMock(return_value=MagicMock(id="fdb-variant"))
    client = _client(db, spoolman, filamentdb)

    body = client.post("/api/wizard/execute").json()
    # Master is skipped (already linked); variant is created fresh
    assert body["failed"] == 0
    assert db.query(FilamentMapping).count() == 2


# ---------------------------------------------------------------------------
# Preview — variant_plan populated, no writes
# ---------------------------------------------------------------------------


def test_preview_variant_plan_populated_from_sm_decisions(db):
    """variant_plan reflects saved SM variant decisions with conflict flags."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
        {"spoolman_filament_id": 11, "action": "create"},
    ])
    set_config_value(db, "wizard_sm_variant_decisions", [
        {"master_spoolman_filament_id": 10, "variant_spoolman_filament_ids": [11]},
    ])
    db.commit()

    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_filaments = [
        SpoolmanFilament(id=10, name="PLA", vendor=elegoo, material="PLA", density=1.24),
        SpoolmanFilament(id=11, name="PLA Red", vendor=elegoo, material="PLA", density=1.27),
    ]
    client = _client(db, _fake_spoolman(filaments=sm_filaments, spools=[]), _fake_filamentdb(filaments=[]))

    resp = client.get("/api/wizard/preview")
    assert resp.status_code == 200
    body = resp.json()
    assert "variant_plan" in body
    assert len(body["variant_plan"]) == 1
    group = body["variant_plan"][0]
    # Master member has no conflicts; variant member has density conflict
    master_m = next(m for m in group["members"] if m["is_master"])
    assert master_m["conflicts"] == []
    variant_m = next(m for m in group["members"] if not m["is_master"])
    assert any(c["field"] == "density" for c in variant_m["conflicts"])


def test_preview_variant_plan_empty_when_no_sm_decisions(db):
    """No wizard_sm_variant_decisions → variant_plan is empty."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
    ])
    db.commit()
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    client = _client(
        db,
        _fake_spoolman(filaments=[SpoolmanFilament(id=10, name="PLA", vendor=elegoo)], spools=[]),
        _fake_filamentdb(filaments=[]),
    )
    body = client.get("/api/wizard/preview").json()
    assert body["variant_plan"] == []


def test_preview_with_sm_decisions_makes_no_writes(db):
    """Preview with SM variant decisions must not call any mutating upstream method."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
        {"spoolman_filament_id": 11, "action": "create"},
    ])
    set_config_value(db, "wizard_sm_variant_decisions", [
        {"master_spoolman_filament_id": 10, "variant_spoolman_filament_ids": [11]},
    ])
    db.commit()
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_filaments = [
        SpoolmanFilament(id=10, name="PLA", vendor=elegoo),
        SpoolmanFilament(id=11, name="PLA Red", vendor=elegoo),
    ]
    spoolman = _fake_spoolman(filaments=sm_filaments, spools=[])
    filamentdb = _fake_filamentdb(filaments=[])
    client = _client(db, spoolman, filamentdb)

    resp = client.get("/api/wizard/preview")
    assert resp.status_code == 200
    filamentdb.create_filament.assert_not_called()
    filamentdb.update_filament.assert_not_called()
    spoolman.update_spool.assert_not_called()
