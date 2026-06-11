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
- TypeScript + React for the Bulk Import Wizard, dashboard, conflict resolution, and sync log views
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
│   │   ├── api/             — REST endpoints (sync, conflicts, config, health, opentag, backup)
│   │   ├── core/            — sync engine, diff logic, field mapping
│   │   │   ├── engine.py        — main sync loop: snapshot, diff, apply, log
│   │   │   ├── sync_policy.py   — two-axis direction+policy resolver (resolve_sync_action)
│   │   │   ├── planner.py       — wizard execution planner
│   │   │   ├── dryrun.py        — dry-run preview helpers
│   │   │   ├── differ.py        — snapshot diff, change classification
│   │   │   ├── fields.py        — field mapping resolution (auto-match + explicit)
│   │   │   ├── color.py         — multicolor/gradient conversion (FDB ↔ Spoolman)
│   │   │   ├── material_tags.py — finish-tag detection and serialization
│   │   │   ├── version.py       — FDB version comparison helpers
│   │   │   ├── opentag_match.py — OPTMaterial → Spoolman field mapper + scorer
│   │   │   ├── opentag_cache.py — local OpenTag dataset cache (JSON, TTL-gated)
│   │   │   └── opentag_secondary.py — secondary-color recovery from the raw OPT tarball
│   │   ├── models/          — SQLAlchemy models (mapping, conflicts, log, snapshot, config)
│   │   ├── services/        — Filament DB client, Spoolman client
│   │   └── main.py          — FastAPI app, scheduler setup, static file serving
│   └── requirements.txt
├── frontend/                — React SPA
│   ├── src/
│   │   ├── components/      — shared UI components
│   │   ├── pages/           — Wizard/, Dashboard.tsx, Conflicts.tsx, SyncLog.tsx,
│   │   │                       SyncedRecords.tsx, Settings.tsx, OpenTagCleanup.tsx
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
                       resolve_sync_action()   [Queue as
                       (direction + policy)    conflict]
                                     │
                          ┌──────────┴──────────┐
                          ▼                     ▼
              PUT /api/v1/spool/{id}    POST /api/filaments/
              (update Spoolman)          :id/spools/:sid/usage
                                        (update Filament DB)
```

The engine runs multiple per-cycle passes over the mapped filament/spool pairs:

| Pass | Function | Notes |
|---|---|---|
| Weight | `_sync_weight` | Spoolman ↔ FDB; `newest_wins` available (weight-only) |
| Field mapping | `_apply_field_changes` | FR-11 mapped fields; follows material_properties direction |
| Cost | `_sync_cost` | Filament price, spool-price-first effective cost; FDB→SM writes filament price only |
| Multicolor | `_sync_multicolor` | Requires FDB ≥ 1.33.0; `color_hex`/`multi_color_hexes`/`multi_color_direction` ↔ FDB `color`/`secondaryColors`/`optTags` |
| Finish tags | `_sync_finish_tags` | Requires FDB ≥ 1.33.0; `optTags` (managed subset) ↔ Spoolman `extra.filamentdb_material_tags` |
| OpenTag identity | `_sync_opentag_identity` | Propagates `openprinttag_slug`/`uuid` from Spoolman extra fields into FDB `settings{}` bag |

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

### P0 — Bulk Import Wizard

#### FR-1: Connectivity check
- On first access to the web UI, verify connectivity to both Filament DB and Spoolman APIs
- Display version info and record counts from both systems
- Block further steps if either is unreachable

#### FR-2: Direction selection
- User chooses initial import direction: "Import from Spoolman" or "Import from Filament DB"
- This sets the data flow for the wizard execution (FR-7) only — it does **not** configure ongoing sync settings
- Ongoing sync direction and conflict policy are configured in Settings (FR-8); see that section for the full two-axis model and default values

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
- **Every record row displays two text-badge links:** "FDB" (blue badge) linking directly to that spool/filament in Filament DB's web UI, and "SM" (emerald badge) linking directly to Spoolman's web UI. Links open in new tabs.

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

#### FR-7: Execute import
- Write cross-reference IDs to both systems
- Create missing records in the target system
- Apply weight conversions
- If `never_import_empties` is on, spools with zero remaining weight are skipped at both preview and execute
- Log all actions for audit trail
- Report: created, updated, skipped, failed — with details for each
- The wizard is re-runnable; subsequent runs re-use existing mappings where possible

### P0 — Continuous sync engine

#### FR-8: Sync cycle and runtime settings
- On configured interval (`SYNC_INTERVAL_SECONDS` env var, or the runtime override in Settings), poll both APIs
- Diff current state against last-known snapshot
- For each changed record, `resolve_sync_action` is called with the category's `direction` and `conflict_policy`:
  - If only one side changed: propagate to the other (regardless of policy)
  - If both sides changed under `two_way`: apply the conflict policy (`manual` → queue; `spoolman_wins`/`filamentdb_wins` → push; `newest_wins` → compare timestamps, fall back to queue if indeterminate)
  - One-way directions: only the source side can propagate; drift on the locked side is NOOP
- Resolved by `core/sync_policy.py:resolve_sync_action`. Each category has two independent axes:
  - **`direction`** — `two_way` | `spoolman_to_filamentdb` | `filamentdb_to_spoolman`
  - **`conflict_policy`** — `manual` | `spoolman_wins` | `filamentdb_wins` | `newest_wins`
    (consulted only when `direction == "two_way"` AND both sides changed)
  - **Weight:** direction defaults `spoolman_to_filamentdb`; `newest_wins` available (Spoolman exposes a spool modification timestamp)
  - **Material properties:** direction defaults `filamentdb_to_spoolman`; `newest_wins` rejected (Spoolman has no per-filament mtime)
  - **New spool creation:** direction only (no conflict policy); defaults `two_way`
- Apply changes to the other system via API calls; update the local snapshot
- Auto-sync is disabled by default — must be explicitly enabled after initial sync
- **Runtime-editable settings** (all configurable in Settings UI, stored in SQLite):
  - `sync_interval_seconds` — interval override (env var is the start-up fallback)
  - `never_import_empties` — skip zero-weight spools during wizard preview/execute
  - `sync_log_retention_days` — auto-prune log entries older than N days (default 30)
  - `debug_mode` — enable reset/clear endpoints (see Debug tools below)

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
- **Native shared filament scalars** — five fields with a direct FDB↔SM counterpart are synced by the dedicated `_sync_material_scalars` pass (Phase A, 2026-06-10):
  - SM `material` ↔ FDB `type` (name remap)
  - SM `density` ↔ FDB `density`
  - SM `diameter` ↔ FDB `diameter`
  - SM `spool_weight` ↔ FDB `spoolWeight`
  - SM `weight` ↔ FDB `netFilamentWeight`
  - These fields are handled OUTSIDE the generic extra-field mapper (they are native, not extra-field)
  - Snapshots keyed `_mp_<sm_field>` coexist with `_mc_sig`, `_cost`, `_finish_sig` via `_merge_snapshot`
  - **Master/variant gate (PUSH_SM_TO_FDB):**
    - Standalone or already-overridden variant → write directly
    - Inherited AND SM value matches resolved (inherited) value → skip (no redundant override)
    - Inherited AND SM value diverges → queue `master_divergence` conflict (record-only; no write; Phase B owns apply)
  - `conflict_type` column on `Conflict`: `"cross_system"` (standard both-sides-changed) or `"master_divergence"` (inherited-field divergence, pending Phase B)
  - Per-field dedup: `_has_open_conflict` accepts `conflict_type` so cross_system and master_divergence conflicts on the same field+ids deduplicate independently

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
- Conflicts are never auto-resolved — they always go into a queue for human decision
- Conflict record includes: entity type, entity IDs on both sides, field name, value on each side, timestamps
- Queue persists across restarts; open conflicts are deduplicated (same field + IDs only queued once)
- Two classes of conflict:

**Both-sides-changed conflicts** — when `direction == "two_way"` and `conflict_policy == "manual"` (or `newest_wins` falls back): the same field changed on both sides since the last snapshot. The field name is the changed field (e.g. `remaining_weight`, `color`, `cost`, `material_tags`, `multicolor`).

**Upstream-deletion conflicts** — when a previously mapped spool is missing from one side on the next poll, `_queue_deletion_conflict` fires. The field name is the sentinel `DELETION_FIELD = "__record_deleted__"` (from `models/conflict.py`). The surviving side carries a descriptor `{ "exists": true, "deleted_side": "spoolman"|"filamentdb" }`; the deleted side value is null. These are deduplicated in the same way. Resolution via the conflict UI removes the orphaned bridge mapping and both snapshots (`api/conflicts.py:_cleanup_orphaned_mapping`).

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
- **Every conflict row displays two text-badge links** — "FDB" (blue) linking to Filament DB, "SM" (emerald) linking to Spoolman — to the affected record (same URL patterns as FR-4)
- Resolving a conflict **records the chosen value and removes the conflict from the open queue** — it does NOT write the value upstream. Applying the resolved value to both systems is a Phase-2 follow-up; `api/conflicts.py` performs no upstream writes. For deletion conflicts, resolution also cleans up the orphaned bridge mapping and snapshots.

#### FR-17: Sync log
- Scrollable log of all sync actions with timestamps
- Filter by: entity type, direction, action type (create, update, conflict)
- **Time-window selector** (last 24 h / 7 d / 30 d / all) to limit display without deleting entries
- **Clear log** action permanently deletes all log entries from SQLite (confirmation required)
- **Each log entry includes text-badge links** ("FDB"/"SM") to the affected record in both systems where applicable
- Useful for debugging unexpected changes

#### FR-18: Manual sync trigger
- Button to trigger an immediate sync cycle outside the scheduled interval
- Shows results inline

#### FR-19: Synced records view
- Table of all synced spool/filament pairs showing current state on both sides
- Columns: name, vendor, color, Spoolman weight, Filament DB weight, sync status, last synced
- **Each row displays two text-badge links** ("FDB"/"SM") to the record in Filament DB and Spoolman
- Sortable and filterable
- **Hide empty spools** toggle (hides spools where Spoolman remaining_weight ≈ 0)
- Visual indicators for: in sync (green), pending sync (yellow), conflict (red), unlinked (grey)

### P2 — Enhanced features

#### FR-20: Discord notifications *(Not implemented — v0.1.0)*
- `DISCORD_WEBHOOK_URL` env var is declared and validated, but no posting code exists
- On conflict: post to configured Discord webhook with conflict details *(planned)*
- On sync error: post with error details and retry status *(planned)*
- Optional: daily summary of sync activity *(planned)*

#### FR-21: Spoolman archive/retire sync *(Partial — v0.1.0)*
- Archived Spoolman spools are detected and excluded from sync cycles
- Symmetric propagation (`retired: true` in FDB ↔ `archived` in Spoolman) is not yet implemented

#### FR-22: Print history enrichment *(Not implemented — v0.1.0)*
- Planned: when a weight decrement is synced from Spoolman, optionally create a `POST /api/print-history` record in Filament DB
- Would require OctoPrint job metadata (filename, duration) — may need an OctoPrint API call or Spoolman webhook

#### FR-23: Bulk operations
- Bulk resolve conflicts (e.g., "accept all from Spoolman")
- Bulk assign variants
- Bulk update tare weights

#### FR-23b: OpenTag (OpenPrintTag) Cleanup tool
A standalone on-demand tool to match Spoolman filaments against the OpenPrintTag community dataset and apply corrections.

- **Dataset:** fetched from FDB's `GET /api/openprinttag` endpoint (a denormalized JSON feed), cached locally at `DATA_DIR/opentag_cache.json` with a TTL of `OPENTAG_CACHE_MAX_AGE_HOURS`. Secondary colors are recovered from the raw OPT tarball via `core/opentag_secondary.py`.
- **Matching** (`core/opentag_match.py`): per-Spoolman-filament scoring by material family, vendor/brand (via `OPENTAG_VENDOR_ALIASES` map), color name similarity, hex proximity, and finish-tag overlap. Color-profile pre-filter (single/coextruded/gradient) prevents cross-profile matches. UUID exact-match bypasses fuzzy scoring for filaments already tagged by a prior run.
- **Review UI** (`frontend/src/pages/OpenTagCleanup.tsx`): per-filament card with a best match + up to 5 alternate candidates. Each candidate shows per-field comparison (current Spoolman value vs OpenTag suggestion). User selects a candidate and can mark individual fields "keep mine" or edit the suggested value. The **Manufacturer** field (vendor) shows only when the Spoolman vendor name and OpenTag brand differ after normalization.
- **Apply** (`POST /api/openprinttag/apply`): writes confirmed fields to Spoolman; for the vendor field, resolves or creates the Spoolman vendor via find-or-create (`_ensure_vendor`). After the Spoolman write, stamps `openprinttag_slug`/`openprinttag_uuid` into the linked FDB filament's `settings{}` bag via `FilamentDBClient.merge_filament_settings()` (the approved scoped exception).
- Routes: `GET /api/openprinttag/status`, `POST /api/openprinttag/refresh`, `GET /api/openprinttag/matches`, `POST /api/openprinttag/apply`.

#### FR-23c: Debug mode and reset tools
- `debug_mode` is a runtime-editable BridgeConfig flag (default `false`), toggled in Settings
- When `debug_mode` is `false`, the two debug endpoints return **403**
- `POST /api/debug/clear-spoolman-fdb-refs` — strips all `filamentdb_*` extra fields from every Spoolman spool/filament; clears bridge mapping table. Useful for a clean re-import without resetting Spoolman data.
- `POST /api/debug/reset-bridge-state` — drops all bridge SQLite state (mappings, snapshots, conflicts, sync log, config). Full reset; leaves both upstream systems untouched.
- These are development/testing tools and must never be called in an automated workflow.

#### FR-24: Backup and restore
- **Export** the bridge's sync state (mapping table, configuration, conflict queue) as a JSON file via `GET /api/backup/export`
- **Import/restore** a previously exported backup via `POST /api/backup/import`
- Backup includes: all spool/filament mappings with cross-reference IDs, runtime config, and unresolved conflicts
- Does NOT include data from Filament DB or Spoolman themselves — only the bridge's own state
- Useful for: migrating the bridge to a new host, recovering from a corrupted SQLite database, or resetting and re-importing after a configuration change
- Backup file is versioned with a schema version for forward compatibility; import is idempotent
- **Upstream backup proxies (pre-write safety dialog):**
  - `POST /api/backup/spoolman` — proxies to Spoolman's `POST /api/v1/backup`; Spoolman writes the archive to its own data volume
  - `POST /api/backup/filamentdb` — fetches Filament DB's `GET /api/snapshot` (full JSON backup: filaments, locations, print history, catalogs, tombstones) and writes it to `DATA_DIR/backups/filamentdb-snapshot-<timestamp>.json`; the bridge's data volume must be mounted for the file to survive a restart. Note: unlike Spoolman, FDB delivers the snapshot to the caller rather than writing it internally, so the bridge stores it.

#### FR-25: Configuration-only export *(Not implemented — folded into full backup)*
- Originally planned as a separate config-only export; folded into `GET /api/backup/export` which includes config in the full dump

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
- Every spool and filament reference in the UI includes direct text-badge links ("FDB" / "SM") to both Filament DB and Spoolman web UIs
- Link format: `{FILAMENTDB_URL}/filaments/{id}` and `{SPOOLMAN_URL}/spool/show/{id}` (verified against live instances)
- Links open in new tabs

---

## UI deep link pattern

Throughout the web UI, every record that maps to a spool or filament in either system displays two text-badge links:

| Badge | Target | URL pattern |
|---|---|---|
| **FDB** (blue) | Filament detail page (spool rows link here too — no standalone spool page) | `{FILAMENTDB_URL}/filaments/{filamentdb_id}` |
| **SM** (emerald) | Spool / filament detail page | `{SPOOLMAN_URL}/spool/show/{spoolman_id}` · `/filament/show/{id}` |

These appear in: the Bulk Import Wizard match review (FR-4), the synced records view (FR-19), the conflict resolution UI (FR-16), and the sync log (FR-17). URL base paths are derived from the configured `FILAMENTDB_URL` and `SPOOLMAN_URL` environment variables.

---

## Open questions

> Pre-2026-05-28 questions resolved against the live crzynet instances. Post-2026-05-28
> questions resolved by code (see `docs/decisions.md` for full write-ups).

1. **Sync granularity for weight** — ✅ **Resolved by code.** Sync only when the delta ≥ a configurable threshold (default ~2g) to avoid net/gross rounding churn. Implemented in `core/weight.py:weight_changed`.

2. **Spoolman extra field creation** — ✅ **Resolved by code.** The bridge creates its cross-ref fields via `POST /api/v1/field/{entity_type}/{key}` on startup (`ensure_extra_fields()`). Extra-field text values round-trip JSON-double-quoted via `encode_extra_value`/`decode_extra_value`.

3. **Filament DB variant creation via API** — ✅ **Resolved by code.** `parentId` links variants; `GET /api/filaments/:id` resolves inheritance server-side in `_inherited[]`/`_parent`/`_variants`. Fields in `_inherited[]` are skipped by `core/fields.py:should_skip_inherited`.

4. **OctoPrint 2.0 impact** — ⏳ **Deferred (monitor).** No bridge code depends on it; watch RC releases.

5. **Moonraker compatibility** — ⏳ **Deferred.** Test once the sync engine is fully validated.

6. **Rate limiting / full-snapshot diff** — ✅ **Resolved by code.** Full-snapshot diff each cycle; `GET /api/v1/spool?limit=1000` returns all spools (incl. archived — filtered `archived == false` client-side). Add incremental fetch only if a larger inventory demands it.

7. **Multi-printer attribution** — ✅ **Resolved.** Accept the aggregate delta; per-printer attribution is out of scope (documented, not silently dropped).

8. **Filament DB and Spoolman URL path patterns** — ✅ **Resolved by code.** Filament DB `{FILAMENTDB_URL}/filaments/{id}` (plural, no standalone spool page); Spoolman `{SPOOLMAN_URL}/spool/show/{id}` and `/filament/show/{id}` (no hash routing). UI renders text badges "FDB"/"SM", not vendor logos.
