"""Tests for the upsert (replace-on-resync) behavior of new_filament / new_spool
conflict queuing, and for identity-blob persistence.

Bug 1 (dedup): two sync cycles over the same unmapped item produce exactly ONE
open conflict, not two.  A pre-seeded duplicate collapses on the next cycle.
An unrelated cross_system conflict on a mapped item is never wiped.

Bug 2 (identity): the conflict row stores vendor/name/color_hex/material as a
JSON blob in spoolman_value / filamentdb_value; _conflict_identity reads it
when no snapshot exists (new_filament / new_spool have no snapshot).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.config import BridgeConfig, seed_defaults
from app.models.conflict import Conflict
from app.models.mapping import FilamentMapping
from app.schemas.filamentdb import FDBFilament
from app.schemas.spoolman import SpoolmanFilament, SpoolmanSpool, SpoolmanVendor
from app.api.conflicts import _conflict_identity, _to_response


# ---------------------------------------------------------------------------
# In-memory DB fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    seed_defaults(session)
    session.commit()
    yield session
    session.close()


# ---------------------------------------------------------------------------
# Helpers mirroring test_engine.py
# ---------------------------------------------------------------------------


def _sm_spool_rich(spool_id: int, filament_id: int, vendor: str, name: str, color_hex: str | None = None, material: str | None = None) -> SpoolmanSpool:
    fil = SpoolmanFilament(
        id=filament_id,
        name=name,
        vendor=SpoolmanVendor(id=1, name=vendor),
        color_hex=color_hex,
        material=material,
    )
    return SpoolmanSpool(id=spool_id, filament=fil, remaining_weight=500.0, archived=False, extra={})


def _fdb_filament_rich(fid: str, spool_id: str, vendor: str, name: str, color: str | None = None, type_: str | None = None) -> FDBFilament:
    return FDBFilament.model_validate({
        "_id": fid,
        "name": name,
        "vendor": vendor,
        "color": color,
        "type": type_,
        "spoolWeight": 200.0,
        "spools": [{"_id": spool_id, "totalWeight": 700.0, "retired": False}],
    })


def _fake_spoolman(spools: list[SpoolmanSpool]):
    mock = AsyncMock()
    mock.get_spools.return_value = spools
    mock.get_filaments.return_value = []
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


def _seed_policy(db, filament_policy: str = "manual_review", spool_policy: str = "manual_review"):
    db.merge(BridgeConfig(key="new_filament_policy", value=json.dumps(filament_policy)))
    db.merge(BridgeConfig(key="new_spool_policy", value=json.dumps(spool_policy)))
    db.commit()


def _add_fil_mapping(db, sm_fil_id: int, fdb_fil_id: str):
    db.add(FilamentMapping(spoolman_filament_id=sm_fil_id, filamentdb_id=fdb_fil_id))
    db.commit()


# ---------------------------------------------------------------------------
# Bug 1 — upsert dedup: exactly ONE open conflict per (item, kind)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_cycles_produce_one_new_filament_conflict(db):
    """Two sync cycles over the same unmapped SM filament produce exactly ONE open
    new_filament conflict (not two).  The second cycle replaces the first."""
    from app.core.engine import run_sync_cycle

    sm_spool = _sm_spool_rich(1, filament_id=10, vendor="ELEGOO", name="PLA Wood", color_hex="8B5E3C", material="PLA")
    _seed_policy(db, filament_policy="manual_review")
    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[])

    with patch("app.core.engine._settings") as ms:
        _default_settings(ms)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="cycle-1")
        db.expire_all()
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="cycle-2")
        db.expire_all()

    open_conflicts = (
        db.query(Conflict)
        .filter(
            Conflict.resolved_at.is_(None),
            Conflict.entity_type == "filament",
            Conflict.field_name == "new_filament",
            Conflict.spoolman_id == 10,
        )
        .all()
    )
    assert len(open_conflicts) == 1, (
        f"Expected exactly 1 open new_filament conflict, got {len(open_conflicts)}"
    )


@pytest.mark.asyncio
async def test_conflict_id_is_stable_across_cycles(db):
    """Re-queuing the same unmapped item across cycles UPDATES the row in place — its
    `id` is preserved (issue #44).  A churned id would 404 the Add/import/suggestions
    endpoints (which look the conflict up by id) the moment a sync cycle fires."""
    from app.core.engine import run_sync_cycle

    sm_spool = _sm_spool_rich(1, filament_id=10, vendor="ELEGOO", name="PLA Wood", color_hex="8B5E3C", material="PLA")
    _seed_policy(db, filament_policy="manual_review")
    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[])

    def _open_id() -> int:
        c = (
            db.query(Conflict)
            .filter(
                Conflict.resolved_at.is_(None),
                Conflict.entity_type == "filament",
                Conflict.field_name == "new_filament",
                Conflict.spoolman_id == 10,
            )
            .one()
        )
        return c.id

    with patch("app.core.engine._settings") as ms:
        _default_settings(ms)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="stable-1")
        db.expire_all()
        first_id = _open_id()
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="stable-2")
        db.expire_all()
        second_id = _open_id()

    assert first_id == second_id, (
        f"Conflict id must be stable across cycles (was {first_id}, became {second_id}) — "
        "a churned id breaks the Add/import/suggestions by-id lookup"
    )


@pytest.mark.asyncio
async def test_pre_seeded_duplicate_collapses_on_next_cycle(db):
    """A pre-seeded duplicate new_filament conflict collapses to one on the next cycle."""
    from app.core.engine import run_sync_cycle

    # Seed TWO open conflicts for the same filament (simulates the old buggy state).
    for _ in range(2):
        db.add(Conflict(
            entity_type="filament",
            field_name="new_filament",
            spoolman_id=10,
            spoolman_value='"stale"',
            conflict_type="cross_system",
        ))
    db.flush()

    sm_spool = _sm_spool_rich(1, filament_id=10, vendor="ELEGOO", name="PLA", color_hex=None, material="PLA")
    _seed_policy(db, filament_policy="manual_review")
    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[])

    with patch("app.core.engine._settings") as ms:
        _default_settings(ms)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="dedup-cycle")
        db.expire_all()

    open_conflicts = (
        db.query(Conflict)
        .filter(
            Conflict.resolved_at.is_(None),
            Conflict.entity_type == "filament",
            Conflict.field_name == "new_filament",
            Conflict.spoolman_id == 10,
        )
        .all()
    )
    assert len(open_conflicts) == 1, (
        f"Pre-seeded duplicates must collapse to 1 on next cycle, got {len(open_conflicts)}"
    )


@pytest.mark.asyncio
async def test_unrelated_cross_system_conflict_survives_upsert(db):
    """An unrelated cross_system conflict on a different field of a mapped item is
    NOT wiped by the new_filament upsert."""
    from app.core.engine import run_sync_cycle
    from app.models.mapping import SpoolMapping
    from app.models.snapshot import Snapshot

    # Seed a mapped spool with a pre-existing cross_system density conflict.
    _add_fil_mapping(db, sm_fil_id=10, fdb_fil_id="fil-mapped")
    db.add(SpoolMapping(
        spoolman_spool_id=1,
        filamentdb_filament_id="fil-mapped",
        filamentdb_spool_id="spool-mapped",
        filament_mapping_id=db.query(FilamentMapping).first().id,
    ))
    db.add(Snapshot(source="spoolman", entity_type="spool", entity_id="1",
                    data=json.dumps({"remaining_weight": 500.0, "filament": {"id": 10, "name": "PLA", "spool_weight": 200.0}})))
    db.add(Snapshot(source="filamentdb", entity_type="spool", entity_id="spool-mapped",
                    data=json.dumps({"totalWeight": 700.0})))

    # The cross_system conflict on the mapped item.
    unrelated = Conflict(
        entity_type="filament",
        field_name="density",
        spoolman_id=10,
        filamentdb_filament_id="fil-mapped",
        spoolman_value=json.dumps(1.24),
        filamentdb_value=json.dumps(1.30),
        conflict_type="cross_system",
    )
    db.add(unrelated)
    db.flush()
    unrelated_id = unrelated.id

    # Run a cycle that has the MAPPED spool (no new_filament conflict should be queued
    # for it since it's mapped; only the unrelated cross_system conflict should survive).
    sm_spool = _sm_spool_rich(1, filament_id=10, vendor="ELEGOO", name="PLA", color_hex=None, material="PLA")
    _seed_policy(db, filament_policy="manual_review")
    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_fil = _fdb_filament_rich("fil-mapped", "spool-mapped", "elegoo", "PLA")
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])

    with patch("app.core.engine._settings") as ms:
        _default_settings(ms)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="survive-cycle")
        db.expire_all()

    # The unrelated cross_system conflict must still be open.
    surviving = db.query(Conflict).filter_by(id=unrelated_id).first()
    assert surviving is not None, "Unrelated conflict row must still exist"
    assert surviving.resolved_at is None, "Unrelated cross_system conflict must not be resolved"


@pytest.mark.asyncio
async def test_two_cycles_produce_one_new_spool_conflict_sm_side(db):
    """Two cycles for the same unmapped SM spool on a mapped filament → exactly ONE
    open new_spool conflict."""
    from app.core.engine import run_sync_cycle

    _add_fil_mapping(db, sm_fil_id=50, fdb_fil_id="fdb-fil-50")
    _seed_policy(db, spool_policy="manual_review")

    sm_spool = _sm_spool_rich(501, filament_id=50, vendor="Bambu", name="PLA Basic", color_hex="0000FF", material="PLA")
    fdb_fil = _fdb_filament_rich("fdb-fil-50", "existing-spool", "Bambu", "PLA Basic")
    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])

    with patch("app.core.engine._settings") as ms:
        _default_settings(ms)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="ns-1")
        db.expire_all()
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="ns-2")
        db.expire_all()

    open_ns = (
        db.query(Conflict)
        .filter(
            Conflict.resolved_at.is_(None),
            Conflict.entity_type == "spool",
            Conflict.field_name == "new_spool",
            Conflict.spoolman_id == 501,
        )
        .all()
    )
    assert len(open_ns) == 1, (
        f"Expected exactly 1 open new_spool conflict for SM spool 501, got {len(open_ns)}"
    )


@pytest.mark.asyncio
async def test_new_filament_conflict_type_is_new_filament(db):
    """new_filament conflicts are stored with conflict_type='new_filament', not 'cross_system'."""
    from app.core.engine import run_sync_cycle

    sm_spool = _sm_spool_rich(1, filament_id=10, vendor="ELEGOO", name="PLA", color_hex=None, material="PLA")
    _seed_policy(db, filament_policy="manual_review")
    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[])

    with patch("app.core.engine._settings") as ms:
        _default_settings(ms)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="ct-1")
        db.expire_all()

    c = db.query(Conflict).filter(
        Conflict.resolved_at.is_(None),
        Conflict.field_name == "new_filament",
        Conflict.spoolman_id == 10,
    ).first()
    assert c is not None
    assert c.conflict_type == "new_filament", (
        f"Expected conflict_type='new_filament', got '{c.conflict_type}'"
    )


# ---------------------------------------------------------------------------
# Bug 2 — identity blob: vendor/name/color_hex/material stored + surfaced
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_filament_conflict_stores_identity_blob(db):
    """A new_filament conflict row stores vendor/name/color_hex/material as a
    JSON blob in spoolman_value."""
    from app.core.engine import run_sync_cycle

    sm_spool = _sm_spool_rich(1, filament_id=10, vendor="ELEGOO", name="PLA Wood", color_hex="8B5E3C", material="PLA")
    _seed_policy(db, filament_policy="manual_review")
    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[])

    with patch("app.core.engine._settings") as ms:
        _default_settings(ms)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="id-1")
        db.expire_all()

    c = db.query(Conflict).filter(
        Conflict.resolved_at.is_(None),
        Conflict.field_name == "new_filament",
        Conflict.spoolman_id == 10,
    ).first()
    assert c is not None
    blob = json.loads(c.spoolman_value)
    assert isinstance(blob, dict), "spoolman_value must be a JSON object"
    assert blob["vendor"] == "ELEGOO"
    assert blob["name"] == "PLA Wood"
    assert blob["color_hex"] == "8B5E3C"
    assert blob["material"] == "PLA"


@pytest.mark.asyncio
async def test_identity_from_blob_surfaced_by_conflict_identity(db):
    """_conflict_identity reads the JSON blob for new_filament rows (no snapshot exists)
    and returns vendor/name/color_hex/label."""
    # Seed a new_filament conflict with a JSON identity blob (no snapshot).
    identity_blob = {"vendor": "Bambu", "name": "PLA Basic Blue", "color_hex": "0000FF", "material": "PLA"}
    c = Conflict(
        entity_type="filament",
        field_name="new_filament",
        spoolman_id=77,
        spoolman_value=json.dumps(identity_blob),
        conflict_type="new_filament",
    )
    db.add(c)
    db.flush()

    identity = _conflict_identity(db, c)

    assert identity["vendor"] == "Bambu"
    assert identity["name"] == "PLA Basic Blue"
    assert identity["color_hex"] == "0000FF"
    assert identity["material"] == "PLA"
    assert "Bambu" in identity["label"]
    assert "PLA Basic Blue" in identity["label"]
    assert "SM #77" in identity["label"] or "77" in identity["label"]


def test_identity_from_blob_legacy_string_falls_back(db):
    """_conflict_identity falls back gracefully for legacy rows whose spoolman_value
    is a plain string (old format), not a JSON object with 'name' key."""
    c = Conflict(
        entity_type="filament",
        field_name="new_filament",
        spoolman_id=99,
        spoolman_value=json.dumps("Spoolman filament 99 has no FDB match"),
        conflict_type="cross_system",
    )
    db.add(c)
    db.flush()

    identity = _conflict_identity(db, c)

    # Should return an id-based fallback without crashing.
    assert identity["label"] is not None
    assert "99" in identity["label"]
    # Fields without blob data should be None.
    assert identity["vendor"] is None
    assert identity["name"] is None


def test_to_response_carries_identity_from_blob(db):
    """_to_response returns a ConflictResponse with vendor/name/color_hex populated
    from the JSON blob when no snapshot exists."""
    identity_blob = {"vendor": "ELEGOO", "name": "PLA Marble", "color_hex": "AAAAAA", "material": "PLA"}
    c = Conflict(
        entity_type="filament",
        field_name="new_filament",
        spoolman_id=136,
        spoolman_value=json.dumps(identity_blob),
        conflict_type="new_filament",
    )
    db.add(c)
    db.flush()

    response = _to_response(c, db)

    assert response.vendor == "ELEGOO"
    assert response.name == "PLA Marble"
    assert response.color_hex == "AAAAAA"
    assert response.material == "PLA"
    assert "ELEGOO" in (response.label or "")
    assert "PLA Marble" in (response.label or "")
