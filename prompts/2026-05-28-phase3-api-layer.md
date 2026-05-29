---
name: 2026-05-28-phase3-api-layer
status: pending          # pending | completed | failed
created: 2026-05-28
model: opus              # opus = research/planning, sonnet = coding
completed:               # filled when the work is done
result:                  # one-line summary of the outcome
---

# Task: Phase 3 — Bridge API layer (wizard + sync/conflict/config/backup routers)

Expose the Phase 2 engine and the persistence layer over HTTP: the initial-sync wizard
endpoints (FR-1…FR-7), the sync controls (trigger, dry run, enable/disable auto-sync),
the conflict queue (list/resolve/bulk-resolve), mappings view/edit, runtime config, and
backup export/import. This is the contract the Phase 4 React UI consumes — design the
response shapes for the screens described in FR-15…FR-19.

This implements the API surface for **FR-1…FR-6, FR-14, FR-16, FR-18** and the data
endpoints behind **FR-15, FR-17, FR-19, FR-24/FR-25**. The wizard *execute* step (FR-7)
is carved into its own follow-on prompt (Phase 3b) — see the scope boundary.

## Before you start

- **Read `docs/prd.md`** — the P0 wizard (FR-1…FR-7), FR-14 (dry run), and the P1 UI
  sections (FR-15…FR-19) define exactly what data each screen needs. Build endpoints that
  return those shapes — including the deep-link IDs every row requires.
- **Read `docs/decisions.md`** — deep-link routes (FDB `/filaments/{id}` plural; Spoolman
  `/spool/show/{id}` and `/filament/show/{id}`, no hash routing; no standalone FDB spool
  page), the canonical phase table, and the engine's source-of-truth config keys.
- **Read `CLAUDE.md`** — the `api/` router list, env vars, and the hard rules (no
  auto-resolve, no upstream deletes, usage-endpoint-only weight decrements).
- **Phase 2 must be merged first.** This phase calls `core/engine.run_sync_cycle`,
  `core/matcher`, `core/fields`, `core/weight`, and the client write methods. Read those
  signatures before designing routes; do not reimplement engine logic in a router.
- **Read `backend/app/api/health.py`** — match its router style, `app.state` client
  access, and error handling. **Read `backend/app/db.py`** — use the `get_db` dependency
  in route handlers (FastAPI runs sync `Depends` in a threadpool).
- Use the `vexp` `run_pipeline` MCP tool for code context, not grep/glob.

## Working tree check

Before editing, run `git status --porcelain` and cross-reference the files this plan
touches (new routers under `backend/app/api/`, a new `backend/app/schemas/api.py` for
request/response models, `main.py` router registration, `backend/tests/`). If any are
dirty, list them and ask. Surface unrelated dirty files once; don't block. This prompt
file is exempt.

## Scope boundary (read this)

- **IN:** FastAPI routers + the bridge's own request/response Pydantic models, mounted on
  the existing app; all logic delegated to Phase 2's `core/`. Tests that exercise the
  routes with faked upstream clients.
- **OUT:** Any React/TypeScript (Phase 4) and the `/static` SPA mount (still a commented
  placeholder until Phase 4). Do not change engine algorithms here — if a route needs
  behavior the engine lacks, note it and prefer a small engine addition over duplicating
  logic in the router.
- **FR-7 (wizard execute) is explicitly OUT — it's Phase 3b** (`prompts/`
  `2026-05-28-phase3b-wizard-execute.md`). This phase builds everything up to and
  including the user *deciding* the sync (connectivity → direction → matches → weights →
  variants, all persisted), plus the sync/conflict/mappings/config/backup/sync-log
  routers. Phase 3b is the single endpoint that *performs* the initial write to both
  upstreams. Design `api/wizard.py` so 3b can drop `POST /api/wizard/execute` in alongside
  the read/decision endpoints without reshaping them.

## What to do

All routes under `/api`. Define request/response models in
`backend/app/schemas/api.py` (keep upstream-shape schemas separate in `schemas/filamentdb`
/`schemas/spoolman`). Every record-bearing response includes the IDs needed to build both
deep links (FDB filament id, Spoolman spool/filament id) — the UI constructs URLs from
the env-var bases.

### 1. `api/sync.py` — sync controls (FR-8/FR-14/FR-18)
- `POST /api/sync/trigger` → run `run_sync_cycle(db, dry_run=False)` now; return counts.
- `POST /api/sync/dry-run` → `run_sync_cycle(db, dry_run=True)`; return the full preview
  changeset (creates/updates/conflicts) without applying (FR-14).
- `POST /api/sync/auto` `{enabled: bool}` → write `auto_sync_enabled` to `BridgeConfig`.
  Guard: refuse to enable while `wizard_completed` is false (return 409 with a reason).
- `GET /api/sync/status` → last sync time, next scheduled run, in-sync vs pending counts,
  pending-conflict count, both-system connectivity (reuse the health probes) — the
  Dashboard payload (FR-15).

### 2. `api/conflicts.py` — conflict queue (FR-13/FR-16)
- `GET /api/conflicts?status=open|resolved` → list `Conflict` rows with both values,
  field name, timestamps, and deep-link IDs.
- `POST /api/conflicts/{id}/resolve` `{resolution: "spoolman"|"filamentdb"|"manual",
  value?}` → record the choice on the `Conflict` row (`resolved_at`, `resolution`,
  `resolved_value`). Applied on the next cycle (or apply immediately — pick one, document
  it). Never auto-pick.
- `POST /api/conflicts/bulk-resolve` `{ids[], resolution}` → same, batched.

### 3. `api/mappings.py` — paired records (FR-19)
- `GET /api/mappings` → joined `FilamentMapping`/`SpoolMapping` + current weights/status
  per side for the Synced Records table; sortable/filterable params; status enum
  in-sync/pending/conflict/unlinked.
- `PUT /api/mappings/{id}` and `DELETE /api/mappings/{id}` → manual relink/unlink (unlink
  only severs the bridge mapping; it must NEVER delete an upstream record).

### 4. `api/config.py` — runtime config (FR-2 ongoing settings)
- `GET /api/config` / `PUT /api/config` over the `BridgeConfig` keys (source-of-truth per
  category, weight threshold). Validate enum values. Field-mapping *connection* settings
  stay env-var-only — this is the user-tunable subset.

### 5. `api/wizard.py` — initial sync wizard (FR-1…FR-7)
- `GET /api/wizard/connectivity` (FR-1) → reuse health: versions + counts, block flag.
- `POST /api/wizard/direction` (FR-2) → persist import direction + source-of-truth choices.
- `GET /api/wizard/matches` (FR-3/FR-4) → run `core/matcher` over both systems; return
  matched / unmatched-each-side / ambiguous, each row with deep-link IDs and a
  vendor-dedup hint where names collide.
- `POST /api/wizard/matches` → persist user pairings / create-new / skip decisions.
- `GET /api/wizard/weights` (FR-5) → per-spool net↔gross preview via `core/weight`, with
  the tare source and a per-spool/per-filament override field.
- `GET /api/wizard/variants` + `POST` (FR-6) → suggested parent/variant groupings (strip
  color from name); persist confirmed `filamentdb_parent_id` choices.
- `POST /api/wizard/execute` (FR-7) is **Phase 3b** — not built here. Leave the wizard
  decision state persisted and `wizard_completed` still `false`; 3b flips it.

### 6. `api/backup.py` — state export/import (FR-24/FR-25)
- `GET /api/backup/export` → JSON dump of mappings + config + open conflicts (NOT a copy
  of upstream data — bridge state only, per `CLAUDE.md`).
- `POST /api/backup/import` → restore from that dump; validate version/shape; idempotent.

### 7. `api/sync_log.py` — audit log (FR-17)
- `GET /api/sync-log` → paginated `SyncLog` query, filterable by entity_type / direction /
  action, newest first, each entry carrying deep-link IDs where applicable.

### 8. Register routers + tests
- Mount all routers in `main.py` alongside the health router.
- `backend/tests/` route tests with **faked upstream clients** (no live network): assert
  dry-run returns a preview and applies nothing; resolving a conflict records the choice
  and never auto-applies the other side; auto-enable is refused before `wizard_completed`;
  `GET /api/mappings` returns correct status enums; backup export→import round-trips.
- `cd backend && pytest` must pass.

## Conventions to honor

- Delegate to `core/`; routers orchestrate and shape responses, they don't contain sync
  algorithms.
- `get_db` dependency for sessions; async route handlers only where they await a client.
- Every record row response carries the IDs to build both deep links (no URL building in
  the backend — the UI owns that from env-var bases).
- Hard rules stay hard: no auto-resolve, no upstream deletes, usage-endpoint-only weight
  decrements, don't touch the FDB `settings{}` bag.
- Consistent error envelope; structured JSON logs; respect `LOG_LEVEL`.
- The `/static` SPA mount stays a commented placeholder (Phase 4 lands it).

## When done

1. Update this file's frontmatter: `status`, `completed`, `result` (note any split).
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/` (failure).
3. Record non-obvious decisions in `docs/decisions.md` (e.g. resolve-now vs resolve-next-
   cycle, the API error envelope shape, backup format/versioning).
4. Propose ONE commit (no `Co-authored-by:`). Suggested message:
   `feat: Phase 3 — bridge API layer (wizard, sync, conflicts, config, backup)`.
   Files: `api/*.py`, `schemas/api.py`, `main.py`, `tests/*`, `docs/decisions.md`, the
   prompt move. Present the file list and ask `commit these as "<message>"? (y/n)` before
   staging. Stage specific paths only; commit on `dev`; no push.
