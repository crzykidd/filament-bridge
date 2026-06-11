"""Tests for core/dryrun.py — unified matcher-driven dry-run plan."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.config import set_config_value
from app.config import settings
from app.core.dryrun import plan_dry_run
from app.core.engine import run_sync_cycle
from app.models.mapping import FilamentMapping, SpoolMapping
from app.models.snapshot import Snapshot
from app.schemas.filamentdb import FDBFilament
from app.schemas.spoolman import SpoolmanFilament, SpoolmanSpool, SpoolmanVendor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sm_filament(fid: int, name: str, vendor: str = "ACME", color: str = "#FF0000") -> SpoolmanFilament:
    return SpoolmanFilament(
        id=fid, name=name,
        vendor=SpoolmanVendor(id=fid, name=vendor),
        color_hex=color,
        material="PLA",
    )


def _sm_spool(sid: int, filament: SpoolmanFilament, remaining: float = 200.0, extra: dict | None = None) -> SpoolmanSpool:
    return SpoolmanSpool(
        id=sid, filament=filament, remaining_weight=remaining,
        archived=False, extra=extra or {},
    )


def _fdb_filament(fid: str, name: str, vendor: str = "ACME", color: str = "#FF0000") -> FDBFilament:
    return FDBFilament.model_validate({
        "_id": fid,
        "name": name,
        "vendor": vendor,
        "color": color,
        "spoolWeight": 200.0,
        "spools": [],
    })


def _xref_extra(fdb_spool_id: str) -> dict:
    """SM spool extra dict with the filamentdb_spool_id cross-ref set."""
    return {settings.spoolman_field_filamentdb_spool_id: json.dumps(fdb_spool_id)}


def _fake_spoolman(spools=None, filaments=None) -> AsyncMock:
    client = AsyncMock()
    client.get_spools = AsyncMock(return_value=spools or [])
    client.get_filaments = AsyncMock(return_value=filaments or [])
    client.get_field_definitions = AsyncMock(return_value=[])
    # These should never be called in a dry-run
    client.create_spool = AsyncMock(side_effect=AssertionError("no writes in dry-run"))
    client.update_spool = AsyncMock(side_effect=AssertionError("no writes in dry-run"))
    client.create_filament = AsyncMock(side_effect=AssertionError("no writes in dry-run"))
    return client


def _fake_filamentdb(filaments=None) -> AsyncMock:
    client = AsyncMock()
    client.get_filaments = AsyncMock(return_value=filaments or [])
    client.get_filament = AsyncMock(return_value=None)
    client.get_version = AsyncMock(return_value="1.33.0")
    # These should never be called in a dry-run
    client.create_spool = AsyncMock(side_effect=AssertionError("no writes in dry-run"))
    client.update_spool = AsyncMock(side_effect=AssertionError("no writes in dry-run"))
    client.create_filament = AsyncMock(side_effect=AssertionError("no writes in dry-run"))
    client.log_usage = AsyncMock(side_effect=AssertionError("no writes in dry-run"))
    return client


def _seed_spool_mapping(db, sm_spool_id, fdb_filament_id, fdb_spool_id, sm_filament_id=None):
    fil_map = db.query(FilamentMapping).filter_by(spoolman_filament_id=sm_filament_id or 0).first()
    if fil_map is None and sm_filament_id:
        fil_map = FilamentMapping(
            spoolman_filament_id=sm_filament_id,
            filamentdb_id=fdb_filament_id,
        )
        db.add(fil_map)
        db.flush()
    mapping = SpoolMapping(
        spoolman_spool_id=sm_spool_id,
        filamentdb_filament_id=fdb_filament_id,
        filamentdb_spool_id=fdb_spool_id,
        filament_mapping_id=fil_map.id if fil_map else None,
    )
    db.add(mapping)
    db.flush()
    return mapping


def _seed_snapshot(db, source, entity_id, data: dict):
    db.add(Snapshot(
        source=source, entity_type="spool", entity_id=entity_id,
        data=json.dumps(data),
    ))
    db.flush()


# ---------------------------------------------------------------------------
# Empty bridge (no mappings) — primary scenario from the handoff
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_bridge_unmatched_sm_creates(db):
    """Unmatched SM filament (no FDB counterpart) → create entries."""
    sm_fil = _sm_filament(1, "PLA Blue", vendor="ACME", color="#0000FF")
    sm_sp = _sm_spool(1, sm_fil)
    # FDB has a different filament that won't match
    fdb_fil = _fdb_filament("fdb1", "PETG Red", vendor="ACME", color="#FF0000")

    sm = _fake_spoolman(spools=[sm_sp], filaments=[sm_fil])
    fdb = _fake_filamentdb(filaments=[fdb_fil])

    result = await plan_dry_run(db, sm, fdb)

    creates = [p for p in result.preview if p["action"] == "create"]
    assert len(creates) >= 2, "expected filament create + spool create"
    assert result.created >= 2
    assert result.conflicts == 0  # no ambiguous matches
    assert all(p["label"] for p in result.preview), "every entry must have a label"


@pytest.mark.asyncio
async def test_empty_bridge_matched_sm_updates(db):
    """SM filament that matches an existing FDB filament → update (link) entries."""
    sm_fil = _sm_filament(1, "PLA Red", vendor="ACME", color="#FF0000")
    sm_sp = _sm_spool(1, sm_fil)
    fdb_fil = _fdb_filament("fdb1", "PLA Red", vendor="acme", color="#FF0000")  # same normalized key

    sm = _fake_spoolman(spools=[sm_sp], filaments=[sm_fil])
    fdb = _fake_filamentdb(filaments=[fdb_fil])

    result = await plan_dry_run(db, sm, fdb)

    fil_updates = [p for p in result.preview if p["action"] == "update" and p["entity_type"] == "filament"]
    assert len(fil_updates) >= 1
    assert fil_updates[0]["fdb_filament_id"] == "fdb1"
    assert result.conflicts == 0
    assert result.created >= 1  # spool is still a create (no SpoolMapping)


@pytest.mark.asyncio
async def test_empty_bridge_ambiguous_conflicts(db):
    """Two FDB filaments with same key as one SM filament → conflict with candidates."""
    sm_fil = _sm_filament(1, "PLA Black", vendor="ACME", color="#000000")
    sm_sp = _sm_spool(1, sm_fil)
    # Two FDB filaments that both match the SM key
    fdb_a = _fdb_filament("fdb1", "PLA Black", vendor="acme", color="#000000")
    fdb_b = _fdb_filament("fdb2", "PLA Black", vendor="acme", color="#000000")

    sm = _fake_spoolman(spools=[sm_sp], filaments=[sm_fil])
    fdb = _fake_filamentdb(filaments=[fdb_a, fdb_b])

    result = await plan_dry_run(db, sm, fdb)

    conflicts = [p for p in result.preview if p["action"] == "conflict"]
    assert len(conflicts) >= 1
    # At least one conflict entry has candidates
    with_candidates = [c for c in conflicts if c.get("candidates") and len(c["candidates"]) >= 2]
    assert len(with_candidates) >= 1
    assert result.conflicts >= 1
    assert result.created == 0  # ambiguous → no auto-create


# ---------------------------------------------------------------------------
# Cross-ref orphan handling (the "167" scenario)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_ref_orphan_bucketed_as_update(db):
    """SM spool with xref extra but no SpoolMapping → update, not silently dropped."""
    sm_fil = _sm_filament(1, "PLA Red")
    sm_sp = _sm_spool(1, sm_fil, extra=_xref_extra("fdb-spool-123"))

    sm = _fake_spoolman(spools=[sm_sp], filaments=[sm_fil])
    fdb = _fake_filamentdb(filaments=[])

    result = await plan_dry_run(db, sm, fdb)

    orphan_updates = [
        p for p in result.preview
        if p["action"] == "update" and p.get("reason") == "re-link from existing cross-ref"
    ]
    assert len(orphan_updates) == 1
    assert orphan_updates[0]["spoolman_id"] == 1
    assert orphan_updates[0]["fdb_spool_id"] == "fdb-spool-123"
    # Must NOT appear as a conflict
    assert all(p["action"] != "conflict" or p.get("field") != "new_spool"
               for p in result.preview)


@pytest.mark.asyncio
async def test_cross_ref_orphan_not_double_counted(db):
    """Cross-ref orphan spool must NOT also appear as a create from the planner."""
    sm_fil = _sm_filament(1, "PLA Red")
    sm_sp = _sm_spool(1, sm_fil, extra=_xref_extra("fdb-spool-xyz"))

    sm = _fake_spoolman(spools=[sm_sp], filaments=[sm_fil])
    fdb = _fake_filamentdb(filaments=[])

    result = await plan_dry_run(db, sm, fdb)

    spool_entries = [p for p in result.preview if p.get("spoolman_id") == 1]
    actions = [p["action"] for p in spool_entries]
    assert actions.count("update") == 1
    assert "create" not in actions  # must not also appear as create


# ---------------------------------------------------------------------------
# Already-linked pair diff (steady-state)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_already_linked_no_change_skipped(db):
    """Already-linked pair with no weight change → skipped."""
    sm_fil = _sm_filament(1, "PLA")
    sm_sp = _sm_spool(1, sm_fil, remaining=200.0)

    fil_map = FilamentMapping(spoolman_filament_id=1, filamentdb_id="fdb1")
    db.add(fil_map)
    db.flush()
    spool_map = SpoolMapping(
        spoolman_spool_id=1, filamentdb_filament_id="fdb1", filamentdb_spool_id="sp1",
        filament_mapping_id=fil_map.id,
    )
    db.add(spool_map)
    db.flush()

    # Seed snapshots so the diff has a baseline (no change)
    _seed_snapshot(db, "spoolman", "1", {"remaining_weight": 200.0, "id": 1, "filament": {"id": 1}})
    _seed_snapshot(db, "filamentdb", "sp1", {"_id": "sp1", "totalWeight": 400.0, "retired": False})

    fdb_fil_with_spool = FDBFilament.model_validate({
        "_id": "fdb1", "name": "PLA", "vendor": "ACME", "color": "#FF0000",
        "spoolWeight": 200.0,
        "spools": [{"_id": "sp1", "totalWeight": 400.0, "retired": False}],
    })
    sm = _fake_spoolman(spools=[sm_sp], filaments=[sm_fil])
    fdb = _fake_filamentdb(filaments=[fdb_fil_with_spool])

    result = await plan_dry_run(db, sm, fdb)

    # The engine omits no-change pairs from the dry-run preview entirely (no entry, no counter).
    # Verify no update or conflict was generated for this pair.
    pair_entries = [p for p in result.preview if p.get("spoolman_id") == 1]
    assert all(p["action"] not in ("update", "conflict") for p in pair_entries), \
        f"no-change pair must not produce update/conflict: {pair_entries}"


@pytest.mark.asyncio
async def test_already_linked_weight_change_updated(db):
    """Already-linked pair with one-sided SM weight change → updated."""
    sm_fil = _sm_filament(1, "PLA")
    sm_sp = _sm_spool(1, sm_fil, remaining=150.0)  # changed from 200
    fdb_fil_with_spool = FDBFilament.model_validate({
        "_id": "fdb1", "name": "PLA", "vendor": "ACME", "color": "#FF0000",
        "spoolWeight": 200.0,
        "spools": [{"_id": "sp1", "totalWeight": 400.0, "retired": False}],
    })

    fil_map = FilamentMapping(spoolman_filament_id=1, filamentdb_id="fdb1")
    db.add(fil_map)
    db.flush()
    spool_map = SpoolMapping(
        spoolman_spool_id=1, filamentdb_filament_id="fdb1", filamentdb_spool_id="sp1",
        filament_mapping_id=fil_map.id,
    )
    db.add(spool_map)
    db.flush()

    # SM snapshot shows old weight 200 → current 150 = SM changed
    _seed_snapshot(db, "spoolman", "1", {"remaining_weight": 200.0, "id": 1, "filament": {"id": 1}})
    # FDB snapshot unchanged
    _seed_snapshot(db, "filamentdb", "sp1", {"_id": "sp1", "totalWeight": 400.0, "retired": False})

    sm = _fake_spoolman(spools=[sm_sp], filaments=[sm_fil])
    fdb = _fake_filamentdb(filaments=[fdb_fil_with_spool])

    result = await plan_dry_run(db, sm, fdb)

    updates = [p for p in result.preview if p["action"] == "update" and p.get("spoolman_id") == 1]
    assert len(updates) >= 1
    assert result.updated >= 1


# ---------------------------------------------------------------------------
# Invariant checks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_entry_has_action_and_label(db):
    """Every preview entry must have a non-None action and non-empty label."""
    sm_fil = _sm_filament(1, "PLA Red")
    sm_sp = _sm_spool(1, sm_fil)
    sm_sp2 = _sm_spool(2, sm_fil, extra=_xref_extra("fdb-sp-99"))
    fdb_fil = _fdb_filament("fdb1", "PETG Blue")

    sm = _fake_spoolman(spools=[sm_sp, sm_sp2], filaments=[sm_fil])
    fdb = _fake_filamentdb(filaments=[fdb_fil])

    result = await plan_dry_run(db, sm, fdb)

    for entry in result.preview:
        assert entry.get("action") in ("create", "update", "conflict", "skip"), \
            f"unexpected action: {entry.get('action')}"
        assert entry.get("label"), f"empty label in entry: {entry}"


@pytest.mark.asyncio
async def test_matcher_invoked_not_all_conflict(db):
    """Empty bridge with unmatched SM spool should not produce all-conflict output."""
    sm_fil = _sm_filament(1, "PLA Unique Color X")
    sm_sp = _sm_spool(1, sm_fil)

    sm = _fake_spoolman(spools=[sm_sp], filaments=[sm_fil])
    fdb = _fake_filamentdb(filaments=[])  # empty FDB

    result = await plan_dry_run(db, sm, fdb)

    creates = [p for p in result.preview if p["action"] == "create"]
    assert len(creates) >= 1, "unmatched SM spool must produce create entries, not conflicts"
    assert result.conflicts == 0


# ---------------------------------------------------------------------------
# Regression: run_sync_cycle(dry_run=False) is unchanged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_sync_cycle_live_still_writes(db):
    """run_sync_cycle(dry_run=False) still applies weight changes."""
    sm_fil = _sm_filament(1, "PLA")
    sm_sp = _sm_spool(1, sm_fil, remaining=150.0)
    fdb_fil_with_spool = FDBFilament.model_validate({
        "_id": "fdb1", "name": "PLA", "vendor": "ACME", "color": "#FF0000",
        "spoolWeight": 200.0,
        "spools": [{"_id": "sp1", "totalWeight": 400.0, "retired": False}],
    })

    fil_map = FilamentMapping(spoolman_filament_id=1, filamentdb_id="fdb1")
    db.add(fil_map)
    db.flush()
    spool_map = SpoolMapping(
        spoolman_spool_id=1, filamentdb_filament_id="fdb1", filamentdb_spool_id="sp1",
        filament_mapping_id=fil_map.id,
    )
    db.add(spool_map)
    db.flush()

    _seed_snapshot(db, "spoolman", "1", {"remaining_weight": 200.0, "id": 1, "filament": {"id": 1}})
    _seed_snapshot(db, "filamentdb", "sp1", {"_id": "sp1", "totalWeight": 400.0, "retired": False})

    sm = AsyncMock()
    sm.get_spools = AsyncMock(return_value=[sm_sp])
    sm.get_filaments = AsyncMock(return_value=[sm_fil])
    sm.get_field_definitions = AsyncMock(return_value=[])
    sm.update_spool = AsyncMock(return_value=MagicMock())

    fdb = AsyncMock()
    fdb.get_filaments = AsyncMock(return_value=[fdb_fil_with_spool])
    fdb.get_filament = AsyncMock(return_value=fdb_fil_with_spool)
    fdb.get_version = AsyncMock(return_value="1.33.0")
    fdb.log_usage = AsyncMock(return_value={})

    result = await run_sync_cycle(db, sm, fdb, dry_run=False)

    # SM weight decreased → FDB log_usage should have been called
    assert fdb.log_usage.called, "live sync must call log_usage for weight decrease"
    assert result.dry_run is False
    assert result.updated >= 1


# ---------------------------------------------------------------------------
# Fix #6 — dry-run respects never_import_empties from BridgeConfig
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_respects_never_import_empties(db):
    """Dry-run preview omits zero-weight spools when never_import_empties is on."""
    set_config_value(db, "never_import_empties", True)
    db.commit()

    sm_fil = _sm_filament(1, "PLA Blue", vendor="ACME", color="#0000FF")
    # One spool with remaining weight, one empty (0.0).
    sm_sp_with_weight = _sm_spool(10, sm_fil, remaining=200.0)
    sm_sp_empty = _sm_spool(11, sm_fil, remaining=0.0)

    sm = _fake_spoolman(spools=[sm_sp_with_weight, sm_sp_empty], filaments=[sm_fil])
    fdb = _fake_filamentdb(filaments=[])

    result = await plan_dry_run(db, sm, fdb)

    # Only the non-empty spool should appear as a create; the empty one is skipped.
    spool_creates = [
        p for p in result.preview
        if p["action"] == "create" and p["entity_type"] == "spool"
    ]
    spool_spoolman_ids = {p.get("spoolman_id") for p in spool_creates}
    assert 10 in spool_spoolman_ids, "non-empty spool should be a create"
    assert 11 not in spool_spoolman_ids, "empty spool must be skipped when never_import_empties=True"


@pytest.mark.asyncio
async def test_dry_run_includes_empties_when_setting_off(db):
    """Dry-run preview includes zero-weight spools when never_import_empties is off (default)."""
    # never_import_empties defaults to False — no explicit set needed.
    sm_fil = _sm_filament(1, "PLA Blue", vendor="ACME", color="#0000FF")
    sm_sp_with_weight = _sm_spool(10, sm_fil, remaining=200.0)
    sm_sp_empty = _sm_spool(11, sm_fil, remaining=0.0)

    sm = _fake_spoolman(spools=[sm_sp_with_weight, sm_sp_empty], filaments=[sm_fil])
    fdb = _fake_filamentdb(filaments=[])

    result = await plan_dry_run(db, sm, fdb)

    spool_creates = [
        p for p in result.preview
        if p["action"] == "create" and p["entity_type"] == "spool"
    ]
    spool_spoolman_ids = {p.get("spoolman_id") for p in spool_creates}
    assert 10 in spool_spoolman_ids
    assert 11 in spool_spoolman_ids, "empty spool should be included when never_import_empties=False"
