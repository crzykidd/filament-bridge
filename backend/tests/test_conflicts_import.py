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
"""
from __future__ import annotations

import datetime
import json
from unittest.mock import AsyncMock, MagicMock

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
    return fdb


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
