# Changelog

All notable changes to **filament-bridge** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). The bare
version lives in `backend/app/__init__.py`; the `v` prefix is added only on the git tag and
GitHub release.

## [Unreleased]

### Added

- **Pre-write backup safeguard** — `BackupSafetyDialog` gates three destructive actions
  (Wizard Execute, OpenTag Apply, Enable auto-sync): one-click Spoolman backup
  (`POST /api/backup/spoolman`) and one-click Filament DB backup (`GET /api/snapshot`
  proxied to `DATA_DIR/backups/`) before proceeding.
- **OpenTag secondary-colors recovery** — fetches the raw OpenPrintTag tarball on each
  cache refresh to recover `secondaryColors` missing from the FDB feed; multicolor-mismatch
  badge on cleanup cards when SM is multicolor but the matched OPT entry is single-color.
- **Scheduler & Logs settings** — runtime-editable sync interval (minutes) and sync-log
  retention (days) in Settings; `Sync Log` page gains a windowed view (`?windows=N` = most
  recent N cycle_ids) and a clear-log action (`DELETE /sync-log`).
- **Bulk Import Wizard** — wizard renamed from "Initial Sync Wizard" (re-runnable;
  idempotent execute); "Never import empties" global setting replaces per-run checkbox.
- **Debug mode + reset tools** — `debug_mode` config flag gates two destructive endpoints:
  clear Spoolman FDB cross-ref extras and reset bridge local state (mappings, snapshots,
  conflicts, sync log); both visible in a Settings danger zone.
- **Browser-local timestamps** — all timestamps in the UI render in the browser's local
  timezone (naive UTC strings get a `Z` appended before `toLocaleString`).
- **Synced Records enrichment** — `MappingRow` carries `multi_color_hexes`,
  `remaining_weight`, `is_empty`, and `conflict_id`; table gains hide-empty toggle,
  multicolor swatch, conflict deep-link, and empty-state.
- **Wizard OPT badge + filters** — OpenPrintTag-tagged filaments show an OPT badge in the
  match step; filter bar gains tagged-only, hide-matched, and hide-tagged toggles.
- **Guided initial-sync wizard** — multi-step wizard covering connectivity check, import
  direction, fuzzy vendor+name+color match review, variant grouping, field-variances
  reconciliation, dry-run preview, and execute. Decision state persists across browser visits.
- **Match review v2** — unified group-by / sort / per-column-filter table with bulk select,
  per-row decision rehydration, and a Rescan action to re-run matching after data corrections.
- **Variant-grouping step** — groups flat Spoolman filaments into Filament DB parent/variant
  hierarchies during the wizard; configurable via `VARIANT_LINE_KEYWORDS`; supports
  per-member move, standalone, and ignore actions; finish-line auto-split.
- **Variances step** — per-field reconcile of differences between Spoolman and Filament DB
  for already-matched records; picks the winning value and writes back to Spoolman before
  execute.
- **Continuous sync engine** — snapshot / diff / apply loop on a configurable interval
  (`SYNC_INTERVAL_SECONDS`); all applied changes are written to the audit log.
- **Per-category sync direction + conflict policy (two-axis model)** — weight, material
  properties, and new-spool creation each have independent direction (`filamentdb_to_spoolman`
  / `spoolman_to_filamentdb` / `two_way`) and conflict policy (`manual` or `newest_wins`).
  All are runtime-editable in Settings without a restart.
- **Enforced new-spool direction** — new-spool creation honors the configured direction;
  prevents duplicate spool creation when both sides add a spool simultaneously.
- **Net ↔ gross weight-model translation** — Spoolman weight decrements are forwarded to
  Filament DB as usage log entries (`POST .../usage`) to preserve the audit trail; weight
  increases update `totalWeight` directly.
- **Filament cost sync** — spool price syncs bidirectionally (spool-price-first); handled in
  the wizard and in the ongoing sync engine.
- **Structured multicolor/gradient sync** — bidirectional sync of FDB multi-color and
  gradient fields (hex arrays, arrangement, direction), version-gated to Filament DB ≥ 1.33.0.
- **Material-finish tag round-trip** — OpenPrintTag finish-tag IDs (matte, silk, satin, etc.)
  sync as the `filamentdb_material_tags` Spoolman extra field (CSV of ints) and back.
- **OpenTag (OpenPrintTag) cleanup tool** — matches Spoolman filaments against the
  OpenPrintTag dataset; per-filament candidate picker (best + top-5 alternates); multicolor
  and arrangement-aware scoring; group collapse/expand, ignore-all, sort by SM ID; reviewable
  Manufacturer field with vendor find-or-create reassignment; applies `openprinttag_slug` and
  `openprinttag_uuid` to Spoolman extra fields and stamps both keys into the Filament DB
  `settings{}` bag.
- **Upstream-deletion detection** — detects records soft-deleted in either system and queues
  them as conflicts for explicit user action.
- **Conflict queue** — all conflicts (field-level and deletion) are queued for manual
  resolution; conflict cards show snapshot-derived identity context; filter bar by conflict
  type.
- **Spool location carry-over** — Spoolman spool `location` is carried into Filament DB
  `locationId` during the initial wizard seed.
- **`VARIANT_LINE_KEYWORDS` config** — comma-separated keywords that prevent filaments
  matching different keywords from being grouped together; runtime-editable in Settings.
- **`OPENTAG_VENDOR_ALIASES` config** — maps Spoolman vendor names to OpenPrintTag brand
  names for the brand pre-filter; runtime-editable in Settings.
- **Web UI** — React SPA with Dashboard, Synced Records, Conflicts, Sync Log, OpenTag
  Cleanup, and Settings pages; all record rows include deep links into both upstream systems.
- **CI / publish matrix** — GitHub Actions wires lint, test, multi-arch Docker build, GHCR
  publish, registry retention, and main branch protection.

### Changed

- **Conflicts page rework** — collapsible conflict rows, sort controls, expand-all,
  resolve-clarity improvements, and multicolor color display; new_spool conflicts labelled
  "Dismiss".
- **Ongoing source-of-truth removed from wizard Step 2** — sync direction and conflict
  policy are Settings-only; wizard Step 2 only persists `import_direction`.
- **Standard `docker-compose.yml` is bridge-only** — full dev stack (Spoolman + Filament DB
  + Mongo + bridge build-from-source) moved to `docker-compose.dev.yml`.
- **Container runs non-root 1000:1000** — entrypoint chown+gosu drops to `PUID:PGID` after
  healing `/data` ownership; no static `USER` directive.
- Replaced the single source-of-truth model with the two-axis
  direction × conflict-policy model; Settings page exposes all six per-category controls.
- Enforced new-spool sync direction is now a first-class setting written by the wizard;
  removed the legacy "source of truth for new spools" concept.
- `filamentdb_material_tags` is stored as a CSV string on the Spoolman extra field (Spoolman
  text fields do not accept JSON arrays).
- OpenTag/OpenPrintTag API routes renamed from `/api/opentag/*` to `/api/openprinttag/*` to
  avoid ad-blocker interference.

### Fixed

- `multi_color_direction` is now always sent alongside `multi_color_hexes` (completes the
  multicolor 422 trio; `multi_unknown` defaults to `"coaxial"`).
- `new_spool` conflicts are now deduplicated (no duplicate row each cycle) and
  auto-resolved when the spool becomes mapped.
- Wizard pre-matches already-linked records via `filamentdb_id` cross-reference before
  fuzzy matching, making re-runs idempotent.
- Readonly-DB crash on a root-owned volume is self-healed by the entrypoint chown before
  startup.
- OpenTag color-name tokenization now splits on non-alphanumeric characters (fixes
  "Green/Purple" → `{green, purple}`).
- All backend ruff lint errors resolved (74 → 0).
- Stale cross-reference no longer causes `create_spool` to be skipped when the target spool
  already exists with a different xref; spoolWeight is resolved from the tare before use.
- `netFilamentWeight` is now set on Filament DB filament create so the spool percentage bar
  renders correctly.
- Spool `_id` is extracted from the `create_spool` response by label match rather than
  assuming a fixed position.
- Tare weight is excluded from variant-property conflict detection to prevent false conflicts
  when spoolWeight differs between variants.
- Wizard name-collision detection is now vendor-aware (same name under different vendors no
  longer triggers a false collision).
- OpenTag apply self-heals missing extra fields; `ensure_extra_fields` is resilient to partial
  field sets.
- Never send both `color_hex` and `multi_color_hexes` to Spoolman simultaneously (was
  triggering a 422).
- `multi_color_direction` is not sent to Spoolman without accompanying hex values.
- Hex color values are prefixed with `#` when writing to Filament DB.
- `filamentdb_material_tags` CSV extra field value is no longer included in the generic
  field-rows display (preventing duplicate display).
- OpenTag matcher uses color name as the primary discriminator within a brand+material bucket.
- OpenTag matcher correctly gates on polymer family and applies finish-aware scoring.
- One-way sync correctness: Spoolman PATCH is used (not PUT); weight precision setting
  respected; import guards prevent writes in the wrong direction.
- docker-compose made fully deployable; SPA route fallback added so browser-side navigation
  does not return 404.

[Unreleased]: https://github.com/hyiger/filament-bridge/compare/HEAD...HEAD
