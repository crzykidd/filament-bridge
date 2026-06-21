"""Tests for `never_import_empties` in the ongoing sync engine (new-spool path).

Bug: an empty (0 g) unmapped spool on a mapped filament was re-queued as a `new_spool`
conflict every cycle (it can never auto-import), despite `never_import_empties` being on.
The engine now skips empty spools from new-spool import/conflict when the gate is set, and
auto-resolves any lingering new_spool conflict for an empty/archived (never-importable) spool.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.api.config import set_config_value
from app.models.conflict import Conflict
from app.models.mapping import FilamentMapping
from app.models.sync_log import SyncLog
from app.schemas.filamentdb import FDBFilament
from app.schemas.spoolman import SpoolmanFilament, SpoolmanSpool, SpoolmanVendor


def _sm_spool(spool_id: int, fil_id: int, *, remaining: float, archived: bool = False) -> SpoolmanSpool:
    fil = SpoolmanFilament(id=fil_id, name="PLA Basic", vendor=SpoolmanVendor(id=1, name="Amolen"), material="PLA")
    return SpoolmanSpool(id=spool_id, filament=fil, remaining_weight=remaining, archived=archived, extra={})


def _fdb_fil(fid: str) -> FDBFilament:
    return FDBFilament.model_validate({
        "_id": fid, "name": "PLA Basic", "vendor": "Amolen", "type": "PLA",
        "spoolWeight": 200.0, "spools": [{"_id": "existing", "totalWeight": 700.0, "retired": False}],
    })


def _fake_spoolman(spools):
    m = AsyncMock()
    m.get_spools.return_value = spools
    m.get_filaments.return_value = []
    m.health = AsyncMock(return_value={"version": "0.22.0"})
    return m


def _fake_filamentdb(filaments):
    m = AsyncMock()
    m.get_filaments.return_value = filaments
    m.get_version = AsyncMock(return_value="1.33.0")
    return m


def _settings(ms):
    ms.filamentdb_spoolman_id_field = "label"
    ms.spoolman_field_filamentdb_id = "filamentdb_id"
    ms.spoolman_field_filamentdb_spool_id = "filamentdb_spool_id"
    ms.spoolman_field_filamentdb_parent_id = "filamentdb_parent_id"
    ms.spoolman_field_filamentdb_material_tags = "filamentdb_material_tags"
    ms.spoolman_field_openprinttag_slug = "openprinttag_slug"
    ms.spoolman_field_openprinttag_uuid = "openprinttag_uuid"
    ms.material_tag_ids = {}


def _open_new_spool_conflicts(db, spool_id: int):
    return (
        db.query(Conflict)
        .filter(
            Conflict.resolved_at.is_(None),
            Conflict.entity_type == "spool",
            Conflict.field_name == "new_spool",
            Conflict.spoolman_id == spool_id,
        )
        .all()
    )


@pytest.mark.asyncio
async def test_empty_spool_on_mapped_filament_skipped_when_gate_on(db):
    """never_import_empties=on: an empty unmapped spool on a mapped filament is skipped —
    no new_spool conflict, and a skip is logged."""
    from app.core.engine import run_sync_cycle

    db.add(FilamentMapping(spoolman_filament_id=50, filamentdb_id="fdb-50"))
    set_config_value(db, "new_spool_policy", "manual_review")
    set_config_value(db, "never_import_empties", True)
    db.commit()

    spoolman = _fake_spoolman([_sm_spool(208, 50, remaining=0.0)])
    fdb = _fake_filamentdb([_fdb_fil("fdb-50")])

    with patch("app.core.engine._settings") as ms:
        _settings(ms)
        await run_sync_cycle(db, spoolman, fdb, dry_run=False, cycle_id="c1")
        db.expire_all()

    assert _open_new_spool_conflicts(db, 208) == [], "empty spool must NOT be queued as a conflict"
    skips = db.query(SyncLog).filter(
        SyncLog.action == "skip", SyncLog.entity_type == "spool", SyncLog.spoolman_id == 208,
    ).all()
    assert len(skips) >= 1, "expected a skip log entry for the empty spool"


@pytest.mark.asyncio
async def test_empty_spool_conflicts_when_gate_off(db):
    """Control: never_import_empties=off → the empty spool still queues a new_spool conflict
    (existing behavior), proving the gate is what suppresses it."""
    from app.core.engine import run_sync_cycle

    db.add(FilamentMapping(spoolman_filament_id=50, filamentdb_id="fdb-50"))
    set_config_value(db, "new_spool_policy", "manual_review")
    set_config_value(db, "never_import_empties", False)
    db.commit()

    spoolman = _fake_spoolman([_sm_spool(208, 50, remaining=0.0)])
    fdb = _fake_filamentdb([_fdb_fil("fdb-50")])

    with patch("app.core.engine._settings") as ms:
        _settings(ms)
        await run_sync_cycle(db, spoolman, fdb, dry_run=False, cycle_id="c1")
        db.expire_all()

    assert len(_open_new_spool_conflicts(db, 208)) == 1, "gate off → empty spool conflicts as before"


@pytest.mark.asyncio
async def test_lingering_empty_spool_conflict_auto_resolved(db):
    """A pre-existing open new_spool conflict for an empty spool is auto-resolved once the
    gate is on (the spool can never import, so the conflict shouldn't linger)."""
    from app.core.engine import run_sync_cycle

    db.add(FilamentMapping(spoolman_filament_id=50, filamentdb_id="fdb-50"))
    set_config_value(db, "new_spool_policy", "manual_review")
    set_config_value(db, "never_import_empties", True)
    db.add(Conflict(
        entity_type="spool", field_name="new_spool", spoolman_id=208,
        filamentdb_filament_id="fdb-50", spoolman_value=json.dumps({"name": "PLA Basic"}),
        conflict_type="new_spool",
    ))
    db.commit()

    spoolman = _fake_spoolman([_sm_spool(208, 50, remaining=0.0)])
    fdb = _fake_filamentdb([_fdb_fil("fdb-50")])

    with patch("app.core.engine._settings") as ms:
        _settings(ms)
        await run_sync_cycle(db, spoolman, fdb, dry_run=False, cycle_id="c1")
        db.expire_all()

    assert _open_new_spool_conflicts(db, 208) == [], "lingering empty-spool conflict must be auto-resolved"
    resolved = db.query(Conflict).filter(Conflict.spoolman_id == 208, Conflict.field_name == "new_spool").first()
    assert resolved is not None and resolved.resolved_at is not None
    assert resolved.resolution == "resolved_not_imported"
