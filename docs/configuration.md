# filament-bridge — Configuration Reference

All configuration is via environment variables. The service will not start if `FILAMENTDB_URL`
or `SPOOLMAN_URL` are missing.

Some settings are **also runtime-editable** in the Settings UI (sync direction, conflict policy,
variant keywords, vendor aliases). The runtime value overrides the env var for the lifetime of
that bridge instance, and is stored in the SQLite state database. The env var still sets the
initial default used before any runtime edit has been made.

---

## Permissions

The container process runs as **uid 1000 / gid 1000** (user `app`). The `/data` directory is
pre-owned by 1000:1000 in the image.

- **Named volume** (default — `bridge-data:/data`): nothing extra required; Docker inherits the
  image ownership on first creation.
- **Bind mount** (e.g. `./data:/data`): the host directory must be owned by 1000:1000:
  ```bash
  chown -R 1000:1000 ./data
  ```
- **Upgrading from a root-owned volume** (pre-1000:1000 image): run a one-time chown or
  recreate the volume:
  ```bash
  docker run --rm -v bridge-data:/data busybox chown -R 1000:1000 /data
  ```

---

## Core / Connection

| Variable | Required | Default | Description |
|---|---|---|---|
| `FILAMENTDB_URL` | **Yes** | — | Base URL of your Filament DB instance. Trailing slash is stripped automatically. Example: `http://filament-db:3000` |
| `SPOOLMAN_URL` | **Yes** | — | Base URL of your Spoolman instance. Example: `http://spoolman:7912` |
| `DATA_DIR` | No | `/data` | Directory for the SQLite state database (`bridge.db`) and backup files. Mount a persistent volume at this path. |

---

## Sync behavior

| Variable | Required | Default | Description |
|---|---|---|---|
| `SYNC_INTERVAL_SECONDS` | No | `120` | Seconds between auto-sync cycles when auto-sync is enabled. Auto-sync is OFF by default; enable it explicitly in the Settings UI after completing the wizard. |

### Two-axis sync model

Each data category is configured independently on two axes:

- **Sync direction** — which side can write to the other:
  - `filamentdb_to_spoolman` — Filament DB is authoritative; changes flow to Spoolman only
  - `spoolman_to_filamentdb` — Spoolman is authoritative; changes flow to Filament DB only
  - `two_way` — changes on either side are applied to the other

- **Conflict policy** — what happens when the same field changes on both sides between sync cycles:
  - `manual` — the change is queued in the conflict queue for human decision (default for all categories)
  - `newest_wins` — the most-recently-modified value wins automatically (**weight only** — Spoolman exposes no per-filament modification timestamp, so `newest_wins` is not available for material properties)

Default directions: weight syncs `spoolman_to_filamentdb`; material properties sync
`filamentdb_to_spoolman`; new spools are `two_way`.

All three direction/policy pairs are **runtime-editable** in the Settings UI.

---

## Cross-reference fields

These control which Spoolman extra fields the bridge uses to store cross-reference IDs. Change
only if those field names are already taken in your Spoolman instance.

The bridge creates any missing extra fields automatically on startup.

| Variable | Required | Default | Description |
|---|---|---|---|
| `FILAMENTDB_SPOOLMAN_ID_FIELD` | No | `label` | Filament DB spool field used to store the Spoolman spool ID. The `label` field is visible in Filament DB's spool list. |
| `SPOOLMAN_FIELD_FILAMENTDB_ID` | No | `filamentdb_id` | Spoolman filament extra field storing the Filament DB filament ID (MongoDB ObjectId). |
| `SPOOLMAN_FIELD_FILAMENTDB_PARENT_ID` | No | `filamentdb_parent_id` | Spoolman filament extra field storing the Filament DB parent filament ID (for variant tracking). |
| `SPOOLMAN_FIELD_FILAMENTDB_SPOOL_ID` | No | `filamentdb_spool_id` | Spoolman spool extra field storing the Filament DB spool subdocument `_id`. |
| `SPOOLMAN_FIELD_FILAMENTDB_MATERIAL_TAGS` | No | `filamentdb_material_tags` | Spoolman filament extra field storing OpenPrintTag finish-tag IDs as a CSV string of integers (e.g. `12,47`). |

---

## Field mapping

| Variable | Required | Default | Description |
|---|---|---|---|
| `FIELD_MAPPINGS` | No | — | Explicit field mapping overrides. Comma-separated `fdb_field=spoolman_field` pairs. Example: `density=density,printTemp=nozzle_temperature`. When set, these pairs supplement the auto-matched fields. |
| `FIELD_MAPPING_EXCLUDES` | No | — | Comma-separated field names to exclude from auto-matching entirely. Useful if a field auto-matches incorrectly. |

---

## Variant grouping

| Variable | Required | Default | Description |
|---|---|---|---|
| `VARIANT_LINE_KEYWORDS` | No | `silk,matte,satin,carbon,cf,glow,wood,marble,metal,metallic,high-speed,hs,dual,tri,rainbow,multicolor,rapid` | Comma-separated keywords that identify distinct variant lines. If two filaments' names match different keywords from this list, they are placed in separate variant groups rather than being grouped together. Example: a "Silk PLA" and a "Matte PLA" would not be grouped even though both are PLA. **Runtime-editable** in the Settings UI. |

---

## Material tags + OpenTag (OpenPrintTag)

| Variable | Required | Default | Description |
|---|---|---|---|
| `MATERIAL_TAG_IDS` | No | (seed list) | Override the default finish-keyword→OpenPrintTag-ID map. CSV of `keyword=id` pairs (e.g. `silk=12,matte=47`). Empty string uses the built-in seed list from `core/material_tags.py`. |
| `OPENTAG_VENDOR_ALIASES` | No | — | Map Spoolman vendor names to OpenPrintTag brand names for the brand pre-filter. CSV of `spoolman_vendor=opentag_brand` pairs (e.g. `prusa=prusament,esun=eSUN`). Matching is case-insensitive. **Runtime-editable** in the Settings UI. |
| `SPOOLMAN_FIELD_OPENPRINTTAG_SLUG` | No | `openprinttag_slug` | Spoolman filament extra field for the OpenPrintTag slug. |
| `SPOOLMAN_FIELD_OPENPRINTTAG_UUID` | No | `openprinttag_uuid` | Spoolman filament extra field for the OpenPrintTag UUID. |
| `OPENTAG_CACHE_MAX_AGE_HOURS` | No | `24` | Hours before the locally cached OpenPrintTag dataset tarball is considered stale and re-fetched. |

---

## Logging / Data

| Variable | Required | Default | Description |
|---|---|---|---|
| `LOG_LEVEL` | No | `info` | Logging verbosity: `debug`, `info`, `warn`, `error`. |
| `DISCORD_WEBHOOK_URL` | No | — | Discord webhook URL for conflict and error notifications. The env var is parsed and stored; notification delivery is not yet implemented. |

---

## Runtime-editable settings (Settings UI)

The following settings can be changed in the bridge Settings page without restarting the
container. The runtime value is persisted in SQLite and overrides the env var default.

| Setting | Env var equivalent | Notes |
|---|---|---|
| Weight sync direction | (two-axis model) | `spoolman_to_filamentdb` / `filamentdb_to_spoolman` / `two_way` |
| Weight conflict policy | (two-axis model) | `manual` or `newest_wins` |
| Material properties sync direction | (two-axis model) | |
| Material properties conflict policy | (two-axis model) | `manual` only — `newest_wins` not supported (no SM filament mtime) |
| New-spool sync direction | (two-axis model) | |
| Variant line keywords | `VARIANT_LINE_KEYWORDS` | Comma-separated; changes take effect on the next wizard run or sync cycle |
| OpenTag vendor aliases | `OPENTAG_VENDOR_ALIASES` | Comma-separated `sm_vendor=opentag_brand` pairs |
| Sync weight threshold (grams) | — | Weight changes smaller than this are ignored (reduces noise from rounding) |
| Weight precision (decimal places) | — | Number of decimal places used when comparing/writing weights |

---

## Example `.env` for local development

```env
FILAMENTDB_URL=http://localhost:3000
SPOOLMAN_URL=http://localhost:7912
DATA_DIR=/tmp/bridge-dev
LOG_LEVEL=debug
SYNC_INTERVAL_SECONDS=30
VARIANT_LINE_KEYWORDS=silk,matte,satin,carbon,glow,wood,marble,rapid
```
