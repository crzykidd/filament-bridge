"""Tests for FDB->SM new-spool detection keying on the GUID, not the user-set `label`
(issue #87).

Bug: the FDB->SM new-spool loop decided "already synced?" by checking whether the FDB
spool `label` field was non-empty. `label` is a user-supplied field (e.g. FDB 1.73.0's
"Next #" button) — the bridge only ever stuffed the Spoolman spool id into it as a
convenience when it was blank. Because detection keyed on `label`, a spool the user
hand-labeled was wrongly treated as already synced and never created in Spoolman.

Fix (backend/app/core/engine.py):
1. Detection now keys on the FDB spool GUID: skip only when the spool is already
   SpoolMapping'd, or its GUID is already referenced by a Spoolman spool's
   `filamentdb_spool_id` extra (a cross-ref orphan whose SpoolMapping was lost —
   don't duplicate). The `label`-presence skip is gone entirely.
2. The SM-id-into-`label` writeback (both the engine's `_handle_new_fdb_spool` and the
   wizard's parallel writeback) is now conditional on `label` being blank — a user value
   is never overwritten.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.engine import run_sync_cycle
from app.models.mapping import FilamentMapping
from app.schemas.filamentdb import FDBFilament
from app.schemas.spoolman import SpoolmanFilament, SpoolmanSpool, SpoolmanVendor


# ---------------------------------------------------------------------------
# Helpers (mirroring tests/test_engine.py's new-record-policy section)
# ---------------------------------------------------------------------------


def _fdb_filament_with_labeled_spool(fid: str, spool_id: str, label: str | None) -> FDBFilament:
    return FDBFilament.model_validate({
        "_id": fid,
        "name": "PLA",
        "spoolWeight": 200.0,
        "spools": [{"_id": spool_id, "totalWeight": 700.0, "retired": False, "label": label}],
    })


def _sm_spool_with_extra(spool_id: int, filament_id: int, extra: dict | None = None) -> SpoolmanSpool:
    fil = SpoolmanFilament(id=filament_id, name="PLA", vendor=SpoolmanVendor(id=1, name="ACME"))
    return SpoolmanSpool(
        id=spool_id, filament=fil, remaining_weight=500.0, archived=False, extra=extra or {},
    )


def _add_fil_mapping(db, sm_fil_id: int, fdb_fil_id: str):
    db.add(FilamentMapping(spoolman_filament_id=sm_fil_id, filamentdb_id=fdb_fil_id))
    db.flush()


def _seed_new_spool_policy(db, policy: str = "auto_import"):
    from app.models.config import BridgeConfig
    db.merge(BridgeConfig(key="new_spool_policy", value=json.dumps(policy)))
    db.commit()


def _fake_spoolman(spools=None, filaments=None) -> AsyncMock:
    client = AsyncMock()
    client.get_spools = AsyncMock(return_value=spools or [])
    # Union any explicit filaments with those embedded on spools — the engine purges a
    # FilamentMapping whose Spoolman filament isn't returned by get_filaments, treating
    # it as deleted (stale-mapping GC), so a mapped filament must always appear here.
    fils: dict[int, object] = {f.id: f for f in (filaments or [])}
    for s in spools or []:
        f = getattr(s, "filament", None)
        if f is not None and f.id not in fils:
            fils[f.id] = f
    client.get_filaments = AsyncMock(return_value=list(fils.values()))
    client.get_field_definitions = AsyncMock(return_value=[])
    client.update_spool = AsyncMock(return_value=MagicMock())
    client.update_filament = AsyncMock(return_value=MagicMock())
    client.create_spool = AsyncMock(return_value=MagicMock(id=999))
    return client


def _fake_filamentdb(filaments=None) -> AsyncMock:
    client = AsyncMock()
    client.get_filaments = AsyncMock(return_value=filaments or [])
    client.get_filament = AsyncMock(return_value=None)
    client.get_version = AsyncMock(return_value="1.33.0")
    client.log_usage = AsyncMock(return_value={})
    client.update_spool = AsyncMock(return_value={})
    client.update_filament = AsyncMock(return_value={})
    client.create_spool = AsyncMock(return_value={"_id": "new-spool-id"})
    client.get_locations = AsyncMock(return_value=[])
    client.create_location = AsyncMock(return_value={"_id": "new-loc-id", "name": "New"})
    return client


def _default_settings(mock_settings):
    mock_settings.filamentdb_spoolman_id_field = "label"
    mock_settings.spoolman_field_filamentdb_id = "filamentdb_id"
    mock_settings.spoolman_field_filamentdb_spool_id = "filamentdb_spool_id"
    mock_settings.spoolman_field_filamentdb_parent_id = "filamentdb_parent_id"
    mock_settings.parsed_field_mappings = {}
    mock_settings.parsed_field_mapping_excludes = set()


# ---------------------------------------------------------------------------
# 1. A user-set label must NOT block the import, and must NOT be overwritten.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fdb_spool_with_user_label_is_imported_and_label_preserved(db):
    """A FDB spool carrying a user-set `label` (e.g. FDB's "Next #") with no
    SpoolMapping and no live Spoolman cross-ref must still be imported to Spoolman
    (detection is by GUID, not label), and its label must be left untouched."""
    fdb_fil = _fdb_filament_with_labeled_spool("fdb-fil-70", "fdb-spool-70", label="007")
    _add_fil_mapping(db, sm_fil_id=70, fdb_fil_id="fdb-fil-70")
    _seed_new_spool_policy(db, "auto_import")

    sm_fil = SpoolmanFilament(id=70, name="PLA", vendor=SpoolmanVendor(id=1, name="ACME"))
    spoolman = _fake_spoolman(spools=[], filaments=[sm_fil])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])

    with patch("app.core.engine._settings") as ms:
        _default_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="c-label-user")

    spoolman.create_spool.assert_called_once()
    assert result.created >= 1

    # The user-set label must never be overwritten.
    for call in fdb_client.update_spool.await_args_list:
        payload = call.args[2] if len(call.args) > 2 else call.kwargs.get("data", {})
        assert "label" not in payload or payload.get("label") == "007", (
            f"user-set label must not be overwritten, got payload={payload}"
        )


# ---------------------------------------------------------------------------
# 2. A blank label -> imported, and the label is filled with the SM spool id.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fdb_spool_with_blank_label_is_imported_and_label_filled(db):
    """A FDB spool with a blank label is imported normally, and the bridge fills the
    now-blank label with the new Spoolman spool id as a convenience."""
    fdb_fil = _fdb_filament_with_labeled_spool("fdb-fil-71", "fdb-spool-71", label=None)
    _add_fil_mapping(db, sm_fil_id=71, fdb_fil_id="fdb-fil-71")
    _seed_new_spool_policy(db, "auto_import")

    sm_fil = SpoolmanFilament(id=71, name="PLA", vendor=SpoolmanVendor(id=1, name="ACME"))
    spoolman = _fake_spoolman(spools=[], filaments=[sm_fil])
    spoolman.create_spool = AsyncMock(return_value=MagicMock(id=555))
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])

    with patch("app.core.engine._settings") as ms:
        _default_settings(ms)
        result = await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="c-label-blank")

    spoolman.create_spool.assert_called_once()
    assert result.created >= 1

    fdb_client.update_spool.assert_called_once()
    call = fdb_client.update_spool.await_args
    fil_id, spool_id, payload = call.args[0], call.args[1], call.args[2]
    assert fil_id == "fdb-fil-71"
    assert spool_id == "fdb-spool-71"
    assert payload == {"label": "555"}


# ---------------------------------------------------------------------------
# 3. GUID already referenced by a Spoolman spool but SpoolMapping is missing ->
#    treated as an already-synced orphan, not duplicated.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fdb_spool_guid_already_xreffed_is_not_duplicated(db):
    """An FDB spool whose GUID is already stored in a Spoolman spool's
    filamentdb_spool_id extra, but which has no SpoolMapping row (e.g. the bridge DB
    was reset), must NOT be re-imported/duplicated — even though its label is blank."""
    fdb_fil = _fdb_filament_with_labeled_spool("fdb-fil-72", "fdb-spool-72", label=None)
    _add_fil_mapping(db, sm_fil_id=72, fdb_fil_id="fdb-fil-72")
    _seed_new_spool_policy(db, "auto_import")

    sm_spool = _sm_spool_with_extra(
        900, filament_id=72,
        extra={"filamentdb_spool_id": json.dumps("fdb-spool-72")},
    )
    spoolman = _fake_spoolman(spools=[sm_spool])
    fdb_client = _fake_filamentdb(filaments=[fdb_fil])

    with patch("app.core.engine._settings") as ms:
        _default_settings(ms)
        await run_sync_cycle(db, spoolman, fdb_client, dry_run=False, cycle_id="c-xref-orphan")

    spoolman.create_spool.assert_not_called()
