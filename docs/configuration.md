# filament-bridge — Configuration Reference

Configuration lives in two layers:

1. **Environment variables** — connection settings and startup defaults. The service will
   not start if `FILAMENTDB_URL` or `SPOOLMAN_URL` are missing.
2. **Runtime settings (BridgeConfig)** — behavior settings editable in the Settings UI and
   stored in the SQLite state database. Where a setting exists in both layers, the runtime
   value overrides the env var; the env var only sets the initial default.

---

## Core / Connection

| Variable | Required | Default | Description |
|---|---|---|---|
| `FILAMENTDB_URL` | **Yes** | — | Base URL of your Filament DB instance. Trailing slash is stripped automatically. Example: `http://filament-db:3000` |
| `SPOOLMAN_URL` | **Yes** | — | Base URL of your Spoolman instance. Example: `http://spoolman:7912` |
| `DATA_DIR` | No | `/data` | Directory for the SQLite state database (`bridge.db`), the OpenTag dataset cache, and backup files. Mount a persistent volume at this path. |

## Authentication

| Variable | Required | Default | Description |
|---|---|---|---|
| `AUTH_ENABLED` | No | `true` | When `false`, authentication is fully bypassed (open app). Also the lockout-recovery path: disable → restart → change password in Settings → re-enable. See [security.md](security.md). |

## Permissions

The container starts as root, automatically `chown`s `/data` to the runtime user, then drops
privileges via `gosu`. No manual `chown` is ever needed — pre-existing root-owned volumes
(named or bind-mounted) are corrected automatically on every start.

| Variable | Default | Description |
|---|---|---|
| `PUID` | `1000` | User ID the app process runs as after the entrypoint drops privileges. |
| `PGID` | `1000` | Group ID the app process runs as after the entrypoint drops privileges. |

## Sync behavior

| Variable | Required | Default | Description |
|---|---|---|---|
| `SYNC_INTERVAL_SECONDS` | No | `120` | Default seconds between auto-sync cycles. Runtime-editable in Settings → Scheduler & Logs (no restart needed; backend clamps to ≥ 30 s). Auto-sync itself is OFF by default and must be enabled explicitly after the wizard. |

### Two-axis sync model

Each data category is configured independently on two axes (Settings → Weight sync /
Material properties sync / New spools):

- **Sync direction** — which side may write to the other:
  - `filamentdb_to_spoolman` — Filament DB is authoritative; changes flow to Spoolman only
  - `spoolman_to_filamentdb` — Spoolman is authoritative; changes flow to Filament DB only
  - `two_way` — changes on either side are applied to the other
- **Conflict policy** — what happens when the same field changes on both sides between
  cycles (consulted only under `two_way`):
  - `manual` — queue in the conflict queue for human decision (default for all categories)
  - `spoolman_wins` / `filamentdb_wins` — that side's value is pushed automatically
  - `newest_wins` — most-recently-modified value wins (**weight only** — Spoolman exposes
    no per-filament modification timestamp, so it is rejected for material properties).
    Timestamps are anchored to the last sync time so a stale clock can't win; if the
    winner is indeterminate, the conflict falls back to `manual`.

Defaults: weight syncs `spoolman_to_filamentdb`; material properties sync
`filamentdb_to_spoolman`; new-spool creation is `two_way` (direction only — there is no
conflict policy for creation).

Under a one-way direction, drift on the locked side is ignored (NOOP), not reverted.

## Cross-reference fields

These control which fields the bridge uses to store cross-reference IDs. Change them only
if the default names are already taken in your instance. The bridge creates missing Spoolman
extra fields automatically on startup.

| Variable | Required | Default | Description |
|---|---|---|---|
| `FILAMENTDB_SPOOLMAN_ID_FIELD` | No | `label` | Filament DB spool field used to store the Spoolman spool ID. The `label` field is visible in Filament DB's spool list. |
| `SPOOLMAN_FIELD_FILAMENTDB_ID` | No | `filamentdb_id` | Spoolman spool extra field storing the Filament DB filament ID (MongoDB ObjectId). |
| `SPOOLMAN_FIELD_FILAMENTDB_PARENT_ID` | No | `filamentdb_parent_id` | Spoolman spool extra field storing the Filament DB parent filament ID (variant tracking). |
| `SPOOLMAN_FIELD_FILAMENTDB_SPOOL_ID` | No | `filamentdb_spool_id` | Spoolman spool extra field storing the Filament DB spool subdocument `_id`. |
| `SPOOLMAN_FIELD_FILAMENTDB_MATERIAL_TAGS` | No | `filamentdb_material_tags` | Spoolman **filament** extra field storing OpenPrintTag finish-tag IDs as a CSV string of integers (e.g. `16,17`). |

## Field mapping

| Variable | Required | Default | Description |
|---|---|---|---|
| `FIELD_MAPPINGS` | No | — | Explicit field-mapping overrides. Comma-separated `fdb_field=spoolman_extra_field` pairs (dotted FDB paths allowed, e.g. `temperatures.nozzle=nozzle_temp`). Supplements the auto-matched fields. |
| `FIELD_MAPPING_EXCLUDES` | No | — | Comma-separated field names excluded from auto-matching entirely. |

Auto-matching links any Spoolman *extra* field whose key exactly equals a syncable Filament
DB field name. Native shared fields (material, density, diameter, weights, temperatures,
cost, color) are synced by dedicated passes and need no mapping — see
[sync-model.md](sync-model.md).

## Variant grouping / wizard

| Variable | Required | Default | Description |
|---|---|---|---|
| `VARIANT_LINE_KEYWORDS` | No | `silk,matte,satin,carbon,cf,glow,wood,marble,metal,metallic,high-speed,hs,dual,tri,rainbow,multicolor,rapid` | Keywords that identify distinct variant lines. Filaments whose names match *different* keywords are never grouped together (a "Silk PLA" and a "Matte PLA" stay separate). **Runtime-editable.** |
| `CONTAINER_PARENT_MARKER` | No | `(Master)` | String appended (after a space) to generic-container parent names, e.g. "ELEGOO PLA (Master)". Empty string = no suffix. **Runtime-editable** (shown in Settings when `generic_container` mode is selected). Changing it does not rename existing containers. |

## Material tags + OpenTag (OpenPrintTag)

| Variable | Required | Default | Description |
|---|---|---|---|
| `MATERIAL_TAG_IDS` | No | (seed list) | Override the default finish-keyword→OpenPrintTag-ID map. CSV of `keyword=id` pairs (e.g. `silk=17,matte=16`). Empty uses the built-in seed list from `core/material_tags.py`. |
| `OPENTAG_VENDOR_ALIASES` | No | — | Map Spoolman vendor names to OpenPrintTag brand names for the matcher's brand pre-filter. CSV of `spoolman_vendor=opentag_brand` pairs (e.g. `prusa=prusament`). Case-insensitive. **Runtime-editable**; new installs seed `prusa=prusament, polyterra=polymaker`. |
| `OPENTAG_COLOR_KEYWORDS` | No | — | Map color/marketing words to canonical base colors for the matcher (e.g. `galaxy=black,cool=grey`). Merged on top of the built-in seed map. **Runtime-editable**; new installs seed `galaxy=black, cool=grey, jet=black`. |
| `SPOOLMAN_FIELD_OPENPRINTTAG_SLUG` | No | `openprinttag_slug` | Spoolman filament extra field for the OpenPrintTag slug. |
| `SPOOLMAN_FIELD_OPENPRINTTAG_UUID` | No | `openprinttag_uuid` | Spoolman filament extra field for the OpenPrintTag UUID. |
| `OPENTAG_CACHE_MAX_AGE_HOURS` | No | `24` | Hours before the locally cached OpenPrintTag dataset is considered stale and re-fetched. |

## Build / logging / misc

| Variable | Required | Default | Description |
|---|---|---|---|
| `BRIDGE_CHANNEL` | No | `release` | Build channel baked in at image build time (`BUILD_CHANNEL` build arg). `dev` builds show a `-dev` version suffix and suppress the update nag. |
| `BRIDGE_COMMIT` | No | — | Short git SHA baked in at image build time (`GIT_COMMIT` build arg); shown in the dev version label. |
| `LOG_LEVEL` | No | `info` | Logging verbosity: `debug`, `info`, `warn`, `error`. JSON logs go to stdout; rotation is your Docker logging driver's job. |
| `DISCORD_WEBHOOK_URL` | No | — | Declared for future conflict/error notifications; delivery is not yet implemented. |
| `DEBUG_STARTUP_DUMP` | No | `false` | When `true`, writes a human-readable snapshot of both upstream systems at boot to `{DATA_DIR}/state-dumps/startup-state-<UTC ts>.txt`. Runs as a background task (never delays startup) and retries the upstream fetch for ~2 minutes, so the file appears once Spoolman and Filament DB finish booting alongside the bridge. The newest 10 dump files are kept; older ones are pruned automatically. **Never enable in production.** |
| `CHANGES_LOG_ENABLED` | No | `true` | When `false` / `0` / `no`, disables the durable per-write audit file. Applies without restart. |
| `CHANGES_LOG_PATH` | No | `{DATA_DIR}/changes.log` | Override the path for the changes.log file. Useful when `DATA_DIR` is already mounted as read-only or you want the log on a separate volume. |

---

## Runtime-editable settings (Settings UI)

Stored in SQLite (`BridgeConfig`); changes take effect without a restart.

| Setting | Default | Where | Description |
|---|---|---|---|
| Auto-sync enabled | `false` | Scheduler & Logs | Master switch for scheduled sync. Enabling requires a completed wizard and is gated behind the backup dialog. |
| `sync_interval_seconds` | env (`120`) | Scheduler & Logs | Auto-sync interval; rescheduled immediately on save (min 30 s). |
| `sync_log_retention_days` | `30` | Scheduler & Logs | Sync-log rows older than this are pruned at the start of each auto-sync tick. `0` = keep forever. |
| Weight / material-properties / new-spool direction + policy | see above | category cards | The two-axis model. |
| `sync_weight_threshold_grams` | `2.0` | Other settings | Weight changes smaller than this are ignored (suppresses net/gross rounding churn). |
| `weight_precision_decimals` | `2` | Other settings | Decimal places used when comparing/writing weights. |
| `variant_line_keywords` | env seed | Other settings | See `VARIANT_LINE_KEYWORDS`. |
| `opentag_vendor_aliases` | env / seed | Other settings | See `OPENTAG_VENDOR_ALIASES`. |
| `opentag_color_keywords` | env / seed | Other settings | See `OPENTAG_COLOR_KEYWORDS`. |
| `new_filament_policy` | `manual_review` | New records | What the engine does when it detects an unmapped filament: `manual_review` queues a `new_filament` conflict (actionable — the Conflicts page "Add" button imports it); `auto_import` creates the filament automatically and writes the cross-reference. Defaults to `manual_review` for both fresh and existing installs. When `variant_parent_mode` is `unset` and the filament looks like a variant-cluster member, auto-import falls back to `manual_review` regardless of this setting (can't group variants without a mode). |
| `new_spool_policy` | `manual_review` | New records | What the engine does when an unmapped spool appears whose filament **is already mapped**: `manual_review` queues a `new_spool` conflict; `auto_import` creates the spool immediately. A spool is always held when its filament is unmapped, regardless of this setting — the filament tier must resolve first. |
| `never_import_empties` | `false` | New spools | Controls both empty and archived spools. When `false` (default): all spools import, including depleted (`remaining ≤ 0`) and archived ones. Archived spools import as **retired** FDB spools (spool only — the filament stays live). When `true`: spools with `remaining ≤ 0` are skipped (whether active or archived); archived spools with positive remaining weight still import as retired. The filament definition always imports regardless. |
| `variant_parent_mode` | `unset` | Variant parent mode | **Required before the wizard runs** (Spoolman→FDB direction): `promote_color` or `generic_container`. See [variant-parent-mode.md](variant-parent-mode.md). |
| `container_parent_marker` | env (`(Master)`) | Variant parent mode | Marker on generic-container names; checkbox + text field, visible in `generic_container` mode. |
| `api_token_enabled` | `false` | Security | Allow `Authorization: Bearer` / `X-API-Key` machine auth. |
| `api_token` | (none) | Security | The token value; generate/regenerate in Settings (displayed masked). |
| `debug_mode` | `false` | Debug mode | Reveals the Danger Zone and enables the three `/api/debug/*` reset endpoints (403 when off). Never enable in production. |

The wizard also persists its own decision state in BridgeConfig
(`import_direction`, `wizard_match_decisions`, `wizard_sm_variant_decisions`,
`wizard_variances_reconcile`, `wizard_container_name_overrides`, `wizard_completed`) —
these are managed by the wizard UI, not edited directly.

---

## Example `.env` for local development

```env
FILAMENTDB_URL=http://localhost:3000
SPOOLMAN_URL=http://localhost:7912
DATA_DIR=/tmp/bridge-dev
LOG_LEVEL=debug
SYNC_INTERVAL_SECONDS=30
AUTH_ENABLED=false
VARIANT_LINE_KEYWORDS=silk,matte,satin,carbon,glow,wood,marble,rapid
```
