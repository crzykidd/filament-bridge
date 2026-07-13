"""FDB→Spoolman wizard import: create-payload shape and master exclusion.

Regression tests for the bug where importing a freshly-created FDB master +
variant into Spoolman failed with HTTP 422 on POST /api/v1/filament:

- Spoolman *requires* ``density`` and ``diameter`` (both > 0) on every filament,
  but FDB frequently leaves them unset (diameter especially). The payload builder
  must substitute the standard FDM defaults rather than omit them.
- Synthetic/container parents (masters) must never be created in Spoolman — a
  master carries no material/density/diameter and would 422; its variants sync on
  their own.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.config import set_config_value
from app.api.wizard import (
    _SM_DEFAULT_DENSITY,
    _SM_DEFAULT_DIAMETER,
    _sm_filament_payload_from_fdb,
)
from app.core.single_record_import import import_single_fdb_filament
from app.schemas.filamentdb import FDBFilament, FDBSpool

from tests.test_variant_parent_mode import _client, _fake_filamentdb, _fake_spoolman


# ---------------------------------------------------------------------------
# 1. Payload builder — required density/diameter never omitted
# ---------------------------------------------------------------------------


def test_payload_defaults_diameter_when_missing():
    """A real variant has density but no diameter → diameter falls back to 1.75."""
    fdb = FDBFilament(_id="v1", name="Amolen PLA Orange", type="PLA", density=1.27,
                      color="#F26A1B")
    payload = _sm_filament_payload_from_fdb(fdb, vendor_id=3)
    assert payload["density"] == 1.27
    assert payload["diameter"] == _SM_DEFAULT_DIAMETER == 1.75
    assert payload["material"] == "PLA"
    assert payload["vendor_id"] == 3


def test_payload_defaults_density_when_missing():
    """Density absent → falls back to the generic default (still > 0 for Spoolman)."""
    fdb = FDBFilament(_id="v2", name="Mystery PLA", type="PLA")
    payload = _sm_filament_payload_from_fdb(fdb, vendor_id=None)
    assert payload["density"] == _SM_DEFAULT_DENSITY
    assert payload["diameter"] == _SM_DEFAULT_DIAMETER
    # both required Spoolman fields are present and positive
    assert payload["density"] > 0 and payload["diameter"] > 0
    assert "vendor_id" not in payload


def test_payload_preserves_real_values():
    """Explicit FDB values win over the defaults."""
    fdb = FDBFilament(_id="v3", name="PETG", type="PETG", density=1.30, diameter=2.85,
                      spoolWeight=180)
    payload = _sm_filament_payload_from_fdb(fdb, vendor_id=1)
    assert payload["density"] == 1.30
    assert payload["diameter"] == 2.85
    assert payload["spool_weight"] == 180


def test_payload_includes_weight_from_net_filament_weight():
    """SM `weight` (needed so a spool's remaining_weight is accepted) ← FDB netFilamentWeight."""
    fdb = FDBFilament(_id="v", name="Ultraglow Green", type="PETG", density=1.5,
                      netFilamentWeight=800, spoolWeight=277)
    payload = _sm_filament_payload_from_fdb(fdb, vendor_id=None)
    assert payload["weight"] == 800


def test_payload_weight_falls_back_to_max_spool_net():
    """No netFilamentWeight → use the largest net (gross − tare) across the spools."""
    fdb = FDBFilament(_id="v", name="X", type="PETG", spoolWeight=277,
                      spools=[FDBSpool(_id="s1", totalWeight=1126)])
    payload = _sm_filament_payload_from_fdb(fdb, vendor_id=None)
    assert payload["weight"] == 1126 - 277  # 849


def test_payload_weight_not_clamped_when_spool_exceeds_nominal():
    """A spool holding more than the nominal net (overfilled reel) must NOT be clamped —
    weight is the max of netFilamentWeight and the largest actual spool net."""
    fdb = FDBFilament(_id="v", name="Ultraglow Green", type="PETG", density=1.5,
                      netFilamentWeight=800, spoolWeight=277,
                      spools=[FDBSpool(_id="s1", totalWeight=1126)])  # net 849 > 800
    payload = _sm_filament_payload_from_fdb(fdb, vendor_id=None)
    assert payload["weight"] == 849  # not clamped to the 800 nominal


def test_payload_omits_weight_when_unknown():
    """No netFilamentWeight, no tare, no spools → weight simply omitted (no spool to create)."""
    fdb = FDBFilament(_id="v", name="X", type="PETG")
    payload = _sm_filament_payload_from_fdb(fdb, vendor_id=None)
    assert "weight" not in payload


# ---------------------------------------------------------------------------
# 2. Execute (FDB→SM) — masters skipped, variants created with valid payload
# ---------------------------------------------------------------------------


def test_execute_fdb_to_sm_skips_master_and_creates_variant(db):
    """A master (hasVariants) is skipped; its variant is created with density+diameter."""
    set_config_value(db, "import_direction", "filamentdb")
    db.commit()

    master = FDBFilament(_id="m1", name="Amolen PLA Silk (Master)", type="PLA",
                         hasVariants=True)
    variant = FDBFilament(
        _id="v1", name="Amolen PLA Silk Pumpkin Orange", type="PLA",
        density=1.27, color="#F26A1B", spoolWeight=150,
        parentId="m1",
        spools=[FDBSpool(_id="s1", totalWeight=650.0)],
    )

    create_payloads: list[dict] = []

    async def _create_filament(payload):
        create_payloads.append(dict(payload))
        return MagicMock(id=888)

    spoolman = _fake_spoolman(filaments=[], spools=[])
    spoolman.create_filament = AsyncMock(side_effect=_create_filament)
    filamentdb = _fake_filamentdb(filaments=[master, variant])
    client = _client(db, spoolman, filamentdb)

    body = client.post("/api/wizard/execute").json()

    # No 422 / failures.
    assert body["failed"] == 0, body

    # The master must NOT be sent to Spoolman; exactly the variant is created.
    assert len(create_payloads) == 1, create_payloads
    created = create_payloads[0]
    assert created["name"] == "Amolen PLA Silk Pumpkin Orange"
    assert created["density"] == 1.27
    assert created["diameter"] == _SM_DEFAULT_DIAMETER  # FDB had none → default

    # The master appears as a skipped filament row, not created/failed.
    master_rows = [r for r in body["records"]
                   if r["entity_type"] == "filament" and r["filamentdb_filament_id"] == "m1"]
    assert len(master_rows) == 1
    assert master_rows[0]["action"] == "skipped"


# ---------------------------------------------------------------------------
# 3. Single-record import (Conflicts "Add") — the path that created junk masters
#    in production: the dry-run "preview" was calling the real writer.
# ---------------------------------------------------------------------------


def _variant_with_spool() -> FDBFilament:
    return FDBFilament(
        _id="v1", name="Amolen PLA Pumpkin Orange", type="PLA",
        density=1.27, color="#F26A1B", spoolWeight=150, parentId="m1",
        spools=[FDBSpool(_id="s1", totalWeight=650.0)],
    )


@pytest.mark.asyncio
async def test_single_import_dry_run_writes_nothing_but_counts(db):
    """A conflict-import PREVIEW (dry_run) must not touch Spoolman/FDB, yet still
    report the filament + spool it would create (incl. the spool count)."""
    sm = _fake_spoolman(filaments=[], spools=[])
    fdb = _fake_filamentdb(filaments=[_variant_with_spool()])

    res = await import_single_fdb_filament(db, "cyc", sm, fdb, "v1", dry_run=True)

    # Not a single upstream write may happen during a preview.
    sm.create_filament.assert_not_called()
    sm.create_spool.assert_not_called()
    sm.create_vendor.assert_not_called()
    fdb.update_spool.assert_not_called()
    # ...but the plan is still counted: 1 filament + 1 spool.
    assert res.failed == 0
    assert sum(1 for r in res.records if r.entity_type == "filament" and r.action == "created") == 1
    assert sum(1 for r in res.records if r.entity_type == "spool" and r.action == "created") == 1


@pytest.mark.asyncio
async def test_single_import_real_run_writes(db):
    """A real (non-dry) single-record import DOES create in Spoolman."""
    sm = _fake_spoolman(filaments=[], spools=[])
    fdb = _fake_filamentdb(filaments=[_variant_with_spool()])

    res = await import_single_fdb_filament(db, "cyc", sm, fdb, "v1", dry_run=False)

    sm.create_filament.assert_called_once()
    sm.create_spool.assert_called_once()
    assert res.failed == 0


@pytest.mark.asyncio
async def test_single_import_master_is_skipped_not_created(db):
    """The exact production bug: importing a master must NOT create it in Spoolman."""
    master = FDBFilament(_id="m1", name="Prusament Ultraglow (Master)", type="PETG",
                         hasVariants=True)
    sm = _fake_spoolman(filaments=[], spools=[])
    fdb = _fake_filamentdb(filaments=[master])

    res = await import_single_fdb_filament(db, "cyc", sm, fdb, "m1", dry_run=False)

    sm.create_filament.assert_not_called()
    assert res.failed == 0
    fil_rows = [r for r in res.records if r.entity_type == "filament"]
    assert len(fil_rows) == 1 and fil_rows[0].action == "skipped"


@pytest.mark.asyncio
async def test_execute_backfills_missing_weight_before_spool(db):
    """An existing link whose SM filament has no `weight` (pre-fix orphan) is
    healed — weight is set before the spool create so it doesn't 400."""
    from app.api.wizard import _ExecResult, _execute_fdb_to_spoolman
    from app.models.mapping import FilamentMapping
    from app.schemas.spoolman import SpoolmanFilament

    db.add(FilamentMapping(spoolman_filament_id=178, filamentdb_id="v1"))
    db.commit()

    sm_fil = SpoolmanFilament(id=178, name="Ultraglow Green", weight=None, spool_weight=277)
    fdb = FDBFilament(_id="v1", name="Ultraglow Green", type="PETG", density=1.5,
                      netFilamentWeight=800, spoolWeight=277,
                      spools=[FDBSpool(_id="s1", totalWeight=1126)])

    sm = _fake_spoolman(filaments=[sm_fil], spools=[])
    fdb_client = _fake_filamentdb(filaments=[fdb])
    res = _ExecResult(cycle_id="c", direction="filamentdb_to_spoolman")

    await _execute_fdb_to_spoolman(db, res, sm, fdb_client, [sm_fil], [fdb],
                                   {}, {}, {}, precision=2)

    # Backfilled with max(nominal 800, spool net 849) so the 849 g isn't clamped.
    sm.update_filament.assert_any_call(178, {"weight": 849})
    sm.create_spool.assert_called_once()
    assert res.failed == 0
