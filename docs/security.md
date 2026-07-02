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
   `TimestampSigner`-signed payload. The cookie is marked `Secure` when the request is
   HTTPS — determined from `X-Forwarded-Proto` if present, else the request scheme (see
   [Reverse proxy and TLS](#reverse-proxy-and-tls); LAN deployments commonly use plain
   HTTP, where the cookie is correctly not `Secure`).
4. Sessions are **stateless** — there is no sessions table or migration. The server
   validates the signature and checks max-age on every request. The lifetime is
   **configurable via `mobile_session_days`**: when `>= 1` the cookie lives that many
   days; when `0` (the default is `30`) it falls back to a **30-day** default. See the
   [Mobile scan flow](#mobile-scan-flow-and-public-mode) section for what `0` also does.
5. The signing secret (`auth_secret`) is auto-generated on first startup and persisted
   in `BridgeConfig` so sessions survive container restarts.
6. `POST /api/auth/logout` clears the cookie and is itself public (no session needed).

## Protected routes

All `/api/*` routes require authentication (the global `require_auth` dependency)
**except** the following always-public endpoints:
- `GET /api/health`
- `GET /api/version`
- `GET /api/auth/status`
- `POST /api/auth/login`
- `POST /api/auth/setup`
- `POST /api/auth/logout`

The React SPA (`/`, `/assets/*`, and all client-side routes) is always public — the
frontend renders the login/setup screen itself.

A third group — the **mobile scan flow** (`/api/mobile/*`, `/api/labels/*`, and the
`GET /r/{fil}/{spool}` QR redirect) — carries a *conditional* `mobile_auth` dependency
instead of `require_auth`. It enforces the same check as every other protected route
**unless `mobile_session_days` is `0`**, in which case those three surfaces become
public. See the next section — this is the one place authentication can be relaxed for
write-capable endpoints, so understand it before enabling it.

## Mobile scan flow and public mode

The mobile-updates & labels feature (off by default; gated by `mobile_labels_enabled`)
is built so a phone can scan a spool's QR label and update it without a login. The auth
behavior is governed by `mobile_session_days`:

- **`mobile_session_days >= 1` (default `30`)** — the scan flow requires the normal app
  login, exactly like the rest of the app. No auth is relaxed.
- **`mobile_session_days = 0`** — the scan flow is **public**: `/api/mobile/*`,
  `/api/labels/*`, and `/r/{fil}/{spool}` skip the app password entirely. The rest of the
  app stays gated. (The `mobile_labels_enabled` 403 feature gate still applies — the
  feature must also be turned on for anything to be reachable at all.)

When public mode is enabled, anyone who can reach the port can, **without
authenticating**, on already-mapped spools:

- update spool weight (writing a usage entry to Filament DB and/or Spoolman) and change
  its storage location (`PATCH /api/mobile/spool/{fil}/{spool}`),
- change printer-slot (AMS/MMU) assignments (`PUT`/`DELETE .../assignment`),
- log dry-cycle records (`POST .../dry-cycle`),
- enumerate the mapped inventory, vendors, colors, locations, and printers
  (`GET /api/mobile/spools`, `/locations`, `/printers`),
- trigger a physical label print on the configured LabelForge printer
  (`POST /api/labels/print`).

These endpoints cannot delete records and only touch spools the bridge already maps, so
the blast radius is bounded — but the writes are real. **Only enable `mobile_session_days
= 0` when the bridge is reachable only from a trusted LAN** (or otherwise not exposed to
the internet). If the bridge is internet-facing, keep `mobile_session_days >= 1` so the
scan flow still requires the login.

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

## Login rate-limiting

`POST /api/auth/login` is protected by a per-IP in-memory rate-limiter:

- **Threshold:** after **5 consecutive wrong-password attempts** from the same client IP,
  the endpoint returns **HTTP 429** with a `Retry-After` header and the detail code
  `too_many_attempts`. The correct password is also rejected during the cooldown window.
- **Cooldown:** **5 minutes** from the moment the threshold is crossed.
- **Reset on success:** a correct password before the threshold clears the counter for
  that IP, so an honest user who mistyped a few times is not penalized.
- **Per-IP scope:** tracking is per client IP (resolved from `X-Forwarded-For` when
  behind a reverse proxy, via uvicorn `--proxy-headers`), so one device failing
  repeatedly does not lock out the admin on a different device.
- **In-memory only:** state lives in the Python process — a container restart clears it.
  This is intentional: a restart is itself part of the documented lockout-recovery path
  (`AUTH_ENABLED=false` + restart).
- **Skipped when `AUTH_ENABLED=false`:** when auth is disabled globally, the throttle
  is not applied (the endpoint is a no-op in that mode anyway).

## Crypto choices

| Concern | Choice | Rationale |
|---|---|---|
| Session integrity | itsdangerous `TimestampSigner` (HMAC-SHA256) | Ships with Starlette; signed cookie expires via a configurable max-age (`mobile_session_days` days, default 30) |
| Password hashing | bcrypt (cost=12, auto-generated salt) | Industry standard for password storage; intentionally slow |
| Secret generation | `secrets.token_urlsafe(32)` | Python stdlib CSPRNG |
| Token comparison | `secrets.compare_digest` | Constant-time to prevent timing attacks |

## Backup export and secrets

Backup exports (`GET /api/backup/export` and the nightly on-disk job) **deliberately
exclude** auth secrets: `auth_secret`, `admin_password_hash`, `api_token`, and
`labelforge_token` are never written to the exported file. Import (`POST /api/backup/import`)
likewise silently ignores any of those keys if they appear in the payload.

This means a restored backup keeps the **target instance's own credentials** — an exported
file is not a credential dump, and a crafted backup cannot overwrite the admin password or
session-signing key. If you are migrating to a new host and want to carry over the admin
password and API token, reset them via Settings after the restore.

## Reverse proxy and TLS

A reverse proxy is **not required**. There are two supported deployment shapes:

- **LAN-only, plain HTTP (no proxy)** — Access the container directly over `http://`
  (e.g. `http://nas:8090`). Everything works as-is; the `fb_session` cookie is issued
  without the `Secure` attribute, which is correct for a plaintext channel. This is a fine
  setup for a purely local homelab that isn't exposed to the internet.
- **Behind a TLS-terminating reverse proxy or tunnel (recommended for any internet or
  HTTPS exposure)** — Nginx, Caddy, **Traefik**, a **Cloudflare Tunnel**, etc. terminate
  TLS and forward to the bridge over http. As long as they set `X-Forwarded-Proto: https`
  (Traefik and Cloudflare both do by default), the cookie correctly gets `Secure=true`.

**Proxy-header trust** — Uvicorn is started with `--proxy-headers --forwarded-allow-ips=*`
so `request.url.scheme`, client IP, and Host are derived from the forwarded headers rather
than the inner plaintext connection. The app also reads `X-Forwarded-Proto` directly when
determining the `Secure` attribute on the `fb_session` cookie. Because forwarded headers
are trusted from any immediate peer, **do not publish port 8090 directly to the internet**
alongside the proxy — a client reaching the port directly could set
`X-Forwarded-Proto: https` and receive a Secure cookie over a plain channel. With a proxy
or tunnel as the only ingress (the normal setup — proxy on the same host, same Docker
network, or a Cloudflare Tunnel), this is not a concern, because the proxy overwrites the
forwarded headers itself. A LAN-only deployment with no ingress from the internet is also
unaffected.

**Response security headers** — The bridge adds the following headers to every response:

| Header | Value | Purpose |
|---|---|---|
| `X-Content-Type-Options` | `nosniff` | Prevent MIME-type sniffing |
| `X-Frame-Options` | `DENY` | Block clickjacking (no iframes in the SPA) |
| `Referrer-Policy` | `same-origin` | Avoid leaking URLs to external origins (Filament DB, Spoolman) |

`Content-Security-Policy` and `Strict-Transport-Security` are **intentionally not set by
the bridge** — CSP for the Vite/React SPA + react-markdown docs viewer needs care and
should be tuned at the proxy; HSTS is harmful on plain-http LAN deployments and belongs
at the TLS terminator.

## What is NOT implemented

- Multi-user support
- Password reset tokens / email flow
- Signed HTTPS enforcement (LAN deployment assumption)
- CSRF protection (SameSite=Lax cookie + JSON-only API mitigate standard CSRF)
