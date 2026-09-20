"""Integration tests for ``_sync_opentag_identity`` — the bidirectional,
baselined reconciliation of the OpenPrintTag identity (``openprinttag_slug`` /
``openprinttag_uuid``) between a Spoolman filament's extra fields and a Filament
DB filament's ``settings{}`` bag.

Covers:
  - FDB→SM fill: FDB has an identity, Spoolman doesn't → SM extras written (the
    new leg, closes #81)
  - SM→FDB push (regression): Spoolman has an identity, FDB doesn't →
    merge_filament_settings called (unchanged one-way behavior)
  - In sync: both sides carry the same uuid → neither write called
  - Divergence → conflict: both set, different uuid, policy=manual → a Conflict
    row is queued (deduped on a second cycle), no overwrite
  - Direction gating: one-way directions suppress the opposite leg's fill
  - Dry-run: no writes, a preview row is produced instead
  - Deliberate-unlink propagation (#89): a baselined side that goes empty is
    read as a clear (not a hole to fill) and propagated to the other side,
    with anti-ping-pong and direction-gating coverage for the new legs.

Mirrors test_engine_opentag_fields.py.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.engine import run_sync_cycle
from app.core.fields import OPENTAG_EXTRA_FIELDS
from app.models.config import BridgeConfig
from app.models.conflict import Conflict
from app.models.mapping import FilamentMapping
from app.models.snapshot import Snapshot
from app.schemas.filamentdb import FDBFilament, FDBFilamentDetail
from app.schemas.spoolman import SpoolmanFilament, SpoolmanVendor, encode_extra_value

CYCLE_ID = "opt-identity-test-cycle"
OI_SM_FIL_ID = 90
OI_FDB_FIL_ID = "fil-opt-identity"

SLUG_FIELD = "openprinttag_slug"
UUID_FIELD = "openprinttag_uuid"


def _sm_fil(extra: dict | None = None) -> SpoolmanFilament:
    return SpoolmanFilament(
        id=OI_SM_FIL_ID,
        name="OPT Identity PLA",
        vendor=SpoolmanVendor(id=1, name="ELEGOO"),
        material="PLA",
        extra=extra or {},
    )


def _fdb_list() -> FDBFilament:
    return FDBFilament.model_validate({
        "_id": OI_FDB_FIL_ID, "name": "OPT Identity PLA", "type": "PLA", "spools": [],
    })


def _fdb_detail(*, settings: dict | None = None, parent_id: str | None = None) -> FDBFilamentDetail:
    return FDBFilamentDetail.model_validate({
        "_id": OI_FDB_FIL_ID,
        "name": "OPT Identity PLA",
        "type": "PLA",
        "settings": settings,
        "parentId": parent_id,
        "spools": [],
    })


def _add_fil_mapping(db) -> None:
    db.add(FilamentMapping(
        spoolman_filament_id=OI_SM_FIL_ID, filamentdb_id=OI_FDB_FIL_ID
    ))
    db.flush()


def _seed_identity_baseline(db, *, sm_uuid: str | None, fdb_uuid: str | None) -> None:
    """Seed the ``_opt_uuid`` baseline on both filament snapshot rows, as if a
    prior cycle had already observed these values — used to set up the
    "had a value" precondition for the deliberate-clear tests without having
    to run an extra sync cycle first."""
    db.add(Snapshot(
        source="spoolman", entity_type="filament", entity_id=str(OI_SM_FIL_ID),
        data=json.dumps({"_opt_uuid": sm_uuid or "", "_opt_slug": ""}),
    ))
    db.add(Snapshot(
        source="filamentdb", entity_type="filament", entity_id=OI_FDB_FIL_ID,
        data=json.dumps({"_opt_uuid": fdb_uuid or "", "_opt_slug": ""}),
    ))
    db.flush()


def _get_identity_baseline(db, source: str, entity_id: str) -> dict:
    row = (
        db.query(Snapshot)
        .filter_by(source=source, entity_type="filament", entity_id=entity_id)
        .first()
    )
    return json.loads(row.data) if row else {}


def _identity_settings(mock_settings) -> None:
    """Minimal _settings attrs for an identity-only cycle (real key strings)."""
    mock_settings.filamentdb_spoolman_id_field = "label"
    mock_settings.spoolman_field_filamentdb_id = "filamentdb_id"
    mock_settings.spoolman_field_filamentdb_spool_id = "filamentdb_spool_id"
    mock_settings.spoolman_field_filamentdb_parent_id = "filamentdb_parent_id"
    mock_settings.parsed_field_mappings = {}
    mock_settings.parsed_field_mapping_excludes = set()
    mock_settings.spoolman_field_openprinttag_slug = SLUG_FIELD
    mock_settings.spoolman_field_openprinttag_uuid = UUID_FIELD
    # Real key strings for the seven OPT material extras too, so the sibling
    # material-fields pass doesn't choke on MagicMock dict keys.
    for ef in OPENTAG_EXTRA_FIELDS:
        setattr(mock_settings, ef.config_attr, ef.default_key)


def _seed_matprop(db, direction: str, policy: str = "manual") -> None:
    db.merge(BridgeConfig(key="material_properties_sync_direction", value=json.dumps(direction)))
    db.merge(BridgeConfig(key="material_properties_conflict_policy", value=json.dumps(policy)))
    db.commit()


def _fake_spoolman(filaments=None) -> AsyncMock:
    client = AsyncMock()
    client.get_spools = AsyncMock(return_value=[])
    client.get_filaments = AsyncMock(return_value=filaments or [])
    client.get_field_definitions = AsyncMock(return_value=[])
    client.update_spool = AsyncMock(return_value=MagicMock())
    client.update_filament = AsyncMock(return_value=MagicMock())
    return client


def _fake_fdb(filaments=None, detail=None, version="1.33.0") -> AsyncMock:
    client = AsyncMock()
    client.get_filaments = AsyncMock(return_value=filaments or [])
    client.get_filament = AsyncMock(return_value=detail)
    client.get_version = AsyncMock(return_value=version)
    client.update_filament = AsyncMock(return_value={})
    client.merge_filament_settings = AsyncMock(return_value=None)
    client.remove_filament_settings_keys = AsyncMock(return_value=True)
    return client


@pytest.mark.asyncio
async def test_identity_fdb_to_sm_fill(db):
    """FDB settings.openprinttag_uuid+slug set, SM extras empty → SM extras written."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="two_way", policy="manual")

    sm_fil = _sm_fil(extra={})
    fdb_detail = _fdb_detail(settings={
        "openprinttag_slug": "elegoo-pla-beige", "openprinttag_uuid": "uuid-123",
    })

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    spoolman.update_filament.assert_any_call(
        OI_SM_FIL_ID,
        {"extra": {
            SLUG_FIELD: encode_extra_value("elegoo-pla-beige"),
            UUID_FIELD: encode_extra_value("uuid-123"),
        }},
    )
    fdb_client.merge_filament_settings.assert_not_called()
    assert result.updated >= 1
    assert result.conflicts == 0


@pytest.mark.asyncio
async def test_identity_sm_to_fdb_push_regression(db):
    """SM extras set, FDB settings empty → merge_filament_settings called (unchanged)."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="two_way", policy="manual")

    sm_fil = _sm_fil(extra={
        SLUG_FIELD: encode_extra_value("elegoo-pla-beige"),
        UUID_FIELD: encode_extra_value("uuid-123"),
    })
    fdb_detail = _fdb_detail(settings=None)

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    fdb_client.merge_filament_settings.assert_any_call(
        OI_FDB_FIL_ID,
        {"openprinttag_slug": "elegoo-pla-beige", "openprinttag_uuid": "uuid-123"},
    )
    spoolman.update_filament.assert_not_called()
    assert result.updated >= 1
    assert result.conflicts == 0


@pytest.mark.asyncio
async def test_identity_in_sync_no_writes(db):
    """Both sides carry the same uuid → neither write called."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="two_way", policy="manual")

    sm_fil = _sm_fil(extra={
        SLUG_FIELD: encode_extra_value("elegoo-pla-beige"),
        UUID_FIELD: encode_extra_value("uuid-123"),
    })
    fdb_detail = _fdb_detail(settings={
        "openprinttag_slug": "elegoo-pla-beige", "openprinttag_uuid": "uuid-123",
    })

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    spoolman.update_filament.assert_not_called()
    fdb_client.merge_filament_settings.assert_not_called()
    assert result.conflicts == 0


@pytest.mark.asyncio
async def test_identity_divergence_queues_conflict_deduped(db):
    """Both set, different uuid, policy=manual → a Conflict is queued, no overwrite.

    A second cycle with the same divergence does NOT duplicate the conflict.
    """
    _add_fil_mapping(db)
    _seed_matprop(db, direction="two_way", policy="manual")

    sm_fil = _sm_fil(extra={
        SLUG_FIELD: encode_extra_value("elegoo-pla-beige"),
        UUID_FIELD: encode_extra_value("uuid-sm"),
    })
    fdb_detail = _fdb_detail(settings={
        "openprinttag_slug": "elegoo-pla-beige-v2", "openprinttag_uuid": "uuid-fdb",
    })

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    spoolman.update_filament.assert_not_called()
    fdb_client.merge_filament_settings.assert_not_called()
    assert result.conflicts >= 1
    conflict = db.query(Conflict).filter_by(field_name="OpenPrintTag identity").first()
    assert conflict is not None
    assert conflict.conflict_type == "cross_system"

    # Second cycle: same divergence — must NOT duplicate the conflict.
    spoolman2 = _fake_spoolman(filaments=[sm_fil])
    fdb_client2 = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)
    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        r2 = await run_sync_cycle(db, spoolman2, fdb_client2, dry_run=False, cycle_id=CYCLE_ID + "-2")

    assert r2.conflicts == 0
    conflicts = db.query(Conflict).filter_by(field_name="OpenPrintTag identity").all()
    assert len(conflicts) == 1


@pytest.mark.asyncio
async def test_identity_direction_gating_sm_to_fdb_only_suppresses_fdb_to_sm_fill(db):
    """direction=spoolman_to_filamentdb → the FDB→SM fill is NOT performed."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="spoolman_to_filamentdb", policy="manual")

    sm_fil = _sm_fil(extra={})
    fdb_detail = _fdb_detail(settings={
        "openprinttag_slug": "elegoo-pla-beige", "openprinttag_uuid": "uuid-123",
    })

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    spoolman.update_filament.assert_not_called()


@pytest.mark.asyncio
async def test_identity_direction_gating_fdb_to_sm_only_suppresses_sm_to_fdb_push(db):
    """direction=filamentdb_to_spoolman → the SM→FDB push is NOT performed."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="filamentdb_to_spoolman", policy="manual")

    sm_fil = _sm_fil(extra={
        SLUG_FIELD: encode_extra_value("elegoo-pla-beige"),
        UUID_FIELD: encode_extra_value("uuid-123"),
    })
    fdb_detail = _fdb_detail(settings=None)

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    fdb_client.merge_filament_settings.assert_not_called()


@pytest.mark.asyncio
async def test_identity_dry_run_fdb_to_sm_fill_no_write_preview_row(db):
    """FDB→SM fill case with dry_run=True → no update_filament write, a preview row present."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="two_way", policy="manual")

    sm_fil = _sm_fil(extra={})
    fdb_detail = _fdb_detail(settings={
        "openprinttag_slug": "elegoo-pla-beige", "openprinttag_uuid": "uuid-123",
    })

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=True, cycle_id=CYCLE_ID)

    spoolman.update_filament.assert_not_called()
    fdb_client.merge_filament_settings.assert_not_called()
    assert result.updated >= 1
    rows = [p for p in result.preview if p.get("field") == "OpenPrintTag identity"]
    assert len(rows) == 1
    assert rows[0]["action"] == "update"
    assert rows[0]["direction"] == "filamentdb_to_spoolman"
    assert rows[0]["new"] == "uuid-123"

    # No Conflict row should have been created either (dry-run never queues).
    assert db.query(Conflict).filter_by(field_name="OpenPrintTag identity").first() is None


# ---------------------------------------------------------------------------
# #89 — deliberate-unlink propagation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_identity_fdb_unlink_propagates_to_sm(db):
    """Baseline had a uuid on both sides; FDB now empty, SM still set →
    SM extras are blanked (propagated), FDB is NOT refilled from SM."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="two_way", policy="manual")
    _seed_identity_baseline(db, sm_uuid="uuid-123", fdb_uuid="uuid-123")

    sm_fil = _sm_fil(extra={
        SLUG_FIELD: encode_extra_value("elegoo-pla-beige"),
        UUID_FIELD: encode_extra_value("uuid-123"),
    })
    fdb_detail = _fdb_detail(settings=None)  # link removed in FDB

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    spoolman.update_filament.assert_any_call(
        OI_SM_FIL_ID,
        {"extra": {SLUG_FIELD: encode_extra_value(""), UUID_FIELD: encode_extra_value("")}},
    )
    fdb_client.merge_filament_settings.assert_not_called()
    assert result.updated >= 1
    assert result.conflicts == 0

    sm_baseline = _get_identity_baseline(db, "spoolman", str(OI_SM_FIL_ID))
    fdb_baseline = _get_identity_baseline(db, "filamentdb", OI_FDB_FIL_ID)
    assert sm_baseline["_opt_uuid"] == ""
    assert fdb_baseline["_opt_uuid"] == ""


@pytest.mark.asyncio
async def test_identity_sm_unlink_propagates_to_fdb(db):
    """Baseline had a uuid on both sides; SM now empty, FDB still set →
    FDB's identity keys are removed via remove_filament_settings_keys, SM is
    NOT refilled from FDB."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="two_way", policy="manual")
    _seed_identity_baseline(db, sm_uuid="uuid-123", fdb_uuid="uuid-123")

    sm_fil = _sm_fil(extra={
        SLUG_FIELD: encode_extra_value(""), UUID_FIELD: encode_extra_value(""),
    })  # link removed in Spoolman (bridge blanks rather than deletes keys)
    fdb_detail = _fdb_detail(settings={
        "openprinttag_slug": "elegoo-pla-beige", "openprinttag_uuid": "uuid-123",
    })

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    fdb_client.remove_filament_settings_keys.assert_any_call(
        OI_FDB_FIL_ID, ["openprinttag_slug", "openprinttag_uuid"],
    )
    fdb_client.merge_filament_settings.assert_not_called()
    spoolman.update_filament.assert_not_called()
    assert result.updated >= 1
    assert result.conflicts == 0

    sm_baseline = _get_identity_baseline(db, "spoolman", str(OI_SM_FIL_ID))
    fdb_baseline = _get_identity_baseline(db, "filamentdb", OI_FDB_FIL_ID)
    assert sm_baseline["_opt_uuid"] == ""
    assert fdb_baseline["_opt_uuid"] == ""


@pytest.mark.asyncio
async def test_identity_never_linked_regression_guard(db):
    """#81 regression guard: a side with NO baseline (never linked) still
    fills from the other side, even after a prior no-op cycle where both
    sides were empty."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="two_way", policy="manual")

    sm_fil_empty = _sm_fil(extra={})
    fdb_detail_empty = _fdb_detail(settings=None)
    spoolman1 = _fake_spoolman(filaments=[sm_fil_empty])
    fdb_client1 = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail_empty)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        await run_sync_cycle(db, spoolman1, fdb_client1, dry_run=False, cycle_id=CYCLE_ID)

    # Neither side has ever held an identity — no _opt_uuid baseline should
    # have been recorded (nothing to converge). Other passes sharing this
    # same filament-level snapshot row (e.g. material fields) may still
    # write their own keys, so check for absence of the key, not an empty row.
    assert "_opt_uuid" not in _get_identity_baseline(db, "spoolman", str(OI_SM_FIL_ID))
    assert "_opt_uuid" not in _get_identity_baseline(db, "filamentdb", OI_FDB_FIL_ID)

    # Now FDB gets linked for the first time — SM has still never had one.
    sm_fil = _sm_fil(extra={})
    fdb_detail = _fdb_detail(settings={
        "openprinttag_slug": "elegoo-pla-beige", "openprinttag_uuid": "uuid-123",
    })
    spoolman2 = _fake_spoolman(filaments=[sm_fil])
    fdb_client2 = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        result = await run_sync_cycle(db, spoolman2, fdb_client2, dry_run=False, cycle_id=CYCLE_ID + "-2")

    spoolman2.update_filament.assert_any_call(
        OI_SM_FIL_ID,
        {"extra": {
            SLUG_FIELD: encode_extra_value("elegoo-pla-beige"),
            UUID_FIELD: encode_extra_value("uuid-123"),
        }},
    )
    assert result.updated >= 1


@pytest.mark.asyncio
async def test_identity_clear_second_cycle_no_ping_pong(db):
    """After a clear propagates, a second cycle with both sides now empty
    performs no further writes (anti-ping-pong)."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="two_way", policy="manual")
    _seed_identity_baseline(db, sm_uuid="uuid-123", fdb_uuid="uuid-123")

    sm_fil = _sm_fil(extra={
        SLUG_FIELD: encode_extra_value("elegoo-pla-beige"),
        UUID_FIELD: encode_extra_value("uuid-123"),
    })
    fdb_detail = _fdb_detail(settings=None)
    spoolman1 = _fake_spoolman(filaments=[sm_fil])
    fdb_client1 = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        await run_sync_cycle(db, spoolman1, fdb_client1, dry_run=False, cycle_id=CYCLE_ID)

    spoolman1.update_filament.assert_any_call(
        OI_SM_FIL_ID,
        {"extra": {SLUG_FIELD: encode_extra_value(""), UUID_FIELD: encode_extra_value("")}},
    )

    # Second cycle: SM now genuinely reflects the blanked extras, FDB stays
    # empty too — both sides converged. No further writes should occur.
    sm_fil_cleared = _sm_fil(extra={
        SLUG_FIELD: encode_extra_value(""), UUID_FIELD: encode_extra_value(""),
    })
    spoolman2 = _fake_spoolman(filaments=[sm_fil_cleared])
    fdb_client2 = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        result2 = await run_sync_cycle(db, spoolman2, fdb_client2, dry_run=False, cycle_id=CYCLE_ID + "-2")

    spoolman2.update_filament.assert_not_called()
    fdb_client2.merge_filament_settings.assert_not_called()
    fdb_client2.remove_filament_settings_keys.assert_not_called()
    assert result2.conflicts == 0


@pytest.mark.asyncio
async def test_identity_direction_gating_blocks_fdb_clear_propagation(db):
    """direction=spoolman_to_filamentdb → an FDB-side clear is NOT propagated
    to Spoolman (allow_fdb_to_sm is False)."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="spoolman_to_filamentdb", policy="manual")
    _seed_identity_baseline(db, sm_uuid="uuid-123", fdb_uuid="uuid-123")

    sm_fil = _sm_fil(extra={
        SLUG_FIELD: encode_extra_value("elegoo-pla-beige"),
        UUID_FIELD: encode_extra_value("uuid-123"),
    })
    fdb_detail = _fdb_detail(settings=None)  # cleared in FDB

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    spoolman.update_filament.assert_not_called()


@pytest.mark.asyncio
async def test_identity_direction_gating_blocks_sm_clear_propagation(db):
    """direction=filamentdb_to_spoolman → an SM-side clear is NOT propagated
    to Filament DB (allow_sm_to_fdb is False)."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="filamentdb_to_spoolman", policy="manual")
    _seed_identity_baseline(db, sm_uuid="uuid-123", fdb_uuid="uuid-123")

    sm_fil = _sm_fil(extra={
        SLUG_FIELD: encode_extra_value(""), UUID_FIELD: encode_extra_value(""),
    })  # cleared in Spoolman
    fdb_detail = _fdb_detail(settings={
        "openprinttag_slug": "elegoo-pla-beige", "openprinttag_uuid": "uuid-123",
    })

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    fdb_client.remove_filament_settings_keys.assert_not_called()


@pytest.mark.asyncio
async def test_identity_clear_dry_run_preview_no_writes(db):
    """A deliberate clear under dry_run=True produces a preview row and
    performs no writes and no baseline mutation."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="two_way", policy="manual")
    _seed_identity_baseline(db, sm_uuid="uuid-123", fdb_uuid="uuid-123")

    sm_fil = _sm_fil(extra={
        SLUG_FIELD: encode_extra_value("elegoo-pla-beige"),
        UUID_FIELD: encode_extra_value("uuid-123"),
    })
    fdb_detail = _fdb_detail(settings=None)  # cleared in FDB

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=True, cycle_id=CYCLE_ID)

    spoolman.update_filament.assert_not_called()
    fdb_client.merge_filament_settings.assert_not_called()
    fdb_client.remove_filament_settings_keys.assert_not_called()
    rows = [p for p in result.preview if p.get("field") == "OpenPrintTag identity"]
    assert len(rows) == 1
    assert rows[0]["action"] == "update"
    assert rows[0]["direction"] == "filamentdb_to_spoolman"
    assert rows[0]["new"] is None

    # Baseline must be untouched by the dry run.
    sm_baseline = _get_identity_baseline(db, "spoolman", str(OI_SM_FIL_ID))
    assert sm_baseline["_opt_uuid"] == "uuid-123"


@pytest.mark.asyncio
async def test_identity_divergence_after_baseline_still_conflicts_not_fills(db):
    """A genuine divergence (both sides currently set, different values) is
    still routed to conflict — never misread as a one-sided clear-to-fill —
    even when both sides already carry a baseline."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="two_way", policy="manual")
    _seed_identity_baseline(db, sm_uuid="uuid-123", fdb_uuid="uuid-123")

    sm_fil = _sm_fil(extra={
        SLUG_FIELD: encode_extra_value("elegoo-pla-beige"),
        UUID_FIELD: encode_extra_value("uuid-sm-changed"),
    })
    fdb_detail = _fdb_detail(settings={
        "openprinttag_slug": "elegoo-pla-beige", "openprinttag_uuid": "uuid-123",
    })

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    spoolman.update_filament.assert_not_called()
    fdb_client.merge_filament_settings.assert_not_called()
    fdb_client.remove_filament_settings_keys.assert_not_called()
    assert result.conflicts >= 1


# ---------------------------------------------------------------------------
# #93 — clear-plus-relink race: a clear on one side must not beat a
# simultaneous re-link on the other.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_identity_fdb_cleared_sm_relinked_queues_conflict_not_propagate(db):
    """FDB unlinked AND Spoolman re-linked to a NEW uuid in the same interval
    -> two opposing actions, not a clear to propagate (#93): a cross_system
    conflict is queued instead, nothing is blanked, and neither baseline
    moves (so the pair stays on the conflict path until a human resolves it
    via #94)."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="two_way", policy="manual")
    _seed_identity_baseline(db, sm_uuid="uuid-123", fdb_uuid="uuid-123")

    sm_fil = _sm_fil(extra={
        SLUG_FIELD: encode_extra_value("elegoo-pla-new"),
        UUID_FIELD: encode_extra_value("uuid-NEW"),
    })
    fdb_detail = _fdb_detail(settings=None)  # link removed in FDB

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    spoolman.update_filament.assert_not_called()
    fdb_client.merge_filament_settings.assert_not_called()
    fdb_client.remove_filament_settings_keys.assert_not_called()
    assert result.conflicts >= 1

    conflict = db.query(Conflict).filter_by(field_name="OpenPrintTag identity").first()
    assert conflict is not None
    assert conflict.conflict_type == "cross_system"
    assert conflict.resolved_at is None

    sm_baseline = _get_identity_baseline(db, "spoolman", str(OI_SM_FIL_ID))
    fdb_baseline = _get_identity_baseline(db, "filamentdb", OI_FDB_FIL_ID)
    assert sm_baseline["_opt_uuid"] == "uuid-123"
    assert fdb_baseline["_opt_uuid"] == "uuid-123"


@pytest.mark.asyncio
async def test_identity_sm_cleared_fdb_relinked_queues_conflict_not_propagate(db):
    """Mirror: Spoolman unlinked AND Filament DB re-linked to a NEW uuid ->
    conflict queued, nothing removed from FDB's settings{} bag, neither
    baseline moves."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="two_way", policy="manual")
    _seed_identity_baseline(db, sm_uuid="uuid-123", fdb_uuid="uuid-123")

    sm_fil = _sm_fil(extra={
        SLUG_FIELD: encode_extra_value(""), UUID_FIELD: encode_extra_value(""),
    })  # cleared in Spoolman
    fdb_detail = _fdb_detail(settings={
        "openprinttag_slug": "elegoo-pla-new", "openprinttag_uuid": "uuid-NEW-fdb",
    })  # re-linked in FDB

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    spoolman.update_filament.assert_not_called()
    fdb_client.merge_filament_settings.assert_not_called()
    fdb_client.remove_filament_settings_keys.assert_not_called()
    assert result.conflicts >= 1

    conflict = db.query(Conflict).filter_by(field_name="OpenPrintTag identity").first()
    assert conflict is not None
    assert conflict.conflict_type == "cross_system"
    assert conflict.resolved_at is None

    sm_baseline = _get_identity_baseline(db, "spoolman", str(OI_SM_FIL_ID))
    fdb_baseline = _get_identity_baseline(db, "filamentdb", OI_FDB_FIL_ID)
    assert sm_baseline["_opt_uuid"] == "uuid-123"
    assert fdb_baseline["_opt_uuid"] == "uuid-123"


@pytest.mark.asyncio
async def test_identity_clear_relink_race_stable_across_cycles(db):
    """The clear-plus-relink race stays deduped on a second cycle: still
    exactly one conflict, still no writes, baselines still unmoved."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="two_way", policy="manual")
    _seed_identity_baseline(db, sm_uuid="uuid-123", fdb_uuid="uuid-123")

    sm_fil = _sm_fil(extra={
        SLUG_FIELD: encode_extra_value("elegoo-pla-new"),
        UUID_FIELD: encode_extra_value("uuid-NEW"),
    })
    fdb_detail = _fdb_detail(settings=None)

    spoolman1 = _fake_spoolman(filaments=[sm_fil])
    fdb_client1 = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)
    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        r1 = await run_sync_cycle(db, spoolman1, fdb_client1, dry_run=False, cycle_id=CYCLE_ID)
    assert r1.conflicts >= 1

    spoolman2 = _fake_spoolman(filaments=[sm_fil])
    fdb_client2 = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)
    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        r2 = await run_sync_cycle(db, spoolman2, fdb_client2, dry_run=False, cycle_id=CYCLE_ID + "-2")

    assert r2.conflicts == 0  # deduped, not a fresh row
    spoolman2.update_filament.assert_not_called()
    fdb_client2.merge_filament_settings.assert_not_called()
    fdb_client2.remove_filament_settings_keys.assert_not_called()

    conflicts = db.query(Conflict).filter_by(field_name="OpenPrintTag identity").all()
    assert len(conflicts) == 1

    sm_baseline = _get_identity_baseline(db, "spoolman", str(OI_SM_FIL_ID))
    fdb_baseline = _get_identity_baseline(db, "filamentdb", OI_FDB_FIL_ID)
    assert sm_baseline["_opt_uuid"] == "uuid-123"
    assert fdb_baseline["_opt_uuid"] == "uuid-123"


# ---------------------------------------------------------------------------
# #91 — a converged identity conflict is auto-resolved instead of lingering
# and blocking future ones.
# ---------------------------------------------------------------------------


def _seed_open_identity_conflict(db, *, sm_value: str | None, fdb_value: str | None) -> int:
    conflict = Conflict(
        entity_type="filament", spoolman_id=OI_SM_FIL_ID, filamentdb_filament_id=OI_FDB_FIL_ID,
        field_name="OpenPrintTag identity",
        spoolman_value=json.dumps(sm_value) if sm_value is not None else None,
        filamentdb_value=json.dumps(fdb_value) if fdb_value is not None else None,
        conflict_type="cross_system",
    )
    db.add(conflict)
    db.commit()
    return conflict.id


@pytest.mark.asyncio
async def test_identity_auto_resolve_converged_both_equal(db):
    """An open conflict for this pair is auto-resolved once the pass observes
    both sides currently equal (#91)."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="two_way", policy="manual")
    _seed_identity_baseline(db, sm_uuid="uuid-A", fdb_uuid="uuid-B")
    conflict_id = _seed_open_identity_conflict(db, sm_value="uuid-A", fdb_value="uuid-B")

    sm_fil = _sm_fil(extra={
        SLUG_FIELD: encode_extra_value("elegoo-pla-beige"),
        UUID_FIELD: encode_extra_value("uuid-123"),
    })
    fdb_detail = _fdb_detail(settings={
        "openprinttag_slug": "elegoo-pla-beige", "openprinttag_uuid": "uuid-123",
    })

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    resolved = db.query(Conflict).filter_by(id=conflict_id).one()
    assert resolved.resolved_at is not None
    assert resolved.resolution == "auto_resolved_converged"
    assert json.loads(resolved.resolved_value) == "uuid-123"


@pytest.mark.asyncio
async def test_identity_auto_resolve_converged_after_clear_propagates_to_empty(db):
    """An open conflict for this pair is auto-resolved the moment a
    propagated clear converges both sides to empty (#91)."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="two_way", policy="manual")
    _seed_identity_baseline(db, sm_uuid="uuid-123", fdb_uuid="uuid-123")
    conflict_id = _seed_open_identity_conflict(db, sm_value="uuid-A", fdb_value="uuid-B")

    sm_fil = _sm_fil(extra={
        SLUG_FIELD: encode_extra_value("elegoo-pla-beige"),
        UUID_FIELD: encode_extra_value("uuid-123"),
    })
    fdb_detail = _fdb_detail(settings=None)  # cleared in FDB, SM unchanged from baseline

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    spoolman.update_filament.assert_any_call(
        OI_SM_FIL_ID,
        {"extra": {SLUG_FIELD: encode_extra_value(""), UUID_FIELD: encode_extra_value("")}},
    )

    resolved = db.query(Conflict).filter_by(id=conflict_id).one()
    assert resolved.resolved_at is not None
    assert resolved.resolution == "auto_resolved_converged"


@pytest.mark.asyncio
async def test_identity_still_diverging_conflict_not_auto_resolved(db):
    """A pair that is STILL diverging must not have its open conflict closed
    — #91 never picks a winner for a real divergence."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="two_way", policy="manual")
    _seed_identity_baseline(db, sm_uuid="uuid-123", fdb_uuid="uuid-123")
    conflict_id = _seed_open_identity_conflict(db, sm_value="uuid-123", fdb_value="uuid-123")

    sm_fil = _sm_fil(extra={
        SLUG_FIELD: encode_extra_value("elegoo-pla-a"),
        UUID_FIELD: encode_extra_value("uuid-A"),
    })
    fdb_detail = _fdb_detail(settings={
        "openprinttag_slug": "elegoo-pla-b", "openprinttag_uuid": "uuid-B",
    })

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    still_open = db.query(Conflict).filter_by(id=conflict_id).one()
    assert still_open.resolved_at is None
    assert still_open.resolution is None


@pytest.mark.asyncio
async def test_identity_auto_resolve_dry_run_no_resolution(db):
    """Dry run never mutates the DB — an open conflict is left untouched even
    when the pass would observe convergence (#91)."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="two_way", policy="manual")
    _seed_identity_baseline(db, sm_uuid="uuid-A", fdb_uuid="uuid-B")
    conflict_id = _seed_open_identity_conflict(db, sm_value="uuid-A", fdb_value="uuid-B")

    sm_fil = _sm_fil(extra={
        SLUG_FIELD: encode_extra_value("elegoo-pla-beige"),
        UUID_FIELD: encode_extra_value("uuid-123"),
    })
    fdb_detail = _fdb_detail(settings={
        "openprinttag_slug": "elegoo-pla-beige", "openprinttag_uuid": "uuid-123",
    })

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=True, cycle_id=CYCLE_ID)

    still_open = db.query(Conflict).filter_by(id=conflict_id).one()
    assert still_open.resolved_at is None


@pytest.mark.asyncio
async def test_identity_new_divergence_after_auto_resolve_queues_fresh_conflict(db):
    """Once a converged conflict is auto-resolved, a NEW divergence on the
    same pair is free to queue again — proving the ``_has_open_conflict``
    dedup is no longer permanently blocked by the stale row (#91)."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="two_way", policy="manual")
    _seed_identity_baseline(db, sm_uuid="uuid-A", fdb_uuid="uuid-B")
    conflict_id = _seed_open_identity_conflict(db, sm_value="uuid-A", fdb_value="uuid-B")

    # Cycle 1: both sides now agree -> auto-resolve the stale conflict.
    sm_fil = _sm_fil(extra={
        SLUG_FIELD: encode_extra_value("elegoo-pla-beige"),
        UUID_FIELD: encode_extra_value("uuid-123"),
    })
    fdb_detail = _fdb_detail(settings={
        "openprinttag_slug": "elegoo-pla-beige", "openprinttag_uuid": "uuid-123",
    })
    spoolman1 = _fake_spoolman(filaments=[sm_fil])
    fdb_client1 = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)
    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        await run_sync_cycle(db, spoolman1, fdb_client1, dry_run=False, cycle_id=CYCLE_ID)

    resolved = db.query(Conflict).filter_by(id=conflict_id).one()
    assert resolved.resolved_at is not None

    # Cycle 2: a brand-new divergence on the same pair.
    sm_fil2 = _sm_fil(extra={
        SLUG_FIELD: encode_extra_value("elegoo-pla-new"),
        UUID_FIELD: encode_extra_value("uuid-NEW"),
    })
    fdb_detail2 = _fdb_detail(settings={
        "openprinttag_slug": "elegoo-pla-other", "openprinttag_uuid": "uuid-OTHER",
    })
    spoolman2 = _fake_spoolman(filaments=[sm_fil2])
    fdb_client2 = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail2)
    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        r2 = await run_sync_cycle(db, spoolman2, fdb_client2, dry_run=False, cycle_id=CYCLE_ID + "-2")

    assert r2.conflicts >= 1
    open_conflicts = (
        db.query(Conflict)
        .filter_by(field_name="OpenPrintTag identity", resolved_at=None)
        .all()
    )
    assert len(open_conflicts) == 1
    assert open_conflicts[0].id != conflict_id


@pytest.mark.asyncio
async def test_identity_clear_relink_race_policy_winner_empty_still_applies(db):
    """Clear-plus-relink race (#93) under a NON-manual policy whose winner is
    the CLEARED side: the winner's decision is "no link", so the clear must
    still propagate.

    ``_resolve_divergence``'s PUSH_* legs call ``_push_*``, which build their
    payload from the winning side's values and no-op on an empty one — so
    without routing an empty winner to the matching ``_clear_*`` helper the
    race would silently do nothing at all, forever, with no conflict and no
    log row. The mirror leg is covered by the test below.
    """
    _add_fil_mapping(db)
    _seed_matprop(db, direction="two_way", policy="filamentdb_wins")
    _seed_identity_baseline(db, sm_uuid="uuid-123", fdb_uuid="uuid-123")

    sm_fil = _sm_fil(extra={
        SLUG_FIELD: encode_extra_value("elegoo-pla-new"),
        UUID_FIELD: encode_extra_value("uuid-NEW"),
    })
    fdb_detail = _fdb_detail(settings=None)  # link removed in FDB — FDB wins

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    # FDB won and FDB is empty -> the Spoolman extras are blanked.
    spoolman.update_filament.assert_called_once()
    _, payload = spoolman.update_filament.call_args[0]
    assert payload["extra"][UUID_FIELD] == encode_extra_value("")
    assert payload["extra"][SLUG_FIELD] == encode_extra_value("")

    sm_baseline = _get_identity_baseline(db, "spoolman", str(OI_SM_FIL_ID))
    assert sm_baseline["_opt_uuid"] == ""


@pytest.mark.asyncio
async def test_identity_clear_relink_race_policy_winner_empty_mirror(db):
    """Mirror of the above: Spoolman cleared, FDB re-linked, ``spoolman_wins``
    -> the empty Spoolman side wins, so the two OpenTag keys are removed from
    FDB's settings{} bag via the scoped helper rather than silently no-oping."""
    _add_fil_mapping(db)
    _seed_matprop(db, direction="two_way", policy="spoolman_wins")
    _seed_identity_baseline(db, sm_uuid="uuid-123", fdb_uuid="uuid-123")

    sm_fil = _sm_fil(extra={})  # link removed in Spoolman — Spoolman wins
    fdb_detail = _fdb_detail(settings={
        "openprinttag_slug": "elegoo-pla-new",
        "openprinttag_uuid": "uuid-NEW",
    })

    spoolman = _fake_spoolman(filaments=[sm_fil])
    fdb_client = _fake_fdb(filaments=[_fdb_list()], detail=fdb_detail)

    with patch("app.core.engine._settings") as ms, \
         patch("app.core.engine.resolve_field_map", return_value=[]):
        _identity_settings(ms)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id=CYCLE_ID)

    fdb_client.remove_filament_settings_keys.assert_called_once_with(
        OI_FDB_FIL_ID, ["openprinttag_slug", "openprinttag_uuid"]
    )
    fdb_client.merge_filament_settings.assert_not_called()

    fdb_baseline = _get_identity_baseline(db, "filamentdb", OI_FDB_FIL_ID)
    assert fdb_baseline["_opt_uuid"] == ""
