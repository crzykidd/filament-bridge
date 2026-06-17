# filament-bridge

![version](https://img.shields.io/badge/version-0.2.0-blue)

Bidirectional sync between [Filament DB](https://github.com/hyiger/filament-db) and [Spoolman](https://github.com/Donkie/Spoolman) for 3D printing filament management.

> ## ⚠️ BETA — back up your databases before any writes
>
> filament-bridge is **beta** software that writes to both **Spoolman** and **Filament DB**.
> **Before** running the Bulk Import Wizard, applying an OpenTag cleanup, or enabling
> auto-sync, **back up all three databases** (Spoolman, Filament DB, and the bridge). See
> [Backups](#backups). Test against non-critical data first.

<p align="center">
  <img src="docs/images/dashboard.png" alt="filament-bridge Dashboard — in-sync spool and filament counts, connected-system health with versions, and sync controls" width="820">
</p>

---

## Why?

Filament DB and Spoolman are both excellent tools that solve different parts of the filament management problem:

- **[Filament DB](https://github.com/hyiger/filament-db)** excels at material profile management — deep slicer integration (PrusaSlicer, OrcaSlicer, Bambu Studio), per-printer/nozzle calibration storage, material science properties, NFC tag support, and AI-powered data sheet import.
- **[Spoolman](https://github.com/Donkie/Spoolman)** is a long-standing inventory solution with native connections to OctoPrint, Moonraker/Klipper, and Home Assistant (among others), plus a broad surrounding ecosystem. If you want to start using Filament DB but still rely on features Spoolman offers, this tool lets you combine both experiences instead of choosing one.

filament-bridge keeps the two in sync so you can use both without manual data entry. It runs as a single Docker container next to your existing instances, links records via Spoolman extra fields and Filament DB spool labels, and keeps its own state in SQLite — neither upstream system is ever modified beyond its documented REST API.

It also cleans up your spool and brand names in Spoolman against [OpenPrintTag](https://openprinttag.org) before pushing that standardized data into Filament DB — automating what would otherwise be tedious manual data hygiene.

It was built out of a real migration: moving filament management into Filament DB while keeping Spoolman fully working, because OctoPrint and Home Assistant talk to it directly and aren't going anywhere. That last part is why this is a continuous two-way sync, not a one-time export.

There are **two ways to onboard**: just bridge the two systems and create your Filament DB records straight from Spoolman, or do a little cleanup work against OpenPrintTag first so your catalog lands standardized and Filament DB can keep pulling canonical updates later. **[Getting started](docs/getting-started.md) walks through both paths** and helps you pick.

---

## What it does

- **Bulk Import Wizard** — a re-runnable six-step wizard (Connectivity → Direction → Matches → Variances → Preview → Execute) that pairs the two systems: fuzzy vendor+name+color matching with bulk actions, variant grouping with per-group tare and property reconciliation, a full dry-run preview with collision rename/skip, and a per-record execute report that isolates failures so one bad record never aborts the batch
- **Continuous sync engine** — polls both APIs on a configurable interval and diffs against last-known snapshots; syncs spool weights, material/density/diameter, spool & net filament weights, bed/nozzle temperatures, cost, structured multicolor/gradient colors, and OpenPrintTag finish tags
- **Per-category direction + conflict policy** — weight, material properties, and new-spool creation each have an independently configurable sync direction (`two_way` / one-way) and conflict policy (`manual` / `spoolman_wins` / `filamentdb_wins`; `newest_wins` for weight only)
- **Usage-logged weight sync** — Spoolman weight decrements become Filament DB usage entries (preserving the audit trail), never raw weight overwrites; net↔gross weight-model translation is automatic
- **Conflict queue** — when both sides change the same field between cycles, the change is queued for human decision; conflicts are never silently auto-resolved. Master-divergence conflicts (a Spoolman value that would override an inherited Filament DB variant setting) get a dedicated resolve workflow: apply to the whole line, make it the variant's own setting, or ignore
- **Variant model translation** — understands Filament DB's parent/variant hierarchy and builds it from flat Spoolman filaments, either by promoting one color to parent or by creating a colorless container parent per line (your choice — see [variant parent mode](docs/variant-parent-mode.md))
- **OpenTag (OpenPrintTag) cleanup tool** — matches your Spoolman filaments against the OpenPrintTag community database, lets you review every field, applies canonical data to Spoolman, and stamps the OpenPrintTag slug/UUID into Filament DB
- **Upstream-deletion handling** — a deletion on one side queues a conflict when a live, linked counterpart needs protecting; stale links with nothing to protect are purged from the bridge automatically
- **Web UI** — Dashboard, Synced Records (expandable per-field side-by-side detail, conflict deep-links), Conflicts, Sync Log (per-cycle windows), Settings; every record links straight to its page in Filament DB and Spoolman; light/dark/system theme
- **Authentication** — single-account password login (on by default) with an optional API token for machine access; see [Security](#security)
- **Pre-write backup safeguard** — a backup dialog gates the three write actions (wizard Execute, OpenTag Apply, enabling auto-sync) with one-click Spoolman and Filament DB backups
- **Backup & restore** — export/import the bridge's own state (mappings, config, open conflicts) as JSON
- **Version badge + update check** — the sidebar shows the running version and surfaces new GitHub releases (checked server-side, cached 6 h)
- **Debug reset tools** — a gated Danger Zone (off by default) with three reset tools for clean re-testing: clear Spoolman cross-refs, reset the bridge DB, or both at once

<img src="docs/images/wizard-matches.png" alt="Bulk Import Wizard, Matches step — fuzzy vendor/name/color pairing of Spoolman and Filament DB records with per-row status and bulk actions" width="760">

---

## What's New

### v0.2.0 (2026-06-15)

First public release. The bridge is feature-complete for two-way sync between Filament DB and Spoolman:

- **Bulk Import Wizard** — re-runnable six-step wizard with fuzzy matching, variant grouping, dry-run preview, and per-record execute reporting
- **Continuous sync engine** — snapshot/diff/apply loop with per-category sync direction + conflict policy (two-axis model) for weight, material properties, and new-spool creation
- **Conflict queue** — conflicts are always queued for human decision, never silently resolved; includes the master-divergence resolve workflow for variant inheritance
- **OpenTag (OpenPrintTag) cleanup tool** — match Spoolman filaments against the community dataset, review per field, and stamp canonical slug/UUID into both systems
- **Variant parent modes** — `promote_color` or `generic_container`, building Filament DB's parent/variant hierarchy from Spoolman's flat list
- **Weight-model translation** — net↔gross conversion with Spoolman decrements logged as Filament DB usage entries (audit trail preserved)
- **Structured multicolor/gradient, finish-tag, and bed/nozzle temperature sync**
- **Minimum upstream version enforcement** — sync is hard-gated below Filament DB 1.33.0 / Spoolman 0.22.0
- **Single-account auth + optional API token**, light/dark/system theme, version badge with GitHub update check, and a pre-write backup safeguard

See [CHANGELOG.md](CHANGELOG.md) for the full list.

---

## Quick start (Docker)

[`docker-compose.yml`](docker-compose.yml) is the standard bridge-only deployment — it pulls the published image and points at your existing Filament DB and Spoolman instances. Copy it, fill in your URLs, and run:

```bash
docker compose up -d
```

To add the bridge to an existing compose file:

```yaml
services:
  filament-bridge:
    image: ghcr.io/crzykidd/filament-bridge:latest
    restart: unless-stopped
    ports:
      - "8090:8090"
    volumes:
      - bridge-data:/data        # REQUIRED — persists the SQLite state database
    environment:
      FILAMENTDB_URL: http://your-filament-db-host:3000   # your existing Filament DB
      SPOOLMAN_URL: http://your-spoolman-host:7912         # your existing Spoolman
      # SYNC_INTERVAL_SECONDS: 120
      # See docs/configuration.md for all options

volumes:
  bridge-data:
```

> **Note:** the `bridge-data:/data` volume is required. Without it, all bridge state (mappings, sync history, wizard progress) is lost on every container restart.

For a full local stack (bridge + Filament DB + MongoDB + Spoolman) for development or testing, use [`docker-compose.dev.yml`](docker-compose.dev.yml) instead:

```bash
docker compose -f docker-compose.dev.yml up -d --build
```

### First run

New to the bridge? **[docs/getting-started.md](docs/getting-started.md)** explains the two
onboarding paths (just-bridge-them vs. clean-up-against-OpenPrintTag-first) and walks through
each. The short version:

1. Open `http://localhost:8090`. The bridge asks you to **set an admin password**
   (authentication is on by default — set `AUTH_ENABLED=false` to skip it).
2. Pick a **variant parent mode** in Settings when prompted — the Bulk Import Wizard
   won't run in the Spoolman → Filament DB direction until you do
   ([what the modes mean](docs/variant-parent-mode.md)).
3. **Back up both systems**, then run the **Bulk Import Wizard** to pair your records.
4. Review the **dry run** from the Dashboard, then explicitly **enable auto-sync**.
   Auto-sync is always OFF until you turn it on.

---

## Prerequisites

**Minimum supported versions — sync is disabled below these:**

| System | Minimum supported | Why |
|---|---|---|
| **Filament DB** | **1.33.0** | structured multicolor/gradient, finish-tag, and temperature sync |
| **Spoolman** | **0.22.0** | structured multi-color fields (`multi_color_hexes` / `multi_color_direction`) and the stable extra-fields system used for cross-reference IDs |

These minimums are **enforced, not advisory.** When the bridge can read an upstream's version and
it is below the minimum, **sync is hard-gated**: the sync trigger, dry-run, and the Bulk Import
Wizard all refuse with *"Sync disabled — upgrade … to use"*, and scheduled auto-sync cycles are
skipped. The bridge still starts and the UI loads — the Dashboard and `GET /api/health` surface a
per-system warning explaining why sync is off — so you can see and fix it. An **unknown/unreadable**
version does *not* block sync (that is treated as a connectivity issue, surfaced as `degraded`
health, not as "too old").

Latest tested upstreams: **Filament DB 1.49.0** and **Spoolman 0.23.1**.

- **Filament DB** — the bridge gates version-specific features automatically.
- **Spoolman** — the bridge creates its required extra fields (`filamentdb_id`, `filamentdb_spool_id`, etc.) automatically on startup if they are missing.
- Both upstream APIs are unauthenticated **by default**. **Filament DB ≥ 1.39.0** can optionally require an API key (FDB's own `FILAMENTDB_API_KEY`); if you enable it, set the bridge's `FILAMENTDB_API_KEY` to the same value and the bridge sends `Authorization: Bearer <key>` on every Filament DB request. Spoolman's API has no auth. (The bridge's own UI/API has its own login; see [Security](#security).)

---

## Safety model — what the bridge will never do

- **Auto-sync is OFF by default** — you must explicitly enable it after completing the wizard and reviewing the dry-run plan
- **Conflicts are never auto-resolved** — every conflict is queued for manual human decision; no silent value-picking
- **Records are never deleted** from either upstream system without explicit user action in the bridge UI
- **Weight decrements are logged as usage entries** in Filament DB (via `POST /api/filaments/:id/spools/:spoolId/usage`), preserving the full usage-history audit trail
- **No upstream code modification** — the bridge uses only the documented REST APIs and Spoolman's extra field system; neither Filament DB nor Spoolman is forked or patched

Every field the bridge writes to Spoolman, and when, is enumerated in
[docs/spoolman-writes.md](docs/spoolman-writes.md).

---

## Backups

**Before running the Bulk Import Wizard, applying an OpenTag cleanup, or enabling auto-sync, back up all three systems.** The pre-write safety dialog offers one-click backups of both upstreams; the same endpoints are available directly:

### Spoolman

Trigger a safe server-side backup via the API (Spoolman does not need to be stopped; it copies its database into a `backups/` folder inside its own data volume):

```bash
curl -X POST http://<spoolman-host>:7912/api/v1/backup
```

Make sure Spoolman's data volume is itself persisted/copied — the backup file lands inside that volume.

### Filament DB

Filament DB exposes `GET /api/snapshot` — a full JSON backup of all collections. Restore with `POST /api/snapshot` (destructive).

**One-click via the bridge:** the pre-write safety dialog's "Back up Filament DB now" button calls `POST /api/backup/filamentdb`, which downloads the snapshot to the bridge's data volume (`DATA_DIR/backups/filamentdb-snapshot-<timestamp>.json`).

```bash
curl http://<fdb-host>:3000/api/snapshot -o fdb-snapshot.json
```

Or back up the raw MongoDB volume:

```bash
docker exec <mongo-container> mongodump --archive=/data/db/fdb-$(date +%F).archive
```

### filament-bridge

Export the bridge's own state (mappings, runtime config, open conflicts) from Settings → Backup, or:

```bash
curl http://<bridge-host>:8090/api/backup/export -o bridge-backup.json
```

Restore with `POST /api/backup/import`.

**Audit log — `changes.log`:** every write the bridge makes to Spoolman or Filament DB is appended to `{DATA_DIR}/changes.log` (default `/data/changes.log`). Each line shows a UTC timestamp, action, target system, entity id, and old → new values for updates — useful for reviewing what changed after a bad release without needing the UI or the SQLite database. The file rotates automatically at ~10 MB (keeps 3 backups). Disable with `CHANGES_LOG_ENABLED=false`. Pairs with `DEBUG_STARTUP_DUMP` (point-in-time boot snapshot) for a full before/after picture.

---

## How sync works

### Per-category direction and conflict policy

Each data category is configured independently on two axes in Settings:

- **Sync direction** — `filamentdb_to_spoolman`, `spoolman_to_filamentdb`, or `two_way`
- **Conflict policy** — what happens when the same field changes on both sides between
  cycles (only consulted under `two_way`): `manual` (queue for human decision, the default),
  `spoolman_wins`, `filamentdb_wins`, or `newest_wins` (weight only — Spoolman exposes no
  per-filament modification timestamp)

Defaults: weight syncs Spoolman→FDB; material properties sync FDB→Spoolman; new spools and archive/retire both sync two-way.

<img src="docs/images/settings-direction-policy.png" alt="Settings — per-category sync direction and conflict policy controls for weight, material properties, and new records" width="760">

### What syncs

Beyond spool weight, the engine syncs the shared filament surface per cycle: material/type,
density, diameter, spool (tare) weight, net filament weight, bed/nozzle temperatures, cost,
structured multicolor/gradient colors, OpenPrintTag finish tags, and any extra fields you map
via `FIELD_MAPPINGS`. It also mirrors each synced spool's **archive/retire lifecycle state**
between the two systems (see [below](#archive--retire-lifecycle)). The full pass-by-pass model
lives in [docs/sync-model.md](docs/sync-model.md).

<img src="docs/images/synced-records.png" alt="Synced Records — paired spools with an expanded row showing field-by-field Spoolman vs Filament DB values and deep links to each system" width="820">

### Weight model translation

Spoolman tracks **net filament weight** (`remaining_weight` excludes the reel). Filament DB tracks **gross spool weight** (`totalWeight` includes the reel; the filament-level `spoolWeight` field is the empty-reel tare).

- Spoolman → Filament DB: weight decrements are logged as usage entries — never raw overwrites
- Filament DB → Spoolman: `remaining_weight = totalWeight − spoolWeight`

### Archive / retire (lifecycle)

Once a spool is synced, its lifecycle state stays in step across both systems: archiving a
spool in Spoolman retires it in Filament DB, and retiring it in Filament DB archives it in
Spoolman — un-archiving/un-retiring mirrors back the same way. It runs as its own category
(`archive_sync`, default `two_way` / `manual`), and the final weight always settles **before**
the archive bit propagates, so a depleted-then-archived spool never lands on the other side
with a stale weight. A one-sided change is a clean push; only a genuine both-sides divergence
queues a conflict.

This is separate from the wizard's **Skip empty & archived spools on import** setting, which
only controls whether already-dead spools are pulled in during a bulk import — it does not
affect ongoing lifecycle mirroring.

### Variant tracking

Filament DB uses parent/variant inheritance (one parent with shared settings, color variants underneath). Spoolman is flat — one filament per color. The bridge tracks the relationship via Spoolman extra fields (`filamentdb_id`, `filamentdb_parent_id`) and builds the hierarchy at import time according to your [variant parent mode](docs/variant-parent-mode.md). When a Spoolman change would override a variant's *inherited* setting, the bridge queues a master-divergence conflict instead of silently detaching the variant from its parent — you decide whether the change applies to the whole line, just that variant, or not at all.

### Conflict resolution

All conflicts are queued — never silently resolved — and shown on the Conflicts page with both values and deep links. Resolving a standard conflict records your choice; resolving a master-divergence conflict applies your chosen action upstream. Details in [docs/conflicts.md](docs/conflicts.md).

<img src="docs/images/conflicts.png" alt="Conflicts page — queued new-filament and conflict entries with per-entry Add/Dismiss and resolution actions; nothing is auto-resolved" width="760">

---

## Concepts

### The filament → spool hierarchy

A **filament is a container**. In Filament DB, the hierarchy is:

```
Parent filament (shared properties: material, diameter, density, temps)
  └── Variant filament (inherits parent; overrides: color, name suffix)
        └── Spool (weight, location, purchase date)
```

Spoolman is flat: every color is its own filament. The bridge builds the Filament DB
hierarchy from Spoolman's flat list at import time (Bulk Import Wizard) and maintains it
with cross-reference IDs (`filamentdb_id`, `filamentdb_parent_id`) stored in Spoolman
extra fields.

### Hold-until-filament rule

Sync flows **top-down**. A spool can only be created in the target system once its filament
exists and is mapped there. If the filament isn't mapped yet:

- Under `manual_review` (the default): a `new_filament` conflict is queued. The Conflicts
  page surfaces an **Import** button that creates the filament on the other side (powered by
  `POST /api/conflicts/{id}/import`) without leaving the page. Any spools belonging to that
  filament are held until you act.
- Under `auto_import`: the engine creates the filament automatically (same code path as the
  wizard), writes the mapping and cross-reference IDs, and releases held spools to normal
  new-spool handling.

Spools are **never silently dropped** — they wait in the conflict queue until their filament
is resolved.

### New-record policy axes

Two independent settings (Settings → New records) control this behavior:

| Setting | Values | Effect |
|---|---|---|
| `new_filament_policy` | `manual_review` (default) / `auto_import` | Queue a conflict vs auto-create for unmapped filaments |
| `new_spool_policy` | `manual_review` (default) / `auto_import` | Queue a conflict vs auto-create for unmapped spools on already-mapped filaments |

Both default to `manual_review` — no records appear in either system without a human
decision or an explicit enable.

---

## OpenTag cleanup tool

The OpenTag tool matches your Spoolman filaments against the [OpenPrintTag](https://openprinttag.org) database, which provides standardized filament identification (slugs, UUIDs, finish tags).

1. Open the OpenTag Cleanup page — the bridge fetches the dataset directly from the OpenPrintTag GitHub tarball (cached locally for 24 h) and scores every Spoolman filament: brand pre-filter (with configurable vendor aliases), color-profile and polymer-family gates, color-name + hex + finish-aware scoring
2. Review per filament: the best match plus up to 5 alternates, each with a field-by-field comparison; accept, edit, mark fields "keep mine", switch candidates, or ignore
3. Confirm and apply — the bridge writes the confirmed fields to Spoolman (creating vendors via find-or-create where you approved a manufacturer change) and stamps `openprinttag_slug`/`openprinttag_uuid` into both systems

Vendor-name and color-word mappings for the matcher are editable in Settings. Full guide: [docs/opentag-cleanup.md](docs/opentag-cleanup.md).

<img src="docs/images/opentag-review.png" alt="OpenTag Cleanup — match list across the catalog with an expanded filament showing field-by-field Filament DB / Spoolman / use-value comparison and per-field keep-mine controls" width="820">

---

## Security

Authentication is **on by default**: the first visit asks you to set an admin password, after
which the UI and API require a login (signed httpOnly session cookie, 30-day max-age). An
optional **API token** (Settings → Security) allows machine access via
`Authorization: Bearer <token>` or `X-API-Key`.

Locked out? Set `AUTH_ENABLED=false`, restart, change the password in Settings → Security,
then re-enable. The full model — crypto choices, protected routes, recovery — is in
[docs/security.md](docs/security.md).

---

## Configuration

All connection configuration is via environment variables; the service refuses to start without `FILAMENTDB_URL` and `SPOOLMAN_URL`. Most behavior settings are also editable at runtime in the Settings UI (stored in SQLite; the env var is the startup default).

| Variable | Required | Default | Description |
|---|---|---|---|
| `FILAMENTDB_URL` | **Yes** | — | Base URL of your Filament DB instance (e.g. `http://filament-db:3000`) |
| `SPOOLMAN_URL` | **Yes** | — | Base URL of your Spoolman instance (e.g. `http://spoolman:7912`) |
| `SYNC_INTERVAL_SECONDS` | No | `120` | Seconds between auto-sync cycles (runtime-editable in Settings) |
| `AUTH_ENABLED` | No | `true` | `false` fully bypasses authentication (also the lockout-recovery path) |
| `PUID` / `PGID` | No | `1000` | UID/GID the container process runs as (see [Permissions](#permissions)) |
| `DATA_DIR` | No | `/data` | Directory for the SQLite state database and backup files |
| `FILAMENTDB_SPOOLMAN_ID_FIELD` | No | `label` | Filament DB spool field used to store the Spoolman spool ID |
| `SPOOLMAN_FIELD_FILAMENTDB_ID` | No | `filamentdb_id` | Spoolman extra field name for the Filament DB filament ID |
| `SPOOLMAN_FIELD_FILAMENTDB_PARENT_ID` | No | `filamentdb_parent_id` | Spoolman extra field for the FDB parent filament ID (variant tracking) |
| `SPOOLMAN_FIELD_FILAMENTDB_SPOOL_ID` | No | `filamentdb_spool_id` | Spoolman extra field for the FDB spool subdocument ID |
| `SPOOLMAN_FIELD_FILAMENTDB_MATERIAL_TAGS` | No | `filamentdb_material_tags` | Spoolman extra field storing finish-tag IDs (CSV string, e.g. `16,17`) |
| `FIELD_MAPPINGS` | No | — | Comma-separated `fdb_field=spoolman_field` pairs for explicit field mapping |
| `FIELD_MAPPING_EXCLUDES` | No | — | Comma-separated field names to exclude from auto-matching |
| `VARIANT_LINE_KEYWORDS` | No | `silk,matte,satin,…` | Keywords that separate variant lines (runtime-editable) |
| `CONTAINER_PARENT_MARKER` | No | `(Master)` | Marker appended to generic-container parent names; empty = none (runtime-editable) |
| `MATERIAL_TAG_IDS` | No | (seed list) | CSV of `keyword=id` pairs overriding the default finish-tag ID map |
| `OPENTAG_VENDOR_ALIASES` | No | — | CSV of `spoolman_vendor=opentag_brand` pairs for OpenTag brand matching (runtime-editable) |
| `SPOOLMAN_FIELD_OPENPRINTTAG_SLUG` | No | `openprinttag_slug` | Spoolman extra field for the OpenPrintTag slug |
| `SPOOLMAN_FIELD_OPENPRINTTAG_UUID` | No | `openprinttag_uuid` | Spoolman extra field for the OpenPrintTag UUID |
| `OPENTAG_CACHE_MAX_AGE_HOURS` | No | `24` | Hours before the locally cached OpenPrintTag dataset is considered stale |
| `BRIDGE_CHANNEL` / `BRIDGE_COMMIT` | No | `release` / — | Build channel + short SHA baked in at image build time (dev builds get a `-dev+sha` version label) |
| `DISCORD_WEBHOOK_URL` | No | — | Declared for future conflict/error notifications (delivery not yet implemented) |
| `LOG_LEVEL` | No | `info` | Logging verbosity (`debug`, `info`, `warn`, `error`) |
| `DEBUG_STARTUP_DUMP` | No | `false` | When `true`, writes a human-readable upstream-state snapshot to `{DATA_DIR}/state-dumps/` at boot (newest 10 kept). Development use only. |
| `CHANGES_LOG_ENABLED` | No | `true` | When `false`, disables the durable per-write audit log at `{DATA_DIR}/changes.log`. |
| `CHANGES_LOG_PATH` | No | `{DATA_DIR}/changes.log` | Override the path for the changes.log file. |

See **[docs/configuration.md](docs/configuration.md)** for the complete reference, including every runtime-editable setting (sync direction + conflict policy, variant parent mode, weight threshold/precision, log retention, debug mode, API token, and more).

---

## Permissions

The container starts as root, automatically `chown`s `/data` to the runtime user, then drops privileges to **uid 1000 / gid 1000** (user `app`) via `gosu`. No manual `chown` is ever needed — pre-existing root-owned volumes are corrected automatically on start.

Override the runtime uid/gid with `PUID` / `PGID` environment variables if your host uses a different uid:

```yaml
environment:
  PUID: "1001"
  PGID: "1001"
```

This applies to named volumes and bind mounts alike, including volumes created by older versions that ran as root.

---

## Architecture

```
                          ┌──────────────────────────────────────┐
                          │           filament-bridge            │
                          │                                      │
┌─────────────┐           │  - Bulk Import Wizard                │           ┌───────────────┐
│  Filament DB │◄─────────┤  - Continuous sync engine            ├──────────►│    Spoolman   │
│  (Next.js)   │  FDB API │  - Conflict queue + resolution       │  SM API   │   (FastAPI)   │
└──────┬───────┘          │  - OpenTag cleanup tool              │           └───────┬───────┘
       │                  │  - Web UI (React SPA)                │                   │
       ▼                  └──────────────────────────────────────┘                   ▼
┌─────────────┐                                                          ┌───────────────────┐
│ PrusaSlicer  │                                                          │  OctoPrint        │
│ OrcaSlicer   │                                                          │  Moonraker/Klipper│
│ Bambu Studio │                                                          │  Home Assistant   │
└─────────────┘                                                          └───────────────────┘
```

Both Filament DB and Spoolman continue to function independently. filament-bridge is the glue that keeps them in sync. If the bridge goes down, both systems keep working — you just lose sync until it's back up. OctoPrint, Moonraker, and Klipper talk to **Spoolman** directly; the bridge is not in that data path.

**Stack:** Python 3.12 / FastAPI backend, React 18 / TypeScript / Tailwind frontend, SQLite state via SQLAlchemy + Alembic, APScheduler for the sync interval. Single image, single port (8090).

---

## Documentation

| Doc | What it covers |
|---|---|
| [docs/getting-started.md](docs/getting-started.md) | Why the bridge exists, the two onboarding paths, and a first-run walkthrough of each |
| [docs/configuration.md](docs/configuration.md) | Every env var and runtime setting |
| [docs/sync-model.md](docs/sync-model.md) | The sync engine: passes, snapshots, direction/policy resolution, version gating |
| [docs/wizard.md](docs/wizard.md) | The Bulk Import Wizard, step by step |
| [docs/conflicts.md](docs/conflicts.md) | Conflict types and what each resolution actually does |
| [docs/variant-parent-mode.md](docs/variant-parent-mode.md) | `promote_color` vs `generic_container`, container naming |
| [docs/opentag-cleanup.md](docs/opentag-cleanup.md) | The OpenTag matcher and apply flow |
| [docs/security.md](docs/security.md) | Auth model, API token, lockout recovery |
| [docs/spoolman-writes.md](docs/spoolman-writes.md) | Every field the bridge writes to Spoolman, and when |
| [docs/version-update-check.md](docs/version-update-check.md) | Version badge and GitHub update check |
| [docs/migration-spoolman-to-filamentdb.md](docs/migration-spoolman-to-filamentdb.md) | Standalone one-time migration guide (without the bridge) |
| [docs/prd.md](docs/prd.md) | The full product spec |
| [docs/decisions.md](docs/decisions.md) | Why things are the way they are |

---

## Local development

### Prerequisites

- Python 3.12+, Node 22+
- A running Filament DB instance and a running Spoolman instance (or use `docker-compose.dev.yml` to spin up the full local stack)

### Backend

```bash
cd backend
pip install -r requirements.txt
FILAMENTDB_URL=http://localhost:3000 SPOOLMAN_URL=http://localhost:7912 \
  uvicorn app.main:app --reload --port 8090
```

### Frontend

```bash
cd frontend
npm install
npm run dev   # Vite dev server; API calls are proxied to the backend on :8090
```

### Tests

```bash
cd backend && pytest
cd frontend && npm test
```

### Database migrations

SQLite schema changes go through Alembic:

```bash
cd backend
alembic revision --autogenerate -m "description"
alembic upgrade head
```

---

## Changelog

The first release is **v0.2.0**. Per-release notes live in [CHANGELOG.md](CHANGELOG.md);
recent highlights are summarized under [What's New](#whats-new).

---

## Contributing

Contributions welcome. Please open an issue to discuss before submitting PRs for new features.

## License

MIT
