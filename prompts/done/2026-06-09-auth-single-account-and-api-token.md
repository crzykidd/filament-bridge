---
name: 2026-06-09-auth-single-account-and-api-token
status: completed
created: 2026-06-09
model: sonnet
completed: 2026-06-09
result: Implemented. 20/20 auth tests pass, 780/780 total backend tests pass, frontend build clean.
---

# Task: Single-account auth + API token + first-login required-settings flow

Add a security layer to filament-bridge (currently fully open). Three coupled pieces:
A) single-account user auth (admin password), B) a single API token, C) a first-login
"required settings" gate. Security-sensitive — follow the prescribed design exactly; do NOT
improvise the crypto or the protected-route logic. Planned in an Opus session 2026-06-09.

## Working tree note
Repo root has pre-existing untracked dotfiles (.bashrc/.gitconfig/.idea/.mcp.json/.claude/* etc.)
and an unrelated uncommitted `docker-compose.dev.yml` (a `/data` path tweak) — IGNORE all of those,
never stage them. Run `git status --porcelain` first.

## Decisions already made (do not change)

- **Mechanism:** stateless signed session cookie. On login, sign a small payload (e.g. `"admin"` +
  issued-at) with `itsdangerous` (a Starlette dependency — confirm it's importable; it is) using a
  server secret. Set it as an **httpOnly, SameSite=Lax** cookie named `fb_session` (mark `Secure`
  only when the request is https — don't hard-require https since this runs on a LAN). Validate
  signature + max-age (e.g. 30 days) on each protected request. Logout clears the cookie. No
  sessions table, no migration.
- **Server secret:** auto-generate once (`secrets.token_urlsafe(32)`) and persist in `BridgeConfig`
  as `auth_secret` so sessions survive restarts. Never log it.
- **Password hashing:** `bcrypt` (add `bcrypt` to `backend/requirements.txt`). Store ONLY the hash,
  in `BridgeConfig` key `admin_password_hash`. Never store or log the plaintext.
- **Enable flag:** env `AUTH_ENABLED` (bool, default **true**) on `Settings` in `backend/app/config.py`.
  When false, auth is fully bypassed (open app) — the dependency returns immediately.
- **Password-reset model (document it):** there is NO in-app reset. If locked out, the user sets
  `AUTH_ENABLED=false` in `.env`, restarts, changes the password in Settings, then re-enables. No
  reset token.
- **API token:** a single token. Stored in `BridgeConfig`: `api_token` (the value — stored so
  Settings can DISPLAY it; this is an intentional tradeoff for a self-hosted single-user app) and
  `api_token_enabled` (bool, default false). When enabled, a request authenticates if it carries
  `Authorization: Bearer <token>` OR `X-API-Key: <token>` matching `api_token` (constant-time
  compare via `secrets.compare_digest`). The token is an ALTERNATIVE credential to the session
  cookie for `/api/*`.

## A — Backend auth

1. **New router `backend/app/api/auth.py`** (mounted under `/api` in `main.py`). Endpoints:
   - `GET /api/auth/status` (PUBLIC) → `{auth_enabled, password_set, authenticated, api_token_enabled}`.
     `password_set` = admin_password_hash present. Frontend uses this to choose setup/login/in.
   - `POST /api/auth/setup` (PUBLIC, allowed ONLY when `password_set` is false) → body `{password}`;
     sets `admin_password_hash`. Rejects (409) if a password is already set.
   - `POST /api/auth/login` (PUBLIC) → body `{password}`; bcrypt-verify against `admin_password_hash`;
     on success set the `fb_session` cookie; 401 on failure. Add a small fixed delay or rely on
     bcrypt cost to blunt brute force (don't build a lockout — out of scope).
   - `POST /api/auth/logout` → clear cookie.
   - `POST /api/auth/change-password` (AUTH REQUIRED) → `{current_password, new_password}`; verify
     current, set new hash.
   - `POST /api/auth/api-token/regenerate` (AUTH REQUIRED) → generate `secrets.token_urlsafe(32)`,
     store in `api_token`, return it.
   - API-token enable/disable + reading the token value flow through the existing
     `PUT /api/config` + `GET /api/config` (add `api_token`, `api_token_enabled` to ConfigResponse /
     ConfigUpdateRequest) — OR expose on the auth router; pick one and be consistent. Reading the
     token requires auth.

2. **Enforcement.** Add a FastAPI dependency `require_auth` (in `auth.py`) applied to all `/api/*`
   routers EXCEPT the PUBLIC set: `/api/health`, `/api/auth/status`, `/api/auth/login`,
   `/api/auth/setup`. `require_auth` passes when: `AUTH_ENABLED` is false; OR a valid `fb_session`
   cookie; OR (`api_token_enabled` and a matching Bearer/X-API-Key). Otherwise 401. Apply it via
   `dependencies=[Depends(require_auth)]` on each protected `include_router(...)` in `main.py` (or a
   router-level dependency) — keep `/api/health` and the auth public endpoints open. The SPA static
   files and `/` stay public (the frontend renders the login screen itself).

3. Add `AUTH_ENABLED` to `config.py`, and `admin_password_hash` / `auth_secret` / `api_token` /
   `api_token_enabled` to `BridgeConfig` `_DEFAULTS` (sensible defaults: empty / false). Do NOT
   expose `admin_password_hash` or `auth_secret` in any API response.

## B — Frontend auth

- **Auth gate in `App.tsx`:** on load, call `GET /api/auth/status`. If `auth_enabled` and not
  `authenticated`: render a **Login** page (or a **Setup** page when `!password_set`) instead of the
  router. After login/setup succeeds, proceed to the app. Add a logout control (in the sidebar
  footer near Settings, or a small header menu).
- **Login page** (`frontend/src/pages/Login.tsx`): password field → `POST /api/auth/login`; on
  success reload/enter app. **Setup mode**: when `!password_set`, show "Set admin password"
  (password + confirm) → `POST /api/auth/setup`.
- **API client:** ensure fetch includes credentials (cookies) — set `credentials: 'include'` on the
  api wrapper. On any 401 from the API, drop back to the login screen.
- **Settings → Security section:** change-password form; API token controls (enable/disable toggle,
  show the token with a copy button, regenerate button). Only meaningful when auth is enabled.

## C — First-login required-settings flow

- Backend: add `required_settings_unset` to the config/status response — a list of required setting
  keys that are currently unset. For now the required set is **`variant_parent_mode`** (it defaults
  to `unset`); structure it as a list so we can add more later.
- Frontend: after the user is authenticated (or always, if auth disabled), if
  `required_settings_unset` is non-empty, **redirect to `/settings`** and show a modal/popup:
  "The following settings must be set before you can use the bridge: <list>." Dismissible only by
  setting them (or a "later" that re-prompts). Keep it simple: a modal listing the unset required
  settings with a note to set them on this page.

## Conventions / tests / done

- Backend tests (`cd backend && python3 -m pytest`, use python3): cover status/setup/login/logout,
  change-password, the `require_auth` dependency (bypassed when AUTH_ENABLED=false; 401 without
  creds; 200 with cookie; 200 with valid API token when enabled; 401 with token when disabled),
  and `required_settings_unset` reporting variant_parent_mode. Use a test secret/hash; never assert
  on plaintext.
- Frontend: `cd frontend && npm run build`; report result.
- Update `CHANGELOG.md` `[Unreleased]`, `CLAUDE.md` (new env vars `AUTH_ENABLED`; new runtime
  settings `api_token` / `api_token_enabled`; the reset-via-env note), and add a short
  `docs/security.md` describing the auth model, the API token, and the lockout-recovery procedure.
- `bcrypt` added to `requirements.txt` (and the Docker build will pick it up — no Dockerfile change
  needed unless deps are pinned elsewhere; check).
- Commit prefix `feat:`. No `Co-authored-by:`. Branch `dev`, never `main`, never push.
- When done: frontmatter → completed; `git mv` to `prompts/done/`; record decisions in
  `docs/decisions.md`. DO NOT `git commit` — leave changes in the working tree and report back:
  file list, proposed commit message, backend test results, frontend build result, and any security
  considerations or deferrals. (The orchestrator will review the auth code and commit.)
