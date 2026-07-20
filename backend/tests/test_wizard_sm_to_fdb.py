"""Spoolman→Filament DB single-record import: dry-run must never write upstream.

Regression test for GitHub #65 — the Conflicts "Add" PREVIEW (dry-run) for the
Spoolman→Filament DB direction called the real writer (``_execute_spoolman_to_fdb``
had no ``dry_run`` support), so a preview created real Filament DB filaments/spools
and mutated Spoolman. Mirrors the #64 fix for the opposite direction
(``_execute_fdb_to_spoolman`` / ``tests/test_wizard_fdb_to_sm.py``).
"""

import pytest

from app.core.single_record_import import import_single_sm_filament

from tests.test_variant_parent_mode import (
    _fake_filamentdb,
    _fake_spoolman,
    _sm_filament,
    _sm_spool,
)


def _unmapped_sm_filament_with_spool():
    """A Spoolman filament + spool with no existing FilamentMapping (→ 'create')."""
    fil = _sm_filament(101, "ELEGOO RAPID PLA Plus Orange")
    spool = _sm_spool(501, fil, remaining=500.0)
    return fil, spool


@pytest.mark.asyncio
async def test_sm_to_fdb_dry_run_writes_nothing_but_plans_records(db):
    """A conflict-import PREVIEW (dry_run) must not touch FDB/Spoolman, yet still
    report the filament + spool it would create."""
    fil, spool = _unmapped_sm_filament_with_spool()
    sm = _fake_spoolman(filaments=[fil], spools=[spool])
    fdb = _fake_filamentdb(filaments=[])

    res = await import_single_sm_filament(
        db, "cyc", sm, fdb, fil.id,
        filament_action="create",
        dry_run=True,
    )

    # Not a single upstream write may happen during a preview.
    fdb.create_filament.assert_not_called()
    fdb.create_spool.assert_not_called()
    fdb.update_filament.assert_not_called()
    fdb.merge_filament_settings.assert_not_called()
    sm.update_filament.assert_not_called()
    sm.update_spool.assert_not_called()

    # ...but the plan is still counted: 1 filament + 1 spool, no failures.
    assert res.failed == 0
    assert sum(
        1 for r in res.records if r.entity_type == "filament" and r.action == "created"
    ) == 1
    assert sum(
        1 for r in res.records if r.entity_type == "spool" and r.action == "created"
    ) == 1


@pytest.mark.asyncio
async def test_sm_to_fdb_real_run_writes(db):
    """A real (non-dry) single-record import DOES create in Filament DB — proves
    the dry_run guard above is conditional, not a permanent no-op."""
    fil, spool = _unmapped_sm_filament_with_spool()
    sm = _fake_spoolman(filaments=[fil], spools=[spool])
    fdb = _fake_filamentdb(filaments=[])

    res = await import_single_sm_filament(
        db, "cyc", sm, fdb, fil.id,
        filament_action="create",
        dry_run=False,
    )

    fdb.create_filament.assert_called_once()
    fdb.create_spool.assert_called_once()
    assert res.failed == 0
