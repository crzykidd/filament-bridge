"""Tests for GET/POST /api/masters/defaults (issue #76)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import masters as masters_router
from app.db import Base, get_db
from app.models.config import seed_defaults
from app.models.mapping import FilamentMapping
from app.schemas.filamentdb import FDBFilament
from app.schemas.spoolman import SpoolmanFilament, SpoolmanVendor


def _make_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    seed_defaults(session)
    session.commit()
    return session


def _make_app(db_session, spoolman_client, filamentdb_client):
    app = FastAPI()
    app.include_router(masters_router.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db_session
    app.state.spoolman = spoolman_client
    app.state.filamentdb = filamentdb_client
    return app


def _fake_spoolman(filaments=None):
    sm = AsyncMock()
    sm.get_filaments = AsyncMock(return_value=filaments or [])
    sm.update_filament = AsyncMock(return_value=MagicMock())
    sm.health = AsyncMock(return_value={"version": "0.22.0"})
    return sm


def _fake_filamentdb(filaments=None):
    fdb = AsyncMock()
    fdb.get_filaments = AsyncMock(return_value=filaments or [])
    fdb.update_filament = AsyncMock(return_value=MagicMock())
    fdb.get_version = AsyncMock(return_value="1.35.0")
    return fdb


def test_list_master_defaults_returns_would_fill_row():
    db = _make_session()
    master = FDBFilament(_id="m1", name="Acme PLA (Master)", hasVariants=True, spoolWeight=None)
    variant = FDBFilament(_id="v1", name="Acme PLA Red", parentId="m1", spoolWeight=200.0)
    db.add(FilamentMapping(spoolman_filament_id=11, filamentdb_id="m1"))
    db.commit()

    fdb = _fake_filamentdb([master, variant])
    sm = _fake_spoolman([SpoolmanFilament(id=11, name="Acme PLA", vendor=SpoolmanVendor(id=1, name="Acme"))])

    client = TestClient(_make_app(db, sm, fdb))
    r = client.get("/api/masters/defaults")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["rows"]) == 1
    row = body["rows"][0]
    assert row["filamentdb_id"] == "m1"
    assert row["fields"]["spool_weight"]["proposal"] == 200.0
    assert row["fields"]["spool_weight"]["would_fill"] is True


def test_apply_master_defaults_writes_and_reports_updated():
    db = _make_session()
    master = FDBFilament(_id="m2", name="Acme PLA (Master)", hasVariants=True, spoolWeight=None)
    variant = FDBFilament(_id="v2", name="Acme PLA Blue", parentId="m2", spoolWeight=210.0)
    db.add(FilamentMapping(spoolman_filament_id=22, filamentdb_id="m2"))
    db.commit()

    fdb = _fake_filamentdb([master, variant])
    sm = _fake_spoolman([SpoolmanFilament(id=22, name="Acme PLA", vendor=SpoolmanVendor(id=1, name="Acme"))])

    client = TestClient(_make_app(db, sm, fdb))
    r = client.post("/api/masters/defaults/apply", json={
        "updates": [{"filamentdb_id": "m2", "fields": ["spool_weight"]}],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["updated"] == 1
    assert body["failed"] == []
    fdb.update_filament.assert_awaited_once_with("m2", {"spoolWeight": 210.0})


def test_apply_master_defaults_gated_on_upstream_version():
    db = _make_session()
    fdb = _fake_filamentdb([])
    fdb.get_version = AsyncMock(return_value="0.1.0")  # below MIN_FDB
    sm = _fake_spoolman([])

    client = TestClient(_make_app(db, sm, fdb))
    r = client.post("/api/masters/defaults/apply", json={
        "updates": [{"filamentdb_id": "m3", "fields": ["spool_weight"]}],
    })
    assert r.status_code == 409
