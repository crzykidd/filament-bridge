---
name: 2026-06-24-mobile-scan-auth
status: done
created: 2026-06-24
model: sonnet
completed: 2026-06-24
result: >
  Added the runtime setting mobile_session_days (int, default 30). 0 = the scan
  flow (/r/ redirect, /api/mobile/*, /api/labels/*, SPA /scan/:filId/:spoolId) is
  public; >= 1 = it requires the normal login and the fb_session cookie lives that
  many days. Re-wired the mobile + labels routers and the /r/ redirect off the
  global require_auth onto a new conditional mobile_auth dep (public only at days==0,
  else the exact same check as require_auth via a shared _has_valid_credentials
  helper); no other router changed. Cookie max-age now reads the setting. Exposed
  mobile_public on GET /api/version; App.tsx renders /scan without login only when
  mobile_public. Settings gained a "Scan login (days)" field. Backend 1262 → 1285,
  frontend 124 → 129; ruff + tsc + build clean.
---

# Task: Configurable mobile-scan auth (`mobile_session_days`)

The "Mobile updates & labels" feature mirrors the app's auth. When the app has a password set,
a cold phone scanning a QR label has no session and gets **access denied**. Add a setting that lets
the user open the scan flow (or keep it gated) and control the session lifetime.

## Decision (implement exactly)
New runtime setting **`mobile_session_days`** (integer, **default 30**):
- **`0`** → the mobile scan flow **bypasses the app password** (public): the `GET /r/{fil}/{spool}`
  redirect, the `/api/mobile/*` and `/api/labels/*` endpoints, **and** the frontend `/scan/:filId/:spoolId`
  route render/run WITHOUT auth. (The rest of the app stays password-protected.)
- **`>= 1`** → the mobile scan flow requires the normal app login (session cookie / API token, exactly
  as today), AND the login session cookie's lifetime is set to **`mobile_session_days` days**
  (today it's hard-coded 30 — make it read this setting; `0` falls back to a 30-day cookie for any
  non-mobile login). Default `30` ⇒ **no behavior change** from today.

This is independent of the existing `mobile_labels_enabled` master toggle (which still 403s every
mobile/label endpoint + hides the nav when off). Feature-gate first, then auth.

## Before you start
- Read `app/api/auth.py` (`require_auth`, the `fb_session` cookie set/verify + its hard-coded 30-day
  `max_age`), `app/main.py` (how `mobile`/`labels` routers + the `/r/` redirect are included — they
  currently carry the global `_auth_dep`; the SPA catch-all order), `app/api/mobile.py`
  (`_require_labels_enabled`), `app/api/config.py` + `models/config.py` (the `backup_*` / mobile
  config pattern), `app/api/version.py` (it already exposes `mobile_labels_enabled`).
- Frontend: `src/App.tsx` (the global gate at ~line 82 that renders `<Login/>` when
  `auth_enabled && !authenticated`), how it reads `/api/version`, `src/pages/Settings.tsx` (the
  "Mobile & Labels" section), `src/api/types.ts`.
- Honor `code-checkin-and-pr`: worktree off `dev`, `feat:` prefix, no `Co-authored-by:`. UNATTENDED.

## What to do

### Backend
1. **Config** (`config.py` env + `models/config.py` `_DEFAULTS` + `ConfigResponse`/`ConfigUpdateRequest`
   + `_config_response`, the `backup_*` pattern): `mobile_session_days: int = 30`, env
   `MOBILE_SESSION_DAYS`. Validate `>= 0` with the error envelope.
2. **Conditional auth on the mobile flow.** Add a dependency, e.g. `app/api/mobile.py:_mobile_auth`,
   that reads `mobile_session_days`: if `0` → return (public); else → run the SAME check as
   `require_auth` (reuse it / its internals — session cookie OR API token OR `AUTH_ENABLED=false`),
   raising 401 otherwise. **Include the `mobile` + `labels` routers and the `/r/` redirect WITHOUT
   the global `_auth_dep`**, and instead depend on `_mobile_auth` (router-level or per-route) — so
   `days==0` truly opens just these routes while the rest of the app keeps `_auth_dep`. Keep
   `_require_labels_enabled` on them too (feature gate). **Do not weaken auth on any other router.**
3. **Configurable session TTL** (`auth.py`): when issuing the `fb_session` cookie on login, set
   `max_age` to `mobile_session_days` days when `>= 1`, else 30 days; use the same value for the
   `TimestampSigner` verify `max_age`. (Default 30 ⇒ unchanged.)
4. **Expose to the SPA**: add `mobile_public: bool` (= `mobile_session_days == 0`) to the public
   `GET /api/version` response (next to `mobile_labels_enabled`).

### Frontend
5. **Auth-gate exception** (`src/App.tsx`): when `auth_enabled && !authenticated`, still render the
   router (not `<Login/>`) **iff** the current path matches `/scan/:filId/:spoolId` AND
   `mobile_public` (from `/api/version`). Everything else keeps showing Login. (The scan page's API
   calls already hit public endpoints in this mode.)
6. **Settings** (`Settings.tsx`, the "Mobile & Labels" section): a `mobile_session_days` number input
   with helper text — e.g. "Days a scan login stays signed in. 0 = scanned labels need no login
   (public); the rest of the app still requires the password." Fold into the existing isDirty/save.
   Add the field to `ConfigResponse`/`ConfigUpdateRequest` TS types + `mobile_public` to the version type.

## Tests
- Backend: with `mobile_session_days=0` → `GET /api/mobile/spool/...`, `PATCH`, `/api/labels/...`,
  and `/r/...` succeed **without** a session (and the rest of the app still 401s without auth); with
  `>=1` → they 401 without a session and 200 with one. Session cookie `max_age` reflects the setting.
  Feature still 403s when `mobile_labels_enabled` is off regardless of session-days.
- Frontend: scan route renders without login when `mobile_public`; Settings field renders/saves.
- Run `cd backend && .venv/bin/python -m pytest -q` (baseline 1262) + `ruff check .`, and
  `cd frontend && npx tsc --noEmit && npx vitest run && npm run build` (baseline 124). (Worktree has
  no node_modules — symlink the main repo's, run, remove before commit; say so.)

## When done
1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md` (the setting + the 0=public/N=login semantics + session-TTL); update
   `docs/mobile-updates.md`, `docs/configuration.md` + `CLAUDE.md` tables, and `CHANGELOG.md`.
3. ONE `feat:` commit on the worktree branch (specific paths, never `git add -A`, never push).
   Suggested: `feat: configurable mobile scan auth — mobile_session_days (0=public, N=login TTL)`.
4. Final message: commit SHA, file list, both test commands + pass/fail, and **exactly how the
   mobile/labels routers + /r redirect were re-wired off the global auth dep** (so it can be reviewed
   for holes), plus anything deferred/uncertain.
