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
    client.add_dry_cycle = AsyncMock(return_value={})
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


# ===========================================================================
# GET /api/mobile/spools — spool search endpoint
# ===========================================================================


def _make_db_with_mapping_and_snapshot(name="Galaxy Black", vendor="ELEGOO", color_hex="111111"):
    """Helper: db with a mapped spool + a Spoolman snapshot carrying filament fields."""
    from app.models.mapping import FilamentMapping

    db = _make_db()
    set_config_value(db, "mobile_labels_enabled", True)
    fm = FilamentMapping(
        spoolman_filament_id=10,
        filamentdb_id="fil-1",
        filamentdb_parent_id=None,
    )
    db.add(fm)
    db.flush()
    db.add(SpoolMapping(
        spoolman_spool_id=1,
        filamentdb_filament_id="fil-1",
        filamentdb_spool_id="spool-1",
        filament_mapping_id=fm.id,
    ))
    # Snapshot with nested filament dict (mirrors real engine output).
    sm_data = {
        "remaining_weight": 800.0,
        "filament": {
            "id": 10,
            "name": name,
            "material": "PLA",
            "color_hex": color_hex,
            "vendor": {"id": 2, "name": vendor},
        },
    }
    _snap(db, "spoolman", "1", sm_data)
    _snap(db, "filamentdb", "spool-1", {"totalWeight": 1000.0})
    db.commit()
    return db


def test_search_spools_403_when_feature_disabled():
    db = _make_db()  # mobile_labels_enabled defaults to false
    client = _client(db, _fake_spoolman(), _fake_filamentdb())
    r = client.get("/api/mobile/spools")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "mobile_labels_disabled"


def test_search_spools_empty_q_returns_all():
    db = _make_db_with_mapping_and_snapshot()
    client = _client(db, _fake_spoolman(), _fake_filamentdb())

    r = client.get("/api/mobile/spools")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    row = body[0]
    assert row["filamentdb_filament_id"] == "fil-1"
    assert row["filamentdb_spool_id"] == "spool-1"
    assert row["spoolman_spool_id"] == 1
    assert row["name"] == "Galaxy Black"
    assert row["vendor"] == "ELEGOO"
    assert row["color"] == "111111"


def test_search_spools_filters_by_name():
    db = _make_db_with_mapping_and_snapshot(name="Galaxy Black", vendor="ELEGOO")
    client = _client(db, _fake_spoolman(), _fake_filamentdb())

    r = client.get("/api/mobile/spools?q=galaxy")
    assert r.status_code == 200
    assert len(r.json()) == 1

    r2 = client.get("/api/mobile/spools?q=nomatch")
    assert r2.status_code == 200
    assert len(r2.json()) == 0


def test_search_spools_filters_by_vendor():
    db = _make_db_with_mapping_and_snapshot(vendor="ELEGOO")
    client = _client(db, _fake_spoolman(), _fake_filamentdb())

    r = client.get("/api/mobile/spools?q=elegoo")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_search_spools_filters_by_spool_id():
    db = _make_db_with_mapping_and_snapshot()
    client = _client(db, _fake_spoolman(), _fake_filamentdb())

    r = client.get("/api/mobile/spools?q=1")
    assert r.status_code == 200
    # spoolman_spool_id=1 contains "1"
    assert len(r.json()) == 1


def test_search_spools_only_returns_spool_rows():
    """Filament-only rows (kind='filament') are not returned by the search endpoint."""
    from app.models.mapping import FilamentMapping

    db = _make_db()
    set_config_value(db, "mobile_labels_enabled", True)
    # Add a filament mapping with no child SpoolMapping — this becomes a kind="filament" row.
    db.add(FilamentMapping(
        spoolman_filament_id=99,
        filamentdb_id="fil-99",
        filamentdb_parent_id=None,
    ))
    db.commit()
    client = _client(db, _fake_spoolman(), _fake_filamentdb())

    r = client.get("/api/mobile/spools")
    assert r.status_code == 200
    # No spool rows exist — the filament-only row must not be returned.
    assert len(r.json()) == 0


# ===========================================================================
# Dry cycle — POST /api/mobile/spool/{fil}/{spool}/dry-cycle
# ===========================================================================


def _fdb_detail_with_drying(gross=1000.0):
    """FDB detail carrying dryingTemperature + dryingTime + a spool dryCycles array.

    Mirrors the real GET /api/filaments/:id shape: the spool carries a dryCycles[]
    array of {date, tempC, durationMin} entries (no convenience lastDriedAt/
    dryCycleCount fields — those are computed and not reliably returned). The newest
    cycle date is deliberately NOT last in the array, to exercise the newest-wins
    derivation.
    """
    return FDBFilamentDetail.model_validate({
        "_id": "fil-1", "name": "PLA", "spoolWeight": 200.0, "colorName": "Galaxy Black",
        "color": "#111111", "type": "PLA", "_inherited": [],
        "dryingTemperature": 65,
        "dryingTime": 240,
        "spools": [{
            "_id": "spool-1", "totalWeight": gross, "retired": False,
            "dryCycles": [
                {"date": "2026-05-01T10:00:00Z", "tempC": 60, "durationMin": 180},
                {"date": "2026-06-01T10:00:00Z", "tempC": 65, "durationMin": 240},
                {"date": "2026-04-01T10:00:00Z", "tempC": 55, "durationMin": 120},
            ],
        }],
    })


def test_dry_cycle_calls_add_dry_cycle_and_returns_detail():
    db = _make_db()
    set_config_value(db, "mobile_labels_enabled", True)
    db.add(SpoolMapping(spoolman_spool_id=1, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    db.commit()
    spoolman = _fake_spoolman(spool=_sm_spool())
    filamentdb = _fake_filamentdb(detail=_fdb_detail_with_drying())
    client = _client(db, spoolman, filamentdb)

    r = client.post(
        "/api/mobile/spool/fil-1/spool-1/dry-cycle",
        json={"temp_c": 65, "duration_min": 240, "notes": "pre-print"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["filamentdb_spool_id"] == "spool-1"
    # add_dry_cycle called once with camelCase FDB keys (no date).
    filamentdb.add_dry_cycle.assert_awaited_once_with(
        "fil-1", "spool-1",
        {"tempC": 65, "durationMin": 240, "notes": "pre-print"},
    )


def test_dry_cycle_omits_none_fields():
    db = _make_db()
    set_config_value(db, "mobile_labels_enabled", True)
    db.add(SpoolMapping(spoolman_spool_id=1, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    db.commit()
    spoolman = _fake_spoolman(spool=_sm_spool())
    filamentdb = _fake_filamentdb(detail=_fdb_detail())
    client = _client(db, spoolman, filamentdb)

    r = client.post("/api/mobile/spool/fil-1/spool-1/dry-cycle", json={})
    assert r.status_code == 200
    # No fields → empty dict passed to add_dry_cycle.
    filamentdb.add_dry_cycle.assert_awaited_once_with("fil-1", "spool-1", {})


def test_dry_cycle_403_when_feature_disabled():
    db = _make_db()  # mobile_labels_enabled defaults to false
    db.add(SpoolMapping(spoolman_spool_id=1, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    db.commit()
    client = _client(db, _fake_spoolman(spool=_sm_spool()), _fake_filamentdb(detail=_fdb_detail()))
    r = client.post("/api/mobile/spool/fil-1/spool-1/dry-cycle", json={"temp_c": 65})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "mobile_labels_disabled"


def test_dry_cycle_404_when_unmapped():
    db = _make_db()
    set_config_value(db, "mobile_labels_enabled", True)
    db.commit()
    client = _client(db, _fake_spoolman(spool=_sm_spool()), _fake_filamentdb(detail=_fdb_detail()))
    r = client.post("/api/mobile/spool/fil-1/spool-1/dry-cycle", json={"temp_c": 65})
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "spool_not_mapped"


@pytest.mark.asyncio
async def test_assemble_spool_detail_surfaces_drying_fields():
    db = _make_db()
    db.add(SpoolMapping(spoolman_spool_id=1, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    db.commit()
    spoolman = _fake_spoolman(spool=_sm_spool())
    filamentdb = _fake_filamentdb(detail=_fdb_detail_with_drying())

    detail = await assemble_spool_detail(
        db, spoolman, filamentdb, fdb_fil_id="fil-1", fdb_spool_id="spool-1",
    )
    assert detail is not None
    assert detail.recommended_drying_temp_c == 65
    assert detail.recommended_drying_time_min == 240
    assert detail.last_dried_at == "2026-06-01T10:00:00Z"
    assert detail.dry_cycle_count == 3


@pytest.mark.asyncio
async def test_assemble_spool_detail_surfaces_is_retired():
    """is_retired is propagated from the FDB spool subdocument."""
    db = _make_db()
    db.add(SpoolMapping(spoolman_spool_id=1, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    db.commit()
    spoolman = _fake_spoolman(spool=_sm_spool())
    retired_detail = FDBFilamentDetail.model_validate({
        "_id": "fil-1", "name": "PLA", "spoolWeight": 200.0, "colorName": "Galaxy Black",
        "color": "#111111", "type": "PLA", "_inherited": [],
        "spools": [{"_id": "spool-1", "totalWeight": 1000.0, "retired": True}],
    })
    filamentdb = _fake_filamentdb(detail=retired_detail)

    detail = await assemble_spool_detail(
        db, spoolman, filamentdb, fdb_fil_id="fil-1", fdb_spool_id="spool-1",
    )
    assert detail is not None
    assert detail.is_retired is True


# ===========================================================================
# Printer + slot assignment endpoints
# ===========================================================================

_PRINTER_RAW = [
    {
        "_id": "printer-1",
        "name": "Bambu X1C",
        "amsSlots": [
            {"_id": "slot-1", "slotName": "AMS 1", "spoolId": None, "filamentId": None},
            {"_id": "slot-2", "slotName": "AMS 2", "spoolId": "spool-99", "filamentId": "fil-99"},
        ],
    }
]

_ASSIGNMENT_RAW = {
    "assignment": {
        "printerId": "printer-1",
        "printerName": "Bambu X1C",
        "slotId": "slot-1",
        "slotName": "AMS 1",
        "filamentId": "fil-1",
    }
}


def _fake_filamentdb_with_printers(detail=None) -> AsyncMock:
    client = _fake_filamentdb(detail=detail)
    client.list_printers = AsyncMock(return_value=_PRINTER_RAW)
    client.get_spool_assignment = AsyncMock(return_value=_ASSIGNMENT_RAW)
    client.set_spool_assignment = AsyncMock(return_value=_ASSIGNMENT_RAW)
    client.clear_spool_assignment = AsyncMock(return_value={"assignment": None})
    return client


def test_get_printers_returns_list():
    db = _make_db()
    set_config_value(db, "mobile_labels_enabled", True)
    db.commit()
    client = _client(db, _fake_spoolman(), _fake_filamentdb_with_printers())

    r = client.get("/api/mobile/printers")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    p = body[0]
    assert p["printer_id"] == "printer-1"
    assert p["printer_name"] == "Bambu X1C"
    assert len(p["slots"]) == 2
    assert p["slots"][0]["slot_id"] == "slot-1"
    assert p["slots"][0]["spool_id"] is None
    assert p["slots"][1]["spool_id"] == "spool-99"


def test_get_printers_403_when_feature_disabled():
    db = _make_db()
    client = _client(db, _fake_spoolman(), _fake_filamentdb_with_printers())
    r = client.get("/api/mobile/printers")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "mobile_labels_disabled"


def test_get_spool_assignment_returns_assignment():
    db = _make_db()
    set_config_value(db, "mobile_labels_enabled", True)
    db.add(SpoolMapping(spoolman_spool_id=1, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    db.commit()
    client = _client(db, _fake_spoolman(spool=_sm_spool()), _fake_filamentdb_with_printers(detail=_fdb_detail()))

    r = client.get("/api/mobile/spool/fil-1/spool-1/assignment")
    assert r.status_code == 200
    body = r.json()
    assert body["printer_id"] == "printer-1"
    assert body["slot_id"] == "slot-1"
    assert body["slot_name"] == "AMS 1"


def test_get_spool_assignment_404_when_unmapped():
    db = _make_db()
    set_config_value(db, "mobile_labels_enabled", True)
    db.commit()
    client = _client(db, _fake_spoolman(spool=_sm_spool()), _fake_filamentdb_with_printers())
    r = client.get("/api/mobile/spool/fil-1/spool-1/assignment")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "spool_not_mapped"


def test_get_spool_assignment_403_when_feature_disabled():
    db = _make_db()
    db.add(SpoolMapping(spoolman_spool_id=1, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    db.commit()
    client = _client(db, _fake_spoolman(spool=_sm_spool()), _fake_filamentdb_with_printers())
    r = client.get("/api/mobile/spool/fil-1/spool-1/assignment")
    assert r.status_code == 403


def test_get_spool_assignment_returns_null_when_unassigned():
    db = _make_db()
    set_config_value(db, "mobile_labels_enabled", True)
    db.add(SpoolMapping(spoolman_spool_id=1, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    db.commit()
    fdb = _fake_filamentdb_with_printers(detail=_fdb_detail())
    fdb.get_spool_assignment = AsyncMock(return_value={"assignment": None})
    client = _client(db, _fake_spoolman(spool=_sm_spool()), fdb)

    r = client.get("/api/mobile/spool/fil-1/spool-1/assignment")
    assert r.status_code == 200
    assert r.json() is None


def test_put_assignment_happy_path():
    db = _make_db()
    set_config_value(db, "mobile_labels_enabled", True)
    db.add(SpoolMapping(spoolman_spool_id=1, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    db.commit()
    fdb = _fake_filamentdb_with_printers(detail=_fdb_detail())
    client = _client(db, _fake_spoolman(spool=_sm_spool()), fdb)

    r = client.put(
        "/api/mobile/spool/fil-1/spool-1/assignment",
        json={"printer_id": "printer-1", "slot_id": "slot-1"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["printer_id"] == "printer-1"
    # Verify we called set_spool_assignment with the right args.
    fdb.set_spool_assignment.assert_awaited_once_with("spool-1", "printer-1", "slot-1")


def test_put_assignment_propagates_400_retired():
    """FDB 400 (retired spool) is surfaced as bridge 400 spool_retired."""
    import httpx as _httpx

    db = _make_db()
    set_config_value(db, "mobile_labels_enabled", True)
    db.add(SpoolMapping(spoolman_spool_id=1, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    db.commit()
    fdb = _fake_filamentdb_with_printers(detail=_fdb_detail())
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    fdb.set_spool_assignment = AsyncMock(
        side_effect=_httpx.HTTPStatusError("400", request=MagicMock(), response=mock_resp)
    )
    client = _client(db, _fake_spoolman(spool=_sm_spool()), fdb)

    r = client.put(
        "/api/mobile/spool/fil-1/spool-1/assignment",
        json={"printer_id": "printer-1", "slot_id": "slot-1"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "spool_retired"


def test_put_assignment_propagates_404():
    """FDB 404 (spool/printer/slot not found) is surfaced as bridge 404 not_found."""
    import httpx as _httpx

    db = _make_db()
    set_config_value(db, "mobile_labels_enabled", True)
    db.add(SpoolMapping(spoolman_spool_id=1, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    db.commit()
    fdb = _fake_filamentdb_with_printers(detail=_fdb_detail())
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    fdb.set_spool_assignment = AsyncMock(
        side_effect=_httpx.HTTPStatusError("404", request=MagicMock(), response=mock_resp)
    )
    client = _client(db, _fake_spoolman(spool=_sm_spool()), fdb)

    r = client.put(
        "/api/mobile/spool/fil-1/spool-1/assignment",
        json={"printer_id": "printer-1", "slot_id": "slot-1"},
    )
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "not_found"


def test_put_assignment_403_when_feature_disabled():
    db = _make_db()
    db.add(SpoolMapping(spoolman_spool_id=1, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    db.commit()
    client = _client(db, _fake_spoolman(spool=_sm_spool()), _fake_filamentdb_with_printers())
    r = client.put(
        "/api/mobile/spool/fil-1/spool-1/assignment",
        json={"printer_id": "printer-1", "slot_id": "slot-1"},
    )
    assert r.status_code == 403


def test_delete_assignment_happy_path():
    db = _make_db()
    set_config_value(db, "mobile_labels_enabled", True)
    db.add(SpoolMapping(spoolman_spool_id=1, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    db.commit()
    fdb = _fake_filamentdb_with_printers(detail=_fdb_detail())
    client = _client(db, _fake_spoolman(spool=_sm_spool()), fdb)

    r = client.delete("/api/mobile/spool/fil-1/spool-1/assignment")
    assert r.status_code == 200
    assert r.json() is None  # assignment: null → returns None
    fdb.clear_spool_assignment.assert_awaited_once_with("spool-1")


def test_delete_assignment_403_when_feature_disabled():
    db = _make_db()
    db.add(SpoolMapping(spoolman_spool_id=1, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    db.commit()
    client = _client(db, _fake_spoolman(spool=_sm_spool()), _fake_filamentdb_with_printers())
    r = client.delete("/api/mobile/spool/fil-1/spool-1/assignment")
    assert r.status_code == 403
