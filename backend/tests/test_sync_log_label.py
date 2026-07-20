"""Tests for the sync-log `label` resolution (human-readable record name).

The sync_log table stores ids only. The API resolves a name at read time from:
- FilamentMapping.identity (authoritative for synced records), and
- a best-effort live-Spoolman fallback (for unmapped records, e.g. new_filament conflicts).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import sync_log
from app.db import get_db
from app.models.mapping import FilamentMapping
from app.models.sync_log import SyncLog
from app.schemas.spoolman import SpoolmanFilament, SpoolmanSpool, SpoolmanVendor


def _client(db, spoolman=None) -> TestClient:
    app = FastAPI()
    app.include_router(sync_log.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.state.spoolman = spoolman or AsyncMock(
        get_filaments=AsyncMock(return_value=[]),
        get_spools=AsyncMock(return_value=[]),
    )
    return TestClient(app)


def _add_log(db, **kw):
    defaults = dict(cycle_id="c1", direction="spoolman_to_filamentdb", action="create", entity_type="filament")
    defaults.update(kw)
    db.add(SyncLog(**defaults))
    db.commit()


def _by_id(items):
    return {i["id"]: i for i in items}


def test_label_from_filament_mapping_identity(db):
    """A row whose FDB filament id maps to a FilamentMapping resolves to 'Vendor Name'."""
    db.add(FilamentMapping(
        spoolman_filament_id=170,
        filamentdb_id="fdb-amolen-cream",
        identity=json.dumps({"vendor": "Amolen", "name": "PLA Basic-High Speed Cream Yellow", "material": "PLA"}),
    ))
    db.commit()
    _add_log(db, action="create", entity_type="filament", spoolman_id=170,
             filamentdb_filament_id="fdb-amolen-cream")

    resp = _client(db).get("/api/sync-log")
    assert resp.status_code == 200, resp.text
    entry = resp.json()["items"][0]
    assert entry["label"] == "Amolen PLA Basic-High Speed Cream Yellow"


def test_label_for_spool_conflict_via_fdb_filament(db):
    """An unmapped spool's new_spool conflict row carries the parent FDB filament id and
    resolves to that filament's name (the reported Amolen case)."""
    db.add(FilamentMapping(
        spoolman_filament_id=170,
        filamentdb_id="fdb-amolen-cream",
        identity=json.dumps({"vendor": "Amolen", "name": "PLA Basic-High Speed Cream Yellow"}),
    ))
    db.commit()
    _add_log(db, action="conflict", entity_type="spool", spoolman_id=208,
             filamentdb_filament_id="fdb-amolen-cream", field_name="new_spool")

    entry = _client(db).get("/api/sync-log").json()["items"][0]
    assert entry["label"] == "Amolen PLA Basic-High Speed Cream Yellow"
    assert entry["spoolman_id"] == 208  # UI shows the spool id alongside


def test_label_falls_back_to_live_spoolman_for_unmapped_filament(db):
    """A new_filament conflict on an unmapped filament (no mapping, no FDB id) is labeled
    from live Spoolman."""
    _add_log(db, action="conflict", entity_type="filament", spoolman_id=55, field_name="new_filament")

    spoolman = AsyncMock(
        get_filaments=AsyncMock(return_value=[
            SpoolmanFilament(id=55, name="Galaxy Black", vendor=SpoolmanVendor(id=1, name="Bambu Lab")),
        ]),
        get_spools=AsyncMock(return_value=[]),
    )
    entry = _client(db, spoolman).get("/api/sync-log").json()["items"][0]
    assert entry["label"] == "Bambu Lab Galaxy Black"


def test_label_none_when_unresolvable_and_spoolman_unavailable(db):
    """No mapping + Spoolman lookup fails → label is None (page still renders)."""
    _add_log(db, action="skip", entity_type="filament", spoolman_id=999)

    spoolman = AsyncMock(get_filaments=AsyncMock(side_effect=RuntimeError("down")),
                         get_spools=AsyncMock(return_value=[]))
    entry = _client(db, spoolman).get("/api/sync-log").json()["items"][0]
    assert entry["label"] is None


def test_label_for_unmapped_spool_via_live_spoolman(db):
    """A spool row with no mapping resolves via the spool's nested filament from live Spoolman."""
    _add_log(db, action="skip", entity_type="spool", spoolman_id=300)

    fil = SpoolmanFilament(id=12, name="Matte Charcoal", vendor=SpoolmanVendor(id=2, name="Prusament"))
    spoolman = AsyncMock(
        get_filaments=AsyncMock(return_value=[fil]),
        get_spools=AsyncMock(return_value=[SpoolmanSpool(id=300, filament=fil)]),
    )
    entry = _client(db, spoolman).get("/api/sync-log").json()["items"][0]
    assert entry["label"] == "Prusament Matte Charcoal"


def test_all_mapped_page_skips_live_spoolman_lookup(db):
    """Perf: when every displayed row resolves from mappings, the sync-log view must NOT
    make the expensive live Spoolman catalog calls."""
    db.add(FilamentMapping(
        spoolman_filament_id=170,
        filamentdb_id="fdb-amolen-cream",
        identity=json.dumps({"vendor": "Amolen", "name": "Cream Yellow", "material": "PLA"}),
    ))
    db.commit()
    _add_log(db, action="update", entity_type="filament", spoolman_id=170,
             filamentdb_filament_id="fdb-amolen-cream")

    spoolman = AsyncMock(get_filaments=AsyncMock(return_value=[]),
                         get_spools=AsyncMock(return_value=[]))
    resp = _client(db, spoolman).get("/api/sync-log")
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"][0]["label"] == "Amolen Cream Yellow"
    spoolman.get_filaments.assert_not_called()
    spoolman.get_spools.assert_not_called()


def test_live_spoolman_labels_cached_across_requests(db):
    """Perf: the live Spoolman catalog lookup is cached, so a second sync-log view (within
    the TTL) does not re-fetch it."""
    _add_log(db, action="conflict", entity_type="filament", spoolman_id=55, field_name="new_filament")

    spoolman = AsyncMock(
        get_filaments=AsyncMock(return_value=[
            SpoolmanFilament(id=55, name="Galaxy Black", vendor=SpoolmanVendor(id=1, name="Bambu Lab")),
        ]),
        get_spools=AsyncMock(return_value=[]),
    )
    client = _client(db, spoolman)  # one app → shared app.state cache
    r1 = client.get("/api/sync-log")
    r2 = client.get("/api/sync-log")
    assert r1.json()["items"][0]["label"] == "Bambu Lab Galaxy Black"
    assert r2.json()["items"][0]["label"] == "Bambu Lab Galaxy Black"
    assert spoolman.get_filaments.call_count == 1  # 2nd request served from cache
