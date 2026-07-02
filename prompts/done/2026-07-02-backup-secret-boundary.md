---
name: 2026-07-02-backup-secret-boundary
status: completed        # pending | completed | failed
created: 2026-07-02
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-07-02
result: SECRET_CONFIG_KEYS strips auth secrets + internal state from backup export/import; 13 tests; Fixes #57
---

# Task: Stop the backup boundary from leaking / accepting auth secrets (H1 + H2)

A 2026-07-02 security audit found two HIGH issues in the bridge-state backup feature.
Both share one root cause — the backup treats the entire `BridgeConfig` key→JSON store
as opaque, with no notion of "sensitive". Fix them together.

- **H1 (leak):** `GET /api/backup/export` sets `config=read_config(db)` with no denylist
  (`app/api/backup.py:238`, `app/api/config.py:41-43`). The exported JSON — and the
  nightly on-disk backup at `{DATA_DIR}/backups/bridge-state-*.json` — therefore contains
  `auth_secret` (the itsdangerous cookie-signing key → anyone with the file can forge
  `fb_session` cookies), `admin_password_hash`, `api_token`, and `labelforge_token`, all
  cleartext.
- **H2 (overwrite):** `POST /api/backup/import` loops `payload.config.items()` and calls
  `set_config_value` for **every** key with no allowlist (`app/api/backup.py:256-258`). A
  crafted backup can overwrite `admin_password_hash` (→ account takeover) or `auth_secret`
  (→ offline cookie forgery / mass session invalidation), or flip `debug_mode`,
  `mobile_session_days`, etc.

## Before you start

- Read `prompts/startnewsession.md` (operating rules, git/commit conventions, test
  commands). Honor them — commit but **do not push**; conventional-commit prefix; docs in
  the same commit; no `Co-authored-by:` trailers.
- Read `app/api/backup.py` (export at :200, import at :245) and `app/api/config.py`
  (`read_config` :41, `set_config_value` :63, and note the existing GET /api/config
  handling at :276-278 that already refuses to return `admin_password_hash`/`auth_secret`).
- Note the sensitive/internal keys in `app/models/config.py:_DEFAULTS`: `auth_secret`,
  `admin_password_hash`, `api_token`, `labelforge_token`. Also internal-state keys that
  should not round-trip through a portable backup: `backup_last_run`, `wizard_last_run`
  (and any other `*_last_run` write-only state).

## Working tree check

Before editing, run `git status --porcelain` and cross-reference the files below. If any
have uncommitted changes, list them and ask before touching. Surface unrelated dirty files
once as awareness; don't block. This prompt file is exempt.

## What to do

1. **Define one shared constant** of config keys that must never cross the backup
   boundary — put it where both export and import can import it (e.g. a
   `SECRET_CONFIG_KEYS` frozenset in `app/api/config.py` next to the store helpers, or a
   small module). It MUST include: `auth_secret`, `admin_password_hash`, `api_token`,
   `labelforge_token`. Add a short comment explaining why (session-forgery / takeover).
   Decide whether to also exclude write-only internal state (`backup_last_run`,
   `wizard_last_run`) — recommended, since restoring stale run-summaries onto another
   instance is meaningless; if you exclude them, note it.
2. **H1 — export:** filter the config dict so no `SECRET_CONFIG_KEYS` entry is emitted.
   Do it at the source so BOTH the endpoint and the nightly on-disk job are covered —
   check `app/core/backup_job.py` (`write_bridge_state_backup` or similar) and confirm it
   builds its payload from the same export path; if it calls `read_config` independently,
   fix it there too (or route both through one sanitized builder). Grep for every caller
   of `read_config` to be sure.
3. **H2 — import:** skip any key in `SECRET_CONFIG_KEYS` when applying `payload.config`
   (don't `set_config_value` for them). Keep counting only applied keys. A restored backup
   must never change auth material — the target instance keeps its own `auth_secret` /
   password / tokens.
4. **Tests** (`backend/tests/`, pytest): add coverage that
   (a) `GET /backup/export` output's `config` contains none of the secret keys even when
   they're set in the DB; (b) `POST /backup/import` with a payload that includes a
   `admin_password_hash` / `auth_secret` / `api_token` leaves the existing DB values
   unchanged; (c) a normal non-secret key (e.g. `sync_interval_seconds`) still
   round-trips through export→import. Reuse existing backup test fixtures/patterns.
5. **Docs:** update `docs/backups.md` to state that backups deliberately exclude auth
   secrets (cookie-signing key, password hash, API + LabelForge tokens) — so a restored
   backup keeps the target instance's own credentials, and an exported file is not a
   credential leak. One or two sentences. If `docs/security.md` references backups, add a
   line there too (the fuller security.md rewrite is a separate task — don't do it here).
6. **CHANGELOG:** add a `## [Unreleased]` → `### Security` (or `### Fixed`) entry
   describing both fixes in one bullet. This is required in the same commit.
7. **GitHub issue:** these are audit-discovered security bugs with no existing issue.
   Per the operating rules, `gh issue create` a single issue covering H1+H2 (title e.g.
   "Backup export/import leaks and accepts auth secrets"), then end the commit body with
   `Fixes #N`. If unsure whether to combine or split, ask the user first.

## Conventions to honor

- Match surrounding style; keep the constant near the config-store helpers it relates to.
- No behavior change for non-secret config. Import must stay idempotent.
- Run before committing: `cd backend && .venv/bin/python -m pytest` and
  `.venv/bin/python -m ruff check backend/`.

## When done

1. Update this file's frontmatter (`status`, `completed`, `result`).
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/`.
3. Record any non-obvious decision (e.g. whether internal-state keys were excluded) in
   `docs/decisions.md`.
4. Propose ONE commit covering exactly the modified files (code + tests + docs + CHANGELOG
   + this prompt move), `fix:` prefix, body ending `Fixes #N`. Present the file list and
   message; ask before committing. Never `git add -A`. **Never push.**
