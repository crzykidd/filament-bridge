"""Tests for core/planner.py — FDB filament create-payload builder.

Covers:
- netFilamentWeight field on FDB create payloads (Spoolman → FDB wizard import).
- Bug A: stale filamentdb_spool_id cross-ref → spool is planned as create, not skip.
- Bug B: resolved tare is written to spoolWeight, not raw sm.spool_weight.
- Archived spool fix: archived spools route through the empty gate and import as retired.
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
from app.core.planner import _fdb_filament_payload_from_sm, _filament_base_name, _patch_fdb_name, _plan_spoolman_to_fdb
from app.db import Base, get_db
from app.models.config import seed_defaults
from app.models.mapping import FilamentMapping, SpoolMapping
from app.schemas.filamentdb import FDBFilament
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
    # Default to "promote_color" so wizard preview/execute tests do not hit the
    # variant_parent_mode == "unset" gate.
    set_config_value(session, "variant_parent_mode", "promote_color")
    session.commit()
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


def test_planner_phase_a_no_tare_when_no_override_and_no_sm_spool_weight(db):
    """When no user tare override and sm.spool_weight is None, spoolWeight must be
    absent from the filament payload (None is filtered out by the payload builder).
    The execute path rejects rather than writing 200 g as a guess."""
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
    # _resolve_filament_tare returns None → spoolWeight absent (filtered) or None
    assert item.fdb_payload.get("spoolWeight") is None, (
        f"Expected spoolWeight=None (no default fallback), got {item.fdb_payload.get('spoolWeight')}"
    )
    # The spool item must be tagged needs_input, not default
    spool_item = plan.spool_items[0]
    assert spool_item.tare_source == "needs_input", (
        f"Expected tare_source='needs_input', got '{spool_item.tare_source}'"
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


# ---------------------------------------------------------------------------
# Variant naming — FDB names include vendor + material + color (collision fix)
# ---------------------------------------------------------------------------


def _sm_filament_with_vendor(
    fid: int,
    name: str,
    vendor_name: str,
    material: str = "PLA",
) -> SpoolmanFilament:
    return SpoolmanFilament(
        id=fid,
        name=name,
        vendor=SpoolmanVendor(id=fid, name=vendor_name),
        material=material,
        weight=1000.0,
    )


def _run_planner_named(db, sm_filaments, decisions, master_of_sm=None) -> dict:
    """Run the planner and return {sm_id: planned_fdb_name} for 'create' items."""
    decisions_by_sm = {d["spoolman_filament_id"]: d for d in decisions}
    plan = _plan_spoolman_to_fdb(
        db,
        sm_filaments=sm_filaments,
        sm_spools=[],
        fdb_filaments=[],
        decisions_by_sm=decisions_by_sm,
        master_of_sm=master_of_sm or {},
        tare_by_sm_spool={},
    )
    return {
        item.sm_filament.id: item.fdb_payload.get("name")
        for item in plan.filament_items
        if item.action == "create" and item.fdb_payload
    }


def test_variant_names_distinct_across_different_vendors(db):
    """Two SM filaments with the same bare color from different vendors → distinct FDB names.

    Before fix: both became "Light Blue" → 409 collision.
    After fix: "Hatchbox PLA Light Blue" vs "SUNLU PLA Light Blue" → no collision.
    """
    hatchbox_lb = _sm_filament_with_vendor(1, "Light Blue", "Hatchbox", "PLA")
    sunlu_lb = _sm_filament_with_vendor(2, "Light Blue", "SUNLU", "PLA")
    decisions = [
        {"spoolman_filament_id": 1, "action": "create"},
        {"spoolman_filament_id": 2, "action": "create"},
    ]
    names = _run_planner_named(db, [hatchbox_lb, sunlu_lb], decisions)

    assert names[1] != names[2], "same-color names from different vendors must be distinct"
    assert "Hatchbox" in names[1] or "hatchbox" in names[1].lower()
    assert "SUNLU" in names[2] or "sunlu" in names[2].lower()
    assert "Light Blue" in names[1]
    assert "Light Blue" in names[2]


def test_variant_name_equals_master_base_plus_color(db):
    """A variant's planned FDB name = master's base name (no marker) + variant's sm.name.

    Master SM: name="Red", material="PLA", vendor="Hatchbox"
    Variant SM: name="Light Blue", material="PLA", vendor="Hatchbox"
    Expected variant name: "Hatchbox PLA Light Blue"
    """
    master = _sm_filament_with_vendor(10, "Red", "Hatchbox", "PLA")
    variant = _sm_filament_with_vendor(11, "Light Blue", "Hatchbox", "PLA")
    decisions = [
        {"spoolman_filament_id": 10, "action": "create"},
        {"spoolman_filament_id": 11, "action": "create"},
    ]
    names = _run_planner_named(
        db, [master, variant], decisions, master_of_sm={11: 10},
    )

    # Both carry vendor+material
    assert names[10] == "Hatchbox PLA Red"
    assert names[11] == "Hatchbox PLA Light Blue"

    # Variant and master share the base ("Hatchbox PLA"); only color differs
    assert names[11].startswith("Hatchbox PLA ")
    assert names[10].startswith("Hatchbox PLA ")


def test_variant_name_shares_base_with_container_display_name(db):
    """Variant base name (no marker) must match what _container_display_name builds (no marker).

    In generic_container mode, the container is "Hatchbox PLA (Master)" and the variants are
    "Hatchbox PLA Red", "Hatchbox PLA Light Blue" — they share the base "Hatchbox PLA".
    The variant's planned name must start with the same base that _container_display_name
    produces (minus the marker).
    """
    from app.api.wizard import _container_display_name

    master = _sm_filament_with_vendor(20, "Red", "Hatchbox", "PLA")
    variant = _sm_filament_with_vendor(21, "Light Blue", "Hatchbox", "PLA")

    # Container display name (what the synthetic parent in generic_container mode gets)
    container_name = _container_display_name([master], [], marker="(Master)")
    container_base = container_name.replace(" (Master)", "")  # strip marker → "Hatchbox PLA"

    decisions = [
        {"spoolman_filament_id": 20, "action": "create"},
        {"spoolman_filament_id": 21, "action": "create"},
    ]
    names = _run_planner_named(db, [master, variant], decisions, master_of_sm={21: 20})

    # The variant name must start with the same base as the container (minus marker)
    assert names[21].startswith(container_base), (
        f"Variant '{names[21]}' does not start with container base '{container_base}'"
    )
    # The master (promote_color mode: the master is itself a color member, e.g. "Red")
    # also starts with the container base (vendor+material), just with its own color.
    assert names[20].startswith(container_base), (
        f"Master '{names[20]}' does not start with container base '{container_base}'"
    )


def test_dedup_guard_sm_name_already_has_vendor_material(db):
    """Dedup guard: sm.name already contains vendor+material → name not doubled."""
    # Spoolman setup stores the full name including vendor+material
    sm = _sm_filament_with_vendor(30, "Hatchbox PLA Light Blue", "Hatchbox", "PLA")
    decisions = [{"spoolman_filament_id": 30, "action": "create"}]
    names = _run_planner_named(db, [sm], decisions)

    # Must not become "Hatchbox PLA Hatchbox PLA Light Blue"
    assert names[30] == "Hatchbox PLA Light Blue"


def test_standalone_created_filament_includes_vendor_material(db):
    """A standalone (no master) created filament always carries vendor + material in its name."""
    sm = _sm_filament_with_vendor(40, "Beige", "SUNLU", "PETG")
    decisions = [{"spoolman_filament_id": 40, "action": "create"}]
    names = _run_planner_named(db, [sm], decisions)

    # Name must include both vendor and material
    assert "SUNLU" in names[40]
    assert "PETG" in names[40]
    assert "Beige" in names[40]


def test_linked_name_not_overridden(db):
    """A 'link' action (standardized/existing FDB filament) must not have its name changed.

    The planner does not set fdb_payload for link items; name patching must be a no-op.
    """
    sm = _sm_filament_with_vendor(50, "Beige", "SUNLU", "PETG")
    fdb_fil = FDBFilament.model_validate({"_id": "fdb-50", "name": "SUNLU PETG Beige"})
    decisions_by_sm = {50: {"spoolman_filament_id": 50, "action": "link", "filamentdb_id": "fdb-50"}}
    plan = _plan_spoolman_to_fdb(
        db,
        sm_filaments=[sm],
        sm_spools=[],
        fdb_filaments=[fdb_fil],
        decisions_by_sm=decisions_by_sm,
        master_of_sm={},
        tare_by_sm_spool={},
    )
    link_item = next(i for i in plan.filament_items if i.action == "link")
    # link items have no fdb_payload — name patching has no effect
    assert link_item.fdb_payload is None


def test_filament_base_name_helper_vendor_material_finish(db):
    """_filament_base_name produces vendor + base_material + finish (capitalized), no color."""
    # Silk finish: material "PLA Silk" → strip to "PLA", then append "Silk"
    result = _filament_base_name("Prusament", "PLA Silk", "Silk Red", variant_keywords=["silk"])
    assert result == "Prusament PLA Silk"

    # No finish: plain PLA
    result = _filament_base_name("Hatchbox", "PLA", "Red", variant_keywords=[])
    assert result == "Hatchbox PLA"

    # No vendor
    result = _filament_base_name(None, "PETG", "Grey", variant_keywords=[])
    assert result == "PETG"


def test_patch_fdb_name_dedup_material_prefix_in_color(db):
    """_patch_fdb_name strips a material prefix from color to avoid doubling.

    e.g. sm.name="PLA Red", base="ELEGOO PLA" → "ELEGOO PLA Red" (not "ELEGOO PLA PLA Red").
    """
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm = SpoolmanFilament(id=1, name="PLA Red", vendor=elegoo, material="PLA", weight=1000.0)
    result = _patch_fdb_name(sm)
    assert result == "ELEGOO PLA Red", f"Expected 'ELEGOO PLA Red', got '{result}'"


def test_patch_fdb_name_plain_color_gets_qualified(db):
    """_patch_fdb_name builds 'Vendor Material Color' when sm.name is just the color."""
    elegoo = SpoolmanVendor(id=1, name="ELEGOO")
    sm = SpoolmanFilament(id=2, name="Light Blue", vendor=elegoo, material="PLA", weight=1000.0)
    result = _patch_fdb_name(sm)
    assert result == "ELEGOO PLA Light Blue"


def test_patch_fdb_name_no_double_finish_word(db):
    """Regression: a Silk variant whose SM name carries the finish ("PLA Silk Pink") must not
    double the finish in the FDB name ("PLA Silk Silk Pink"). The base already includes "Silk",
    so the color suffix drops the leading finish word → "Buddy3D PLA Silk Pink"."""
    buddy = SpoolmanVendor(id=1, name="Buddy3D")
    sm = SpoolmanFilament(id=1, name="PLA Silk Pink", vendor=buddy, material="PLA", weight=1000.0)
    # Derived base path.
    assert _patch_fdb_name(sm, variant_keywords=["silk"]) == "Buddy3D PLA Silk Pink"
    # Explicit master base_name (the variant-attach path) — same result, no double Silk.
    assert _patch_fdb_name(sm, base_name="Buddy3D PLA Silk", variant_keywords=["silk"]) == "Buddy3D PLA Silk Pink"


# ---------------------------------------------------------------------------
# Stale FilamentMapping / SpoolMapping validation
# ---------------------------------------------------------------------------
# When a local mapping exists but its FDB target has been deleted, the planner
# must treat the mapping as stale: route through the normal decision logic
# (create/link instead of skip) and expose the stale mapping for cleanup on
# execute.  When the FDB target still exists, the existing "skip / already
# linked" behaviour must be unchanged.
# ---------------------------------------------------------------------------


def _add_filament_mapping(db, sm_filament_id: int, filamentdb_id: str):
    """Insert a FilamentMapping row and return it."""
    fm = FilamentMapping(spoolman_filament_id=sm_filament_id, filamentdb_id=filamentdb_id)
    db.add(fm)
    db.flush()
    return fm


def _add_spool_mapping(db, sm_spool_id: int, fdb_filament_id: str, fdb_spool_id: str, fil_map_id=None):
    """Insert a SpoolMapping row and return it."""
    sm = SpoolMapping(
        spoolman_spool_id=sm_spool_id,
        filamentdb_filament_id=fdb_filament_id,
        filamentdb_spool_id=fdb_spool_id,
        filament_mapping_id=fil_map_id,
    )
    db.add(sm)
    db.flush()
    return sm


def test_stale_filament_mapping_routes_to_create(db):
    """When a FilamentMapping exists but filamentdb_id is NOT in the live FDB fetch,
    the planner must plan action='create' (not 'skip') and set stale_filament_mapping."""
    sm_fil = _sm_filament(fid=1, name="ELEGOO PLA Red", weight=1000.0)
    sm_sp = _sm_spool(101, sm_fil, remaining=500.0)
    # FDB has no filament with id "deleted-fdb-fil" — the mapping is stale.
    fdb_fil = _make_fdb_filament("live-fdb-fil", ["live-spool-aaa"])
    _add_filament_mapping(db, sm_filament_id=1, filamentdb_id="deleted-fdb-fil")
    db.commit()

    plan = _run_planner(
        db,
        sm_filaments=[sm_fil],
        sm_spools=[sm_sp],
        fdb_filaments=[fdb_fil],
        decisions=[{"spoolman_filament_id": 1, "action": "create"}],
    )

    assert len(plan.filament_items) == 1
    item = plan.filament_items[0]
    assert item.action == "create", (
        f"Expected 'create' for stale mapping, got '{item.action}'"
    )
    assert item.stale_filament_mapping is not None, (
        "stale_filament_mapping must be set so execute can clean it up"
    )
    assert item.stale_filament_mapping.filamentdb_id == "deleted-fdb-fil"


def test_valid_filament_mapping_still_skips(db):
    """When a FilamentMapping exists and filamentdb_id IS in the live FDB fetch,
    the planner must keep the existing 'skip / already linked' behaviour."""
    sm_fil = _sm_filament(fid=2, name="ELEGOO PLA Blue", weight=1000.0)
    sm_sp = _sm_spool(102, sm_fil, remaining=500.0)
    # FDB has the filament the mapping points to — mapping is valid.
    fdb_fil = _make_fdb_filament("still-valid-fdb-fil", ["spool-xyz"])
    _add_filament_mapping(db, sm_filament_id=2, filamentdb_id="still-valid-fdb-fil")
    db.commit()

    plan = _run_planner(
        db,
        sm_filaments=[sm_fil],
        sm_spools=[sm_sp],
        fdb_filaments=[fdb_fil],
        decisions=[{"spoolman_filament_id": 2, "action": "create"}],
    )

    assert len(plan.filament_items) == 1
    item = plan.filament_items[0]
    assert item.action == "skip", (
        f"Expected 'skip' for valid mapping, got '{item.action}'"
    )
    assert item.detail == "already linked"
    assert item.stale_filament_mapping is None


def test_stale_spool_mapping_routes_to_create(db):
    """When a SpoolMapping exists but filamentdb_spool_id is NOT in the live FDB spool ids,
    the planner must plan action='create' (not 'skip') and set stale_spool_mapping."""
    sm_fil = _sm_filament(fid=3, name="ELEGOO PLA Green", weight=1000.0)
    sm_sp = _sm_spool(103, sm_fil, remaining=400.0)
    # FDB has a filament but with a DIFFERENT spool id (simulates user deleting the spool).
    fdb_fil = _make_fdb_filament("fdb-fil-3", ["current-spool-bbb"])
    # SpoolMapping points to a spool that no longer exists in FDB.
    _add_spool_mapping(db, sm_spool_id=103, fdb_filament_id="fdb-fil-3",
                       fdb_spool_id="deleted-fdb-spool")
    db.commit()

    plan = _run_planner(
        db,
        sm_filaments=[sm_fil],
        sm_spools=[sm_sp],
        fdb_filaments=[fdb_fil],
        decisions=[{"spoolman_filament_id": 3, "action": "create"}],
    )

    spool_items = [si for si in plan.spool_items if si.sm_spool.id == 103]
    assert len(spool_items) == 1, f"Expected 1 spool item for SM spool 103, got {len(spool_items)}"
    si = spool_items[0]
    assert si.action == "create", (
        f"Expected 'create' for stale spool mapping, got '{si.action}'"
    )
    assert si.stale_spool_mapping is not None, (
        "stale_spool_mapping must be set so execute can clean it up"
    )
    assert si.stale_spool_mapping.filamentdb_spool_id == "deleted-fdb-spool"


def test_valid_spool_mapping_still_skips(db):
    """When a SpoolMapping exists and filamentdb_spool_id IS in the live FDB spool ids,
    the planner must keep the existing 'skip / already linked' behaviour."""
    sm_fil = _sm_filament(fid=4, name="ELEGOO PLA White", weight=1000.0)
    sm_sp = _sm_spool(104, sm_fil, remaining=600.0)
    # FDB has the spool the mapping points to — mapping is valid.
    fdb_fil = _make_fdb_filament("fdb-fil-4", ["live-fdb-spool-ccc"])
    _add_spool_mapping(db, sm_spool_id=104, fdb_filament_id="fdb-fil-4",
                       fdb_spool_id="live-fdb-spool-ccc")
    db.commit()

    plan = _run_planner(
        db,
        sm_filaments=[sm_fil],
        sm_spools=[sm_sp],
        fdb_filaments=[fdb_fil],
        decisions=[{"spoolman_filament_id": 4, "action": "create"}],
    )

    spool_items = [si for si in plan.spool_items if si.sm_spool.id == 104]
    assert len(spool_items) == 1
    si = spool_items[0]
    assert si.action == "skip", (
        f"Expected 'skip' for valid spool mapping, got '{si.action}'"
    )
    assert si.stale_spool_mapping is None


def test_stale_filament_mapping_execute_replaces_mapping(db):
    """Execute: stale FilamentMapping is deleted; fresh mapping is written; no orphan remains.

    Uses the wizard execute endpoint (via TestClient) to verify end-to-end that:
    1. The stale FilamentMapping is removed.
    2. A fresh FilamentMapping pointing to the newly-created FDB filament is written.
    3. No orphan row is left behind (exactly one FilamentMapping after execute).
    """
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions",
                     [{"spoolman_filament_id": 5, "action": "create"}])
    db.commit()

    sm_fil = SpoolmanFilament(
        id=5, name="ELEGOO PLA Yellow",
        vendor=SpoolmanVendor(id=1, name="ELEGOO"), material="PLA", weight=1000.0,
        spool_weight=200.0,  # provide tare so execute is not rejected
    )
    sm_sp = SpoolmanSpool(id=501, filament=sm_fil, remaining_weight=750.0, archived=False, extra={})
    # FDB has no filament matching the stale mapping target ("old-fdb-fil").
    fdb_fil_new = _make_fdb_filament("brand-new-fdb-fil", ["new-spool-ddd"])

    spoolman_client = AsyncMock()
    spoolman_client.get_filaments = AsyncMock(return_value=[sm_fil])
    spoolman_client.get_spools = AsyncMock(return_value=[sm_sp])
    spoolman_client.update_spool = AsyncMock(return_value=None)
    spoolman_client.get_field_definitions = AsyncMock(return_value=[])

    created_fdb_fil = MagicMock()
    created_fdb_fil.id = "brand-new-fdb-fil"

    filamentdb_client = AsyncMock()
    filamentdb_client.get_filaments = AsyncMock(return_value=[fdb_fil_new])
    filamentdb_client.get_filament = AsyncMock(return_value=None)
    filamentdb_client.get_version = AsyncMock(return_value="1.33.0")
    filamentdb_client.create_filament = AsyncMock(return_value=created_fdb_fil)
    filamentdb_client.create_spool = AsyncMock(return_value={"_id": "new-spool-exec"})
    filamentdb_client.get_locations = AsyncMock(return_value=[])

    # Seed the stale FilamentMapping (points to "old-fdb-fil" which is NOT in FDB).
    stale_fm = FilamentMapping(spoolman_filament_id=5, filamentdb_id="old-fdb-fil")
    db.add(stale_fm)
    db.commit()

    app = FastAPI()
    app.include_router(wizard.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.state.spoolman = spoolman_client
    app.state.filamentdb = filamentdb_client
    client = TestClient(app)

    resp = client.post("/api/wizard/execute")
    assert resp.status_code == 200
    body = resp.json()
    assert body["failed"] == 0

    # Stale mapping must be gone; a fresh one pointing to the new FDB id must exist.
    # NOTE: SQLite may re-use id=1 after DELETE+INSERT on an empty table, so we
    # check the filamentdb_id value, not the row id.
    all_maps = db.query(FilamentMapping).filter_by(is_synthetic_parent=False).all()
    assert len(all_maps) == 1, f"Expected exactly 1 FilamentMapping, got {len(all_maps)}"
    fresh = all_maps[0]
    assert fresh.filamentdb_id == "brand-new-fdb-fil", (
        f"Fresh mapping should point to 'brand-new-fdb-fil' (stale 'old-fdb-fil' must be "
        f"gone), got '{fresh.filamentdb_id}'"
    )
    assert fresh.spoolman_filament_id == 5, (
        f"Fresh mapping should be for SM filament 5, got {fresh.spoolman_filament_id}"
    )


def test_stale_spool_mapping_execute_replaces_mapping(db):
    """Execute: stale SpoolMapping is deleted; fresh mapping is written; no orphan remains.

    Verifies end-to-end that after execute with a stale SpoolMapping:
    1. The stale SpoolMapping is removed.
    2. A fresh SpoolMapping is written with the new FDB spool id.
    3. Exactly one SpoolMapping row remains after execute.
    """
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions",
                     [{"spoolman_filament_id": 6, "action": "create"}])
    db.commit()

    sm_fil = SpoolmanFilament(
        id=6, name="ELEGOO PLA Orange",
        vendor=SpoolmanVendor(id=1, name="ELEGOO"), material="PLA", weight=1000.0,
        spool_weight=200.0,  # provide tare so execute is not rejected
    )
    sm_sp = SpoolmanSpool(id=601, filament=sm_fil, remaining_weight=800.0, archived=False, extra={})
    # FDB has a filament with a spool "current-spool-eee" (not the stale "old-spool-fff").
    fdb_fil = _make_fdb_filament("fdb-fil-6", ["current-spool-eee"])

    spoolman_client = AsyncMock()
    spoolman_client.get_filaments = AsyncMock(return_value=[sm_fil])
    spoolman_client.get_spools = AsyncMock(return_value=[sm_sp])
    spoolman_client.update_spool = AsyncMock(return_value=None)
    spoolman_client.get_field_definitions = AsyncMock(return_value=[])

    created_fdb_fil = MagicMock()
    created_fdb_fil.id = "fdb-fil-6"

    filamentdb_client = AsyncMock()
    filamentdb_client.get_filaments = AsyncMock(return_value=[fdb_fil])
    filamentdb_client.get_filament = AsyncMock(return_value=None)
    filamentdb_client.get_version = AsyncMock(return_value="1.33.0")
    filamentdb_client.create_filament = AsyncMock(return_value=created_fdb_fil)
    filamentdb_client.create_spool = AsyncMock(return_value={"_id": "fresh-spool-zzz"})
    filamentdb_client.get_locations = AsyncMock(return_value=[])

    # Seed the stale SpoolMapping (points to "old-spool-fff" which is NOT in FDB).
    stale_sm = SpoolMapping(
        spoolman_spool_id=601,
        filamentdb_filament_id="fdb-fil-6",
        filamentdb_spool_id="old-spool-fff",
    )
    db.add(stale_sm)
    db.commit()

    app = FastAPI()
    app.include_router(wizard.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.state.spoolman = spoolman_client
    app.state.filamentdb = filamentdb_client
    client = TestClient(app)

    resp = client.post("/api/wizard/execute")
    assert resp.status_code == 200
    body = resp.json()
    assert body["failed"] == 0

    # Stale spool mapping must be gone; a fresh one with the new FDB spool id must exist.
    # NOTE: SQLite may re-use id=1 after DELETE+INSERT on an empty table, so we
    # check the filamentdb_spool_id value, not the row id.
    all_spool_maps = db.query(SpoolMapping).all()
    assert len(all_spool_maps) == 1, f"Expected exactly 1 SpoolMapping, got {len(all_spool_maps)}"
    fresh = all_spool_maps[0]
    assert fresh.filamentdb_spool_id == "fresh-spool-zzz", (
        f"Fresh spool mapping should point to 'fresh-spool-zzz' (stale 'old-spool-fff' should "
        f"be gone), got '{fresh.filamentdb_spool_id}'"
    )
    assert fresh.spoolman_spool_id == 601, (
        f"Fresh spool mapping should be for SM spool 601, got {fresh.spoolman_spool_id}"
    )


# ---------------------------------------------------------------------------
# Archived-spool fix — SM filament 63 / spool 65 scenario (never_import_empties)
# ---------------------------------------------------------------------------
# SM spool #65: archived=True, used_weight=1047.98, initial_weight=1000.0 →
# remaining_weight = 1000 - 1047.98 = -47.98 (negative; used more than initial).
# This mirrors the real-world "Light Purple PLA" case.


def _sm_spool_archived(
    sid: int,
    filament: SpoolmanFilament,
    remaining: float = -47.98,
    archived: bool = True,
) -> SpoolmanSpool:
    """Build a SpoolmanSpool fixture mirroring the SM #65 (archived, negative remaining)."""
    return SpoolmanSpool(
        id=sid,
        filament=filament,
        initial_weight=1000.0,
        remaining_weight=remaining,
        archived=archived,
        extra={},
    )


# ---- test 1: planner includes archived empty spool → plan item create, retired=True ----


def test_planner_archived_empty_spool_creates_retired_plan_item(db):
    """Archived spool with negative remaining is planned as create (retired=True)
    when include_empty_spools=True (never_import_empties=False, the default)."""
    sm_fil = _sm_filament(fid=63, name="Light Purple PLA", weight=1000.0)
    sm_sp = _sm_spool_archived(65, sm_fil, remaining=-47.98, archived=True)

    decisions_by_sm = {63: {"spoolman_filament_id": 63, "action": "create"}}
    plan = _plan_spoolman_to_fdb(
        db,
        sm_filaments=[sm_fil],
        sm_spools=[sm_sp],
        fdb_filaments=[],
        decisions_by_sm=decisions_by_sm,
        master_of_sm={},
        tare_by_sm_spool={},
        include_empty_spools=True,  # never_import_empties=False → include empties
    )

    assert len(plan.spool_items) == 1, (
        f"Expected 1 spool item for archived spool, got {len(plan.spool_items)}"
    )
    si = plan.spool_items[0]
    assert si.action == "create", (
        f"Archived spool with include_empty=True must be planned as 'create', got '{si.action}'"
    )
    assert si.retired is True, (
        "Archived SM spool must set retired=True on the plan item"
    )


# ---- test 2: never_import_empties=True skips archived empty spool ----


def test_planner_archived_empty_spool_skipped_when_never_import_empties(db):
    """Archived spool with negative remaining is skipped when include_empty_spools=False."""
    sm_fil = _sm_filament(fid=63, name="Light Purple PLA", weight=1000.0)
    sm_sp_archived = _sm_spool_archived(65, sm_fil, remaining=-47.98, archived=True)
    # Also add an active empty spool to confirm it is also skipped
    sm_sp_active_empty = _sm_spool(66, sm_fil, remaining=0.0)

    decisions_by_sm = {63: {"spoolman_filament_id": 63, "action": "create"}}
    plan = _plan_spoolman_to_fdb(
        db,
        sm_filaments=[sm_fil],
        sm_spools=[sm_sp_archived, sm_sp_active_empty],
        fdb_filaments=[],
        decisions_by_sm=decisions_by_sm,
        master_of_sm={},
        tare_by_sm_spool={},
        include_empty_spools=False,  # never_import_empties=True → skip empties
    )

    # Both spools have remaining <= 0 → both skipped
    assert len(plan.spool_items) == 0, (
        f"Expected 0 spool items when never_import_empties=True, got {len(plan.spool_items)}"
    )
    # ...and the FILAMENT itself is skipped (no spool-less half-synced record).
    fil = next(i for i in plan.filament_items if i.sm_filament.id == 63)
    assert fil.action == "skip", (
        f"filament with no importable spool must be skipped, got '{fil.action}'"
    )
    assert fil.resolved is False


def test_planner_filament_with_one_nonempty_spool_still_created(db):
    """Control: a filament with at least one importable (non-empty) spool is still CREATED when
    never_import_empties is ON — only the empty siblings are skipped. Guards against over-skipping."""
    sm_fil = _sm_filament(fid=63, name="Light Purple PLA", weight=1000.0)
    empty = _sm_spool_archived(65, sm_fil, remaining=-47.98, archived=True)
    full = _sm_spool(66, sm_fil, remaining=500.0)

    decisions_by_sm = {63: {"spoolman_filament_id": 63, "action": "create"}}
    plan = _plan_spoolman_to_fdb(
        db,
        sm_filaments=[sm_fil],
        sm_spools=[empty, full],
        fdb_filaments=[],
        decisions_by_sm=decisions_by_sm,
        master_of_sm={},
        tare_by_sm_spool={},
        include_empty_spools=False,
    )
    fil = next(i for i in plan.filament_items if i.sm_filament.id == 63)
    assert fil.action == "create", "filament with an importable spool must still be created"
    assert any(si.action == "create" for si in plan.spool_items), "the non-empty spool imports"


# ---- test 3: active empty spool → retired=False when imported ----


def test_planner_active_empty_spool_not_retired(db):
    """An active (non-archived) spool with zero remaining imports with retired=False."""
    sm_fil = _sm_filament(fid=70, name="PLA Active Empty", weight=1000.0)
    sm_sp = _sm_spool(70, sm_fil, remaining=0.0)  # active, archived=False

    decisions_by_sm = {70: {"spoolman_filament_id": 70, "action": "create"}}
    plan = _plan_spoolman_to_fdb(
        db,
        sm_filaments=[sm_fil],
        sm_spools=[sm_sp],
        fdb_filaments=[],
        decisions_by_sm=decisions_by_sm,
        master_of_sm={},
        tare_by_sm_spool={},
        include_empty_spools=True,
    )

    assert len(plan.spool_items) == 1
    si = plan.spool_items[0]
    assert si.action == "create"
    assert si.retired is False, (
        "Active (non-archived) spool must set retired=False"
    )


# ---- test 4: archived non-empty spool → creates as retired ----


def test_planner_archived_nonempty_spool_creates_as_retired(db):
    """An archived spool with positive remaining weight still imports as retired (O1)."""
    sm_fil = _sm_filament(fid=80, name="PLA Archived NonEmpty", weight=1000.0)
    # archived but still has 200g remaining
    sm_sp = _sm_spool_archived(80, sm_fil, remaining=200.0, archived=True)

    decisions_by_sm = {80: {"spoolman_filament_id": 80, "action": "create"}}
    plan = _plan_spoolman_to_fdb(
        db,
        sm_filaments=[sm_fil],
        sm_spools=[sm_sp],
        fdb_filaments=[],
        decisions_by_sm=decisions_by_sm,
        master_of_sm={},
        tare_by_sm_spool={},
        include_empty_spools=False,  # never_import_empties=True — but 200g > 0, so not skipped
    )

    # remaining > 0 → not skipped by the empty gate, even when never_import_empties=True
    assert len(plan.spool_items) == 1
    si = plan.spool_items[0]
    assert si.action == "create"
    assert si.retired is True, (
        "Archived spool (even non-empty) must import as retired (O1)"
    )


# ---- test 5: execute creates FDB spool with retired=True + SpoolMapping exists ----


def test_execute_archived_spool_imports_as_retired_with_mapping(db):
    """Execute: archived SM spool creates FDB spool with retired=True and a SpoolMapping.

    End-to-end: after execute, SpoolMapping exists → filament appears in Synced Records.
    """
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions",
                     [{"spoolman_filament_id": 63, "action": "create"}])
    db.commit()

    sm_fil = SpoolmanFilament(
        id=63, name="Light Purple PLA",
        vendor=SpoolmanVendor(id=1, name="ACME"), material="PLA", weight=1000.0,
        spool_weight=200.0,  # provide tare so execute is not rejected
    )
    # Mirror SM spool #65: archived, negative remaining (used > initial)
    sm_sp = SpoolmanSpool(
        id=65, filament=sm_fil, initial_weight=1000.0,
        remaining_weight=-47.98, archived=True, extra={},
    )

    spoolman_client = AsyncMock()
    spoolman_client.get_filaments = AsyncMock(return_value=[sm_fil])
    spoolman_client.get_spools = AsyncMock(return_value=[sm_sp])
    spoolman_client.update_spool = AsyncMock(return_value=None)
    spoolman_client.get_field_definitions = AsyncMock(return_value=[])

    created_fdb_fil = MagicMock()
    created_fdb_fil.id = "fdb-fil-63"

    filamentdb_client = AsyncMock()
    filamentdb_client.get_filaments = AsyncMock(return_value=[])
    filamentdb_client.get_version = AsyncMock(return_value="1.33.0")
    filamentdb_client.create_filament = AsyncMock(return_value=created_fdb_fil)
    # create_spool returns the raw FDB response dict; retired flag must be in the call
    filamentdb_client.create_spool = AsyncMock(return_value={"_id": "fdb-spool-65"})
    filamentdb_client.get_locations = AsyncMock(return_value=[])

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import wizard
    from app.db import get_db

    app = FastAPI()
    app.include_router(wizard.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.state.spoolman = spoolman_client
    app.state.filamentdb = filamentdb_client
    client = TestClient(app)

    resp = client.post("/api/wizard/execute")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["failed"] == 0, f"Expected 0 failures, got {body['failed']}: {body['records']}"

    # SpoolMapping must exist (this is what makes the filament appear in Synced Records)
    all_spool_maps = db.query(SpoolMapping).all()
    assert len(all_spool_maps) == 1, (
        f"Expected exactly 1 SpoolMapping after importing archived spool, got {len(all_spool_maps)}"
    )
    sm_map = all_spool_maps[0]
    assert sm_map.spoolman_spool_id == 65
    assert sm_map.filamentdb_spool_id == "fdb-spool-65"

    # FDB create_spool must have been called with retired=True
    call_args = filamentdb_client.create_spool.call_args
    assert call_args is not None, "create_spool was never called"
    spool_payload = call_args[0][1]  # positional: (fdb_id, spool_payload)
    assert spool_payload.get("retired") is True, (
        f"FDB spool payload must have retired=True for archived SM spool; got: {spool_payload}"
    )

    # The execute record detail must mention "retired"
    spool_records = [r for r in body["records"] if r["entity_type"] == "spool" and r["action"] == "created"]
    assert len(spool_records) >= 1
    assert spool_records[0]["detail"] is not None
    assert "retired" in spool_records[0]["detail"], (
        f"Execute record detail must mention 'retired'; got: {spool_records[0]['detail']}"
    )


# ---- test 6: never_import_empties=True → no create_spool / SpoolMapping for #65 ----


def test_execute_never_import_empties_skips_archived_empty(db):
    """Execute with never_import_empties=True: archived empty spool is not created in FDB."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "never_import_empties", True)
    set_config_value(db, "wizard_match_decisions",
                     [{"spoolman_filament_id": 63, "action": "create"}])
    db.commit()

    sm_fil = SpoolmanFilament(
        id=63, name="Light Purple PLA",
        vendor=SpoolmanVendor(id=1, name="ACME"), material="PLA", weight=1000.0,
    )
    sm_sp = SpoolmanSpool(
        id=65, filament=sm_fil, initial_weight=1000.0,
        remaining_weight=-47.98, archived=True, extra={},
    )

    spoolman_client = AsyncMock()
    spoolman_client.get_filaments = AsyncMock(return_value=[sm_fil])
    spoolman_client.get_spools = AsyncMock(return_value=[sm_sp])
    spoolman_client.update_spool = AsyncMock(return_value=None)
    spoolman_client.get_field_definitions = AsyncMock(return_value=[])

    created_fdb_fil = MagicMock()
    created_fdb_fil.id = "fdb-fil-63"

    filamentdb_client = AsyncMock()
    filamentdb_client.get_filaments = AsyncMock(return_value=[])
    filamentdb_client.get_version = AsyncMock(return_value="1.33.0")
    filamentdb_client.create_filament = AsyncMock(return_value=created_fdb_fil)
    filamentdb_client.create_spool = AsyncMock(return_value={"_id": "fdb-spool-65"})
    filamentdb_client.get_locations = AsyncMock(return_value=[])

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import wizard
    from app.db import get_db

    app = FastAPI()
    app.include_router(wizard.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.state.spoolman = spoolman_client
    app.state.filamentdb = filamentdb_client
    client = TestClient(app)

    resp = client.post("/api/wizard/execute")
    assert resp.status_code == 200, resp.text

    # No spool created in FDB
    filamentdb_client.create_spool.assert_not_called()
    # No SpoolMapping
    all_spool_maps = db.query(SpoolMapping).all()
    assert len(all_spool_maps) == 0, (
        f"Expected 0 SpoolMappings when never_import_empties=True, got {len(all_spool_maps)}"
    )


# ---- test 7: _compute_empty_active includes archived entry with archived=True ----


def test_compute_empty_active_includes_archived():
    """_compute_empty_active emits entries for empty active spools AND archived spools.

    Archived spools must have archived=True; active-empty have archived=False.
    """
    from app.api.wizard import _compute_empty_active

    sm_fil = MagicMock()
    sm_fil.id = 1
    sm_fil.name = "PLA"

    # Active, fully depleted
    active_empty = MagicMock()
    active_empty.id = 10
    active_empty.filament = sm_fil
    active_empty.remaining_weight = 0.0
    active_empty.archived = False

    # Archived, also depleted (negative remaining)
    archived_empty = MagicMock()
    archived_empty.id = 65
    archived_empty.filament = sm_fil
    archived_empty.remaining_weight = -47.98
    archived_empty.archived = True

    # Archived, non-empty (still archived → must appear)
    archived_nonempty = MagicMock()
    archived_nonempty.id = 66
    archived_nonempty.filament = sm_fil
    archived_nonempty.remaining_weight = 200.0
    archived_nonempty.archived = True

    # Active, non-empty → must NOT appear
    active_nonempty = MagicMock()
    active_nonempty.id = 99
    active_nonempty.filament = sm_fil
    active_nonempty.remaining_weight = 500.0
    active_nonempty.archived = False

    result = _compute_empty_active([active_empty, archived_empty, archived_nonempty, active_nonempty])

    ids = {e.spoolman_spool_id for e in result}
    assert 10 in ids, "active-empty spool must appear"
    assert 65 in ids, "archived-empty spool must appear"
    assert 66 in ids, "archived-nonempty spool must appear"
    assert 99 not in ids, "active-nonempty spool must NOT appear"

    # archived flag must be set correctly
    archived_entries = {e.spoolman_spool_id: e.archived for e in result}
    assert archived_entries[10] is False, "active-empty must have archived=False"
    assert archived_entries[65] is True, "archived-empty must have archived=True"
    assert archived_entries[66] is True, "archived-nonempty must have archived=True"
