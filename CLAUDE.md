# CLAUDE.md

filament-bridge is a bidirectional sync service between [Filament DB](https://github.com/hyiger/filament-db)
and [Spoolman](https://github.com/Donkie/Spoolman) for 3D-printing filament management. It runs
as a Docker sidecar alongside both systems, keeps their databases in sync, and queues conflicts
for manual resolution. This file is the per-session quick reference; deeper material lives in
`docs/` behind the pointers below.

> **When implementing a new functional requirement (FR-*) or questioning a requirement,**
> read `docs/prd.md` (the full spec). It is NOT required reading for routine changes.

## Standards (per-session rules)

This repo adopts crzynet `homelab-configs` standards. `standards.md` lists each standard + the
pinned version. The hard day-to-day rules:

**Code check-in (`code-checkin-and-pr`):**
- **Never push directly to `main`** — it's protected. Changes land via a `dev → main` PR with
  all required checks green. Day-to-day work is on `dev` (or a short branch off it); push to
  `dev` freely.
- **Conventional-commit prefixes required:** `feat:` / `fix:` / `chore:` / `docs:`.
- **No `Co-authored-by:` trailers** unless the user asks.
- **Docs ship in the same commit as the code they describe** — never as a follow-up.
- **Never bypass hooks** (`--no-verify` etc.) unless the user asks. Fix the underlying issue.
- Stable releases are tagged from `main` only.

**Other standards (full rules in the linked source; invoked on demand):**
- **Releases** — `release-prep-and-cut`: use `/release-prep <version>` then `/release-cut
  <version>`. Version stored bare (no `v` prefix) except the git tag; `CHANGELOG.md` is the
  single source of release notes. Never re-tag. Details in `.claude/commands/release-*.md` +
  `standards.md`.
- **Sandbox** — `repo-sandbox-permissions` (repo-wide): in-repo reads/edits/writes/bash run
  sandboxed; widen `allowedDomains`/`allowWrite` rather than adding `Bash(...)` allow rules.
- **Handoff prompts** — `handoff-prompt-workflow`: scoped tasks live in `prompts/` (from
  `TEMPLATE.md`), completed → `prompts/done/`; log non-obvious decisions in `docs/decisions.md`.

If unsure whether an action violates one of these, stop and ask.

## Key concepts

- **Filament DB** — Next.js 14 / MongoDB. REST at `/api/`. Spools are embedded subdocuments on
  filament records (not a separate collection). MongoDB ObjectIds (24-char hex). Weight model is
  **GROSS** (filament + reel tare). API unauthenticated (optional bearer key).
- **Spoolman** — Python/FastAPI. REST at `/api/v1/`. Relational Vendor → Filament → Spool with
  auto-increment int IDs. Weight model is **NET** (filament only). Extra-fields system for custom
  data on any entity. API unauthenticated.
- **Minimum supported versions** — Filament DB **≥ 1.33.0**, Spoolman **≥ 0.22.0** (`core/version.py`:
  `MIN_FDB`, `MIN_SPOOLMAN`). When a *known* upstream version is below its minimum, **sync is
  hard-gated** (cycle, trigger/dry-run endpoints, and wizard execute all refuse; auto-sync
  skipped) — the bridge still starts and the UI/health load with a warning. An unknown/unreadable
  version does NOT block (that's a connectivity concern → health `degraded`).
- **Sync engine** — polls both APIs on an interval, diffs against the last snapshot, applies
  non-conflicting changes, queues conflicts.
- **Cross-reference IDs** — Spoolman extra fields (`filamentdb_id`, `filamentdb_parent_id`,
  `filamentdb_spool_id`) link to FDB; the FDB spool `label` field (configurable) stores the
  Spoolman spool ID.
- **Variant model** — FDB has parent/variant inheritance via `parentId` (one parent, multiple
  color variants, one level deep). Spoolman is flat one-filament-per-color. The bridge tracks the
  parent via the `filamentdb_parent_id` extra field. See `docs/variant-parent-mode.md`.

## Architecture decisions

- **No upstream modifications** — documented REST APIs + Spoolman extra fields only. Never fork
  or patch either system.
- **Three-phase sync** — Bulk Import Wizard (re-runnable) → validation dry run → user-enabled
  auto-sync. Auto-sync is OFF by default and requires explicit user action.
- **Conflicts are never auto-resolved** — queued for human decision. Hard rule; no silent
  resolution.
- **Weight decrements from Spoolman create usage-log entries in Filament DB** (via
  `POST /api/filaments/:id/spools/:spoolId/usage`), never raw weight overwrites — preserves FDB's
  audit trail.
- **Sync direction and conflict policy are user-configurable** per data category via Settings (two
  independent axes: `direction` and `conflict_policy`), resolved by
  `core/sync_policy.py:resolve_sync_action`. The wizard captures the initial import direction only.
- **Configuration via env vars** — the service refuses to start without `FILAMENTDB_URL` /
  `SPOOLMAN_URL`. No config file; no DB-stored connection URLs.
- **Never delete records** in either upstream system without explicit user action in the bridge UI.

## Tech stack

- **Backend:** Python 3.12+ / FastAPI, httpx (async clients), SQLAlchemy + SQLite (sync state),
  APScheduler (intervals), Pydantic v2.
- **Frontend:** React 18+ / TypeScript, Vite, Tailwind, React Router.
- **Deployment:** Docker multi-stage build (Node builds React → FastAPI serves it + static assets
  from `/static`), single container, single port (default 8090), SQLite in a mounted volume at
  `/data/bridge.db`.

## Project structure

Top-level map — explore with `ls`/glob for specifics (per-file descriptions live in the modules'
own docstrings):

```
backend/app/
  api/          — FastAPI routers (one per feature: sync, conflicts, mappings, config, wizard,
                  backup, health, auth, debug, opentag, sync_log, tare, mobile, labels,
                  reconcile, version, errors)
  core/         — sync engine + logic (engine, sync_policy, conflict_apply, planner, dryrun,
                  differ, matcher, weight, fields, color, material_tags, locations, masters,
                  version/compat, opentag_*, backup_job, change_log, state_dump, …)
  schemas/      — Pydantic models (bridge API, FDB & Spoolman shapes)
  models/       — SQLAlchemy: mapping, conflict, sync_log, snapshot, config
  services/     — async httpx clients: filamentdb.py, spoolman.py
  main.py       — app init, scheduler, static mount   config.py — env parsing + startup validation
  alembic/      — SQLite migrations
frontend/src/
  pages/        — one per screen (Wizard/, Dashboard, SyncedRecords, Conflicts, SyncLog,
                  Settings, OpenTagCleanup, Reconcile, TareEditor, MobileUpdates, Login, …)
  components/   — DeepLinks, StatusBadge, …    api/ — typed fetch wrappers    App.tsx — router
docs/           — see docs/README.md for the index
prompts/        — handoff-prompt queue (TEMPLATE.md, done/, assets/)
standards.md    — pinned homelab standards this repo implements
```

## Configuration

The bridge takes **two required** env vars — `FILAMENTDB_URL` and `SPOOLMAN_URL` — and refuses to
start without them. `FILAMENTDB_API_KEY` (optional) adds a bearer header to FDB requests. The
cross-reference field-name defaults are `filamentdb_id` / `filamentdb_parent_id` /
`filamentdb_spool_id` (Spoolman extras) and `label` (FDB spool field).

**Everything else — the full env-var list, the runtime-editable BridgeConfig settings (DB value
wins over env), field mappings, OpenPrintTag extra fields, backup/mobile/LabelForge settings — is
in [`docs/configuration.md`](docs/configuration.md).** That file is the single source of truth;
don't duplicate its tables here.

## Sync engine — hard invariants

These are load-bearing (violating them caused real ping-pong / double-count bugs). Mechanics —
the full pass order, snapshot builders, lifecycle/location passes, version gating — are in
[`docs/sync-model.md`](docs/sync-model.md).

- **Weight model:** SM `remaining_weight` is net; FDB `totalWeight` is gross; filament-level
  `spoolWeight` is the reel tare. SM→FDB: `totalWeight = remaining_weight + spoolWeight`.
  FDB→SM: `remaining_weight = totalWeight - spoolWeight`.
- **DO NOT also subtract `sum(usageHistory.grams)`.** FDB already reduces `totalWeight` directly
  when a usage entry is logged, so `totalWeight` is the *current* gross; subtracting usage on top
  double-counts it (caused a runaway compounding decrement loop, fixed 2026-06-10). `usageHistory`
  is an audit trail only.
- **Weight decrements from Spoolman → FDB usage entries** (`source: "spoolman"`), never raw
  weight overwrites. Weight *increases* update `totalWeight` directly (no negative usage).
- **After ANY propagation (weight, lifecycle, or location), refresh BOTH side snapshots to the
  post-write agreed values** — otherwise the change is re-detected on the other side next cycle →
  ping-pong.
- **Lifecycle pass runs AFTER the weight pass** (a spool is usually archived right as it hits ~0 g,
  so the final decrement + its usage entry must settle first). Location pass is independent of
  weight (no ordering requirement).
- **Scoped `settings{}` exception:** the only permitted writer to the FDB filament `settings{}` bag
  is `FilamentDBClient.merge_filament_settings()`, and only for the two OpenTag identity keys
  (`openprinttag_slug` / `openprinttag_uuid`). See "What NOT to do".

**Upstream API endpoint lists + data-model gotchas** (embedded-spool model, `?limit=1000`,
`?allow_archived=true`, vendor dedup, deep-link routes, …) are in
[`docs/upstream-apis.md`](docs/upstream-apis.md). The two that bite most often: Spoolman
`GET /api/v1/spool` **paginates — always pass `?limit=1000`**, and **archived spools need
`?allow_archived=true`** (no `archived` filter param exists).

## Development workflow

```bash
# Backend (dev):  cd backend && uvicorn app.main:app --reload --port 8090
# Frontend (dev): cd frontend && npm run dev            # Vite proxies API to backend
# Required env:   FILAMENTDB_URL=http://localhost:3000 SPOOLMAN_URL=http://localhost:7912
# Tests:          cd backend && .venv/bin/python -m pytest        # lint: .venv/bin/python -m ruff check backend/
#                 cd frontend && npx vitest run && npx tsc --noEmit
# Docker image:   docker build -t filament-bridge .
# DB migration:   cd backend && alembic revision --autogenerate -m "desc" && alembic upgrade head
```

## What NOT to do

- Don't modify Filament DB or Spoolman source code — all integration via REST APIs only.
- Don't auto-resolve conflicts — always queue for user decision.
- Don't delete records in upstream systems without explicit user action.
- Don't overwrite Filament DB spool weights directly — always use the usage endpoint to preserve
  the audit trail.
- Don't assume Spoolman extra fields exist — check on startup.
- Don't store upstream API data in SQLite beyond what's needed for diffing — the bridge stores
  snapshots and mappings, not a full copy of both databases.
- Don't touch the `settings{}` bag on Filament DB filaments — it's slicer passthrough data.
  **SCOPED EXCEPTION (approved 2026-06-06):** `FilamentDBClient.merge_filament_settings()` is the
  single permitted path, and it MAY only merge the two OpenTag identity keys
  (`openprinttag_slug` / `openprinttag_uuid`) into the bag (read-modify-write, preserving ALL other
  keys, idempotent). Called by the OpenTag cleanup apply endpoint and the sync engine's
  `_sync_opentag_identity` pass. No other code may write to `settings{}`. See `docs/decisions.md`.

## Historical / do-not-read-unprompted

To keep sessions cheap, do **not** read these unless a task explicitly points you at one:
`prompts/done/` (completed handoffs), `docs/wizard-redesign.md` and `docs/reconcile-backlog.md`
(historical design notes — `docs/decisions.md` is authoritative), and `docs/CHANGELOG-0.*.md`
(archived changelogs). `docs/decisions.md` is large — search it for the relevant dated entry
rather than reading it whole.
