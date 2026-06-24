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
| `FILAMENTDB_API_KEY` | No | — | Bearer token for Filament DB's optional API-key auth (Filament DB ≥ 1.39.0, enabled by setting FDB's own `FILAMENTDB_API_KEY`). When set, the bridge sends `Authorization: Bearer <key>` on every Filament DB request. Leave empty unless you've turned on FDB's API key. Spoolman's API has no auth. |
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
| `SYNC_INTERVAL_SECONDS` | No | `120` | Default seconds between auto-sync cycles. Runtime-editable in Settings → Sync (no restart needed; backend clamps to ≥ 30 s). Auto-sync itself is OFF by default and must be enabled explicitly after the wizard. |
| `BACKUP_SCHEDULE_ENABLED` | No | `true` | Start-up fallback for the master switch of the nightly scheduled backup job. Runtime-editable in Settings → Scheduled backups (DB value wins). |
| `BACKUP_BRIDGE_STATE_ENABLED` | No | `true` | Include the bridge-state export in the nightly backup. Runtime-editable. |
| `BACKUP_FILAMENTDB_ENABLED` | No | `true` | Include the Filament DB snapshot in the nightly backup. Runtime-editable. Spoolman is intentionally excluded from the scheduled path (the bridge can't prune Spoolman's own volume). |
| `BACKUP_RETENTION_DAYS` | No | `7` | Delete bridge-written backups in `{DATA_DIR}/backups/` older than this. Only the `bridge-state-`/`filamentdb-snapshot-` prefixes are eligible. Runtime-editable; min 1. |
| `BACKUP_HOUR_UTC` | No | `3` | UTC hour (0–23) the nightly backup fires at, minute 0. Runtime-editable; the cron reschedules on save. See [backups.md](backups.md). |

### Two-axis sync model

Each data category is configured independently on two axes (Settings → Weight sync /
Material properties sync / Archive / retire sync / New spools):

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
`filamentdb_to_spoolman`; archive/retire syncs `two_way`; new-spool creation is `two_way`
(direction only — there is no conflict policy for creation).

Under a one-way direction, drift on the locked side is ignored (NOOP), not reverted.

The **archive / retire** category (`archive_sync_direction` / `archive_conflict_policy`)
mirrors a *mapped* spool's lifecycle state between Spoolman (`archived`) and Filament DB
(`retired`) — see [sync-model.md](sync-model.md) for the pass. Its state is a boolean, so
`newest_wins` is **rejected** (422) for `archive_conflict_policy` — there is no comparable
timestamp; use `manual` (default), `spoolman_wins`, or `filamentdb_wins`. A one-sided flip
is a clean push; only a both-sides-diverge-to-opposite-states case consults the policy.
This is independent of `never_import_empties` (below), which only governs *import*.

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
| `SPOOLMAN_FIELD_OPENPRINTTAG_SLUG` | No | `openprinttag_slug` | Spoolman filament extra field for the OpenPrintTag slug. |
| `SPOOLMAN_FIELD_OPENPRINTTAG_UUID` | No | `openprinttag_uuid` | Spoolman filament extra field for the OpenPrintTag UUID. |
| `SPOOLMAN_FIELD_OPENPRINTTAG_IGNORE` | No | `openprinttag_ignore` | Spoolman filament extra field storing the "ignore future updates" flag (`"1"` = ignored, `""` = not ignored). Written by the OpenTag Updates Review UI. |
| `SPOOLMAN_FIELD_OPENPRINTTAG_NOZZLE_TEMP_MIN` | No | `openprinttag_nozzle_temp_min` | Typed (**integer**) Spoolman filament extra for OPT `nozzleTempMin` (°C). Synced ↔ FDB `temperatures.nozzleRangeMin`. |
| `SPOOLMAN_FIELD_OPENPRINTTAG_NOZZLE_TEMP_MAX` | No | `openprinttag_nozzle_temp_max` | Typed (**integer**) Spoolman filament extra for OPT `nozzleTempMax` (°C). Synced ↔ FDB `temperatures.nozzleRangeMax`. |
| `SPOOLMAN_FIELD_OPENPRINTTAG_DRYING_TEMP` | No | `openprinttag_drying_temp` | Typed (**integer**) Spoolman filament extra for OPT `dryingTemp` (°C). Synced ↔ FDB `dryingTemperature`. |
| `SPOOLMAN_FIELD_OPENPRINTTAG_DRYING_TIME` | No | `openprinttag_drying_time` | Typed (**integer**) Spoolman filament extra for drying time in **minutes**. OpenPrintTag and Filament DB both store `dryingTime` in minutes (e.g. `480` = 8 h), so it passes through unchanged. Synced ↔ FDB `dryingTime` (minutes). |
| `SPOOLMAN_FIELD_OPENPRINTTAG_HARDNESS_SHORE_A` | No | `openprinttag_hardness_shore_a` | Typed (**float**) Spoolman filament extra for OPT `hardnessShoreA`. Synced ↔ FDB `shoreHardnessA`. |
| `SPOOLMAN_FIELD_OPENPRINTTAG_HARDNESS_SHORE_D` | No | `openprinttag_hardness_shore_d` | Typed (**float**) Spoolman filament extra for OPT `hardnessShoreD`. Synced ↔ FDB `shoreHardnessD`. |
| `SPOOLMAN_FIELD_OPENPRINTTAG_TRANSMISSION_DISTANCE` | No | `openprinttag_transmission_distance` | Typed (**float**) Spoolman filament extra for OPT `transmissionDistance` (mm). Synced ↔ FDB `transmissionDistance`. |
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

## Mobile updates & labels

The phone scan-and-update flow and LabelForge label printing. The whole feature is **off by
default**; while off, every mobile/label endpoint and the `/r/` redirect return 403. Env
vars are the start-up fallback — the matching runtime setting wins when set. See
[mobile-updates.md](mobile-updates.md).

| Variable | Required | Default | Description |
|---|---|---|---|
| `MOBILE_LABELS_ENABLED` | No | `false` | Master switch for the mobile-updates & labels feature. Start-up fallback; runtime-editable in Settings → Mobile & Labels (DB value wins). |
| `BRIDGE_PUBLIC_URL` | No | — | External base URL baked into the printed QR (`{base}/r/{fil}/{spool}`). Blank = derive from the request (honoring `X-Forwarded-Proto`/`X-Forwarded-Host` behind a proxy). Runtime-editable. |
| `MOBILE_REDIRECT_TARGET` | No | `bridge` | Where `GET /r/{fil}/{spool}` 302-redirects: `bridge` (the SPA scan page `/scan/{fil}/{spool}`) or `filamentdb` (`{FILAMENTDB_URL}/filaments/{fil}`). Runtime-editable. |
| `MOBILE_WEIGHT_DEFAULT_MODE` | No | `direct_correction` | Default weight-save mode on the update page: `direct_correction` (absolute true-up) or `usage` (log an FDB usage entry on a decrease). Overridable per save. Runtime-editable. |
| `LABELFORGE_URL` | No | — | Base URL of the LabelForge instance used for printing. Blank = not configured. Runtime-editable. |
| `LABELFORGE_TOKEN` | No | — | LabelForge bearer token (secret). Blank = no auth header. Runtime-editable. |
| `LABELFORGE_TEMPLATE` | No | — | Name of the user-created LabelForge template to print. Blank = not configured. Runtime-editable. |
| `LABELFORGE_FIELDS` | No | — | CSV of catalog field names to send to LabelForge (`brand`, `color`, `color_hex`, `number`, `material`, `qr_url`), e.g. `brand,color,number,qr_url`. Unknown names are skipped with a warning. Runtime-editable. |
| `LABELFORGE_LABEL_MEDIA` | No | — | Optional per-print media/size hint passed to LabelForge. Blank = the template's stored media. Runtime-editable. |

---

## Runtime-editable settings (Settings UI)

Stored in SQLite (`BridgeConfig`); changes take effect without a restart.

| Setting | Default | Where | Description |
|---|---|---|---|
| Auto-sync enabled | `false` | Sync | Master switch for scheduled sync. Enabling requires a completed wizard and shows a friendly backup prompt (optional — you can proceed immediately). |
| `sync_interval_seconds` | env (`120`) | Sync | Auto-sync interval; rescheduled immediately on save (min 30 s). |
| `sync_log_retention_days` | `30` | Sync | Sync-log rows older than this are pruned at the start of each auto-sync tick. `0` = keep forever. |
| `backup_schedule_enabled` | env (`true`) | Scheduled backups | Master switch for the nightly backup job. When off, the `nightly_backup` cron is a no-op. |
| `backup_bridge_state_enabled` | env (`true`) | Scheduled backups | Include the bridge-state export in the nightly backup (sub-toggle, greyed out when master off). |
| `backup_filamentdb_enabled` | env (`true`) | Scheduled backups | Include the Filament DB snapshot in the nightly backup (sub-toggle). Spoolman is intentionally excluded. |
| `backup_retention_days` | env (`7`) | Scheduled backups | Delete bridge-written backups in `{DATA_DIR}/backups/` older than this. Min 1. Only the bridge's own prefixes are eligible — Spoolman archives are never touched. |
| `backup_hour_utc` | env (`3`) | Scheduled backups | UTC hour (0–23) the nightly backup runs at, minute 0. Rescheduled immediately on save. See [backups.md](backups.md). |
| Weight / material-properties / archive-retire / new-record direction + policy | see above | Sync → category cards | The two-axis model. |
| `archive_sync_direction` | `two_way` | Sync → Archive / retire sync | Which side's archive/retire flip is mirrored: `two_way` (default), `spoolman_to_filamentdb`, or `filamentdb_to_spoolman`. Applies to mapped pairs only. |
| `archive_conflict_policy` | `manual` | Sync → Archive / retire sync | Consulted only under `two_way` when both sides diverge to opposite states: `manual` (default — queue a `cross_system` lifecycle conflict), `spoolman_wins`, or `filamentdb_wins`. `newest_wins` is **rejected** (422) — the state is a boolean with no timestamp. |
| `sync_weight_threshold_grams` | `2.0` | Sync → Weight sync | Weight changes smaller than this are ignored (suppresses net/gross rounding churn). |
| `weight_precision_decimals` | `2` | Sync → Weight sync | Decimal places used when comparing/writing weights. |
| `new_filament_policy` | `manual_review` | Sync → New records | What the engine does when it detects an unmapped filament: `manual_review` queues a `new_filament` conflict (actionable — the Conflicts page "Add" button imports it); `auto_import` creates the filament automatically and writes the cross-reference. Defaults to `manual_review` for both fresh and existing installs. When `variant_parent_mode` is `unset` and the filament looks like a variant-cluster member, auto-import falls back to `manual_review` regardless of this setting (can't group variants without a mode). |
| `new_spool_policy` | `manual_review` | Sync → New records | What the engine does when an unmapped spool appears whose filament **is already mapped**: `manual_review` queues a `new_spool` conflict; `auto_import` creates the spool immediately. A spool is always held when its filament is unmapped, regardless of this setting — the filament tier must resolve first. |
| `never_import_empties` | `false` | Sync → New records | **Import-time only** (UI label: "Skip empty & archived spools on import") — governs which spools the wizard and ongoing new-spool import create; it does **not** affect archive/retire mirroring for already-paired spools (that runs regardless — see `archive_sync_direction` above). When `false` (default): all spools import, including depleted (`remaining ≤ 0`) and archived ones. Archived spools import as **retired** FDB spools (spool only — the filament stays live). When `true`: spools with `remaining ≤ 0` are skipped (whether active or archived); archived spools with positive remaining weight still import as retired. The filament definition always imports regardless. |
| `variant_parent_mode` | `unset` | Import & matching | **Required before the wizard runs** (Spoolman→FDB direction): `promote_color` or `generic_container`. See [variant-parent-mode.md](variant-parent-mode.md). |
| `container_parent_marker` | env (`(Master)`) | Import & matching | Marker on generic-container names; checkbox + text field, visible in `generic_container` mode. |
| `variant_line_keywords` | env seed | Import & matching | See `VARIANT_LINE_KEYWORDS`. |
| `opentag_vendor_aliases` | env / seed | Import & matching | See `OPENTAG_VENDOR_ALIASES`. |
| `api_token_enabled` | `false` | Security | Allow `Authorization: Bearer` / `X-API-Key` machine auth. |
| `api_token` | (none) | Security | The token value; generate/regenerate in Settings (displayed masked). |
| `debug_mode` | `false` | Debug mode | Reveals the Danger Zone and enables the four `/api/debug/*` reset endpoints (403 when off). Never enable in production. |
| `mobile_labels_enabled` | env (`false`) | Mobile & Labels | Master switch for mobile updates & labels. When off, every mobile/label endpoint and the `/r/` redirect return 403 and the nav item is hidden. |
| `bridge_public_url` | env (`""`) | Mobile & Labels | External base URL baked into the printed QR. Blank = derive from the request. |
| `mobile_redirect_target` | env (`bridge`) | Mobile & Labels | `/r/` 302 target: `bridge` (scan page) or `filamentdb` (filament page). Lets every existing label re-point without reprinting. |
| `mobile_weight_default_mode` | env (`direct_correction`) | Mobile & Labels | Default weight-save mode: `direct_correction` or `usage`. Overridable per save on the update card. |
| `labelforge_url` | env (`""`) | Mobile & Labels | LabelForge base URL. Blank = printing not configured (`400 labelforge_not_configured`). |
| `labelforge_token` | env (`""`) | Mobile & Labels | LabelForge bearer token (secret; masked input). Blank = no auth header. |
| `labelforge_template` | env (`""`) | Mobile & Labels | Name of the user-created LabelForge template to print. |
| `labelforge_fields` | env (`""`) | Mobile & Labels | CSV of catalog fields to send (`brand`, `color`, `color_hex`, `number`, `material`, `qr_url`). Unknown names are skipped with a warning. |
| `labelforge_label_media` | env (`""`) | Mobile & Labels | Optional per-print media hint; blank = template default. |

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
