"""Tests for Phase B: master_divergence conflict resolution (core/conflict_apply.py
and the updated POST /conflicts/{id}/resolve endpoint).

Covers:
  - apply_all: FDB master write, FDB overridden-variant write, SM filament writes,
    snapshot refresh, sibling auto-resolve, material→type remap
  - variant_override: FDB variant-only write, snapshot refresh, siblings untouched
  - ignore: no upstream writes, snapshot baseline stored
  - apply_all: upstream failure does NOT resolve the conflict
  - variant_override: upstream failure does NOT resolve the conflict
  - 422 when action is missing for a master_divergence conflict
  - action is ignored for non-master_divergence conflicts
  - Async endpoint wiring (via TestClient + faked app.state clients)
  - divergence-context endpoint returns correct shape
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import conflicts as conflicts_router
from app.api.config import set_config_value
from app.core.conflict_apply import (
    _fdb_path_for_sm_field,
    _make_fdb_write,
    _snap_key,
    apply_master_divergence,
)
from app.db import Base, get_db
from app.models.config import seed_defaults
from app.models.conflict import Conflict
from app.models.mapping import FilamentMapping
from app.models.snapshot import Snapshot
from app.schemas.filamentdb import FDBFilamentDetail

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MASTER_FDB_ID = "master-001"
VARIANT_FDB_ID = "variant-002"
OTHER_VARIANT_FDB_ID = "variant-003"
SM_FIL_ID = 42
SM_FIL_ID_2 = 43  # Other variant's SM filament


# ---------------------------------------------------------------------------
# In-memory database fixture (standalone, not using conftest.py db fixture,
# to allow independent session management in TestClient tests)
# ---------------------------------------------------------------------------


def _make_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    seed_defaults(session)
    set_config_value(session, "variant_parent_mode", "promote_color")
    session.commit()
    return session


# ---------------------------------------------------------------------------
# FDB / SM detail helpers
# ---------------------------------------------------------------------------


def _fdb_variant_detail(
    fdb_id: str = VARIANT_FDB_ID,
    parent_id: str = MASTER_FDB_ID,
    density: float | None = 1.24,
    ftype: str | None = "PLA",
    inherited: list[str] | None = None,
) -> FDBFilamentDetail:
    return FDBFilamentDetail.model_validate({
        "_id": fdb_id,
        "name": "Test Variant",
        "type": ftype,
        "density": density,
        "parentId": parent_id,
        "_inherited": inherited or ["density", "type"],
        "_variants": [],
        "spools": [],
    })


def _fdb_master_detail(
    fdb_id: str = MASTER_FDB_ID,
    density: float | None = 1.30,
    ftype: str | None = "PLA",
    variant_ids: list[str] | None = None,
) -> FDBFilamentDetail:
    # FDBVariantRef requires at least _id and name.
    variants_raw = [{"_id": v, "name": f"Variant {v}"} for v in (variant_ids or [VARIANT_FDB_ID])]
    return FDBFilamentDetail.model_validate({
        "_id": fdb_id,
        "name": "Test Master",
        "type": ftype,
        "density": density,
        "_inherited": [],
        "_variants": variants_raw,
        "parentId": None,
        "spools": [],
    })


def _fake_fdb_client(
    variant_detail: FDBFilamentDetail | None = None,
    master_detail: FDBFilamentDetail | None = None,
) -> AsyncMock:
    """Build an AsyncMock FilamentDBClient with canned responses."""
    client = AsyncMock()

    async def _get_filament(fid: str) -> FDBFilamentDetail:
        if fid == MASTER_FDB_ID and master_detail is not None:
            return master_detail
        if variant_detail is not None:
            return variant_detail
        raise ValueError(f"Unexpected get_filament call for {fid}")

    client.get_filament = AsyncMock(side_effect=_get_filament)
    client.update_filament = AsyncMock(return_value=MagicMock())
    return client


def _fake_spoolman_client() -> AsyncMock:
    client = AsyncMock()
    client.update_filament = AsyncMock(return_value=MagicMock())
    return client


# ---------------------------------------------------------------------------
# DB seed helpers
# ---------------------------------------------------------------------------


def _add_filament_mapping(db, fdb_id: str, sm_id: int, parent_id: str | None = None) -> None:
    db.add(FilamentMapping(
        spoolman_filament_id=sm_id,
        filamentdb_id=fdb_id,
        filamentdb_parent_id=parent_id,
    ))
    db.flush()


def _add_conflict(
    db,
    fdb_id: str = VARIANT_FDB_ID,
    sm_id: int = SM_FIL_ID,
    field_name: str = "density",
    sm_value: float = 1.38,
    fdb_value: float = 1.24,
    conflict_type: str = "master_divergence",
) -> Conflict:
    c = Conflict(
        entity_type="filament",
        spoolman_id=sm_id,
        filamentdb_filament_id=fdb_id,
        filamentdb_spool_id=None,
        field_name=field_name,
        spoolman_value=json.dumps(sm_value),
        filamentdb_value=json.dumps(fdb_value),
        conflict_type=conflict_type,
    )
    db.add(c)
    db.flush()
    return c


def _get_snap(db, source: str, entity_type: str, entity_id: str) -> dict | None:
    row = db.query(Snapshot).filter_by(
        source=source, entity_type=entity_type, entity_id=entity_id
    ).first()
    return json.loads(row.data) if row else None


# ---------------------------------------------------------------------------
# Unit tests: _make_fdb_write / _snap_key / _fdb_path_for_sm_field
# ---------------------------------------------------------------------------


def test_make_fdb_write_flat():
    assert _make_fdb_write("density", 1.38) == {"density": 1.38}


def test_make_fdb_write_dotted():
    assert _make_fdb_write("temperatures.bed", 70) == {"temperatures": {"bed": 70}}


def test_fdb_path_material_remap():
    assert _fdb_path_for_sm_field("material") == "type"


def test_fdb_path_same_name():
    assert _fdb_path_for_sm_field("density") == "density"


def test_snap_key():
    assert _snap_key("density") == "_mp_density"
    assert _snap_key("material") == "_mp_material"


# ---------------------------------------------------------------------------
# apply_master_divergence — apply_all action
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_all_writes_fdb_master(db):
    """apply_all: FDB master must be written with new_value."""
    _add_filament_mapping(db, VARIANT_FDB_ID, SM_FIL_ID, parent_id=MASTER_FDB_ID)
    conflict = _add_conflict(db, field_name="density", sm_value=1.38, fdb_value=1.24)
    db.commit()

    master = _fdb_master_detail(density=1.30, variant_ids=[VARIANT_FDB_ID])
    variant = _fdb_variant_detail(density=1.24, inherited=["density"])
    fdb = _fake_fdb_client(variant_detail=variant, master_detail=master)
    sm = _fake_spoolman_client()

    await apply_master_divergence(conflict, "apply_all", db, sm, fdb)

    # Master FDB write
    fdb.update_filament.assert_any_call(MASTER_FDB_ID, {"density": 1.38})
    assert conflict.resolved_at is not None
    assert conflict.resolution == "apply_all"


@pytest.mark.asyncio
async def test_apply_all_writes_sm_filament(db):
    """apply_all: SM filament mapped to the variant is updated."""
    _add_filament_mapping(db, VARIANT_FDB_ID, SM_FIL_ID, parent_id=MASTER_FDB_ID)
    conflict = _add_conflict(db, field_name="density", sm_value=1.38)
    db.commit()

    master = _fdb_master_detail(density=1.30, variant_ids=[VARIANT_FDB_ID])
    variant = _fdb_variant_detail(density=1.24, inherited=["density"])
    fdb = _fake_fdb_client(variant_detail=variant, master_detail=master)
    sm = _fake_spoolman_client()

    await apply_master_divergence(conflict, "apply_all", db, sm, fdb)

    sm.update_filament.assert_any_call(SM_FIL_ID, {"density": 1.38})


@pytest.mark.asyncio
async def test_apply_all_writes_overridden_variant(db):
    """apply_all: variant that has density explicitly overridden (not in _inherited) is also written."""
    _add_filament_mapping(db, VARIANT_FDB_ID, SM_FIL_ID, parent_id=MASTER_FDB_ID)
    # other_variant has density NOT in inherited → explicitly overridden
    _add_filament_mapping(db, OTHER_VARIANT_FDB_ID, SM_FIL_ID_2, parent_id=MASTER_FDB_ID)
    conflict = _add_conflict(db, field_name="density", sm_value=1.38)
    db.commit()

    overridden_variant = FDBFilamentDetail.model_validate({
        "_id": OTHER_VARIANT_FDB_ID, "name": "Other Variant",
        "density": 1.30, "type": "PLA",
        "parentId": MASTER_FDB_ID,
        "_inherited": [],   # density NOT inherited → explicitly overridden
        "_variants": [], "spools": [],
    })

    call_map = {
        MASTER_FDB_ID: _fdb_master_detail(density=1.30, variant_ids=[VARIANT_FDB_ID, OTHER_VARIANT_FDB_ID]),
        VARIANT_FDB_ID: _fdb_variant_detail(density=1.24, inherited=["density"]),
        OTHER_VARIANT_FDB_ID: overridden_variant,
    }

    async def _get_fil(fid: str) -> FDBFilamentDetail:
        return call_map[fid]

    fdb = AsyncMock()
    fdb.get_filament = AsyncMock(side_effect=_get_fil)
    fdb.update_filament = AsyncMock(return_value=MagicMock())
    sm = _fake_spoolman_client()

    await apply_master_divergence(conflict, "apply_all", db, sm, fdb)

    # OTHER_VARIANT_FDB_ID should also be written (explicit override)
    fdb.update_filament.assert_any_call(OTHER_VARIANT_FDB_ID, {"density": 1.38})


@pytest.mark.asyncio
async def test_apply_all_refreshes_snapshots(db):
    """apply_all: snapshots for touched records are updated to new_value to prevent ping-pong."""
    _add_filament_mapping(db, VARIANT_FDB_ID, SM_FIL_ID, parent_id=MASTER_FDB_ID)
    conflict = _add_conflict(db, field_name="density", sm_value=1.38)
    db.commit()

    master = _fdb_master_detail(density=1.30, variant_ids=[VARIANT_FDB_ID])
    variant = _fdb_variant_detail(density=1.24, inherited=["density"])
    fdb = _fake_fdb_client(variant_detail=variant, master_detail=master)
    sm = _fake_spoolman_client()

    await apply_master_divergence(conflict, "apply_all", db, sm, fdb)
    db.commit()

    # SM snapshot for the SM filament should have _mp_density = 1.38
    sm_snap = _get_snap(db, "spoolman", "filament", str(SM_FIL_ID))
    assert sm_snap is not None
    assert sm_snap.get("_mp_density") == 1.38

    # FDB snapshot for master should have _mp_density = 1.38
    master_snap = _get_snap(db, "filamentdb", "filament", MASTER_FDB_ID)
    assert master_snap is not None
    assert master_snap.get("_mp_density") == 1.38

    # FDB snapshot for variant should also be refreshed
    variant_snap = _get_snap(db, "filamentdb", "filament", VARIANT_FDB_ID)
    assert variant_snap is not None
    assert variant_snap.get("_mp_density") == 1.38


@pytest.mark.asyncio
async def test_apply_all_skips_snapshot_refresh_for_failed_write(db):
    """apply_all: a record whose downstream write fails is NOT snapshot-refreshed,
    so it re-detects next cycle. The successful master is still refreshed and the
    conflict still resolves."""
    _add_filament_mapping(db, VARIANT_FDB_ID, SM_FIL_ID, parent_id=MASTER_FDB_ID)
    conflict = _add_conflict(db, field_name="density", sm_value=1.38)
    db.commit()

    master = _fdb_master_detail(density=1.30, variant_ids=[VARIANT_FDB_ID])
    variant = _fdb_variant_detail(density=1.24, inherited=["density"])
    fdb = _fake_fdb_client(variant_detail=variant, master_detail=master)
    sm = _fake_spoolman_client()
    sm.update_filament = AsyncMock(side_effect=RuntimeError("spoolman down"))

    await apply_master_divergence(conflict, "apply_all", db, sm, fdb)
    db.commit()

    sm_snap = _get_snap(db, "spoolman", "filament", str(SM_FIL_ID))
    assert (sm_snap or {}).get("_mp_density") != 1.38      # failed write → not stamped
    master_snap = _get_snap(db, "filamentdb", "filament", MASTER_FDB_ID)
    assert (master_snap or {}).get("_mp_density") == 1.38  # master succeeded → refreshed
    db.refresh(conflict)
    assert conflict.resolved_at is not None                # still resolves


@pytest.mark.asyncio
async def test_apply_all_auto_resolves_sibling_conflicts(db):
    """apply_all: open sibling master_divergence conflicts for the same field/line are auto-resolved."""
    _add_filament_mapping(db, VARIANT_FDB_ID, SM_FIL_ID, parent_id=MASTER_FDB_ID)
    _add_filament_mapping(db, OTHER_VARIANT_FDB_ID, SM_FIL_ID_2, parent_id=MASTER_FDB_ID)

    conflict = _add_conflict(db, fdb_id=VARIANT_FDB_ID, sm_id=SM_FIL_ID, field_name="density", sm_value=1.38)
    sibling = _add_conflict(db, fdb_id=OTHER_VARIANT_FDB_ID, sm_id=SM_FIL_ID_2, field_name="density", sm_value=1.38)
    db.commit()

    call_map = {
        MASTER_FDB_ID: _fdb_master_detail(density=1.30, variant_ids=[VARIANT_FDB_ID, OTHER_VARIANT_FDB_ID]),
        VARIANT_FDB_ID: _fdb_variant_detail(density=1.24, inherited=["density"]),
        OTHER_VARIANT_FDB_ID: _fdb_variant_detail(
            fdb_id=OTHER_VARIANT_FDB_ID, density=1.24, inherited=["density"]
        ),
    }

    async def _get_fil(fid: str) -> FDBFilamentDetail:
        return call_map[fid]

    fdb = AsyncMock()
    fdb.get_filament = AsyncMock(side_effect=_get_fil)
    fdb.update_filament = AsyncMock(return_value=MagicMock())
    sm = _fake_spoolman_client()

    await apply_master_divergence(conflict, "apply_all", db, sm, fdb)
    db.commit()

    # The primary conflict is resolved
    db.refresh(conflict)
    assert conflict.resolved_at is not None

    # The sibling should also be auto-resolved
    db.refresh(sibling)
    assert sibling.resolved_at is not None
    assert sibling.resolution == "apply_all"


@pytest.mark.asyncio
async def test_apply_all_material_type_remap(db):
    """apply_all: SM 'material' field maps to FDB 'type' path."""
    _add_filament_mapping(db, VARIANT_FDB_ID, SM_FIL_ID, parent_id=MASTER_FDB_ID)
    conflict = _add_conflict(db, field_name="material", sm_value="PETG", fdb_value="PLA")
    db.commit()

    master = _fdb_master_detail(ftype="PLA", variant_ids=[VARIANT_FDB_ID])
    variant = _fdb_variant_detail(ftype="PLA", inherited=["type"])
    fdb = _fake_fdb_client(variant_detail=variant, master_detail=master)
    sm = _fake_spoolman_client()

    await apply_master_divergence(conflict, "apply_all", db, sm, fdb)

    # FDB master must be updated with {"type": "PETG"} (remapped from "material")
    fdb.update_filament.assert_any_call(MASTER_FDB_ID, {"type": "PETG"})

    # SM must be updated with {"material": "PETG"} (SM native field name)
    sm.update_filament.assert_any_call(SM_FIL_ID, {"material": "PETG"})


# ---------------------------------------------------------------------------
# apply_master_divergence — variant_override action
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_variant_override_writes_only_variant(db):
    """variant_override: only the variant FDB filament is written; master/siblings untouched."""
    _add_filament_mapping(db, VARIANT_FDB_ID, SM_FIL_ID, parent_id=MASTER_FDB_ID)
    conflict = _add_conflict(db, field_name="density", sm_value=1.38)
    db.commit()

    master = _fdb_master_detail(density=1.30, variant_ids=[VARIANT_FDB_ID])
    variant = _fdb_variant_detail(density=1.24, inherited=["density"])
    fdb = _fake_fdb_client(variant_detail=variant, master_detail=master)
    sm = _fake_spoolman_client()

    await apply_master_divergence(conflict, "variant_override", db, sm, fdb)

    # Only variant written in FDB
    assert fdb.update_filament.call_count == 1
    fdb.update_filament.assert_called_once_with(VARIANT_FDB_ID, {"density": 1.38})

    # SM must NOT be updated (SM is the source of the value already)
    sm.update_filament.assert_not_called()

    assert conflict.resolution == "variant_override"
    assert conflict.resolved_at is not None


@pytest.mark.asyncio
async def test_variant_override_refreshes_snapshots(db):
    """variant_override: snapshots for V + S are refreshed to new_value."""
    _add_filament_mapping(db, VARIANT_FDB_ID, SM_FIL_ID, parent_id=MASTER_FDB_ID)
    conflict = _add_conflict(db, field_name="density", sm_value=1.38)
    db.commit()

    master = _fdb_master_detail(density=1.30, variant_ids=[VARIANT_FDB_ID])
    variant = _fdb_variant_detail(density=1.24, inherited=["density"])
    fdb = _fake_fdb_client(variant_detail=variant, master_detail=master)
    sm = _fake_spoolman_client()

    await apply_master_divergence(conflict, "variant_override", db, sm, fdb)
    db.commit()

    sm_snap = _get_snap(db, "spoolman", "filament", str(SM_FIL_ID))
    assert sm_snap is not None
    assert sm_snap.get("_mp_density") == 1.38

    fdb_snap = _get_snap(db, "filamentdb", "filament", VARIANT_FDB_ID)
    assert fdb_snap is not None
    assert fdb_snap.get("_mp_density") == 1.38


@pytest.mark.asyncio
async def test_variant_override_does_not_auto_resolve_siblings(db):
    """variant_override: sibling conflicts are NOT auto-resolved."""
    _add_filament_mapping(db, VARIANT_FDB_ID, SM_FIL_ID, parent_id=MASTER_FDB_ID)
    _add_filament_mapping(db, OTHER_VARIANT_FDB_ID, SM_FIL_ID_2, parent_id=MASTER_FDB_ID)
    conflict = _add_conflict(db, fdb_id=VARIANT_FDB_ID, sm_id=SM_FIL_ID, field_name="density", sm_value=1.38)
    sibling = _add_conflict(db, fdb_id=OTHER_VARIANT_FDB_ID, sm_id=SM_FIL_ID_2, field_name="density", sm_value=1.38)
    db.commit()

    master = _fdb_master_detail(density=1.30, variant_ids=[VARIANT_FDB_ID])
    variant = _fdb_variant_detail(density=1.24, inherited=["density"])
    fdb = _fake_fdb_client(variant_detail=variant, master_detail=master)
    sm = _fake_spoolman_client()

    await apply_master_divergence(conflict, "variant_override", db, sm, fdb)
    db.commit()

    db.refresh(sibling)
    assert sibling.resolved_at is None, "variant_override should NOT auto-resolve sibling"


# ---------------------------------------------------------------------------
# apply_master_divergence — ignore action
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ignore_makes_no_upstream_writes(db):
    """ignore: no FDB or SM writes are made."""
    _add_filament_mapping(db, VARIANT_FDB_ID, SM_FIL_ID, parent_id=MASTER_FDB_ID)
    conflict = _add_conflict(db, field_name="density", sm_value=1.38)
    db.commit()

    master = _fdb_master_detail(density=1.30, variant_ids=[VARIANT_FDB_ID])
    variant = _fdb_variant_detail(density=1.24, inherited=["density"])
    fdb = _fake_fdb_client(variant_detail=variant, master_detail=master)
    sm = _fake_spoolman_client()

    await apply_master_divergence(conflict, "ignore", db, sm, fdb)

    fdb.update_filament.assert_not_called()
    sm.update_filament.assert_not_called()
    assert conflict.resolution == "ignore"
    assert conflict.resolved_at is not None


@pytest.mark.asyncio
async def test_ignore_stores_baselines_to_suppress_requeue(db):
    """ignore: snapshot baselines are stored both sides so next cycle won't re-queue."""
    _add_filament_mapping(db, VARIANT_FDB_ID, SM_FIL_ID, parent_id=MASTER_FDB_ID)
    conflict = _add_conflict(db, field_name="density", sm_value=1.38, fdb_value=1.24)
    db.commit()

    variant = _fdb_variant_detail(density=1.24, inherited=["density"])
    # For ignore we only need the variant detail
    fdb = AsyncMock()
    fdb.get_filament = AsyncMock(return_value=variant)
    fdb.update_filament = AsyncMock(return_value=MagicMock())
    sm = _fake_spoolman_client()

    await apply_master_divergence(conflict, "ignore", db, sm, fdb)
    db.commit()

    # FDB snapshot should have _mp_density = current FDB value (1.24)
    fdb_snap = _get_snap(db, "filamentdb", "filament", VARIANT_FDB_ID)
    assert fdb_snap is not None
    assert fdb_snap.get("_mp_density") == 1.24

    # SM snapshot should have _mp_density = SM value (1.38)
    sm_snap = _get_snap(db, "spoolman", "filament", str(SM_FIL_ID))
    assert sm_snap is not None
    assert sm_snap.get("_mp_density") == 1.38


# ---------------------------------------------------------------------------
# Upstream failure does NOT resolve the conflict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_all_upstream_failure_does_not_resolve(db):
    """If FDB master write fails, the conflict must remain open."""
    _add_filament_mapping(db, VARIANT_FDB_ID, SM_FIL_ID, parent_id=MASTER_FDB_ID)
    conflict = _add_conflict(db, field_name="density", sm_value=1.38)
    db.commit()

    master = _fdb_master_detail(density=1.30, variant_ids=[VARIANT_FDB_ID])
    variant = _fdb_variant_detail(density=1.24, inherited=["density"])
    fdb = AsyncMock()
    # get_filament succeeds, but update_filament raises
    fdb.get_filament = AsyncMock(side_effect=lambda fid: master if fid == MASTER_FDB_ID else variant)
    fdb.update_filament = AsyncMock(side_effect=Exception("FDB network error"))
    sm = _fake_spoolman_client()

    with pytest.raises(Exception, match="FDB network error"):
        await apply_master_divergence(conflict, "apply_all", db, sm, fdb)

    # Conflict must NOT be resolved
    assert conflict.resolved_at is None


@pytest.mark.asyncio
async def test_variant_override_upstream_failure_does_not_resolve(db):
    """If FDB variant write fails, the conflict must remain open."""
    _add_filament_mapping(db, VARIANT_FDB_ID, SM_FIL_ID, parent_id=MASTER_FDB_ID)
    conflict = _add_conflict(db, field_name="density", sm_value=1.38)
    db.commit()

    variant = _fdb_variant_detail(density=1.24, inherited=["density"])
    master = _fdb_master_detail(density=1.30, variant_ids=[VARIANT_FDB_ID])

    fdb = AsyncMock()
    fdb.get_filament = AsyncMock(side_effect=lambda fid: master if fid == MASTER_FDB_ID else variant)
    fdb.update_filament = AsyncMock(side_effect=Exception("FDB connection refused"))
    sm = _fake_spoolman_client()

    with pytest.raises(Exception, match="FDB connection refused"):
        await apply_master_divergence(conflict, "variant_override", db, sm, fdb)

    assert conflict.resolved_at is None


# ---------------------------------------------------------------------------
# API endpoint tests (via TestClient)
# ---------------------------------------------------------------------------


def _make_test_app(db_session):
    """Build a minimal FastAPI app with the conflicts router and faked state."""
    app = FastAPI()
    app.include_router(conflicts_router.router, prefix="/api")

    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.state.spoolman = _fake_spoolman_client()
    app.state.filamentdb = None  # overridden per test
    return app


def test_api_master_divergence_missing_action_returns_422():
    """POST resolve without action for a master_divergence conflict → 422."""
    db = _make_db()
    _add_conflict(db, conflict_type="master_divergence")
    db.commit()

    c = db.query(Conflict).first()

    app = _make_test_app(db)
    # Set a minimal fdb client that won't be called
    app.state.filamentdb = AsyncMock()

    with TestClient(app) as client:
        resp = client.post(f"/api/conflicts/{c.id}/resolve", json={
            "resolution": "spoolman",
            # action is missing!
        })
    assert resp.status_code == 422


def test_api_other_conflict_type_action_ignored():
    """POST resolve with action for a non-master_divergence conflict is silently ignored."""
    db = _make_db()
    _add_conflict(db, conflict_type="cross_system")
    db.commit()

    c = db.query(Conflict).first()
    app = _make_test_app(db)
    app.state.filamentdb = AsyncMock()
    app.state.spoolman = AsyncMock()

    with TestClient(app) as client:
        resp = client.post(f"/api/conflicts/{c.id}/resolve", json={
            "resolution": "spoolman",
            "action": "apply_all",  # should be ignored
        })
    assert resp.status_code == 200
    data = resp.json()
    assert data["resolution"] == "spoolman"
    assert data["status"] == "resolved"


def test_api_master_divergence_apply_all_calls_apply_logic():
    """POST resolve with action=apply_all on a master_divergence conflict calls apply logic."""
    db = _make_db()
    _add_filament_mapping(db, VARIANT_FDB_ID, SM_FIL_ID, parent_id=MASTER_FDB_ID)
    conflict = _add_conflict(db, conflict_type="master_divergence", field_name="density", sm_value=1.38)
    db.commit()

    master = _fdb_master_detail(density=1.30, variant_ids=[VARIANT_FDB_ID])
    variant = _fdb_variant_detail(density=1.24, inherited=["density"])

    fdb_client = _fake_fdb_client(variant_detail=variant, master_detail=master)
    sm_client = _fake_spoolman_client()

    app = _make_test_app(db)
    app.state.filamentdb = fdb_client
    app.state.spoolman = sm_client

    with TestClient(app) as client:
        resp = client.post(f"/api/conflicts/{conflict.id}/resolve", json={
            "resolution": "spoolman",
            "action": "apply_all",
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "resolved"
    assert data["resolution"] == "apply_all"

    # Verify upstream writes actually happened
    fdb_client.update_filament.assert_any_call(MASTER_FDB_ID, {"density": 1.38})
    sm_client.update_filament.assert_any_call(SM_FIL_ID, {"density": 1.38})


def test_api_master_divergence_upstream_failure_returns_502():
    """If upstream write fails, the endpoint returns 502 and the conflict is not resolved."""
    db = _make_db()
    _add_filament_mapping(db, VARIANT_FDB_ID, SM_FIL_ID, parent_id=MASTER_FDB_ID)
    conflict = _add_conflict(db, conflict_type="master_divergence", field_name="density", sm_value=1.38)
    db.commit()

    variant = _fdb_variant_detail(density=1.24, inherited=["density"])
    master = _fdb_master_detail(density=1.30, variant_ids=[VARIANT_FDB_ID])

    fdb_client = AsyncMock()
    fdb_client.get_filament = AsyncMock(side_effect=lambda fid: master if fid == MASTER_FDB_ID else variant)
    fdb_client.update_filament = AsyncMock(side_effect=Exception("FDB down"))

    app = _make_test_app(db)
    app.state.filamentdb = fdb_client
    app.state.spoolman = _fake_spoolman_client()

    with TestClient(app) as client:
        resp = client.post(f"/api/conflicts/{conflict.id}/resolve", json={
            "resolution": "spoolman",
            "action": "apply_all",
        })

    assert resp.status_code == 502
    # Conflict must still be open
    db.refresh(conflict)
    assert conflict.resolved_at is None


# ---------------------------------------------------------------------------
# Divergence context endpoint
# ---------------------------------------------------------------------------


def test_api_divergence_context_not_master_divergence_returns_400():
    """GET divergence-context on a cross_system conflict → 400."""
    db = _make_db()
    _add_conflict(db, conflict_type="cross_system")
    db.commit()

    c = db.query(Conflict).first()
    app = _make_test_app(db)
    app.state.filamentdb = AsyncMock()

    with TestClient(app) as client:
        resp = client.get(f"/api/conflicts/{c.id}/divergence-context")

    assert resp.status_code == 400


def test_api_divergence_context_not_found_returns_404():
    """GET divergence-context for non-existent id → 404."""
    db = _make_db()
    app = _make_test_app(db)
    app.state.filamentdb = AsyncMock()

    with TestClient(app) as client:
        resp = client.get("/api/conflicts/9999/divergence-context")

    assert resp.status_code == 404


def test_api_divergence_context_returns_correct_shape():
    """GET divergence-context returns master + variant list with expected fields."""
    db = _make_db()
    _add_filament_mapping(db, VARIANT_FDB_ID, SM_FIL_ID, parent_id=MASTER_FDB_ID)
    conflict = _add_conflict(db, conflict_type="master_divergence", field_name="density")
    db.commit()

    master = _fdb_master_detail(density=1.30, variant_ids=[VARIANT_FDB_ID])
    variant = _fdb_variant_detail(density=1.24, inherited=["density"])
    fdb_client = _fake_fdb_client(variant_detail=variant, master_detail=master)

    app = _make_test_app(db)
    app.state.filamentdb = fdb_client

    with TestClient(app) as client:
        resp = client.get(f"/api/conflicts/{conflict.id}/divergence-context")

    assert resp.status_code == 200
    data = resp.json()
    assert data["master_fdb_id"] == MASTER_FDB_ID
    assert data["master_name"] == "Test Master"
    assert data["field_name"] == "density"
    assert data["fdb_path"] == "density"
    assert isinstance(data["variants"], list)
    assert len(data["variants"]) == 1
    v = data["variants"][0]
    assert v["fdb_id"] == VARIANT_FDB_ID
    assert v["spoolman_filament_id"] == SM_FIL_ID
    assert v["inherited"] is True


# ---------------------------------------------------------------------------
# Lifecycle (archive/retire) cross_system conflict resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_lifecycle_conflict_writes_both_sides_and_converges():
    """Resolving a lifecycle cross_system conflict writes the chosen boolean to BOTH
    systems and refreshes both snapshots so it does not re-queue."""
    from app.core.conflict_apply import apply_lifecycle_conflict

    db = _make_db()
    # Diverged: SM archived=true, FDB retired=false.
    c = Conflict(
        entity_type="spool",
        field_name="lifecycle",
        conflict_type="cross_system",
        spoolman_id=7,
        filamentdb_filament_id="fil-7",
        filamentdb_spool_id="spool-7",
        spoolman_value=json.dumps(True),
        filamentdb_value=json.dumps(False),
    )
    db.add(c)
    # Seed snapshots in the diverged state.
    db.add(Snapshot(source="spoolman", entity_type="spool", entity_id="7",
                    data=json.dumps({"remaining_weight": 0.0, "archived": True})))
    db.add(Snapshot(source="filamentdb", entity_type="spool", entity_id="spool-7",
                    data=json.dumps({"totalWeight": 200.0, "retired": False})))
    db.commit()

    spoolman = AsyncMock()
    spoolman.update_spool = AsyncMock(return_value=MagicMock())
    filamentdb = AsyncMock()
    filamentdb.update_spool = AsyncMock(return_value={})

    # Resolution "spoolman" → adopt SM archived (True) on both sides.
    await apply_lifecycle_conflict(c, "spoolman", db, spoolman, filamentdb)
    db.commit()

    spoolman.update_spool.assert_awaited_once_with(7, {"archived": True})
    filamentdb.update_spool.assert_awaited_once_with("fil-7", "spool-7", {"retired": True})
    assert c.resolved_at is not None
    assert json.loads(c.resolved_value) is True
    sm_snap = db.query(Snapshot).filter_by(source="spoolman", entity_type="spool", entity_id="7").first()
    fdb_snap = db.query(Snapshot).filter_by(source="filamentdb", entity_type="spool", entity_id="spool-7").first()
    assert json.loads(sm_snap.data)["archived"] is True
    assert json.loads(fdb_snap.data)["retired"] is True


@pytest.mark.asyncio
async def test_apply_lifecycle_conflict_filamentdb_resolution():
    """Resolution 'filamentdb' adopts the FDB retired state on both sides."""
    from app.core.conflict_apply import apply_lifecycle_conflict

    db = _make_db()
    c = Conflict(
        entity_type="spool", field_name="lifecycle", conflict_type="cross_system",
        spoolman_id=8, filamentdb_filament_id="fil-8", filamentdb_spool_id="spool-8",
        spoolman_value=json.dumps(True), filamentdb_value=json.dumps(False),
    )
    db.add(c)
    db.add(Snapshot(source="spoolman", entity_type="spool", entity_id="8",
                    data=json.dumps({"archived": True})))
    db.add(Snapshot(source="filamentdb", entity_type="spool", entity_id="spool-8",
                    data=json.dumps({"retired": False})))
    db.commit()

    spoolman = AsyncMock()
    spoolman.update_spool = AsyncMock(return_value=MagicMock())
    filamentdb = AsyncMock()
    filamentdb.update_spool = AsyncMock(return_value={})

    await apply_lifecycle_conflict(c, "filamentdb", db, spoolman, filamentdb)
    db.commit()

    spoolman.update_spool.assert_awaited_once_with(8, {"archived": False})
    filamentdb.update_spool.assert_awaited_once_with("fil-8", "spool-8", {"retired": False})
    assert json.loads(c.resolved_value) is False
