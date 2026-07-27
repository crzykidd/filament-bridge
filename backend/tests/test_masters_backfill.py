"""Tests for the master-defaults backfill screen (issue #76)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.masters_backfill import (
    apply_master_defaults,
    apply_master_defaults_bulk,
    build_master_default_rows,
)
from app.models.mapping import FilamentMapping
from app.schemas.filamentdb import FDBFilament, FDBTemperatures
from app.schemas.spoolman import SpoolmanFilament, SpoolmanVendor


def _fdb(id, *, has_variants=False, parent_id=None, spool_weight=None,
         density=None, diameter=None, ftype=None, nozzle=None, bed=None, name=None):
    temps = None
    if nozzle is not None or bed is not None:
        temps = FDBTemperatures(nozzle=nozzle, bed=bed)
    return FDBFilament(
        _id=id, name=name or f"fil-{id}", hasVariants=has_variants, parentId=parent_id,
        spoolWeight=spool_weight, density=density, diameter=diameter, type=ftype,
        temperatures=temps,
    )


def _sm(id, *, spool_weight=None, density=None, diameter=None, material=None,
        nozzle=None, bed=None, name=None):
    return SpoolmanFilament(
        id=id, name=name or f"sm-{id}", vendor=SpoolmanVendor(id=1, name="Acme"),
        material=material, spool_weight=spool_weight, density=density, diameter=diameter,
        settings_extruder_temp=nozzle, settings_bed_temp=bed,
    )


def _fake_spoolman(filaments=None):
    client = AsyncMock()
    client.get_filaments = AsyncMock(return_value=filaments or [])
    client.update_filament = AsyncMock(return_value=MagicMock())
    return client


def _fake_filamentdb(filaments=None):
    client = AsyncMock()
    client.get_filaments = AsyncMock(return_value=filaments or [])
    client.update_filament = AsyncMock(return_value=MagicMock())
    return client


# ---------------------------------------------------------------------------
# build_master_default_rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_real_master_proposes_mode_from_variant_own_values(db):
    master = _fdb("m1", has_variants=True, spool_weight=None)
    var_a = _fdb("va", parent_id="m1", spool_weight=200.0)
    var_b = _fdb("vb", parent_id="m1", spool_weight=200.0)
    var_c = _fdb("vc", parent_id="m1", spool_weight=250.0)
    db.add(FilamentMapping(spoolman_filament_id=101, filamentdb_id="m1"))
    db.commit()

    fdb = _fake_filamentdb([master, var_a, var_b, var_c])
    sm = _fake_spoolman([_sm(101, spool_weight=None)])

    rows = await build_master_default_rows(db, sm, fdb)
    assert len(rows) == 1
    row = rows[0]
    assert row["filamentdb_id"] == "m1"
    assert row["is_synthetic"] is False
    assert row["spoolman_filament_id"] == 101
    assert row["variant_count"] == 3

    field = row["fields"]["spool_weight"]
    assert field["current"] is None
    assert field["proposal"] == 200.0
    assert field["would_fill"] is True
    assert {b["filamentdb_id"] for b in field["breakdown"]} == {"va", "vb", "vc"}


@pytest.mark.asyncio
async def test_master_with_existing_value_is_not_would_fill(db):
    master = _fdb("m2", has_variants=True, spool_weight=180.0)
    var_a = _fdb("va2", parent_id="m2", spool_weight=200.0)
    db.commit()

    fdb = _fake_filamentdb([master, var_a])
    sm = _fake_spoolman([])

    rows = await build_master_default_rows(db, sm, fdb)
    field = rows[0]["fields"]["spool_weight"]
    assert field["current"] == 180.0
    assert field["proposal"] == 200.0  # still computed/shown…
    assert field["would_fill"] is False  # …but never proposed for fill


@pytest.mark.asyncio
async def test_synthetic_master_has_no_sm_counterpart(db):
    master = _fdb("synth1", has_variants=True, spool_weight=None)
    var_a = _fdb("vs1", parent_id="synth1", density=1.24)
    db.add(FilamentMapping(spoolman_filament_id=None, filamentdb_id="synth1", is_synthetic_parent=True))
    db.commit()

    fdb = _fake_filamentdb([master, var_a])
    sm = _fake_spoolman([])

    rows = await build_master_default_rows(db, sm, fdb)
    row = rows[0]
    assert row["is_synthetic"] is True
    assert row["spoolman_filament_id"] is None
    assert row["fields"]["density"]["proposal"] == 1.24


@pytest.mark.asyncio
async def test_field_skipped_when_no_variant_has_a_value(db):
    master = _fdb("m3", has_variants=True)
    var_a = _fdb("va3", parent_id="m3")  # no fields set at all
    db.commit()

    fdb = _fake_filamentdb([master, var_a])
    sm = _fake_spoolman([])

    rows = await build_master_default_rows(db, sm, fdb)
    field = rows[0]["fields"]["density"]
    assert field["proposal"] is None
    assert field["would_fill"] is False


@pytest.mark.asyncio
async def test_non_master_filament_produces_no_row(db):
    plain = _fdb("p1", has_variants=False)
    db.commit()

    fdb = _fake_filamentdb([plain])
    sm = _fake_spoolman([])

    rows = await build_master_default_rows(db, sm, fdb)
    assert rows == []


# ---------------------------------------------------------------------------
# apply_master_defaults
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_fills_null_fields_on_both_sides(db):
    master = _fdb("m4", has_variants=True, spool_weight=None, density=None)
    var_a = _fdb("va4", parent_id="m4", spool_weight=200.0, density=1.24)
    var_b = _fdb("vb4", parent_id="m4", spool_weight=200.0, density=1.24)
    db.add(FilamentMapping(spoolman_filament_id=201, filamentdb_id="m4"))
    db.commit()

    fdb = _fake_filamentdb([master, var_a, var_b])
    sm_master = _sm(201, spool_weight=None, density=None)
    sm = _fake_spoolman([sm_master])

    rows = await build_master_default_rows(db, sm, fdb)
    rows_by_id = {r["filamentdb_id"]: r for r in rows}

    filled = await apply_master_defaults(
        db, filamentdb_id="m4", fields=["spool_weight", "density"],
        spoolman=sm, filamentdb=fdb, rows_by_fdb_id=rows_by_id, cycle_id="cyc-1",
    )
    db.commit()

    assert set(filled) == {"spool_weight", "density"}
    fdb.update_filament.assert_awaited_once_with("m4", {"spoolWeight": 200.0, "density": 1.24})
    sm.update_filament.assert_awaited_once_with(201, {"spool_weight": 200.0, "density": 1.24})


@pytest.mark.asyncio
async def test_apply_never_overwrites_a_non_null_sm_value(db):
    """Even though the FDB master field is null (would_fill), the master's live SM
    counterpart already has its own value — that value must never be clobbered."""
    master = _fdb("m5", has_variants=True, spool_weight=None)
    var_a = _fdb("va5", parent_id="m5", spool_weight=200.0)
    db.add(FilamentMapping(spoolman_filament_id=301, filamentdb_id="m5"))
    db.commit()

    fdb = _fake_filamentdb([master, var_a])
    sm_master = _sm(301, spool_weight=175.0)  # already set on the SM side
    sm = _fake_spoolman([sm_master])

    rows = await build_master_default_rows(db, sm, fdb)
    rows_by_id = {r["filamentdb_id"]: r for r in rows}

    filled = await apply_master_defaults(
        db, filamentdb_id="m5", fields=["spool_weight"],
        spoolman=sm, filamentdb=fdb, rows_by_fdb_id=rows_by_id, cycle_id="cyc-2",
    )
    db.commit()

    assert filled == ["spool_weight"]
    fdb.update_filament.assert_awaited_once_with("m5", {"spoolWeight": 200.0})
    sm.update_filament.assert_not_awaited()  # SM already had 175.0 — untouched


@pytest.mark.asyncio
async def test_apply_skips_non_fillable_field_silently(db):
    master = _fdb("m6", has_variants=True, spool_weight=180.0)  # already set
    var_a = _fdb("va6", parent_id="m6", spool_weight=200.0)
    db.commit()

    fdb = _fake_filamentdb([master, var_a])
    sm = _fake_spoolman([])

    rows = await build_master_default_rows(db, sm, fdb)
    rows_by_id = {r["filamentdb_id"]: r for r in rows}

    filled = await apply_master_defaults(
        db, filamentdb_id="m6", fields=["spool_weight"],
        spoolman=sm, filamentdb=fdb, rows_by_fdb_id=rows_by_id, cycle_id="cyc-3",
    )
    assert filled == []
    fdb.update_filament.assert_not_awaited()


@pytest.mark.asyncio
async def test_apply_synthetic_master_skips_sm_write_and_snapshot(db):
    master = _fdb("synth2", has_variants=True, density=None)
    var_a = _fdb("vs2", parent_id="synth2", density=1.24)
    db.add(FilamentMapping(spoolman_filament_id=None, filamentdb_id="synth2", is_synthetic_parent=True))
    db.commit()

    fdb = _fake_filamentdb([master, var_a])
    sm = _fake_spoolman([])

    rows = await build_master_default_rows(db, sm, fdb)
    rows_by_id = {r["filamentdb_id"]: r for r in rows}

    filled = await apply_master_defaults(
        db, filamentdb_id="synth2", fields=["density"],
        spoolman=sm, filamentdb=fdb, rows_by_fdb_id=rows_by_id, cycle_id="cyc-4",
    )
    db.commit()

    assert filled == ["density"]
    fdb.update_filament.assert_awaited_once_with("synth2", {"density": 1.24})
    sm.update_filament.assert_not_awaited()

    from app.core.engine import _get_snapshot
    fdb_snap = _get_snapshot(db, "filamentdb", "filament", "synth2")
    assert fdb_snap["_mp_density"] == 1.24
    sm_snap = _get_snapshot(db, "spoolman", "filament", "synth2")
    assert sm_snap is None  # no SM counterpart — nothing keyed for it


@pytest.mark.asyncio
async def test_apply_unknown_master_raises_value_error(db):
    with pytest.raises(ValueError):
        await apply_master_defaults(
            db, filamentdb_id="does-not-exist", fields=["density"],
            spoolman=_fake_spoolman([]), filamentdb=_fake_filamentdb([]),
            rows_by_fdb_id={}, cycle_id="cyc-5",
        )


# ---------------------------------------------------------------------------
# apply_master_defaults_bulk — per-row failure isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_apply_isolates_per_row_failures(db):
    master_ok = _fdb("m7", has_variants=True, spool_weight=None)
    var_ok = _fdb("va7", parent_id="m7", spool_weight=200.0)
    db.add(FilamentMapping(spoolman_filament_id=401, filamentdb_id="m7"))
    db.commit()

    fdb = _fake_filamentdb([master_ok, var_ok])
    sm = _fake_spoolman([_sm(401, spool_weight=None)])

    result = await apply_master_defaults_bulk(
        db,
        [
            {"filamentdb_id": "m7", "fields": ["spool_weight"]},
            {"filamentdb_id": "does-not-exist", "fields": ["spool_weight"]},
        ],
        sm, fdb,
    )
    assert result["updated"] == 1
    assert len(result["failed"]) == 1
    assert result["failed"][0]["filamentdb_id"] == "does-not-exist"
