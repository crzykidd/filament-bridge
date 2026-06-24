"""Tests for the mobile updates & labels phase-1 backend.

Covers:
  * weight_ops: the extracted absolute-write core (the #21 behaviour lives in
    test_cross_system_resolve.py + test_api.py) + gross-input mobile cases for
    BOTH save modes.
  * core/locations.ensure_fdb_location: found vs created.
  * core/mobile.assemble_spool_detail: resolve by FDB ids → payload; 404 on no mapping.
  * api/mobile endpoints: the 403 feature gate, GET detail, PATCH applying weight +
    location with both-snapshot refresh.
  * the /r/{fil}/{spool} redirect: target switching + 403 when disabled.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import mobile as mobile_router
from app.api.config import set_config_value
from app.core.locations import ensure_fdb_location
from app.core.mobile import assemble_spool_detail
from app.core.weight_ops import apply_absolute_weight
from app.db import Base, get_db
from app.models.config import seed_defaults
from app.models.mapping import SpoolMapping
from app.models.snapshot import Snapshot
from app.schemas.filamentdb import FDBFilamentDetail
from app.schemas.spoolman import SpoolmanFilament, SpoolmanSpool, SpoolmanVendor


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def _make_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    seed_defaults(session)
    session.commit()
    return session


def _fake_spoolman(spool=None, spools=None) -> AsyncMock:
    client = AsyncMock()
    client.get_spool = AsyncMock(return_value=spool)
    client.get_spools = AsyncMock(return_value=spools or ([spool] if spool else []))
    client.update_spool = AsyncMock(return_value=MagicMock())
    return client


def _fake_filamentdb(detail=None, locations=None) -> AsyncMock:
    client = AsyncMock()
    client.get_filament = AsyncMock(return_value=detail)
    client.update_spool = AsyncMock(return_value={})
    client.log_usage = AsyncMock(return_value={})
    client.get_locations = AsyncMock(return_value=locations or [])
    client.create_location = AsyncMock(return_value={"_id": "loc-new", "name": "X"})
    return client


def _sm_spool(remaining=800.0, location="Shelf A"):
    return SpoolmanSpool(
        id=1,
        filament=SpoolmanFilament(
            id=10, name="Galaxy Black", material="PLA",
            vendor=SpoolmanVendor(id=2, name="ELEGOO"), color_hex="111111",
        ),
        remaining_weight=remaining, archived=False, location=location,
    )


def _fdb_detail(gross=1000.0):
    return FDBFilamentDetail.model_validate({
        "_id": "fil-1", "name": "PLA", "spoolWeight": 200.0, "colorName": "Galaxy Black",
        "color": "#111111", "type": "PLA", "_inherited": [],
        "spools": [{"_id": "spool-1", "totalWeight": gross, "retired": False}],
    })


def _snap(db, source, eid, data):
    db.add(Snapshot(source=source, entity_type="spool", entity_id=eid, data=json.dumps(data)))
    db.flush()


def _client(db, spoolman, filamentdb, *, with_redirect=False) -> TestClient:
    app = FastAPI()
    app.include_router(mobile_router.router, prefix="/api")
    if with_redirect:
        # Replicate main.py's /r/ redirect registration (auth omitted in tests).
        @app.get("/r/{fil}/{spool}")
        async def _qr_redirect(fil: str, spool: str, db_=Depends(get_db)):  # noqa: ANN001
            from fastapi.responses import RedirectResponse

            from app.api.config import mobile_redirect_target
            from app.api.mobile import _require_labels_enabled, qr_redirect_url
            from app.config import settings as _settings

            _require_labels_enabled(db_)
            target = mobile_redirect_target(db_)
            url = qr_redirect_url(target, fil, spool, filamentdb_url=_settings.filamentdb_url)
            return RedirectResponse(url, status_code=302)

    app.dependency_overrides[get_db] = lambda: db
    app.state.spoolman = spoolman
    app.state.filamentdb = filamentdb
    return TestClient(app)


# ===========================================================================
# weight_ops — absolute (mobile gross, direct_correction)
# ===========================================================================


@pytest.mark.asyncio
async def test_apply_absolute_weight_increase_writes_totalweight():
    """An INCREASE / refill is a direct FDB totalWeight write; both snapshots refresh."""
    db = _make_db()
    db.add(SpoolMapping(spoolman_spool_id=1, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    _snap(db, "spoolman", "1", {"remaining_weight": 700.0})
    _snap(db, "filamentdb", "spool-1", {"totalWeight": 900.0})
    db.commit()

    spoolman = _fake_spoolman()
    filamentdb = _fake_filamentdb()

    # net 900 → gross 1100 > current 900 → INCREASE.
    w = await apply_absolute_weight(
        db, spoolman, filamentdb,
        sm_spool_id=1, fdb_fil_id="fil-1", fdb_spool_id="spool-1",
        net_w=900.0, tare=200.0, current_fdb_gross=900.0, cycle_id="t", source="mobile-scale",
    )
    assert w == 900.0
    spoolman.update_spool.assert_awaited_with(1, {"remaining_weight": 900.0})
    filamentdb.update_spool.assert_awaited_with("fil-1", "spool-1", {"totalWeight": 1100.0})
    filamentdb.log_usage.assert_not_awaited()
    fdb_snap = json.loads(db.query(Snapshot).filter_by(source="filamentdb", entity_id="spool-1").first().data)
    assert fdb_snap["totalWeight"] == 1100.0


@pytest.mark.asyncio
async def test_apply_absolute_weight_decrease_logs_usage_not_direct_write():
    """A DECREASE goes through an FDB usage entry — FDB can't lower totalWeight via a
    direct PUT (#28). Spoolman is set directly and both snapshots refresh."""
    db = _make_db()
    db.add(SpoolMapping(spoolman_spool_id=1, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    _snap(db, "spoolman", "1", {"remaining_weight": 800.0})
    _snap(db, "filamentdb", "spool-1", {"totalWeight": 1000.0})
    db.commit()

    spoolman = _fake_spoolman()
    filamentdb = _fake_filamentdb()

    # Scale reads 950 g GROSS; tare 200 → net 750. Current gross 1000 → DECREASE of 50.
    w = await apply_absolute_weight(
        db, spoolman, filamentdb,
        sm_spool_id=1, fdb_fil_id="fil-1", fdb_spool_id="spool-1",
        net_w=750.0, tare=200.0, current_fdb_gross=1000.0, cycle_id="t",
        source="mobile-scale-correction", job_label="Mobile scale correction",
    )
    assert w == 750.0
    spoolman.update_spool.assert_awaited_with(1, {"remaining_weight": 750.0})
    # FDB usage entry for the consumed 50 g — NOT a direct totalWeight write.
    filamentdb.log_usage.assert_awaited_once()
    la = filamentdb.log_usage.await_args
    assert la.args[0] == "fil-1" and la.args[1] == "spool-1" and la.args[2] == 50.0
    assert la.kwargs["source"] == "mobile-scale-correction"
    filamentdb.update_spool.assert_not_awaited()
    # Both snapshots advanced to converged values (anti-ping-pong).
    sm_snap = json.loads(db.query(Snapshot).filter_by(source="spoolman", entity_id="1").first().data)
    fdb_snap = json.loads(db.query(Snapshot).filter_by(source="filamentdb", entity_id="spool-1").first().data)
    assert sm_snap["remaining_weight"] == 750.0
    assert fdb_snap["totalWeight"] == 950.0


# ===========================================================================
# ensure_fdb_location — found vs created
# ===========================================================================


@pytest.mark.asyncio
async def test_ensure_fdb_location_found_existing():
    filamentdb = _fake_filamentdb(locations=[{"_id": "loc-7", "name": "Shelf A"}])
    loc_id = await ensure_fdb_location(filamentdb, "Shelf A")
    assert loc_id == "loc-7"
    filamentdb.create_location.assert_not_awaited()


@pytest.mark.asyncio
async def test_ensure_fdb_location_creates_when_absent():
    filamentdb = _fake_filamentdb(locations=[{"_id": "loc-7", "name": "Shelf A"}])
    filamentdb.create_location = AsyncMock(return_value={"_id": "loc-99", "name": "New Bin"})
    loc_id = await ensure_fdb_location(filamentdb, "New Bin")
    assert loc_id == "loc-99"
    filamentdb.create_location.assert_awaited_once_with("New Bin")


@pytest.mark.asyncio
async def test_ensure_fdb_location_blank_returns_none():
    filamentdb = _fake_filamentdb()
    assert await ensure_fdb_location(filamentdb, "") is None
    assert await ensure_fdb_location(filamentdb, "   ") is None


@pytest.mark.asyncio
async def test_ensure_fdb_location_uses_cache():
    filamentdb = _fake_filamentdb()
    cache = {"Shelf A": "loc-cached"}
    loc_id = await ensure_fdb_location(filamentdb, "Shelf A", cache)
    assert loc_id == "loc-cached"
    filamentdb.get_locations.assert_not_awaited()
    filamentdb.create_location.assert_not_awaited()


# ===========================================================================
# assemble_spool_detail — by FDB ids; 404 on no mapping
# ===========================================================================


@pytest.mark.asyncio
async def test_assemble_spool_detail_payload():
    db = _make_db()
    db.add(SpoolMapping(spoolman_spool_id=1, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    db.commit()
    spoolman = _fake_spoolman(spool=_sm_spool(remaining=800.0))
    filamentdb = _fake_filamentdb(detail=_fdb_detail(gross=1000.0))

    detail = await assemble_spool_detail(
        db, spoolman, filamentdb, fdb_fil_id="fil-1", fdb_spool_id="spool-1",
    )
    assert detail is not None
    assert detail.number == 1
    assert detail.brand == "ELEGOO"
    assert detail.color_name == "Galaxy Black"
    assert detail.gross == 1000.0
    assert detail.net == 800.0
    assert detail.tare == 200.0
    assert detail.location == "Shelf A"
    assert detail.weight_default_mode == "direct_correction"


@pytest.mark.asyncio
async def test_assemble_spool_detail_no_mapping_returns_none():
    db = _make_db()
    spoolman = _fake_spoolman(spool=_sm_spool())
    filamentdb = _fake_filamentdb(detail=_fdb_detail())
    detail = await assemble_spool_detail(
        db, spoolman, filamentdb, fdb_fil_id="fil-1", fdb_spool_id="nope",
    )
    assert detail is None


# ===========================================================================
# Feature gate — 403 when mobile_labels_enabled is off
# ===========================================================================


def test_endpoints_403_when_feature_disabled():
    db = _make_db()  # mobile_labels_enabled defaults to false
    db.add(SpoolMapping(spoolman_spool_id=1, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    db.commit()
    client = _client(db, _fake_spoolman(spool=_sm_spool()), _fake_filamentdb(detail=_fdb_detail()))

    r = client.get("/api/mobile/spool/fil-1/spool-1")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "mobile_labels_disabled"

    r = client.patch("/api/mobile/spool/fil-1/spool-1", json={"gross_grams": 900})
    assert r.status_code == 403
    r = client.get("/api/mobile/locations")
    assert r.status_code == 403


# ===========================================================================
# GET detail (enabled) + 404
# ===========================================================================


def test_get_mobile_spool_returns_detail_when_enabled():
    db = _make_db()
    set_config_value(db, "mobile_labels_enabled", True)
    db.add(SpoolMapping(spoolman_spool_id=1, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    db.commit()
    client = _client(db, _fake_spoolman(spool=_sm_spool()), _fake_filamentdb(detail=_fdb_detail()))

    r = client.get("/api/mobile/spool/fil-1/spool-1")
    assert r.status_code == 200
    body = r.json()
    assert body["brand"] == "ELEGOO"
    assert body["net"] == 800.0
    assert body["gross"] == 1000.0


def test_get_mobile_spool_404_when_unmapped():
    db = _make_db()
    set_config_value(db, "mobile_labels_enabled", True)
    db.commit()
    client = _client(db, _fake_spoolman(spool=_sm_spool()), _fake_filamentdb(detail=_fdb_detail()))
    r = client.get("/api/mobile/spool/fil-1/spool-1")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "spool_not_mapped"


# ===========================================================================
# PATCH — applies gross weight + location and refreshes BOTH snapshots
# ===========================================================================


def test_patch_applies_weight_and_location_with_snapshot_refresh():
    db = _make_db()
    set_config_value(db, "mobile_labels_enabled", True)
    db.add(SpoolMapping(spoolman_spool_id=1, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    _snap(db, "spoolman", "1", {"remaining_weight": 800.0, "location": "Shelf A"})
    _snap(db, "filamentdb", "spool-1", {"totalWeight": 1000.0})
    db.commit()

    spoolman = _fake_spoolman(spool=_sm_spool(remaining=750.0, location="Bin 9"))
    filamentdb = _fake_filamentdb(detail=_fdb_detail(gross=1000.0))
    filamentdb.create_location = AsyncMock(return_value={"_id": "loc-9", "name": "Bin 9"})
    client = _client(db, spoolman, filamentdb)

    # GROSS 950 → net 750 (tare 200), default mode = direct_correction. Move to Bin 9.
    r = client.patch(
        "/api/mobile/spool/fil-1/spool-1",
        json={"gross_grams": 950, "location": "Bin 9"},
    )
    assert r.status_code == 200

    # Weight DECREASE (950 < current 1000): SM net 750 set directly; FDB lowered via a
    # usage entry, not a direct totalWeight write (#28).
    spoolman.update_spool.assert_any_await(1, {"remaining_weight": 750.0})
    filamentdb.log_usage.assert_awaited_once()
    assert filamentdb.log_usage.await_args.args[2] == 50.0
    # Location: FDB locationId + SM free-text (location DOES use update_spool).
    filamentdb.update_spool.assert_any_await("fil-1", "spool-1", {"locationId": "loc-9"})
    spoolman.update_spool.assert_any_await(1, {"location": "Bin 9"})

    # Both snapshots refreshed (anti-ping-pong): weight + location.
    sm_snap = json.loads(db.query(Snapshot).filter_by(source="spoolman", entity_id="1").first().data)
    fdb_snap = json.loads(db.query(Snapshot).filter_by(source="filamentdb", entity_id="spool-1").first().data)
    assert sm_snap["remaining_weight"] == 750.0
    assert sm_snap["location"] == "Bin 9"
    assert fdb_snap["totalWeight"] == 950.0
    assert fdb_snap["locationId"] == "loc-9"


def test_patch_usage_mode_logs_fdb_usage_on_decrease():
    db = _make_db()
    set_config_value(db, "mobile_labels_enabled", True)
    db.add(SpoolMapping(spoolman_spool_id=1, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    db.commit()
    spoolman = _fake_spoolman(spool=_sm_spool(remaining=750.0))
    filamentdb = _fake_filamentdb(detail=_fdb_detail(gross=1000.0))
    client = _client(db, spoolman, filamentdb)

    # Per-request override to usage mode; GROSS 950 (net 750) < current gross 1000 → usage 50 g.
    r = client.patch(
        "/api/mobile/spool/fil-1/spool-1",
        json={"gross_grams": 950, "weight_mode": "usage"},
    )
    assert r.status_code == 200
    filamentdb.log_usage.assert_awaited_once()
    assert filamentdb.log_usage.await_args.args[2] == 50.0


def test_patch_negative_weight_rejected():
    db = _make_db()
    set_config_value(db, "mobile_labels_enabled", True)
    db.add(SpoolMapping(spoolman_spool_id=1, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    db.commit()
    client = _client(db, _fake_spoolman(spool=_sm_spool()), _fake_filamentdb(detail=_fdb_detail()))
    r = client.patch("/api/mobile/spool/fil-1/spool-1", json={"gross_grams": -5})
    assert r.status_code == 422


def test_get_mobile_locations_merges_and_sorts():
    db = _make_db()
    set_config_value(db, "mobile_labels_enabled", True)
    db.commit()
    spoolman = _fake_spoolman(spools=[_sm_spool(location="Bin 9"), _sm_spool(location="Shelf A")])
    filamentdb = _fake_filamentdb(locations=[{"_id": "1", "name": "Dry Box"}, {"_id": "2", "name": "Shelf A"}])
    client = _client(db, spoolman, filamentdb)
    r = client.get("/api/mobile/locations")
    assert r.status_code == 200
    assert r.json() == ["Bin 9", "Dry Box", "Shelf A"]


# ===========================================================================
# /r/{fil}/{spool} redirect — target switching + 403 gate
# ===========================================================================


def test_redirect_to_bridge_scan_page():
    db = _make_db()
    set_config_value(db, "mobile_labels_enabled", True)
    set_config_value(db, "mobile_redirect_target", "bridge")
    db.commit()
    client = _client(db, _fake_spoolman(), _fake_filamentdb(), with_redirect=True)
    r = client.get("/r/fil-1/spool-1", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/scan/fil-1/spool-1"


def test_redirect_to_filamentdb():
    db = _make_db()
    set_config_value(db, "mobile_labels_enabled", True)
    set_config_value(db, "mobile_redirect_target", "filamentdb")
    db.commit()
    client = _client(db, _fake_spoolman(), _fake_filamentdb(), with_redirect=True)
    r = client.get("/r/fil-1/spool-1", follow_redirects=False)
    assert r.status_code == 302
    from app.config import settings as _settings
    assert r.headers["location"] == f"{_settings.filamentdb_url}/filaments/fil-1"


def test_redirect_403_when_feature_disabled():
    db = _make_db()  # disabled by default
    client = _client(db, _fake_spoolman(), _fake_filamentdb(), with_redirect=True)
    r = client.get("/r/fil-1/spool-1", follow_redirects=False)
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "mobile_labels_disabled"


def test_redirect_rejects_malformed_id():
    # A scanned id outside the [A-Za-z0-9_-] allowlist (e.g. one carrying a '.') 404s
    # rather than being interpolated into the redirect URL — closes the open-redirect /
    # path-injection vector (CWE-601 / CWE-22).
    db = _make_db()
    set_config_value(db, "mobile_labels_enabled", True)
    set_config_value(db, "mobile_redirect_target", "bridge")
    db.commit()
    client = _client(db, _fake_spoolman(), _fake_filamentdb(), with_redirect=True)
    r = client.get("/r/fil.1/spool-1", follow_redirects=False)
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "not_found"
