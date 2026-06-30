"""Integration tests for ``_sync_opentag_material_fields`` — the bidirectional sync
of the seven typed OpenPrintTag material-setting extras to/from their first-class
Filament DB fields.

Covers:
  - First-sight baseline: no prior _mp_<key> snapshots → store, no write
  - SM→FDB (standalone scalar field, dryingTime): extra change → FDB write + both
    snapshots refreshed (no ping-pong on a follow-up cycle)
  - SM→FDB (dotted temperatures.nozzleRangeMin): read-modify-write preserves siblings
  - SM→FDB inherited master gate: variant inheriting the field, SM diverges →
    master_divergence conflict, NO write
  - FDB→SM: lone FDB change writes the SM extra field

Mirrors test_engine_scalars.py.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.engine import run_sync_cycle
from app.core.fields import OPENTAG_EXTRA_FIELDS
from app.models.config import BridgeConfig
from app.models.conflict import Conflict
from app.models.mapping import FilamentMapping
from app.models.snapshot import Snapshot
from app.schemas.filamentdb import FDBFilament, FDBFilamentDetail
from app.schemas.spoolman import SpoolmanFilament, SpoolmanVendor, encode_extra_value

CYCLE_ID = "opt-fields-test-cycle"
OT_SM_FIL_ID = 80
OT_FDB_FIL_ID = "fil-opt"

# Default extra-field keys (match config defaults).
KEY_DRY_TIME = "openprinttag_drying_time"
KEY_NOZZLE_MIN = "openprinttag_nozzle_temp_min"


def _sm_fil_opt(extra: dict | None = None) -> SpoolmanFilament:
    return SpoolmanFilament(
        id=OT_SM_FIL_ID,
        name="OPT PLA",
        vendor=SpoolmanVendor(id=1, name="ELEGOO"),
        material="PLA",
        extra=extra or {},
    )


def _fdb_list_opt() -> FDBFilament:
    return FDBFilament.model_validate({
        "_id": OT_FDB_FIL_ID, "name": "OPT PLA", "type": "PLA", "spools": [],
    })


def _fdb_detail_opt(
    *,
    drying_time: float | None = None,
    temperatures: dict | None = None,
    parent_id: str | None = None,
    inherited: list[str] | None = None,
) -> FDBFilamentDetail:
    return FDBFilamentDetail.model_validate({
        "_id": OT_FDB_FIL_ID,
        "name": "OPT PLA",
        "type": "PLA",
        "dryingTime": drying_time,
        "temperatures": temperatures or {},
        "parentId": parent_id,
        "_inherited": inherited or [],
        "spools": [],
    })


def _add_fil_mapping(db) -> None:
    db.add(FilamentMapping(
        spoolman_filament_id=OT_SM_FIL_ID, filamentdb_id=OT_FDB_FIL_ID
    ))
    db.flush()


def _opt_settings(mock_settings) -> None:
    """Apply the minimal _settings attrs needed for an OPT-field-only cycle.

    Critically, the seven openprinttag_* extra-field keys must be REAL strings (not
    MagicMock attrs) so the engine reads/writes the correct Spoolman extra keys.
    """
    mock_settings.filamentdb_spoolman_id_field = "label"
    mock_settings.spoolman_field_filamentdb_id = "filamentdb_id"
    mock_settings.spoolman_field_filamentdb_spool_id = "filamentdb_spool_id"
    mock_settings.spoolman_field_filamentdb_parent_id = "filamentdb_parent_id"
    mock_settings.parsed_field_mappings = {}
    mock_settings.parsed_field_mapping_excludes = set()
    # Real key strings for the seven OPT extras (use the dataclass defaults).
    for ef in OPENTAG_EXTRA_FIELDS:
        setattr(mock_settings, ef.config_attr, ef.default_key)


def _seed_matprop(db, direction: str, policy: str = "manual") -> None:
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
    return client


def _fake_fdb(filaments=None, detail=None, version="1.33.0") -> AsyncMock:
    client = AsyncMock()
    client.get_filaments = AsyncMock(return_value=filaments or [])
    client.get_filament = AsyncMock(return_value=detail)
    client.get_version = AsyncMock(return_value=version)
    client.update_filament = AsyncMock(return_value={})
    return client


def _snap(db, source, entity_type, entity_id, data) -> None:
    db.add(Snapshot(
        source=source, entity_type=entity_type,
        entity_id=entity_id, data=json.dumps(data),
    ))
    db.flush()


def _get_snap_data(db, source, entity_type, entity_id) -> dict | None:
    row = db.query(Snapshot).filter_by(
        source=source, entity_type=entity_type, entity_id=entity_id
    ).first()
    return json.loads(row.data) if row else None


@pytest.mark.asyncio
async def test_opt_field_first_sight_stores_baseline_no_write(db):
    """No prior _mp_<key> snapshots → store baseline, no upstream writes."""
    _add_fil_mapping(db)
    sm_fil = _sm_fil_opt(extra={KEY_DRY_TIME: encode_extra_value(6)})
    fdb_detail = _fdb_detail_opt(drying_time=6)

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[_fdb_list_opt()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _opt_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    fdb_client.update_filament.assert_not_called()
    spoolman.update_filament.assert_not_called()
    assert result.conflicts == 0

    sm_data = _get_snap_data(db, "spoolman", "filament", str(OT_SM_FIL_ID))
    assert sm_data is not None
    assert sm_data.get(f"_mp_{KEY_DRY_TIME}") == 6


@pytest.mark.asyncio
async def test_opt_field_sm_to_fdb_scalar_writes_and_no_pingpong(db):
    """Standalone filament: SM drying_time extra changed → FDB dryingTime written,
    BOTH snapshots refreshed so the next cycle does not re-detect the change."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="spoolman_to_filamentdb", policy="manual")

    sm_fil = _sm_fil_opt(extra={KEY_DRY_TIME: encode_extra_value(8)})  # now 8
    fdb_detail = _fdb_detail_opt(drying_time=6, parent_id=None, inherited=[])

    _snap(db, "spoolman", "filament", str(OT_SM_FIL_ID), {f"_mp_{KEY_DRY_TIME}": 6})
    _snap(db, "filamentdb", "filament", OT_FDB_FIL_ID, {f"_mp_{KEY_DRY_TIME}": 6})

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[_fdb_list_opt()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _opt_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    fdb_client.update_filament.assert_any_call(OT_FDB_FIL_ID, {"dryingTime": 8})
    assert result.updated >= 1

    # Anti-ping-pong: both snapshots now hold the post-write agreed value (8).
    sm_data = _get_snap_data(db, "spoolman", "filament", str(OT_SM_FIL_ID))
    fdb_data = _get_snap_data(db, "filamentdb", "filament", OT_FDB_FIL_ID)
    assert sm_data.get(f"_mp_{KEY_DRY_TIME}") == 8
    assert fdb_data.get(f"_mp_{KEY_DRY_TIME}") == 8

    # Second cycle with the SAME state → no new write (FDB now reads 8 too).
    fdb_detail2 = _fdb_detail_opt(drying_time=8, parent_id=None, inherited=[])
    fdb_client2 = _fake_fdb(filaments=[_fdb_list_opt()], detail=fdb_detail2)
    spoolman2 = _fake_spoolman(filaments=[sm_fil])
    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _opt_settings(ms)
        r2 = await run_sync_cycle(db, spoolman2, fdb_client2, dry_run=False, cycle_id=CYCLE_ID + "-2")
    fdb_client2.update_filament.assert_not_called()
    assert r2.updated == 0


@pytest.mark.asyncio
async def test_opt_field_sm_to_fdb_dotted_temp_preserves_siblings(db):
    """SM nozzle_temp_min extra → FDB temperatures.nozzleRangeMin via read-modify-write
    that preserves sibling temperature keys."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="spoolman_to_filamentdb", policy="manual")

    sm_fil = _sm_fil_opt(extra={KEY_NOZZLE_MIN: encode_extra_value(205)})  # now 205
    # FDB has a populated temperatures object with a sibling (nozzle) that must survive.
    fdb_detail = _fdb_detail_opt(
        temperatures={"nozzle": 215, "nozzleRangeMin": 200},
        parent_id=None, inherited=[],
    )

    _snap(db, "spoolman", "filament", str(OT_SM_FIL_ID), {f"_mp_{KEY_NOZZLE_MIN}": 200})
    _snap(db, "filamentdb", "filament", OT_FDB_FIL_ID, {f"_mp_{KEY_NOZZLE_MIN}": 200})

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[_fdb_list_opt()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _opt_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    assert result.updated >= 1
    # The PUT payload must carry the whole temperatures object with the sibling kept.
    found = None
    for call in fdb_client.update_filament.call_args_list:
        args, _ = call
        if args[0] == OT_FDB_FIL_ID and "temperatures" in args[1]:
            found = args[1]["temperatures"]
            break
    assert found is not None, "expected a temperatures read-modify-write PUT"
    assert found.get("nozzleRangeMin") == 205
    assert found.get("nozzle") == 215  # sibling preserved


@pytest.mark.asyncio
async def test_opt_field_sm_to_fdb_inherited_divergence_queues_master_divergence(db):
    """Variant inheriting dryingTime; SM extra diverges → master_divergence, no write."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="spoolman_to_filamentdb", policy="manual")

    sm_fil = _sm_fil_opt(extra={KEY_DRY_TIME: encode_extra_value(10)})  # diverges
    fdb_detail = _fdb_detail_opt(
        drying_time=6, parent_id="parent-999", inherited=["dryingTime"],
    )

    _snap(db, "spoolman", "filament", str(OT_SM_FIL_ID), {f"_mp_{KEY_DRY_TIME}": 6})
    _snap(db, "filamentdb", "filament", OT_FDB_FIL_ID, {f"_mp_{KEY_DRY_TIME}": 6})

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[_fdb_list_opt()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _opt_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    fdb_client.update_filament.assert_not_called()
    spoolman.update_filament.assert_not_called()
    assert result.conflicts >= 1
    conflict = db.query(Conflict).filter_by(field_name="opt_drying_time").first()
    assert conflict is not None
    assert conflict.conflict_type == "master_divergence"


@pytest.mark.asyncio
async def test_opt_field_fdb_to_sm_writes_extra(db):
    """Lone FDB dryingTime change → Spoolman extra openprinttag_drying_time written."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="filamentdb_to_spoolman", policy="manual")

    sm_fil = _sm_fil_opt(extra={KEY_DRY_TIME: encode_extra_value(6)})  # SM unchanged
    fdb_detail = _fdb_detail_opt(drying_time=9, parent_id=None, inherited=[])  # FDB changed

    _snap(db, "spoolman", "filament", str(OT_SM_FIL_ID), {f"_mp_{KEY_DRY_TIME}": 6})
    _snap(db, "filamentdb", "filament", OT_FDB_FIL_ID, {f"_mp_{KEY_DRY_TIME}": 6})

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[_fdb_list_opt()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _opt_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    spoolman.update_filament.assert_any_call(
        OT_SM_FIL_ID, {"extra": {KEY_DRY_TIME: encode_extra_value(9)}},
    )
    assert result.updated >= 1
    fdb_client.update_filament.assert_not_called()


# ---------------------------------------------------------------------------
# New fields: all Spoolman-only (no FDB leg)
# ---------------------------------------------------------------------------

KEY_BED_MAX = "openprinttag_bed_temp_max"    # fdb_path=None → Spoolman-only
KEY_CHAMBER = "openprinttag_chamber_temp"    # fdb_path=None → Spoolman-only


@pytest.mark.asyncio
async def test_opt_field_bed_temp_max_is_spoolman_only_no_fdb_write(db):
    """openprinttag_bed_temp_max is Spoolman-only — the OPT pass must NOT write to FDB.

    FDB's single ``temperatures.bed`` is already owned by the native
    ``settings_bed_temp`` ↔ ``temperatures.bed`` pass (MATERIAL_PROP_TEMP_PAIRS).
    The OPT bed-temp extra therefore has no FDB leg, or two Spoolman fields would
    fight over the same FDB field (ping-pong).  Bed temp still reaches FDB via the
    native channel — just not through this extra.
    """
    _add_fil_mapping(db)
    _seed_matprop(db, direction="spoolman_to_filamentdb", policy="manual")

    # SM bed-temp extra diverges from FDB's temperatures.bed — must NOT trigger a write.
    sm_fil = _sm_fil_opt(extra={KEY_BED_MAX: encode_extra_value(65)})
    fdb_detail = _fdb_detail_opt(temperatures={"bed": 60}, parent_id=None, inherited=[])

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[_fdb_list_opt()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _opt_settings(ms)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    # The OPT pass must never write temperatures.bed from the bed-temp extra.
    for call in fdb_client.update_filament.call_args_list:
        args, _ = call
        if args[0] == OT_FDB_FIL_ID and "temperatures" in args[1]:
            assert "bed" not in args[1]["temperatures"], \
                "bed_temp_max must be Spoolman-only — no FDB temperatures.bed write"
    # No conflict queued for a Spoolman-only field either.
    assert db.query(Conflict).filter_by(field_name="opt_bed_temp_max").first() is None


@pytest.mark.asyncio
async def test_opt_field_spoolman_only_no_fdb_write(db):
    """Spoolman-only field (chamber_temp, fdb_path=None) never triggers an FDB write.

    Even if the SM extra changes, the engine must skip the FDB leg entirely for
    fields with no FDB counterpart.
    """
    _add_fil_mapping(db)
    _seed_matprop(db, direction="spoolman_to_filamentdb", policy="manual")

    # Put a chamber temp value in Spoolman — there is no FDB field to compare against.
    sm_fil = _sm_fil_opt(extra={KEY_CHAMBER: encode_extra_value(30)})
    fdb_detail = _fdb_detail_opt(temperatures={}, parent_id=None, inherited=[])

    # No prior snapshot for this key (first-sight scenario for a Spoolman-only field).
    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[_fdb_list_opt()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _opt_settings(ms)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    # The FDB client must never be asked to update a filament for this field.
    fdb_client.update_filament.assert_not_called()
    # No conflicts should be queued for a Spoolman-only field.
    conflict = db.query(Conflict).filter_by(field_name="opt_chamber_temp").first()
    assert conflict is None
