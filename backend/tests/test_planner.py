"""Tests for core/planner.py — FDB filament create-payload builder.

Focused on the netFilamentWeight field added so that Filament DB can render the
spool fill % bar for imported filaments (Spoolman → FDB wizard import).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import wizard
from app.api.config import set_config_value
from app.core.planner import _fdb_filament_payload_from_sm
from app.db import Base, get_db
from app.models.config import BridgeConfig, seed_defaults
from app.schemas.spoolman import SpoolmanFilament, SpoolmanSpool, SpoolmanVendor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sm_filament(
    fid: int = 1,
    name: str = "PLA Black",
    weight: float | None = 1000.0,
    spool_weight: float | None = None,
) -> SpoolmanFilament:
    return SpoolmanFilament(
        id=fid,
        name=name,
        vendor=SpoolmanVendor(id=1, name="ACME"),
        material="PLA",
        weight=weight,
        spool_weight=spool_weight,
    )


def _sm_spool(
    sid: int,
    filament: SpoolmanFilament,
    initial_weight: float | None = None,
    remaining: float = 500.0,
) -> SpoolmanSpool:
    return SpoolmanSpool(
        id=sid,
        filament=filament,
        initial_weight=initial_weight,
        remaining_weight=remaining,
        archived=False,
        extra={},
    )


# ---------------------------------------------------------------------------
# Unit tests for _fdb_filament_payload_from_sm
# ---------------------------------------------------------------------------


def test_net_filament_weight_from_sm_weight():
    """netFilamentWeight is set from sm.weight when available."""
    sm = _sm_filament(weight=1000.0)
    payload = _fdb_filament_payload_from_sm(sm)
    assert payload["netFilamentWeight"] == 1000.0


def test_net_filament_weight_fallback_to_spool_initial_weight():
    """netFilamentWeight falls back to the first spool's initial_weight when sm.weight is None."""
    sm = _sm_filament(weight=None)
    # Three spools; pick the one with the lowest id that has a non-null initial_weight.
    spool_a = _sm_spool(10, sm, initial_weight=None)       # no initial_weight, skipped
    spool_b = _sm_spool(5, sm, initial_weight=800.0)        # lowest id with value → picked
    spool_c = _sm_spool(3, sm, initial_weight=None)         # no initial_weight, skipped
    spools = [spool_a, spool_b, spool_c]

    payload = _fdb_filament_payload_from_sm(sm, spools=spools)
    assert payload["netFilamentWeight"] == 800.0


def test_net_filament_weight_fallback_selects_lowest_spool_id():
    """Fallback uses the first spool sorted by id (deterministic selection)."""
    sm = _sm_filament(weight=None)
    spool_lo = _sm_spool(2, sm, initial_weight=750.0)
    spool_hi = _sm_spool(7, sm, initial_weight=900.0)
    # Pass in reverse order to confirm sorting is applied
    payload = _fdb_filament_payload_from_sm(sm, spools=[spool_hi, spool_lo])
    assert payload["netFilamentWeight"] == 750.0


def test_net_filament_weight_omitted_when_neither_set():
    """netFilamentWeight is completely absent (not null/0) when sm.weight is None and no spool has initial_weight."""
    sm = _sm_filament(weight=None)
    spool_no_initial = _sm_spool(1, sm, initial_weight=None)

    payload = _fdb_filament_payload_from_sm(sm, spools=[spool_no_initial])
    assert "netFilamentWeight" not in payload


def test_net_filament_weight_omitted_with_no_spools():
    """netFilamentWeight is absent when sm.weight is None and no spools are provided."""
    sm = _sm_filament(weight=None)
    payload = _fdb_filament_payload_from_sm(sm, spools=None)
    assert "netFilamentWeight" not in payload


def test_sm_weight_takes_priority_over_spool_initial_weight():
    """sm.weight is used even when spools have initial_weight — sm.weight is authoritative."""
    sm = _sm_filament(weight=1000.0)
    spool = _sm_spool(1, sm, initial_weight=850.0)
    payload = _fdb_filament_payload_from_sm(sm, spools=[spool])
    assert payload["netFilamentWeight"] == 1000.0


# ---------------------------------------------------------------------------
# Integration: netFilamentWeight appears in wizard planned-writes preview
# ---------------------------------------------------------------------------


def _fresh_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    seed_defaults(session)
    return session


def _fake_spoolman(spools=None, filaments=None) -> AsyncMock:
    client = AsyncMock()
    client.get_spools = AsyncMock(return_value=spools or [])
    client.get_filaments = AsyncMock(return_value=filaments or [])
    client.get_field_definitions = AsyncMock(return_value=[])
    return client


def _fake_filamentdb(filaments=None) -> AsyncMock:
    client = AsyncMock()
    client.get_filaments = AsyncMock(return_value=filaments or [])
    client.get_filament = AsyncMock(return_value=None)
    client.get_version = AsyncMock(return_value="1.33.0")
    return client


def _preview_client(db, spoolman=None, filamentdb=None) -> TestClient:
    app = FastAPI()
    app.include_router(wizard.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.state.spoolman = spoolman or _fake_spoolman()
    app.state.filamentdb = filamentdb or _fake_filamentdb()
    return TestClient(app)


def test_wizard_preview_includes_net_filament_weight_in_planned_writes():
    """Wizard planned-writes preview includes netFilamentWeight field for FDB filament creates."""
    db = _fresh_db()
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions",
                     [{"spoolman_filament_id": 1, "action": "create"}])
    db.commit()

    sm_fil = _sm_filament(fid=1, weight=1000.0)
    sm_sp = _sm_spool(1, sm_fil, initial_weight=1000.0)

    spoolman = _fake_spoolman(filaments=[sm_fil], spools=[sm_sp])
    filamentdb = _fake_filamentdb(filaments=[])

    client = _preview_client(db, spoolman, filamentdb)
    resp = client.get("/api/wizard/preview")
    assert resp.status_code == 200
    body = resp.json()

    planned_writes = body.get("planned_writes", [])
    filament_creates = [
        pw for pw in planned_writes
        if pw["system"] == "filamentdb"
        and pw["entity_type"] == "filament"
        and pw["action"] == "create"
    ]
    assert len(filament_creates) >= 1, "expected at least one FDB filament create in planned_writes"

    # netFilamentWeight must appear in the fields of the filament create entry
    all_field_names = {
        f["name"]
        for pw in filament_creates
        for f in pw.get("fields", [])
    }
    assert "netFilamentWeight" in all_field_names, (
        f"netFilamentWeight missing from planned_writes fields; found: {all_field_names}"
    )


def test_wizard_preview_omits_net_filament_weight_when_not_available():
    """Wizard planned-writes preview does NOT include netFilamentWeight when sm.weight is None and no initial_weight."""
    db = _fresh_db()
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions",
                     [{"spoolman_filament_id": 1, "action": "create"}])
    db.commit()

    sm_fil = _sm_filament(fid=1, weight=None)  # no sm.weight
    # Spool with no initial_weight either
    sm_sp = _sm_spool(1, sm_fil, initial_weight=None)

    spoolman = _fake_spoolman(filaments=[sm_fil], spools=[sm_sp])
    filamentdb = _fake_filamentdb(filaments=[])

    client = _preview_client(db, spoolman, filamentdb)
    resp = client.get("/api/wizard/preview")
    assert resp.status_code == 200
    body = resp.json()

    planned_writes = body.get("planned_writes", [])
    filament_creates = [
        pw for pw in planned_writes
        if pw["system"] == "filamentdb"
        and pw["entity_type"] == "filament"
        and pw["action"] == "create"
    ]
    assert len(filament_creates) >= 1

    all_field_names = {
        f["name"]
        for pw in filament_creates
        for f in pw.get("fields", [])
    }
    assert "netFilamentWeight" not in all_field_names, (
        f"netFilamentWeight should be absent; found in: {all_field_names}"
    )
