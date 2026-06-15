"""Tests for extract_created_spool_id and its integration at both call sites.

Verifies the fix for the critical bug where create_spool (POST /api/filaments/:id/spools)
returns the *filament* document whose ``_id`` is the filament id, not the spool id.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import config, conflicts, health, mappings, sync, sync_log, wizard
from app.api.config import set_config_value
from app.db import Base, get_db
from app.models.config import seed_defaults
from app.models.mapping import FilamentMapping, SpoolMapping
from app.schemas.filamentdb import FDBFilament
from app.schemas.spoolman import SpoolmanFilament, SpoolmanSpool, SpoolmanVendor
from app.core.engine import run_sync_cycle
from app.services.filamentdb import extract_created_spool_id

# ---------------------------------------------------------------------------
# Unit tests — extract_created_spool_id
# ---------------------------------------------------------------------------


def _filament_resp(
    filament_id: str,
    spools: list[dict],
) -> dict:
    """Build a FDB-shaped filament response with an embedded spools list."""
    return {"_id": filament_id, "name": "PLA", "spools": spools}


def test_extract_label_match_returns_spool_id_not_filament_id():
    """Given a filament-doc response the extractor returns the spool _id, NOT the filament _id."""
    resp = _filament_resp(
        "FILAMENT-ID-aaaaaa",
        [
            {"_id": "SPOOL-ID-111", "label": "128"},
            {"_id": "SPOOL-ID-222", "label": "999"},
        ],
    )
    result = extract_created_spool_id(resp, label_field="label", label_value="128")
    assert result == "SPOOL-ID-111"
    assert result != "FILAMENT-ID-aaaaaa"


def test_extract_label_match_second_spool():
    """Label match can be the second spool in the array."""
    resp = _filament_resp(
        "FILAMENT-ID-bbbbbb",
        [
            {"_id": "SPOOL-ID-AAA", "label": "42"},
            {"_id": "SPOOL-ID-BBB", "label": "99"},
        ],
    )
    result = extract_created_spool_id(resp, label_field="label", label_value="99")
    assert result == "SPOOL-ID-BBB"


def test_extract_last_spool_fallback_when_no_label_match():
    """When no spool matches the label, fall back to the last spool in the array."""
    resp = _filament_resp(
        "FILAMENT-ID-cccccc",
        [
            {"_id": "SPOOL-FIRST", "label": "10"},
            {"_id": "SPOOL-LAST", "label": "20"},
        ],
    )
    # label_value doesn't match any spool — should return the LAST spool
    result = extract_created_spool_id(resp, label_field="label", label_value="99")
    assert result == "SPOOL-LAST"
    assert result != "FILAMENT-ID-cccccc"


def test_extract_bare_spool_response():
    """If the response has no 'spools' key, treat it as a bare spool subdocument."""
    bare_spool = {"_id": "BARE-SPOOL-ID", "totalWeight": 1000.0}
    result = extract_created_spool_id(bare_spool, label_field="label", label_value="128")
    assert result == "BARE-SPOOL-ID"


def test_extract_empty_spools_list_falls_through_to_bare():
    """An empty spools list falls through to the bare-spool path."""
    resp = {"_id": "FILAMENT-NO-SPOOLS", "spools": []}
    result = extract_created_spool_id(resp, label_field="label", label_value="128")
    # No spools — top-level _id is used as the spool id (bare path)
    assert result == "FILAMENT-NO-SPOOLS"


def test_extract_empty_dict_returns_empty_string():
    """Returns '' when neither spools nor a top-level _id is present."""
    result = extract_created_spool_id({}, label_field="label", label_value="128")
    assert result == ""


def test_extract_label_value_type_coercion():
    """label_value=128 (int) should match a spool with label='128' (str)."""
    resp = _filament_resp(
        "FIL-ID",
        [{"_id": "SPOOL-COERCE", "label": "128"}],
    )
    result = extract_created_spool_id(resp, label_field="label", label_value="128")
    assert result == "SPOOL-COERCE"


def test_extract_uses_id_field_when_underscore_id_absent():
    """Spool subdoc may use 'id' instead of '_id' — both are accepted."""
    resp = _filament_resp(
        "FIL-ID",
        [{"id": "SPOOL-ALT-ID", "label": "55"}],
    )
    result = extract_created_spool_id(resp, label_field="label", label_value="55")
    assert result == "SPOOL-ALT-ID"


# ---------------------------------------------------------------------------
# Wizard integration — SpoolMapping gets the spool _id, not the filament _id
# ---------------------------------------------------------------------------


def _fresh_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    seed_defaults(session)
    return session


def _fake_spoolman_client(spools=None, filaments=None) -> AsyncMock:
    client = AsyncMock()
    client.get_spools = AsyncMock(return_value=spools or [])
    client.get_filaments = AsyncMock(return_value=filaments or [])
    client.get_vendors = AsyncMock(return_value=[])
    client.get_field_definitions = AsyncMock(return_value=[])
    client.ensure_extra_fields = AsyncMock(return_value=None)
    client.update_spool = AsyncMock(return_value=MagicMock())
    client.create_spool = AsyncMock(return_value=MagicMock(id=999))
    client.create_filament = AsyncMock(return_value=MagicMock(id=888))
    client.create_vendor = AsyncMock(return_value=MagicMock(id=1))
    client.health = AsyncMock(
        return_value={"version": "1.0", "filament_count": 1, "spool_count": 1, "active_spool_count": 1}
    )
    return client


def _fake_filamentdb_client(filaments=None) -> AsyncMock:
    client = AsyncMock()
    client.get_filaments = AsyncMock(return_value=filaments or [])
    client.get_filament = AsyncMock(return_value=None)
    client.get_version = AsyncMock(return_value="1.33.0")
    client.log_usage = AsyncMock(return_value={})
    client.update_spool = AsyncMock(return_value={})
    client.update_filament = AsyncMock(return_value=MagicMock(id="fil-x"))
    client.create_filament = AsyncMock(return_value=MagicMock(id="new-fil-id"))
    client.get_locations = AsyncMock(return_value=[])
    client.create_location = AsyncMock(return_value={"_id": "loc-1", "name": "Shelf"})
    client.health = AsyncMock(return_value={"filament_count": 1, "spool_count": 1})
    # Default: returns a filament doc (the actual FDB behavior); tests override this.
    client.create_spool = AsyncMock(return_value={"_id": "FILAMENT-ID"})
    return client


def _test_client(db, spoolman, filamentdb) -> TestClient:
    _ROUTERS = (health, sync, conflicts, mappings, config, wizard, sync_log)
    app = FastAPI()
    for mod in _ROUTERS:
        app.include_router(mod.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.state.spoolman = spoolman
    app.state.filamentdb = filamentdb
    return TestClient(app)


def _sm_spool(spool_id: int, remaining: float) -> SpoolmanSpool:
    return SpoolmanSpool(
        id=spool_id,
        filament=SpoolmanFilament(
            id=10, name="PLA", vendor=SpoolmanVendor(id=1, name="ELEGOO")
        ),
        remaining_weight=remaining,
        archived=False,
        extra={},
    )


def _fdb_filament(fid: str) -> FDBFilament:
    return FDBFilament.model_validate({
        "_id": fid,
        "name": "PLA",
        "vendor": "elegoo",
        "spoolWeight": 200.0,
        "spools": [],
    })


def test_wizard_execute_spool_mapping_uses_spool_id_not_filament_id(db):
    """The SpoolMapping.filamentdb_spool_id must be the spool's _id, NOT the filament _id.

    Simulates the actual FDB response: create_spool returns a filament document
    whose top-level _id is the filament id, but the embedded spool has a different _id.
    """
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(
        db,
        "wizard_match_decisions",
        [{"spoolman_filament_id": 10, "action": "link", "filamentdb_id": "FILAMENT-ID-aaa"}],
    )
    db.commit()

    sm_client = _fake_spoolman_client(
        filaments=[SpoolmanFilament(id=10, name="PLA", vendor=SpoolmanVendor(id=1, name="ELEGOO"))],
        spools=[_sm_spool(128, 800.0)],
    )
    fdb_client = _fake_filamentdb_client(
        filaments=[_fdb_filament("FILAMENT-ID-aaa")]
    )
    # Simulate real FDB behavior: returns the filament doc (not just the spool).
    # The spool's _id ("ACTUAL-SPOOL-ID") differs from the filament _id ("FILAMENT-ID-aaa").
    fdb_client.create_spool = AsyncMock(return_value={
        "_id": "FILAMENT-ID-aaa",   # ← filament id (the bug would store this)
        "spools": [
            {"_id": "ACTUAL-SPOOL-ID", "label": "128"},   # ← spool id (correct)
        ],
    })

    client = _test_client(db, sm_client, fdb_client)
    resp = client.post("/api/wizard/execute")
    assert resp.status_code == 200

    sm_map = db.query(SpoolMapping).one()
    # Must be the spool _id, NOT the filament _id
    assert sm_map.filamentdb_spool_id == "ACTUAL-SPOOL-ID", (
        f"Expected 'ACTUAL-SPOOL-ID', got '{sm_map.filamentdb_spool_id}' — "
        "bug: filament id stored as spool id"
    )
    assert sm_map.filamentdb_spool_id != "FILAMENT-ID-aaa"

    # Cross-ref write-back to Spoolman must also use the spool _id
    extra = sm_client.update_spool.await_args.args[1]["extra"]
    assert extra["filamentdb_spool_id"] == json.dumps("ACTUAL-SPOOL-ID"), (
        "Cross-ref extra must contain the spool _id, not the filament _id"
    )
    assert extra["filamentdb_spool_id"] != json.dumps("FILAMENT-ID-aaa")


# ---------------------------------------------------------------------------
# Engine integration — _handle_new_sm_spool stores the spool _id
# ---------------------------------------------------------------------------

def _sm_spool_with_extra(spool_id: int, filament_id: int, extra: dict | None = None):
    fil = SpoolmanFilament(id=filament_id, name="PLA", vendor=SpoolmanVendor(id=1, name="ACME"))
    return SpoolmanSpool(
        id=spool_id,
        filament=fil,
        remaining_weight=500.0,
        archived=False,
        extra=extra or {},
    )


def _fdb_filament_no_spools(fid: str):
    return FDBFilament.model_validate({
        "_id": fid,
        "name": "PLA",
        "spoolWeight": 200.0,
        "spools": [],
    })


def _fake_spoolman_engine(spools=None, filaments=None) -> AsyncMock:
    client = AsyncMock()
    client.get_spools = AsyncMock(return_value=spools or [])
    client.get_filaments = AsyncMock(return_value=filaments or [])
    client.get_field_definitions = AsyncMock(return_value=[])
    client.update_spool = AsyncMock(return_value=MagicMock())
    client.update_filament = AsyncMock(return_value=MagicMock())
    client.create_spool = AsyncMock(return_value=MagicMock(id=999))
    return client


def _fake_filamentdb_engine(filaments=None) -> AsyncMock:
    client = AsyncMock()
    client.get_filaments = AsyncMock(return_value=filaments or [])
    client.get_filament = AsyncMock(return_value=None)
    client.get_version = AsyncMock(return_value="1.33.0")
    client.log_usage = AsyncMock(return_value={})
    client.update_spool = AsyncMock(return_value={})
    client.update_filament = AsyncMock(return_value={})
    client.create_spool = AsyncMock(return_value={"_id": "new-spool-id"})
    return client


@pytest.mark.asyncio
async def test_engine_new_sm_spool_mapping_uses_spool_id_not_filament_id(db):
    """_handle_new_sm_spool must store the spool _id (from inside spools[]),
    NOT the filament _id returned as the top-level _id of the FDB response.
    """
    sm_sp = _sm_spool_with_extra(200, filament_id=20)
    fdb_fil = _fdb_filament_no_spools("FDB-FIL-ID-xyz")
    db.add(FilamentMapping(spoolman_filament_id=20, filamentdb_id="FDB-FIL-ID-xyz"))
    db.flush()
    # Enable auto-import so new spools on mapped filaments create rather than queue.
    from app.models.config import BridgeConfig
    db.merge(BridgeConfig(key="new_spool_policy", value='"auto_import"'))
    db.commit()

    spoolman = _fake_spoolman_engine(spools=[sm_sp])
    fdb_client = _fake_filamentdb_engine(filaments=[fdb_fil])
    # Simulate real FDB behavior: create_spool returns the filament doc.
    fdb_client.create_spool = AsyncMock(return_value={
        "_id": "FDB-FIL-ID-xyz",          # filament _id (the bug stored this)
        "spools": [
            {"_id": "FDB-SPOOL-ID-abc", "label": "200"},  # spool _id (correct)
        ],
    })

    with patch("app.core.engine._settings") as mock_settings:
        mock_settings.filamentdb_spoolman_id_field = "label"
        mock_settings.spoolman_field_filamentdb_id = "filamentdb_id"
        mock_settings.spoolman_field_filamentdb_spool_id = "filamentdb_spool_id"
        mock_settings.spoolman_field_filamentdb_parent_id = "filamentdb_parent_id"
        mock_settings.parsed_field_mappings = {}
        mock_settings.parsed_field_mapping_excludes = set()
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="test-engine-fix")

    fdb_client.create_spool.assert_called_once()
    assert result.errors == 0

    sm_map = db.query(SpoolMapping).one()
    assert sm_map.filamentdb_spool_id == "FDB-SPOOL-ID-abc", (
        f"Expected 'FDB-SPOOL-ID-abc', got '{sm_map.filamentdb_spool_id}' — "
        "bug: filament id stored as spool id in engine"
    )
    assert sm_map.filamentdb_spool_id != "FDB-FIL-ID-xyz"

    # Cross-ref write-back must also carry the spool _id
    sm_update_call = spoolman.update_spool.await_args
    spool_extra = sm_update_call.args[1]["extra"]
    fdb_spool_xref = spool_extra.get("filamentdb_spool_id")
    assert fdb_spool_xref == json.dumps("FDB-SPOOL-ID-abc"), (
        f"Cross-ref extra filamentdb_spool_id must be spool id, got {fdb_spool_xref!r}"
    )
