"""Integration tests for _sync_material_scalars (Phase A, FR-11 native fields).

Covers:
  - Standalone filament: SM-only change → FDB write (no master gate)
  - Already-overridden variant: SM-only change → FDB write (parentId set, field
    NOT in _inherited — override already exists)
  - Redundant-skip: SM→FDB direction, SM value matches inherited master → skip
  - Divergence from master: SM→FDB would clash with inherited master → queue
    master_divergence conflict (no write)
  - material→type name remap: SM ``material`` → FDB ``type``
  - FDB→SM write: lone FDB type/density/etc change propagates to Spoolman
  - Conflict under manual policy: both sides changed → cross_system conflict
  - First-sight baseline: no prior snapshots → store, no write
  - Snapshot keys _mp_<field> coexist with pre-existing keys (_mc_sig, _cost)
  - _build_detail in mappings.py reads _mp_* and _mc_color from snapshot

Mirror of the existing temp / cost pass tests in test_engine.py.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.engine import run_sync_cycle
from app.models.conflict import Conflict
from app.models.mapping import FilamentMapping
from app.models.snapshot import Snapshot
from app.schemas.filamentdb import FDBFilament, FDBFilamentDetail
from app.schemas.spoolman import SpoolmanFilament, SpoolmanVendor

CYCLE_ID = "scalars-test-cycle"

# Scalar-test specific IDs (chosen to not clash with test_engine.py IDs).
SC_SM_FIL_ID = 70
SC_FDB_FIL_ID = "fil-scalar"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _sm_fil_scalar(
    material: str | None = "PLA",
    density: float | None = 1.24,
    diameter: float | None = 1.75,
    spool_weight: float | None = 200.0,
    weight: float | None = 1000.0,
) -> SpoolmanFilament:
    return SpoolmanFilament(
        id=SC_SM_FIL_ID,
        name="Scalar PLA",
        vendor=SpoolmanVendor(id=1, name="ELEGOO"),
        material=material,
        density=density,
        diameter=diameter,
        spool_weight=spool_weight,
        weight=weight,
    )


def _fdb_list_scalar(
    ftype: str | None = "PLA",
    density: float | None = 1.24,
    diameter: float | None = 1.75,
    spool_weight: float | None = 200.0,
    net_weight: float | None = 1000.0,
) -> FDBFilament:
    return FDBFilament.model_validate({
        "_id": SC_FDB_FIL_ID,
        "name": "Scalar PLA",
        "type": ftype,
        "density": density,
        "diameter": diameter,
        "spoolWeight": spool_weight,
        "netFilamentWeight": net_weight,
        "spools": [],
    })


def _fdb_detail_scalar(
    ftype: str | None = "PLA",
    density: float | None = 1.24,
    diameter: float | None = 1.75,
    spool_weight: float | None = 200.0,
    net_weight: float | None = 1000.0,
    *,
    parent_id: str | None = None,
    inherited: list[str] | None = None,
) -> FDBFilamentDetail:
    """Return a FDBFilamentDetail for the scalar-test filament.

    ``parent_id`` and ``inherited`` allow variant / master scenarios.
    """
    return FDBFilamentDetail.model_validate({
        "_id": SC_FDB_FIL_ID,
        "name": "Scalar PLA",
        "type": ftype,
        "density": density,
        "diameter": diameter,
        "spoolWeight": spool_weight,
        "netFilamentWeight": net_weight,
        "parentId": parent_id,
        "_inherited": inherited or [],
        "spools": [],
    })


def _add_fil_mapping(db) -> None:
    db.add(FilamentMapping(
        spoolman_filament_id=SC_SM_FIL_ID, filamentdb_id=SC_FDB_FIL_ID
    ))
    db.flush()


def _scalar_settings(mock_settings) -> None:
    """Apply the minimal _settings attrs needed for a scalar-only cycle."""
    mock_settings.filamentdb_spoolman_id_field = "label"
    mock_settings.spoolman_field_filamentdb_id = "filamentdb_id"
    mock_settings.spoolman_field_filamentdb_spool_id = "filamentdb_spool_id"
    mock_settings.spoolman_field_filamentdb_parent_id = "filamentdb_parent_id"
    mock_settings.parsed_field_mappings = {}
    mock_settings.parsed_field_mapping_excludes = set()


def _seed_matprop(db, direction: str = "spoolman_to_filamentdb", policy: str = "manual") -> None:
    from app.models.config import BridgeConfig
    db.merge(BridgeConfig(key="material_properties_sync_direction", value=json.dumps(direction)))
    db.merge(BridgeConfig(key="material_properties_conflict_policy", value=json.dumps(policy)))
    db.commit()


def _fake_spoolman(filaments=None) -> AsyncMock:
    client = AsyncMock()
    client.get_spools = AsyncMock(return_value=[])
    client.get_filaments = AsyncMock(return_value=filaments or [])
    client.get_field_definitions = AsyncMock(return_value=[])
    client.update_spool = AsyncMock(return_value=MagicMock())
    client.update_filament = AsyncMock(return_value=MagicMock())
    client.create_spool = AsyncMock(return_value=MagicMock(id=999))
    return client


def _fake_fdb(filaments=None, detail=None, version="1.33.0") -> AsyncMock:
    client = AsyncMock()
    client.get_filaments = AsyncMock(return_value=filaments or [])
    client.get_filament = AsyncMock(return_value=detail)
    client.get_version = AsyncMock(return_value=version)
    client.log_usage = AsyncMock(return_value={})
    client.update_spool = AsyncMock(return_value={})
    client.update_filament = AsyncMock(return_value={})
    client.create_spool = AsyncMock(return_value={"_id": "new-spool-id"})
    return client


def _snap(db, source: str, entity_type: str, entity_id: str, data: dict) -> None:
    db.add(Snapshot(
        source=source, entity_type=entity_type,
        entity_id=entity_id, data=json.dumps(data),
    ))
    db.flush()


def _get_snap_data(db, source: str, entity_type: str, entity_id: str) -> dict | None:
    row = db.query(Snapshot).filter_by(
        source=source, entity_type=entity_type, entity_id=entity_id
    ).first()
    return json.loads(row.data) if row else None


# ---------------------------------------------------------------------------
# First-sight baseline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scalar_first_sight_stores_baseline_no_write(db):
    """No prior _mp_* snapshots → store baseline, no upstream writes."""
    _add_fil_mapping(db)
    sm_fil = _sm_fil_scalar(material="PLA", density=1.24)
    fdb_list = _fdb_list_scalar(ftype="PLA", density=1.24)
    fdb_detail = _fdb_detail_scalar(ftype="PLA", density=1.24)

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[fdb_list], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _scalar_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    fdb_client.update_filament.assert_not_called()
    spoolman.update_filament.assert_not_called()
    assert result.updated == 0
    assert result.conflicts == 0

    # Snapshot must have _mp_material stored on the SM side.
    sm_data = _get_snap_data(db, "spoolman", "filament", str(SC_SM_FIL_ID))
    assert sm_data is not None
    assert sm_data.get("_mp_material") == "PLA"
    assert sm_data.get("_mp_density") == 1.24


# ---------------------------------------------------------------------------
# SM→FDB write: standalone filament (no parent)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scalar_sm_to_fdb_standalone_writes_material(db):
    """Standalone filament: SM material changed → FDB type written."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="spoolman_to_filamentdb", policy="manual")

    sm_fil = _sm_fil_scalar(material="PETG", density=1.24)
    fdb_list = _fdb_list_scalar(ftype="PLA", density=1.24)
    fdb_detail = _fdb_detail_scalar(
        ftype="PLA", density=1.24,
        parent_id=None,      # standalone — no parent
        inherited=[],
    )

    # Baseline: SM material was "PLA"; now "PETG" — SM only changed
    _snap(db, "spoolman", "filament", str(SC_SM_FIL_ID), {"_mp_material": "PLA"})
    _snap(db, "filamentdb", "filament", SC_FDB_FIL_ID, {"_mp_material": "PLA"})

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[fdb_list], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _scalar_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    # Bridge must call update_filament with {type: "PETG"}
    fdb_client.update_filament.assert_any_call(SC_FDB_FIL_ID, {"type": "PETG"})
    assert result.updated >= 1
    spoolman.update_filament.assert_not_called()


# ---------------------------------------------------------------------------
# SM→FDB write: variant with overridden field
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scalar_sm_to_fdb_overridden_variant_writes(db):
    """Variant with parentId set but field NOT in _inherited (already overridden).

    The gate should see it is NOT inherited → write directly (same as standalone).
    """
    _add_fil_mapping(db)
    _seed_matprop(db, direction="spoolman_to_filamentdb", policy="manual")

    sm_fil = _sm_fil_scalar(density=1.38)
    fdb_list = _fdb_list_scalar(density=1.24)
    fdb_detail = _fdb_detail_scalar(
        density=1.24,
        parent_id="parent-fil-999",   # has a parent
        inherited=[],                  # density NOT in inherited → already overridden
    )

    _snap(db, "spoolman", "filament", str(SC_SM_FIL_ID), {"_mp_density": 1.24})
    _snap(db, "filamentdb", "filament", SC_FDB_FIL_ID, {"_mp_density": 1.24})

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[fdb_list], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _scalar_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    fdb_client.update_filament.assert_any_call(SC_FDB_FIL_ID, {"density": 1.38})
    assert result.updated >= 1


# ---------------------------------------------------------------------------
# SM→FDB skip: variant inheriting field that already matches SM
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scalar_sm_to_fdb_inherited_matches_skips_write(db):
    """Variant inheriting density and SM value == resolved (inherited) → skip.

    No write is needed because the variant already shows the correct value via
    inheritance; writing an explicit override would be a no-op but pollutes the FDB
    record by detaching it from the master for no reason.
    """
    _add_fil_mapping(db)
    _seed_matprop(db, direction="spoolman_to_filamentdb", policy="manual")

    # SM density = 1.24 (changed from baseline 1.20)
    sm_fil = _sm_fil_scalar(density=1.24)
    # FDB (list view) resolves density = 1.24 from inherited master
    fdb_list = _fdb_list_scalar(density=1.24)
    fdb_detail = _fdb_detail_scalar(
        density=1.24,                        # resolved inherited value
        parent_id="parent-fil-999",
        inherited=["density"],               # density is inherited → master owns it
    )

    # Baseline: only SM changed (1.20 → 1.24); FDB already resolved to 1.24 via the
    # inherited master, so fdb_changed is False and the action is PUSH_SM_TO_FDB —
    # which the inherited-master gate then skips (no redundant override).
    _snap(db, "spoolman", "filament", str(SC_SM_FIL_ID), {"_mp_density": 1.20})
    _snap(db, "filamentdb", "filament", SC_FDB_FIL_ID, {"_mp_density": 1.24})

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[fdb_list], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _scalar_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    # SM changed but matches inherited master — no write, just skip
    fdb_client.update_filament.assert_not_called()
    assert result.skipped >= 1
    assert result.updated == 0
    assert result.conflicts == 0


# ---------------------------------------------------------------------------
# SM→FDB master_divergence: variant inheriting field that differs from SM
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scalar_sm_to_fdb_inherited_divergence_queues_master_divergence(db):
    """Variant inheriting density; SM value differs from resolved → master_divergence conflict.

    No write — this is a record-only conflict pending Phase B approval.
    """
    _add_fil_mapping(db)
    _seed_matprop(db, direction="spoolman_to_filamentdb", policy="manual")

    # SM density changed to 1.38; FDB variant still shows 1.24 via inheritance
    sm_fil = _sm_fil_scalar(density=1.38)
    fdb_list = _fdb_list_scalar(density=1.24)
    fdb_detail = _fdb_detail_scalar(
        density=1.24,
        parent_id="parent-fil-999",
        inherited=["density"],
    )

    _snap(db, "spoolman", "filament", str(SC_SM_FIL_ID), {"_mp_density": 1.24})
    _snap(db, "filamentdb", "filament", SC_FDB_FIL_ID, {"_mp_density": 1.24})

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[fdb_list], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _scalar_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    # No write to either side
    fdb_client.update_filament.assert_not_called()
    spoolman.update_filament.assert_not_called()

    # One master_divergence conflict queued
    assert result.conflicts >= 1
    conflict = db.query(Conflict).filter_by(field_name="density").first()
    assert conflict is not None
    assert conflict.conflict_type == "master_divergence"
    assert conflict.spoolman_id == SC_SM_FIL_ID
    assert conflict.filamentdb_filament_id == SC_FDB_FIL_ID


@pytest.mark.asyncio
async def test_scalar_master_divergence_dedup_no_requeue(db):
    """Second cycle with same divergence must NOT re-queue the master_divergence conflict."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="spoolman_to_filamentdb", policy="manual")

    sm_fil = _sm_fil_scalar(density=1.38)
    fdb_list = _fdb_list_scalar(density=1.24)
    fdb_detail = _fdb_detail_scalar(density=1.24, parent_id="parent-999", inherited=["density"])

    _snap(db, "spoolman", "filament", str(SC_SM_FIL_ID), {"_mp_density": 1.24})
    _snap(db, "filamentdb", "filament", SC_FDB_FIL_ID, {"_mp_density": 1.24})

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[fdb_list], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _scalar_settings(ms)
        r1 = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    assert r1.conflicts >= 1
    n_after_first = db.query(Conflict).filter_by(
        conflict_type="master_divergence", field_name="density"
    ).count()
    assert n_after_first == 1

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _scalar_settings(ms)
        r2 = await run_sync_cycle(
            db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID + "-2"
        )

    # No new conflict was added on the second cycle
    assert r2.conflicts == 0
    assert db.query(Conflict).filter_by(
        conflict_type="master_divergence", field_name="density"
    ).count() == 1


# ---------------------------------------------------------------------------
# FDB→SM write: type/density/diameter/spool_weight/weight
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scalar_fdb_to_sm_density_writes_spoolman(db):
    """FDB density changed (lone FDB change) → Spoolman filament density updated."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="filamentdb_to_spoolman", policy="manual")

    sm_fil = _sm_fil_scalar(density=1.24)       # SM unchanged
    fdb_list = _fdb_list_scalar(density=1.38)    # FDB changed
    fdb_detail = _fdb_detail_scalar(density=1.38, parent_id=None, inherited=[])

    _snap(db, "spoolman", "filament", str(SC_SM_FIL_ID), {"_mp_density": 1.24})
    _snap(db, "filamentdb", "filament", SC_FDB_FIL_ID, {"_mp_density": 1.24})

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[fdb_list], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _scalar_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    spoolman.update_filament.assert_any_call(SC_SM_FIL_ID, {"density": 1.38})
    assert result.updated >= 1
    fdb_client.update_filament.assert_not_called()


@pytest.mark.asyncio
async def test_scalar_fdb_to_sm_material_remap(db):
    """FDB ``type`` changed → SM ``material`` written (name remap materialized)."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="filamentdb_to_spoolman", policy="manual")

    sm_fil = _sm_fil_scalar(material="PLA")      # SM unchanged
    fdb_list = _fdb_list_scalar(ftype="PETG")     # FDB type changed
    fdb_detail = _fdb_detail_scalar(ftype="PETG", parent_id=None, inherited=[])

    _snap(db, "spoolman", "filament", str(SC_SM_FIL_ID), {"_mp_material": "PLA"})
    _snap(db, "filamentdb", "filament", SC_FDB_FIL_ID, {"_mp_material": "PLA"})

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[fdb_list], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _scalar_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    # SM ``material`` must be updated (the bridge remaps FDB "type" → SM "material")
    spoolman.update_filament.assert_any_call(SC_SM_FIL_ID, {"material": "PETG"})
    assert result.updated >= 1
    fdb_client.update_filament.assert_not_called()


# ---------------------------------------------------------------------------
# Both changed → cross_system conflict (two_way + manual)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scalar_both_changed_queues_cross_system_conflict(db):
    """Both sides changed density under two_way+manual → cross_system Conflict, no write."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="two_way", policy="manual")

    sm_fil = _sm_fil_scalar(density=1.38)        # SM changed
    fdb_list = _fdb_list_scalar(density=1.30)    # FDB also changed
    fdb_detail = _fdb_detail_scalar(density=1.30, parent_id=None, inherited=[])

    # Baseline: both had 1.24
    _snap(db, "spoolman", "filament", str(SC_SM_FIL_ID), {"_mp_density": 1.24})
    _snap(db, "filamentdb", "filament", SC_FDB_FIL_ID, {"_mp_density": 1.24})

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[fdb_list], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _scalar_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    fdb_client.update_filament.assert_not_called()
    spoolman.update_filament.assert_not_called()

    conflict = db.query(Conflict).filter_by(field_name="density").first()
    assert conflict is not None
    assert conflict.conflict_type == "cross_system"
    assert conflict.spoolman_id == SC_SM_FIL_ID
    assert conflict.filamentdb_filament_id == SC_FDB_FIL_ID
    assert result.conflicts >= 1
    assert result.updated == 0


# ---------------------------------------------------------------------------
# Snapshot keys coexist with _mc_sig / _cost
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scalar_snapshot_keys_coexist_with_mc_and_cost(db):
    """After a cycle, _mp_material must coexist with pre-existing _mc_sig and _cost keys."""
    _add_fil_mapping(db)

    sm_fil = _sm_fil_scalar(material="PLA", density=1.24)
    fdb_list = _fdb_list_scalar(ftype="PLA", density=1.24)
    fdb_detail = _fdb_detail_scalar(ftype="PLA", density=1.24)

    # Pre-seed with _mc_sig and _cost so a prior "other-pass" state exists
    _snap(db, "spoolman", "filament", str(SC_SM_FIL_ID), {
        "_mc_sig": "solid|112233|", "_cost": 19.99,
    })
    _snap(db, "filamentdb", "filament", SC_FDB_FIL_ID, {
        "_mc_sig": "solid|112233|", "_cost": 19.99,
    })

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[fdb_list], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _scalar_settings(ms)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    sm_data = _get_snap_data(db, "spoolman", "filament", str(SC_SM_FIL_ID))
    assert sm_data is not None
    # Old keys must survive
    assert sm_data.get("_mc_sig") == "solid|112233|"
    assert sm_data.get("_cost") == 19.99
    # New key added by scalar pass
    assert sm_data.get("_mp_material") == "PLA"


# ---------------------------------------------------------------------------
# _build_detail reads _mp_* and _mc_color from snapshot
# ---------------------------------------------------------------------------


def test_build_detail_reads_snapshot_keys(db):
    """_build_detail must return real FDB values read from the _mp_* snapshot keys.

    Before the Phase-A fix, material/density/diameter were always None.  This test
    verifies that they are now populated from the filament snapshot.
    """
    from app.api.mappings import _build_detail

    sm_fil = {
        "material": "PETG",
        "density": 1.27,
        "diameter": 1.75,
        "settings_bed_temp": 80,
        "settings_extruder_temp": 240,
        "price": 25.00,
        "color_hex": "aabbcc",
    }

    # FDB spool snapshot (gross weight)
    fdb_snap = {"totalWeight": 1200.0}

    # FDB filament snapshot carrying the _mp_* keys and _mc_color
    fdb_fil_snap = {
        "_mp_material": "PETG",
        "_mp_density": 1.27,
        "_mp_diameter": 1.75,
        "_mc_color": "#aabbcc",
        "_cost": 24.99,
        "_mp_settings_bed_temp": 80,
        "_mp_settings_extruder_temp": 240,
    }

    detail = _build_detail(sm_fil, fdb_snap, fdb_fil_snap, remaining=900.0)

    # Convert to dict keyed by field name for easy lookup
    by_field = {d.field: d for d in detail}

    assert by_field["material"].filamentdb == "PETG"
    assert by_field["density"].filamentdb == 1.27
    assert by_field["diameter"].filamentdb == 1.75
    assert by_field["color"].filamentdb == "#aabbcc"
    assert by_field["cost"].filamentdb == 24.99
    assert by_field["weight"].filamentdb == 1200.0
    assert by_field["weight"].spoolman == 900.0


def test_build_detail_returns_none_when_no_snapshot(db):
    """When FDB filament snapshot has no _mp_* keys, values are None (pre-baseline)."""
    from app.api.mappings import _build_detail

    sm_fil = {"material": "PLA", "density": 1.24}
    fdb_snap = {"totalWeight": 1000.0}
    fdb_fil_snap: dict = {}   # empty — no keys yet

    detail = _build_detail(sm_fil, fdb_snap, fdb_fil_snap, remaining=800.0)
    by_field = {d.field: d for d in detail}

    assert by_field["material"].filamentdb is None
    assert by_field["density"].filamentdb is None
    assert by_field["color"].filamentdb is None
