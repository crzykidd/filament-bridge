"""Tests for GET /api/reconcile — read-only cross-system reconcile report.

Exercises the endpoint via a minimal FastAPI test app with faked upstream
clients, following the same harness pattern as test_api.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import reconcile
from app.db import Base, get_db
from app.models.config import seed_defaults
from app.schemas.filamentdb import FDBFilament
from app.schemas.spoolman import SpoolmanFilament, SpoolmanSpool, SpoolmanVendor


# ---------------------------------------------------------------------------
# Harness helpers
# ---------------------------------------------------------------------------


def _fresh_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    seed_defaults(session)
    session.commit()
    return session


def _fake_spoolman(filaments=None, spools=None) -> AsyncMock:
    client = AsyncMock()
    client.get_filaments = AsyncMock(return_value=filaments or [])
    client.get_spools = AsyncMock(return_value=spools or [])
    return client


def _fake_filamentdb(filaments=None) -> AsyncMock:
    client = AsyncMock()
    client.get_filaments = AsyncMock(return_value=filaments or [])
    return client


def _client(db, spoolman=None, filamentdb=None) -> TestClient:
    app = FastAPI()
    app.include_router(reconcile.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.state.spoolman = spoolman or _fake_spoolman()
    app.state.filamentdb = filamentdb or _fake_filamentdb()
    return TestClient(app)


# ---------------------------------------------------------------------------
# Fixture factories
# ---------------------------------------------------------------------------


def _sm_filament(id_: int, vendor: str, name: str, color: str) -> SpoolmanFilament:
    return SpoolmanFilament(
        id=id_,
        name=name,
        vendor=SpoolmanVendor(id=1, name=vendor),
        color_hex=color,
    )


def _sm_spool(
    spool_id: int,
    filament: SpoolmanFilament,
    remaining: float | None = None,
    extra: dict | None = None,
    archived: bool = False,
) -> SpoolmanSpool:
    return SpoolmanSpool(
        id=spool_id,
        filament=filament,
        remaining_weight=remaining,
        archived=archived,
        extra=extra or {},
    )


def _fdb_filament(
    id_: str,
    vendor: str,
    name: str,
    color: str,
    spools: list[dict] | None = None,
) -> FDBFilament:
    spool_dicts = spools or []
    return FDBFilament.model_validate(
        {
            "_id": id_,
            "name": name,
            "vendor": vendor,
            "color": color,
            "spoolWeight": 200.0,
            "spools": spool_dicts,
        }
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_reconcile_name_match():
    """A SM and FDB filament with matching vendor+name+color appear as matched."""
    db = _fresh_db()
    sm_fil = _sm_filament(1, "ELEGOO", "PLA", "ff0000")
    fdb_fil = _fdb_filament("fdb-1", "ELEGOO", "PLA", "#ff0000")

    tc = _client(
        db,
        spoolman=_fake_spoolman(filaments=[sm_fil], spools=[]),
        filamentdb=_fake_filamentdb(filaments=[fdb_fil]),
    )
    r = tc.get("/api/reconcile")
    assert r.status_code == 200
    data = r.json()

    assert data["summary"]["matched"] == 1
    assert data["summary"]["only_in_spoolman"] == 0
    assert data["summary"]["only_in_filamentdb"] == 0
    assert data["summary"]["ambiguous"] == 0

    row = data["matched"][0]
    assert row["spoolman"]["spoolman_filament_id"] == 1
    assert row["filamentdb"]["filamentdb_filament_id"] == "fdb-1"
    assert row["confidence"] == 1.0
    # No cross-ref → not linked (name match only)
    assert row["linked"] is False
    db.close()


def test_reconcile_xref_match_linked_true():
    """When an SM spool has filamentdb_id set, the pair is linked=True."""
    db = _fresh_db()
    sm_fil = _sm_filament(1, "ELEGOO", "PLA", "ff0000")
    # SM spool carries the cross-ref extra field
    sm_spool = _sm_spool(
        100,
        sm_fil,
        remaining=800.0,
        extra={"filamentdb_id": '"fdb-1"'},  # encode_extra_value format
    )
    fdb_fil = _fdb_filament("fdb-1", "ELEGOO", "PLA", "#ff0000")

    tc = _client(
        db,
        spoolman=_fake_spoolman(filaments=[sm_fil], spools=[sm_spool]),
        filamentdb=_fake_filamentdb(filaments=[fdb_fil]),
    )
    r = tc.get("/api/reconcile")
    assert r.status_code == 200
    data = r.json()

    assert data["summary"]["matched"] == 1
    row = data["matched"][0]
    assert row["linked"] is True
    db.close()


def test_reconcile_only_in_spoolman():
    """SM filament with no FDB counterpart ends up in only_in_spoolman."""
    db = _fresh_db()
    sm_fil = _sm_filament(1, "ELEGOO", "PLA", "ff0000")

    tc = _client(
        db,
        spoolman=_fake_spoolman(filaments=[sm_fil], spools=[]),
        filamentdb=_fake_filamentdb(filaments=[]),
    )
    r = tc.get("/api/reconcile")
    assert r.status_code == 200
    data = r.json()

    assert data["summary"]["only_in_spoolman"] == 1
    assert data["summary"]["matched"] == 0
    assert data["only_in_spoolman"][0]["ref"]["spoolman_filament_id"] == 1
    db.close()


def test_reconcile_only_in_filamentdb():
    """FDB filament with no SM counterpart ends up in only_in_filamentdb."""
    db = _fresh_db()
    fdb_fil = _fdb_filament("fdb-1", "ELEGOO", "PLA", "#ff0000")

    tc = _client(
        db,
        spoolman=_fake_spoolman(filaments=[], spools=[]),
        filamentdb=_fake_filamentdb(filaments=[fdb_fil]),
    )
    r = tc.get("/api/reconcile")
    assert r.status_code == 200
    data = r.json()

    assert data["summary"]["only_in_filamentdb"] == 1
    assert data["summary"]["matched"] == 0
    assert data["only_in_filamentdb"][0]["ref"]["filamentdb_filament_id"] == "fdb-1"
    db.close()


def test_reconcile_ambiguous():
    """One SM filament with two FDB candidates appears in ambiguous."""
    db = _fresh_db()
    sm_fil = _sm_filament(1, "ELEGOO", "PLA", "ff0000")
    # Two FDB filaments with the same normalized key → ambiguous
    fdb_a = _fdb_filament("fdb-a", "ELEGOO", "PLA", "#ff0000")
    fdb_b = _fdb_filament("fdb-b", "elegoo", "pla", "ff0000")

    tc = _client(
        db,
        spoolman=_fake_spoolman(filaments=[sm_fil], spools=[]),
        filamentdb=_fake_filamentdb(filaments=[fdb_a, fdb_b]),
    )
    r = tc.get("/api/reconcile")
    assert r.status_code == 200
    data = r.json()

    assert data["summary"]["ambiguous"] == 1
    assert data["summary"]["matched"] == 0
    assert len(data["ambiguous"]) == 1
    amb = data["ambiguous"][0]
    assert amb["spoolman"]["spoolman_filament_id"] == 1
    assert len(amb["candidates"]) == 2
    db.close()


def test_reconcile_spool_rollup_counts_and_weights():
    """Spool roll-up counts and weights are correctly summed per filament."""
    db = _fresh_db()
    sm_fil = _sm_filament(1, "ELEGOO", "PLA", "ff0000")
    fdb_fil = _fdb_filament(
        "fdb-1",
        "ELEGOO",
        "PLA",
        "#ff0000",
        spools=[
            {"_id": "spool-a", "totalWeight": 900.0, "retired": False},
            {"_id": "spool-b", "totalWeight": 500.0, "retired": False},
        ],
    )
    sm_spool1 = _sm_spool(101, sm_fil, remaining=700.0)
    sm_spool2 = _sm_spool(102, sm_fil, remaining=300.0)

    tc = _client(
        db,
        spoolman=_fake_spoolman(filaments=[sm_fil], spools=[sm_spool1, sm_spool2]),
        filamentdb=_fake_filamentdb(filaments=[fdb_fil]),
    )
    r = tc.get("/api/reconcile")
    assert r.status_code == 200
    data = r.json()

    assert data["summary"]["matched"] == 1
    row = data["matched"][0]
    assert row["spoolman_spools"] == 2
    assert row["filamentdb_spools"] == 2
    assert abs(row["spoolman_weight"] - 1000.0) < 0.001
    assert abs(row["filamentdb_weight"] - 1400.0) < 0.001
    db.close()


def test_reconcile_none_weight_spool():
    """A spool with None remaining_weight results in weight_total=None for that side."""
    db = _fresh_db()
    sm_fil = _sm_filament(1, "ELEGOO", "PLA", "ff0000")
    sm_spool = _sm_spool(101, sm_fil, remaining=None)  # no weight recorded

    tc = _client(
        db,
        spoolman=_fake_spoolman(filaments=[sm_fil], spools=[sm_spool]),
        filamentdb=_fake_filamentdb(filaments=[]),
    )
    r = tc.get("/api/reconcile")
    assert r.status_code == 200
    data = r.json()

    assert data["summary"]["only_in_spoolman"] == 1
    missing = data["only_in_spoolman"][0]
    assert missing["spool_count"] == 1
    assert missing["weight_total"] is None
    db.close()


def test_reconcile_summary_counts():
    """Summary totals correctly reflect the full dataset."""
    db = _fresh_db()
    # 2 SM + 3 FDB, with 1 matched, 1 only-SM, 2 only-FDB
    sm_a = _sm_filament(1, "ELEGOO", "PLA", "ff0000")   # matches fdb_a
    sm_b = _sm_filament(2, "ELEGOO", "PETG", "00ff00")  # no FDB match

    fdb_a = _fdb_filament("fdb-a", "ELEGOO", "PLA", "#ff0000")    # matches sm_a
    fdb_b = _fdb_filament("fdb-b", "Bambu", "ASA", "#0000ff")     # no SM match
    fdb_c = _fdb_filament("fdb-c", "Bambu", "TPU", "#ffffff")     # no SM match

    tc = _client(
        db,
        spoolman=_fake_spoolman(filaments=[sm_a, sm_b], spools=[]),
        filamentdb=_fake_filamentdb(filaments=[fdb_a, fdb_b, fdb_c]),
    )
    r = tc.get("/api/reconcile")
    assert r.status_code == 200
    data = r.json()

    s = data["summary"]
    assert s["spoolman_filaments"] == 2
    assert s["filamentdb_filaments"] == 3
    assert s["matched"] == 1
    assert s["only_in_spoolman"] == 1
    assert s["only_in_filamentdb"] == 2
    assert s["ambiguous"] == 0
    db.close()
