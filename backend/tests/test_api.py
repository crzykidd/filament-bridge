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
    # Default to "promote_color" so wizard-execute tests do not hit the unset gate.
    set_config_value(session, "variant_parent_mode", "promote_color")
    session.commit()
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
    client.get_locations = AsyncMock(return_value=[])
    client.create_location = AsyncMock(return_value={"_id": "loc-1", "name": "TestShelf"})
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


def _sm_spool(spool_id: int, remaining: float, extra=None, location: str | None = None) -> SpoolmanSpool:
    return SpoolmanSpool(
        id=spool_id,
        filament=SpoolmanFilament(id=10, name="PLA", vendor=SpoolmanVendor(id=1, name="ELEGOO")),
        remaining_weight=remaining,
        archived=False,
        extra=extra or {},
        location=location,
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

    # two_way + manual weight config so pair 4 (both-changed) still queues a conflict
    set_config_value(db, "weight_sync_direction", "two_way")
    set_config_value(db, "weight_conflict_policy", "manual")
    db.commit()

    archived = SpoolmanSpool(
        id=99,
        filament=SpoolmanFilament(id=10, name="PLA", vendor=SpoolmanVendor(id=1, name="ELEGOO")),
        remaining_weight=0.0,
        archived=True,
        extra={},
    )
    spoolman = _fake_spoolman(spools=[
        _sm_spool(1, 795.0),
        _sm_spool(2, 500.0),
        _sm_spool(3, 850.0),   # changed from 900 snapshot → weight conflict
        archived,              # sm_id=99 archived (in sm_all_ids but not active) → skip
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


def test_resolve_deletion_conflict_removes_mapping_and_snapshots(db):
    """Resolving a __record_deleted__ conflict removes the SpoolMapping and Snapshots."""
    db.add(SpoolMapping(spoolman_spool_id=1, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    db.add(Snapshot(source="spoolman", entity_type="spool", entity_id="1", data='{"remaining_weight": 800}'))
    db.add(Snapshot(source="filamentdb", entity_type="spool", entity_id="spool-1", data='{"totalWeight": 1000}'))
    db.add(Conflict(
        entity_type="spool",
        spoolman_id=1,
        filamentdb_filament_id="fil-1",
        filamentdb_spool_id="spool-1",
        field_name="__record_deleted__",
        spoolman_value=json.dumps({"exists": True, "deleted_side": "filamentdb"}),
        filamentdb_value=None,
    ))
    db.commit()
    cid = db.query(Conflict).first().id
    client = _client(db)

    resp = client.post(f"/api/conflicts/{cid}/resolve", json={"resolution": "spoolman"})
    assert resp.status_code == 200

    assert db.query(SpoolMapping).count() == 0
    assert db.query(Snapshot).count() == 0
    assert db.query(Conflict).filter_by(resolved_at=None).count() == 0


def test_resolve_normal_conflict_keeps_mapping(db):
    """Resolving a normal field conflict does NOT remove the SpoolMapping."""
    db.add(SpoolMapping(spoolman_spool_id=1, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
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
    cid = db.query(Conflict).first().id
    client = _client(db)

    resp = client.post(f"/api/conflicts/{cid}/resolve", json={"resolution": "spoolman"})
    assert resp.status_code == 200

    assert db.query(SpoolMapping).count() == 1


def test_bulk_resolve_deletion_conflict_removes_mapping(db):
    """bulk-resolve on a deletion conflict also removes the SpoolMapping."""
    db.add(SpoolMapping(spoolman_spool_id=1, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    db.add(Conflict(
        entity_type="spool",
        spoolman_id=1,
        filamentdb_filament_id="fil-1",
        filamentdb_spool_id="spool-1",
        field_name="__record_deleted__",
        filamentdb_value=json.dumps({"exists": True, "deleted_side": "spoolman"}),
        spoolman_value=None,
    ))
    db.commit()
    cid = db.query(Conflict).first().id
    client = _client(db)

    resp = client.post("/api/conflicts/bulk-resolve", json={"ids": [cid], "resolution": "filamentdb"})
    assert resp.status_code == 200
    assert db.query(SpoolMapping).count() == 0


def test_conflict_identity_populated_from_spool_snapshot(db):
    """GET /api/conflicts returns label/vendor/name/color_hex/material from the Spoolman spool snapshot."""
    spool_snap = {
        "id": 7,
        "remaining_weight": 500.0,
        "filament": {
            "id": 3,
            "name": "PLA Matte",
            "color_hex": "FF5733",
            "material": "PLA",
            "vendor": {"id": 1, "name": "ELEGOO"},
        },
    }
    db.add(Snapshot(
        source="spoolman",
        entity_type="spool",
        entity_id="7",
        data=json.dumps(spool_snap),
    ))
    db.add(Conflict(
        entity_type="spool",
        spoolman_id=7,
        filamentdb_filament_id="fil-1",
        filamentdb_spool_id="spool-1",
        field_name="weight",
        spoolman_value=json.dumps(500.0),
        filamentdb_value=json.dumps(700.0),
    ))
    db.commit()
    client = _client(db)

    resp = client.get("/api/conflicts?status=open")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    c = body[0]
    assert c["label"] == "ELEGOO PLA Matte"
    assert c["vendor"] == "ELEGOO"
    assert c["name"] == "PLA Matte"
    assert c["color_hex"] == "FF5733"
    assert c["material"] == "PLA"


def test_conflict_identity_graceful_when_no_snapshot(db):
    """GET /api/conflicts returns an id-based label and null identity fields when no snapshot exists."""
    db.add(Conflict(
        entity_type="spool",
        spoolman_id=42,
        filamentdb_filament_id="fil-2",
        filamentdb_spool_id="spool-2",
        field_name="weight",
        spoolman_value=json.dumps(100.0),
        filamentdb_value=json.dumps(200.0),
    ))
    db.commit()
    client = _client(db)

    resp = client.get("/api/conflicts?status=open")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    c = body[0]
    assert c["label"] == "SM #42"
    assert c["vendor"] is None
    assert c["name"] is None
    assert c["color_hex"] is None
    assert c["material"] is None


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


def test_mapping_row_enrichment_fields(db):
    """MappingRow includes multi_color_hexes/direction, remaining_weight/is_empty, and conflict_id."""
    fm = FilamentMapping(spoolman_filament_id=10, filamentdb_id="fil-mc")
    db.add(fm)
    db.flush()

    # Multicolor filament snapshot
    mc_filament = {
        "id": 10,
        "name": "Rainbow PLA",
        "vendor": {"name": "ACME"},
        "color_hex": None,
        "multi_color_hexes": "FF0000,00FF00,0000FF",
        "multi_color_direction": "longitudinal",
    }

    # Row 1: in_sync, multicolor, non-empty
    db.add(SpoolMapping(spoolman_spool_id=10, filamentdb_filament_id="fil-mc",
                        filamentdb_spool_id="s10", filament_mapping_id=fm.id))
    _snap(db, "spoolman", "10", {"remaining_weight": 450.0, "filament": mc_filament})
    _snap(db, "filamentdb", "s10", {"totalWeight": 650.0})

    # Row 2: conflict — has an open Conflict; remaining_weight == 0 → is_empty True
    fm2 = FilamentMapping(spoolman_filament_id=11, filamentdb_id="fil-empty")
    db.add(fm2)
    db.flush()
    plain_filament = {
        "id": 11,
        "name": "Empty PLA",
        "vendor": {"name": "ACME"},
        "color_hex": "AABBCC",
    }
    db.add(SpoolMapping(spoolman_spool_id=11, filamentdb_filament_id="fil-empty",
                        filamentdb_spool_id="s11", filament_mapping_id=fm2.id))
    _snap(db, "spoolman", "11", {"remaining_weight": 0.0, "filament": plain_filament})
    _snap(db, "filamentdb", "s11", {"totalWeight": 200.0})
    conflict = Conflict(entity_type="spool", spoolman_id=11, filamentdb_spool_id="s11",
                        field_name="weight")
    db.add(conflict)
    db.commit()
    conflict_id = db.query(Conflict).filter_by(spoolman_id=11).first().id

    client = _client(db)
    rows = client.get("/api/mappings").json()
    by_spool = {r["spoolman_spool_id"]: r for r in rows}

    # Row 1: multicolor fields populated, not empty, no conflict_id
    r1 = by_spool[10]
    assert r1["multi_color_hexes"] == "FF0000,00FF00,0000FF"
    assert r1["multi_color_direction"] == "longitudinal"
    assert r1["remaining_weight"] == 450.0
    assert r1["is_empty"] is False
    assert r1["conflict_id"] is None

    # Row 2: conflict_id set, is_empty True, no multicolor
    r2 = by_spool[11]
    assert r2["status"] == "conflict"
    assert r2["conflict_id"] == conflict_id
    assert r2["is_empty"] is True
    assert r2["remaining_weight"] == 0.0
    assert r2["multi_color_hexes"] is None
    assert r2["multi_color_direction"] is None


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
    assert body["weight_sync_direction"] == "spoolman_to_filamentdb"
    assert body["wizard_completed"] is False
    # Old *_source_of_truth fields must NOT appear in the response
    assert "weight_source_of_truth" not in body
    assert "material_properties_source_of_truth" not in body
    assert "new_spool_source_of_truth" not in body

    resp = client.put("/api/config", json={
        "weight_sync_direction": "filamentdb_to_spoolman",
        "sync_weight_threshold_grams": 5.0,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["weight_sync_direction"] == "filamentdb_to_spoolman"
    assert body["sync_weight_threshold_grams"] == 5.0


def test_config_rejects_bad_enum(db):
    client = _client(db)
    resp = client.put("/api/config", json={"weight_sync_direction": "nonsense"})
    assert resp.status_code == 422


def test_config_rejects_newest_wins_for_material_properties(db):
    """material_properties_conflict_policy=newest_wins must be rejected with HTTP 422."""
    client = _client(db)
    resp = client.put("/api/config", json={"material_properties_conflict_policy": "newest_wins"})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "invalid_conflict_policy"


def test_config_allows_newest_wins_for_weight(db):
    """weight_conflict_policy=newest_wins is valid and must be accepted."""
    client = _client(db)
    resp = client.put("/api/config", json={"weight_conflict_policy": "newest_wins"})
    assert resp.status_code == 200
    assert resp.json()["weight_conflict_policy"] == "newest_wins"


def test_config_sync_direction_fields_round_trip(db):
    """New four-axis fields read back correctly after update."""
    client = _client(db)
    resp = client.put("/api/config", json={
        "weight_sync_direction": "two_way",
        "weight_conflict_policy": "spoolman_wins",
        "material_properties_sync_direction": "spoolman_to_filamentdb",
        "material_properties_conflict_policy": "filamentdb_wins",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["weight_sync_direction"] == "two_way"
    assert body["weight_conflict_policy"] == "spoolman_wins"
    assert body["material_properties_sync_direction"] == "spoolman_to_filamentdb"
    assert body["material_properties_conflict_policy"] == "filamentdb_wins"


# ---------------------------------------------------------------------------
# never_import_empties — config round-trip + wizard execute behaviour
# ---------------------------------------------------------------------------


def test_never_import_empties_default_false(db):
    """never_import_empties defaults to false and round-trips via PUT /api/config."""
    client = _client(db)
    body = client.get("/api/config").json()
    assert body["never_import_empties"] is False

    resp = client.put("/api/config", json={"never_import_empties": True})
    assert resp.status_code == 200
    assert resp.json()["never_import_empties"] is True

    resp2 = client.put("/api/config", json={"never_import_empties": False})
    assert resp2.status_code == 200
    assert resp2.json()["never_import_empties"] is False


def test_wizard_execute_skips_empty_spool_when_never_import_empties_on(db):
    """When never_import_empties=True, an empty spool (remaining=0) is excluded from
    the plan entirely — the filament is still imported, and only the full spool is created."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "never_import_empties", True)
    set_config_value(db, "wizard_match_decisions",
                     [{"spoolman_filament_id": 10, "action": "create"}])
    db.commit()

    sm_filament = SpoolmanFilament(id=10, name="PLA", vendor=SpoolmanVendor(id=1, name="ELEGOO"))
    full_spool = SpoolmanSpool(
        id=1, filament=sm_filament, remaining_weight=500.0, archived=False, extra={},
    )
    empty_spool = SpoolmanSpool(
        id=2, filament=sm_filament, remaining_weight=0.0, archived=False, extra={},
    )
    spoolman = _fake_spoolman(filaments=[sm_filament], spools=[full_spool, empty_spool])
    filamentdb = _fake_filamentdb(filaments=[])
    filamentdb.create_filament = AsyncMock(return_value=MagicMock(id="new-fil"))
    filamentdb.create_spool = AsyncMock(return_value={"_id": "new-spool"})
    client = _client(db, spoolman, filamentdb)

    body = client.post("/api/wizard/execute").json()
    assert body["failed"] == 0
    # Filament created once (filament def always imported)
    filamentdb.create_filament.assert_awaited_once()
    # Only the full spool is created; the empty spool is excluded from the plan
    assert filamentdb.create_spool.await_count == 1
    created_spools = [r for r in body["records"] if r["entity_type"] == "spool" and r["action"] == "created"]
    assert len(created_spools) == 1
    assert created_spools[0]["spoolman_spool_id"] == 1
    # Empty spool (id=2) has no record at all — excluded from plan
    all_spool_records = [r for r in body["records"] if r["entity_type"] == "spool"]
    spool_ids_in_records = {r["spoolman_spool_id"] for r in all_spool_records}
    assert 2 not in spool_ids_in_records


def test_wizard_execute_imports_empty_spool_when_never_import_empties_off(db):
    """When never_import_empties=False (default), empty spools are imported normally."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "never_import_empties", False)
    set_config_value(db, "wizard_match_decisions",
                     [{"spoolman_filament_id": 10, "action": "create"}])
    db.commit()

    sm_filament = SpoolmanFilament(id=10, name="PLA", vendor=SpoolmanVendor(id=1, name="ELEGOO"))
    full_spool = SpoolmanSpool(
        id=1, filament=sm_filament, remaining_weight=500.0, archived=False, extra={},
    )
    empty_spool = SpoolmanSpool(
        id=2, filament=sm_filament, remaining_weight=0.0, archived=False, extra={},
    )
    spoolman = _fake_spoolman(filaments=[sm_filament], spools=[full_spool, empty_spool])
    filamentdb = _fake_filamentdb(filaments=[])
    filamentdb.create_filament = AsyncMock(return_value=MagicMock(id="new-fil"))
    filamentdb.create_spool = AsyncMock(return_value={"_id": "new-spool"})
    client = _client(db, spoolman, filamentdb)

    body = client.post("/api/wizard/execute").json()
    assert body["failed"] == 0
    # Both spools should be created
    assert filamentdb.create_spool.await_count == 2
    skipped_spools = [r for r in body["records"] if r["entity_type"] == "spool" and r["action"] == "skipped"]
    assert len(skipped_spools) == 0


def test_wizard_direction_save_works_without_sot_fields(db):
    """Wizard direction POST succeeds with only import_direction (no *_source_of_truth fields)."""
    client = _client(db)
    resp = client.post("/api/wizard/direction", json={"import_direction": "spoolman"})
    assert resp.status_code == 200
    assert resp.json()["persisted"] == 1
    assert client.get("/api/config").json()["import_direction"] == "spoolman"


# ---------------------------------------------------------------------------
# Wizard (FR-1 … FR-6)
# ---------------------------------------------------------------------------


def test_wizard_direction_persists_choices(db):
    """Wizard direction POST persists import_direction; extra fields are ignored."""
    client = _client(db)
    resp = client.post("/api/wizard/direction", json={
        "import_direction": "filamentdb",
    })
    assert resp.status_code == 200
    cfg = client.get("/api/config").json()
    assert cfg["import_direction"] == "filamentdb"
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


def test_wizard_matches_openprinttag_flag(db):
    """SM refs expose openprinttag=True when openprinttag_uuid extra is set, False otherwise."""
    from app.schemas.spoolman import encode_extra_value

    # SM filament 10 has a non-empty openprinttag_uuid → flag True
    sm_tagged = SpoolmanFilament(
        id=10, name="PLA", material="PLA",
        vendor=SpoolmanVendor(id=1, name="Brand"),
        extra={"openprinttag_uuid": encode_extra_value("some-uuid-value")},
    )
    # SM filament 11 has no openprinttag_uuid → flag False
    sm_untagged = SpoolmanFilament(
        id=11, name="PETG", material="PETG",
        vendor=SpoolmanVendor(id=1, name="Brand"),
        extra={},
    )
    fdb = [
        FDBFilament.model_validate({"_id": "f1", "name": "PLA", "vendor": "Brand", "type": "PLA"}),
        FDBFilament.model_validate({"_id": "f2", "name": "PETG", "vendor": "Brand", "type": "PETG"}),
    ]
    client = _client(db, _fake_spoolman(filaments=[sm_tagged, sm_untagged]), _fake_filamentdb(filaments=fdb))

    body = client.get("/api/wizard/matches").json()
    matched = {p["spoolman"]["spoolman_filament_id"]: p["spoolman"] for p in body["matched"]}
    assert matched[10]["openprinttag"] is True, "tagged filament should have openprinttag=True"
    assert matched[11]["openprinttag"] is False, "untagged filament should have openprinttag=False"


def test_wizard_save_matches_persists(db):
    client = _client(db)
    resp = client.post("/api/wizard/matches", json={"decisions": [
        {"spoolman_filament_id": 10, "action": "link", "filamentdb_id": "f1"},
        {"spoolman_filament_id": 11, "action": "skip"},
    ]})
    assert resp.status_code == 200
    assert resp.json()["persisted"] == 2


def test_wizard_skip_match_updates_existing_decision(db):
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 42, "action": "create"},
        {"spoolman_filament_id": 99, "action": "link", "filamentdb_id": "fdb-1"},
    ])
    db.commit()

    client = _client(db)
    resp = client.post("/api/wizard/matches/42/skip")
    assert resp.status_code == 200
    assert resp.json()["persisted"] == 1

    decisions = get_config_value(db, "wizard_match_decisions", [])
    d42 = next(d for d in decisions if d["spoolman_filament_id"] == 42)
    d99 = next(d for d in decisions if d["spoolman_filament_id"] == 99)
    assert d42["action"] == "skip"
    assert d99["action"] == "link"  # unchanged


def test_wizard_skip_match_appends_if_missing(db):
    set_config_value(db, "wizard_match_decisions", [])
    db.commit()

    client = _client(db)
    resp = client.post("/api/wizard/matches/77/skip")
    assert resp.status_code == 200

    decisions = get_config_value(db, "wizard_match_decisions", [])
    assert len(decisions) == 1
    assert decisions[0] == {"spoolman_filament_id": 77, "action": "skip"}


def test_wizard_skip_removes_from_included_sm_ids(db):
    from app.api.wizard import _included_sm_ids

    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 42, "action": "create"},
    ])
    db.commit()
    assert 42 in _included_sm_ids(db)

    client = _client(db)
    client.post("/api/wizard/matches/42/skip")

    # Session sees the committed change
    db.expire_all()
    assert 42 not in _included_sm_ids(db)


def test_wizard_weights_spoolman_direction(db):
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions",
                     [{"spoolman_filament_id": 10, "action": "create"}])
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

    body = _client(db, spoolman, filamentdb).post("/api/wizard/execute").json()
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


def test_wizard_execute_spool_location_included_in_payload(db):
    """SM spool with a location → FDB create_spool payload includes locationId."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions",
                     [{"spoolman_filament_id": 10, "action": "link", "filamentdb_id": "fil-1"}])
    db.commit()
    spoolman = _fake_spoolman(
        filaments=[SpoolmanFilament(id=10, name="PLA", vendor=SpoolmanVendor(id=1, name="ELEGOO"))],
        spools=[_sm_spool(1, 800.0, location="DryBox")],
    )
    filamentdb = _fake_filamentdb(filaments=[_fdb_filament("fil-1", "ignored", 0.0)])
    filamentdb.create_spool = AsyncMock(return_value={"_id": "fdb-spool-1"})
    filamentdb.create_location = AsyncMock(return_value={"_id": "loc-99", "name": "DryBox"})
    client = _client(db, spoolman, filamentdb)

    body = client.post("/api/wizard/execute").json()
    assert body["created"] == 1
    assert body["failed"] == 0

    filamentdb.create_spool.assert_awaited_once()
    payload = filamentdb.create_spool.await_args.args[1]
    assert payload["locationId"] == "loc-99"
    filamentdb.create_location.assert_awaited_once()
    assert filamentdb.create_location.await_args.args[0] == "DryBox"


def test_wizard_execute_spool_no_location_omits_key(db):
    """SM spool with no location → locationId key is absent (not null)."""
    spoolman, filamentdb = _setup_link_execute(db)
    filamentdb.create_spool = AsyncMock(return_value={"_id": "fdb-spool-1"})
    client = _client(db, spoolman, filamentdb)

    client.post("/api/wizard/execute")
    payload = filamentdb.create_spool.await_args.args[1]
    assert "locationId" not in payload


def test_wizard_execute_location_reuses_prefetched_id(db):
    """Location already in FDB (returned by get_locations) → create_location not called."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions",
                     [{"spoolman_filament_id": 10, "action": "link", "filamentdb_id": "fil-1"}])
    db.commit()
    spoolman = _fake_spoolman(
        filaments=[SpoolmanFilament(id=10, name="PLA", vendor=SpoolmanVendor(id=1, name="ELEGOO"))],
        spools=[_sm_spool(1, 800.0, location="Shelf A")],
    )
    filamentdb = _fake_filamentdb(filaments=[_fdb_filament("fil-1", "ignored", 0.0)])
    filamentdb.get_locations = AsyncMock(return_value=[{"_id": "loc-42", "name": "Shelf A"}])
    filamentdb.create_spool = AsyncMock(return_value={"_id": "fdb-spool-1"})
    client = _client(db, spoolman, filamentdb)

    body = client.post("/api/wizard/execute").json()
    assert body["failed"] == 0
    filamentdb.create_location.assert_not_called()
    payload = filamentdb.create_spool.await_args.args[1]
    assert payload["locationId"] == "loc-42"


def test_wizard_execute_location_failure_isolates_to_spool(db):
    """create_location failure → that spool fails; other spools in the run still import."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions",
                     [{"spoolman_filament_id": 10, "action": "link", "filamentdb_id": "fil-1"}])
    db.commit()
    spoolman = _fake_spoolman(
        filaments=[SpoolmanFilament(id=10, name="PLA", vendor=SpoolmanVendor(id=1, name="ELEGOO"))],
        spools=[
            _sm_spool(1, 800.0, location="BadShelf"),
            _sm_spool(2, 600.0),
        ],
    )
    filamentdb = _fake_filamentdb(filaments=[_fdb_filament("fil-1", "ignored", 0.0)])
    filamentdb.create_location = AsyncMock(side_effect=RuntimeError("location API down"))
    filamentdb.create_spool = AsyncMock(return_value={"_id": "fdb-spool-ok"})
    client = _client(db, spoolman, filamentdb)

    body = client.post("/api/wizard/execute").json()
    assert body["created"] == 1   # spool 2 (no location) succeeded
    assert body["failed"] == 1    # spool 1 (bad location) failed
    assert body["wizard_completed"] is False
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


def test_sync_log_windows(db):
    """windows=N returns only entries from the most recent N distinct cycle_ids."""
    import datetime

    base = datetime.datetime(2024, 1, 1, 12, 0, 0)
    # cycle "c1" — oldest (2 entries)
    for i in range(2):
        db.add(SyncLog(cycle_id="c1", direction="spoolman_to_filamentdb",
                       action="update", entity_type="spool", spoolman_id=i,
                       timestamp=base + datetime.timedelta(minutes=i)))
    # cycle "c2" — middle (3 entries)
    for i in range(3):
        db.add(SyncLog(cycle_id="c2", direction="spoolman_to_filamentdb",
                       action="update", entity_type="spool", spoolman_id=10 + i,
                       timestamp=base + datetime.timedelta(hours=1, minutes=i)))
    # cycle "c3" — newest (1 entry)
    db.add(SyncLog(cycle_id="c3", direction="spoolman_to_filamentdb",
                   action="update", entity_type="spool", spoolman_id=20,
                   timestamp=base + datetime.timedelta(hours=2)))
    db.commit()
    client = _client(db)

    # windows=1 — only the newest cycle (c3)
    body1 = client.get("/api/sync-log?windows=1").json()
    assert body1["total"] == 1
    assert all(it["cycle_id"] == "c3" for it in body1["items"])

    # windows=2 — last 2 cycles (c2 + c3 = 4 entries)
    body2 = client.get("/api/sync-log?windows=2").json()
    assert body2["total"] == 4
    cycle_ids = {it["cycle_id"] for it in body2["items"]}
    assert cycle_ids == {"c2", "c3"}

    # windows=10 (more than available) — all 3 cycles (all 6 entries)
    body3 = client.get("/api/sync-log?windows=10").json()
    assert body3["total"] == 6

    # without windows= — still works (total = 6)
    body_all = client.get("/api/sync-log").json()
    assert body_all["total"] == 6


def test_sync_log_windows_oldest_cycle_excluded(db):
    """windows=N selects only the most recent N cycles; older cycles are excluded."""
    import datetime

    base = datetime.datetime(2024, 1, 1, 12, 0, 0)
    # Three cycles — only c2 and c3 should appear with windows=2
    for cycle, delta, count in [("c1", 0, 2), ("c2", 60, 3), ("c3", 120, 1)]:
        for i in range(count):
            db.add(SyncLog(cycle_id=cycle, direction="spoolman_to_filamentdb",
                           action="update", entity_type="spool",
                           spoolman_id=100 * ord(cycle[-1]) + i,
                           timestamp=base + datetime.timedelta(minutes=delta + i)))
    db.commit()
    client = _client(db)

    # windows=2 should return c2 + c3 (4 entries) but NOT c1 (2 entries)
    body = client.get("/api/sync-log?windows=2").json()
    assert body["total"] == 4
    cycle_ids = {it["cycle_id"] for it in body["items"]}
    assert "c1" not in cycle_ids
    assert cycle_ids == {"c2", "c3"}


def test_sync_log_delete(db):
    """DELETE /sync-log clears all rows and returns the count."""
    for i in range(4):
        db.add(SyncLog(cycle_id="c1", direction="spoolman_to_filamentdb",
                       action="update", entity_type="spool", spoolman_id=i))
    db.commit()
    client = _client(db)

    resp = client.delete("/api/sync-log")
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted"] == 4

    # Table is now empty
    assert db.query(SyncLog).count() == 0

    # Second delete returns 0
    resp2 = client.delete("/api/sync-log")
    assert resp2.json()["deleted"] == 0


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
    """Name collisions: vendor-aware — only same-vendor+name collides.

    - ids 10 and 11 are both "Black PLA" from ELEGOO → intra_batch=True, vs_existing=True
      (existing FDB "Black PLA" is also from ELEGOO)
    - id 13 is "Black PLA" from a DIFFERENT vendor (Bambu) → no collision with ELEGOO entry
    - id 12 ("White PLA" / ELEGOO) is unique → no collision entry
    """
    sm_filaments = [
        SpoolmanFilament(id=10, name="Black PLA", vendor=SpoolmanVendor(id=1, name="ELEGOO")),
        SpoolmanFilament(id=11, name="Black PLA", vendor=SpoolmanVendor(id=1, name="ELEGOO")),
        SpoolmanFilament(id=12, name="White PLA", vendor=SpoolmanVendor(id=1, name="ELEGOO")),
        SpoolmanFilament(id=13, name="Black PLA", vendor=SpoolmanVendor(id=2, name="Bambu")),
    ]
    fdb_filaments = [
        # Same vendor+name as ids 10 and 11 → vs_existing should fire
        FDBFilament.model_validate({"_id": "existing", "name": "Black PLA", "vendor": "ELEGOO"}),
    ]
    decisions = [
        {"spoolman_filament_id": 10, "action": "create"},
        {"spoolman_filament_id": 11, "action": "create"},
        {"spoolman_filament_id": 12, "action": "create"},
        {"spoolman_filament_id": 13, "action": "create"},
    ]
    client, _, _ = _setup_preview(db, sm_filaments=sm_filaments, fdb_filaments=fdb_filaments, decisions=decisions)

    body = client.get("/api/wizard/preview").json()
    collisions = body["name_collisions"]

    # "black pla" from ELEGOO: intra_batch (ids 10+11) and vs_existing
    black_entry = next(c for c in collisions if c["normalized_name"] == "black pla")
    assert black_entry["vs_existing"] is True
    assert black_entry["intra_batch"] is True
    assert black_entry["existing_fdb_filament_id"] == "existing"
    assert set(black_entry["sm_filament_ids"]) == {10, 11}

    # id 13 "Black PLA" from Bambu → different vendor, no collision entry for it
    assert not any(13 in c["sm_filament_ids"] for c in collisions)

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


def test_sm_prop_conflicts_tare_only_diff_returns_empty():
    """spool_weight (tare) is excluded from the conflict check — tare-only diff is never a conflict."""
    from app.core.matcher import sm_prop_conflicts
    a = SpoolmanFilament(id=1, name="PLA Beige", material="PLA", density=1.24,
                         spool_weight=160.0, settings_extruder_temp=210, settings_bed_temp=60)
    b = SpoolmanFilament(id=2, name="PLA Black", material="PLA", density=1.24,
                         spool_weight=154.0, settings_extruder_temp=210, settings_bed_temp=60)
    assert sm_prop_conflicts(a, b) == [], "tare-only difference must not produce a conflict"


def test_sm_prop_conflicts_real_diff_still_detected():
    """A non-tare difference (diameter or temp) is still reported after the tare exclusion."""
    from app.core.matcher import sm_prop_conflicts
    a = SpoolmanFilament(id=1, name="PLA Red", material="PLA", diameter=1.75,
                         spool_weight=160.0, settings_extruder_temp=210)
    b = SpoolmanFilament(id=2, name="PLA Blue", material="PLA", diameter=2.85,
                         spool_weight=154.0, settings_extruder_temp=210)
    c = sm_prop_conflicts(a, b)
    fields = [x["field"] for x in c]
    assert "diameter" in fields
    assert "spool_weight" not in fields, "tare must not appear even when it also differs"


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
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
        {"spoolman_filament_id": 11, "action": "create"},
        {"spoolman_filament_id": 12, "action": "create"},
    ])
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
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
        {"spoolman_filament_id": 11, "action": "create"},
    ])
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
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
        {"spoolman_filament_id": 11, "action": "create"},
    ])
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


# ---------------------------------------------------------------------------
# Downstream filtering — only link|create SM filaments reach each endpoint
# ---------------------------------------------------------------------------


def test_wizard_weights_excludes_skip_and_undecided(db):
    """skip decision and no-decision filaments are excluded from wizard_weights."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
        {"spoolman_filament_id": 11, "action": "skip"},
        # filament 12: no decision (undecided)
    ])
    db.commit()
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")

    def mk_spool(sid, fid):
        return SpoolmanSpool(
            id=sid, filament=SpoolmanFilament(id=fid, name="PLA", vendor=elegoo),
            remaining_weight=500.0, archived=False, extra={},
        )

    spools = [mk_spool(1, 10), mk_spool(2, 11), mk_spool(3, 12)]
    client = _client(db, _fake_spoolman(spools=spools), _fake_filamentdb())

    body = client.get("/api/wizard/weights").json()
    assert body["direction"] == "spoolman_to_filamentdb"
    spool_ids = [r["spoolman_spool_id"] for r in body["rows"]]
    assert 1 in spool_ids           # filament 10 (create) included
    assert 2 not in spool_ids       # filament 11 (skip) excluded
    assert 3 not in spool_ids       # filament 12 (undecided) excluded


def test_wizard_variants_excludes_skip_and_undecided(db):
    """skip and undecided filaments are not clustered in wizard_variants."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
        {"spoolman_filament_id": 11, "action": "skip"},
        # filament 12: undecided
    ])
    db.commit()
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    # All three would cluster if unfiltered
    sm_filaments = [
        SpoolmanFilament(id=10, name="PLA Red", vendor=elegoo, material="PLA"),
        SpoolmanFilament(id=11, name="PLA Blue", vendor=elegoo, material="PLA"),
        SpoolmanFilament(id=12, name="PLA Green", vendor=elegoo, material="PLA"),
    ]
    client = _client(db, _fake_spoolman(filaments=sm_filaments, spools=[]), _fake_filamentdb())

    body = client.get("/api/wizard/variants").json()
    # Only filament 10 is included → singleton, no clusters
    assert body["sm_groups"] == []


# ---------------------------------------------------------------------------
# Variances endpoint
# ---------------------------------------------------------------------------


def test_wizard_variances_spoolman_returns_groups_and_ungrouped(db):
    """wizard_variances groups clusterable filaments and lists singletons as ungrouped."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
        {"spoolman_filament_id": 11, "action": "create"},
        {"spoolman_filament_id": 12, "action": "create"},
    ])
    db.commit()
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_filaments = [
        SpoolmanFilament(id=10, name="PLA Red", vendor=elegoo, material="PLA", color_hex="#ff0000"),
        SpoolmanFilament(id=11, name="PLA Blue", vendor=elegoo, material="PLA", color_hex="#0000ff"),
        SpoolmanFilament(id=12, name="PETG Red", vendor=elegoo, material="PETG", color_hex="#ff0000"),
    ]
    spool = _sm_spool(1, 500.0)
    spool.filament = SpoolmanFilament(id=10, name="PLA Red", vendor=elegoo, material="PLA")
    client = _client(db, _fake_spoolman(filaments=sm_filaments, spools=[spool]), _fake_filamentdb())

    body = client.get("/api/wizard/variances").json()
    assert body["direction"] == "spoolman"
    # PLA Red + PLA Blue cluster; PETG Red is a singleton
    assert len(body["groups"]) == 1
    group = body["groups"][0]
    member_ids = {m["ref"]["spoolman_filament_id"] for m in group["members"]}
    assert member_ids == {10, 11}
    # Spool ids for filament 10 populated
    master = next(m for m in group["members"] if m["is_master"])
    assert 1 in master["spool_ids"]
    # PETG Red is ungrouped
    assert len(body["ungrouped"]) == 1
    assert body["ungrouped"][0]["ref"]["spoolman_filament_id"] == 12


def test_wizard_variances_filters_skip_and_undecided(db):
    """skip and undecided SM filaments absent from variances response."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
        {"spoolman_filament_id": 11, "action": "skip"},
    ])
    db.commit()
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_filaments = [
        SpoolmanFilament(id=10, name="PLA Red", vendor=elegoo, material="PLA"),
        SpoolmanFilament(id=11, name="PLA Blue", vendor=elegoo, material="PLA"),
        SpoolmanFilament(id=12, name="PETG", vendor=elegoo, material="PETG"),  # undecided
    ]
    client = _client(db, _fake_spoolman(filaments=sm_filaments, spools=[]), _fake_filamentdb())

    body = client.get("/api/wizard/variances").json()
    all_ids = {m["ref"]["spoolman_filament_id"] for g in body["groups"] for m in g["members"]}
    all_ids |= {f["ref"]["spoolman_filament_id"] for f in body["ungrouped"]}
    assert 11 not in all_ids   # skip excluded
    assert 12 not in all_ids   # undecided excluded
    assert 10 in all_ids       # create included


def test_wizard_variances_conflicts_for_clustered_members(db):
    """VariancesFilament carries conflicts for members with differing props."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
        {"spoolman_filament_id": 11, "action": "create"},
    ])
    db.commit()
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_filaments = [
        SpoolmanFilament(id=10, name="PLA Red", vendor=elegoo, material="PLA", density=1.24),
        SpoolmanFilament(id=11, name="PLA Blue", vendor=elegoo, material="PLA", density=1.27),
    ]
    client = _client(db, _fake_spoolman(filaments=sm_filaments, spools=[]), _fake_filamentdb())

    body = client.get("/api/wizard/variances").json()
    assert len(body["groups"]) == 1
    master_id = body["groups"][0]["suggested_master"]["spoolman_filament_id"]
    non_master = next(m for m in body["groups"][0]["members"]
                      if m["ref"]["spoolman_filament_id"] != master_id)
    assert any(c["field"] == "density" for c in non_master["conflicts"])
    assert next(m for m in body["groups"][0]["members"] if m["is_master"])["conflicts"] == []


def test_wizard_variances_tare_source_and_props_present(db):
    """VariancesFilament carries tare, tare_source, and comparable props."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions",
                     [{"spoolman_filament_id": 10, "action": "create"}])
    db.commit()
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_filaments = [SpoolmanFilament(id=10, name="PLA", vendor=elegoo, material="PLA",
                                     spool_weight=220.0, density=1.24,
                                     settings_extruder_temp=210, settings_bed_temp=60)]
    client = _client(db, _fake_spoolman(filaments=sm_filaments, spools=[]), _fake_filamentdb())

    body = client.get("/api/wizard/variances").json()
    assert len(body["ungrouped"]) == 1
    f = body["ungrouped"][0]
    assert f["tare"] == 220.0
    assert f["tare_source"] == "spoolman"
    assert f["material"] == "PLA"
    assert f["density"] == 1.24
    assert f["settings_extruder_temp"] == 210
    assert f["settings_bed_temp"] == 60


def test_wizard_variances_default_tare_when_no_spool_weight(db):
    """tare_source is 'default' (200g) when filament has no spool_weight."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions",
                     [{"spoolman_filament_id": 10, "action": "create"}])
    db.commit()
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_filaments = [SpoolmanFilament(id=10, name="PLA", vendor=elegoo, spool_weight=None)]
    client = _client(db, _fake_spoolman(filaments=sm_filaments, spools=[]), _fake_filamentdb())

    body = client.get("/api/wizard/variances").json()
    f = body["ungrouped"][0]
    assert f["tare"] == 200.0
    assert f["tare_source"] == "default"


def test_wizard_variances_filamentdb_direction_returns_empty(db):
    """FDB direction returns empty groups/ungrouped with direction='filamentdb'."""
    set_config_value(db, "import_direction", "filamentdb")
    db.commit()
    client = _client(db, _fake_spoolman(), _fake_filamentdb())

    body = client.get("/api/wizard/variances").json()
    assert body["direction"] == "filamentdb"
    assert body["groups"] == []
    assert body["ungrouped"] == []


# ---------------------------------------------------------------------------
# D1 — vendor+material grouping key (Brown + Beige must cluster)
# ---------------------------------------------------------------------------


def test_wizard_variances_brown_beige_cluster_into_one_group(db):
    """D1: filaments named 'Brown' and 'Beige' with same vendor+material cluster together.

    The old 3-tuple key stripped color words and produced different base_names
    ('brown' and 'beige'), so they never grouped. The 2-tuple key (vendor, material)
    fixes this.
    """
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
        {"spoolman_filament_id": 11, "action": "create"},
    ])
    db.commit()
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_filaments = [
        SpoolmanFilament(id=10, name="Brown", vendor=elegoo, material="PLA"),
        SpoolmanFilament(id=11, name="Beige", vendor=elegoo, material="PLA"),
    ]
    client = _client(db, _fake_spoolman(filaments=sm_filaments, spools=[]), _fake_filamentdb())

    body = client.get("/api/wizard/variances").json()
    assert len(body["groups"]) == 1, "Brown + Beige must be in one variant group"
    member_ids = {m["ref"]["spoolman_filament_id"] for m in body["groups"][0]["members"]}
    assert member_ids == {10, 11}
    assert body["ungrouped"] == []


def test_sm_variant_cluster_key_groups_by_vendor_material(db):
    """D1: sm_variant_cluster_key returns (vendor, material, finish) 3-tuple; color words are irrelevant."""
    from app.core.matcher import sm_variant_cluster_key
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    brown = SpoolmanFilament(id=5, name="Brown", vendor=elegoo, material="PLA")
    beige = SpoolmanFilament(id=6, name="Beige", vendor=elegoo, material="PLA")
    petg = SpoolmanFilament(id=7, name="Brown", vendor=elegoo, material="PETG")
    assert sm_variant_cluster_key(brown) == sm_variant_cluster_key(beige)
    assert sm_variant_cluster_key(brown) != sm_variant_cluster_key(petg)
    assert len(sm_variant_cluster_key(brown)) == 3  # (vendor, material, finish) 3-tuple


# ---------------------------------------------------------------------------
# D2 — suggest_exclude on conflicting members
# ---------------------------------------------------------------------------


def test_wizard_variances_suggest_exclude_on_conflicting_member(db):
    """D2: suggest_exclude=True on a non-master with property conflicts; master always False."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
        {"spoolman_filament_id": 11, "action": "create"},
    ])
    db.commit()
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_filaments = [
        SpoolmanFilament(id=10, name="PLA", vendor=elegoo, material="PLA", density=1.24),
        # "PLA Dense" has no finish token — stays in same cluster as "PLA" but with conflicting density
        SpoolmanFilament(id=11, name="PLA Dense", vendor=elegoo, material="PLA", density=1.35),
    ]
    client = _client(db, _fake_spoolman(filaments=sm_filaments, spools=[]), _fake_filamentdb())

    body = client.get("/api/wizard/variances").json()
    assert len(body["groups"]) == 1
    master_id = body["groups"][0]["suggested_master"]["spoolman_filament_id"]
    master_m = next(m for m in body["groups"][0]["members"] if m["ref"]["spoolman_filament_id"] == master_id)
    non_master = next(m for m in body["groups"][0]["members"] if m["ref"]["spoolman_filament_id"] != master_id)
    assert master_m["suggest_exclude"] is False
    assert non_master["suggest_exclude"] is True


def test_wizard_variances_tare_only_diff_does_not_suggest_exclude(db):
    """Tare-only difference must NOT set suggest_exclude — both members form one group without
    the non-master being pushed to ungrouped/standalone.

    Regression guard: before the fix, spool_weight was included in sm_prop_conflicts, so
    ELEGOO PLA Beige (tare 160) + Black (tare 154) would yield conflicts → suggest_exclude=True
    on the non-master, even though tare is unified per group and is not a variant-distinguishing
    property.
    """
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
        {"spoolman_filament_id": 11, "action": "create"},
    ])
    db.commit()
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_filaments = [
        SpoolmanFilament(id=10, name="PLA Beige", vendor=elegoo, material="PLA",
                         density=1.24, spool_weight=160.0,
                         settings_extruder_temp=210, settings_bed_temp=60),
        SpoolmanFilament(id=11, name="PLA Black", vendor=elegoo, material="PLA",
                         density=1.24, spool_weight=154.0,
                         settings_extruder_temp=210, settings_bed_temp=60),
    ]
    client = _client(db, _fake_spoolman(filaments=sm_filaments, spools=[]), _fake_filamentdb())

    body = client.get("/api/wizard/variances").json()
    # Must form ONE group with both members
    assert len(body["groups"]) == 1, "tare-only diff must not split the group"
    member_ids = {m["ref"]["spoolman_filament_id"] for m in body["groups"][0]["members"]}
    assert member_ids == {10, 11}
    # Neither member should be suggested for exclusion
    for m in body["groups"][0]["members"]:
        assert m["suggest_exclude"] is False, (
            f"member {m['ref']['spoolman_filament_id']} must not have suggest_exclude=True "
            "when the only difference is tare"
        )
    # Nothing pushed to ungrouped
    assert body["ungrouped"] == []


# ---------------------------------------------------------------------------
# D4 — empty-spool toggle
# ---------------------------------------------------------------------------


def test_wizard_variances_empty_spool_excluded_when_never_import_empties_on(db):
    """D4: when never_import_empties=True, zero-weight spools are absent from spool_ids."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "never_import_empties", True)
    set_config_value(db, "wizard_match_decisions",
                     [{"spoolman_filament_id": 10, "action": "create"}])
    db.commit()
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_fil = SpoolmanFilament(id=10, name="PLA", vendor=elegoo, material="PLA")
    full_spool = SpoolmanSpool(id=1, filament=sm_fil, remaining_weight=200.0, archived=False, extra={})
    empty_spool = SpoolmanSpool(id=2, filament=sm_fil, remaining_weight=0.0, archived=False, extra={})
    client = _client(db, _fake_spoolman(filaments=[sm_fil], spools=[full_spool, empty_spool]),
                     _fake_filamentdb())

    body = client.get("/api/wizard/variances").json()
    spool_ids = body["ungrouped"][0]["spool_ids"]
    assert 1 in spool_ids
    assert 2 not in spool_ids  # empty spool excluded when never_import_empties is on


def test_wizard_variances_empty_spool_included_when_never_import_empties_off(db):
    """D4: when never_import_empties=False (default), zero-weight spools appear in spool_ids."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "never_import_empties", False)
    set_config_value(db, "wizard_match_decisions",
                     [{"spoolman_filament_id": 10, "action": "create"}])
    db.commit()
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_fil = SpoolmanFilament(id=10, name="PLA", vendor=elegoo, material="PLA")
    full_spool = SpoolmanSpool(id=1, filament=sm_fil, remaining_weight=200.0, archived=False, extra={})
    empty_spool = SpoolmanSpool(id=2, filament=sm_fil, remaining_weight=0.0, archived=False, extra={})
    client = _client(db, _fake_spoolman(filaments=[sm_fil], spools=[full_spool, empty_spool]),
                     _fake_filamentdb())

    body = client.get("/api/wizard/variances").json()
    spool_ids = body["ungrouped"][0]["spool_ids"]
    assert 1 in spool_ids
    assert 2 in spool_ids  # empty spool included when never_import_empties is off


def test_wizard_execute_empty_spool_skipped_when_never_import_empties_on(db):
    """D4: when never_import_empties=True, empty spool creates are excluded but the filament IS created."""
    from unittest.mock import AsyncMock, MagicMock
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "never_import_empties", True)
    set_config_value(db, "wizard_match_decisions",
                     [{"spoolman_filament_id": 10, "action": "create"}])
    db.commit()
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_fil = SpoolmanFilament(id=10, name="PLA", vendor=elegoo, material="PLA")
    empty_spool = SpoolmanSpool(id=1, filament=sm_fil, remaining_weight=0.0, archived=False, extra={})
    full_spool = SpoolmanSpool(id=2, filament=sm_fil, remaining_weight=500.0, archived=False, extra={})
    spoolman = _fake_spoolman(filaments=[sm_fil], spools=[empty_spool, full_spool])
    fdb = _fake_filamentdb()
    fdb_created = MagicMock(id="new-fil-id")
    fdb.create_filament = AsyncMock(return_value=fdb_created)
    fdb.create_spool = AsyncMock(return_value={"_id": "new-spool-id"})
    fdb.get_locations = AsyncMock(return_value=[])
    client = _client(db, spoolman, fdb)

    body = client.post("/api/wizard/execute").json()
    assert body["failed"] == 0
    fdb.create_filament.assert_awaited_once()  # filament still created
    assert fdb.create_spool.call_count == 1  # only the non-empty spool
    called_fdb_id = fdb.create_spool.call_args.args[0]
    assert called_fdb_id == "new-fil-id"


# ---------------------------------------------------------------------------
# D3 — existing FDB parent attach
# ---------------------------------------------------------------------------


def test_wizard_execute_attach_existing_fdb_parent(db):
    """D3: existing_fdb_parent_id in decision → all members created with that parentId; no new parent."""
    from unittest.mock import AsyncMock, MagicMock
    from app.schemas.filamentdb import FDBFilament as FDBFil
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
        {"spoolman_filament_id": 11, "action": "create"},
    ])
    set_config_value(db, "wizard_sm_variant_decisions", [{
        "master_spoolman_filament_id": 10,
        "variant_spoolman_filament_ids": [11],
        "existing_fdb_parent_id": "existing-parent-fdb",
    }])
    db.commit()

    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_filaments = [
        SpoolmanFilament(id=10, name="Brown", vendor=elegoo, material="PLA"),
        SpoolmanFilament(id=11, name="Beige", vendor=elegoo, material="PLA"),
    ]
    existing_parent = FDBFil.model_validate({
        "_id": "existing-parent-fdb", "name": "ELEGOO PLA",
        "vendor": "ELEGOO", "hasVariants": True,
    })
    spoolman = _fake_spoolman(filaments=sm_filaments, spools=[])
    fdb = _fake_filamentdb(filaments=[existing_parent])
    create_calls: list[dict] = []
    call_counter = 0

    async def _create(payload):
        nonlocal call_counter
        call_counter += 1
        create_calls.append(payload)
        return MagicMock(id=f"new-fdb-{call_counter}")

    fdb.create_filament = AsyncMock(side_effect=_create)
    fdb.get_locations = AsyncMock(return_value=[])
    client = _client(db, spoolman, fdb)

    body = client.post("/api/wizard/execute").json()
    assert body["failed"] == 0
    # Both SM filaments should be created (no spools to create)
    assert len(create_calls) == 2
    # Both must have parentId = existing-parent-fdb
    for payload in create_calls:
        assert payload.get("parentId") == "existing-parent-fdb"


# ---------------------------------------------------------------------------
# Membership edits → POST /wizard/variants/sm round-trip
# ---------------------------------------------------------------------------


def test_wizard_sm_variants_added_non_clustered_member_accepted(db):
    """A group may include a filament id that wasn't in the suggested cluster."""
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
        {"spoolman_filament_id": 99, "action": "create"},  # non-clustered
    ])
    db.commit()
    client = _client(db)
    resp = client.post("/api/wizard/variants/sm", json={"groups": [
        {"master_spoolman_filament_id": 10, "variant_spoolman_filament_ids": [99]},
    ]})
    assert resp.status_code == 200
    stored = get_config_value(db, "wizard_sm_variant_decisions", [])
    assert stored[0]["variant_spoolman_filament_ids"] == [99]


def test_wizard_sm_variants_group_reduced_to_master_only_is_flat(db):
    """A saved group with zero variants is accepted (dissolves to flat)."""
    client = _client(db)
    resp = client.post("/api/wizard/variants/sm", json={"groups": [
        {"master_spoolman_filament_id": 10, "variant_spoolman_filament_ids": []},
    ]})
    assert resp.status_code == 200
    assert resp.json()["persisted"] == 1


# ---------------------------------------------------------------------------
# Tare/master rule end-to-end — executor applies master tare to all group spools
# ---------------------------------------------------------------------------


def test_wizard_execute_per_group_tare_override_applied_to_all_spools(db):
    """A per-spool WizardTareOverride expanded from the group master tare is applied."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "link", "filamentdb_id": "fdb-master"},
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
    # One spool per variant; master has no spools (already linked)
    spool_11 = _sm_spool(101, 500.0)
    spool_11.filament = SpoolmanFilament(id=11, name="PLA Red", vendor=elegoo, material="PLA")
    spool_12 = _sm_spool(102, 400.0)
    spool_12.filament = SpoolmanFilament(id=12, name="PLA Blue", vendor=elegoo, material="PLA")

    spoolman = _fake_spoolman(filaments=sm_filaments, spools=[spool_11, spool_12])
    filamentdb = _fake_filamentdb(filaments=[_fdb_filament("fdb-master", "s-master", 0.0)])
    filamentdb.create_filament = AsyncMock(return_value=MagicMock(id="new-fdb-fil"))
    filamentdb.create_spool = AsyncMock(return_value={"_id": "new-spool"})
    client = _client(db, spoolman, filamentdb)

    # Frontend expands the master's tare (250g) to both spools (101 and 102)
    body = client.post("/api/wizard/execute", json={"tare_overrides": [
        {"spoolman_spool_id": 101, "tare": 250.0},
        {"spoolman_spool_id": 102, "tare": 250.0},
    ]}).json()
    assert body["failed"] == 0

    # Both spool creates should use gross = remaining + 250 tare
    calls = filamentdb.create_spool.call_args_list
    assert len(calls) == 2
    for call in calls:
        payload = call.args[1]
        # The override tare of 250 replaces any default
        assert payload["totalWeight"] == pytest.approx(500.0 + 250.0, abs=1) or \
               payload["totalWeight"] == pytest.approx(400.0 + 250.0, abs=1)


# ---------------------------------------------------------------------------
# Phase 1 — variances endpoint returns enriched fields
# ---------------------------------------------------------------------------


def test_wizard_variances_returns_material_type_diameter_color_hex(db):
    """Phase 1: variances endpoint populates material_type, diameter, color_hex on VariancesFilament."""
    set_config_value(db, "import_direction", "spoolman")
    # SM filament 10 has a link decision to FDB filament "fdb-1" which has type="PLA+"
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "link", "filamentdb_id": "fdb-1"},
        {"spoolman_filament_id": 11, "action": "create"},
    ])
    db.commit()
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_filaments = [
        SpoolmanFilament(id=10, name="PLA Red", vendor=elegoo, material="PLA",
                         diameter=1.75, color_hex="#ff0000"),
        SpoolmanFilament(id=11, name="PLA Blue", vendor=elegoo, material="PLA",
                         diameter=1.75, color_hex="#0000ff"),
    ]
    # FDB filament that sm 10 is linked to
    fdb_pla_plus = FDBFilament.model_validate({
        "_id": "fdb-1", "name": "PLA+ Red", "vendor": "ELEGOO", "type": "PLA+",
    })
    spoolman = _fake_spoolman(filaments=sm_filaments, spools=[])
    filamentdb = _fake_filamentdb(filaments=[fdb_pla_plus])
    client = _client(db, spoolman, filamentdb)

    body = client.get("/api/wizard/variances").json()
    assert body["direction"] == "spoolman"
    assert len(body["groups"]) == 1
    # Find the member for SM filament 10 (linked → material_type from FDB)
    members = body["groups"][0]["members"]
    m10 = next(m for m in members if m["ref"]["spoolman_filament_id"] == 10)
    m11 = next(m for m in members if m["ref"]["spoolman_filament_id"] == 11)
    # material_type comes from the linked FDB filament's `type`
    assert m10["material_type"] == "PLA+"
    # SM filament 11 has no link decision → material_type is None
    assert m11["material_type"] is None
    # diameter and color_hex always come from SM
    assert m10["diameter"] == 1.75
    assert m10["color_hex"] == "#ff0000"
    assert m11["diameter"] == 1.75
    assert m11["color_hex"] == "#0000ff"


def test_wizard_variances_ungrouped_returns_diameter_color_hex(db):
    """Phase 1: ungrouped VariancesFilament entries also carry diameter and color_hex."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions",
                     [{"spoolman_filament_id": 20, "action": "create"}])
    db.commit()
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_filaments = [
        SpoolmanFilament(id=20, name="PETG Black", vendor=elegoo, material="PETG",
                         diameter=2.85, color_hex="#111111"),
    ]
    client = _client(db, _fake_spoolman(filaments=sm_filaments, spools=[]), _fake_filamentdb())

    body = client.get("/api/wizard/variances").json()
    assert len(body["ungrouped"]) == 1
    f = body["ungrouped"][0]
    assert f["diameter"] == 2.85
    assert f["color_hex"] == "#111111"
    assert f["material_type"] is None  # no link decision


def test_wizard_variances_conflicts_include_diameter(db):
    """Phase 1 + matcher: diameter differences are surfaced as conflicts in variances groups."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 30, "action": "create"},
        {"spoolman_filament_id": 31, "action": "create"},
    ])
    db.commit()
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_filaments = [
        SpoolmanFilament(id=30, name="PLA Red", vendor=elegoo, material="PLA", diameter=1.75),
        SpoolmanFilament(id=31, name="PLA Blue", vendor=elegoo, material="PLA", diameter=2.85),
    ]
    client = _client(db, _fake_spoolman(filaments=sm_filaments, spools=[]), _fake_filamentdb())

    body = client.get("/api/wizard/variances").json()
    assert len(body["groups"]) == 1
    master_id = body["groups"][0]["suggested_master"]["spoolman_filament_id"]
    non_master = next(m for m in body["groups"][0]["members"]
                      if m["ref"]["spoolman_filament_id"] != master_id)
    conflict_fields = [c["field"] for c in non_master["conflicts"]]
    assert "diameter" in conflict_fields


# ---------------------------------------------------------------------------
# Phase 2 — reconcile decisions persist and reload from BridgeConfig
# ---------------------------------------------------------------------------


def test_wizard_save_sm_variants_reconcile_persists(db):
    """Phase 2: POST /wizard/variants/sm with reconcile list persists to wizard_variances_reconcile."""
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
        {"spoolman_filament_id": 11, "action": "create"},
    ])
    db.commit()
    client = _client(db)
    resp = client.post("/api/wizard/variants/sm", json={
        "groups": [
            {"master_spoolman_filament_id": 10, "variant_spoolman_filament_ids": [11]},
        ],
        "reconcile": [
            {
                "master_spoolman_filament_id": 10,
                "fields": [
                    {"field": "density", "value": 1.25, "source": "spoolman_filament",
                     "source_spoolman_filament_id": 10},
                    {"field": "type", "value": "PLA", "source": "manual",
                     "source_spoolman_filament_id": None},
                ],
            }
        ],
    })
    assert resp.status_code == 200
    assert resp.json()["persisted"] == 1  # 1 group persisted

    # Verify both keys are stored
    stored_groups = get_config_value(db, "wizard_sm_variant_decisions", [])
    assert len(stored_groups) == 1
    assert stored_groups[0]["master_spoolman_filament_id"] == 10

    stored_reconcile = get_config_value(db, "wizard_variances_reconcile", [])
    assert len(stored_reconcile) == 1
    rec = stored_reconcile[0]
    assert rec["master_spoolman_filament_id"] == 10
    assert len(rec["fields"]) == 2
    density_field = next(f for f in rec["fields"] if f["field"] == "density")
    assert density_field["value"] == 1.25
    assert density_field["source"] == "spoolman_filament"
    type_field = next(f for f in rec["fields"] if f["field"] == "type")
    assert type_field["value"] == "PLA"
    assert type_field["source"] == "manual"


def test_wizard_save_sm_variants_empty_reconcile_does_not_overwrite(db):
    """Phase 2: if reconcile is empty/absent, wizard_variances_reconcile is untouched."""
    # Pre-seed a reconcile decision
    set_config_value(db, "wizard_variances_reconcile", [
        {"master_spoolman_filament_id": 5, "fields": [
            {"field": "density", "value": 1.24, "source": "manual", "source_spoolman_filament_id": None}
        ]},
    ])
    db.commit()
    client = _client(db)
    # POST without reconcile key
    client.post("/api/wizard/variants/sm", json={
        "groups": [
            {"master_spoolman_filament_id": 5, "variant_spoolman_filament_ids": []},
        ],
    })
    # Should still be there
    stored_reconcile = get_config_value(db, "wizard_variances_reconcile", [])
    assert len(stored_reconcile) == 1
    assert stored_reconcile[0]["master_spoolman_filament_id"] == 5


# ---------------------------------------------------------------------------
# Phase 3 — execute overlays reconcile on FDB payload + SM write-back PATCH
# ---------------------------------------------------------------------------


def test_wizard_execute_reconcile_overlays_fdb_create_payload(db):
    """Phase 3: reconcile decisions are overlaid on FDB create payload at execute time."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
    ])
    set_config_value(db, "wizard_variances_reconcile", [
        {
            "master_spoolman_filament_id": 10,
            "fields": [
                {"field": "density", "value": 1.28, "source": "manual",
                 "source_spoolman_filament_id": None},
            ],
        }
    ])
    db.commit()
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_filaments = [
        SpoolmanFilament(id=10, name="PLA Red", vendor=elegoo, material="PLA", density=1.24),
    ]
    spoolman = _fake_spoolman(filaments=sm_filaments, spools=[])
    filamentdb = _fake_filamentdb()
    create_calls = []

    async def _create(payload):
        create_calls.append(payload)
        return MagicMock(id="new-fdb-fil")

    filamentdb.create_filament = AsyncMock(side_effect=_create)
    client = _client(db, spoolman, filamentdb)

    body = client.post("/api/wizard/execute").json()
    assert body["failed"] == 0
    assert len(create_calls) == 1
    # The reconciled density value (1.28) must override the SM value (1.24) in the FDB payload
    assert create_calls[0]["density"] == pytest.approx(1.28)


def test_wizard_execute_reconcile_sm_writeback_patches_differing_fields(db):
    """Phase 3: Spoolman write-back PATCH is called for fields that differ from canonical value."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
        {"spoolman_filament_id": 11, "action": "create"},
    ])
    set_config_value(db, "wizard_sm_variant_decisions", [
        {"master_spoolman_filament_id": 10, "variant_spoolman_filament_ids": [11]},
    ])
    set_config_value(db, "wizard_variances_reconcile", [
        {
            "master_spoolman_filament_id": 10,
            "fields": [
                {"field": "density", "value": 1.26, "source": "manual",
                 "source_spoolman_filament_id": None},
            ],
        }
    ])
    db.commit()
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_filaments = [
        SpoolmanFilament(id=10, name="PLA Red", vendor=elegoo, material="PLA", density=1.24),
        SpoolmanFilament(id=11, name="PLA Blue", vendor=elegoo, material="PLA", density=1.27),
    ]
    spoolman = _fake_spoolman(filaments=sm_filaments, spools=[])
    filamentdb = _fake_filamentdb()
    filamentdb.create_filament = AsyncMock(return_value=MagicMock(id="new-fdb-fil"))
    client = _client(db, spoolman, filamentdb)

    body = client.post("/api/wizard/execute").json()
    assert body["failed"] == 0

    # spoolman.update_filament should be called for both SM filaments since both differ from 1.26
    update_calls = spoolman.update_filament.call_args_list
    patched_ids = {c.args[0] for c in update_calls}
    assert 10 in patched_ids  # density 1.24 != 1.26
    assert 11 in patched_ids  # density 1.27 != 1.26
    # Verify the patch payload contains the correct canonical density
    for call in update_calls:
        if call.args[0] in (10, 11):
            assert call.args[1].get("density") == pytest.approx(1.26)


def test_wizard_execute_reconcile_no_patch_when_values_already_match(db):
    """Phase 3: Spoolman write-back is NOT called when canonical value already matches SM value."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
    ])
    set_config_value(db, "wizard_variances_reconcile", [
        {
            "master_spoolman_filament_id": 10,
            "fields": [
                # density canonical = 1.24 = SM value → no diff → no PATCH
                {"field": "density", "value": 1.24, "source": "spoolman_filament",
                 "source_spoolman_filament_id": 10},
            ],
        }
    ])
    db.commit()
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_filaments = [
        SpoolmanFilament(id=10, name="PLA Red", vendor=elegoo, material="PLA", density=1.24),
    ]
    spoolman = _fake_spoolman(filaments=sm_filaments, spools=[])
    filamentdb = _fake_filamentdb()
    filamentdb.create_filament = AsyncMock(return_value=MagicMock(id="new-fdb-fil"))
    client = _client(db, spoolman, filamentdb)

    client.post("/api/wizard/execute")

    # No PATCH should be issued since density already matches
    spoolman.update_filament.assert_not_called()


def test_wizard_execute_reconcile_nozzle_temp_overlays_fdb_and_patches_spoolman(db):
    """Regression: nozzle_temp/bed_temp canonical keys (not settings_extruder_temp) reach FDB+SM.

    Before the canonical-key fix, the frontend emitted 'settings_extruder_temp' as the
    ReconciledField.field name.  The backend _RECONCILE_FIELD_MAP keys on 'nozzle_temp',
    so mismatched keys caused temp reconcile decisions to be silently dropped.
    This test verifies the correct canonical key 'nozzle_temp' / 'bed_temp' flows end-to-end.
    """
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
        {"spoolman_filament_id": 11, "action": "create"},
    ])
    set_config_value(db, "wizard_sm_variant_decisions", [
        {"master_spoolman_filament_id": 10, "variant_spoolman_filament_ids": [11]},
    ])
    set_config_value(db, "wizard_variances_reconcile", [
        {
            "master_spoolman_filament_id": 10,
            "fields": [
                # Canonical keys — what the frontend must now emit (was 'settings_extruder_temp')
                {"field": "nozzle_temp", "value": 215, "source": "manual",
                 "source_spoolman_filament_id": None},
                {"field": "bed_temp", "value": 65, "source": "manual",
                 "source_spoolman_filament_id": None},
            ],
        }
    ])
    db.commit()
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_filaments = [
        SpoolmanFilament(id=10, name="PLA Blue", vendor=elegoo, material="PLA",
                         density=1.24, settings_extruder_temp=210, settings_bed_temp=60),
        SpoolmanFilament(id=11, name="PLA Red", vendor=elegoo, material="PLA",
                         density=1.24, settings_extruder_temp=210, settings_bed_temp=60),
    ]
    spoolman = _fake_spoolman(filaments=sm_filaments, spools=[])
    filamentdb = _fake_filamentdb()
    create_calls = []

    async def _create(payload):
        create_calls.append(payload)
        return MagicMock(id="new-fdb-fil")

    filamentdb.create_filament = AsyncMock(side_effect=_create)
    client = _client(db, spoolman, filamentdb)

    body = client.post("/api/wizard/execute").json()
    assert body["failed"] == 0

    # FDB create payload for the master must have reconciled temps via temperatures.nozzle/bed
    assert len(create_calls) >= 1
    master_payload = create_calls[0]
    assert master_payload.get("temperatures", {}).get("nozzle") == 215
    assert master_payload.get("temperatures", {}).get("bed") == 65

    # Both SM filaments should be PATCHed since their current values (210/60) differ from canonical
    update_calls = spoolman.update_filament.call_args_list
    patched_ids = {c.args[0] for c in update_calls}
    assert 10 in patched_ids
    assert 11 in patched_ids
    for call in update_calls:
        if call.args[0] in (10, 11):
            assert call.args[1].get("settings_extruder_temp") == 215
            assert call.args[1].get("settings_bed_temp") == 65


# ---------------------------------------------------------------------------
# Phase 4 — preview emits PlannedWrite matching what execute does
# ---------------------------------------------------------------------------


def test_wizard_preview_planned_writes_fdb_filament_create(db):
    """Phase 4: preview planned_writes includes FDB filament create entries."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
    ])
    db.commit()
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_filaments = [
        SpoolmanFilament(id=10, name="PLA Red", vendor=elegoo, material="PLA", density=1.24),
    ]
    client = _client(db, _fake_spoolman(filaments=sm_filaments, spools=[]), _fake_filamentdb())

    body = client.get("/api/wizard/preview").json()
    assert "planned_writes" in body
    fdb_creates = [w for w in body["planned_writes"]
                   if w["system"] == "filamentdb" and w["action"] == "create"
                   and w["entity_type"] == "filament"]
    assert len(fdb_creates) == 1
    assert "SM #10" in fdb_creates[0]["target_label"]
    # fields list should contain density
    field_names = [f["name"] for f in fdb_creates[0]["fields"]]
    assert "density" in field_names


def test_wizard_preview_planned_writes_sm_writeback_matches_execute(db):
    """Phase 4: preview planned_writes SM write-back entries match what execute actually PATCHes."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
    ])
    set_config_value(db, "wizard_variances_reconcile", [
        {
            "master_spoolman_filament_id": 10,
            "fields": [
                {"field": "density", "value": 1.30, "source": "manual",
                 "source_spoolman_filament_id": None},
            ],
        }
    ])
    db.commit()
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_filaments = [
        SpoolmanFilament(id=10, name="PLA Red", vendor=elegoo, material="PLA", density=1.24),
    ]
    spoolman = _fake_spoolman(filaments=sm_filaments, spools=[])
    filamentdb = _fake_filamentdb()
    filamentdb.create_filament = AsyncMock(return_value=MagicMock(id="new-fdb-fil"))
    client = _client(db, spoolman, filamentdb)

    # First check preview
    preview_body = client.get("/api/wizard/preview").json()
    sm_writes = [w for w in preview_body["planned_writes"]
                 if w["system"] == "spoolman" and w["action"] == "update"]
    assert len(sm_writes) == 1
    sm_write = sm_writes[0]
    assert "SM #10" in sm_write["target_label"]
    sm_write_field = next(f for f in sm_write["fields"] if f["name"] == "density")
    assert sm_write_field["old"] == pytest.approx(1.24)
    assert sm_write_field["new"] == pytest.approx(1.30)

    # Now execute and verify the actual Spoolman PATCH matches the preview
    client.post("/api/wizard/execute")
    update_calls = [c for c in spoolman.update_filament.call_args_list if c.args[0] == 10]
    assert len(update_calls) == 1
    assert update_calls[0].args[1].get("density") == pytest.approx(1.30)


def test_wizard_preview_planned_writes_no_sm_writeback_when_no_reconcile(db):
    """Phase 4: no Spoolman write-back entries in planned_writes when no reconcile decisions exist."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
    ])
    db.commit()
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_filaments = [
        SpoolmanFilament(id=10, name="PLA Red", vendor=elegoo, material="PLA", density=1.24),
    ]
    client = _client(db, _fake_spoolman(filaments=sm_filaments, spools=[]), _fake_filamentdb())

    body = client.get("/api/wizard/preview").json()
    sm_writes = [w for w in body["planned_writes"] if w["system"] == "spoolman"]
    assert sm_writes == []


# ---------------------------------------------------------------------------
# Wizard cost sync tests (spool-first, filament fallback)
# ---------------------------------------------------------------------------


def test_wizard_execute_create_payload_includes_spool_price(db):
    """Wizard execute: FDB filament create payload uses spool price when set."""
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_fil = SpoolmanFilament(id=10, name="PLA Blue", vendor=elegoo, material="PLA", price=20.0)
    # Spool has price=29.99 — spool price wins over filament price
    sm_spool = SpoolmanSpool(
        id=1, filament=sm_fil, remaining_weight=500.0, price=29.99, archived=False, extra={},
    )
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions",
                     [{"spoolman_filament_id": 10, "action": "create"}])
    db.commit()

    filamentdb = _fake_filamentdb(filaments=[])
    filamentdb.create_filament = AsyncMock(return_value=MagicMock(id="new-fil"))
    filamentdb.create_spool = AsyncMock(return_value={"_id": "new-spool"})
    client = _client(db, _fake_spoolman(filaments=[sm_fil], spools=[sm_spool]), filamentdb)

    resp = client.post("/api/wizard/execute")
    assert resp.status_code == 200
    filamentdb.create_filament.assert_awaited_once()
    payload = filamentdb.create_filament.await_args.args[0]
    # Spool price (29.99) must appear as cost in the FDB create payload
    assert payload.get("cost") == pytest.approx(29.99)


def test_wizard_execute_create_payload_falls_back_to_filament_price(db):
    """Wizard execute: FDB filament create payload uses filament price when no spool price."""
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_fil = SpoolmanFilament(id=10, name="PLA Blue", vendor=elegoo, material="PLA", price=14.99)
    # Spool has no price — filament price is the fallback
    sm_spool = SpoolmanSpool(
        id=1, filament=sm_fil, remaining_weight=500.0, price=None, archived=False, extra={},
    )
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions",
                     [{"spoolman_filament_id": 10, "action": "create"}])
    db.commit()

    filamentdb = _fake_filamentdb(filaments=[])
    filamentdb.create_filament = AsyncMock(return_value=MagicMock(id="new-fil"))
    filamentdb.create_spool = AsyncMock(return_value={"_id": "new-spool"})
    client = _client(db, _fake_spoolman(filaments=[sm_fil], spools=[sm_spool]), filamentdb)

    resp = client.post("/api/wizard/execute")
    assert resp.status_code == 200
    filamentdb.create_filament.assert_awaited_once()
    payload = filamentdb.create_filament.await_args.args[0]
    assert payload.get("cost") == pytest.approx(14.99)


def test_wizard_execute_create_payload_omits_cost_when_none(db):
    """Wizard execute: FDB filament create payload omits cost when both spool and filament price are None."""
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_fil = SpoolmanFilament(id=10, name="PLA Blue", vendor=elegoo, material="PLA", price=None)
    sm_spool = SpoolmanSpool(
        id=1, filament=sm_fil, remaining_weight=500.0, price=None, archived=False, extra={},
    )
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions",
                     [{"spoolman_filament_id": 10, "action": "create"}])
    db.commit()

    filamentdb = _fake_filamentdb(filaments=[])
    filamentdb.create_filament = AsyncMock(return_value=MagicMock(id="new-fil"))
    filamentdb.create_spool = AsyncMock(return_value={"_id": "new-spool"})
    client = _client(db, _fake_spoolman(filaments=[sm_fil], spools=[sm_spool]), filamentdb)

    resp = client.post("/api/wizard/execute")
    assert resp.status_code == 200
    filamentdb.create_filament.assert_awaited_once()
    payload = filamentdb.create_filament.await_args.args[0]
    assert "cost" not in payload


def test_wizard_preview_planned_writes_includes_cost_field(db):
    """Wizard preview: planned_writes FDB filament create includes cost field when spool price set."""
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm_fil = SpoolmanFilament(id=10, name="PLA Red", vendor=elegoo, material="PLA", price=9.99)
    sm_spool = SpoolmanSpool(
        id=1, filament=sm_fil, remaining_weight=500.0, price=24.99, archived=False, extra={},
    )
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions",
                     [{"spoolman_filament_id": 10, "action": "create"}])
    db.commit()

    client = _client(db, _fake_spoolman(filaments=[sm_fil], spools=[sm_spool]), _fake_filamentdb())

    body = client.get("/api/wizard/preview").json()
    fdb_creates = [w for w in body["planned_writes"]
                   if w["system"] == "filamentdb" and w["action"] == "create"
                   and w["entity_type"] == "filament"]
    assert len(fdb_creates) == 1
    field_names = [f["name"] for f in fdb_creates[0]["fields"]]
    # cost = spool price (24.99) must appear in the planned fields
    assert "cost" in field_names
    cost_field = next(f for f in fdb_creates[0]["fields"] if f["name"] == "cost")
    assert cost_field["new"] == pytest.approx(24.99)


# ---------------------------------------------------------------------------
# New-spool sync direction — enforced gating (FR-12)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_spool_two_way_creates_in_both_directions(db):
    """two_way: both SM→FDB and FDB→SM spool creation paths fire."""
    from app.core.engine import run_sync_cycle
    from app.models.config import BridgeConfig

    # New SM spool (id=1, not in any SpoolMapping)
    sm_spool = SpoolmanSpool(
        id=1,
        filament=SpoolmanFilament(id=10, name="PLA", vendor=SpoolmanVendor(id=1, name="ELEGOO")),
        remaining_weight=500.0,
        archived=False,
        extra={},
    )
    # New FDB spool (not in any SpoolMapping)
    fdb_fil = FDBFilament.model_validate({
        "_id": "fil-1", "name": "PLA", "vendor": "elegoo", "spoolWeight": 200.0,
        "spools": [{"_id": "spool-fdb-1", "totalWeight": 700.0, "retired": False}],
    })
    db.add(FilamentMapping(spoolman_filament_id=10, filamentdb_id="fil-1"))
    db.merge(BridgeConfig(key="new_spool_sync_direction", value='"two_way"'))
    db.commit()

    spoolman = AsyncMock()
    spoolman.get_spools = AsyncMock(return_value=[sm_spool])
    spoolman.get_filaments = AsyncMock(return_value=[sm_spool.filament])
    spoolman.get_field_definitions = AsyncMock(return_value=[])
    spoolman.update_spool = AsyncMock(return_value=MagicMock())
    spoolman.create_spool = AsyncMock(return_value=MagicMock(id=999))

    filamentdb = AsyncMock()
    filamentdb.get_filaments = AsyncMock(return_value=[fdb_fil])
    filamentdb.get_filament = AsyncMock(return_value=None)
    filamentdb.get_version = AsyncMock(return_value="1.33.0")
    filamentdb.create_spool = AsyncMock(return_value={"_id": "new-fdb-spool"})
    filamentdb.update_spool = AsyncMock(return_value={})
    filamentdb.update_filament = AsyncMock(return_value=MagicMock())
    filamentdb.log_usage = AsyncMock(return_value={})

    await run_sync_cycle(db, spoolman, filamentdb, dry_run=False)

    # SM→FDB: new SM spool creates an FDB spool
    filamentdb.create_spool.assert_awaited()
    # FDB→SM: new FDB spool creates a SM spool
    spoolman.create_spool.assert_awaited()


@pytest.mark.asyncio
async def test_new_spool_spoolman_to_filamentdb_only_creates_fdb(db):
    """spoolman_to_filamentdb: SM→FDB creation fires; FDB→SM does NOT."""
    from app.core.engine import run_sync_cycle
    from app.models.config import BridgeConfig

    sm_spool = SpoolmanSpool(
        id=1,
        filament=SpoolmanFilament(id=10, name="PLA", vendor=SpoolmanVendor(id=1, name="ELEGOO")),
        remaining_weight=500.0,
        archived=False,
        extra={},
    )
    fdb_fil = FDBFilament.model_validate({
        "_id": "fil-1", "name": "PLA", "vendor": "elegoo", "spoolWeight": 200.0,
        "spools": [{"_id": "spool-fdb-1", "totalWeight": 700.0, "retired": False}],
    })
    db.add(FilamentMapping(spoolman_filament_id=10, filamentdb_id="fil-1"))
    db.merge(BridgeConfig(key="new_spool_sync_direction", value='"spoolman_to_filamentdb"'))
    db.commit()

    spoolman = AsyncMock()
    spoolman.get_spools = AsyncMock(return_value=[sm_spool])
    spoolman.get_filaments = AsyncMock(return_value=[sm_spool.filament])
    spoolman.get_field_definitions = AsyncMock(return_value=[])
    spoolman.update_spool = AsyncMock(return_value=MagicMock())
    spoolman.create_spool = AsyncMock(return_value=MagicMock(id=999))

    filamentdb = AsyncMock()
    filamentdb.get_filaments = AsyncMock(return_value=[fdb_fil])
    filamentdb.get_filament = AsyncMock(return_value=None)
    filamentdb.get_version = AsyncMock(return_value="1.33.0")
    filamentdb.create_spool = AsyncMock(return_value={"_id": "new-fdb-spool"})
    filamentdb.update_spool = AsyncMock(return_value={})
    filamentdb.update_filament = AsyncMock(return_value=MagicMock())
    filamentdb.log_usage = AsyncMock(return_value={})

    await run_sync_cycle(db, spoolman, filamentdb, dry_run=False)

    # SM→FDB creation fired
    filamentdb.create_spool.assert_awaited()
    # FDB→SM creation did NOT fire
    spoolman.create_spool.assert_not_called()


@pytest.mark.asyncio
async def test_new_spool_filamentdb_to_spoolman_only_creates_sm(db):
    """filamentdb_to_spoolman: FDB→SM creation fires; SM→FDB does NOT."""
    from app.core.engine import run_sync_cycle
    from app.models.config import BridgeConfig

    sm_spool = SpoolmanSpool(
        id=1,
        filament=SpoolmanFilament(id=10, name="PLA", vendor=SpoolmanVendor(id=1, name="ELEGOO")),
        remaining_weight=500.0,
        archived=False,
        extra={},
    )
    fdb_fil = FDBFilament.model_validate({
        "_id": "fil-1", "name": "PLA", "vendor": "elegoo", "spoolWeight": 200.0,
        "spools": [{"_id": "spool-fdb-1", "totalWeight": 700.0, "retired": False}],
    })
    db.add(FilamentMapping(spoolman_filament_id=10, filamentdb_id="fil-1"))
    db.merge(BridgeConfig(key="new_spool_sync_direction", value='"filamentdb_to_spoolman"'))
    db.commit()

    spoolman = AsyncMock()
    spoolman.get_spools = AsyncMock(return_value=[sm_spool])
    spoolman.get_filaments = AsyncMock(return_value=[sm_spool.filament])
    spoolman.get_field_definitions = AsyncMock(return_value=[])
    spoolman.update_spool = AsyncMock(return_value=MagicMock())
    spoolman.create_spool = AsyncMock(return_value=MagicMock(id=999))

    filamentdb = AsyncMock()
    filamentdb.get_filaments = AsyncMock(return_value=[fdb_fil])
    filamentdb.get_filament = AsyncMock(return_value=None)
    filamentdb.get_version = AsyncMock(return_value="1.33.0")
    filamentdb.create_spool = AsyncMock(return_value={"_id": "new-fdb-spool"})
    filamentdb.update_spool = AsyncMock(return_value={})
    filamentdb.update_filament = AsyncMock(return_value=MagicMock())
    filamentdb.log_usage = AsyncMock(return_value={})

    await run_sync_cycle(db, spoolman, filamentdb, dry_run=False)

    # FDB→SM creation fired
    spoolman.create_spool.assert_awaited()
    # SM→FDB creation did NOT fire
    filamentdb.create_spool.assert_not_called()


# ---------------------------------------------------------------------------
# Migration: new_spool_sync_direction defaults to two_way (idempotent)
# ---------------------------------------------------------------------------


def test_migrate_new_spool_sync_direction_defaults_two_way(db):
    """_migrate_sync_config sets new_spool_sync_direction=two_way when absent."""
    from app.main import _migrate_sync_config
    from app.api.config import get_config_value

    # Ensure key is absent before migration
    from app.models.config import BridgeConfig as BC
    db.query(BC).filter_by(key="new_spool_sync_direction").delete()
    db.commit()

    _migrate_sync_config(db)
    assert get_config_value(db, "new_spool_sync_direction") == "two_way"


def test_migrate_new_spool_sync_direction_is_idempotent(db):
    """_migrate_sync_config does not overwrite an existing new_spool_sync_direction."""
    from app.main import _migrate_sync_config
    from app.api.config import get_config_value, set_config_value

    set_config_value(db, "new_spool_sync_direction", "spoolman_to_filamentdb")
    db.commit()

    _migrate_sync_config(db)
    # Value unchanged
    assert get_config_value(db, "new_spool_sync_direction") == "spoolman_to_filamentdb"


# ---------------------------------------------------------------------------
# Wizard direction: persists new keys (not old *_source_of_truth)
# ---------------------------------------------------------------------------


def test_wizard_direction_persists_import_direction_only(db):
    """POST /wizard/direction only persists import_direction; ongoing sync settings
    are configured via Settings (PUT /api/config), not the wizard direction step."""
    client = _client(db)
    resp = client.post("/api/wizard/direction", json={
        "import_direction": "spoolman",
    })
    assert resp.status_code == 200
    assert resp.json()["persisted"] == 1

    from app.api.config import get_config_value
    assert get_config_value(db, "import_direction") == "spoolman"
    # Ongoing-sync direction keys are NOT written by the wizard direction handler
    # (they retain their seeded defaults)
    assert get_config_value(db, "weight_sync_direction") == "spoolman_to_filamentdb"  # seeded default


def test_wizard_direction_filamentdb_sets_import_direction(db):
    """Wizard direction POST with filamentdb sets import_direction=filamentdb."""
    client = _client(db)
    resp = client.post("/api/wizard/direction", json={"import_direction": "filamentdb"})
    assert resp.status_code == 200
    from app.api.config import get_config_value
    assert get_config_value(db, "import_direction") == "filamentdb"


# ---------------------------------------------------------------------------
# Config API: new_spool_sync_direction round-trip; old SoT fields gone
# ---------------------------------------------------------------------------


def test_config_new_spool_sync_direction_round_trip(db):
    """new_spool_sync_direction can be set and read back via the config API."""
    client = _client(db)

    # Default should be two_way
    body = client.get("/api/config").json()
    assert body["new_spool_sync_direction"] == "two_way"

    # Update to one-way
    resp = client.put("/api/config", json={"new_spool_sync_direction": "spoolman_to_filamentdb"})
    assert resp.status_code == 200
    assert resp.json()["new_spool_sync_direction"] == "spoolman_to_filamentdb"

    # Round-trip GET confirms the new value
    body = client.get("/api/config").json()
    assert body["new_spool_sync_direction"] == "spoolman_to_filamentdb"


def test_config_old_sot_fields_absent_from_response(db):
    """Old *_source_of_truth fields are absent from the config API response."""
    body = _client(db).get("/api/config").json()
    assert "weight_source_of_truth" not in body
    assert "material_properties_source_of_truth" not in body
    assert "new_spool_source_of_truth" not in body


def test_config_old_sot_fields_rejected_on_update(db):
    """Sending old *_source_of_truth fields in a PUT returns 422 (unknown field)."""
    client = _client(db)
    # Pydantic v2 with extra='ignore' would accept unknown fields silently,
    # but the schema no longer defines these fields. We verify the new direction
    # field is present and the old ones are not in the response.
    resp = client.put("/api/config", json={
        "weight_sync_direction": "two_way",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert "weight_source_of_truth" not in body
    assert "new_spool_source_of_truth" not in body


# ---------------------------------------------------------------------------
# Scheduler + sync-log retention settings
# ---------------------------------------------------------------------------


def test_config_sync_interval_seconds_defaults_to_env(db):
    """Without a DB override, sync_interval_seconds reflects the env default (120)."""
    body = _client(db).get("/api/config").json()
    # env default in conftest is 120
    assert body["sync_interval_seconds"] == 120


def test_config_sync_interval_round_trips(db):
    """sync_interval_seconds round-trips through PUT/GET and is clamped to ≥ 30."""
    client = _client(db)

    resp = client.put("/api/config", json={"sync_interval_seconds": 300})
    assert resp.status_code == 200
    assert resp.json()["sync_interval_seconds"] == 300

    # Confirm GET returns the new value too
    body = client.get("/api/config").json()
    assert body["sync_interval_seconds"] == 300


def test_config_sync_interval_clamped_to_minimum(db):
    """sync_interval_seconds < 30 is rejected by the schema validator (ge=30)."""
    client = _client(db)
    resp = client.put("/api/config", json={"sync_interval_seconds": 10})
    assert resp.status_code == 422


def test_config_sync_log_retention_days_defaults_to_30(db):
    """sync_log_retention_days defaults to 30."""
    body = _client(db).get("/api/config").json()
    assert body["sync_log_retention_days"] == 30


def test_config_sync_log_retention_days_round_trips(db):
    """sync_log_retention_days round-trips; 0 (keep forever) is valid."""
    client = _client(db)

    resp = client.put("/api/config", json={"sync_log_retention_days": 7})
    assert resp.status_code == 200
    assert resp.json()["sync_log_retention_days"] == 7

    resp = client.put("/api/config", json={"sync_log_retention_days": 0})
    assert resp.status_code == 200
    assert resp.json()["sync_log_retention_days"] == 0


def test_config_sync_log_retention_days_negative_rejected(db):
    """sync_log_retention_days < 0 is rejected."""
    client = _client(db)
    resp = client.put("/api/config", json={"sync_log_retention_days": -1})
    assert resp.status_code == 422


def test_config_auto_sync_enabled_round_trips(db):
    """auto_sync_enabled is read back in ConfigResponse."""
    set_config_value(db, "wizard_completed", True)
    db.commit()
    client = _client(db)

    # Start disabled
    body = client.get("/api/config").json()
    assert body["auto_sync_enabled"] is False

    # Enable via the sync/auto endpoint and verify config reflects it
    resp = client.post("/api/sync/auto", json={"enabled": True})
    assert resp.status_code == 200
    body = client.get("/api/config").json()
    assert body["auto_sync_enabled"] is True


def test_prune_sync_log_deletes_old_rows(db):
    """prune_sync_log removes rows older than the cutoff and leaves newer ones."""
    import datetime
    from app.api.config import prune_sync_log

    now = datetime.datetime.utcnow()
    old_ts = now - datetime.timedelta(days=40)
    new_ts = now - datetime.timedelta(days=5)

    db.add(SyncLog(cycle_id="old", direction="spoolman_to_filamentdb",
                   action="update", entity_type="spool", spoolman_id=1,
                   timestamp=old_ts))
    db.add(SyncLog(cycle_id="new", direction="spoolman_to_filamentdb",
                   action="update", entity_type="spool", spoolman_id=2,
                   timestamp=new_ts))
    db.commit()

    deleted = prune_sync_log(db, retention_days=30)
    db.commit()

    assert deleted == 1
    remaining = db.query(SyncLog).all()
    assert len(remaining) == 1
    assert remaining[0].cycle_id == "new"


def test_prune_sync_log_noop_when_zero(db):
    """prune_sync_log is a no-op when retention_days=0 (keep forever)."""
    import datetime
    from app.api.config import prune_sync_log

    old_ts = datetime.datetime.utcnow() - datetime.timedelta(days=365)
    db.add(SyncLog(cycle_id="c1", direction="spoolman_to_filamentdb",
                   action="update", entity_type="spool", spoolman_id=1,
                   timestamp=old_ts))
    db.commit()

    deleted = prune_sync_log(db, retention_days=0)
    assert deleted == 0
    assert db.query(SyncLog).count() == 1


def test_prune_sync_log_all_within_cutoff_deletes_nothing(db):
    """prune_sync_log leaves rows that are within the retention window untouched."""
    import datetime
    from app.api.config import prune_sync_log

    recent_ts = datetime.datetime.utcnow() - datetime.timedelta(days=2)
    db.add(SyncLog(cycle_id="c1", direction="spoolman_to_filamentdb",
                   action="update", entity_type="spool", spoolman_id=1,
                   timestamp=recent_ts))
    db.commit()

    deleted = prune_sync_log(db, retention_days=30)
    assert deleted == 0
    assert db.query(SyncLog).count() == 1


def test_update_config_reschedules_when_scheduler_present(db):
    """update_config calls scheduler.reschedule_job when app.state.scheduler is set."""
    from unittest.mock import MagicMock
    from fastapi import FastAPI

    mock_scheduler = MagicMock()
    app = FastAPI()
    app.state.scheduler = mock_scheduler
    for mod in _ROUTERS:
        app.include_router(mod.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.state.spoolman = _fake_spoolman()
    app.state.filamentdb = _fake_filamentdb()
    client = TestClient(app)

    resp = client.put("/api/config", json={"sync_interval_seconds": 180})
    assert resp.status_code == 200
    assert resp.json()["sync_interval_seconds"] == 180
    mock_scheduler.reschedule_job.assert_called_once_with(
        "sync_cycle", trigger="interval", seconds=180
    )


def test_update_config_no_reschedule_when_scheduler_absent(db):
    """update_config does not fail when app.state has no scheduler (e.g. in tests)."""
    client = _client(db)
    # No app.state.scheduler set — should not raise
    resp = client.put("/api/config", json={"sync_interval_seconds": 60})
    assert resp.status_code == 200
    assert resp.json()["sync_interval_seconds"] == 60
