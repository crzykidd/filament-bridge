# filament-bridge

![version](https://img.shields.io/badge/version-0.1.0-blue)

Bidirectional sync between [Filament DB](https://github.com/hyiger/filament-db) and [Spoolman](https://github.com/Donkie/Spoolman) for 3D printing filament management.

> ## ⚠️ ALPHA — back up your databases before any writes
>
> filament-bridge is **alpha** software that writes to both **Spoolman** and **Filament DB**.
> **Before** running the Bulk Import Wizard, applying an OpenTag cleanup, or enabling
> auto-sync, **back up all three databases** (Spoolman, Filament DB, and the bridge). See
> [Backups](#backups). Test against non-critical data first.

---

## Why?

Filament DB and Spoolman are both excellent tools that solve different parts of the filament management problem:

- **Filament DB** excels at material profile management — deep slicer integration (PrusaSlicer, OrcaSlicer, Bambu Studio), per-printer/nozzle calibration storage, material science properties, NFC tag support, and AI-powered data sheet import.
- **Spoolman** excels at print-side inventory tracking — native OctoPrint and Moonraker/Klipper integration, real-time spool weight decrement during prints, Home Assistant integration, and broad ecosystem support.

Neither can do what the other does well. filament-bridge keeps them in sync so you can use both without manual data entry.

---

## Backups

**Before running the Bulk Import Wizard, applying an OpenTag cleanup, or enabling auto-sync, back up all three systems.** The bridge keeps auto-sync OFF by default and never deletes upstream records without explicit user action — but during alpha a backup is still the safe move.

### Spoolman

Trigger a safe server-side backup via the API (Spoolman does not need to be stopped; it copies its database into a `backups/` folder inside its own data volume):

```bash
curl -X POST http://<spoolman-host>:7912/api/v1/backup
```

Make sure Spoolman's data volume is itself persisted/copied — the backup file lands inside that volume. Docs: <https://donkie.github.io/Spoolman/#operation/backup_backup_post>

### Filament DB

Filament DB exposes `GET /api/snapshot` — a full JSON backup of all collections (filaments, spools, locations, print history, catalogs, tombstones). Restore with `POST /api/snapshot` (destructive).

**One-click via the bridge:** the pre-write safety dialog has a "Back up Filament DB now" button that calls the bridge's `POST /api/backup/filamentdb` endpoint, which downloads the snapshot and saves it to the bridge's data volume (`DATA_DIR/backups/filamentdb-snapshot-<timestamp>.json`).

**Curl:**

```bash
curl http://<fdb-host>:3000/api/snapshot -o fdb-snapshot.json
```

**Secondary option — raw MongoDB backup:**

```bash
docker exec <mongo-container> mongodump --archive=/data/db/fdb-$(date +%F).archive
```

Or snapshot the Mongo volume / use your MongoDB host's native backup tooling.

### filament-bridge

Export the bridge's own state (mappings, snapshots, conflict queue):

```bash
curl http://<bridge-host>:8090/api/backup/export -o bridge-backup.json
```

Restore with `POST /api/backup/import`.

---

## What it does

- **Bidirectional sync engine** — spool weights, material properties, and inventory changes flow between Filament DB and Spoolman on a configurable interval
- **Bulk Import Wizard** — re-runnable multi-step wizard with fuzzy vendor+name+color matching, group-by/sort/filter review, bulk actions, decision persistence, and a Rescan action; run it any time to import new filaments; optionally skip creating empty spool records via the "Never import empties" setting
- **Usage-logged weight sync** — Spoolman weight decrements are logged as Filament DB usage entries (preserving the audit trail), not raw weight overwrites; net↔gross weight-model translation is automatic
- **Per-category sync direction + conflict policy** — each data category (weight, material properties, new spools) has an independently configurable sync direction and conflict policy; `newest_wins` is available for weight only
- **Field and cost mapping** — Spoolman extra fields map to Filament DB's richer property set (density, temperatures, TDS URL, cost, etc.) by name match or explicit configuration
- **Spoolman→FDB variant grouping** — understands Filament DB's parent/variant model; groups flat Spoolman filaments into parent+color-variant hierarchies during the wizard
- **Structured multicolor/gradient sync** — bidirectional sync of FDB multi-color and gradient fields, version-gated to Filament DB ≥ 1.33.0
- **Material-finish tag round-trip** — OpenPrintTag finish tags (matte, silk, satin, etc.) sync as a Spoolman extra field (`filamentdb_material_tags`) and back
- **Conflict queue** — collapsible, sortable rows; when both sides change the same field between sync cycles the change is queued for manual resolution (conflicts are never silently auto-resolved); Synced Records rows link directly to the relevant conflict
- **Upstream-deletion detection** — detects records deleted in either system and queues them for explicit user action
- **OpenTag (OpenPrintTag) cleanup tool** — matches your Spoolman filaments against the OpenPrintTag database, lets you review candidates, apply to Spoolman, and stamp the OpenPrintTag `slug`/`uuid` into Filament DB
- **Pre-write backup safeguard** — a backup dialog *gates* the three write actions (Bulk Import Wizard Execute, OpenTag Apply, Enable auto-sync); back up Spoolman and/or Filament DB in one click before proceeding
- **Scheduler & Logs** — sync interval is runtime-editable in Settings (no restart needed; env var sets the default); sync-log page has window views (last 10 or 25 cycles) and a clear-log action; configurable log-retention period
- **Debug mode** — a Settings toggle (off by default) that reveals a Danger Zone with reset tools: clear Spoolman FDB cross-references and reset bridge local state; all `/api/debug/*` endpoints return 403 when debug mode is off
- **Runtime Settings** — sync direction, conflict policy, scheduler interval, log retention, variant keywords, vendor aliases, and more are editable in the Settings UI without restarting the service; timestamps throughout the UI are rendered in the browser's local timezone

---

## Screenshots

<!-- TODO: add screenshots once the UI is stable -->
<!-- Suggested: Dashboard overview, Wizard step 3 (match review), Conflicts queue, OpenTag Cleanup tool, Settings page -->

---

## Safety model — what the bridge will never do

- **Auto-sync is OFF by default** — you must explicitly enable it after completing the wizard and reviewing the dry-run plan
- **Conflicts are never auto-resolved** — every conflict is queued for manual human decision; no silent value-picking
- **Records are never deleted** from either upstream system without explicit user action in the bridge UI
- **Weight decrements are logged as usage entries** in Filament DB (via `POST /api/filaments/:id/spools/:spoolId/usage`), preserving the full usage-history audit trail
- **No upstream code modification** — the bridge uses only the documented REST APIs and Spoolman's extra field system; neither Filament DB nor Spoolman is forked or patched

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

Both Filament DB and Spoolman continue to function independently. filament-bridge is the glue that keeps them in sync. If the bridge goes down, both systems keep working — you just lose sync until it's back up.

OctoPrint, Moonraker, and Klipper talk to **Spoolman** directly; the bridge is not in that data path.

---

## Quick start (Docker)

[`docker-compose.yml`](docker-compose.yml) is the standard bridge-only deployment — it pulls the published image and points at your existing Filament DB and Spoolman instances. Copy it, fill in your URLs, and run:

```bash
docker compose up -d
```

For a full local stack (bridge + Filament DB + MongoDB + Spoolman) for development or testing, use [`docker-compose.dev.yml`](docker-compose.dev.yml) instead:

```bash
docker compose -f docker-compose.dev.yml up -d --build
```

To add the bridge to an existing compose file:

```yaml
services:
  filament-bridge:
    image: ghcr.io/hyiger/filament-bridge:latest
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

---

## Permissions

The container starts as root, automatically `chown`s `/data` to the runtime user, then drops privileges to **uid 1000 / gid 1000** (user `app`) via `gosu`. No manual `chown` is ever needed — pre-existing root-owned volumes are corrected automatically on start.

Override the runtime uid/gid with `PUID` / `PGID` environment variables if your host uses a different uid:

```yaml
environment:
  PUID: "1001"
  PGID: "1001"
```

- **Named volume** (the default — `bridge-data:/data`): nothing extra required; the entrypoint fixes ownership on every start.
- **Bind mount** (e.g. `./data:/data`): ownership is also corrected automatically — no pre-chown needed.
- **Upgrading from a root-owned volume** (prior versions set `user: "1000:1000"` in compose and required a manual chown): the entrypoint handles this automatically — no one-time chown step is needed.

---

## Prerequisites

**Minimum supported versions:**

| System | Minimum | Why |
|---|---|---|
| **Filament DB** | **1.33.0** | structured multicolor/gradient, finish-tag, and temperature sync (these features are skipped below it) |
| **Spoolman** | **0.22.0** | structured multi-color fields (`multi_color_hexes` / `multi_color_direction`) and the stable extra-fields system used for cross-reference IDs |

The bridge still starts and runs core weight/field sync against older versions, but `GET /api/health`
(and the Dashboard) will show a warning per system that is below its minimum. Filament DB ≥ **1.36.1**
is recommended (latest tested).

- **Filament DB** — the bridge gates version-specific features automatically.
- **Spoolman** — the bridge creates its required extra fields (`filamentdb_id`, `filamentdb_spool_id`, etc.) automatically on startup if they are missing.
- Both APIs are unauthenticated; no API keys or tokens are needed.

---

## Bulk Import Wizard

Navigate to `http://localhost:8090` after starting the container. The Bulk Import Wizard walks you through pairing records between the two systems. It can be re-run at any time — for example to import a batch of new filaments added to Spoolman after the initial setup.

1. **Connectivity check** — verifies the bridge can reach both upstream APIs
2. **Import direction** — choose whether the import comes from Filament DB or from Spoolman
3. **Match review** — the bridge reads both databases, fuzzy-matches records by vendor + name + color, and shows matched pairs, ambiguous matches, and unmatched records; group, sort, filter, and bulk-resolve as needed
4. **Variant grouping** — for Spoolman→FDB imports, assign color variants to parent filaments
5. **Variances** — review field differences and pick which value wins per field
6. **Dry-run preview** — see every write the execute step will perform (created, updated, conflicts, skipped)
7. **Execute** — gated behind the pre-write backup dialog; writes cross-reference IDs to both systems

After the wizard, review the Settings page to configure per-category sync direction and conflict policy, then explicitly enable auto-sync. The **Never import empties** setting (Settings → Scheduler & Logs) controls whether depleted spools (net weight = 0) are skipped during wizard imports; the filament definition is always imported regardless.

---

## Configuration

All configuration is via environment variables. The service will not start if `FILAMENTDB_URL` or `SPOOLMAN_URL` are missing.

| Variable | Required | Default | Description |
|---|---|---|---|
| `FILAMENTDB_URL` | **Yes** | — | Base URL of your Filament DB instance (e.g. `http://filament-db:3000`) |
| `SPOOLMAN_URL` | **Yes** | — | Base URL of your Spoolman instance (e.g. `http://spoolman:7912`) |
| `SYNC_INTERVAL_SECONDS` | No | `120` | Seconds between auto-sync cycles (when enabled) |
| `DATA_DIR` | No | `/data` | Directory for the SQLite state database and backup files |
| `FILAMENTDB_SPOOLMAN_ID_FIELD` | No | `label` | Filament DB spool field used to store the Spoolman spool ID |
| `SPOOLMAN_FIELD_FILAMENTDB_ID` | No | `filamentdb_id` | Spoolman extra field name for the Filament DB filament ID |
| `SPOOLMAN_FIELD_FILAMENTDB_PARENT_ID` | No | `filamentdb_parent_id` | Spoolman extra field for the FDB parent filament ID (variant tracking) |
| `SPOOLMAN_FIELD_FILAMENTDB_SPOOL_ID` | No | `filamentdb_spool_id` | Spoolman extra field for the FDB spool subdocument ID |
| `SPOOLMAN_FIELD_FILAMENTDB_MATERIAL_TAGS` | No | `filamentdb_material_tags` | Spoolman extra field storing finish-tag IDs (CSV of ints) |
| `FIELD_MAPPINGS` | No | — | Comma-separated `fdb_field=spoolman_field` pairs for explicit field mapping |
| `FIELD_MAPPING_EXCLUDES` | No | — | Comma-separated field names to exclude from auto-matching |
| `VARIANT_LINE_KEYWORDS` | No | `silk,matte,satin,...` | Keywords that separate variant lines (filaments matching different keywords won't be grouped) |
| `MATERIAL_TAG_IDS` | No | (seed list) | CSV of `keyword=id` pairs overriding the default finish-tag ID map |
| `OPENTAG_VENDOR_ALIASES` | No | — | CSV of `spoolman_vendor=opentag_brand` pairs for OpenTag brand matching |
| `SPOOLMAN_FIELD_OPENPRINTTAG_SLUG` | No | `openprinttag_slug` | Spoolman extra field for the OpenPrintTag slug |
| `SPOOLMAN_FIELD_OPENPRINTTAG_UUID` | No | `openprinttag_uuid` | Spoolman extra field for the OpenPrintTag UUID |
| `OPENTAG_CACHE_MAX_AGE_HOURS` | No | `24` | Hours before the local OpenPrintTag dataset cache is considered stale |
| `DISCORD_WEBHOOK_URL` | No | — | Discord webhook URL for conflict/error notifications (env var; notification delivery not yet implemented) |
| `LOG_LEVEL` | No | `info` | Logging level (`debug`, `info`, `warn`, `error`) |

See **[docs/configuration.md](docs/configuration.md)** for the complete reference, including the runtime-editable settings (sync direction, conflict policy, variant keywords, vendor aliases) and the two-axis sync model.

---

## How sync works

### Per-category direction and conflict policy

Each data category has two independently configurable axes:

- **Sync direction** — `filamentdb_to_spoolman`, `spoolman_to_filamentdb`, or `two_way`
- **Conflict policy** — `manual` (queue for human decision) or `newest_wins` (weight only)

Defaults: weight syncs Spoolman→FDB; material properties sync FDB→Spoolman; new spools sync two-way.

### Weight model translation

Spoolman tracks **net filament weight** (`remaining_weight` excludes the reel). Filament DB tracks **gross spool weight** (`totalWeight` includes the reel; the filament-level `spoolWeight` field is the empty reel tare).

- Spoolman → Filament DB: the weight decrement is sent as a usage log entry (`POST /api/filaments/:id/spools/:spoolId/usage`) — never as a raw weight overwrite
- Filament DB → Spoolman: `remaining_weight = totalWeight - spoolWeight`

### Variant tracking

Filament DB uses parent/variant inheritance (one parent with shared settings, color variants underneath). Spoolman has a flat one-filament-per-color model. The bridge tracks the relationship via Spoolman extra fields: `filamentdb_id` (direct link to the FDB color variant) and `filamentdb_parent_id` (link to the FDB parent).

### Conflict resolution

A conflict occurs when the same field changes on both sides between sync cycles. All conflicts are queued — never silently resolved — and displayed in the Conflicts page with both values, timestamps, and a button to pick either side or enter a manual value.

---

## OpenTag cleanup tool

The OpenTag tool matches your Spoolman filaments against the [OpenPrintTag](https://openprinttag.org) database, which provides standardized filament identification (slugs, UUIDs, finish tags).

1. Navigate to the OpenTag page in the bridge UI
2. The bridge fetches the OpenPrintTag dataset (cached locally for 24 h by default) and scores each Spoolman filament against it — brand pre-filter, color matching, finish-aware scoring
3. Review candidates: each filament shows the best match and up to 5 alternates; accept, switch, or ignore per filament
4. Optionally assign or create Spoolman vendors; review the Manufacturer field per filament
5. Confirm — the bridge writes the `openprinttag_slug` and `openprinttag_uuid` extra fields to Spoolman, and stamps the same identity keys into the Filament DB `settings{}` bag

API routes are at `/api/openprinttag/*` (renamed from `/opentag/*` to avoid ad-blocker interference).

Vendor name discrepancies between Spoolman and OpenPrintTag can be bridged with the `OPENTAG_VENDOR_ALIASES` env var (also runtime-editable in Settings).

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

No release has been cut yet. Notable changes are tracked in [CHANGELOG.md](CHANGELOG.md)
under `[Unreleased]`; per-release entries will appear here starting with v0.1.0.

---

## Contributing

Contributions welcome. Please open an issue to discuss before submitting PRs for new features.

## License

MIT
