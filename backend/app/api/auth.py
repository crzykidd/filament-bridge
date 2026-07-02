"""Auth router and require_auth dependency for filament-bridge.

Security model:
- Stateless signed session cookie ``fb_session`` via itsdangerous
  (TimestampSigner, max-age = mobile_session_days days when >= 1, else 30 days).
- Server secret auto-generated once and persisted in BridgeConfig ``auth_secret``.
- Password stored as bcrypt hash in BridgeConfig ``admin_password_hash``.
- Single optional API token: Bearer / X-API-Key header (constant-time compare).
- AUTH_ENABLED=false (env) fully bypasses auth — used for locked-out recovery.

Public endpoints (no auth required):
  GET  /api/auth/status
  POST /api/auth/setup   (only when password not yet set)
  POST /api/auth/login
  GET  /api/health       (mounted separately, not under auth)

Everything else under /api/* requires auth.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import time

import bcrypt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.config import get_config_value, set_config_value
from app.config import settings as _settings
from app.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# Session cookie name and default max-age (30 days in seconds). The effective
# max-age is configurable via mobile_session_days (>= 1 sets it; 0 falls back to
# this 30-day default) — see _session_max_age below.
_COOKIE_NAME = "fb_session"
_DEFAULT_COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 days
_SESSION_PAYLOAD = "admin"  # constant payload; the signature is the secret

# ---------------------------------------------------------------------------
# Login rate-limiter
# ---------------------------------------------------------------------------
# Per-IP in-memory throttle (vs. global) so that one device failing repeatedly —
# e.g. a phone with a cached wrong password — does not lock out the real admin on
# a different device. Since uvicorn is started with --proxy-headers, the ASGI
# layer resolves request.client.host from X-Forwarded-For, giving the true
# client IP behind a reverse proxy. A process restart clears all state, which is
# acceptable for a single-admin self-hosted app and is itself part of the
# documented lockout-recovery path (AUTH_ENABLED=false + restart).
#
# Throttle applies only to POST /api/auth/login and only when AUTH_ENABLED=true
# (when auth is disabled the endpoint is a no-op anyway).

_MAX_ATTEMPTS = 5       # consecutive wrong-password attempts before lockout
_LOCKOUT_SECONDS = 300  # 5-minute cooldown window; deters scripted brute force


class _ThrottleEntry:
    """Per-IP mutable failure state (module-level, reset on process restart)."""

    __slots__ = ("count", "locked_until")

    def __init__(self) -> None:
        self.count: int = 0
        self.locked_until: float = 0.0  # monotonic timestamp; 0.0 = not locked


# Maps client-IP string → _ThrottleEntry.  Reset between tests via fixture.
_throttle: dict[str, _ThrottleEntry] = {}


def _get_client_ip(request: Request) -> str:
    """Return the proxy-aware client IP string for throttle keying.

    Under uvicorn --proxy-headers the ASGI layer already resolves
    request.client.host from X-Forwarded-For, so no manual header inspection
    is needed here.  Falls back to "unknown" when request.client is None (e.g.
    during unit tests that never wire a real transport).
    """
    return (request.client.host if request.client else "unknown") or "unknown"


def _check_throttle(ip: str) -> None:
    """Raise HTTP 429 with Retry-After if ip is currently locked out."""
    entry = _throttle.get(ip)
    if entry is None:
        return
    if entry.locked_until and time.monotonic() < entry.locked_until:
        remaining = int(entry.locked_until - time.monotonic()) + 1
        raise HTTPException(
            status_code=429,
            detail={
                "code": "too_many_attempts",
                "message": (
                    f"Too many failed login attempts. "
                    f"Try again in {remaining} second{'s' if remaining != 1 else ''}."
                ),
            },
            headers={"Retry-After": str(remaining)},
        )
    # Lockout window has expired — the counter stays until the next
    # successful login or another failure rearms the lock.


def _record_failure(ip: str) -> None:
    """Increment the consecutive-failure counter; lock out ip if threshold is reached."""
    entry = _throttle.setdefault(ip, _ThrottleEntry())
    entry.count += 1
    if entry.count >= _MAX_ATTEMPTS:
        entry.locked_until = time.monotonic() + _LOCKOUT_SECONDS


def _record_success(ip: str) -> None:
    """Clear throttle state for ip on a successful login."""
    _throttle.pop(ip, None)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_or_create_auth_secret(db: Session) -> str:
    """Return the persisted auth secret, generating and saving it on first call."""
    raw = get_config_value(db, "auth_secret", None)
    if raw:
        return raw
    new_secret = secrets.token_urlsafe(32)
    set_config_value(db, "auth_secret", new_secret)
    db.commit()
    logger.info("auth_secret generated and persisted")
    return new_secret


def _make_signer(db: Session) -> TimestampSigner:
    secret = _get_or_create_auth_secret(db)
    return TimestampSigner(secret, digest_method=hashlib.sha256)


def _session_max_age(db: Session) -> int:
    """Return the fb_session cookie max-age in seconds.

    Reads mobile_session_days: when >= 1 the cookie lives that many days; 0 (the
    public-scan-flow setting) falls back to the 30-day default for any normal login.
    """
    from app.api.config import mobile_session_days

    days = mobile_session_days(db)
    if days >= 1:
        return days * 24 * 3600
    return _DEFAULT_COOKIE_MAX_AGE


def _verify_session_cookie(cookie_value: str, signer: TimestampSigner, max_age: int) -> bool:
    """Return True iff the signed cookie is valid and not older than max_age seconds."""
    try:
        payload = signer.unsign(cookie_value, max_age=max_age).decode()
        return payload == _SESSION_PAYLOAD
    except (SignatureExpired, BadSignature, Exception):
        return False


def _set_session_cookie(
    response: Response, signer: TimestampSigner, *, secure: bool, max_age: int
) -> None:
    signed = signer.sign(_SESSION_PAYLOAD).decode()
    response.set_cookie(
        key=_COOKIE_NAME,
        value=signed,
        httponly=True,
        samesite="lax",
        secure=secure,
        max_age=max_age,
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=_COOKIE_NAME, path="/")


def _is_https(request: Request) -> bool:
    """Return True iff the request is (or was forwarded as) HTTPS.

    Checks X-Forwarded-Proto first so the cookie Secure flag is correct behind a
    TLS-terminating reverse proxy (where uvicorn sees the inner http:// URL).
    Mirrors the same pattern used in labels.py:_resolve_base_url.
    """
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    return proto == "https"


# ---------------------------------------------------------------------------
# require_auth dependency
# ---------------------------------------------------------------------------


def _has_valid_credentials(
    request: Request,
    fb_session: str | None,
    db: Session,
) -> bool:
    """Return True iff the request carries valid auth (or auth is disabled).

    Shared by require_auth and the mobile-flow _mobile_auth dependency so both apply
    EXACTLY the same check:
    - AUTH_ENABLED is false (app is fully open), OR
    - a valid fb_session cookie is present, OR
    - api_token_enabled is true AND a matching Bearer/X-API-Key header is present.
    """
    if not _settings.auth_enabled:
        return True

    # --- Check session cookie ---
    if fb_session:
        signer = _make_signer(db)
        if _verify_session_cookie(fb_session, signer, _session_max_age(db)):
            return True

    # --- Check API token ---
    token_enabled = bool(get_config_value(db, "api_token_enabled", False))
    if token_enabled:
        stored_token = get_config_value(db, "api_token", None)
        if stored_token:
            incoming: str | None = None
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                incoming = auth_header[7:]
            else:
                incoming = request.headers.get("X-API-Key")
            if incoming and secrets.compare_digest(incoming, stored_token):
                return True

    return False


def require_auth(
    request: Request,
    fb_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> None:
    """FastAPI dependency: enforces authentication on protected routes.

    Passes when _has_valid_credentials is true; otherwise raises 401.
    """
    if _has_valid_credentials(request, fb_session, db):
        return
    raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "Authentication required"})


def mobile_auth(
    request: Request,
    fb_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> None:
    """Conditional auth dependency for the mobile scan flow.

    Used ONLY by the mobile + labels routers and the /r/ redirect (the three surfaces
    a cold phone scan touches). It is a strict SUBSET-OR-EQUAL of require_auth:

    - mobile_session_days == 0 → PUBLIC: return immediately, no credentials needed.
      (Just these three surfaces open up; every other router still carries require_auth.)
    - mobile_session_days >= 1 → enforce the SAME check as require_auth (session cookie
      OR API token OR AUTH_ENABLED=false), raising 401 otherwise.

    This is auth only — the separate _require_labels_enabled 403 feature gate still
    runs on every mobile/label route regardless of this value.
    """
    from app.api.config import mobile_session_days

    if mobile_session_days(db) == 0:
        return  # public scan flow
    if _has_valid_credentials(request, fb_session, db):
        return
    raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "Authentication required"})


# ---------------------------------------------------------------------------
# Request/response schemas
# ---------------------------------------------------------------------------


class AuthStatusResponse(BaseModel):
    auth_enabled: bool
    password_set: bool
    authenticated: bool
    api_token_enabled: bool


class SetupRequest(BaseModel):
    password: str


class LoginRequest(BaseModel):
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class TokenResponse(BaseModel):
    api_token: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/status", response_model=AuthStatusResponse)
def auth_status(
    request: Request,
    fb_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> AuthStatusResponse:
    """Public — returns auth state so the frontend can choose setup/login/app."""
    password_hash = get_config_value(db, "admin_password_hash", None)
    password_set = bool(password_hash)
    api_token_enabled = bool(get_config_value(db, "api_token_enabled", False))

    authenticated = False
    if not _settings.auth_enabled:
        # When auth is disabled the user is always "in"
        authenticated = True
    elif fb_session:
        signer = _make_signer(db)
        authenticated = _verify_session_cookie(fb_session, signer, _session_max_age(db))

    return AuthStatusResponse(
        auth_enabled=_settings.auth_enabled,
        password_set=password_set,
        authenticated=authenticated,
        api_token_enabled=api_token_enabled,
    )


@router.post("/setup", status_code=200)
def auth_setup(
    payload: SetupRequest,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
) -> AuthStatusResponse:
    """Public — sets the admin password when none is set yet.

    Returns 409 if a password already exists so callers know to use /login instead.
    """
    existing_hash = get_config_value(db, "admin_password_hash", None)
    if existing_hash:
        raise HTTPException(
            status_code=409,
            detail={"code": "password_already_set", "message": "Password already configured. Use /auth/change-password."},
        )
    if not payload.password:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_password", "message": "Password must not be empty."},
        )

    hashed = bcrypt.hashpw(payload.password.encode(), bcrypt.gensalt()).decode()
    set_config_value(db, "admin_password_hash", hashed)
    db.commit()

    # Set session cookie so the user is immediately logged in after setup
    signer = _make_signer(db)
    _set_session_cookie(
        response, signer, secure=_is_https(request), max_age=_session_max_age(db)
    )

    return AuthStatusResponse(
        auth_enabled=_settings.auth_enabled,
        password_set=True,
        authenticated=True,
        api_token_enabled=bool(get_config_value(db, "api_token_enabled", False)),
    )


@router.post("/login", status_code=200)
def auth_login(
    payload: LoginRequest,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
) -> AuthStatusResponse:
    """Public — verify password; set session cookie on success."""
    # Per-IP rate-limit: skip entirely when AUTH_ENABLED=false (login is a no-op anyway).
    client_ip: str | None = None
    if _settings.auth_enabled:
        client_ip = _get_client_ip(request)
        _check_throttle(client_ip)  # raises 429 if locked out

    stored_hash = get_config_value(db, "admin_password_hash", None)
    if not stored_hash:
        raise HTTPException(
            status_code=401,
            detail={"code": "no_password_set", "message": "No password configured. Use /auth/setup first."},
        )

    # bcrypt.checkpw naturally provides the constant-time compare and work factor
    if not bcrypt.checkpw(payload.password.encode(), stored_hash.encode()):
        if client_ip is not None:
            _record_failure(client_ip)  # increment counter; may arm the lockout
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_credentials", "message": "Invalid password."},
        )

    if client_ip is not None:
        _record_success(client_ip)  # clear counter on successful login

    signer = _make_signer(db)
    _set_session_cookie(
        response, signer, secure=_is_https(request), max_age=_session_max_age(db)
    )

    return AuthStatusResponse(
        auth_enabled=_settings.auth_enabled,
        password_set=True,
        authenticated=True,
        api_token_enabled=bool(get_config_value(db, "api_token_enabled", False)),
    )


@router.post("/logout", status_code=200)
def auth_logout(response: Response) -> dict:
    """Clear the session cookie."""
    _clear_session_cookie(response)
    return {"ok": True}


@router.post("/change-password", status_code=200, dependencies=[Depends(require_auth)])
def auth_change_password(
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Set a new admin password.

    Requires an authenticated session (require_auth) when AUTH_ENABLED is true, and
    additionally verifies the current password. When AUTH_ENABLED is false the app is
    already open (require_auth is bypassed) and the current-password check is skipped —
    this is the documented lockout-recovery path for a forgotten password.
    """
    stored_hash = get_config_value(db, "admin_password_hash", None)

    if _settings.auth_enabled:
        if not stored_hash:
            raise HTTPException(
                status_code=400,
                detail={"code": "no_password_set", "message": "No password configured yet."},
            )
        if not bcrypt.checkpw(payload.current_password.encode(), stored_hash.encode()):
            raise HTTPException(
                status_code=401,
                detail={"code": "invalid_credentials", "message": "Current password is incorrect."},
            )

    if not payload.new_password:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_password", "message": "New password must not be empty."},
        )

    new_hash = bcrypt.hashpw(payload.new_password.encode(), bcrypt.gensalt()).decode()
    set_config_value(db, "admin_password_hash", new_hash)
    db.commit()
    return {"ok": True}


@router.post("/api-token/regenerate", status_code=200, dependencies=[Depends(require_auth)])
def auth_api_token_regenerate(db: Session = Depends(get_db)) -> TokenResponse:
    """AUTH REQUIRED — generate a new API token and persist it."""
    new_token = secrets.token_urlsafe(32)
    set_config_value(db, "api_token", new_token)
    db.commit()
    return TokenResponse(api_token=new_token)
