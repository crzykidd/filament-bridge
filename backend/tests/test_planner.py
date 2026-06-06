"""Tests for core/planner.py — FDB filament create-payload builder.

Covers:
- netFilamentWeight field on FDB create payloads (Spoolman → FDB wizard import).
- Bug A: stale filamentdb_spool_id cross-ref → spool is planned as create, not skip.
- Bug B: resolved tare is written to spoolWeight, not raw sm.spool_weight.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import wizard
from app.api.config import set_config_value
from app.core.planner import _fdb_filament_payload_from_sm, _plan_spoolman_to_fdb
from app.core.weight import DEFAULT_TARE_GRAMS
from app.db import Base, get_db
from app.models.config import BridgeConfig, seed_defaults
from app.schemas.filamentdb import FDBFilament, FDBSpool
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


# ---------------------------------------------------------------------------
# Bug A — stale filamentdb_spool_id cross-ref must not skip spool creation
# ---------------------------------------------------------------------------


def _make_fdb_filament(fid: str, spool_ids: list[str]) -> FDBFilament:
    """Build a minimal FDBFilament with the given spool subdocument ids."""
    return FDBFilament.model_validate({
        "_id": fid,
        "name": "Some Filament",
        "spools": [{"_id": sid, "totalWeight": 250.0, "retired": False} for sid in spool_ids],
    })


def _make_sm_spool_with_xref(
    spool_id: int,
    filament: SpoolmanFilament,
    xref_fdb_spool_id: str | None,
    remaining: float = 200.0,
) -> SpoolmanSpool:
    """Build a SpoolmanSpool with an optional filamentdb_spool_id cross-ref extra."""
    extra: dict = {}
    if xref_fdb_spool_id is not None:
        extra["filamentdb_spool_id"] = json.dumps(xref_fdb_spool_id)
    return SpoolmanSpool(
        id=spool_id,
        filament=filament,
        remaining_weight=remaining,
        archived=False,
        extra=extra,
    )


def _run_planner(db, sm_filaments, sm_spools, fdb_filaments, decisions):
    """Run _plan_spoolman_to_fdb with minimal required args."""
    decisions_by_sm = {d["spoolman_filament_id"]: d for d in decisions}
    return _plan_spoolman_to_fdb(
        db,
        sm_filaments=sm_filaments,
        sm_spools=sm_spools,
        fdb_filaments=fdb_filaments,
        decisions_by_sm=decisions_by_sm,
        master_of_sm={},
        tare_by_sm_spool={},
    )


def test_planner_stale_xref_planned_as_create(db):
    """A SM spool whose filamentdb_spool_id xref points to a non-existent FDB spool
    must be planned as action='create', not 'skip'."""
    sm_fil = _sm_filament(fid=1, name="Beige PLA", weight=1000.0)
    # Xref points to 'old-spool-id' which does NOT exist in current FDB data.
    sm_sp = _make_sm_spool_with_xref(101, sm_fil, xref_fdb_spool_id="old-spool-id")
    # Current FDB has a different spool id (simulates DB wipe/recreate).
    fdb_fil = _make_fdb_filament("fdb-fil-1", ["new-spool-aaa"])

    plan = _run_planner(
        db,
        sm_filaments=[sm_fil],
        sm_spools=[sm_sp],
        fdb_filaments=[fdb_fil],
        decisions=[{"spoolman_filament_id": 1, "action": "create"}],
    )

    spool_items = plan.spool_items
    assert len(spool_items) == 1, f"Expected 1 spool item, got {len(spool_items)}"
    assert spool_items[0].action == "create", (
        f"Expected 'create' but got '{spool_items[0].action}' — stale xref should not skip"
    )


def test_planner_live_xref_planned_as_skip(db):
    """A SM spool whose filamentdb_spool_id xref points to a spool that DOES exist
    in current FDB data must be planned as action='skip'."""
    sm_fil = _sm_filament(fid=2, name="Orange PLA", weight=1000.0)
    # Xref points to 'live-spool-id' which EXISTS in FDB.
    sm_sp = _make_sm_spool_with_xref(102, sm_fil, xref_fdb_spool_id="live-spool-id")
    fdb_fil = _make_fdb_filament("fdb-fil-2", ["live-spool-id"])

    plan = _run_planner(
        db,
        sm_filaments=[sm_fil],
        sm_spools=[sm_sp],
        fdb_filaments=[fdb_fil],
        decisions=[{"spoolman_filament_id": 2, "action": "create"}],
    )

    spool_items = plan.spool_items
    assert len(spool_items) == 1, f"Expected 1 spool item, got {len(spool_items)}"
    assert spool_items[0].action == "skip", (
        f"Expected 'skip' but got '{spool_items[0].action}' — live xref should skip"
    )


def test_planner_live_mapping_skips_regardless_of_xref(db):
    """A SM spool that is in mapped_sm_spool_ids (live SpoolMapping) must always skip,
    even when there is no xref."""
    from app.models.mapping import SpoolMapping

    sm_fil = _sm_filament(fid=3, name="Black PLA", weight=1000.0)
    sm_sp = _make_sm_spool_with_xref(103, sm_fil, xref_fdb_spool_id=None)
    fdb_fil = _make_fdb_filament("fdb-fil-3", ["spool-b"])

    # Add a live SpoolMapping row for this SM spool.
    db.add(SpoolMapping(
        spoolman_spool_id=103,
        filamentdb_filament_id="fdb-fil-3",
        filamentdb_spool_id="spool-b",
    ))
    db.flush()

    plan = _run_planner(
        db,
        sm_filaments=[sm_fil],
        sm_spools=[sm_sp],
        fdb_filaments=[fdb_fil],
        decisions=[{"spoolman_filament_id": 3, "action": "create"}],
    )

    spool_items = plan.spool_items
    assert len(spool_items) == 1
    assert spool_items[0].action == "skip"


def test_planner_standalone_stale_xref_yields_create(db):
    """A standalone filament (one spool, stale xref) must yield a spool create."""
    sm_fil = _sm_filament(fid=4, name="Silk Gold", weight=1000.0)
    sm_sp = _make_sm_spool_with_xref(104, sm_fil, xref_fdb_spool_id="stale-spool-xyz")
    # FDB has NO spool matching 'stale-spool-xyz'.
    fdb_fil = _make_fdb_filament("fdb-fil-4", ["current-spool-111"])

    plan = _run_planner(
        db,
        sm_filaments=[sm_fil],
        sm_spools=[sm_sp],
        fdb_filaments=[fdb_fil],
        decisions=[{"spoolman_filament_id": 4, "action": "create"}],
    )

    assert len(plan.spool_items) == 1
    assert plan.spool_items[0].action == "create"


# ---------------------------------------------------------------------------
# Bug B — spoolWeight on FDB payload must come from the resolved tare
# ---------------------------------------------------------------------------


def test_spool_weight_uses_resolved_tare_when_sm_spool_weight_is_none():
    """When sm.spool_weight is None, spoolWeight on the FDB payload must equal
    the resolved_tare passed in (not None, not omitted)."""
    sm = _sm_filament(fid=10, name="PLA Orange", weight=1000.0, spool_weight=None)
    # Wizard resolved tare = 180g (user override).
    payload = _fdb_filament_payload_from_sm(sm, resolved_tare=180.0)
    assert payload.get("spoolWeight") == 180.0, (
        f"Expected spoolWeight=180.0, got {payload.get('spoolWeight')}"
    )


def test_spool_weight_uses_resolved_tare_over_sm_spool_weight():
    """When sm.spool_weight is set but resolved_tare differs, resolved_tare wins."""
    sm = _sm_filament(fid=11, name="PLA Matte Black", weight=1000.0, spool_weight=220.0)
    # Wizard resolved tare = 185g.
    payload = _fdb_filament_payload_from_sm(sm, resolved_tare=185.0)
    assert payload.get("spoolWeight") == 185.0


def test_spool_weight_default_when_sm_spool_weight_none_and_no_resolved_tare():
    """Without a resolved_tare and with sm.spool_weight=None, spoolWeight is absent
    (the None filter in the payload dict removes it — consistent with prior behavior)."""
    sm = _sm_filament(fid=12, name="PLA White", weight=1000.0, spool_weight=None)
    payload = _fdb_filament_payload_from_sm(sm)
    # spool_weight=None → not in payload (filtered by {k: v for k, v if v is not None})
    assert "spoolWeight" not in payload


def test_planner_phase_a_sets_spool_weight_from_resolved_tare(db):
    """Phase A of _plan_spoolman_to_fdb must set spoolWeight on the filament payload
    from the wizard-resolved tare, not the raw sm.spool_weight."""
    # SM filament has no spool_weight.
    sm_fil = _sm_filament(fid=20, name="PLA Beige", weight=1000.0, spool_weight=None)
    sm_sp = SpoolmanSpool(
        id=201, filament=sm_fil, remaining_weight=800.0, archived=False, extra={},
    )
    fdb_filaments: list = []  # no existing FDB data

    # User set a tare override of 195g for this spool.
    decisions_by_sm = {20: {"spoolman_filament_id": 20, "action": "create"}}
    plan = _plan_spoolman_to_fdb(
        db,
        sm_filaments=[sm_fil],
        sm_spools=[sm_sp],
        fdb_filaments=fdb_filaments,
        decisions_by_sm=decisions_by_sm,
        master_of_sm={},
        tare_by_sm_spool={201: 195.0},
    )

    assert len(plan.filament_items) == 1
    item = plan.filament_items[0]
    assert item.action == "create"
    assert item.fdb_payload is not None
    assert item.fdb_payload.get("spoolWeight") == 195.0, (
        f"Expected spoolWeight=195.0, got {item.fdb_payload.get('spoolWeight')}"
    )


def test_planner_phase_a_uses_default_tare_when_no_override_and_no_sm_spool_weight(db):
    """When no user tare override and sm.spool_weight is None, spoolWeight on the
    filament payload must equal DEFAULT_TARE_GRAMS (200g)."""
    sm_fil = _sm_filament(fid=21, name="PLA Green", weight=1000.0, spool_weight=None)
    sm_sp = SpoolmanSpool(
        id=211, filament=sm_fil, remaining_weight=600.0, archived=False, extra={},
    )

    decisions_by_sm = {21: {"spoolman_filament_id": 21, "action": "create"}}
    plan = _plan_spoolman_to_fdb(
        db,
        sm_filaments=[sm_fil],
        sm_spools=[sm_sp],
        fdb_filaments=[],
        decisions_by_sm=decisions_by_sm,
        master_of_sm={},
        tare_by_sm_spool={},  # no override
    )

    item = plan.filament_items[0]
    assert item.action == "create"
    assert item.fdb_payload.get("spoolWeight") == DEFAULT_TARE_GRAMS, (
        f"Expected spoolWeight={DEFAULT_TARE_GRAMS}, got {item.fdb_payload.get('spoolWeight')}"
    )


def test_planner_spool_gross_matches_filament_spool_weight(db):
    """The gross totalWeight planned for the spool must equal spool net + spoolWeight
    written to the filament payload (they must be driven by the same resolved tare)."""
    sm_fil = _sm_filament(fid=22, name="ABS Red", weight=1000.0, spool_weight=None)
    sm_sp = SpoolmanSpool(
        id=221, filament=sm_fil, remaining_weight=750.0, archived=False, extra={},
    )
    tare_override = 170.0

    decisions_by_sm = {22: {"spoolman_filament_id": 22, "action": "create"}}
    plan = _plan_spoolman_to_fdb(
        db,
        sm_filaments=[sm_fil],
        sm_spools=[sm_sp],
        fdb_filaments=[],
        decisions_by_sm=decisions_by_sm,
        master_of_sm={},
        tare_by_sm_spool={221: tare_override},
    )

    fil_item = plan.filament_items[0]
    spool_item = plan.spool_items[0]

    written_spool_weight = fil_item.fdb_payload.get("spoolWeight")
    planned_gross = spool_item.planned_gross

    assert written_spool_weight == tare_override
    # gross = net + tare
    assert planned_gross == pytest.approx(750.0 + tare_override, abs=0.01)
