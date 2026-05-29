# Decision record

Architecture / approach decisions for filament-bridge, newest at top. One entry per
non-obvious call: a change of approach, a rejected alternative, or a workaround. Keep
entries short — the *why*, not a tutorial. Part of the
[handoff-prompt-workflow](https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/handoff-prompt-workflow/README.md)
standard (see `standards.md`).

## 2026-05-29 — Phase 3 API: error envelope, conflict-resolve semantics, wizard state, backup format

Five decisions taken while building the bridge API layer (Phase 3):

1. **Error envelope.** Handled errors return `{"detail": {"code": <machine
   code>, "message": <human message>}}` via a single `api/errors.py:api_error()`
   helper. `code` is a stable string the UI branches on (e.g. `wizard_incomplete`,
   `manual_value_required`, `mapping_not_found`); `message` is for display.
   FastAPI's own validation (Pydantic `Literal`/`gt`) still returns its native
   422 shape — we don't wrap those.

2. **Conflict resolution = record now, apply on a later cycle.** `POST
   /conflicts/{id}/resolve` writes `resolution`/`resolved_value`/`resolved_at`
   on the row and drops it from the open queue, but performs **no upstream
   write** (honours the no-auto-resolve hard rule and keeps sync logic in
   `core/`). `resolved_value` is the chosen side's value (spoolman/filamentdb)
   or the supplied `manual` value. ⚠️ Engine gap: `core/engine` does not yet
   read resolved conflicts to push the chosen value upstream (and currently
   re-queues an unresolved weight conflict every cycle). Wiring the engine to
   consume resolutions is a Phase 2 follow-up — tracked, not done here.

3. **Wizard decision state lives in `BridgeConfig`, not a new table.** The
   wizard's direction (`import_direction`), match decisions
   (`wizard_match_decisions`), and variant groupings (`wizard_variant_decisions`)
   are persisted as JSON values in the existing key→JSON `BridgeConfig` store.
   Chosen over a dedicated `wizard_state` table to avoid an Alembic migration for
   transient setup data; Phase 3b reads these keys to execute (FR-7) and flips
   `wizard_completed`. The source-of-truth choices reuse the existing
   `*_source_of_truth` keys directly.

4. **Backup format.** `GET /backup/export` emits a versioned envelope
   (`schema_version = 1`) containing **bridge state only** — config, filament
   mappings, spool mappings, and *open* conflicts — never a copy of upstream
   data (CLAUDE.md). `POST /backup/import` is idempotent: mappings upsert by
   their unique business key (`spoolman_filament_id` / `spoolman_spool_id`)
   preserving ids so spool→filament FKs survive a clean restore; conflicts insert
   only when no equivalent open conflict exists (natural key: entity_type +
   field_name + the two ids). A mismatched `schema_version` is a 400.

5. **Mapping status enum (the `/mappings` + dashboard contract).** Precedence:
   `conflict` (an open Conflict references the spool) > `unlinked` (spool mapping
   has no parent filament mapping) > `pending` (a side has no snapshot yet) >
   `in_sync` (both snapshots present, no open conflict). Per-side weights and the
   name/vendor/color display fields come from the last **snapshots** (the
   Spoolman-side snapshot carries the filament detail; the FDB spool snapshot is
   trimmed), so the endpoint needs no live upstream fetch.

Test-harness note: the in-memory SQLite fixtures use `StaticPool` (one shared
connection) because FastAPI's `TestClient` runs sync handlers in a worker thread,
which would otherwise see its own empty `:memory:` database. `tests/conftest.py`
also `setdefault`s the required env vars so `cd backend && pytest` is
self-contained.

## 2026-05-29 — Async-job / sync-DB bridging approach (Option A — inline)

`run_sync_cycle` is a single `async def` that `await`s client I/O and calls
synchronous SQLAlchemy code inline — no thread, no second sync httpx client.
SQLite latency is microseconds; the only real bottleneck is the HTTP calls to
Spoolman and Filament DB. The brief loop stall is harmless for a single-container
homelab service. Rejected Option B (offload DB to `asyncio.to_thread` with a sync
httpx client) because it would split stack traces across the event loop and a worker
thread, surface errors a step removed from their cause, and require a parallel sync
`httpx.Client` purely to make the thread viable. Only revisit if a much larger
inventory (≫ 1000 spools) makes a cycle long enough to visibly stall the event loop.

## 2026-05-29 — Spoolman extra-field conflict-key definition (Phase 2)

The conflict `field_name` for a weight disagreement is `"weight"` (not
`"remaining_weight"` or `"totalWeight"`) so the resolution UI can display a
single unified weight conflict rather than two system-specific column names.
Field-mapping conflicts use the FDB dotted path (e.g. `"temperatures.nozzle"`)
as the key, which is the canonical name in the bridge's field-map config.

## 2026-05-28 — Canonical build-phase numbering (closes the skipped Phase 2)

The handoff prompts grew a numbering gap: Phase 0 (backend foundation) and Phase 1
(SQLite persistence) shipped, but the prompts then forward-referenced "Phase 3 (sync
engine)" and "Phase 4 (wizard API)" — there was never a Phase 2. The Phase 0 prompt only
mentioned Phase 2 in passing ("clients ... Phase 2 leans on this"). To keep the sequence
contiguous, the remaining work is renumbered to close the gap. This table is the single
source of truth for build-phase numbers; product-facing phases in `README.md` (guided
sync → dry run → auto-sync) and the migration-guide phases are separate schemes and are
unaffected.

| Build phase | Scope | Status |
|---|---|---|
| Phase 0 | Backend foundation — FastAPI skeleton, health (FR-1), upstream clients | ✅ done |
| Phase 1 | SQLite persistence — models, Alembic, config seed | ✅ done |
| Phase 2 | Continuous sync engine — snapshot/diff/match/apply/conflict/log (FR-8…FR-14) | next |
| Phase 3 | Bridge API layer — wizard read/decision endpoints (FR-1…FR-6) + sync/conflict/mappings/config/backup/log routers | planned |
| Phase 3b | Wizard execute (FR-7) — the initial-sync write to both upstreams; carved out for risk/isolation | planned |
| Phase 4 | Frontend SPA + `/static` mount (FR-15…FR-19) | planned |

The forward-references in the two completed prompts under `prompts/done/` were corrected
to match (sync engine 3→2, wizard 4→3, SPA 5→4).

## 2026-05-28 — Synchronous SQLAlchemy (not async) for the persistence layer

Used `create_engine` / `Session` rather than `create_async_engine` / `AsyncSession`.
SQLite latency is microseconds — the only real bottleneck is the HTTP calls to Spoolman
and Filament DB. Async SQLAlchemy + Alembic autogenerate also requires a sync
compatibility shim that adds complexity for zero practical gain. FastAPI runs sync
`Depends` handlers in a threadpool automatically, so sync DB sessions in route handlers
are safe without any extra wrapper.

## 2026-05-28 — Deep-link routes (corrects PRD NFR-7 / CLAUDE.md)

Verified against the live crzynet instances. The spec's guessed patterns were wrong:
- Filament DB filament: `{FILAMENTDB_URL}/filaments/{id}` — **plural**, not `/filament/{id}`.
- Spoolman spool: `{SPOOLMAN_URL}/spool/show/{id}` and filament `/filament/show/{id}` —
  **no hash routing** (newer Spoolman dropped `/#/`).
- Filament DB has **no standalone spool page** — spools render under the filament page.
  So bridge spool rows link to the parent filament page, not a per-spool URL.

## 2026-05-28 — Filament DB variant inheritance: read detail, strip computed fields

`GET /api/filaments/:id` resolves parent→variant inheritance server-side: the variant
response merges inherited values and names which ones in `_inherited[]` (plus `_parent`,
and `_variants[]` on the parent). The trimmed list view (`GET /api/filaments`) is for
enumeration only. Two rules for the bridge: (1) writing a material prop onto a variant
whose field is in `_inherited[]` overrides inheritance — check `_inherited[]` and
skip/flag instead of blindly writing; (2) strip computed/Mongoose fields before any PUT
(`_inherited`, `_parent`, `_variants`, `hasVariants`, `inherits`, `settings`, `__v`,
`instanceId`, `createdAt`, `updatedAt`, `_deletedAt`). Note `inherits` (a PrusaSlicer
preset name) is unrelated to the `parentId` variant tree — do not conflate.

## 2026-05-28 — Spoolman extra fields: create on startup, JSON-decode values

`GET /api/v1/field/spool` returns `[]` on the live instance — none of the bridge's
cross-ref fields exist. The bridge creates `filamentdb_id`, `filamentdb_parent_id`,
`filamentdb_spool_id` via `POST /api/v1/field/{entity_type}/{key}` on startup (chosen
over requiring manual UI setup — keeps deployment env-var-only). Spoolman stores text
extra-field values JSON-double-quoted (`"\"https://...\""`), so the bridge must
`json.loads()` them on read and `json.dumps()` on write, never use raw.

## 2026-05-28 — Sync engine defaults for the three design open questions

Defaults chosen now, revisitable later: (OQ#1) sync a weight change only when the delta
≥ a configurable threshold (default ~2g) to avoid rounding churn between net/gross
models. (OQ#6) full-snapshot diff each cycle — `GET /api/v1/spool?limit=1000` returns
all 223 spools fast enough; add incremental fetch only if a larger inventory demands it.
Note: `limit=1000` includes archived (active+archived both returned 223), so filter
`archived == false` client-side for the active set. (OQ#7) accept the aggregate weight
delta when multiple printers decrement one spool between cycles; per-printer attribution
is out of scope — documented, not silently dropped.

## 2026-05-28 — Docker base images: node:22-alpine (build) + python:3.12-slim-bookworm (runtime)

Multi-stage Dockerfile uses `node:22-alpine` for the React build stage (throw-away, never
ships) and `python:3.12-slim-bookworm` for the final runtime stage. Slim was chosen over
distroless/Chainguard because the service is still under active development — no shell
means no `exec`-based debugging, which is painful for a homelab sync tool. Revisit
distroless (`gcr.io/distroless/python3-debian12`) once the app is stable.

## 2026-05-28 — Canonical version file is `backend/app/__init__.py`

For the `release-prep-and-cut` standard, the bare version lives in
`backend/app/__init__.py` (`__version__ = "X.Y.Z"`). Chosen over `pyproject.toml`
(the backend uses `requirements.txt`, not pyproject) and a root `VERSION` file (the
FastAPI app would have to parse it at runtime, whereas `__version__` is a native
import that also feeds the in-app version display). The file doesn't exist yet — it's
created when the backend lands.
