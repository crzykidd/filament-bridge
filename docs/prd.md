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
│   │   ├── api/             — REST endpoints (sync, conflicts, mappings, config, health,
│   │   │                       wizard, opentag, backup, sync_log, debug, auth, version,
│   │   │                       reconcile, errors)
│   │   ├── core/            — sync engine, diff logic, field mapping
│   │   │   ├── engine.py        — main sync loop: snapshot, diff, apply, log
│   │   │   ├── sync_policy.py   — two-axis direction+policy resolver (resolve_sync_action)
│   │   │   ├── conflict_apply.py— master_divergence resolve→apply actions (Phase B)
│   │   │   ├── single_record_import.py — single new SM/FDB filament import (conflict UI + engine auto-import)
│   │   │   ├── masters.py       — master/variant reconcile report helpers
│   │   │   ├── planner.py       — wizard execution planner
│   │   │   ├── dryrun.py        — dry-run preview helpers
│   │   │   ├── differ.py        — snapshot diff, change classification
│   │   │   ├── matcher.py       — fuzzy matching, variant cluster keys, finish-line extraction
│   │   │   ├── fields.py        — field mapping resolution (auto-match + explicit)
│   │   │   ├── filament_status.py — per-record sync-status classification
│   │   │   ├── weight.py        — net↔gross conversion, change threshold
│   │   │   ├── color.py         — multicolor/gradient conversion (FDB ↔ Spoolman)
│   │   │   ├── material_tags.py — finish-tag detection and serialization
│   │   │   ├── dates.py         — Spoolman timestamp → FDB date provenance mapping
│   │   │   ├── version.py       — semver helpers + MIN_FDB / MIN_SPOOLMAN gates
│   │   │   ├── compat.py        — shared upstream-version compatibility check
│   │   │   ├── change_log.py    — durable changes.log audit writer
│   │   │   ├── state_dump.py    — DEBUG_STARTUP_DUMP boot-state snapshot writer
│   │   │   ├── log_safe.py      — log-redaction helpers
│   │   │   ├── opentag_match.py — OPTMaterial → Spoolman field mapper + v2 scorer
│   │   │   ├── opentag_lexicon.py — n-gram lexicon miner (modifiers + colors); LEXICON_VERSION self-heal
│   │   │   ├── opentag_match_cache.py — memoized match results
│   │   │   └── opentag_cache.py — local OpenTag dataset cache (JSON, TTL-gated); direct tarball fetch + parse
│   │   ├── models/          — SQLAlchemy models (mapping, conflicts, log, snapshot, config)
│   │   ├── schemas/         — Pydantic models (bridge API, Filament DB, Spoolman shapes)
│   │   ├── services/        — Filament DB client, Spoolman client
│   │   └── main.py          — FastAPI app, scheduler setup, static file serving
│   └── requirements.txt
├── frontend/                — React SPA
│   ├── src/
│   │   ├── components/      — shared UI components
│   │   ├── pages/           — Wizard/, Dashboard.tsx, Conflicts.tsx, SyncLog.tsx,
│   │   │                       SyncedRecords.tsx, Settings.tsx, OpenTagCleanup.tsx,
│   │   │                       Reconcile.tsx, Login.tsx, DocsViewer.tsx
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
| Weight | (inline in `run_sync_cycle`) | Spoolman ↔ FDB; `newest_wins` available (weight-only) |
| Field mapping | `_apply_field_changes` | FR-11 mapped extra fields; follows material_properties direction |
| Cost | `_sync_cost` | Filament price, spool-price-first effective cost; FDB→SM writes filament price only |
| Temperatures | `_sync_material_props` | Native bed/nozzle temps: SM `settings_bed_temp`/`settings_extruder_temp` ↔ FDB `temperatures.bed`/`.nozzle` (read-modify-write preserves sibling temps) |
| Native scalars | `_sync_material_scalars` | SM `material`/`density`/`diameter`/`spool_weight`/`weight` ↔ FDB `type`/`density`/`diameter`/`spoolWeight`/`netFilamentWeight`; SM→FDB writes are master/variant-gated (see FR-11) |
| Multicolor | `_sync_multicolor` | Requires FDB ≥ 1.33.0; `color_hex`/`multi_color_hexes`/`multi_color_direction` ↔ FDB `color`/`secondaryColors`/`optTags` |
| Finish tags | `_sync_finish_tags` | Requires FDB ≥ 1.33.0; `optTags` (managed subset) ↔ Spoolman `extra.filamentdb_material_tags` |
| New spools | `_handle_new_sm_spool` / `_handle_new_fdb_spool` | FR-12; gated by `new_spool_sync_direction` |
| Stale-mapping purge | `_purge_stale_mapping` + orphaned-FilamentMapping cleanup | Removes bridge-local rows when no live, still-linked counterpart exists (see FR-13) |
| OpenTag identity | `_sync_opentag_identity` | Propagates `openprinttag_slug`/`uuid` from Spoolman extra fields into FDB `settings{}` bag |

All field-level passes (everything except weight and new-spool creation) follow the
`material_properties` direction + conflict policy. Every pass stores per-side snapshot
baselines and refreshes BOTH sides to the post-write agreed value after a successful
write, so propagated changes are never re-detected as fresh changes (anti-ping-pong).

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
- **Cross-reference pre-match:** any Spoolman filament whose spools carry a live
  `filamentdb_id` extra field is matched at confidence 1.0 before fuzzy matching runs
  (stale references fall through to fuzzy matching)
- Match remaining records by vendor name + filament name + color (fuzzy matching for case,
  whitespace, hyphen/underscore normalization, vendor aliases)
- Produce three buckets:
  - **Matched pairs** — high-confidence matches, ready to link
  - **Unmatched (source side)** — records that exist in the source but not the target, to be created
  - **Ambiguous** — multiple possible matches, need user resolution

#### FR-4: Match review UI
- Single unified table of all rows (matched / ambiguous / unmatched-SM / unmatched-FDB),
  with group-by (status / material / brand), sort, full-text search, per-column filters,
  and a status filter
- Tri-state checkboxes include/exclude rows per group or for the whole table; ambiguous
  rows offer per-candidate Link buttons plus create/skip
- Bridge-owned synthetic container parents render as a purple **Master / Parent** status
  (not "Unmatched (FDB)") and are excluded from bulk actions
- An **OPT badge** marks Spoolman filaments already tagged with an `openprinttag_uuid`;
  a filter shows tagged-only rows
- **Rescan** re-fetches both systems and prunes stale decisions; decisions persist in
  BridgeConfig (`wizard_match_decisions`) so the wizard is resumable
- Vendor-dedup hints surface rows where vendor names differ but normalize equal
  (e.g. "ELEGOO" vs "Elegoo")
- **Every record row displays two text-badge links:** "FDB" (blue badge) linking directly to that spool/filament in Filament DB's web UI, and "SM" (emerald badge) linking directly to Spoolman's web UI. Links open in new tabs.

#### FR-5: Weight conversion review
- Tare (empty-reel weight) is reviewed in the **Variances** step: one editable tare per
  variant group (the master's) and one per standalone filament; filaments with no known
  tare show a blank required field (red border) and **block Save & Next until filled** — no
  200 g default is ever written
- Overrides are expanded to per-spool `tare_overrides` and submitted with Execute
  (not persisted in BridgeConfig)
- For the Filament DB → Spoolman direction, a per-spool weight-conversion table
  (net/gross/tare/source) with per-spool override is shown instead

#### FR-6: Variances — variant grouping and reconciliation (Spoolman → FDB)
- A **variant parent mode** must be chosen in Settings before this direction can preview or
  execute (`409 variant_parent_mode_unset` otherwise):
  - `promote_color` — one color in each cluster is promoted to be the FDB parent; the rest
    become variants
  - `generic_container` — a colorless, bridge-owned container parent is created for every
    cluster (even single-color); every color is a child. Containers have no Spoolman
    counterpart (`is_synthetic_parent`, `spoolman_filament_id = NULL`) and never sync.
    See `docs/variant-parent-mode.md`.
- Included filaments are clustered by `(vendor, material, finish-line)` — the finish token
  (silk, matte, cf, …) is parsed from the name using the configurable
  `VARIANT_LINE_KEYWORDS` list so distinct lines never merge
- Members whose shared print properties conflict with the suggested master are pre-flagged
  **suggested standalone**; the user can move members between groups, create manual groups,
  make members standalone, or Ignore (skip) a filament entirely
- When an existing FDB parent line matches a cluster, the group offers
  **attach to existing parent** vs **create new parent**
- **Per-group property reconciliation:** conflicting shared properties
  (type/density/diameter/nozzle/bed/spool weight) get a pick-a-value UI (master value,
  any member's value, or manual). The reconciled values seed the FDB create AND are
  written back to every Spoolman filament in the group at execute (the only place the
  bridge corrects existing Spoolman data outside the OpenTag tool)
- Decisions persist in BridgeConfig (`wizard_sm_variant_decisions`,
  `wizard_variances_reconcile`)

#### FR-7: Execute import
- Write cross-reference IDs to both systems
- Create missing records in the target system; **created FDB filament names are always
  vendor + material [+ finish] + color** (e.g. "Hatchbox PLA Light Blue") so bare-color
  Spoolman names can never collide globally; the container marker (default `(Master)`)
  appears only on generic-container parents
- Per-record failure isolation: any create/update error (including FDB 409 name
  collisions) records a `failed` row and the batch continues; container-name collisions
  can be **renamed or skipped per cluster** at Preview (`wizard_container_name_overrides`)
- Stale local mappings whose FDB target was deleted upstream are detected by the planner
  and **recreated** (old mapping + snapshots removed) instead of being skipped as
  "already linked"
- Apply weight conversions (seed weights are SET on create — usage entries are only for
  ongoing decrements, FR-9); spool location is carried over (FDB locations are
  found-or-created by name) along with purchase/opened provenance dates
- If `never_import_empties` is on, spools with zero remaining weight are skipped at both preview and execute
- Post-create passes: Spoolman reconcile write-back (FR-6), finish-tag extra-field
  write-back, and OpenTag identity merge into FDB `settings{}` (scoped exception)
- Log all actions for audit trail; report created / updated / skipped / failed with a
  human-readable label and error detail per record; failures are surfaced prominently in
  the Execute result view
- `wizard_completed` flips only on a zero-failure run; the wizard is re-runnable and
  idempotent — already-linked records are skipped

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
- Compute the new net weight: `totalWeight - spoolWeight` (tare). **Do NOT subtract
  `usageHistory`** — Filament DB reduces `totalWeight` directly when usage is logged, so
  it is already the current gross; subtracting usage double-counts (this caused a runaway
  decrement loop, fixed 2026-06-10 — see `docs/decisions.md`)
- Call `PATCH /api/v1/spool/{id}` with `{ remaining_weight: new_net_weight }`
- After any weight propagation (either direction) BOTH side snapshots are refreshed to the
  post-write agreed values to prevent ping-pong re-detection

#### FR-11: Field mapping sync
- For configured field mappings (env var `FIELD_MAPPINGS`), sync values between Filament DB filament fields and Spoolman extra fields
- Auto-match: if a Spoolman extra field name matches a Filament DB field name exactly, sync automatically (unless excluded via `FIELD_MAPPING_EXCLUDES`)
- Explicit mapping: `FIELD_MAPPINGS=density=sm_density,temperatures.nozzle=nozzle_temp` overrides auto-match
- Direction + conflict policy follow the `material_properties` category settings
- **Native temperatures** — bed/nozzle temps are native fields on BOTH sides, so they are
  synced by a dedicated pass (`_sync_material_props`): SM `settings_bed_temp` /
  `settings_extruder_temp` ↔ FDB `temperatures.bed` / `.nozzle` (FDB writes
  read-modify-write the `temperatures` object so sibling temps survive)
- **Native shared filament scalars** — five fields with a direct FDB↔SM counterpart are synced by the dedicated `_sync_material_scalars` pass:
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
    - Inherited AND SM value diverges → queue a `master_divergence` conflict; the human
      resolves it with an explicit action that the bridge then applies upstream (FR-16)
  - `conflict_type` column on `Conflict`: `"cross_system"` (standard both-sides-changed) or `"master_divergence"` (inherited-field divergence)
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
- Conflict record includes: entity type, entity IDs on both sides, field name, value on each side, timestamps, and a `conflict_type`
- Queue persists across restarts; open conflicts are deduplicated (same field + IDs + type only queued once)
- Three classes of conflict:

**Both-sides-changed conflicts** (`conflict_type = "cross_system"`) — when `direction == "two_way"` and `conflict_policy == "manual"` (or `newest_wins` falls back): the same field changed on both sides since the last snapshot. The field name is the changed field (e.g. `weight`, `color`, `cost`, `material_tags`, `multicolor`, `density`, `bed_temp`).

**Master-divergence conflicts** (`conflict_type = "master_divergence"`) — an SM→FDB write of a native scalar would override a variant's inherited master value (FR-11 gate). Resolved via the explicit-action workflow in FR-16.

**Upstream-deletion conflicts** — when a previously mapped spool is missing from one side AND a live, still-linked counterpart exists on the other side ("still linked" = the surviving Spoolman spool still carries the `filamentdb_spool_id` cross-reference), `_queue_deletion_conflict` fires. The field name is the sentinel `DELETION_FIELD = "__record_deleted__"`. The surviving side carries a descriptor `{ "exists": true, "deleted_side": "spoolman"|"filamentdb" }`; the deleted side value is null. Resolution via the conflict UI removes the orphaned bridge mapping and both snapshots (`api/conflicts.py:_cleanup_orphaned_mapping`).

**Stale-connection purge (no conflict):** when BOTH sides are gone, or the FDB spool is gone and the surviving Spoolman spool's cross-reference was cleared, there is no live link to protect — the engine silently purges its own `SpoolMapping` + snapshots, auto-resolves any open deletion conflict (`resolution="auto_stale_purge"`), and logs an audit entry. Orphaned `FilamentMapping` rows (non-synthetic, no remaining spool mappings, FDB filament absent) are purged the same cycle. Bridge-local rows only — upstream records are never deleted.

#### FR-14: Validation dry run
- Before enabling auto-sync, user can trigger a dry run
- Shows exactly what the next sync cycle would do: creates, updates, conflicts
- User reviews and explicitly enables auto-sync
- Can be re-run at any time

### P1 — Web UI

#### FR-15: Dashboard
- Show sync status: last sync time, next scheduled sync, records in sync, pending conflicts
- Connectivity status for both systems, including per-system minimum-version warnings
- When a known upstream version is below its minimum, a red "Sync disabled" banner lists
  the reasons and the sync buttons are disabled (`sync_blocked` / `sync_blocked_reasons`
  from `GET /api/sync/status`)
- Quick stats: total filaments, total spools, synced vs unsynced counts

#### FR-16: Conflict resolution UI
- Collapsible, sortable conflict rows with type badges (Deleted record / New spool /
  Weight / Multicolor / Property / Master divergence), type filters, bulk resolve,
  expand/collapse-all, and a `?highlight=<id>` deep-link target (used by Synced Records'
  "See conflict" button)
- For each standard conflict: show both values, let user pick one or enter a manual value
- **Every conflict row displays two text-badge links** — "FDB" (blue) linking to Filament DB, "SM" (emerald) linking to Spoolman — to the affected record (same URL patterns as FR-4)
- **Standard (cross_system) conflicts converge on resolve:** resolving WRITES the chosen
  value to BOTH systems and refreshes both snapshots, then removes the conflict from the open
  queue. This is human-approved reconciliation (not silent auto-apply) and mirrors how the
  lifecycle and master-divergence paths already converge — the next sync cycle re-reads the
  agreed value and does not re-queue (GitHub #21). Every field family is handled by reusing
  the matching sync-pass write + conversion + snapshot key: `weight` (a **direct absolute
  write** to both sides — SM `remaining_weight = W`, FDB `totalWeight = W + tare`; **no usage
  entry**, consistent with the weight-increase correction path), `multicolor`/`material_tags`
  (signature-based — the write payload is re-derived from the chosen side's live state),
  `cost`, the temperature/scalar/OpenPrintTag material-property fields, and dynamic
  `FIELD_MAPPINGS` extra fields. `weight` resolution: `spoolman` → stored SM net; `filamentdb`
  → stored FDB gross − tare; `manual` → the value entered, interpreted as net (Spoolman units).
  A conflict whose `field_name` has no known apply path returns **422** (visible, never a silent
  record-only no-op); `multicolor`/`material_tags` reject `manual` (no scalar representation).
  Any upstream write failure returns **502** and leaves the conflict open with no partial
  snapshot advance. Deletion conflicts remain record-only and additionally clean up the
  orphaned bridge mapping and snapshots. New-spool / new-filament conflicts can be **dismissed
  OR imported directly from the conflict UI** — `POST /conflicts/{id}/import` (driven by
  `GET /conflicts/{id}/filament-suggestions`) creates the single record, and the Conflicts
  "Bulk Add" modal imports several at once. The wizard remains the bulk path; the conflict
  queue is no longer dismiss-only.
- **Master-divergence conflicts apply upstream on resolve** (human-approved, never silent).
  The expanded card fetches `GET /conflicts/{id}/divergence-context` (master + full variant
  line with live values and inherited/overridden status) and offers three actions:
  - `apply_all` — write the incoming value to the FDB master + every explicitly-overridden
    variant, and to every mapped Spoolman filament in the line; sibling master-divergence
    conflicts on the same field+line auto-resolve
  - `variant_override` — write to this variant only (becomes its own setting); master and
    siblings untouched
  - `ignore` — no writes; current values are stored as baselines so the divergence is not
    re-queued next cycle
  - Snapshots refresh for every successfully-written record (failed writes keep their old
    baseline so the next cycle retries); any upstream failure returns 502 and leaves the
    conflict open

#### FR-17: Sync log
- Scrollable log of all sync actions with timestamps (paginated, newest first)
- Filter by: entity type, direction, action type (create, update, skip, conflict, error)
- **Window selector** (last 10 / last 25 sync cycles / all) limits display to the most
  recent cycles without deleting entries; window mode groups rows under per-cycle headers
- **Clear log** action permanently deletes all log entries from SQLite (confirmation required)
- Entries older than `sync_log_retention_days` (default 30; 0 = forever) are pruned
  automatically — on each auto-sync tick, and (since auto-sync is off by default) also on
  every manual sync trigger, the nightly backup job, and once at startup
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

#### FR-20: Discord notifications *(Not implemented)*
- `DISCORD_WEBHOOK_URL` env var is declared and validated, but no posting code exists
- On conflict: post to configured Discord webhook with conflict details *(planned)*
- On sync error: post with error details and retry status *(planned)*
- Optional: daily summary of sync activity *(planned)*

#### FR-21: Spoolman archive/retire sync
- Lifecycle state mirrors **bidirectionally for already-mapped spool pairs**: archiving a spool in Spoolman (`archived`) retires it in Filament DB (`retired: true`), retiring it in FDB archives it in Spoolman, and both un-flips mirror back too (un-archive re-enables weight sync)
- A dedicated `archive_sync` policy category governs it: `archive_sync_direction` (default `two_way`) and `archive_conflict_policy` (default `manual`). `newest_wins` is rejected (the state is a boolean with no comparable timestamp)
- **Import gate preserved (intentionally asymmetric):** *unmapped* archived spools are still NOT auto-imported during ongoing sync — only the *mapped-pair* diffing set includes archived spools so a post-mapping flip is mirrored. Import is about not cluttering FDB with already-dead inventory; mirroring keeps already-paired spools honest
- **Weight settles before the archive bit:** the lifecycle pass runs after the weight pass, so a depleted-and-archived spool propagates its final decrement and FDB usage-log entry (and refreshes both snapshots) before the archive/retire bit mirrors — never retired/archived with a stale weight or missing its final usage entry
- A one-sided flip is a clean push (not a conflict). Only genuine divergence (both sides flipped to opposite states since the last snapshot) queues a `cross_system` conflict with `field_name="lifecycle"`; resolving it writes the chosen boolean to both systems and refreshes both snapshots. Both sides flipping to the same state converges silently

#### FR-21b: Spool location sync *(GitHub #29)*
- Spool storage **location** mirrors **bidirectionally for already-mapped spool pairs** in the continuous engine: changing a spool's location in Spoolman (free-text `location` string) updates the Filament DB spool's `locationId`, and a Filament DB location change writes the resolved name back to Spoolman
- **Compared by name.** Spoolman stores the location as a string; Filament DB references it by `locationId`. The engine resolves each `locationId` to its name (one `GET /api/locations` per cycle, building an `{_id: name}` map threaded into both snapshot builders) so the diff is name-vs-name, and **finds-or-creates** the matching Filament DB location on a Spoolman→Filament DB push (shared `core/locations.py:ensure_fdb_location`, never duplicated)
- A dedicated `location_sync` policy category governs it: `location_sync_direction` (default `two_way`) and `location_sync_conflict_policy` (default `manual`). `newest_wins` is rejected (a location name has no comparable timestamp)
- The location pass is **independent of weight** (no ordering requirement) but runs inside the same per-pair block (alongside the lifecycle pass) for one snapshot-refresh path. After any push, both snapshot location names refresh (anti-ping-pong)
- A one-sided change is a clean push (not a conflict). Only genuine divergence (both sides changed to different names since the last snapshot) queues a `cross_system` conflict with `field_name="location"`; resolving it writes the chosen name to both systems (find-or-create on Filament DB) and refreshes both snapshots. Both sides changing to the same name converges silently

#### FR-22: Print history enrichment *(Not implemented)*
- Planned: when a weight decrement is synced from Spoolman, optionally create a `POST /api/print-history` record in Filament DB
- Would require OctoPrint job metadata (filename, duration) — may need an OctoPrint API call or Spoolman webhook

#### FR-23: Bulk operations
- Bulk resolve conflicts (e.g., "accept all from Spoolman")
- Bulk assign variants _(deferred — wizard-only for now)_
- Bulk update tare weights — **implemented** as a standalone **Tare Editor** page (nav item).
  Lists every mapped filament with its current tare on both sides (FDB `spoolWeight` ↔
  Spoolman `spool_weight`), flags missing/mismatched ones, and lets the user set tare per-row
  or for a multi-selected batch. Saving writes **both** systems at once and refreshes both
  `_mp_spool_weight` snapshots (anti-ping-pong), reusing the engine's material-scalar tare
  path. The list is **grouped by variant family** with a per-family select-all header; every
  mapped filament is editable (a variant write sets an explicit tare on both its sides).
  (`GET /api/tare`, `POST /api/tare/bulk`.)

#### FR-23b: OpenTag (OpenPrintTag) Cleanup tool
A standalone on-demand tool to match Spoolman filaments against the OpenPrintTag community dataset and apply corrections.

- **Dataset:** fetched directly from the OpenPrintTag GitHub tarball (no FDB involvement), cached locally at `DATA_DIR/opentag_cache.json` with a TTL of `OPENTAG_CACHE_MAX_AGE_HOURS`. Brand names, material properties, and secondary colors are all parsed in a single tarball download by `core/opentag_cache.py` (`_parse_tarball`); `core/opentag_lexicon.py` mines modifier/color n-gram lexicons from the dataset (a `LEXICON_VERSION` bump self-heals the cache).
- **Matching** (`core/opentag_match.py`): per-Spoolman-filament scoring by material family, vendor/brand (via `OPENTAG_VENDOR_ALIASES` map), color name similarity, hex proximity, and finish-tag overlap. Color-profile pre-filter (single/coextruded/gradient) prevents cross-profile matches. UUID exact-match bypasses fuzzy scoring for filaments already tagged by a prior run.
- **Review UI** (`frontend/src/pages/OpenTagCleanup.tsx`): per-filament card with a best match + up to 5 alternate candidates. Each candidate shows per-field comparison (current Spoolman value vs OpenTag suggestion). User selects a candidate and can mark individual fields "keep mine" or edit the suggested value. The **Manufacturer** field (vendor) shows only when the Spoolman vendor name and OpenTag brand differ after normalization.
- **Apply** (`POST /api/openprinttag/apply`): writes confirmed fields to Spoolman; for the vendor field, resolves or creates the Spoolman vendor via find-or-create (`_ensure_vendor`). After the Spoolman write, stamps `openprinttag_slug`/`openprinttag_uuid` into the linked FDB filament's `settings{}` bag via `FilamentDBClient.merge_filament_settings()` (the approved scoped exception).
- **Ignore flow:** a filament can be marked "ignore future updates" (`POST /api/openprinttag/ignore/{filament_id}`, stored in the `openprinttag_ignore` extra field) so the Updates Review banner stops surfacing it; its identity extras can be blanked via `POST /api/openprinttag/clear/{filament_id}`.
- Routes (8): `GET /api/openprinttag/status`, `POST /api/openprinttag/refresh`, `GET /api/openprinttag/matches`, `POST /api/openprinttag/apply`, `POST /api/openprinttag/clear/{filament_id}`, `POST /api/openprinttag/ignore/{filament_id}`, `GET /api/openprinttag/search`, `GET /api/openprinttag/completeness`.

#### FR-23c: Debug mode and reset tools
- `debug_mode` is a runtime-editable BridgeConfig flag (default `false`), toggled in Settings
- When `debug_mode` is `false`, all four debug endpoints return **403**
- `POST /api/debug/clear-spoolman-fdb-refs` — blanks the three `filamentdb_*` cross-ref extras on every Spoolman spool that has any set. Spoolman side only; the bridge DB is untouched.
- `POST /api/debug/clear-spoolman-opentag-ids` — blanks the OpenPrintTag identity extras (`openprinttag_slug`/`openprinttag_uuid`) on every Spoolman filament that has any set. Spoolman side only; the bridge DB and Filament DB are untouched.
- `POST /api/debug/reset-bridge-state` — deletes all rows from the five bridge state tables (mappings, snapshots, conflicts, sync log) and re-arms the wizard (`wizard_completed = false`). Bridge side only; BridgeConfig settings other than `wizard_completed` are preserved; upstream systems are untouched.
- `POST /api/debug/full-reset` — both cleanups in one call (Spoolman cross-refs first, then the bridge DB). A Spoolman failure does not abort the local reset; it is reported in `spoolman_error`.
- None of these tools ever delete records in Filament DB or Spoolman.
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

#### FR-24b: Scheduled backups
- A built-in nightly job writes backups into `DATA_DIR/backups/` and prunes old files, so backups happen without a cron host or manual clicks. **On by default** once deployed.
- **What it backs up (two independent toggles, both ON by default):**
  - **Bridge state** — the bridge's own `GET /api/backup/export` payload (mappings, runtime config, open conflicts) → `bridge-state-<UTC timestamp>.json`
  - **Filament DB snapshot** — the same `GET /api/snapshot` fetch used by the manual FDB backup → `filamentdb-snapshot-<UTC timestamp>.json`
- **Spoolman is deliberately excluded** from the scheduled path. Spoolman writes its server-side backup into its own data volume and the bridge has no way to prune it, so scheduling it would leak storage with no retention control. The manual `POST /api/backup/spoolman` button is unchanged.
- **Schedule:** nightly at a configurable UTC hour (default `03:00`, minute 0).
- **Retention:** configurable, default **7 days**. Only files the bridge writes (the two prefixes above) are eligible for deletion — Spoolman archives and unrelated files in the directory are never touched. Age is read from the UTC timestamp in the filename (mtime fallback).
- **Master enable** plus the two sub-toggles, the retention window, and the run hour are all editable in **Settings → Scheduled backups**; env vars (`BACKUP_*`) provide the start-up fallback (DB value wins when set, same precedence as the sync interval).
- This resolves the previously-unbounded accumulation of manual FDB snapshots in `DATA_DIR/backups/` (issue #5).
- Note: the bridge's own SQLite DB still depends on a host-volume backup — the scheduled job protects mappings/config (via the bridge-state export) but does not copy `bridge.db` itself.

#### FR-25: Configuration-only export *(Not implemented — folded into full backup)*
- Originally planned as a separate config-only export; folded into `GET /api/backup/export` which includes config in the full dump

#### FR-26: Authentication and API token
- Optional single-account password auth, enabled by default (`AUTH_ENABLED` env var)
- First visit shows a Setup screen (set admin password, bcrypt-hashed in BridgeConfig);
  subsequent visits show Login. Sessions are a stateless signed `fb_session` httpOnly
  cookie (itsdangerous TimestampSigner, 30-day max-age, secret auto-generated and persisted)
- All `/api/*` routes require auth except `GET /api/health`, `GET /api/version`, and the
  `/api/auth/*` endpoints; the SPA shell itself is public
- Optional single **API token** for machine access (`Authorization: Bearer` or `X-API-Key`,
  constant-time compare); enable/regenerate in Settings → Security; displayed masked
- Lockout recovery: set `AUTH_ENABLED=false`, restart, change the password in Settings,
  re-enable. Full model in `docs/security.md`.

#### FR-27: Version display and update check
- Sidebar shows the running version (build label includes `-dev+<sha>` on dev-channel
  builds) linking to its GitHub release
- The backend checks the GitHub releases API server-side (cached 6 h, degrades gracefully);
  when a newer release exists an "↑ vX.Y.Z" pill appears and a one-time release-notes modal
  is shown (per-version localStorage dismissal; suppressed on first run and on dev builds)
- `GET /api/version` is public. Channel/commit are baked in at image build time
  (`BUILD_CHANNEL` / `GIT_COMMIT` build args → `BRIDGE_CHANNEL` / `BRIDGE_COMMIT`).
  Details in `docs/version-update-check.md`.

#### FR-28: UI shell
- Light / dark / system theme (localStorage-persisted, pre-paint script avoids white flash)
- Required-settings gate: when a required setting is unset (currently
  `variant_parent_mode`), a modal prompts the user to visit Settings before using the bridge
- All timestamps render in the browser's local timezone

#### FR-29: Mobile updates & label printing
- A printed, QR-coded spool label plus a phone-friendly page to update that spool from a
  scale. The whole feature is gated by a single master setting `mobile_labels_enabled`
  (default OFF): while off, every `/api/mobile/*`, `/api/labels/*` endpoint and the `/r/`
  redirect return **403**, and the "Mobile updates" nav item is hidden
- **QR identity = Filament DB filament id + spool id.** The QR encodes
  `{bridge_public_url}/r/{fil}/{spool}`; the bridge resolves the Spoolman spool through its
  own mapping. Keeping the QR on the durable FDB ids lets a physical label survive
  re-imports/re-mapping
- **`/r/` redirect is the indirection point.** `GET /r/{fil}/{spool}` issues a **302** to a
  target chosen at runtime by `mobile_redirect_target`: `bridge` → the SPA scan page
  `/scan/{fil}/{spool}` (default); `filamentdb` → `{FILAMENTDB_URL}/filaments/{fil}`. This
  lets every existing label re-point (e.g. to a future FDB mobile page) **without
  reprinting**
- **Update page (scan target + in-nav search).** `GET /api/mobile/spool/{fil}/{spool}`
  returns the live spool detail; the card accepts a **gross scale weight** (with a live
  `net = gross − tare` preview, tare = the FDB filament's `spoolWeight`) and a location
  change (datalist from `GET /api/mobile/locations`). A single
  `PATCH /api/mobile/spool/{fil}/{spool}` writes both Filament DB and Spoolman and refreshes
  both snapshots (anti-ping-pong). The in-nav "Mobile updates" page reaches the same card via
  a per-spool search
- **Weight-save mode.** `mobile_weight_default_mode` (`direct_correction` default — absolute
  true-up | `usage` — log an FDB usage entry on a decrease, fall back to absolute on an
  increase), overridable per save
- **Label printing via LabelForge.** `POST /api/labels/print` prints a **user-created**
  LabelForge template (`{placeholder}` text + an optional `{qr_url}` QR element); the bridge
  supplies only the values for a fixed field catalog — `brand`, `color`, `color_hex`,
  `number` (Spoolman spool id), `material`, `qr_url` — sending **only** the names listed in
  `labelforge_fields` (unknown names skipped with a warning). A media mismatch returns 409
  with an `override=true` retry; `GET /api/labels/printer-status` backs a Settings "Test
  printer" check
- **Auth mirrors the app.** No token in the QR and no auth exception for the scan page — the
  flow sits behind the same session as every other page (open only when `AUTH_ENABLED=false`)
- **Caveat:** QR *rendering* in LabelForge exists only on its `dev` branch (newer than
  v0.1.3). The HTTP API is identical, so text fields print on any LabelForge version; a
  scannable QR element needs a LabelForge `dev` build. Full guide in `docs/mobile-updates.md`

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

6. **Rate limiting / full-snapshot diff** — ✅ **Resolved by code.** Full-snapshot diff each cycle. Spoolman's `GET /api/v1/spool` **excludes archived spools by default**, so the bridge fetches with `?allow_archived=true&limit=1000` to get active + archived in one listing (there is no `archived` filter param — an unknown `?archived=true` is silently ignored and returns active only; this once hid archived spools and made archived mapped spools look deleted, fixed in 0.5.1). Active-only callers filter `archived == false` client-side. Add incremental fetch only if a larger inventory demands it.

7. **Multi-printer attribution** — ✅ **Resolved.** Accept the aggregate delta; per-printer attribution is out of scope (documented, not silently dropped).

8. **Filament DB and Spoolman URL path patterns** — ✅ **Resolved by code.** Filament DB `{FILAMENTDB_URL}/filaments/{id}` (plural, no standalone spool page); Spoolman `{SPOOLMAN_URL}/spool/show/{id}` and `/filament/show/{id}` (no hash routing). UI renders text badges "FDB"/"SM", not vendor logos.
