"""Auth router and require_auth dependency for filament-bridge.

Security model:
- Stateless signed session cookie ``fb_session`` via itsdangerous
  (TimestampSigner, max-age 30 days).
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

# Session cookie name and max-age (30 days in seconds)
_COOKIE_NAME = "fb_session"
_COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 days
_SESSION_PAYLOAD = "admin"  # constant payload; the signature is the secret


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


def _verify_session_cookie(cookie_value: str, signer: TimestampSigner) -> bool:
    """Return True iff the signed cookie is valid and not expired."""
    try:
        payload = signer.unsign(cookie_value, max_age=_COOKIE_MAX_AGE).decode()
        return payload == _SESSION_PAYLOAD
    except (SignatureExpired, BadSignature, Exception):
        return False


def _set_session_cookie(response: Response, signer: TimestampSigner, *, secure: bool) -> None:
    signed = signer.sign(_SESSION_PAYLOAD).decode()
    response.set_cookie(
        key=_COOKIE_NAME,
        value=signed,
        httponly=True,
        samesite="lax",
        secure=secure,
        max_age=_COOKIE_MAX_AGE,
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=_COOKIE_NAME, path="/")


def _is_https(request: Request) -> bool:
    return request.url.scheme == "https"


# ---------------------------------------------------------------------------
# require_auth dependency
# ---------------------------------------------------------------------------


def require_auth(
    request: Request,
    fb_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> None:
    """FastAPI dependency: enforces authentication on protected routes.

    Passes when any of:
    - AUTH_ENABLED is false (app is fully open)
    - A valid fb_session cookie is present
    - api_token_enabled is true AND a matching Bearer/X-API-Key header is present
    Otherwise raises 401.
    """
    if not _settings.auth_enabled:
        return

    # --- Check session cookie ---
    if fb_session:
        signer = _make_signer(db)
        if _verify_session_cookie(fb_session, signer):
            return

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
        authenticated = _verify_session_cookie(fb_session, signer)

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
    _set_session_cookie(response, signer, secure=_is_https(request))

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
    stored_hash = get_config_value(db, "admin_password_hash", None)
    if not stored_hash:
        raise HTTPException(
            status_code=401,
            detail={"code": "no_password_set", "message": "No password configured. Use /auth/setup first."},
        )

    # bcrypt.checkpw naturally provides the constant-time compare and work factor
    if not bcrypt.checkpw(payload.password.encode(), stored_hash.encode()):
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_credentials", "message": "Invalid password."},
        )

    signer = _make_signer(db)
    _set_session_cookie(response, signer, secure=_is_https(request))

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
