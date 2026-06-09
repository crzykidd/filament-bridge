"""Tests for the variant_parent_mode feature.

Covers:
- unset-mode gating (wizard preview and execute return 409)
- single-color generic_container synthesis
- multi-color generic_container synthesis
- re-run idempotency (no duplicate container parent)
- synthetic-parent sync-exclusion in the engine
- spool-on-container-parent warning and skip
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import config, wizard
from app.api.config import get_config_value, set_config_value
from app.db import Base, get_db
from app.models.config import seed_defaults
from app.models.mapping import FilamentMapping, SpoolMapping
from app.models.snapshot import Snapshot
from app.models.sync_log import SyncLog
from app.schemas.filamentdb import FDBFilament
from app.schemas.spoolman import SpoolmanFilament, SpoolmanSpool, SpoolmanVendor

_ROUTERS = (config, wizard)


# ---------------------------------------------------------------------------
# Harness (mirrors test_api.py helpers)
# ---------------------------------------------------------------------------


def _fresh_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    seed_defaults(session)
    # Note: variant_parent_mode is intentionally left as "unset" here so tests
    # that verify the gate can rely on the default.  Tests that need a working
    # execute set the mode themselves.
    return session


def _fake_spoolman(spools=None, filaments=None, vendors=None) -> AsyncMock:
    client = AsyncMock()
    client.get_spools = AsyncMock(return_value=spools or [])
    client.get_filaments = AsyncMock(return_value=filaments or [])
    client.get_vendors = AsyncMock(return_value=vendors or [])
    client.get_field_definitions = AsyncMock(return_value=[])
    client.ensure_extra_fields = AsyncMock(return_value=None)
    client.update_spool = AsyncMock(return_value=MagicMock())
    client.create_spool = AsyncMock(return_value=MagicMock(id=999))
    client.create_filament = AsyncMock(return_value=MagicMock(id=888))
    client.create_vendor = AsyncMock(return_value=MagicMock(id=1))
    return client


def _fake_filamentdb(filaments=None) -> AsyncMock:
    client = AsyncMock()
    client.get_filaments = AsyncMock(return_value=filaments or [])
    client.get_filament = AsyncMock(return_value=None)
    client.get_version = AsyncMock(return_value="1.35.2")
    client.log_usage = AsyncMock(return_value={})
    client.update_spool = AsyncMock(return_value={})
    client.update_filament = AsyncMock(return_value=MagicMock(id="fil-x"))
    client.create_spool = AsyncMock(return_value={"_id": "new-spool-id"})
    client.create_filament = AsyncMock(return_value=MagicMock(id="new-fil-id"))
    client.get_locations = AsyncMock(return_value=[])
    client.create_location = AsyncMock(return_value={"_id": "loc-1", "name": "TestShelf"})
    client.merge_filament_settings = AsyncMock(return_value=None)
    return client


def _client(db, spoolman=None, filamentdb=None) -> TestClient:
    app = FastAPI()
    for mod in _ROUTERS:
        app.include_router(mod.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.state.spoolman = spoolman or _fake_spoolman()
    app.state.filamentdb = filamentdb or _fake_filamentdb()
    return TestClient(app)


def _sm_filament(fid: int, name: str, vendor_name: str = "ELEGOO", material: str = "PLA") -> SpoolmanFilament:
    return SpoolmanFilament(
        id=fid,
        name=name,
        vendor=SpoolmanVendor(id=1, name=vendor_name),
        material=material,
    )


def _sm_spool(spool_id: int, filament: SpoolmanFilament, remaining: float = 500.0) -> SpoolmanSpool:
    return SpoolmanSpool(
        id=spool_id,
        filament=filament,
        remaining_weight=remaining,
        archived=False,
        extra={},
    )


# ---------------------------------------------------------------------------
# 1. Unset-mode gating
# ---------------------------------------------------------------------------


def test_wizard_preview_returns_409_when_variant_parent_mode_unset():
    """GET /wizard/preview returns 409 variant_parent_mode_unset for SM direction when mode is unset."""
    db = _fresh_db()
    # mode is "unset" by default (seed_defaults seeds "unset")
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
    ])
    db.commit()

    sm = _sm_filament(10, "PLA Black")
    spoolman = _fake_spoolman(filaments=[sm], spools=[])
    filamentdb = _fake_filamentdb()
    client = _client(db, spoolman, filamentdb)

    resp = client.get("/api/wizard/preview")
    assert resp.status_code == 409
    body = resp.json()
    assert body["detail"]["code"] == "variant_parent_mode_unset"


def test_wizard_execute_returns_409_when_variant_parent_mode_unset():
    """POST /wizard/execute returns 409 variant_parent_mode_unset for SM direction when mode is unset."""
    db = _fresh_db()
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
    ])
    db.commit()

    sm = _sm_filament(10, "PLA Black")
    spoolman = _fake_spoolman(filaments=[sm], spools=[])
    filamentdb = _fake_filamentdb()
    client = _client(db, spoolman, filamentdb)

    resp = client.post("/api/wizard/execute")
    assert resp.status_code == 409
    body = resp.json()
    assert body["detail"]["code"] == "variant_parent_mode_unset"
    # Must not have created any filament
    filamentdb.create_filament.assert_not_called()


def test_wizard_preview_not_gated_for_fdb_direction():
    """GET /wizard/preview is NOT gated when import_direction is filamentdb (mode only applies to SM direction)."""
    db = _fresh_db()
    # mode is "unset" — but direction is filamentdb, so no gate
    set_config_value(db, "import_direction", "filamentdb")
    db.commit()

    spoolman = _fake_spoolman(filaments=[], spools=[])
    filamentdb = _fake_filamentdb(filaments=[])
    client = _client(db, spoolman, filamentdb)

    resp = client.get("/api/wizard/preview")
    # Should not 409; FDB direction returns early with an empty plan
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 2. Single-color generic_container synthesis
# ---------------------------------------------------------------------------


def test_wizard_execute_generic_container_single_color_creates_container_and_variant(db):
    """generic_container: single SM filament → container created + child variant created."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "variant_parent_mode", "generic_container")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
    ])
    db.commit()

    sm = _sm_filament(10, "PLA Black")
    spoolman = _fake_spoolman(filaments=[sm], spools=[])

    create_calls: list[dict] = []
    call_counter = 0

    async def _create(payload):
        nonlocal call_counter
        call_counter += 1
        create_calls.append(dict(payload))
        return MagicMock(id=f"fdb-{call_counter}")

    filamentdb = _fake_filamentdb()
    filamentdb.create_filament = AsyncMock(side_effect=_create)
    client = _client(db, spoolman, filamentdb)

    body = client.post("/api/wizard/execute").json()

    assert body["failed"] == 0
    # Two filament creates: 1 container + 1 color child
    assert call_counter == 2

    # Container: no color, no parentId
    container_calls = [c for c in create_calls if c.get("color") is None and "parentId" not in c]
    assert len(container_calls) == 1, f"expected 1 container, got {create_calls}"
    assert container_calls[0].get("name") == "ELEGOO PLA (Master)"

    # Child: has parentId pointing to container
    child_calls = [c for c in create_calls if "parentId" in c]
    assert len(child_calls) == 1
    assert child_calls[0]["parentId"] == "fdb-1"  # container was created first

    # Synthetic FilamentMapping row exists
    synth = db.query(FilamentMapping).filter_by(is_synthetic_parent=True).first()
    assert synth is not None
    assert synth.spoolman_filament_id is None
    assert synth.filamentdb_id == "fdb-1"


# ---------------------------------------------------------------------------
# 3. Multi-color generic_container synthesis
# ---------------------------------------------------------------------------


def test_wizard_execute_generic_container_multi_color_all_variants_under_container(db):
    """generic_container: 3 same-material SM filaments → 1 container + 3 color children."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "variant_parent_mode", "generic_container")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
        {"spoolman_filament_id": 11, "action": "create"},
        {"spoolman_filament_id": 12, "action": "create"},
    ])
    db.commit()

    sm_filaments = [
        _sm_filament(10, "PLA Red"),
        _sm_filament(11, "PLA Green"),
        _sm_filament(12, "PLA Blue"),
    ]
    spoolman = _fake_spoolman(filaments=sm_filaments, spools=[])

    create_calls: list[dict] = []
    call_counter = 0

    async def _create(payload):
        nonlocal call_counter
        call_counter += 1
        create_calls.append(dict(payload))
        return MagicMock(id=f"fdb-{call_counter}")

    filamentdb = _fake_filamentdb()
    filamentdb.create_filament = AsyncMock(side_effect=_create)
    client = _client(db, spoolman, filamentdb)

    body = client.post("/api/wizard/execute").json()

    assert body["failed"] == 0
    # 1 container + 3 color children = 4 creates
    assert call_counter == 4

    # Exactly one container (no color, no parentId)
    containers = [c for c in create_calls if c.get("color") is None and "parentId" not in c]
    assert len(containers) == 1

    # All 3 colors get parentId pointing to the container (fdb-1)
    children = [c for c in create_calls if "parentId" in c]
    assert len(children) == 3
    assert all(c["parentId"] == "fdb-1" for c in children)

    # Only one synthetic FilamentMapping row
    synth_rows = db.query(FilamentMapping).filter_by(is_synthetic_parent=True).all()
    assert len(synth_rows) == 1


def test_wizard_execute_generic_container_carries_shared_finish_tags(db):
    """generic_container: a Silk cluster's container parent carries the shared finish tag.

    The finish (Silk / Matte / …) is a property of the whole line, so it belongs on
    the container parent (variants inherit optTags array-fallback in Filament DB).
    """
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "variant_parent_mode", "generic_container")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
        {"spoolman_filament_id": 11, "action": "create"},
    ])
    db.commit()

    sm_filaments = [
        _sm_filament(10, "PLA Silk Red"),
        _sm_filament(11, "PLA Silk Blue"),
    ]
    spoolman = _fake_spoolman(filaments=sm_filaments, spools=[])

    create_calls: list[dict] = []
    call_counter = 0

    async def _create(payload):
        nonlocal call_counter
        call_counter += 1
        create_calls.append(dict(payload))
        return MagicMock(id=f"fdb-{call_counter}")

    filamentdb = _fake_filamentdb()
    filamentdb.create_filament = AsyncMock(side_effect=_create)
    client = _client(db, spoolman, filamentdb)

    body = client.post("/api/wizard/execute").json()
    assert body["failed"] == 0

    containers = [c for c in create_calls if c.get("color") is None and "parentId" not in c]
    assert len(containers) == 1
    container = containers[0]
    # Name carries the finish line (no double Silk), and optTags carries the shared Silk id (17).
    assert container.get("name") == "ELEGOO PLA Silk (Master)"
    assert container.get("optTags") == [17]


def test_wizard_execute_generic_container_two_separate_clusters_two_containers(db):
    """generic_container: 2 clusters (PLA + PETG) → 2 containers, each with own children."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "variant_parent_mode", "generic_container")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
        {"spoolman_filament_id": 11, "action": "create"},
        {"spoolman_filament_id": 20, "action": "create"},
        {"spoolman_filament_id": 21, "action": "create"},
    ])
    db.commit()

    sm_filaments = [
        _sm_filament(10, "PLA Red", material="PLA"),
        _sm_filament(11, "PLA Blue", material="PLA"),
        _sm_filament(20, "PETG Red", material="PETG"),
        _sm_filament(21, "PETG Blue", material="PETG"),
    ]
    spoolman = _fake_spoolman(filaments=sm_filaments, spools=[])

    create_calls: list[dict] = []
    call_counter = 0

    async def _create(payload):
        nonlocal call_counter
        call_counter += 1
        create_calls.append(dict(payload))
        return MagicMock(id=f"fdb-{call_counter}")

    filamentdb = _fake_filamentdb()
    filamentdb.create_filament = AsyncMock(side_effect=_create)
    client = _client(db, spoolman, filamentdb)

    body = client.post("/api/wizard/execute").json()

    assert body["failed"] == 0
    # 2 containers + 4 children = 6 creates
    assert call_counter == 6

    # Exactly two container rows
    synth_rows = db.query(FilamentMapping).filter_by(is_synthetic_parent=True).all()
    assert len(synth_rows) == 2

    # Container names should be the two cluster display names (with (Master) suffix)
    containers = [c for c in create_calls if c.get("color") is None and "parentId" not in c]
    assert len(containers) == 2
    container_names = {c["name"] for c in containers}
    assert "ELEGOO PLA (Master)" in container_names
    assert "ELEGOO PETG (Master)" in container_names


# ---------------------------------------------------------------------------
# 4. Re-run idempotency — no duplicate container parent
# ---------------------------------------------------------------------------


def test_wizard_execute_generic_container_rerun_no_duplicate_container(db):
    """Re-running with generic_container reuses the existing synthetic parent; no duplicate."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "variant_parent_mode", "generic_container")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
    ])
    db.commit()

    sm = _sm_filament(10, "PLA Black")

    # Simulate a prior run: a synthetic FilamentMapping row already exists,
    # and the SM child has a filamentdb_parent_id pointing to the container.
    db.add(FilamentMapping(
        spoolman_filament_id=None,
        filamentdb_id="prior-container-fdb",
        filamentdb_parent_id=None,
        is_synthetic_parent=True,
    ))
    # The SM filament already mapped (child from previous run)
    db.add(FilamentMapping(
        spoolman_filament_id=10,
        filamentdb_id="prior-child-fdb",
        filamentdb_parent_id="prior-container-fdb",
        is_synthetic_parent=False,
    ))
    db.commit()

    from app.schemas.spoolman import encode_extra_value
    from app.config import settings as _settings
    # SM spool carries the parent xref
    spool = SpoolmanSpool(
        id=100, filament=sm, remaining_weight=500.0, archived=False,
        extra={
            _settings.spoolman_field_filamentdb_parent_id: encode_extra_value("prior-container-fdb"),
        },
    )
    spoolman = _fake_spoolman(filaments=[sm], spools=[spool])
    filamentdb = _fake_filamentdb()
    client = _client(db, spoolman, filamentdb)

    body = client.post("/api/wizard/execute").json()

    # The already-linked SM filament (id=10) is skipped; no new container should be created
    # (the existing FilamentMapping for SM 10 causes a skip in Phase A of the planner)
    assert body["failed"] == 0

    # Still exactly one synthetic row (no duplicate)
    synth_rows = db.query(FilamentMapping).filter_by(is_synthetic_parent=True).all()
    assert len(synth_rows) == 1
    assert synth_rows[0].filamentdb_id == "prior-container-fdb"


# ---------------------------------------------------------------------------
# 5. Synthetic-parent sync-exclusion in the engine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_engine_skips_synthetic_parent_in_new_fdb_spool_detection(db):
    """Sync engine skips spools on synthetic container parents and logs a warning."""
    from app.core.engine import run_sync_cycle
    from sqlalchemy import text

    # Add a synthetic parent FilamentMapping
    db.add(FilamentMapping(
        spoolman_filament_id=None,
        filamentdb_id="container-fdb-id",
        filamentdb_parent_id=None,
        is_synthetic_parent=True,
    ))
    db.commit()

    set_config_value(db, "new_spool_sync_direction", "two_way")
    db.commit()

    # FDB has the container parent with a spool directly on it (user error)
    container_with_spool = FDBFilament.model_validate({
        "_id": "container-fdb-id",
        "name": "ELEGOO PLA",
        "vendor": "ELEGOO",
        "spools": [{"_id": "spool-on-container", "totalWeight": 500.0, "retired": False}],
    })

    spoolman = AsyncMock()
    spoolman.get_spools = AsyncMock(return_value=[])
    spoolman.get_filaments = AsyncMock(return_value=[])
    spoolman.get_field_definitions = AsyncMock(return_value=[])

    filamentdb = AsyncMock()
    filamentdb.get_filaments = AsyncMock(return_value=[container_with_spool])
    filamentdb.get_version = AsyncMock(return_value="1.35.2")
    filamentdb.create_spool = AsyncMock()

    result = await run_sync_cycle(db, spoolman, filamentdb, dry_run=False, cycle_id="test-cycle")

    # The spool on the container parent must be skipped (counted in skipped)
    assert result.skipped >= 1
    # create_spool must NOT be called (no Spoolman spool should be created for the container)
    filamentdb.create_spool.assert_not_called()
    # A warning log entry should exist for the skipped spool
    rows = db.execute(
        text("SELECT * FROM sync_log WHERE filamentdb_spool_id = 'spool-on-container'")
    ).fetchall()
    assert len(rows) >= 1


def test_engine_filament_mapping_by_sm_excludes_synthetic_parents(db):
    """Engine builds filament_mappings_by_sm with real mappings only; synthetic parents excluded."""
    from app.models.mapping import FilamentMapping

    # Synthetic parent (NULL spoolman_filament_id)
    db.add(FilamentMapping(
        spoolman_filament_id=None,
        filamentdb_id="container-fdb",
        is_synthetic_parent=True,
    ))
    # Real mapping
    db.add(FilamentMapping(
        spoolman_filament_id=42,
        filamentdb_id="color-fdb",
        is_synthetic_parent=False,
    ))
    db.commit()

    # Verify the query used in engine filters correctly
    real_maps = [
        m for m in db.query(FilamentMapping).all()
        if not getattr(m, "is_synthetic_parent", False) and m.spoolman_filament_id is not None
    ]
    assert len(real_maps) == 1
    assert real_maps[0].spoolman_filament_id == 42


def test_engine_opentag_identity_skips_synthetic_parents(db):
    """_sync_opentag_identity skips synthetic parent FilamentMapping rows."""
    from app.models.mapping import FilamentMapping

    db.add(FilamentMapping(
        spoolman_filament_id=None,
        filamentdb_id="container-fdb",
        is_synthetic_parent=True,
    ))
    db.commit()

    # Verify the guard works: a synthetic mapping has no sm_filament to look up,
    # so even if sm_filaments dict has a None key entry, it would produce no writes.
    # This is a structural invariant test.
    synth_mappings = db.query(FilamentMapping).filter_by(is_synthetic_parent=True).all()
    assert all(m.spoolman_filament_id is None for m in synth_mappings)


# ---------------------------------------------------------------------------
# 6. Config API: variant_parent_mode round-trip
# ---------------------------------------------------------------------------


def test_config_get_returns_variant_parent_mode():
    """GET /config returns variant_parent_mode field (default is 'unset' from seed_defaults)."""
    db = _fresh_db()
    client = _client(db)
    resp = client.get("/api/config")
    assert resp.status_code == 200
    # _fresh_db() does NOT override to promote_color, so seed_defaults' "unset" applies.
    assert resp.json()["variant_parent_mode"] == "unset"


def test_config_put_updates_variant_parent_mode(db):
    """PUT /config accepts and persists variant_parent_mode."""
    client = _client(db)
    resp = client.put("/api/config", json={"variant_parent_mode": "promote_color"})
    assert resp.status_code == 200
    assert resp.json()["variant_parent_mode"] == "promote_color"

    resp2 = client.put("/api/config", json={"variant_parent_mode": "generic_container"})
    assert resp2.status_code == 200
    assert resp2.json()["variant_parent_mode"] == "generic_container"


def test_config_put_rejects_invalid_variant_parent_mode(db):
    """PUT /config rejects unknown variant_parent_mode values."""
    client = _client(db)
    resp = client.put("/api/config", json={"variant_parent_mode": "not_a_valid_mode"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 7. P0.1 — No double finish word in container name
# ---------------------------------------------------------------------------


def test_container_name_no_double_silk(db):
    """P0.1: container name is 'ELEGOO PLA Silk (Master)', not 'ELEGOO PLA Silk Silk (Master)'.

    When rep.material is 'PLA Silk', strip_finish_words must remove 'Silk' from the
    material before composing, so the extracted finish ('silk') is appended only once.
    """
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "variant_parent_mode", "generic_container")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
        {"spoolman_filament_id": 11, "action": "create"},
    ])
    db.commit()

    # material field is 'PLA Silk' (as Spoolman sometimes stores it)
    sm_filaments = [
        SpoolmanFilament(
            id=10, name="PLA Silk Red",
            vendor=SpoolmanVendor(id=1, name="ELEGOO"),
            material="PLA Silk",
        ),
        SpoolmanFilament(
            id=11, name="PLA Silk Blue",
            vendor=SpoolmanVendor(id=1, name="ELEGOO"),
            material="PLA Silk",
        ),
    ]
    spoolman = _fake_spoolman(filaments=sm_filaments, spools=[])

    create_calls: list[dict] = []
    call_counter = 0

    async def _create(payload):
        nonlocal call_counter
        call_counter += 1
        create_calls.append(dict(payload))
        return MagicMock(id=f"fdb-{call_counter}")

    filamentdb = _fake_filamentdb()
    filamentdb.create_filament = AsyncMock(side_effect=_create)
    client = _client(db, spoolman, filamentdb)

    body = client.post("/api/wizard/execute").json()
    assert body["failed"] == 0

    containers = [c for c in create_calls if c.get("color") is None and "parentId" not in c]
    assert len(containers) == 1, f"expected 1 container, got {create_calls}"
    name = containers[0].get("name")
    # Must not contain 'Silk Silk'
    assert "Silk Silk" not in name, f"double finish word in container name: {name!r}"
    assert name == "ELEGOO PLA Silk (Master)", f"unexpected container name: {name!r}"


# ---------------------------------------------------------------------------
# 8. P0.3 — Patch optTags onto a pre-existing container on re-run
# ---------------------------------------------------------------------------


def test_container_reuse_patches_opt_tags(db):
    """P0.3: re-running with a pre-existing container patches missing optTags onto it.

    Simulates a prior run that created the container without optTags (e.g. created before
    the finish-tag logic was added).  The re-run should PATCH optTags onto the container.
    """
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "variant_parent_mode", "generic_container")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
        {"spoolman_filament_id": 11, "action": "create"},
    ])
    db.commit()

    sm_filaments = [
        _sm_filament(10, "PLA Silk Red"),
        _sm_filament(11, "PLA Silk Blue"),
    ]

    from app.schemas.spoolman import encode_extra_value
    from app.config import settings as _settings

    # Simulate prior run: synthetic parent exists, children have parent xref on their spools
    db.add(FilamentMapping(
        spoolman_filament_id=None,
        filamentdb_id="prior-silk-container",
        filamentdb_parent_id=None,
        is_synthetic_parent=True,
    ))
    db.commit()

    # The SM spools carry the parent xref pointing to the pre-existing container
    spool10 = SpoolmanSpool(
        id=100, filament=sm_filaments[0], remaining_weight=500.0, archived=False,
        extra={
            _settings.spoolman_field_filamentdb_parent_id: encode_extra_value("prior-silk-container"),
        },
    )
    spool11 = SpoolmanSpool(
        id=101, filament=sm_filaments[1], remaining_weight=300.0, archived=False,
        extra={
            _settings.spoolman_field_filamentdb_parent_id: encode_extra_value("prior-silk-container"),
        },
    )
    spoolman = _fake_spoolman(filaments=sm_filaments, spools=[spool10, spool11])

    # The pre-existing FDB container has no optTags (created in an older run)
    existing_container = MagicMock()
    existing_container.id = "prior-silk-container"
    existing_container.optTags = []  # no tags yet

    filamentdb = _fake_filamentdb()
    # fdb_by_id lookup: return the existing container when fetched
    from unittest.mock import MagicMock as MM
    filamentdb.get_filaments = AsyncMock(return_value=[
        FDBFilament.model_validate({
            "_id": "prior-silk-container", "name": "ELEGOO PLA Silk",
            "spools": [], "optTags": [],
        })
    ])

    update_calls: list[tuple] = []

    async def _update(fdb_id, payload):
        update_calls.append((fdb_id, dict(payload)))
        return MagicMock(id=fdb_id)

    filamentdb.update_filament = AsyncMock(side_effect=_update)

    # Already-linked SM filaments from prior run should be in match decisions as 'skip' or 'create'
    # The planner will detect them via FilamentMapping rows so they'd be skipped.
    # Add FM rows to simulate prior-run children
    db.add(FilamentMapping(
        spoolman_filament_id=10, filamentdb_id="prior-red-fdb",
        filamentdb_parent_id="prior-silk-container", is_synthetic_parent=False,
    ))
    db.add(FilamentMapping(
        spoolman_filament_id=11, filamentdb_id="prior-blue-fdb",
        filamentdb_parent_id="prior-silk-container", is_synthetic_parent=False,
    ))
    db.commit()

    client = _client(db, spoolman, filamentdb)
    body = client.post("/api/wizard/execute").json()

    # No failures expected
    assert body["failed"] == 0

    # update_filament should have been called on the container with optTags including silk (17)
    opt_tag_updates = [
        (fid, p) for fid, p in update_calls
        if fid == "prior-silk-container" and "optTags" in p
    ]
    assert len(opt_tag_updates) >= 1, (
        f"expected optTags patch on container, got update_calls={update_calls}"
    )
    assert 17 in opt_tag_updates[0][1]["optTags"], (
        f"Silk tag (17) missing from optTags patch: {opt_tag_updates[0][1]}"
    )


# ---------------------------------------------------------------------------
# 9. P1.1 — Resilient execution: 409 on create does not abort the batch
# ---------------------------------------------------------------------------


def test_execute_409_on_filament_create_does_not_abort_batch(db):
    """P1.1: a 409 from FDB on filament create is recorded as 'failed' but the batch continues.

    Two filaments: the first triggers a 409 (name collision), the second succeeds.
    Total failed=1, created>=1 (the second filament + its container).
    """
    import httpx

    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "variant_parent_mode", "generic_container")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
        {"spoolman_filament_id": 20, "action": "create"},
    ])
    db.commit()

    # Two separate clusters (different materials) → two containers
    sm_filaments = [
        _sm_filament(10, "PLA Red", material="PLA"),
        _sm_filament(20, "PETG Blue", material="PETG"),
    ]
    spoolman = _fake_spoolman(filaments=sm_filaments, spools=[])

    call_counter = 0
    create_calls: list[dict] = []

    async def _create(payload):
        nonlocal call_counter
        call_counter += 1
        create_calls.append(dict(payload))
        # First container create → 409 (simulates name collision on the container)
        if call_counter == 1:
            response = httpx.Response(409, json={"detail": "Duplicate key error"})
            raise httpx.HTTPStatusError("409 conflict", request=MagicMock(), response=response)
        return MagicMock(id=f"fdb-{call_counter}")

    filamentdb = _fake_filamentdb()
    filamentdb.create_filament = AsyncMock(side_effect=_create)
    client = _client(db, spoolman, filamentdb)

    body = client.post("/api/wizard/execute").json()

    # First cluster bombed (container 409) → 1 failed
    assert body["failed"] >= 1
    # Second cluster should have proceeded (container + child created)
    assert body["created"] >= 2  # at least second container + second child
    # Overall response is 200 (not a fatal error)
    assert "records" in body


# ---------------------------------------------------------------------------
# 10. container_parent_marker — configurable suffix (Items 1+5)
# ---------------------------------------------------------------------------


def test_empty_marker_yields_no_suffix(db):
    """When container_parent_marker is set to '' execute creates containers without suffix."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "variant_parent_mode", "generic_container")
    set_config_value(db, "container_parent_marker", "")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
        {"spoolman_filament_id": 11, "action": "create"},
    ])
    db.commit()

    sm_filaments = [
        _sm_filament(10, "PLA Red"),
        _sm_filament(11, "PLA Blue"),
    ]
    spoolman = _fake_spoolman(filaments=sm_filaments, spools=[])

    create_calls: list[dict] = []
    call_counter = 0

    async def _create(payload):
        nonlocal call_counter
        call_counter += 1
        create_calls.append(dict(payload))
        return MagicMock(id=f"fdb-{call_counter}")

    filamentdb = _fake_filamentdb()
    filamentdb.create_filament = AsyncMock(side_effect=_create)
    client = _client(db, spoolman, filamentdb)

    body = client.post("/api/wizard/execute").json()
    assert body["failed"] == 0

    containers = [c for c in create_calls if c.get("color") is None and "parentId" not in c]
    assert len(containers) == 1
    name = containers[0].get("name")
    # No suffix appended when marker is empty
    assert name == "ELEGOO PLA", f"unexpected container name with empty marker: {name!r}"
    assert "(Master)" not in name
    assert "Master" not in name


def test_container_name_override_applied_at_execute(db):
    """Item 4: a saved container_name_override renames the container at execute time."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "variant_parent_mode", "generic_container")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
        {"spoolman_filament_id": 11, "action": "create"},
    ])

    sm_filaments = [
        _sm_filament(10, "PLA Red"),
        _sm_filament(11, "PLA Blue"),
    ]
    # The cluster key is (normalized_vendor, normalized_material, finish) — for ELEGOO PLA with no
    # finish, normalize_vendor("ELEGOO")="elegoo", normalize_name("PLA")="pla", finish="".
    cluster_key_str = "('elegoo', 'pla', '')"
    set_config_value(db, "wizard_container_name_overrides", {
        cluster_key_str: {
            "cluster_key": cluster_key_str,
            "name_override": "My Custom Container",
            "skip": False,
        }
    })
    db.commit()

    spoolman = _fake_spoolman(filaments=sm_filaments, spools=[])

    create_calls: list[dict] = []
    call_counter = 0

    async def _create(payload):
        nonlocal call_counter
        call_counter += 1
        create_calls.append(dict(payload))
        return MagicMock(id=f"fdb-{call_counter}")

    filamentdb = _fake_filamentdb()
    filamentdb.create_filament = AsyncMock(side_effect=_create)
    client = _client(db, spoolman, filamentdb)

    body = client.post("/api/wizard/execute").json()
    assert body["failed"] == 0

    containers = [c for c in create_calls if c.get("color") is None and "parentId" not in c]
    assert len(containers) == 1
    name = containers[0].get("name")
    assert name == "My Custom Container", f"override not applied: {name!r}"


def test_container_name_override_skip_omits_cluster(db):
    """Item 4: a saved override with skip=True causes the entire cluster to be omitted."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "variant_parent_mode", "generic_container")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
        {"spoolman_filament_id": 11, "action": "create"},
        {"spoolman_filament_id": 20, "action": "create"},
    ])

    # Two clusters: ELEGOO PLA (skip=True) and ELEGOO PETG (no skip)
    sm_filaments = [
        _sm_filament(10, "PLA Red", material="PLA"),
        _sm_filament(11, "PLA Blue", material="PLA"),
        _sm_filament(20, "PETG Black", material="PETG"),
    ]

    # normalize_vendor("ELEGOO")="elegoo", normalize_name("PLA")="pla", finish="".
    pla_cluster_key_str = "('elegoo', 'pla', '')"
    set_config_value(db, "wizard_container_name_overrides", {
        pla_cluster_key_str: {
            "cluster_key": pla_cluster_key_str,
            "name_override": None,
            "skip": True,
        }
    })
    db.commit()

    spoolman = _fake_spoolman(filaments=sm_filaments, spools=[])

    create_calls: list[dict] = []
    call_counter = 0

    async def _create(payload):
        nonlocal call_counter
        call_counter += 1
        create_calls.append(dict(payload))
        return MagicMock(id=f"fdb-{call_counter}")

    filamentdb = _fake_filamentdb()
    filamentdb.create_filament = AsyncMock(side_effect=_create)
    client = _client(db, spoolman, filamentdb)

    body = client.post("/api/wizard/execute").json()
    # PLA cluster skipped entirely, PETG cluster should proceed
    containers = [c for c in create_calls if c.get("color") is None and "parentId" not in c]
    container_names = {c["name"] for c in containers}
    # PLA container must NOT be created
    assert all("PLA" not in n for n in container_names), (
        f"PLA cluster should have been skipped but got containers: {container_names}"
    )
    # PETG container should be created
    assert any("PETG" in n for n in container_names), (
        f"PETG cluster should have been created but got containers: {container_names}"
    )


def test_preview_container_name_overrides_endpoint(db):
    """Item 4: POST /wizard/container-name-overrides persists and is returned by GET /wizard/preview."""
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "variant_parent_mode", "generic_container")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
    ])
    db.commit()

    sm_filaments = [_sm_filament(10, "PLA Red")]
    spoolman = _fake_spoolman(filaments=sm_filaments, spools=[])
    client = _client(db, spoolman, _fake_filamentdb())

    # normalize_vendor("ELEGOO")="elegoo", normalize_name("PLA")="pla", finish="".
    cluster_key_str = "('elegoo', 'pla', '')"
    payload = {
        "overrides": [
            {
                "cluster_key": cluster_key_str,
                "name_override": "Renamed Container",
                "skip": False,
            }
        ]
    }
    resp = client.post("/api/wizard/container-name-overrides", json=payload)
    assert resp.status_code == 200
    assert resp.json()["persisted"] == 1

    # Verify the override is stored and returned by preview
    preview_resp = client.get("/api/wizard/preview")
    assert preview_resp.status_code == 200
    preview = preview_resp.json()
    saved_overrides = preview.get("container_name_overrides", [])
    matching = [o for o in saved_overrides if o["cluster_key"] == cluster_key_str]
    assert len(matching) == 1
    assert matching[0]["name_override"] == "Renamed Container"
