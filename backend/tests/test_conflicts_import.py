"""Tests for POST /api/conflicts/{conflict_id}/import endpoint.

Covers:
  - dry_run returns preview without writing
  - SM→FDB new_filament conflict: creates FDB filament + mapping + resolves conflict
  - SM→FDB new_spool conflict: creates FDB spool + mapping + resolves conflict
  - filament_action=link: links to an existing FDB filament
  - 404 on unknown conflict id
  - 409 on already-resolved conflict
  - 400 on unsupported conflict type
  - paired new_filament conflict is resolved when a new_spool is imported
  - find-or-attach on 409 (idempotent conflict Add doom-loop fix):
      re-run Add when master+variant already exist → zero failures, conflict resolves
      sibling variant attaches to existing master, no 409 failure
      genuinely new record still creates fresh (no regression)
      container 409 with no findable match still fails cleanly
"""
from __future__ import annotations

import datetime
import json
from unittest.mock import AsyncMock, MagicMock

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import conflicts as conflicts_router
from app.api.config import set_config_value
from app.db import Base, get_db
from app.models.config import seed_defaults
from app.models.conflict import Conflict
from app.models.mapping import FilamentMapping

# ---------------------------------------------------------------------------
# Test app / client
# ---------------------------------------------------------------------------


def _make_app(db_session, spoolman_client, filamentdb_client):
    app = FastAPI()
    app.include_router(conflicts_router.router, prefix="/api")

    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.state.spoolman = spoolman_client
    app.state.filamentdb = filamentdb_client
    return app


def _make_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    seed_defaults(session)
    set_config_value(session, "variant_parent_mode", "promote_color")
    session.commit()
    return session


def _fake_spoolman(filaments=None, spools=None):
    sm = AsyncMock()
    sm.get_filaments = AsyncMock(return_value=filaments or [])
    sm.get_spools = AsyncMock(return_value=spools or [])
    sm.get_vendors = AsyncMock(return_value=[])
    sm.create_filament = AsyncMock(return_value=MagicMock(id=999))
    sm.create_spool = AsyncMock(return_value=MagicMock(id=888))
    sm.update_spool = AsyncMock(return_value=MagicMock())
    sm.update_filament = AsyncMock(return_value=MagicMock())
    sm.health = AsyncMock(return_value={"version": "0.22.0"})
    sm.ensure_extra_fields = AsyncMock()
    return sm


def _fake_filamentdb(filaments=None):
    fdb = AsyncMock()
    fdb.get_filaments = AsyncMock(return_value=filaments or [])
    fdb.get_version = AsyncMock(return_value="1.33.0")
    fdb.create_filament = AsyncMock(return_value=MagicMock(id="new-fdb-fil-001"))
    fdb.create_spool = AsyncMock(return_value={"_id": "new-fdb-spool-001"})
    fdb.update_spool = AsyncMock(return_value={})
    fdb.update_filament = AsyncMock(return_value={})
    fdb.get_locations = AsyncMock(return_value=[])
    fdb.merge_filament_settings = AsyncMock(return_value=None)
    return fdb


def _make_session_gc():
    """Create a session with generic_container mode for find-or-attach tests."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    seed_defaults(session)
    set_config_value(session, "variant_parent_mode", "generic_container")
    session.commit()
    return session


def _409_response() -> httpx.Response:
    """Build a fake httpx 409 response for use in mock side-effects."""
    return httpx.Response(409, json={"detail": "Duplicate key error"})


def _raise_409(*args, **kwargs):
    """Raise an httpx.HTTPStatusError with a 409 status (sync helper for AsyncMock)."""
    raise httpx.HTTPStatusError("409 conflict", request=MagicMock(), response=_409_response())


# ---------------------------------------------------------------------------
# Tests: validation
# ---------------------------------------------------------------------------


def test_import_conflict_not_found():
    db = _make_session()
    sm = _fake_spoolman()
    fdb = _fake_filamentdb()
    client = TestClient(_make_app(db, sm, fdb))
    r = client.post("/api/conflicts/9999/import", json={"dry_run": False})
    assert r.status_code == 404


def test_import_conflict_already_resolved():
    db = _make_session()
    c = Conflict(
        entity_type="filament", field_name="new_filament",
        spoolman_id=1,
        spoolman_value=json.dumps("SM filament 1"),
        resolved_at=datetime.datetime.now(datetime.timezone.utc),
        resolution="dismissed",
    )
    db.add(c)
    db.commit()
    sm = _fake_spoolman()
    fdb = _fake_filamentdb()
    client = TestClient(_make_app(db, sm, fdb))
    r = client.post(f"/api/conflicts/{c.id}/import", json={"dry_run": False})
    assert r.status_code == 409


def test_import_conflict_unsupported_type():
    db = _make_session()
    c = Conflict(
        entity_type="spool", field_name="weight",
        spoolman_id=1,
        spoolman_value=json.dumps(800.0),
    )
    db.add(c)
    db.commit()
    sm = _fake_spoolman()
    fdb = _fake_filamentdb()
    client = TestClient(_make_app(db, sm, fdb))
    r = client.post(f"/api/conflicts/{c.id}/import", json={"dry_run": False})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Tests: SM→FDB new_filament import
# ---------------------------------------------------------------------------


def test_import_new_filament_conflict_creates_fdb_filament():
    """Importing a new_filament conflict (SM→FDB) creates a FDB filament + mapping."""
    from app.schemas.spoolman import SpoolmanFilament, SpoolmanVendor, SpoolmanSpool

    db = _make_session()
    sm_fil = SpoolmanFilament(id=11, name="PLA Red", material="PLA",
                               vendor=SpoolmanVendor(id=1, name="Acme"), extra={})
    sm_spool = SpoolmanSpool(id=101, filament=sm_fil, remaining_weight=800.0,
                              archived=False, extra={})

    # Queue a new_filament conflict for SM filament 11.
    c = Conflict(
        entity_type="filament", field_name="new_filament",
        spoolman_id=11,
        spoolman_value=json.dumps("SM filament 11 has no FDB match"),
    )
    db.add(c)
    db.commit()
    conflict_id = c.id

    sm = _fake_spoolman(filaments=[sm_fil], spools=[sm_spool])
    fdb = _fake_filamentdb(filaments=[])
    fdb.create_filament = AsyncMock(return_value=MagicMock(id="fdb-fil-new", name="PLA Red",
                                                            vendor="Acme", spoolWeight=200.0,
                                                            spools=[]))
    fdb.create_spool = AsyncMock(return_value={"_id": "fdb-spool-new"})

    client = TestClient(_make_app(db, sm, fdb))
    r = client.post(f"/api/conflicts/{conflict_id}/import", json={"dry_run": False})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["created"] >= 1

    # Conflict must now be resolved.
    db.expire_all()
    c_after = db.query(Conflict).filter_by(id=conflict_id).first()
    assert c_after.resolved_at is not None
    assert c_after.resolution == "imported"

    # A FilamentMapping must exist.
    fm = db.query(FilamentMapping).filter_by(spoolman_filament_id=11).first()
    assert fm is not None, "FilamentMapping must be created after import"


def test_import_new_filament_conflict_dry_run_no_write():
    """dry_run=True returns preview but creates nothing and leaves conflict open."""
    from app.schemas.spoolman import SpoolmanFilament, SpoolmanVendor, SpoolmanSpool

    db = _make_session()
    sm_fil = SpoolmanFilament(id=12, name="PLA Blue", material="PLA",
                               vendor=SpoolmanVendor(id=1, name="Acme"), extra={})
    sm_spool = SpoolmanSpool(id=102, filament=sm_fil, remaining_weight=600.0,
                              archived=False, extra={})
    c = Conflict(
        entity_type="filament", field_name="new_filament",
        spoolman_id=12,
        spoolman_value=json.dumps("SM filament 12 has no FDB match"),
    )
    db.add(c)
    db.commit()
    conflict_id = c.id

    sm = _fake_spoolman(filaments=[sm_fil], spools=[sm_spool])
    fdb = _fake_filamentdb(filaments=[])

    client = TestClient(_make_app(db, sm, fdb))
    r = client.post(f"/api/conflicts/{conflict_id}/import", json={"dry_run": True})
    assert r.status_code == 200, r.text

    # Conflict stays open after dry run.
    db.expire_all()
    c_after = db.query(Conflict).filter_by(id=conflict_id).first()
    assert c_after.resolved_at is None, "dry_run must not resolve the conflict"

    # No FilamentMapping created.
    assert db.query(FilamentMapping).filter_by(spoolman_filament_id=12).first() is None


def test_import_new_spool_conflict_resolves_paired_new_filament():
    """Importing a new_spool conflict also resolves a paired new_filament conflict
    for the same SM filament."""
    from app.schemas.spoolman import SpoolmanFilament, SpoolmanVendor, SpoolmanSpool

    db = _make_session()
    sm_fil = SpoolmanFilament(id=13, name="PETG Green", material="PETG",
                               vendor=SpoolmanVendor(id=1, name="Acme"), extra={})
    sm_spool = SpoolmanSpool(id=103, filament=sm_fil, remaining_weight=700.0,
                              archived=False, extra={})

    # Two conflicts: a new_filament for filament 13 + a new_spool for spool 103.
    c_fil = Conflict(
        entity_type="filament", field_name="new_filament",
        spoolman_id=13,
        spoolman_value=json.dumps("SM filament 13 has no FDB match"),
    )
    c_spool = Conflict(
        entity_type="spool", field_name="new_spool",
        spoolman_id=103,
        spoolman_value=json.dumps("SM spool 103 held"),
    )
    db.add_all([c_fil, c_spool])
    db.commit()
    spool_conflict_id = c_spool.id
    fil_conflict_id = c_fil.id

    sm = _fake_spoolman(
        filaments=[sm_fil],
        spools=[sm_spool],
    )
    fdb = _fake_filamentdb(filaments=[])
    fdb.create_filament = AsyncMock(return_value=MagicMock(id="fdb-fil-13", name="PETG Green",
                                                            vendor="Acme", spoolWeight=200.0,
                                                            spools=[]))
    fdb.create_spool = AsyncMock(return_value={"_id": "fdb-spool-13"})

    client = TestClient(_make_app(db, sm, fdb))
    # Import via the new_spool conflict (the spool belongs to filament 13).
    r = client.post(f"/api/conflicts/{spool_conflict_id}/import", json={"dry_run": False})
    assert r.status_code == 200, r.text

    db.expire_all()
    # Both conflicts resolved.
    c_spool_after = db.query(Conflict).filter_by(id=spool_conflict_id).first()
    assert c_spool_after.resolved_at is not None
    c_fil_after = db.query(Conflict).filter_by(id=fil_conflict_id).first()
    assert c_fil_after.resolved_at is not None, (
        "Paired new_filament conflict must be auto-resolved when new_spool is imported"
    )


# ---------------------------------------------------------------------------
# Tests: find-or-attach on 409 (idempotent conflict-Add doom-loop fix)
# ---------------------------------------------------------------------------


def test_rerun_add_generic_container_master_and_variant_already_exist_zero_failures():
    """Re-running Add when master+variant already exist links to them — zero failures,
    conflict resolves.

    Mirrors the live ELEGOO PLA Red doom-loop: SM filament 172 'ELEGOO PLA Red'
    in generic_container mode.  First Add created 'ELEGOO PLA (Master)' +
    'ELEGOO PLA Red' in FDB; second Add 409s on both creates.  With the
    find-or-attach fix, the second Add should link to the existing records and
    produce zero failures so the conflict resolves.
    """
    from app.schemas.spoolman import SpoolmanFilament, SpoolmanVendor, SpoolmanSpool
    from app.schemas.filamentdb import FDBFilament

    db = _make_session_gc()

    sm_fil = SpoolmanFilament(
        id=172, name="PLA Red", material="PLA",
        vendor=SpoolmanVendor(id=1, name="ELEGOO"), extra={},
    )
    sm_spool = SpoolmanSpool(id=201, filament=sm_fil, remaining_weight=800.0,
                              archived=False, extra={})

    # The existing FDB records (already created by a prior Add).
    master_fdb = FDBFilament.model_validate({
        "_id": "master-001", "name": "ELEGOO PLA (Master)", "vendor": "ELEGOO",
        "type": "PLA", "color": None, "parentId": None, "hasVariants": True,
    })
    variant_fdb = FDBFilament.model_validate({
        "_id": "variant-001", "name": "ELEGOO PLA Red", "vendor": "ELEGOO",
        "type": "PLA", "color": "FF0000", "parentId": "master-001",
    })

    # Queue the new_filament conflict.
    c = Conflict(
        entity_type="filament", field_name="new_filament",
        spoolman_id=172,
        spoolman_value=json.dumps("SM filament 172 has no FDB match"),
    )
    db.add(c)
    db.commit()
    conflict_id = c.id

    sm = _fake_spoolman(filaments=[sm_fil], spools=[sm_spool])
    fdb = _fake_filamentdb(filaments=[master_fdb, variant_fdb])

    # Both create calls 409 (records already exist).
    fdb.create_filament = AsyncMock(side_effect=_raise_409)
    fdb.create_spool = AsyncMock(return_value={"_id": "fdb-spool-rerun"})

    client = TestClient(_make_app(db, sm, fdb))
    r = client.post(f"/api/conflicts/{conflict_id}/import", json={"dry_run": False})

    assert r.status_code == 200, r.text
    data = r.json()
    # find-or-attach: zero failures — both creates resolved to existing FDB records.
    assert data["failed"] == 0, (
        f"Expected 0 failures on find-or-attach re-Add, got {data['failed']}; "
        f"records: {data.get('records')}"
    )
    # Conflict must be resolved (failed==0 → resolution path runs).
    db.expire_all()
    c_after = db.query(Conflict).filter_by(id=conflict_id).first()
    assert c_after.resolved_at is not None, "Conflict must resolve when failed==0"
    assert c_after.resolution == "imported"


def test_sibling_variant_attaches_to_existing_master_no_409_failure():
    """Adding a second variant of the same material cluster attaches to the existing master.

    First variant was already imported (master + first color).  Second Add for a
    sibling color: container create 409s (master exists) → find-or-attach links to
    it; variant create succeeds (new color) → zero failures, conflict resolves.
    """
    from app.schemas.spoolman import SpoolmanFilament, SpoolmanVendor, SpoolmanSpool
    from app.schemas.filamentdb import FDBFilament

    db = _make_session_gc()

    # The sibling filament being added.
    sm_fil_blue = SpoolmanFilament(
        id=173, name="PLA Blue", material="PLA",
        vendor=SpoolmanVendor(id=1, name="ELEGOO"), extra={},
    )
    sm_spool = SpoolmanSpool(id=202, filament=sm_fil_blue, remaining_weight=750.0,
                              archived=False, extra={})

    # Existing FDB: master + first color already imported.
    master_fdb = FDBFilament.model_validate({
        "_id": "master-002", "name": "ELEGOO PLA (Master)", "vendor": "ELEGOO",
        "type": "PLA", "color": None, "parentId": None, "hasVariants": True,
    })
    existing_red = FDBFilament.model_validate({
        "_id": "variant-002", "name": "ELEGOO PLA Red", "vendor": "ELEGOO",
        "type": "PLA", "color": "FF0000", "parentId": "master-002",
    })

    c = Conflict(
        entity_type="filament", field_name="new_filament",
        spoolman_id=173,
        spoolman_value=json.dumps("SM filament 173 has no FDB match"),
    )
    db.add(c)
    db.commit()
    conflict_id = c.id

    sm = _fake_spoolman(filaments=[sm_fil_blue], spools=[sm_spool])
    fdb = _fake_filamentdb(filaments=[master_fdb, existing_red])

    call_count = 0

    async def _create_selective(payload):
        """409 for master container (already exists), success for new blue variant."""
        nonlocal call_count
        call_count += 1
        name = payload.get("name", "")
        if "(Master)" in name:
            raise httpx.HTTPStatusError(
                "409 conflict", request=MagicMock(), response=_409_response()
            )
        return MagicMock(id=f"fdb-blue-{call_count}", name=name, vendor="ELEGOO",
                         spoolWeight=200.0, spools=[])

    fdb.create_filament = AsyncMock(side_effect=_create_selective)
    fdb.create_spool = AsyncMock(return_value={"_id": "fdb-spool-blue"})

    client = TestClient(_make_app(db, sm, fdb))
    r = client.post(f"/api/conflicts/{conflict_id}/import", json={"dry_run": False})

    assert r.status_code == 200, r.text
    data = r.json()
    # Container 409 was resolved via find-or-attach; new variant created.
    assert data["failed"] == 0, (
        f"Sibling variant import should produce 0 failures; records: {data.get('records')}"
    )
    db.expire_all()
    c_after = db.query(Conflict).filter_by(id=conflict_id).first()
    assert c_after.resolved_at is not None, "Conflict must resolve on sibling variant add"


def test_genuinely_new_record_still_creates_fresh():
    """A genuinely new SM filament (no existing FDB match) still creates fresh.

    Regression guard: find-or-attach must not interfere with successful creates.
    """
    from app.schemas.spoolman import SpoolmanFilament, SpoolmanVendor, SpoolmanSpool

    db = _make_session_gc()

    sm_fil = SpoolmanFilament(
        id=174, name="PETG Black", material="PETG",
        vendor=SpoolmanVendor(id=1, name="Bambu Lab"), extra={},
    )
    sm_spool = SpoolmanSpool(id=203, filament=sm_fil, remaining_weight=900.0,
                              archived=False, extra={})

    c = Conflict(
        entity_type="filament", field_name="new_filament",
        spoolman_id=174,
        spoolman_value=json.dumps("SM filament 174 has no FDB match"),
    )
    db.add(c)
    db.commit()
    conflict_id = c.id

    call_count = 0

    async def _create_success(payload):
        nonlocal call_count
        call_count += 1
        return MagicMock(id=f"fdb-new-{call_count}", name=payload.get("name", "?"),
                         vendor="Bambu Lab", spoolWeight=200.0, spools=[])

    sm = _fake_spoolman(filaments=[sm_fil], spools=[sm_spool])
    # FDB has NO filament named "Bambu Lab PETG (Master)" or "Bambu Lab PETG Black"
    fdb = _fake_filamentdb(filaments=[])
    fdb.create_filament = AsyncMock(side_effect=_create_success)
    fdb.create_spool = AsyncMock(return_value={"_id": "fdb-spool-new"})

    client = TestClient(_make_app(db, sm, fdb))
    r = client.post(f"/api/conflicts/{conflict_id}/import", json={"dry_run": False})

    assert r.status_code == 200, r.text
    data = r.json()
    assert data["failed"] == 0, f"Fresh create should have 0 failures; got {data}"
    # Both container + variant should have been created (create was called at least twice)
    assert call_count >= 2, f"Expected at least 2 create_filament calls, got {call_count}"
    db.expire_all()
    c_after = db.query(Conflict).filter_by(id=conflict_id).first()
    assert c_after.resolved_at is not None


def test_container_409_no_existing_match_fails_cleanly():
    """Container 409 with no findable existing FDB match records a failure cleanly.

    When a 409 occurs creating a container AND no FDB filament with that display
    name exists in fdb_by_id, the result should be a single 'failed' record (not a
    crash or silent skip).  The conflict stays open.
    """
    from app.schemas.spoolman import SpoolmanFilament, SpoolmanVendor, SpoolmanSpool

    db = _make_session_gc()

    sm_fil = SpoolmanFilament(
        id=175, name="ABS White", material="ABS",
        vendor=SpoolmanVendor(id=1, name="PolyMaker"), extra={},
    )
    sm_spool = SpoolmanSpool(id=204, filament=sm_fil, remaining_weight=500.0,
                              archived=False, extra={})

    c = Conflict(
        entity_type="filament", field_name="new_filament",
        spoolman_id=175,
        spoolman_value=json.dumps("SM filament 175 has no FDB match"),
    )
    db.add(c)
    db.commit()
    conflict_id = c.id

    sm = _fake_spoolman(filaments=[sm_fil], spools=[sm_spool])
    # FDB has NO filament named "PolyMaker ABS (Master)" → find-or-attach returns None.
    fdb = _fake_filamentdb(filaments=[])
    fdb.create_filament = AsyncMock(side_effect=_raise_409)

    client = TestClient(_make_app(db, sm, fdb))
    r = client.post(f"/api/conflicts/{conflict_id}/import", json={"dry_run": False})

    # Import returns 502 (partial failure leaves conflict open).
    assert r.status_code == 502, r.text
    db.expire_all()
    c_after = db.query(Conflict).filter_by(id=conflict_id).first()
    assert c_after.resolved_at is None, "Conflict must stay open when container create fails"
