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
    db.add(SpoolMapping(spoolman_spool_id=1, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    _snap(db, "spoolman", "1", {"remaining_weight": 800.0})
    _snap(db, "filamentdb", "spool-1", {"totalWeight": 1000.0})
    db.commit()

    spoolman = _fake_spoolman(spools=[_sm_spool(1, 795.0)])
    filamentdb = _fake_filamentdb(filaments=[_fdb_filament("fil-1", "spool-1", 1000.0)])
    client = _client(db, spoolman, filamentdb)

    resp = client.post("/api/sync/dry-run")
    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run"] is True
    assert body["updated"] == 1
    assert len(body["preview"]) >= 1

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
    sm = [SpoolmanFilament(id=10, name="PLA", color_hex="red",
                           vendor=SpoolmanVendor(id=1, name="ELEGOO"))]
    fdb = [FDBFilament.model_validate({"_id": "f1", "name": "PLA", "color": "red", "vendor": "Elegoo"})]
    client = _client(db, _fake_spoolman(filaments=sm), _fake_filamentdb(filaments=fdb))

    body = client.get("/api/wizard/matches").json()
    assert len(body["matched"]) == 1
    pair = body["matched"][0]
    assert pair["spoolman"]["spoolman_filament_id"] == 10
    assert pair["filamentdb"]["filamentdb_filament_id"] == "f1"
    assert pair["vendor_dedup_hint"] is not None  # ELEGOO vs Elegoo


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
    """One spool's API error → a failed entry; the rest still import; flag flips."""
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
    assert body["wizard_completed"] is True  # per-record failure is non-fatal
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
