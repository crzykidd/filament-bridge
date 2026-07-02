---
name: 2026-07-02-login-throttling
status: pending          # pending | completed | failed
created: 2026-07-02
model: sonnet            # opus = research/planning, sonnet = coding
completed:               # filled when the work is done
result:                  # one-line summary of the outcome
---

# Task: Add login rate-limiting / lockout to POST /api/auth/login (M2)

A 2026-07-02 security audit found no rate-limiting or lockout on the login endpoint
(`app/api/auth.py`, `auth_login` ~:310-340) — bcrypt's work factor is the only brake on
password brute-force, and `/api/auth/status` publicly reveals whether a password is set. Add a
simple, self-contained throttle. This is a **single-admin, self-hosted** app, so keep the design
minimal — no external store, no new dependency.

## Before you start

- Read `prompts/startnewsession.md` (operating rules, commit conventions, test commands). Commit
  but **do not push**; conventional-commit prefix; docs in the same commit; no `Co-authored-by:`.
- Read `app/api/auth.py`: `auth_login` (the target), `auth_setup`, `_has_valid_credentials`,
  `require_auth`/`mobile_auth`, and how `AUTH_ENABLED` bypass works. Note the error-envelope
  style (`HTTPException(status_code=..., detail={"code":..., "message":...})`).
- Several audit commits are already on `dev` (expected).

## Design (keep it simple)

- **In-memory** failed-attempt tracking (a module-level structure). A process restart clearing it
  is acceptable — and is itself part of the documented lockout-recovery path (`AUTH_ENABLED=false`
  + restart). Do NOT persist attempts to SQLite.
- Because there is a single admin account, tracking can be **global** or **per-client-IP** — your
  call; per-IP is slightly friendlier (one abuser doesn't lock out the real user) but global is
  simpler and safe for a single user. Pick one, justify it in a comment, and if per-IP use the
  proxy-aware client IP (honor `X-Forwarded-Proto`/forwarded-for consistently with how the app now
  trusts proxy headers — see `_is_https` and the Dockerfile `--proxy-headers`).
- **Threshold + window:** after N consecutive failures (suggest **5**), reject further attempts
  for a cooldown (suggest a short lockout, e.g. **60–120 s**, or a progressive/backoff delay) with
  **HTTP 429** and a clear `detail` code (e.g. `too_many_attempts`) and a `Retry-After` header.
  Make the threshold/window named constants at minimum; a config knob is optional (don't
  over-engineer — constants are fine for this app).
- **Reset on success:** a correct password clears the counter for that key.
- **Do not** throttle when `AUTH_ENABLED` is false (login is bypassed anyway), and do not affect
  the API-token path or any other endpoint — only `POST /api/auth/login`.
- Preserve current behavior otherwise: same 401 codes for `no_password_set` / `invalid_credentials`
  on non-locked attempts.

## What to do

1. Implement the throttle in `app/api/auth.py` (a small helper + a check at the top of
   `auth_login`, plus a reset on the success path). Keep it readable; comment the choice of
   global-vs-per-IP and the threshold/window rationale.
2. **Tests** (`backend/tests/`): cover (a) N failed attempts → the next returns 429 with the
   `Retry-After` header and the lockout code; (b) a successful login before the threshold resets
   the counter; (c) `AUTH_ENABLED=false` is never throttled; (d) the throttle is per the chosen key
   (if per-IP, two different IPs are tracked independently; if global, document that). Ensure the
   in-memory state is reset between tests (fixture) so tests don't bleed into each other.
3. **Docs:** update `docs/security.md` — the "What is NOT implemented" list currently says
   *"Account lockout after failed attempts (bcrypt cost blunts brute force)"*; remove that line and
   add a short note under the auth/crypto section describing the new throttle (threshold, window,
   429 + Retry-After, in-memory, cleared on restart / by the `AUTH_ENABLED=false` recovery path).
4. **CHANGELOG:** add a `## [Unreleased]` → `### Security` bullet.
5. **GitHub issue:** audit-discovered, no existing issue. `gh issue create` one
   ("No rate-limiting / lockout on login"), then end the commit body with `Fixes #N`.

## Conventions to honor

- No new runtime dependency; standard library only.
- Match the existing error-envelope shape.
- Run before committing: `cd backend && .venv/bin/python -m pytest` and
  `.venv/bin/python -m ruff check backend/`.

## When done (dispatched-agent variant)

You are a dispatched agent and cannot ask the user mid-run. Do the code + tests + docs +
CHANGELOG. Run tests + lint. **Do NOT** create the GitHub issue, `git commit`, `git add`, or move
this prompt file — leave the tree dirty for review. In your final message report: (1) files changed
+ one line each, (2) `git diff --stat`, (3) the design you chose (global vs per-IP, threshold,
window, response) and why, (4) proposed `fix:` commit message ending `Fixes #<N>`, (5) proposed
issue title + 2-3 sentence body, (6) test + lint results, (7) any non-obvious decision for
`docs/decisions.md`.
