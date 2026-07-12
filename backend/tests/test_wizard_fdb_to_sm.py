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

from app.api.config import set_config_value
from app.api.wizard import (
    _SM_DEFAULT_DENSITY,
    _SM_DEFAULT_DIAMETER,
    _sm_filament_payload_from_fdb,
)
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
