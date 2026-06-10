# Security model

filament-bridge is designed for self-hosted LAN use. Its security layer is
intentionally minimal — single-account, no roles, no multi-user support.

## Auth overview

Authentication is controlled by the `AUTH_ENABLED` environment variable
(default `true`). When disabled, the app is fully open.

When enabled:

1. On first visit the frontend detects no password is set and shows a **Setup** screen.
2. The user sets an admin password. The backend stores only the bcrypt hash in
   `BridgeConfig` (`admin_password_hash` key). Plaintext is never stored or logged.
3. Subsequent visits show a **Login** screen. On success the backend sets an
   httpOnly, SameSite=Lax cookie named `fb_session` containing an itsdangerous
   `TimestampSigner`-signed payload. The cookie is marked `Secure` only when the
   request arrives over HTTPS (LAN deployments commonly use plain HTTP).
4. Sessions are **stateless** — there is no sessions table or migration. The server
   validates the signature and checks max-age (30 days) on every request.
5. The signing secret (`auth_secret`) is auto-generated on first startup and persisted
   in `BridgeConfig` so sessions survive container restarts.

## Protected routes

All `/api/*` routes require authentication **except**:
- `GET /api/health`
- `GET /api/auth/status`
- `POST /api/auth/login`
- `POST /api/auth/setup`

The React SPA (`/`, `/assets/*`, and all client-side routes) is always public — the
frontend renders the login/setup screen itself.

## API token

An optional single API token enables machine access (CI, Moonraker, scripts):

- **Enable:** Settings → Security → Generate token → toggle enabled.
- **Use:** send `Authorization: Bearer <token>` or `X-API-Key: <token>` on any
  protected `/api/*` request.
- **Validation:** constant-time compare via `secrets.compare_digest`.
- The token value is stored in `BridgeConfig` (`api_token`) and displayed (masked)
  in the Security section of Settings so users can copy it. This is an intentional
  tradeoff for a single-user self-hosted app — the token is no more secret than the
  database file itself.
- Tokens do not expire automatically. Use **Regenerate token** to rotate.

## Lockout recovery

There is no in-app password reset. If locked out:

1. Set `AUTH_ENABLED=false` in your environment (`.env` file or Docker env).
2. Restart the container.
3. Open the app (auth bypassed), go to **Settings → Security**, set a new password.
   While `AUTH_ENABLED=false` the change-password endpoint does **not** require the
   old password — that's what makes recovery from a *forgotten* password possible.
4. Restore `AUTH_ENABLED=true` and restart again.

Note: `change-password` and `api-token/regenerate` require an authenticated session
when `AUTH_ENABLED=true` (a known current password alone is not sufficient).

## Crypto choices

| Concern | Choice | Rationale |
|---|---|---|
| Session integrity | itsdangerous `TimestampSigner` (HMAC-SHA256) | Ships with Starlette; signed cookie expires via 30-day max-age |
| Password hashing | bcrypt (cost=12, auto-generated salt) | Industry standard for password storage; intentionally slow |
| Secret generation | `secrets.token_urlsafe(32)` | Python stdlib CSPRNG |
| Token comparison | `secrets.compare_digest` | Constant-time to prevent timing attacks |

## What is NOT implemented

- Multi-user support
- Password reset tokens / email flow
- Account lockout after failed attempts (bcrypt cost blunts brute force)
- Signed HTTPS enforcement (LAN deployment assumption)
- CSRF protection (SameSite=Lax cookie + JSON-only API mitigate standard CSRF)
