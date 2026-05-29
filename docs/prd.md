# Product Requirements Document: filament-bridge

## Problem statement

Filament DB and Spoolman serve different sides of the 3D printing filament workflow. Filament DB manages material profiles, slicer integration, calibrations, and NFC tags. Spoolman manages real-time spool inventory with native OctoPrint, Moonraker/Klipper, and Home Assistant integration. Neither can replace the other, and there is no way to keep them in sync. Users who want both capabilities face manual data entry, divergent inventory states, and lost usage tracking data.

## Solution

A bidirectional sync service that runs as a Docker sidecar alongside both Filament DB and Spoolman. It maintains a mapping between both databases, syncs changes automatically on a configurable interval, and queues conflicts for manual resolution. Both upstream systems remain unmodified — the bridge talks to their existing REST APIs.

## Users

3D printing enthusiasts and homelabbers running both Filament DB (for slicer integration and material management) and Spoolman (for OctoPrint/Moonraker print-side tracking), who want their inventory and usage data consistent across both systems without manual dual-entry.

---

## Architecture

### Tech stack

**Backend:** Python + FastAPI
- Async HTTP client (httpx) for polling both APIs concurrently
- FastAPI provides the bridge's own REST API + serves the frontend static build
- SQLite via SQLAlchemy for sync state persistence (mapping table, conflict queue, sync log, snapshots)
- APScheduler for the configurable sync interval
- Pydantic models for Spoolman and Filament DB response shapes

**Frontend:** React SPA
- TypeScript + React for the initial sync wizard, dashboard, conflict resolution, and sync log views
- Vite for build tooling
- Tailwind CSS for styling
- Communicates with the FastAPI backend via REST

**Deployment:** Docker
- Multi-stage build: Node (build React) → Python (FastAPI + static assets)
- Single container, single port (default 8090)
- SQLite database file in a mounted volume for persistence
- All configuration via environment variables — service refuses to start if required vars are missing

### Container structure

```
filament-bridge/
├── backend/                 — Python FastAPI application
│   ├── app/
│   │   ├── api/             — REST endpoints (sync, conflicts, config, health)
│   │   ├── core/            — sync engine, diff logic, field mapping
│   │   ├── models/          — SQLAlchemy models (mapping, conflicts, log)
│   │   ├── services/        — Filament DB client, Spoolman client
│   │   └── main.py          — FastAPI app, scheduler setup, static file serving
│   └── requirements.txt
├── frontend/                — React SPA
│   ├── src/
│   │   ├── components/      — shared UI components
│   │   ├── pages/           — wizard, dashboard, conflicts, log
│   │   └── App.tsx
│   ├── package.json
│   └── vite.config.ts
├── Dockerfile               — multi-stage build
├── docker-compose.yml       — example deployment
└── docs/
```

### Data flow

```
Spoolman                         filament-bridge                        Filament DB
─────────                        ───────────────                        ───────────
                                        │
                              [On each sync cycle]
                                        │
GET /api/v1/spool ◄─────────────────────┤
GET /api/v1/filament ◄──────────────────┤
GET /api/v1/vendor ◄────────────────────┤
         │                              │────────────► GET /api/filaments
         │                              │────────────► GET /api/spools/export-csv
         │                              │
         ▼                              ▼
    [Spoolman snapshot]          [Filament DB snapshot]
                                        │
                                 [Diff against last sync]
                                        │
                          ┌─────────────┼─────────────┐
                          ▼             ▼             ▼
                    [No change]   [One side     [Both sides
                     (skip)       changed]       changed]
                                     │               │
                                     ▼               ▼
                              [Apply to other]  [Queue as
                               side via API]     conflict]
                                     │
                          ┌──────────┴──────────┐
                          ▼                     ▼
              PUT /api/v1/spool/{id}    POST /api/filaments/
              (update Spoolman)          :id/spools/:sid/usage
                                        (update Filament DB)
```

### Cross-reference ID storage

Both systems store references to their counterpart:

**In Spoolman (extra fields on spool/filament):**
- `filamentdb_id` — Filament DB filament `_id` (direct match for this color/variant)
- `filamentdb_parent_id` — Filament DB parent filament `_id` (shared across color variants)
- `filamentdb_spool_id` — Filament DB spool subdocument `_id`

**In Filament DB (configurable field on spool):**
- Spoolman spool `id` stored in the spool's `label` field (or user-configured alternative)

Field names are configurable via environment variables.

---

## Functional requirements

### P0 — Initial sync wizard

#### FR-1: Connectivity check
- On first access to the web UI, verify connectivity to both Filament DB and Spoolman APIs
- Display version info and record counts from both systems
- Block further steps if either is unreachable

#### FR-2: Direction selection
- User chooses initial import direction: "Import from Spoolman" or "Import from Filament DB"
- This sets the initial source of truth for the mapping process
- User also configures ongoing source-of-truth per data category:
  - Spool weight: Spoolman (recommended) or Filament DB
  - Material properties: Filament DB (recommended) or Spoolman
  - New spool creation: User's choice

#### FR-3: Auto-matching
- Read all filaments and spools from both systems
- Match records by vendor name + filament name + color (fuzzy matching for case, whitespace, vendor aliases)
- Produce three lists:
  - **Matched pairs** — high-confidence matches, ready to link
  - **Unmatched (source side)** — records that exist in the source but not the target, to be created
  - **Ambiguous** — multiple possible matches, need user resolution

#### FR-4: Match review and conflict resolution UI
- Display all three lists with side-by-side comparison
- For ambiguous matches: user picks the correct pairing or marks as "create new"
- For unmatched: user confirms creation or skips
- Highlight vendor name deduplication issues (e.g., "ELEGOO" vs "Elegoo") and offer normalization
- **Every record row displays two icon links:** one linking directly to that spool/filament in Filament DB's web UI, one linking directly to that spool/filament in Spoolman's web UI. Icons should be visually distinct (e.g., Filament DB logo/color and Spoolman logo/color). Links open in new tabs.

#### FR-5: Weight conversion review
- For each spool being synced from Spoolman → Filament DB, show the weight conversion:
  - Spoolman net weight → Filament DB gross weight (add tare)
  - Display the tare weight source (Spoolman's `filament.spool_weight` or default)
  - User can override tare weight per spool or per filament
- For Filament DB → Spoolman direction, show the reverse conversion

#### FR-6: Variant grouping (optional step)
- Analyze matched filaments for potential parent/variant relationships
- Group by vendor + material type (stripping color from name)
- Suggest parent assignment — user confirms or skips
- Write `filamentdb_parent_id` to Spoolman extra fields for grouped filaments

#### FR-7: Execute initial sync
- Write cross-reference IDs to both systems
- Create missing records in the target system
- Apply weight conversions
- Log all actions for audit trail
- Report: created, updated, skipped, failed — with details for each

### P0 — Continuous sync engine

#### FR-8: Sync cycle
- On configured interval (env var `SYNC_INTERVAL_SECONDS`), poll both APIs
- Diff current state against last-known snapshot
- For each changed record, determine sync direction based on source-of-truth config
- Apply changes to the other system via API calls
- Update the local snapshot
- Auto-sync is disabled by default — must be explicitly enabled after initial sync

#### FR-9: Spool weight sync (Spoolman → Filament DB)
- Detect weight decrease in Spoolman (remaining_weight dropped)
- Compute delta: `last_known_weight - current_weight`
- Call `POST /api/filaments/:id/spools/:spoolId/usage` with `{ grams: delta, jobLabel: "spoolman sync [date]", source: "spoolman" }`
- This creates a proper usage history entry in Filament DB, not a raw weight overwrite

#### FR-10: Spool weight sync (Filament DB → Spoolman)
- Detect weight change in Filament DB (usage logged or manual adjustment)
- Compute the new net weight: `totalWeight - spoolWeight - sum(usageHistory.grams)`
- Call `PUT /api/v1/spool/{id}` with `{ remaining_weight: new_net_weight }`

#### FR-11: Field mapping sync
- For configured field mappings (env var `FIELD_MAPPINGS`), sync values between Filament DB filament fields and Spoolman extra fields
- Auto-match: if a Spoolman extra field name matches a Filament DB field name exactly, sync automatically (unless excluded via `FIELD_MAPPING_EXCLUDES`)
- Explicit mapping: `FIELD_MAPPINGS=density=sm_density,temperatures.nozzle=nozzle_temp` overrides auto-match
- Direction follows source-of-truth config for material properties

#### FR-12: New record detection
- When a new spool appears in Spoolman (no `filamentdb_spool_id` extra field):
  - Try to auto-match to an existing Filament DB filament by vendor + name
  - If matched: create a spool subdocument in Filament DB, write cross-reference IDs
  - If unmatched: queue as conflict for user resolution
- When a new spool appears in Filament DB (no Spoolman ID in label):
  - Try to auto-match to an existing Spoolman filament
  - If matched: create a Spoolman spool under that filament, write cross-reference IDs
  - If unmatched: queue as conflict

#### FR-13: Conflict detection and queuing
- A conflict occurs when the same field on the same record changes on both sides between sync cycles
- Conflicts are never auto-resolved — they go into a queue
- Conflict record includes: entity type, entity IDs on both sides, field name, value on each side, timestamps
- Queue persists across restarts

#### FR-14: Validation dry run
- Before enabling auto-sync, user can trigger a dry run
- Shows exactly what the next sync cycle would do: creates, updates, conflicts
- User reviews and explicitly enables auto-sync
- Can be re-run at any time

### P1 — Web UI

#### FR-15: Dashboard
- Show sync status: last sync time, next scheduled sync, records in sync, pending conflicts
- Connectivity status for both systems
- Quick stats: total filaments, total spools, synced vs unsynced counts

#### FR-16: Conflict resolution UI
- List all pending conflicts with details
- For each: show both values, let user pick one or enter a manual value
- **Every conflict row displays two icon links** to the affected record in Filament DB and Spoolman (same pattern as FR-4)
- Resolving a conflict applies the chosen value to both systems on the next sync cycle

#### FR-17: Sync log
- Scrollable log of all sync actions with timestamps
- Filter by: entity type, direction, action type (create, update, conflict)
- **Each log entry includes icon links** to the affected record in both systems where applicable
- Useful for debugging unexpected changes

#### FR-18: Manual sync trigger
- Button to trigger an immediate sync cycle outside the scheduled interval
- Shows results inline

#### FR-19: Synced records view
- Table of all synced spool/filament pairs showing current state on both sides
- Columns: name, vendor, color, Spoolman weight, Filament DB weight, sync status, last synced
- **Each row displays two icon links** to the record in Filament DB and Spoolman
- Sortable and filterable
- Visual indicators for: in sync (green), pending sync (yellow), conflict (red), unlinked (grey)

### P2 — Enhanced features

#### FR-20: Discord notifications
- On conflict: post to configured Discord webhook with conflict details
- On sync error: post with error details and retry status
- Optional: daily summary of sync activity

#### FR-21: Spoolman archive/retire sync
- When a spool is archived in Spoolman, set `retired: true` on the Filament DB spool
- When a spool is retired in Filament DB, archive it in Spoolman

#### FR-22: Print history enrichment
- When a weight decrement is synced from Spoolman, optionally create a `POST /api/print-history` record in Filament DB
- Would require OctoPrint job metadata (filename, duration) — may need an OctoPrint API call or Spoolman webhook

#### FR-23: Bulk operations
- Bulk resolve conflicts (e.g., "accept all from Spoolman")
- Bulk assign variants
- Bulk update tare weights

#### FR-24: Backup and restore
- **Export** the bridge's sync state (mapping table, configuration, conflict queue) as a JSON file via the web UI or API (`GET /api/backup`)
- **Import/restore** a previously exported backup via the web UI or API (`POST /api/backup`)
- Backup includes: all spool/filament mappings with cross-reference IDs, source-of-truth settings, field mapping configuration, unresolved conflicts, and sync log history
- Does NOT include data from Filament DB or Spoolman themselves — only the bridge's own state
- Useful for: migrating the bridge to a new host, recovering from a corrupted SQLite database, or resetting and re-importing after a configuration change
- Backup file is versioned with a schema version for forward compatibility

#### FR-25: Configuration export/import
- Separate from the full backup: export just the bridge configuration (URLs, field mappings, source-of-truth settings, sync interval) as a shareable config file
- Useful for users sharing their setup or restoring after a fresh install without re-running the initial sync wizard

---

## Non-functional requirements

### NFR-1: No upstream modifications
- filament-bridge must not require changes to Filament DB or Spoolman
- All integration through documented REST APIs and Spoolman's extra field system

### NFR-2: Docker-native deployment
- Single Docker image with React frontend and FastAPI backend
- Multi-stage build: Node stage builds React → Python stage bundles FastAPI + static assets
- All configuration via environment variables
- Service refuses to start if `FILAMENTDB_URL` or `SPOOLMAN_URL` are missing
- Data volume mount for SQLite database persistence

### NFR-3: Lightweight
- SQLite for all persistent state (no MongoDB, no PostgreSQL)
- Single container, single port (default 8090)
- Fast startup — should be serving requests within seconds

### NFR-4: Resilient
- If either API is unreachable during a sync cycle: log, skip, retry next cycle
- Never lose sync state on crash — write-ahead for state changes
- Conflict queue survives restarts
- Startup validates API connectivity and warns (but doesn't crash) if degraded

### NFR-5: Auditable
- Every sync action is logged with timestamp, direction, entity, field, old value, new value
- Logs are queryable through the web UI (FR-17)
- Structured JSON logging to stdout for Docker log aggregation

### NFR-6: Safe
- Never delete records in either system without explicit user action
- Weight decrements always create log entries (never raw overwrites) in Filament DB
- Dry run available before any bulk operation
- Backup/restore available for the bridge's own state

### NFR-7: Deep-linkable
- Every spool and filament reference in the UI includes direct links to both Filament DB and Spoolman web UIs
- Link format: `{FILAMENTDB_URL}/filaments/{id}` and `{SPOOLMAN_URL}/spool/show/{id}` (configurable URL patterns; verified against live instances)
- Links open in new tabs

---

## UI deep link pattern

Throughout the web UI, every record that maps to a spool or filament in either system displays two icon links:

| Icon | Target | URL pattern |
|---|---|---|
| 🔵 Filament DB icon | Filament detail page (spool rows link here too — no standalone spool page) | `{FILAMENTDB_URL}/filaments/{filamentdb_id}` |
| 🟢 Spoolman icon | Spool / filament detail page | `{SPOOLMAN_URL}/spool/show/{spoolman_id}` · `/filament/show/{id}` |

These appear in: the initial sync wizard match review (FR-4), the synced records view (FR-19), the conflict resolution UI (FR-16), and the sync log (FR-17). URL base paths are derived from the configured `FILAMENTDB_URL` and `SPOOLMAN_URL` environment variables.

---

## Open questions

> Resolved 2026-05-28 against the live crzynet instances. Decisions are recorded in
> [`docs/decisions.md`](decisions.md); raw API evidence in `private_data/findings.md`.

1. **Sync granularity for weight** — ✅ **Resolved.** Sync only when the delta ≥ a configurable threshold (default ~2g) to avoid net/gross rounding churn.

2. **Spoolman extra field creation** — ✅ **Resolved.** The bridge creates its cross-ref fields via `POST /api/v1/field/{entity_type}/{key}` on startup (`GET /api/v1/field/spool` returns `[]` today). Extra-field text values round-trip JSON-double-quoted — `json.loads`/`json.dumps` on read/write.

3. **Filament DB variant creation via API** — ✅ **Resolved.** `parentId` links variants; `GET /api/filaments/:id` resolves inheritance server-side and reports it in `_inherited[]`/`_parent`/`_variants`. Strip computed fields before PUT; don't write fields listed in `_inherited[]`.

4. **OctoPrint 2.0 impact** — ⏳ **Deferred (monitor).** No bridge code depends on it; watch RC releases.

5. **Moonraker compatibility** — ⏳ **Deferred.** Test once the sync engine exists.

6. **Rate limiting** — ✅ **Resolved (for now).** Full-snapshot diff each cycle; `GET /api/v1/spool?limit=1000` returns all 223 spools (incl. archived — filter `archived == false` client-side). Add incremental fetch only if a larger inventory demands it.

7. **Multi-printer attribution** — ✅ **Resolved.** Accept the aggregate delta; per-printer attribution is out of scope (documented, not silently dropped).

8. **Filament DB and Spoolman URL path patterns** — ✅ **Resolved.** Filament DB `{FILAMENTDB_URL}/filaments/{id}` (plural, no standalone spool page); Spoolman `{SPOOLMAN_URL}/spool/show/{id}` and `/filament/show/{id}` (no hash routing).
