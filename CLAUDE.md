# CLAUDE.md

## Project overview

filament-bridge is a bidirectional sync service between [Filament DB](https://github.com/hyiger/filament-db) and [Spoolman](https://github.com/Donkie/Spoolman) for 3D printing filament management. It runs as a Docker sidecar alongside both systems, keeps their databases in sync, and handles conflict resolution.

**Read `docs/prd.md` before writing any code.** It contains the full functional requirements, prioritization (P0/P1/P2), data flow diagrams, and open questions. This file is the quick-reference; the PRD is the spec.

## Standards

This project adopts engineering standards from the crzynet `homelab-configs` repo. **Read [`standards.md`](standards.md) at session start** whenever the work could touch branching, commits, PRs, releases, or handoff prompts — it lists every standard and the pinned version this repo actually implements. The hard per-session rules are inlined below; the rest is linked, not restated.

<!--
Source: standards/code-checkin-and-pr @ v1.1.0 (crzynet/homelab-configs).
Paste the section below verbatim into the adopting project's CLAUDE.md.
The full standard (publishing matrix, retention, CI check definitions) lives at:
https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/code-checkin-and-pr/README.md
-->

### Code check-in (operational rules)

This project adopts the `code-checkin-and-pr` standard. The full why-and-how lives at
the source above; the rules below are the per-session do/don'ts a coding agent must
honor by default:

- **Never push directly to `main`.** `main` is protected. All changes land via a pull
  request from `dev` → `main`, and only when every required check is green.
- **Day-to-day work happens on `dev`** (or a short-lived branch off `dev`). Push to
  `dev` freely.
- **Commit message prefixes are required** — Conventional-Commits style:
  - `feat:` — new user-facing feature
  - `fix:` — bug fix
  - `chore:` — config, tooling, dependencies, maintenance
  - `docs:` — documentation-only changes
- **Do not add `Co-authored-by:` trailers** unless the user explicitly asks.
- **Doc updates ship in the same commit as the code they describe** — never as a
  follow-up commit.
- **Never bypass hooks** (no `--no-verify`, `--no-gpg-sign`, etc.) unless the user
  explicitly asks. If a hook fails, fix the underlying issue.
- **Stable releases are tagged from `main` only.** Don't tag from `dev`.

If you're unsure whether an action would violate one of the above, stop and ask before
acting.

<!--
Source: standards/release-prep-and-cut @ v1.0.0 (crzynet/homelab-configs).
Paste the section below verbatim into the adopting project's CLAUDE.md.
The full standard (two-phase prep/cut workflow, archive trigger, validation
steps, adoption checklist) lives at:
https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/release-prep-and-cut/README.md
-->

### Release process (operational rules)

This project adopts the `release-prep-and-cut` standard. The full why-and-how
lives at the source above; the rules below are the per-session do/don'ts a
coding agent must honor by default:

- **The version is stored BARE in the source-of-truth file** — no `v` prefix
  anywhere in code. The `v` prefix is added in exactly one place: the git tag
  and matching GitHub release name. Don't add it to README badges, CHANGELOG
  headers, in-code image tags, or anywhere else.
- **`CHANGELOG.md` is the single source of truth for release notes.** The PR
  description (set by `/release-prep`) and the GitHub release body (set by
  `/release-cut`) reuse the **same section verbatim**. Never author release
  notes twice.
- **One commit per release prep.** Version bump + changelog roll + every doc
  sync ship in a single `chore(release): prepare v<version>` commit. No
  `Co-authored-by:` trailers.
- **Never re-tag.** If `v<version>` already exists as a local tag, a remote
  tag, or a GitHub release, STOP. Never delete-and-recreate; never `--force`.
  Pick the next version instead.
- **`/release-cut` only after the PR has merged and CI is green.** The
  publish-to-`main` workflow must have already pushed `:latest` images to the
  registry before `/release-cut` runs. If you cannot confirm both — STOP and
  tell the user to wait.
- **The release tag is the only thing the cut command writes to `main`.** Both
  the prep commit and any follow-up docs commit land on `dev` and reach `main`
  only via PR. Never push directly to `main` as part of a release.

If you're unsure whether an action would violate one of the above, stop and
ask before acting.

### Sandbox permissions

This project adopts the
[`repo-sandbox-permissions`](https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/repo-sandbox-permissions/README.md)
standard — **scope: repo-wide** (`.claude/settings.json`). Routine in-repo file reads,
edits, writes, and bash commands run sandboxed without prompts; writes outside the repo
and network access stay gated (registries allow-listed in `allowedDomains`). The model is
**confinement, not command-guessing** — don't add `Bash(...)` allow/deny patterns to work
around a prompt; if a command needs to escape the box, widen the sandbox's
`allowedDomains`/`allowWrite` instead. The pinned version + filled-in scope live in
`standards.md`; no `CLAUDE-snippet.md` is shipped for this standard.

### Handoff prompts

This project follows the
[`handoff-prompt-workflow`](https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/handoff-prompt-workflow/README.md)
standard for scoped work: plan → decide → execute → document. Pending tasks live in
`prompts/` (one file per task, from `prompts/TEMPLATE.md`); completed ones move to
`prompts/done/` (or `prompts/failed/`). Non-obvious decisions get logged in
[`docs/decisions.md`](docs/decisions.md). See the standard for the full why.

## Key concepts

- **Filament DB** — Next.js 14 / MongoDB app for filament profile management, slicer integration, calibrations, NFC tags. REST API at `/api/`. Spools are embedded subdocuments on filament records (not a separate collection). Uses MongoDB ObjectIds (24-char hex). Weight model is GROSS (filament + reel tare). API is unauthenticated. [API docs](https://github.com/hyiger/filament-db/blob/main/docs/api.md)
- **Spoolman** — Python/FastAPI app for spool inventory tracking with native OctoPrint/Moonraker integration. REST API at `/api/v1/`. Relational model: Vendor → Filament → Spool with auto-increment integer IDs. Weight model is NET (filament only, reel excluded). Extra fields system for custom data on any entity. API is unauthenticated. [API docs](https://donkie.github.io/Spoolman/)
- **Sync engine** — polls both APIs on a configurable interval, diffs state against last snapshot, applies non-conflicting changes, queues conflicts for manual resolution.
- **Cross-reference IDs** — Spoolman extra fields (`filamentdb_id`, `filamentdb_parent_id`, `filamentdb_spool_id`) link to Filament DB. Filament DB spool `label` field (configurable) stores Spoolman spool ID.
- **Variant model** — Filament DB has parent/variant inheritance via `parentId` field (one parent, multiple color variants, one level deep only). Spoolman has flat one-filament-per-color. Bridge tracks the parent relationship via `filamentdb_parent_id` extra field in Spoolman.

## Architecture decisions

- **No upstream modifications** — bridge only uses documented REST APIs and Spoolman's extra field system. Never fork or patch Filament DB or Spoolman.
- **Three-phase sync** — Bulk Import Wizard (re-runnable) → validation dry run → user-enabled auto-sync. Auto-sync is OFF by default and requires explicit user action to enable.
- **Conflicts are never auto-resolved** — queued for human decision with optional Discord notification. This is a hard rule — do not implement silent conflict resolution.
- **Weight decrements from Spoolman create usage log entries in Filament DB** (via `POST /api/filaments/:id/spools/:spoolId/usage`), never raw weight overwrites. This preserves Filament DB's usage history audit trail.
- **Sync direction and conflict policy are user-configurable** per data category via Settings (two independent axes: `direction` and `conflict_policy`). Resolved by `core/sync_policy.py:resolve_sync_action`. The Bulk Import Wizard captures the initial import direction only; the ongoing two-axis model lives in Settings.
- **Configuration via environment variables** — service refuses to start without required vars (`FILAMENTDB_URL`, `SPOOLMAN_URL`). No config file. No database-stored config for connection URLs.
- **Never delete records** in either upstream system without explicit user action in the bridge UI.

## Tech stack

- **Backend:** Python 3.12+ / FastAPI, httpx for async API clients, SQLAlchemy + SQLite for sync state, APScheduler for sync intervals, Pydantic v2 for data models and API response validation
- **Frontend:** React 18+ / TypeScript, Vite build tooling, Tailwind CSS, React Router for navigation
- **Deployment:** Docker multi-stage build (Node builds React → Python serves FastAPI + static assets from `/static`), single container, single port (default 8090), SQLite database in a mounted volume at `/data/bridge.db`

## Project structure

```
filament-bridge/
├── .gitignore
├── README.md                               — open source project README
├── CLAUDE.md                               — this file (read first)
├── Dockerfile                              — multi-stage build (Node + Python)
├── docker-entrypoint.sh                    — chown-then-gosu entrypoint (PUID/PGID → non-root user)
├── docker-compose.yml                      — standard bridge-only deployment (published image, external Spoolman/FDB)
├── docker-compose.dev.yml                  — full local dev stack (bridge build:. + Spoolman + Filament DB + Mongo)
├── backend/
│   ├── app/
│   │   ├── api/                            — FastAPI routers
│   │   │   ├── sync.py                     — trigger sync, dry run, enable/disable auto-sync
│   │   │   ├── conflicts.py                — list, resolve, bulk-resolve conflicts
│   │   │   ├── mappings.py                 — view/edit spool and filament mappings
│   │   │   ├── config.py                   — runtime config (direction+policy, field mappings)
│   │   │   ├── backup.py                   — export/import bridge state
│   │   │   ├── health.py                   — connectivity check for both upstream APIs
│   │   │   ├── opentag.py                  — OpenTag cleanup tool (matches, refresh, apply)
│   │   │   ├── sync_log.py                 — audit log viewer (FR-17)
│   │   │   ├── wizard.py                   — Bulk Import Wizard read/decision endpoints (FR-1–FR-6)
│   │   │   ├── debug.py                    — gated reset tools (403 unless debug_mode is on)
│   │   │   └── errors.py                   — consistent error envelope for the bridge API
│   │   ├── core/
│   │   │   ├── engine.py                   — main sync loop: snapshot, diff, apply, log
│   │   │   ├── sync_policy.py              — two-axis direction+policy resolver (resolve_sync_action)
│   │   │   ├── planner.py                  — wizard execution planner (shared by FR-7 and FR-14)
│   │   │   ├── dryrun.py                   — dry-run preview helpers (FR-14)
│   │   │   ├── differ.py                   — diff two snapshots, classify changes
│   │   │   ├── matcher.py                  — fuzzy matching for import wizard (vendor+name+color)
│   │   │   ├── weight.py                   — net↔gross weight conversion logic
│   │   │   ├── fields.py                   — field mapping resolution (auto-match + explicit)
│   │   │   ├── color.py                    — multicolor/gradient conversion (FDB ↔ Spoolman)
│   │   │   ├── material_tags.py            — finish-tag detection and serialization
│   │   │   ├── version.py                  — FDB semantic-version comparison helpers
│   │   │   ├── opentag_match.py            — OPTMaterial → Spoolman field mapper + scorer
│   │   │   ├── opentag_cache.py            — local OpenTag dataset cache (JSON, TTL-gated)
│   │   │   └── opentag_secondary.py        — secondary-color recovery from the raw OPT tarball
│   │   ├── models/
│   │   │   ├── mapping.py                  — SpoolMapping, FilamentMapping (cross-reference IDs)
│   │   │   ├── conflict.py                 — Conflict queue entries
│   │   │   ├── sync_log.py                 — audit log of all sync actions
│   │   │   ├── snapshot.py                 — last-known state of each spool/filament
│   │   │   └── config.py                   — persisted runtime config (source of truth choices)
│   │   ├── services/
│   │   │   ├── filamentdb.py               — async httpx client for Filament DB REST API
│   │   │   └── spoolman.py                 — async httpx client for Spoolman REST API
│   │   ├── main.py                         — FastAPI app init, scheduler setup, static file mount
│   │   └── config.py                       — env var parsing, startup validation
│   ├── requirements.txt
│   └── alembic/                            — SQLite schema migrations
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── DeepLinks.tsx               — Filament DB + Spoolman icon links (used everywhere)
│   │   │   ├── StatusBadge.tsx             — sync status indicators (green/yellow/red/grey)
│   │   │   └── ...
│   │   ├── pages/
│   │   │   ├── Wizard/                     — Bulk Import Wizard (re-runnable; FR-1 through FR-7)
│   │   │   ├── Dashboard.tsx               — sync status overview (FR-15)
│   │   │   ├── SyncedRecords.tsx           — paired records table (FR-19)
│   │   │   ├── Conflicts.tsx               — conflict queue and resolution (FR-16)
│   │   │   ├── SyncLog.tsx                 — audit log viewer (FR-17)
│   │   │   ├── Settings.tsx                — runtime settings (direction+policy, debug, interval, etc.)
│   │   │   └── OpenTagCleanup.tsx          — OpenTag cleanup tool UI (FR-23b)
│   │   ├── api/                            — typed fetch wrappers for bridge backend API
│   │   └── App.tsx                         — router setup, layout
│   ├── package.json
│   ├── tsconfig.json
│   ├── tailwind.config.js
│   └── vite.config.ts
├── docs/
│   ├── prd.md                              — full product requirements (READ THIS)
│   ├── spoolman-writes.md                  — every field the bridge writes to Spoolman, and when
│   └── migration-spoolman-to-filamentdb.md — standalone migration guide
└── private_data/                           — gitignored, user-specific test data
```

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `FILAMENTDB_URL` | **Yes** | — | Base URL of Filament DB (e.g., `http://filament-db:3000`) |
| `SPOOLMAN_URL` | **Yes** | — | Base URL of Spoolman (e.g., `http://spoolman:7912`) |
| `SYNC_INTERVAL_SECONDS` | No | `120` | Seconds between auto-sync cycles (also runtime-editable via Settings) |
| `PUID` | No | `1000` | User ID the container process runs as (entrypoint chowns `/data` then drops to this UID) |
| `PGID` | No | `1000` | Group ID the container process runs as |
| `SPOOLMAN_FIELD_FILAMENTDB_ID` | No | `filamentdb_id` | Spoolman extra field name for Filament DB filament ID |
| `SPOOLMAN_FIELD_FILAMENTDB_PARENT_ID` | No | `filamentdb_parent_id` | Spoolman extra field for parent filament ID |
| `SPOOLMAN_FIELD_FILAMENTDB_SPOOL_ID` | No | `filamentdb_spool_id` | Spoolman extra field for spool subdocument ID |
| `FILAMENTDB_SPOOLMAN_ID_FIELD` | No | `label` | Filament DB spool field to store Spoolman spool ID |
| `FIELD_MAPPINGS` | No | — | Comma-separated `fdb_field=spoolman_field` pairs |
| `FIELD_MAPPING_EXCLUDES` | No | — | Comma-separated field names to exclude from auto-match |
| `VARIANT_LINE_KEYWORDS` | No | (seed list) | Comma-separated words marking distinct variant lines (e.g. `silk,matte,rapid`). Filaments whose names match different keywords won't be grouped together. Overridable at runtime via Settings. |
| `SPOOLMAN_FIELD_FILAMENTDB_MATERIAL_TAGS` | No | `filamentdb_material_tags` | Spoolman filament-level extra field storing finish-tag IDs (JSON list of ints) |
| `MATERIAL_TAG_IDS` | No | (seed list) | CSV of `keyword=id` pairs overriding the default keyword→OpenPrintTag-ID map for finish detection. Empty = use seed defaults from `core/material_tags.py`. |
| `OPENTAG_VENDOR_ALIASES` | No | — | CSV of `spoolman_vendor=opentag_brand` pairs for OpenTag brand pre-filter (e.g. `prusa=prusament`). Normalised on both sides; blank = no aliases. Overridable at runtime via Settings. |
| `SPOOLMAN_FIELD_OPENPRINTTAG_SLUG` | No | `openprinttag_slug` | Spoolman filament extra field for the OpenPrintTag material slug |
| `SPOOLMAN_FIELD_OPENPRINTTAG_UUID` | No | `openprinttag_uuid` | Spoolman filament extra field for the OpenPrintTag material UUID |
| `OPENTAG_CACHE_MAX_AGE_HOURS` | No | `24` | Hours before the local OpenTag dataset cache is considered stale |
| `DISCORD_WEBHOOK_URL` | No | — | Discord webhook for conflict/error notifications (declared; not yet implemented) |
| `LOG_LEVEL` | No | `info` | Logging level (debug, info, warn, error) |
| `DATA_DIR` | No | `/data` | Directory for SQLite database and backup files |

### Runtime-editable settings (BridgeConfig)

Several settings can be changed at runtime via the Settings UI (stored in SQLite, env vars are the start-up fallback):

| Setting | Default | Description |
|---|---|---|
| `sync_interval_seconds` | env fallback (`120`) | Auto-sync interval; applied immediately on save |
| `debug_mode` | `false` | Enables `POST /api/debug/clear-spoolman-fdb-refs` and `POST /api/debug/reset-bridge-state` (403 when off) |
| `never_import_empties` | `false` | Wizard skips spools with zero remaining weight at preview/execute |
| `sync_log_retention_days` | `30` | Sync log entries older than this are pruned automatically |

## Important technical details

### Weight model translation
Spoolman `remaining_weight` is net filament. Filament DB `totalWeight` is gross (filament + reel). The filament-level `spoolWeight` field is the empty reel tare weight.
- Spoolman → Filament DB: `totalWeight = remaining_weight + spoolWeight`
- Filament DB → Spoolman: `remaining_weight = totalWeight - spoolWeight - sum(usageHistory.grams)`
- Weight decrements from Spoolman are logged as usage entries in Filament DB with `source: "spoolman"`
- Weight increases (user added filament, correction) should update totalWeight directly, not create negative usage entries

### Filament DB API endpoints the bridge uses
- `GET /api/filaments` — list all filaments with embedded spools
- `GET /api/filaments/:id` — single filament with full detail
- `POST /api/filaments` — create filament (set `parentId` for variants)
- `PUT /api/filaments/:id` — update filament properties
- `GET /api/spools/export-csv` — all active spools with labels, weights, locations
- `POST /api/spools/import` — bulk spool CSV import (columns: filament, vendor, totalWeight, label, lotNumber, location)
- `POST /api/filaments/:id/spools` — add a single spool to a filament
- `PUT /api/filaments/:id/spools/:spoolId` — update spool properties
- `POST /api/filaments/:id/spools/:spoolId/usage` — log usage `{ grams, jobLabel, source, date }`
- `POST /api/print-history` — log print job with multi-spool usage array
- `GET /api/filaments/:id/spool-check?weight=N` — check if spool has enough filament
- `GET /api/locations` — list locations (add `?stats=true` for spool counts/grams)
- `PUT /api/locations/:id` — update location properties (e.g., humidity)
- `DELETE /api/filaments/:id` — soft-delete only (sets `_deletedAt`)

### Spoolman API endpoints the bridge uses
- `GET /api/v1/spool?limit=1000` — list spools (MUST set limit, default paginates)
- `GET /api/v1/spool/{id}` — single spool with nested filament and vendor
- `PATCH /api/v1/spool/{id}` — update spool (remaining_weight, extra fields, location, etc.)
- `POST /api/v1/spool` — create spool (requires filament_id)
- `GET /api/v1/filament` — list filaments with nested vendor
- `GET /api/v1/filament/{id}` — single filament
- `POST /api/v1/filament` — create filament
- `GET /api/v1/vendor` — list vendors
- `POST /api/v1/vendor` — create vendor
- `GET /api/v1/export/spools?fmt=csv` — CSV export (all spools, no pagination limit)
- `PUT /api/v1/spool/{id}/use` — decrement weight (used by OctoPrint/Moonraker, NOT by bridge)
- Note: `?archived=true` returns ONLY archived spools, not "include archived"

### Filament DB data model gotchas
- Spools are embedded subdocuments in the `spools[]` array on the filament document — there is no standalone spool collection or endpoint. Every spool operation goes through `/api/filaments/:filamentId/spools/:spoolId`.
- No spool label lookup endpoint — to find a spool by label, fetch all filaments or use the CSV export and filter client-side.
- Variant deletion is blocked (400) if the parent still has variants — must remove/reassign variants first.
- `DELETE /api/filaments/:id` is a soft-delete (sets `_deletedAt`), not permanent. Returns 400 if filament has variants.
- The `settings{}` bag on filaments is a passthrough for slicer-specific keys — unknown keys round-trip without modification. Don't touch this in sync, except via the scoped `merge_filament_settings()` path for the two OpenTag identity keys (see "What NOT to do" below).
- The `spoolWeight` and `netFilamentWeight` fields are on the FILAMENT, not individual spools. All spools of the same filament share the same tare weight.
- Spool subdocument `_id` values are stable across filament updates (Mongoose doesn't regenerate them on parent save).

### Spoolman data model gotchas
- Extra fields must be created via the Spoolman API or UI BEFORE they can be written to on a spool/filament. The bridge should check for required extra fields on startup and warn (or offer to create them) if missing.
- `GET /api/v1/spool` paginates — the default limit may not return all spools. Always pass `?limit=1000` or implement pagination.
- Vendor deduplication is extremely common — same vendor appearing with different IDs due to case differences ("ELEGOO" vs "Elegoo"), whitespace, or duplicate manual entries. The bridge matcher needs to handle this.
- Spoolman spool has `remaining_weight` (current net) and `used_weight` (total consumed). OctoPrint calls `PUT /api/v1/spool/{id}/use` which decrements remaining and increments used.
- Spoolman filament has `spool_weight` (tare) which may or may not be set. Default to ~200g if missing during weight conversion.

### Deep links (UI requirement)
Every record in the bridge UI must show two clickable icons linking to that record in each upstream system. Routes verified against live instances (see `docs/decisions.md`):
- Filament DB: `{FILAMENTDB_URL}/filaments/{filamentdb_id}` (plural). Filament DB has **no standalone spool page** — spools render under the filament page, so spool rows link to the parent filament URL.
- Spoolman: `{SPOOLMAN_URL}/spool/show/{spoolman_spool_id}` or `{SPOOLMAN_URL}/filament/show/{spoolman_filament_id}` (no hash routing).
- URLs are constructed from the `FILAMENTDB_URL` and `SPOOLMAN_URL` env vars
- Open in new tabs

## Development workflow

### Running locally for development

1. Start Filament DB and Spoolman (Docker or local instances)
2. Backend: `cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload --port 8090`
3. Frontend: `cd frontend && npm install && npm run dev` (Vite proxies API calls to backend)
4. Set required env vars: `FILAMENTDB_URL=http://localhost:3000 SPOOLMAN_URL=http://localhost:7912`

### Building the Docker image

```bash
docker build -t filament-bridge .
```

### Running tests

```bash
cd backend && pytest
cd frontend && npm test
```

### Database migrations

SQLite schema changes go through Alembic:
```bash
cd backend && alembic revision --autogenerate -m "description"
cd backend && alembic upgrade head
```

## What NOT to do

- Don't modify Filament DB or Spoolman source code — all integration via REST APIs only
- Don't auto-resolve conflicts — always queue for user decision
- Don't delete records in upstream systems without explicit user action
- Don't overwrite Filament DB spool weights directly — always use the usage endpoint to preserve audit trail
- Don't assume Spoolman extra fields exist — check on startup
- Don't store upstream API data in SQLite beyond what's needed for diffing — the bridge stores snapshots and mappings, not a full copy of both databases
- Don't touch the `settings{}` bag on Filament DB filaments — it's slicer passthrough data.
  **SCOPED EXCEPTION (approved 2026-06-06):** `FilamentDBClient.merge_filament_settings()` is the
  single permitted path, and it MAY only merge the two OpenTag identity keys
  (`openprinttag_slug` / `openprinttag_uuid`) into the bag (read-modify-write, preserving ALL other
  keys, idempotent). Called by the OpenTag cleanup apply endpoint and the sync engine's
  `_sync_opentag_identity` pass. No other code may write to `settings{}`. See `docs/decisions.md`.
