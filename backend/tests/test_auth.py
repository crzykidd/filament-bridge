"""Tests for the auth router and require_auth dependency.

Covers:
- GET  /api/auth/status (public)
- POST /api/auth/setup  (public, only when password not set)
- POST /api/auth/login  (public)
- POST /api/auth/logout
- POST /api/auth/change-password (auth required)
- POST /api/auth/api-token/regenerate (auth required)
- require_auth dependency:
  - bypassed when AUTH_ENABLED=false
  - 401 without credentials
  - 200 with valid session cookie
  - 200 with valid API token when enabled
  - 401 with token when api_token_enabled=false
  - 401 with wrong token
- required_settings_unset reports variant_parent_mode when "unset"
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch, MagicMock

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import auth as auth_module
from app.api import config as config_module
from app.api import health as health_module
from app.api.auth import require_auth
from app.api.config import get_config_value, set_config_value
from app.db import Base, get_db
from app.models.config import seed_defaults


# ---------------------------------------------------------------------------
# DB fixture
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


# ---------------------------------------------------------------------------
# App / client factory
# ---------------------------------------------------------------------------


def _mock_settings(auth_enabled: bool) -> MagicMock:
    ms = MagicMock()
    ms.auth_enabled = auth_enabled
    ms.sync_interval_seconds = 120
    ms.variant_line_keywords = ""
    ms.opentag_vendor_aliases = ""
    ms.opentag_color_keywords = ""
    ms.container_parent_marker = "(Master)"
    return ms


@contextmanager
def make_client(db, auth_enabled: bool = True):
    """Context-manager yielding a TestClient wired to the given db session."""
    ms = _mock_settings(auth_enabled)
    with patch.object(auth_module, "_settings", ms), \
         patch.object(config_module, "_settings", ms):

        app = FastAPI()
        app.dependency_overrides[get_db] = lambda: db

        # Public routes
        app.include_router(health_module.router, prefix="/api")
        app.include_router(auth_module.router, prefix="/api")

        # Protected route
        app.include_router(
            config_module.router,
            prefix="/api",
            dependencies=[Depends(require_auth)],
        )

        with TestClient(app, raise_server_exceptions=True) as client:
            yield client


# ---------------------------------------------------------------------------
# Status endpoint
# ---------------------------------------------------------------------------


def test_auth_status_no_password(db):
    with make_client(db) as client:
        r = client.get("/api/auth/status")
        assert r.status_code == 200
        body = r.json()
        assert body["auth_enabled"] is True
        assert body["password_set"] is False
        assert body["authenticated"] is False


def test_auth_status_auth_disabled(db):
    with make_client(db, auth_enabled=False) as client:
        r = client.get("/api/auth/status")
        assert r.status_code == 200
        body = r.json()
        assert body["auth_enabled"] is False
        # When auth is disabled, user is always "authenticated"
        assert body["authenticated"] is True


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


def test_setup_sets_password(db):
    with make_client(db) as client:
        r = client.post("/api/auth/setup", json={"password": "secret123"})
        assert r.status_code == 200
        body = r.json()
        assert body["password_set"] is True
        assert body["authenticated"] is True
        assert "fb_session" in r.cookies


def test_setup_rejects_if_already_set(db):
    with make_client(db) as client:
        client.post("/api/auth/setup", json={"password": "first"})
        r = client.post("/api/auth/setup", json={"password": "second"})
        assert r.status_code == 409


def test_setup_rejects_empty_password(db):
    with make_client(db) as client:
        r = client.post("/api/auth/setup", json={"password": ""})
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


def test_login_success(db):
    with make_client(db) as client:
        client.post("/api/auth/setup", json={"password": "correct"})
        r = client.post("/api/auth/login", json={"password": "correct"})
        assert r.status_code == 200
        assert r.json()["authenticated"] is True
        assert "fb_session" in r.cookies


def test_login_wrong_password(db):
    with make_client(db) as client:
        client.post("/api/auth/setup", json={"password": "correct"})
        r = client.post("/api/auth/login", json={"password": "wrong"})
        assert r.status_code == 401


def test_login_no_password_set(db):
    with make_client(db) as client:
        r = client.post("/api/auth/login", json={"password": "anything"})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


def test_logout_clears_cookie(db):
    with make_client(db) as client:
        client.post("/api/auth/setup", json={"password": "secret"})
        r = client.post("/api/auth/logout")
        assert r.status_code == 200
        # After logout the cookie should be absent or empty
        assert r.cookies.get("fb_session", "") == ""


# ---------------------------------------------------------------------------
# require_auth dependency
# ---------------------------------------------------------------------------


def test_require_auth_blocks_without_credentials(db):
    """Protected endpoint returns 401 when not authenticated (no cookie, no token)."""
    with make_client(db) as client:
        # Set up password first (so the server is "ready")
        client.post("/api/auth/setup", json={"password": "pw"})

    # Make a new separate app/client without any stored cookies
    with make_client(db) as bare:
        # Clear any cookies that may have been set
        bare.cookies.clear()
        r = bare.get("/api/config")
        assert r.status_code == 401


def test_require_auth_bypassed_when_disabled(db):
    """With auth_enabled=false, protected endpoints are open."""
    with make_client(db, auth_enabled=False) as client:
        r = client.get("/api/config")
        assert r.status_code == 200


def test_require_auth_passes_with_valid_cookie(db):
    """A valid session cookie allows access to protected routes."""
    with make_client(db) as client:
        client.post("/api/auth/setup", json={"password": "pw"})
        # Session cookie is stored in client after setup
        r = client.get("/api/config")
        assert r.status_code == 200


def test_require_auth_passes_with_api_token(db):
    """A valid API token (when enabled) allows access."""
    # First: generate a token via an authenticated client
    with make_client(db) as client:
        client.post("/api/auth/setup", json={"password": "pw"})
        r_tok = client.post("/api/auth/api-token/regenerate")
        assert r_tok.status_code == 200
        token = r_tok.json()["api_token"]

    # Enable the token directly in DB
    set_config_value(db, "api_token_enabled", True)
    db.commit()

    # Use token via Bearer header with a fresh client (no cookies)
    with make_client(db) as bare:
        bare.cookies.clear()
        r = bare.get("/api/config", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200


def test_require_auth_passes_with_x_api_key_header(db):
    """A valid API token via X-API-Key header allows access."""
    set_config_value(db, "api_token", "mytoken123")
    set_config_value(db, "api_token_enabled", True)
    db.commit()

    with make_client(db) as bare:
        bare.cookies.clear()
        r = bare.get("/api/config", headers={"X-API-Key": "mytoken123"})
        assert r.status_code == 200


def test_require_auth_rejects_token_when_disabled(db):
    """Token auth is rejected when api_token_enabled=false."""
    set_config_value(db, "api_token", "sometoken")
    # api_token_enabled is false by default
    db.commit()

    with make_client(db) as bare:
        bare.cookies.clear()
        r = bare.get("/api/config", headers={"Authorization": "Bearer sometoken"})
        assert r.status_code == 401


def test_require_auth_rejects_wrong_token(db):
    """A wrong API token is rejected even when api_token_enabled=true."""
    set_config_value(db, "api_token", "correct-token")
    set_config_value(db, "api_token_enabled", True)
    db.commit()

    with make_client(db) as bare:
        bare.cookies.clear()
        r = bare.get("/api/config", headers={"X-API-Key": "wrong-token"})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Change password (auth required — called while cookie session is active)
# ---------------------------------------------------------------------------


def test_change_password(db):
    with make_client(db) as client:
        client.post("/api/auth/setup", json={"password": "old"})
        r = client.post(
            "/api/auth/change-password",
            json={"current_password": "old", "new_password": "new123"},
        )
        assert r.status_code == 200
        # Verify new password works
        r2 = client.post("/api/auth/login", json={"password": "new123"})
        assert r2.status_code == 200


def test_change_password_wrong_current(db):
    with make_client(db) as client:
        client.post("/api/auth/setup", json={"password": "correct"})
        r = client.post(
            "/api/auth/change-password",
            json={"current_password": "wrong", "new_password": "new"},
        )
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Security regressions: protected auth endpoints + lockout recovery
# ---------------------------------------------------------------------------


def test_api_token_regenerate_requires_auth(db):
    """SECURITY: regenerating the API token must require an authenticated session."""
    with make_client(db) as client:
        client.post("/api/auth/setup", json={"password": "pw"})  # auto-logs in
        client.cookies.clear()  # drop the session
        r = client.post("/api/auth/api-token/regenerate")
        assert r.status_code == 401


def test_change_password_requires_auth_when_enabled(db):
    """SECURITY: change-password needs a session (not just the old password) when auth is on."""
    with make_client(db) as client:
        client.post("/api/auth/setup", json={"password": "old"})
        client.cookies.clear()
        r = client.post(
            "/api/auth/change-password",
            json={"current_password": "old", "new_password": "new123"},
        )
        assert r.status_code == 401


def test_change_password_recovery_when_auth_disabled(db):
    """Lockout recovery: with AUTH_ENABLED=false a forgotten current password is not required."""
    import bcrypt

    set_config_value(
        db, "admin_password_hash", bcrypt.hashpw(b"forgotten", bcrypt.gensalt()).decode()
    )
    db.commit()
    with make_client(db, auth_enabled=False) as client:
        r = client.post(
            "/api/auth/change-password",
            json={"current_password": "", "new_password": "brandnew"},
        )
        assert r.status_code == 200
    # The new password works once auth is re-enabled.
    with make_client(db, auth_enabled=True) as client:
        r = client.post("/api/auth/login", json={"password": "brandnew"})
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# required_settings_unset
# ---------------------------------------------------------------------------


def test_required_settings_unset_includes_variant_parent_mode_when_unset(db):
    """Config includes variant_parent_mode in required_settings_unset when 'unset'."""
    # Default seed value is "unset"
    with make_client(db, auth_enabled=False) as client:
        r = client.get("/api/config")
        assert r.status_code == 200
        assert "variant_parent_mode" in r.json()["required_settings_unset"]


def test_required_settings_unset_empty_when_mode_is_set(db):
    """required_settings_unset is empty when variant_parent_mode is configured."""
    set_config_value(db, "variant_parent_mode", "promote_color")
    db.commit()
    with make_client(db, auth_enabled=False) as client:
        r = client.get("/api/config")
        assert r.status_code == 200
        assert r.json()["required_settings_unset"] == []
