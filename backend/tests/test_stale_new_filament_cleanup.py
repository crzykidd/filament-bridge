"""Tests for stale `new_filament` conflict cleanup (issue #83).

Bug: `new_filament` conflicts lingered forever for filaments whose only spools had
gone archived (Spoolman) / retired (FDB) — the stale-conflict cleanup pass only ever
handled `new_spool`, never `new_filament`. Two-part fix in app/core/engine.py:

1. Reactive cleanup: the stale-conflict pass now also auto-resolves an open
   `new_filament` conflict once its filament has no active (non-archived /
   non-retired) spool left. Purely lifecycle-state based — a spool at 0 g remaining
   still counts as "active" as long as it isn't archived/retired.
2. Preventive skip: the FDB->SM new-spool detection loop now skips retired FDB
   spools, so a retired-only FDB orphan filament stops re-queuing a `new_filament`
   conflict every cycle (mirrors the SM side, which is already active-only via the
   `sm_spools` set).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.api.config import set_config_value
from app.models.conflict import Conflict
from app.schemas.filamentdb import FDBFilament
from app.schemas.spoolman import SpoolmanFilament, SpoolmanSpool, SpoolmanVendor


# ---------------------------------------------------------------------------
# Helpers (mirroring tests/test_new_record_upsert.py / test_never_import_empties_engine.py)
# ---------------------------------------------------------------------------


def _sm_spool(
    spool_id: int, filament_id: int, *, remaining: float = 500.0, archived: bool = False,
    vendor: str = "ELEGOO", name: str = "PLA Wood",
) -> SpoolmanSpool:
    fil = SpoolmanFilament(id=filament_id, name=name, vendor=SpoolmanVendor(id=1, name=vendor), material="PLA")
    return SpoolmanSpool(id=spool_id, filament=fil, remaining_weight=remaining, archived=archived, extra={})


def _fdb_fil(fid: str, *, spool_retired: bool = False, spool_id: str = "spool-1") -> FDBFilament:
    return FDBFilament.model_validate({
        "_id": fid, "name": "PLA Basic", "vendor": "Amolen", "type": "PLA",
        "spoolWeight": 200.0,
        "spools": [{"_id": spool_id, "totalWeight": 700.0, "retired": spool_retired}],
    })


def _fake_spoolman(spools: list[SpoolmanSpool]):
    mock = AsyncMock()
    mock.get_spools.return_value = spools
    # Spoolman never returns a spool without a live filament — expose the filaments
    # embedded on the spools so the engine's stale-mapping GC (which purges a mapping
    # whose Spoolman filament is gone) doesn't treat a mapped filament as deleted.
    fils: dict[int, object] = {}
    for s in spools:
        f = getattr(s, "filament", None)
        if f is not None and f.id not in fils:
            fils[f.id] = f
    mock.get_filaments.return_value = list(fils.values())
    mock.create_spool = AsyncMock(return_value={"id": 999})
    mock.update_spool = AsyncMock()
    mock.health = AsyncMock(return_value={"version": "0.22.0"})
    return mock


def _fake_filamentdb(filaments: list[FDBFilament]):
    mock = AsyncMock()
    mock.get_filaments.return_value = filaments
    mock.create_spool = AsyncMock(return_value={"_id": "new-spool", "spools": [{"_id": "new-spool", "label": "999"}]})
    mock.update_spool = AsyncMock()
    mock.get_version = AsyncMock(return_value="1.33.0")
    return mock


def _default_settings(mock_settings):
    mock_settings.filamentdb_spoolman_id_field = "label"
    mock_settings.spoolman_field_filamentdb_id = "filamentdb_id"
    mock_settings.spoolman_field_filamentdb_spool_id = "filamentdb_spool_id"
    mock_settings.spoolman_field_filamentdb_parent_id = "filamentdb_parent_id"
    mock_settings.spoolman_field_filamentdb_material_tags = "filamentdb_material_tags"
    mock_settings.spoolman_field_openprinttag_slug = "openprinttag_slug"
    mock_settings.spoolman_field_openprinttag_uuid = "openprinttag_uuid"
    mock_settings.material_tag_ids = {}


def _seed_new_filament_conflict(db, *, spoolman_id: int | None = None, fdb_filament_id: str | None = None):
    db.add(Conflict(
        entity_type="filament",
        field_name="new_filament",
        spoolman_id=spoolman_id,
        filamentdb_filament_id=fdb_filament_id,
        spoolman_value=json.dumps({"name": "PLA Wood"}) if spoolman_id is not None else None,
        filamentdb_value=json.dumps({"name": "PLA Basic"}) if fdb_filament_id is not None else None,
        conflict_type="new_filament",
    ))
    db.commit()


def _open_new_filament_conflict(db, *, spoolman_id: int | None = None, fdb_filament_id: str | None = None):
    q = db.query(Conflict).filter(
        Conflict.resolved_at.is_(None),
        Conflict.entity_type == "filament",
        Conflict.field_name == "new_filament",
    )
    if spoolman_id is not None:
        q = q.filter(Conflict.spoolman_id == spoolman_id)
    if fdb_filament_id is not None:
        q = q.filter(Conflict.filamentdb_filament_id == fdb_filament_id)
    return q.first()


# ---------------------------------------------------------------------------
# 1. SM side: only spool archived -> auto-resolves
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sm_new_filament_conflict_auto_resolved_when_only_spool_archived(db):
    """An open new_filament conflict for an SM filament whose only spool is now
    archived auto-resolves on the next cycle (the filament can never be imported)."""
    from app.core.engine import run_sync_cycle

    _seed_new_filament_conflict(db, spoolman_id=10)
    set_config_value(db, "new_filament_policy", "manual_review")
    db.commit()

    spoolman = _fake_spoolman([_sm_spool(1, 10, remaining=0.0, archived=True)])
    fdb_client = _fake_filamentdb([])

    with patch("app.core.engine._settings") as ms:
        _default_settings(ms)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="c1")
        db.expire_all()

    resolved = _open_new_filament_conflict(db, spoolman_id=10)
    assert resolved is None, "archived-only filament's new_filament conflict must auto-resolve"

    row = db.query(Conflict).filter(Conflict.spoolman_id == 10, Conflict.field_name == "new_filament").first()
    assert row is not None and row.resolved_at is not None
    assert row.resolution == "resolved_not_imported"


# ---------------------------------------------------------------------------
# 2. SM side: active spool at 0g remaining -> conflict stays open
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sm_new_filament_conflict_survives_when_active_spool_is_empty(db):
    """Guard the product-owner rule: an ACTIVE (non-archived) spool at 0 g remaining
    still keeps the filament's new_filament conflict open — lifecycle state (archived
    or not), not remaining weight, decides. never_import_empties must NOT affect this."""
    from app.core.engine import run_sync_cycle

    _seed_new_filament_conflict(db, spoolman_id=10)
    set_config_value(db, "new_filament_policy", "manual_review")
    set_config_value(db, "never_import_empties", True)
    db.commit()

    spoolman = _fake_spoolman([_sm_spool(1, 10, remaining=0.0, archived=False)])
    fdb_client = _fake_filamentdb([])

    with patch("app.core.engine._settings") as ms:
        _default_settings(ms)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="c1")
        db.expire_all()

    still_open = _open_new_filament_conflict(db, spoolman_id=10)
    assert still_open is not None, "active-but-empty spool must NOT clear the new_filament conflict"


# ---------------------------------------------------------------------------
# 3. FDB side: only spool retired -> auto-resolves
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fdb_new_filament_conflict_auto_resolved_when_only_spool_retired(db):
    """An open new_filament conflict for an FDB filament whose only spool is retired
    auto-resolves on the next cycle."""
    from app.core.engine import run_sync_cycle

    _seed_new_filament_conflict(db, fdb_filament_id="fdb-1")
    set_config_value(db, "new_filament_policy", "manual_review")
    db.commit()

    spoolman = _fake_spoolman([])
    fdb_client = _fake_filamentdb([_fdb_fil("fdb-1", spool_retired=True)])

    with patch("app.core.engine._settings") as ms:
        _default_settings(ms)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="c1")
        db.expire_all()

    resolved = _open_new_filament_conflict(db, fdb_filament_id="fdb-1")
    assert resolved is None, "retired-only FDB filament's new_filament conflict must auto-resolve"

    row = db.query(Conflict).filter(
        Conflict.filamentdb_filament_id == "fdb-1", Conflict.field_name == "new_filament",
    ).first()
    assert row is not None and row.resolved_at is not None
    assert row.resolution == "resolved_not_imported"


# ---------------------------------------------------------------------------
# 4. FDB side preventive: retired-only orphan never queues a new_filament conflict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fdb_retired_only_orphan_does_not_queue_new_filament_conflict(db):
    """A brand-new, never-before-seen FDB filament whose only spool is retired must
    NOT queue a new_filament conflict at all (preventive skip in the FDB->SM
    new-spool detection loop, mirroring the SM side's active-only `sm_spools` set)."""
    from app.core.engine import run_sync_cycle

    set_config_value(db, "new_filament_policy", "manual_review")
    db.commit()

    spoolman = _fake_spoolman([])
    fdb_client = _fake_filamentdb([_fdb_fil("fdb-2", spool_retired=True)])

    with patch("app.core.engine._settings") as ms:
        _default_settings(ms)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="c1")
        db.expire_all()

    assert _open_new_filament_conflict(db, fdb_filament_id="fdb-2") is None
    assert db.query(Conflict).filter(Conflict.filamentdb_filament_id == "fdb-2").count() == 0


# ---------------------------------------------------------------------------
# 5. Regression: live active spool keeps the new_filament conflict open
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_filament_conflict_survives_with_live_active_spool_sm_side(db):
    """Regression: an SM filament with a live (non-archived, non-empty) spool must
    NOT have its new_filament conflict wrongly auto-resolved."""
    from app.core.engine import run_sync_cycle

    _seed_new_filament_conflict(db, spoolman_id=10)
    set_config_value(db, "new_filament_policy", "manual_review")
    db.commit()

    spoolman = _fake_spoolman([_sm_spool(1, 10, remaining=500.0, archived=False)])
    fdb_client = _fake_filamentdb([])

    with patch("app.core.engine._settings") as ms:
        _default_settings(ms)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="c1")
        db.expire_all()

    still_open = _open_new_filament_conflict(db, spoolman_id=10)
    assert still_open is not None, "filament with a live active spool must keep its new_filament conflict"


@pytest.mark.asyncio
async def test_new_filament_conflict_survives_with_live_active_spool_fdb_side(db):
    """Regression (FDB side): an FDB filament with a live (non-retired) spool must
    NOT have its new_filament conflict wrongly auto-resolved."""
    from app.core.engine import run_sync_cycle

    _seed_new_filament_conflict(db, fdb_filament_id="fdb-3")
    set_config_value(db, "new_filament_policy", "manual_review")
    db.commit()

    spoolman = _fake_spoolman([])
    fdb_client = _fake_filamentdb([_fdb_fil("fdb-3", spool_retired=False)])

    with patch("app.core.engine._settings") as ms:
        _default_settings(ms)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="c1")
        db.expire_all()

    still_open = _open_new_filament_conflict(db, fdb_filament_id="fdb-3")
    assert still_open is not None, "filament with a live active spool must keep its new_filament conflict"
