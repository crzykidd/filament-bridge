---
name: 2026-05-30-phase5-sync-fixes
status: completed
created: 2026-05-30
model: sonnet
completed: 2026-05-30
result: PATCH fix (A), material default "Unknown" (B), weight_precision_decimals config 0-4 + UI dropdown (C), wizard_completed gated on failed==0 (D); 99 tests green, frontend build clean
---

# Task: Phase 5 — one-way sync correctness fixes + configurable weight precision

The first real end-to-end run of the initial sync (Spoolman → Filament DB, against a live
223-spool / 175-filament dataset) exposed concrete bugs and data-model mismatches. This
prompt fixes the **code bugs** that stop the sync from actually working, and adds a
**user-configurable weight precision** setting. The larger data-model items (filament name
collisions, empty spools, tare confirmation) are genuine **reconcile-phase UI** work and are
captured here as a deferred backlog for the next prompt — do NOT build them here.

## Context — how these findings were produced (reproduce before/after)

A local dev stack is running via `docker-compose.dev.yml` (bridge :8090, Filament DB :3000
+ Mongo, Spoolman :7912). Spoolman holds real data; a clean snapshot is kept at
`private_data/spoolman-livedata.db`. The sync was driven through the wizard API
(`POST /wizard/direction {import_direction:"spoolman"}` → `POST /wizard/matches` with all
unmatched set to `action:"create"` → `POST /wizard/execute`). The full report is saved at
`private_data/sync-test-execute.json`. Result was **131 created, 211 failed**, breaking down
into the findings below (all root-caused and live-verified).

To reproduce a clean run after your fixes: reset Filament DB (drop its Mongo data so it's
empty again), re-seed Spoolman from `private_data/spoolman-livedata.db` if needed, then
re-drive the wizard execute and confirm the failure classes are gone (see Verification).

## Before you start

- **Read `docs/prd.md`** FR-7 (execute), FR-9/FR-10 (ongoing weight sync), FR-2 (config /
  source-of-truth), FR-15…FR-19 (UI). **Read `docs/decisions.md`** (weight model,
  cross-ref IDs, strip-computed-before-PUT, the 2026-05-30 compose/SPA entry).
- **Read `CLAUDE.md`** — the weight-model section, the Spoolman API endpoint list (one note
  is WRONG, see fix A), and the hard rules (never raw-overwrite FDB weight, never touch the
  FDB `settings{}` bag, conflicts never auto-resolved).
- Use the `vexp` `run_pipeline` MCP tool for code context, not grep/glob.
- Touch the backend conversion/client/config code and a small Settings-UI addition only.
  Do not start the reconcile-phase UI (the deferred backlog).

## Working tree check

Run `git status --porcelain`. Files this prompt touches: `backend/app/services/spoolman.py`,
`backend/app/core/weight.py`, `backend/app/core/engine.py`, `backend/app/api/wizard.py`,
`backend/app/api/config.py`, `backend/app/schemas/api.py`, `backend/app/models/config.py`,
`backend/app/config.py`, `CLAUDE.md`, `frontend/src/pages/Settings.tsx` (+ `api/types.ts`,
`api/client.ts`), `backend/tests/*`. If any are dirty, list them and ask. Surface unrelated
dirty files once; don't block. (`private_data/`, `backend/.env` are gitignored.) This prompt
file is exempt.

## What to do — code fixes (implement these)

### A. Spoolman spool update uses the wrong HTTP method (167 failures, also breaks FR-10)
`services/spoolman.py::update_spool` does `self._http.put(f"/api/v1/spool/{id}", ...)`.
Spoolman v0.23.1 returns **405 Method Not Allowed** for `PUT` on that path and **200** for
`PATCH` (`OPTIONS` advertises GET only for the unauthenticated probe; PATCH is the documented
update verb). This one method backs **both** the wizard cross-ref write-back **and** FR-10
ongoing weight sync (FDB → Spoolman `remaining_weight`), so the bug kills that whole path too.

- Change `update_spool` from `.put` → `.patch`. Verify no other Spoolman call uses `.put`.
- **Fix the doc:** `CLAUDE.md` lists `PUT /api/v1/spool/{id}` — correct it to `PATCH`
  (both the endpoint list and the FR-10 line). Note it in `docs/decisions.md`.
- Test: assert `update_spool` issues a PATCH (respx/httpx mock or the existing fake client).

### B (PARTIAL — code side only). Filament create `400` on missing material (1 failure)
Spoolman filament fid 145 ("Silk Pumpkin Orange") has `material: null`; Filament DB rejects
the create with 400. Reproduce and confirm the cause is the missing/empty material (it may
also reject other empty required fields — check the 400 body).
- Make the create resilient: when the source material is missing, fall back to a sensible
  default so the record imports rather than failing the whole filament. Put the default in
  one place (a module constant or config, your call — keep it simple) and **log a warning**
  naming the spoolman filament id so it's visible. Do NOT silently invent material values
  without logging.
- If the 400 turns out to be something other than material, fix the actual cause and note
  it; don't paper over it.
- Test: a filament with null material imports (with the default) instead of failing.

### C. Configurable weight precision (new setting; default 2 decimals)
Today `core/weight.py` adds tare with **no rounding**, so Spoolman's full-precision floats
flow straight through (e.g. Filament DB shows `739.4936014320408`). Add a user-selectable
precision, default **2 decimals**, applied to both conversion directions.

- Keep `weight.py` pure: add a `precision: int = 2` parameter to `spoolman_to_fdb_gross`
  and `fdb_to_spoolman_net`, and `round(result, precision)` the returned weight. Don't read
  the DB inside these pure functions.
- Thread the configured precision in at the call sites (`api/wizard.py` execute, and the
  FR-9/FR-10 paths in `core/engine.py`) — read it from config and pass it.
- **Config plumbing:** add `weight_precision_decimals` (int, default 2) as a `BridgeConfig`
  key in `models/config.py::seed_defaults`, and surface it in `ConfigResponse` /
  `ConfigUpdateRequest` (`schemas/api.py`) with a sane bound (e.g. `ge=0, le=4`). It's a
  key-value config row — no Alembic migration needed.
- **Settings UI:** add a "Weight precision" selector to `frontend/src/pages/Settings.tsx`
  (e.g. options: Whole grams (0) / 0.1 g (1) / 0.01 g (2, default) / 0.001 g (3)), wired to
  GET/PUT `/api/config` via the existing api client + types.
- Note in `CLAUDE.md`/decisions that rounding stays well under `sync_weight_threshold_grams`
  (default ~2 g), so it won't cause sync churn. Tests: rounding at 0/1/2 decimals; round-trip
  net→gross→net is stable at the default precision.

### D. `wizard_completed` should not flip true on a failed run (UX correctness)
Execute set `wizard_completed=true` even with 211 failures. Gate the flip: only set it true
when the run had **no failures** (`failed == 0`); otherwise leave it false and return the
report so the user can fix issues and re-run. (Idempotency already skips already-linked
records, so re-running after fixes is safe.) Test both branches.

## Deferred to the reconcile phase (DOCUMENT ONLY — do NOT build here)

These are real data-model mismatches surfaced by the test. They belong in the FR-4 match/
reconcile UI and will be the next handoff prompt. Capture them in `docs/decisions.md` (or a
short `docs/reconcile-backlog.md`) so they aren't lost:

- **Filament name uniqueness (43 × 409).** Filament DB enforces a **unique filament name**;
  Spoolman allows duplicates across vendors/materials (10×"Black", 8×"White", 7×"Orange").
  43 of 175 collide. The reconcile UI must let the user disambiguate before create
  (rename / vendor- or material-qualify the name / merge into one). This is the single
  biggest reconcile item.
- **Empty-but-active spools (63).** `remaining_weight == 0`, fully used, **not archived** in
  Spoolman. Reconcile choice per spool/bulk: import as empty / skip / treat as archived.
- **Default-tare spools (79).** No `spool_weight` in Spoolman → bridge assumes 200 g, so part
  of the imported gross weight is a guess. FR-5 already supports per-spool/filament tare
  override; the reconcile UI should **flag** default-tare rows so the user can confirm/set.
- **Variant grouping on fresh import (F).** FR-6 only analyzes *matched* filaments, so it
  returns 0 groups on an empty target. Decide whether to also group the to-be-created
  filaments (vendor + material, color stripped) during initial import.

## Conventions to honor

- Delegate writes to the existing client methods + `core/weight`; don't reimplement HTTP or
  conversions. Strip computed fields before any FDB PUT; never touch the FDB `settings{}`
  bag; never raw-overwrite FDB weight (usage entries for decrements per FR-9).
- `weight.py` stays pure (no I/O). Structured JSON logs; respect `LOG_LEVEL`.
- Frontend: match existing Settings page patterns and the typed api client/types.

## Verification

- `cd backend && pytest` green (new tests for A, B, C, D included).
- `cd frontend && npm run build` green; the new precision selector loads and round-trips
  through GET/PUT `/config`.
- **End-to-end on the local stack:** reset Filament DB to empty, re-drive the wizard execute
  (Spoolman → FDB). Confirm: the 405 spool failures are gone and cross-ref IDs are written on
  both sides (mappings created, FDB spool `label` set, Spoolman extra fields populated); the
  null-material filament imports; FDB weights respect the configured precision; the 43 name
  collisions still 409 **as expected** (deferred to reconcile) and `wizard_completed` stays
  false because failures remain. Capture the new created/updated/skipped/failed counts in the
  result line.

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/` (failure).
3. Record decisions in `docs/decisions.md` (PATCH-not-PUT, the weight-precision setting + why
   it's churn-safe, the missing-material default, the wizard_completed gating) and the
   reconcile backlog.
4. Propose ONE commit (no `Co-authored-by:`). Suggested message:
   `fix: one-way sync correctness (Spoolman PATCH, weight precision setting, import guards)`.
   Present the file list and ask `commit these as "<message>"? (y/n)` before staging. Stage
   specific paths only; commit on `dev`; no push.
