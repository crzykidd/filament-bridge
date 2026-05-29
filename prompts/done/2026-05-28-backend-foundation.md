---
name: 2026-05-28-backend-foundation
status: completed
created: 2026-05-28
model: sonnet
completed: 2026-05-28
result: FastAPI skeleton running; GET /api/health returns 200 (degraded/error) with JSON logs; fail-fast on missing env vars confirmed
---

# Task: Backend foundation (Phase 0)

Stand up the FastAPI backend skeleton: startup config validation, structured logging,
the scheduler shell, async clients for both upstream APIs, and a connectivity/health
endpoint (FR-1). This is the runnable base everything else (persistence, sync engine,
wizard, UI) builds on. No sync logic and no SQLite yet — those are later phases.

## Before you start

- **Read `docs/prd.md`** (esp. Architecture, FR-1, NFR-1/2/3/4/5) and `CLAUDE.md`.
- **Read `docs/decisions.md`** — the deep-link routes, extra-field handling, and sync
  defaults are already decided there. Honor them.
- **Read `private_data/findings.md`** — it has the *real* API shapes (Spoolman
  spool/filament/vendor, Filament DB filament + embedded spool + variant detail) pulled
  from the live instances. Model the Pydantic types off those, not off guesses.
- `private_data/` is gitignored test data — never commit anything from it.
- Use the `vexp` `run_pipeline` MCP tool for code context (per `.claude/CLAUDE.md`), not
  grep/glob.

## Working tree check

Before editing, run `git status --porcelain` and cross-reference the files this plan
creates (all new, under `backend/`). If `backend/` already has uncommitted work, list it
and ask before touching. Surface unrelated dirty files once as awareness; don't block.

## What to do

1. **`backend/requirements.txt`** — fastapi, uvicorn[standard], httpx, pydantic v2,
   pydantic-settings, apscheduler. (SQLAlchemy/alembic come in Phase 1 — omit for now.)
2. **`backend/app/__init__.py`** — `__version__ = "0.1.0"` (canonical version file per
   the release standard; bare, no `v` prefix).
3. **`backend/app/config.py`** — env-var parsing via pydantic-settings. **Refuse to start
   if `FILAMENTDB_URL` or `SPOOLMAN_URL` are missing** (NFR-2). Parse the full env table
   from `CLAUDE.md` (sync interval, the Spoolman field-name overrides, field-mapping
   vars, Discord webhook, log level, data dir) with the documented defaults.
4. **`backend/app/services/spoolman.py`** — async httpx client. Methods needed now:
   `get_spools()` (must pass `?limit=1000`; results include archived — caller filters),
   `get_filaments()`, `get_vendors()`, `get_field_definitions(entity_type)`, and a
   `health()`/info call. Extra-field text values are JSON-double-quoted — provide a
   decode helper. Don't build write methods yet.
5. **`backend/app/services/filamentdb.py`** — async httpx client. Methods now:
   `get_filaments()` (list/trimmed), `get_filament(id)` (detail/full), and a health/info
   call. Note: list vs detail are different projections (see findings). Don't build write
   methods yet.
6. **Pydantic models** (`backend/app/services/*` or a `schemas/` module) — response models
   for Spoolman spool/filament/vendor and Filament DB filament + embedded spool, matching
   the real shapes in `findings.md`. Be lenient (extra fields allowed) — both APIs evolve.
7. **`backend/app/api/health.py`** — FR-1: a `GET /api/health` that probes both upstreams
   concurrently and returns connectivity status, version, and record counts for each.
   Degraded (one side down) returns 200 with per-system status, not a hard failure (NFR-4).
8. **`backend/app/main.py`** — FastAPI app; mount the health router; init APScheduler
   (scheduler created but **no jobs / auto-sync OFF** — Phase 3 adds the cycle);
   structured JSON logging to stdout (NFR-5); leave a commented placeholder for the
   `/static` SPA mount (Phase 5). App must start fast (NFR-3).
9. Verify it runs: `cd backend && uvicorn app.main:app --port 8090` and `GET /api/health`
   returns a sensible shape. (Live upstreams optional — degraded response is fine.)

## Conventions to honor

- Python 3.12+, FastAPI, async httpx, Pydantic v2 (per `CLAUDE.md` tech stack).
- **NFR-1:** documented REST APIs only — no upstream modification, no MongoDB access.
- Structured JSON logs to stdout; respect `LOG_LEVEL`.
- Keep it to the skeleton — resist pulling Phase 1+ work forward.
- No tests required to pass yet beyond the manual `GET /api/health` check, but structure
  the clients so they're unit-testable (Phase 2 leans on this).

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/` (failure);
   create the subdir if needed.
3. Record any non-obvious decisions in `docs/decisions.md`.
4. Propose ONE commit covering the files this session created (including the prompt move).
   Present the file list and a one-line message; ask `commit these as "<message>"? (y/n)`.
   On `y`, stage those specific paths and commit on `dev` (never `main`, never
   `git add -A`, never push). Commit prefix `feat:` (new backend foundation). No
   `Co-authored-by:` trailer. After this lands, `main` branch protection + the 5 CI
   checks become wireable (tracked in `standards.md`).
