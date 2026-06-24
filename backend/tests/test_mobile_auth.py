"""SECURITY tests for the conditional mobile-scan auth (mobile_session_days).

These assert the exact wiring done in main.py: the mobile + labels routers and the
/r/ redirect carry `mobile_auth` (conditional) while every OTHER router keeps the
global `require_auth`. The matrix:

  mobile_session_days == 0  (public scan flow)
    - /api/mobile/*, /api/labels/*, /r/... succeed WITHOUT a session
    - a normal protected route (require_auth) still 401s without a session
  mobile_session_days >= 1  (default 30)
    - the same scan-flow surfaces 401 without a session, 200/expected with one
  feature gate (mobile_labels_enabled) — when off, the scan-flow endpoints 403
    regardless of the session-days value
  session cookie max-age tracks mobile_session_days
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import auth as auth_module
from app.api import config as config_module
from app.api import labels as labels_module
from app.api import mobile as mobile_module
from app.api import version as version_module
from app.api.auth import mobile_auth, require_auth
from app.api.config import mobile_redirect_target, set_config_value
from app.api.mobile import _require_labels_enabled
from app.db import Base, get_db
from app.models.config import seed_defaults
from app.models.mapping import SpoolMapping
from app.schemas.filamentdb import FDBFilamentDetail
from app.schemas.spoolman import SpoolmanFilament, SpoolmanSpool, SpoolmanVendor


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    seed_defaults(session)
    session.commit()
    yield session
    session.close()


def _mock_settings(auth_enabled: bool = True) -> MagicMock:
    ms = MagicMock()
    ms.auth_enabled = auth_enabled
    ms.sync_interval_seconds = 120
    ms.variant_line_keywords = ""
    ms.opentag_vendor_aliases = ""
    ms.container_parent_marker = "(Master)"
    ms.mobile_labels_enabled = False
    ms.mobile_session_days = 30
    ms.filamentdb_url = "http://fdb"
    return ms


def _fake_spoolman(spool=None) -> AsyncMock:
    client = AsyncMock()
    client.get_spool = AsyncMock(return_value=spool)
    client.get_spools = AsyncMock(return_value=[spool] if spool else [])
    client.update_spool = AsyncMock(return_value=MagicMock())
    return client


def _fake_filamentdb(detail=None) -> AsyncMock:
    client = AsyncMock()
    client.get_filament = AsyncMock(return_value=detail)
    client.get_locations = AsyncMock(return_value=[])
    return client


def _sm_spool():
    return SpoolmanSpool(
        id=1,
        filament=SpoolmanFilament(
            id=10, name="Galaxy Black", material="PLA",
            vendor=SpoolmanVendor(id=2, name="ELEGOO"), color_hex="111111",
        ),
        remaining_weight=800.0, archived=False, location="Shelf A",
    )


def _fdb_detail():
    return FDBFilamentDetail.model_validate({
        "_id": "fil-1", "name": "PLA", "spoolWeight": 200.0, "colorName": "Galaxy Black",
        "color": "#111111", "type": "PLA", "_inherited": [],
        "spools": [{"_id": "spool-1", "totalWeight": 1000.0, "retired": False}],
    })


@contextmanager
def make_client(db, *, auth_enabled: bool = True):
    """Wire an app EXACTLY like main.py: mobile/labels/redirect on mobile_auth,
    a protected router (config) on the global require_auth, plus the public auth
    + version routers so we can log in / read mobile_public.
    """
    ms = _mock_settings(auth_enabled)
    with patch.object(auth_module, "_settings", ms), \
         patch.object(config_module, "_settings", ms):

        app = FastAPI()
        app.dependency_overrides[get_db] = lambda: db
        app.state.spoolman = _fake_spoolman(spool=_sm_spool())
        app.state.filamentdb = _fake_filamentdb(detail=_fdb_detail())

        # Public
        app.include_router(auth_module.router, prefix="/api")
        app.include_router(version_module.router, prefix="/api")

        # Globally protected (require_auth) — stands in for every other router.
        app.include_router(
            config_module.router, prefix="/api", dependencies=[Depends(require_auth)]
        )

        # Conditional auth — the mobile flow.
        _mob = [Depends(mobile_auth)]
        app.include_router(mobile_module.router, prefix="/api", dependencies=_mob)
        app.include_router(labels_module.router, prefix="/api", dependencies=_mob)

        @app.get("/r/{fil}/{spool}", dependencies=_mob)
        async def _qr_redirect(fil: str, spool: str, db_=Depends(get_db)):  # noqa: ANN001
            from fastapi.responses import RedirectResponse

            _require_labels_enabled(db_)
            target = mobile_redirect_target(db_)
            if target == "filamentdb":
                url = f"{ms.filamentdb_url}/filaments/{fil}"
            else:
                url = f"/scan/{fil}/{spool}"
            return RedirectResponse(url, status_code=302)

        with TestClient(app, raise_server_exceptions=True) as client:
            yield client


def _enable_feature(db):
    set_config_value(db, "mobile_labels_enabled", True)
    db.commit()


def _set_days(db, days: int):
    set_config_value(db, "mobile_session_days", days)
    db.commit()


def _add_mapping(db):
    db.add(SpoolMapping(spoolman_spool_id=1, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    db.commit()


# ---------------------------------------------------------------------------
# days == 0 — public scan flow; rest of app still gated
# ---------------------------------------------------------------------------


def test_public_mobile_get_works_without_session(db):
    _enable_feature(db)
    _set_days(db, 0)
    _add_mapping(db)
    with make_client(db) as client:
        client.cookies.clear()
        r = client.get("/api/mobile/spool/fil-1/spool-1")
        assert r.status_code == 200
        assert r.json()["brand"] == "ELEGOO"


def test_public_mobile_patch_works_without_session(db):
    _enable_feature(db)
    _set_days(db, 0)
    _add_mapping(db)
    with make_client(db) as client:
        client.cookies.clear()
        # No weight/location → no writes, but auth + gate must pass (200, not 401/403).
        r = client.patch("/api/mobile/spool/fil-1/spool-1", json={})
        assert r.status_code == 200


def test_public_mobile_locations_works_without_session(db):
    _enable_feature(db)
    _set_days(db, 0)
    with make_client(db) as client:
        client.cookies.clear()
        r = client.get("/api/mobile/locations")
        assert r.status_code == 200


def test_public_labels_endpoint_works_without_session(db):
    """LabelForge unconfigured → 400 (not 401): proves auth + feature gate passed."""
    _enable_feature(db)
    _set_days(db, 0)
    with make_client(db) as client:
        client.cookies.clear()
        r = client.get("/api/labels/printer-status")
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "labelforge_not_configured"


def test_public_redirect_works_without_session(db):
    _enable_feature(db)
    _set_days(db, 0)
    set_config_value(db, "mobile_redirect_target", "bridge")
    db.commit()
    with make_client(db) as client:
        client.cookies.clear()
        r = client.get("/r/fil-1/spool-1", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/scan/fil-1/spool-1"


def test_public_mode_other_routes_still_require_auth(db):
    """SECURITY: with days==0 the rest of the app (require_auth) still 401s w/o a session."""
    _enable_feature(db)
    _set_days(db, 0)
    with make_client(db) as client:
        client.cookies.clear()
        r = client.get("/api/config")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# days >= 1 — scan flow requires login
# ---------------------------------------------------------------------------


def test_gated_mobile_get_401_without_session(db):
    _enable_feature(db)
    _set_days(db, 30)
    _add_mapping(db)
    with make_client(db) as client:
        client.cookies.clear()
        r = client.get("/api/mobile/spool/fil-1/spool-1")
        assert r.status_code == 401


def test_gated_labels_401_without_session(db):
    _enable_feature(db)
    _set_days(db, 30)
    with make_client(db) as client:
        client.cookies.clear()
        r = client.get("/api/labels/printer-status")
        assert r.status_code == 401


def test_gated_redirect_401_without_session(db):
    _enable_feature(db)
    _set_days(db, 30)
    with make_client(db) as client:
        client.cookies.clear()
        r = client.get("/r/fil-1/spool-1", follow_redirects=False)
        assert r.status_code == 401


def test_gated_mobile_get_200_with_session(db):
    _enable_feature(db)
    _set_days(db, 30)
    _add_mapping(db)
    with make_client(db) as client:
        client.post("/api/auth/setup", json={"password": "pw"})  # logs in (sets cookie)
        r = client.get("/api/mobile/spool/fil-1/spool-1")
        assert r.status_code == 200
        assert r.json()["brand"] == "ELEGOO"


def test_gated_mobile_get_200_with_api_token(db):
    """The mobile flow accepts the API token, same as require_auth, when days >= 1."""
    _enable_feature(db)
    _set_days(db, 30)
    _add_mapping(db)
    set_config_value(db, "api_token", "tok-123")
    set_config_value(db, "api_token_enabled", True)
    db.commit()
    with make_client(db) as client:
        client.cookies.clear()
        r = client.get(
            "/api/mobile/spool/fil-1/spool-1",
            headers={"Authorization": "Bearer tok-123"},
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Feature gate is independent of session-days
# ---------------------------------------------------------------------------


def test_feature_disabled_403_even_when_public(db):
    """SECURITY: the 403 feature gate fires before/independent of auth, even at days==0."""
    # mobile_labels_enabled defaults OFF; set public scan flow anyway.
    _set_days(db, 0)
    _add_mapping(db)
    with make_client(db) as client:
        client.cookies.clear()
        r = client.get("/api/mobile/spool/fil-1/spool-1")
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "mobile_labels_disabled"


def test_feature_disabled_403_when_gated_with_session(db):
    """Feature off → 403 even with a valid session and days >= 1."""
    _set_days(db, 30)
    _add_mapping(db)
    with make_client(db) as client:
        client.post("/api/auth/setup", json={"password": "pw"})
        r = client.get("/api/mobile/spool/fil-1/spool-1")
        assert r.status_code == 403


def test_redirect_feature_disabled_403_even_when_public(db):
    _set_days(db, 0)
    with make_client(db) as client:
        client.cookies.clear()
        r = client.get("/r/fil-1/spool-1", follow_redirects=False)
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Session cookie max-age tracks mobile_session_days
# ---------------------------------------------------------------------------


def test_session_max_age_default_30_days(db):
    """days defaults to 30 → cookie max-age is 30 days."""
    with make_client(db) as client:
        r = client.post("/api/auth/setup", json={"password": "pw"})
        assert r.status_code == 200
        set_cookie = r.headers["set-cookie"]
        assert "fb_session=" in set_cookie
        assert f"Max-Age={30 * 24 * 3600}" in set_cookie


def test_session_max_age_follows_setting(db):
    """days == 7 → cookie max-age is 7 days."""
    _set_days(db, 7)
    with make_client(db) as client:
        r = client.post("/api/auth/setup", json={"password": "pw"})
        set_cookie = r.headers["set-cookie"]
        assert f"Max-Age={7 * 24 * 3600}" in set_cookie


def test_session_max_age_zero_falls_back_to_30(db):
    """days == 0 (public scan flow) → non-mobile login cookie falls back to 30 days."""
    _set_days(db, 0)
    with make_client(db) as client:
        r = client.post("/api/auth/setup", json={"password": "pw"})
        set_cookie = r.headers["set-cookie"]
        assert f"Max-Age={30 * 24 * 3600}" in set_cookie


# ---------------------------------------------------------------------------
# /api/version exposes mobile_public
# ---------------------------------------------------------------------------


def test_version_mobile_public_true_when_days_zero(db):
    _set_days(db, 0)
    with patch("app.api.version._fetch_github", side_effect=OSError("no network")):
        with make_client(db) as client:
            r = client.get("/api/version")
    assert r.status_code == 200
    assert r.json()["mobile_public"] is True


def test_version_mobile_public_false_when_days_nonzero(db):
    _set_days(db, 30)
    with patch("app.api.version._fetch_github", side_effect=OSError("no network")):
        with make_client(db) as client:
            r = client.get("/api/version")
    assert r.status_code == 200
    assert r.json()["mobile_public"] is False


# ---------------------------------------------------------------------------
# Config round-trips + rejects negatives
# ---------------------------------------------------------------------------


def test_config_response_includes_mobile_session_days(db):
    with make_client(db, auth_enabled=False) as client:
        r = client.get("/api/config")
        assert r.status_code == 200
        assert r.json()["mobile_session_days"] == 30


def test_config_update_mobile_session_days(db):
    with make_client(db, auth_enabled=False) as client:
        r = client.put("/api/config", json={"mobile_session_days": 0})
        assert r.status_code == 200
        assert r.json()["mobile_session_days"] == 0
    # Persisted in BridgeConfig.
    assert config_module.get_config_value(db, "mobile_session_days") == 0


def test_config_update_rejects_negative_mobile_session_days(db):
    with make_client(db, auth_enabled=False) as client:
        r = client.put("/api/config", json={"mobile_session_days": -1})
        # Pydantic Field(ge=0) rejects before the handler — 422 either way.
        assert r.status_code == 422
