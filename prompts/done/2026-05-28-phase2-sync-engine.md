---
name: 2026-05-28-phase2-sync-engine
status: completed
created: 2026-05-28
model: sonnet
completed: 2026-05-29
result: core/ engine + helpers, client write methods, scheduler wiring, 57 tests passing
---

# Task: Phase 2 — Continuous sync engine

Build the bridge's brain: the `core/` modules that snapshot both systems, diff against
the last-known state, match records, classify changes, apply non-conflicting ones in the
configured direction, queue conflicts, and log every action. Wire it to the APScheduler
shell from Phase 0 so it runs on the interval — **but gated OFF by default** until the
user enables auto-sync. No HTTP routes and no UI here (those are Phase 3/4); the engine
is a callable function the scheduler invokes and Phase 3 will expose.

This implements **FR-8 through FR-14**.

## Before you start

- **Read `docs/prd.md`** — FR-8 (cycle), FR-9/FR-10 (weight both directions), FR-11
  (field mapping), FR-12 (new record detection), FR-13 (conflict detection), FR-14 (dry
  run). Also re-read the weight-model and data-model gotchas in `CLAUDE.md`.
- **Read `docs/decisions.md`** — the sync-engine defaults (≥2g weight threshold, full
  snapshot diff each cycle, `archived==false` filter, aggregate-delta acceptance), the
  variant inheritance rules (`_inherited[]`, strip computed fields before PUT), and the
  Spoolman extra-field JSON-quoting quirk are **already decided**. Honor them — do not
  re-litigate.
- **Read `private_data/findings.md`** — the real API shapes from the live instances.
  Build fixtures and conversions off these, not guesses. `private_data/` is gitignored —
  never commit anything from it.
- **Read the existing code you build on:**
  - `backend/app/services/filamentdb.py` / `spoolman.py` — read-only clients today
    (`get_filaments`, `get_filament`, `get_spools`, `get_vendors`,
    `get_field_definitions`, `health`). You will ADD the write methods.
  - `backend/app/models/*` — `Snapshot`, `Conflict`, `SyncLog`, `FilamentMapping`,
    `SpoolMapping`, `BridgeConfig` already exist. Read their columns; don't redefine them.
  - `backend/app/main.py` — clients live on `app.state.spoolman` / `app.state.filamentdb`;
    `_scheduler` (AsyncIOScheduler) is module-level and started in the lifespan with **no
    jobs**. `backend/app/db.py` exports `SessionLocal` for sessions outside a request.
  - `backend/app/schemas/*` — Pydantic types for both systems already model the API
    shapes. Reuse them.
- Use the `vexp` `run_pipeline` MCP tool for code context, not grep/glob.

## Working tree check

Before editing, run `git status --porcelain` and cross-reference the files this plan
touches (new files under `backend/app/core/` and `backend/tests/`, edits to
`services/*.py`, `main.py`, `requirements.txt`). If any are dirty, list them and ask.
Surface unrelated dirty files once as awareness; don't block. This prompt file is exempt.

## Scope boundary (read this)

- **IN:** `core/` engine + helpers, the client write methods they need, scheduler wiring,
  conflict queuing, sync-log writes, snapshot persistence, dry-run mode, and unit tests.
- **OUT:** HTTP routers (`api/sync.py`, `api/conflicts.py`, …), the initial-sync wizard,
  and anything React. The engine exposes `run_sync_cycle(...)` as a plain function;
  Phase 3 wraps it in endpoints. The matcher and field-mapping logic live here because
  FR-12 needs them at runtime — the wizard (Phase 3) reuses them, doesn't reimplement.

## What to do

### 1. Add write methods to the upstream clients

Extend the existing clients (keep the async-context-manager pattern, the `_http`
accessor, and lenient parsing). Add only what the engine needs:

**`services/spoolman.py`**
- `get_spool(spool_id)` — single spool (nested filament+vendor).
- `update_spool(spool_id, payload)` — `PUT /api/v1/spool/{id}` (weight, extra fields,
  location).
- `create_spool(payload)` / `create_filament(payload)` / `create_vendor(payload)` — for
  FR-12 new-record creation.
- `ensure_extra_fields()` — check `get_field_definitions("spool")` and create the three
  cross-ref fields (`filamentdb_id`, `filamentdb_parent_id`, `filamentdb_spool_id`) via
  `POST /api/v1/field/spool/{key}` if missing (per the decisions-log startup rule).
- Encode/decode extra-field text values with `json.dumps`/`json.loads` (the double-quote
  quirk) — centralize this so callers never touch raw values.

**`services/filamentdb.py`**
- `update_filament(id, payload)` — `PUT /api/filaments/:id`. **Strip computed/Mongoose
  fields** before sending (`_inherited`, `_parent`, `_variants`, `hasVariants`,
  `inherits`, `settings`, `__v`, `instanceId`, `createdAt`, `updatedAt`, `_deletedAt`).
- `log_usage(filament_id, spool_id, grams, job_label, source, date)` —
  `POST /api/filaments/:id/spools/:spoolId/usage`. This is the ONLY way the engine
  decrements FDB weight (never raw overwrite).
- `update_spool(filament_id, spool_id, payload)` — `PUT /api/filaments/:id/spools/:spoolId`
  for non-weight spool fields and weight *increases* (totalWeight up, not negative usage).
- `create_spool(filament_id, payload)` — `POST /api/filaments/:id/spools`.
- `create_filament(payload)` — `POST /api/filaments` (set `parentId` for variants).

### 2. `core/weight.py` — pure net↔gross conversion (no I/O)

Implement the conversions from `CLAUDE.md`, as pure functions over numbers so they're
trivially testable:
- `spoolman_to_fdb_gross(remaining_weight, spool_weight) -> total_weight`
- `fdb_to_spoolman_net(total_weight, spool_weight, usage_grams_sum) -> remaining_weight`
- Default `spool_weight` to ~200g when missing (per Spoolman gotcha), and surface when a
  default was used (return a flag or named tuple) so the caller can log it.
- A `weight_changed(old, new, threshold)` helper that returns True only when
  `abs(old-new) >= threshold` (threshold from `sync_weight_threshold_grams` config).

### 3. `core/matcher.py` — fuzzy matching + vendor dedup (FR-3/FR-12)

- Normalize for comparison: lowercase, trim, collapse whitespace; vendor-alias folding
  (e.g. "ELEGOO" == "Elegoo"). Keep the normalization function public — the wizard reuses it.
- `match_filaments(spoolman, filamentdb)` → matched / unmatched-each-side / ambiguous,
  keyed on vendor + name + color. Return confidence so the wizard can sort.
- Pure over input lists (no network) so it unit-tests against `findings.md` fixtures.

### 4. `core/fields.py` — field-mapping resolution (FR-11)

- Resolve the effective FDB-field ↔ Spoolman-extra-field map from
  `settings.parsed_field_mappings` (explicit) layered over exact-name auto-matches, minus
  `settings.parsed_field_mapping_excludes`.
- Support dotted FDB paths (e.g. `temperatures.nozzle`).
- Direction follows `material_properties_source_of_truth`.
- Respect variant inheritance: never write a material prop onto a variant whose field is
  listed in that record's `_inherited[]` — skip and log instead (decisions-log rule).

### 5. `core/differ.py` — classify changes against the snapshot

- Input: current entities (from clients) + last `Snapshot` rows. Output: a structured
  changeset — `created`, `updated` (with per-field old/new), `conflict` (same field
  changed on both sides since last snapshot, FR-13), `unchanged`.
- Pure-ish: take fetched data + snapshot data in, return classifications. The engine does
  the persistence.

### 6. `core/engine.py` — the cycle (FR-8) with dry-run support

`run_sync_cycle(db: Session, *, dry_run: bool) -> CycleResult`:
1. Generate a `cycle_id` (UUID — pass it in or stamp inside; do NOT call
   `datetime.now()`-style nondeterminism into tests).
2. Fetch full state from both systems (`get_spools` with the implicit `limit=1000`,
   `get_filaments`); filter Spoolman `archived == false` for the active set.
3. Load last snapshots; run `differ` per entity.
4. For each change, pick direction from `BridgeConfig` source-of-truth keys:
   - weight → `weight_source_of_truth` (FR-9/FR-10, via `core/weight` + the usage endpoint
     for FDB decrements)
   - material props / mapped fields → `material_properties_source_of_truth` (FR-11)
   - new spools → `new_spool_source_of_truth` (FR-12; auto-match or queue conflict)
5. **Conflicts are NEVER auto-resolved** — write a `Conflict` row and a `SyncLog`
   `action="conflict"` entry; skip applying (hard rule from `CLAUDE.md`).
6. If `dry_run`: compute and return the full changeset + a `SyncLog`-shaped preview, but
   **apply nothing and do not advance the snapshot** (FR-14). If not dry_run: apply via
   clients, write `SyncLog` rows for every action, upsert `Snapshot` rows, commit.
7. Return counts: created / updated / conflicts / skipped / errors.

Keep the engine resilient (NFR-4): a single record's API error becomes a `SyncLog`
`action="error"` entry and the cycle continues — one bad record never aborts the run.

### 7. Wire the scheduler (gated OFF by default)

In `main.py`'s lifespan, after the clients open, register an interval job
(`SYNC_INTERVAL_SECONDS`) that:
- opens a `SessionLocal()` session,
- reads `auto_sync_enabled` from `BridgeConfig`; if false, logs `debug` and returns
  immediately (the job stays registered but is a no-op until enabled),
- otherwise calls `run_sync_cycle(db, dry_run=False)`.
Also call `spoolman.ensure_extra_fields()` once on startup.

**Async-job / sync-DB bridging — recommended approach (Option A).** The scheduler job is
`async` and runs on the asyncio event loop; the clients are async but SQLAlchemy is sync.
Make the cycle an `async def` that `await`s the client I/O and calls the sync SQLAlchemy
code **inline** — do NOT introduce a thread or a second sync HTTP client. SQLite writes
are microseconds, so the brief loop stall is harmless for a single-container homelab
service. (The `decisions.md` "sync `Depends` in a threadpool" note covers request
handlers, not this background job — it needs no threadpool.) Beyond the negligible
performance cost, the deciding factor is **troubleshooting**: an inline cycle is one
linear, awaitable call path — exceptions surface where they happen and stack traces stay
intact. Threading would split traces across the loop and a worker, surface errors a step
removed from their cause, and force a parallel sync `httpx.Client` to exist purely to make
the thread viable. Record this choice + rationale in `docs/decisions.md`. Only revisit
(Option B: offload to `asyncio.to_thread` with a sync `httpx.Client`) if a much larger
inventory ever makes a cycle long enough to visibly stall the loop.

### 8. Tests (this is where the suite starts)

Add `pytest` (+`pytest-asyncio` if needed) to `requirements.txt` and create
`backend/tests/`:
- `test_weight.py` — net↔gross both directions, default tare, threshold edges.
- `test_matcher.py` — case/whitespace/vendor-alias folding, matched/ambiguous/unmatched
  using fixtures shaped like `findings.md`.
- `test_fields.py` — explicit-over-auto, excludes, dotted paths, `_inherited[]` skip.
- `test_differ.py` — created/updated/conflict classification.
- `test_engine.py` — drive a cycle with **faked clients** (no live network): assert
  dry-run applies nothing, a weight decrease produces an FDB usage call, a both-sides
  change produces a `Conflict` row and zero writes, an API error is logged and the cycle
  survives. Use an in-memory or temp-file SQLite via the existing models.
- `cd backend && pytest` must pass.

## Conventions to honor

- Sync SQLAlchemy; async httpx clients (per the existing code + decisions log).
- No raw `json.loads`/`json.dumps` of Spoolman extra fields outside the client helper.
- Never overwrite FDB spool weight directly on a decrement — always the usage endpoint.
- Never auto-resolve a conflict. Never delete an upstream record.
- Don't touch the FDB `settings{}` bag; strip computed fields before any PUT.
- `func.now()` for DB-side timestamps; all UTC.
- Structured JSON logs to stdout; respect `LOG_LEVEL`.
- Keep `core/` modules pure where the plan says pure — push all I/O into the engine and
  clients so the logic stays unit-testable.

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/` (failure).
3. Record non-obvious decisions in `docs/decisions.md` (e.g. the async-job/sync-DB
   bridging approach, any conflict-key definition choices).
4. Propose ONE commit (no `Co-authored-by:`). Suggested message:
   `feat: Phase 2 — continuous sync engine (snapshot/diff/match/apply/conflict/log)`.
   Files: `core/*`, `services/*.py` (write methods), `main.py` (scheduler), `tests/*`,
   `requirements.txt`, `docs/decisions.md`, the prompt move. Present the file list and
   ask `commit these as "<message>"? (y/n)` before staging. Stage specific paths only;
   commit on `dev`; no push.
