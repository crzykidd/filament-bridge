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

<!--
Source: standards/vexp-context-engine @ v2.0.0 (crzynet/homelab-configs).
Paste the section below verbatim into the adopting project's CLAUDE.md.
The full standard (scope, the two pushes, the manifest-not-tracked shape,
adoption + gate + verification procedure) lives at:
https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/vexp-context-engine/README.md
-->

### Context search (operational rules)

This project adopts the `vexp-context-engine` standard. The full why-and-how lives at the
source above; the rules below are the per-session do/don'ts a coding agent must honor by
default:

- **Call `run_pipeline` FIRST for any code task** — bug fixes, features, refactors,
  debugging, "how does X work", "where is Y". It runs context search + impact analysis +
  memory recall in one call and returns ranked, compressed context.
- **Do NOT `grep`, `glob`, or `cat` to explore the codebase.** vexp returns pre-indexed,
  graph-ranked context that is more relevant and cheaper than manual searching. A
  `PreToolUse` guard hook blocks `Grep`/`Glob` while the vexp daemon is healthy; if the
  daemon is down it allows the fallback.
- **Prefer `get_skeleton` over `Read` to inspect files** (minimal/standard/detailed —
  70–90% fewer tokens). Use `Read` only when you need exact raw content to edit a specific
  line.
- **Don't chain vexp calls or fan out `Explore` agents to free-search.** One
  `run_pipeline` replaces capsule + impact + memory; if a subagent needs context, run
  `run_pipeline` first and pass the result into the agent's prompt.
- **The vexp daemon runs as a standalone `systemd`-user service — NOT the VS Code
  extension.** The supervisor is `vexp.service` (`ExecStart=vexp serve`), `enabled` + linger,
  auto-restarting; it starts/adopts the per-repo daemon on demand. Managing it with
  `systemctl --user … vexp.service` or `vexp daemon-cmd start|stop|status|logs` is the
  expected control path, not forbidden. Do **not** run vexp from the VS Code extension
  (deprecated here — older bundled core, contends for the socket/port).
- **Start/manage the daemon in the host process namespace (un-sandboxed).** A daemon
  spawned inside a sandboxed shell gets a throwaway PID namespace + socket the host-side
  MCP can't reach, and dies when that shell exits. If `index_status` reports "Cannot
  connect to daemon," run `vexp daemon-cmd start` un-sandboxed and wait for "Socket ready"
  (first start loads the local LLM, so allow >12s).

If you're unsure whether an action would violate one of the above, stop and ask before
acting.

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
- **Three-phase sync** — guided initial sync wizard → validation dry run → user-enabled auto-sync. Auto-sync is OFF by default and requires explicit user action to enable.
- **Conflicts are never auto-resolved** — queued for human decision with optional Discord notification. This is a hard rule — do not implement silent conflict resolution.
- **Weight decrements from Spoolman create usage log entries in Filament DB** (via `POST /api/filaments/:id/spools/:spoolId/usage`), never raw weight overwrites. This preserves Filament DB's usage history audit trail.
- **Source of truth is user-configurable** per data category (weight, material properties, new spools). The bridge does not assume which system is authoritative.
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
├── docker-compose.yml                      — example deployment with both upstream services
├── backend/
│   ├── app/
│   │   ├── api/                            — FastAPI routers
│   │   │   ├── sync.py                     — trigger sync, dry run, enable/disable auto-sync
│   │   │   ├── conflicts.py                — list, resolve, bulk-resolve conflicts
│   │   │   ├── mappings.py                 — view/edit spool and filament mappings
│   │   │   ├── config.py                   — runtime config (source of truth, field mappings)
│   │   │   ├── backup.py                   — export/import bridge state
│   │   │   └── health.py                   — connectivity check for both upstream APIs
│   │   ├── core/
│   │   │   ├── engine.py                   — main sync loop: snapshot, diff, apply, log
│   │   │   ├── differ.py                   — diff two snapshots, classify changes
│   │   │   ├── matcher.py                  — fuzzy matching for initial sync (vendor+name+color)
│   │   │   ├── weight.py                   — net↔gross weight conversion logic
│   │   │   └── fields.py                   — field mapping resolution (auto-match + explicit)
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
│   │   │   ├── Wizard/                     — multi-step initial sync wizard (FR-1 through FR-7)
│   │   │   ├── Dashboard.tsx               — sync status overview (FR-15)
│   │   │   ├── SyncedRecords.tsx           — paired records table (FR-19)
│   │   │   ├── Conflicts.tsx               — conflict queue and resolution (FR-16)
│   │   │   └── SyncLog.tsx                 — audit log viewer (FR-17)
│   │   ├── api/                            — typed fetch wrappers for bridge backend API
│   │   └── App.tsx                         — router setup, layout
│   ├── package.json
│   ├── tsconfig.json
│   ├── tailwind.config.js
│   └── vite.config.ts
├── docs/
│   ├── prd.md                              — full product requirements (READ THIS)
│   └── migration-spoolman-to-filamentdb.md — standalone migration guide
└── private_data/                           — gitignored, user-specific test data
```

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `FILAMENTDB_URL` | **Yes** | — | Base URL of Filament DB (e.g., `http://filament-db:3000`) |
| `SPOOLMAN_URL` | **Yes** | — | Base URL of Spoolman (e.g., `http://spoolman:7912`) |
| `SYNC_INTERVAL_SECONDS` | No | `120` | Seconds between auto-sync cycles |
| `SPOOLMAN_FIELD_FILAMENTDB_ID` | No | `filamentdb_id` | Spoolman extra field name for Filament DB filament ID |
| `SPOOLMAN_FIELD_FILAMENTDB_PARENT_ID` | No | `filamentdb_parent_id` | Spoolman extra field for parent filament ID |
| `SPOOLMAN_FIELD_FILAMENTDB_SPOOL_ID` | No | `filamentdb_spool_id` | Spoolman extra field for spool subdocument ID |
| `FILAMENTDB_SPOOLMAN_ID_FIELD` | No | `label` | Filament DB spool field to store Spoolman spool ID |
| `FIELD_MAPPINGS` | No | — | Comma-separated `fdb_field=spoolman_field` pairs |
| `FIELD_MAPPING_EXCLUDES` | No | — | Comma-separated field names to exclude from auto-match |
| `DISCORD_WEBHOOK_URL` | No | — | Discord webhook for conflict/error notifications |
| `LOG_LEVEL` | No | `info` | Logging level (debug, info, warn, error) |
| `DATA_DIR` | No | `/data` | Directory for SQLite database and backup files |

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
- The `settings{}` bag on filaments is a passthrough for slicer-specific keys — unknown keys round-trip without modification. Don't touch this in sync.
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
- Don't touch the `settings{}` bag on Filament DB filaments — it's slicer passthrough data
