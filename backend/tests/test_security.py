"""Tests for security hardening: proxy-aware Secure cookie flag + security headers.

Covers:
- _is_https(request) honors X-Forwarded-Proto (the load-bearing in-app fix; uvicorn
  --proxy-headers is a server-layer setting that TestClient does not exercise).
- POST /api/auth/login with X-Forwarded-Proto: https → Set-Cookie has Secure attribute.
- POST /api/auth/login without the header (plain http) → Set-Cookie does NOT have Secure.
- Security headers (X-Content-Type-Options, X-Frame-Options, Referrer-Policy) are present
  on responses and are not overwritten by headers a route already set.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app.api import auth as auth_module
from app.api import config as config_module
from app.api.auth import _is_https
from app.db import Base, get_db
from app.models.config import seed_defaults


# ---------------------------------------------------------------------------
# Fixtures
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
    return ms


@contextmanager
def make_auth_client(db, auth_enabled: bool = True):
    """Minimal TestClient with just the auth router — mirrors test_auth.py pattern."""
    ms = _mock_settings(auth_enabled)
    with patch.object(auth_module, "_settings", ms), \
         patch.object(config_module, "_settings", ms):

        mini = FastAPI()
        mini.dependency_overrides[get_db] = lambda: db
        mini.include_router(auth_module.router, prefix="/api")

        with TestClient(mini, raise_server_exceptions=True, base_url="http://testserver") as client:
            yield client


# ---------------------------------------------------------------------------
# _is_https unit tests
# ---------------------------------------------------------------------------


class TestIsHttps:
    """Unit tests for _is_https — the load-bearing fix for the proxy Secure-flag bug."""

    def _make_request(self, scheme: str = "http", forwarded_proto: str | None = None):
        """Build a minimal Starlette Request with the given scheme and optional header."""
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": [],
            "server": ("testserver", 80),
        }
        if forwarded_proto is not None:
            scope["headers"] = [(b"x-forwarded-proto", forwarded_proto.encode())]
        scope["scheme"] = scheme
        return Request(scope)

    def test_plain_http_no_header_is_not_https(self):
        req = self._make_request(scheme="http")
        assert _is_https(req) is False

    def test_direct_https_scheme_is_https(self):
        req = self._make_request(scheme="https")
        assert _is_https(req) is True

    def test_forwarded_proto_https_overrides_http_scheme(self):
        """Primary fix: proxy sets X-Forwarded-Proto: https; uvicorn sees http."""
        req = self._make_request(scheme="http", forwarded_proto="https")
        assert _is_https(req) is True

    def test_forwarded_proto_http_on_https_scheme(self):
        """If proxy says http (unusual), believe the header."""
        req = self._make_request(scheme="https", forwarded_proto="http")
        assert _is_https(req) is False

    def test_forwarded_proto_empty_falls_back_to_scheme(self):
        """An empty X-Forwarded-Proto header should fall back to the URL scheme."""
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": [(b"x-forwarded-proto", b"")],
            "server": ("testserver", 80),
            "scheme": "http",
        }
        req = Request(scope)
        assert _is_https(req) is False


# ---------------------------------------------------------------------------
# Secure cookie attribute via login endpoint
# ---------------------------------------------------------------------------


class TestSecureCookieFlag:
    """Login sets Secure on the fb_session cookie iff X-Forwarded-Proto is https."""

    def _setup_password(self, client, password: str = "pw") -> None:
        r = client.post("/api/auth/setup", json={"password": password})
        assert r.status_code == 200

    def _set_cookie_header(self, response) -> str:
        """Return the raw Set-Cookie header value (case-insensitive key lookup)."""
        # httpx exposes headers as a case-insensitive multi-dict; there may be
        # multiple Set-Cookie entries but we only set one fb_session cookie.
        return response.headers.get("set-cookie", "")

    def test_login_with_forwarded_https_sets_secure(self, db):
        with make_auth_client(db) as client:
            self._setup_password(client)
            r = client.post(
                "/api/auth/login",
                json={"password": "pw"},
                headers={"X-Forwarded-Proto": "https"},
            )
        assert r.status_code == 200
        cookie_hdr = self._set_cookie_header(r)
        assert "fb_session" in cookie_hdr, "Expected fb_session cookie in response"
        # Starlette writes '; Secure' (capital S) when secure=True
        assert "; Secure" in cookie_hdr, (
            "Expected 'Secure' attribute when X-Forwarded-Proto: https is set"
        )

    def test_login_without_forwarded_proto_no_secure(self, db):
        """Plain http (no proxy header) → cookie must NOT be Secure."""
        with make_auth_client(db) as client:
            self._setup_password(client)
            # TestClient base_url is http://testserver — no proxy header → http
            r = client.post("/api/auth/login", json={"password": "pw"})
        assert r.status_code == 200
        cookie_hdr = self._set_cookie_header(r)
        assert "fb_session" in cookie_hdr, "Expected fb_session cookie in response"
        assert "; Secure" not in cookie_hdr, (
            "Did NOT expect 'Secure' attribute on plain-http request (no X-Forwarded-Proto)"
        )

    def test_setup_with_forwarded_https_sets_secure(self, db):
        """POST /auth/setup also sets the cookie; verify Secure flag applies there too."""
        with make_auth_client(db) as client:
            r = client.post(
                "/api/auth/setup",
                json={"password": "pw"},
                headers={"X-Forwarded-Proto": "https"},
            )
        assert r.status_code == 200
        cookie_hdr = self._set_cookie_header(r)
        assert "; Secure" in cookie_hdr


# ---------------------------------------------------------------------------
# Security headers middleware
# ---------------------------------------------------------------------------


def _make_headers_app():
    """Tiny FastAPI app with the same security-headers middleware as app.main.

    Defined inline to avoid importing app.main (which triggers lifespan / DB init).
    The middleware logic is kept in sync with app/main.py:_security_headers — if
    that function changes, this helper must be updated to match.
    """
    _app = FastAPI()

    @_app.middleware("http")
    async def _security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    @_app.get("/ping")
    def ping():
        return {"ok": True}

    @_app.get("/custom-frame")
    def custom_frame():
        """Route that explicitly sets X-Frame-Options to verify setdefault doesn't clobber."""
        return JSONResponse({"ok": True}, headers={"X-Frame-Options": "SAMEORIGIN"})

    return _app


class TestSecurityHeaders:
    """Security headers are injected on every response and do not clobber existing headers."""

    def test_x_content_type_options_nosniff(self):
        with TestClient(_make_headers_app()) as client:
            r = client.get("/ping")
        assert r.headers.get("x-content-type-options") == "nosniff"

    def test_x_frame_options_deny(self):
        with TestClient(_make_headers_app()) as client:
            r = client.get("/ping")
        assert r.headers.get("x-frame-options") == "DENY"

    def test_referrer_policy_same_origin(self):
        with TestClient(_make_headers_app()) as client:
            r = client.get("/ping")
        assert r.headers.get("referrer-policy") == "same-origin"

    def test_setdefault_does_not_clobber_existing_header(self):
        """A route that already sets X-Frame-Options keeps its own value."""
        with TestClient(_make_headers_app()) as client:
            r = client.get("/custom-frame")
        assert r.headers.get("x-frame-options") == "SAMEORIGIN"
