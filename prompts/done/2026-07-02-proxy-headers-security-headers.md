---
name: 2026-07-02-proxy-headers-security-headers
status: completed        # pending | completed | failed
created: 2026-07-02
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-07-02
result: _is_https honors X-Forwarded-Proto + uvicorn --proxy-headers + security-headers middleware; 12 tests; Fixes #58
---

# Task: Correct the session-cookie Secure flag behind a TLS proxy + add security headers (M1)

A 2026-07-02 security audit found the session cookie's `Secure` flag is wrong behind a
TLS-terminating reverse proxy, and that no response security headers are set.

- **Secure-flag bug:** `_is_https(request)` returns `request.url.scheme == "https"`
  (`app/api/auth.py:112-113`), the sole input to the cookie `secure=` flag (set at
  `auth.py:102`, called at `:292` and `:327`). Uvicorn runs without `--proxy-headers`
  (`Dockerfile:55`), so behind a proxy that terminates TLS the app sees scheme `http` and
  the `fb_session` cookie is set **without** `Secure` — it can then ride a downgraded/plain
  channel on an internet-exposed instance. Inconsistently, `labels.py` (`_resolve_base_url`,
  ~:56-71) **already** trusts `X-Forwarded-Proto` — so the codebase disagrees with itself.
- **No security headers:** `app/main.py` registers no middleware setting
  `X-Content-Type-Options`, `X-Frame-Options`, or `Referrer-Policy`. Cheap hardening,
  especially for internet-exposed instances (clickjacking is currently unmitigated).

## Before you start

- Read `prompts/startnewsession.md` (operating rules, commit conventions, test commands).
  Commit but **do not push**; conventional-commit prefix; docs in the same commit; no
  `Co-authored-by:` trailers.
- Read `app/api/auth.py` around the cookie helper (`:90-113`, `:280-330`) and
  `app/api/labels.py` `_resolve_base_url` (~:56-71) — the existing X-Forwarded-Proto parse
  you'll mirror/reuse.
- Read `app/main.py:335-392` (app init, router includes, `/r/` redirect, SPA mount) to see
  where middleware should be added.

## Working tree check

Run `git status --porcelain` first. There is one prior audit commit already on `dev`
(`e752068`, the backup-secret fix) — that's expected, not dirty. If any file this task
touches (`app/api/auth.py`, `app/main.py`, Dockerfile, tests, docs) has *uncommitted*
changes, list them and ask before editing. This prompt file is exempt.

## What to do

1. **Fix the Secure flag at the source (primary, testable fix).** Make `_is_https` honor a
   proxy's `X-Forwarded-Proto` header (treat `https` there as HTTPS), mirroring what
   `labels.py:_resolve_base_url` already does. Prefer **extracting the proto-resolution into
   one shared helper** and reusing it in both places, so the logic isn't written a third
   time — but keep the change tight; don't refactor unrelated code. This is the fix that is
   unit-testable via TestClient (uvicorn's `--proxy-headers` is applied at the server layer
   and would NOT be exercised by the test client).
2. **Also enable uvicorn proxy-header trust for production** so `request.url.scheme`, client
   IP, etc. are correct behind the proxy: add `--proxy-headers` and
   `--forwarded-allow-ips=*` to the `CMD` in `Dockerfile:55`. Because the container only ever
   sits behind the user's own reverse proxy, trusting all upstream IPs is acceptable here;
   note that assumption in a comment and in the docs. (If you'd rather make the allow-list an
   env var, that's fine but optional — don't over-engineer.)
3. **Add a small security-headers middleware** in `app/main.py` that sets, on every response:
   - `X-Content-Type-Options: nosniff`
   - `X-Frame-Options: DENY` (the app is not embedded in any iframe; confirm nothing in the
     SPA relies on framing — there is no in-app iframe usage)
   - `Referrer-Policy: same-origin` (or `no-referrer` — pick one and note why)
   **Deliberately scope out** `Content-Security-Policy` (a strict CSP for the Vite/React SPA
   needs care and risks breaking the app + the react-markdown docs viewer) and
   `Strict-Transport-Security` (HSTS belongs at the TLS terminator and is harmful if the
   homelab serves the bridge over plain http). Leave a one-line comment noting both are
   intentionally deferred to the reverse proxy / a future task. Keep the middleware tiny and
   make sure it does not clobber a header a route already set.
4. **Tests** (`backend/tests/`):
   - Assert the security headers are present on a representative response (e.g. a health or
     version GET) with the correct values.
   - Assert that a login request carrying `X-Forwarded-Proto: https` results in a `Set-Cookie`
     with the `Secure` attribute, and that without it (plain http) the cookie is **not**
     `Secure`. Reuse existing auth-test fixtures/patterns.
5. **Docs:** update `docs/security.md` — add/adjust a short note that the bridge trusts
   `X-Forwarded-Proto` for the cookie Secure flag and runs uvicorn with `--proxy-headers`
   (so it must sit behind a trusted reverse proxy), and that it emits the above security
   headers while leaving CSP/HSTS to the proxy. Keep it brief — the larger security.md
   rewrite (mobile_session_days, public-route list) is a SEPARATE queued task (D1); do not do
   that here, just add the proxy/headers note.
6. **CHANGELOG:** add a `## [Unreleased]` → `### Security` bullet covering the Secure-flag fix
   + the new headers, in the same commit.
7. **GitHub issue:** audit-discovered, no existing issue. `gh issue create` a single issue
   ("Session cookie Secure flag wrong behind TLS proxy; no security headers"), then end the
   commit body with `Fixes #N`.

## Conventions to honor

- Match surrounding style; keep the middleware and helper small and readable.
- No behavior change for the normal same-origin http-dev / test path beyond the added headers.
- Run before committing: `cd backend && .venv/bin/python -m pytest` and
  `.venv/bin/python -m ruff check backend/`. Frontend is untouched, but if you changed
  anything under `frontend/` run its checks too.

## When done

1. Update this file's frontmatter (`status`, `completed`, `result`).
2. `git mv` (or `mv` if untracked) this file into `prompts/done/`.
3. Record any non-obvious decision (shared proto helper; Referrer-Policy choice; CSP/HSTS
   deferral) in `docs/decisions.md`.
4. Propose ONE commit covering exactly the modified files (code + tests + docs + CHANGELOG +
   this prompt move), `fix:` prefix, body ending `Fixes #N`. Present the file list and
   message; ask before committing. Never `git add -A`. **Never push.**
