# Changelog

All notable changes to **filament-bridge** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). The bare
version lives in `backend/app/__init__.py`; the `v` prefix is added only on the git tag and
GitHub release.

## [Unreleased]

## [0.6.5] — 2026-06-27

### Added

- **Sortable columns on the Synced Records page** — click a column header to sort by Name,
  Vendor, Spoolman weight, Filament DB weight, or Last synced (click again to reverse; rows
  with a missing value always sort last). Sorting applies to the current filtered/searched
  set. Closes #41.

### Fixed

- **Bulk Import Wizard no longer crashes on the Variances step** — selecting spools and
  proceeding to the Spoolman → Filament DB variances/tare review threw "Cannot access
  'effectiveUngrouped' before initialization" and rendered an error page, making imports in
  that direction impossible (regression introduced with the v0.6.3 required-tare change). A
  `useMemo` was declared before the variables it reads; it's now ordered correctly, with a
  render regression test guarding it. Closes #42.

## [0.6.4] — 2026-06-27

### Added

- **Wizard partial-success completion + persistent Failure Report** — the wizard now
  completes (`wizard_completed = true`) on any run with at least one success, not only on
  zero-failure runs. A total failure (0 successes, ≥1 failure) still leaves the flag false.
  Every execute run persists a `wizard_last_run` blob (failures-first record ordering) in
  BridgeConfig, served by a new `GET /api/wizard/last-run` endpoint. The Dashboard shows
  a persistent amber banner when `wizard_last_failures > 0` (from sync status), linking to
  a new **Wizard Import Report** page (`/wizard/report`) that renders the persisted
  failures-first report and includes a **Re-run wizard** button. Re-running is idempotent
  — already-imported records skip; the banner disappears when failures reach 0. Closes #14.

## [0.6.3] — 2026-06-27

### Added

- **Backup status surfaced in the UI** — the Dashboard now shows a compact "Last backup /
  Next backup" row in the sync timing card, and Settings → Scheduled backups now shows a
  full status block: last-run timestamp with success/failure detail, next fire time in
  local timezone, count and total size of retained backup files, and the active retention
  window. The **Run at (UTC hour)** selector is annotated with the local-timezone
  equivalent ("03:00 UTC ≈ 22:00 local") so the schedule is immediately interpretable
  without mental UTC conversion. The last-run summary (artifacts written, errors, pruned
  filenames) is persisted in `BridgeConfig["backup_last_run"]` by the nightly job and
  served via a new `GET /api/backup/status` endpoint. Closes #20.

- **Scan page search box** — the `/scan/:filId/:spoolId` QR-target page now shows a
  search box at the top. Typing a query calls the new `GET /api/mobile/spools?q=…`
  endpoint (mobile-gated, so it works under both the normal-login and public-scan auth
  contexts). Selecting a result navigates to that spool's scan page (`/scan/<fil>/<spool>`)
  so the update card reloads for the chosen spool — no re-scanning required. Filtering is
  case-insensitive across name, vendor, color hex, and Spoolman spool number; an empty
  query returns all mapped spools (capped at 200). Closes #36.

### Fixed

- **Wizard no longer silently writes 200 g as a default tare when Spoolman has no
  `spool_weight` set** — a wrong tare poisons every spool's gross weight and all future
  sync cycles for that filament. The Variances step now renders unknown-tare fields blank
  with a red `required` badge and disables "Save & Next" until every tare is filled in.
  The Execute endpoint also rejects (`422 tare_required`) if any tare-unknown filament
  reaches it without an override, as a belt-and-suspenders guard. Applies to both
  Spoolman → Filament DB and Filament DB → Spoolman directions.

## [0.6.2] — 2026-06-25

### Fixed

- **Release-notes / update modal no longer appears trapped inside the sidebar** — after the
  mobile collapsible-sidebar change in 0.6.1, the post-upgrade and "update available" pop-ups
  rendered as a small box pinned inside the nav sidebar instead of centered over the whole
  app. The sidebar gained a CSS `transform` (for the slide-in drawer), which makes it the
  containing block for `position: fixed` descendants and trapped the modal. The modal is now
  rendered through a portal to `<body>` so it overlays the full viewport again.
- **Tare Editor: every filament is now selectable, and the list is grouped by variant family** —
  the editor previously made variant filaments read-only, so a library organised into variant
  clusters (e.g. generic-container or promoted-colour parents) showed no checkboxes at all and
  nothing could be edited. Variants are now editable (each writes an explicit tare to both
  systems), and the list is grouped by variant family with a per-family header you can tick to
  select all of a line's colours at once.

## [0.6.1] — 2026-06-25

### Added

- **Logo & favicon** — filament-bridge now has a logo, shown in the sidebar header, on the
  login page, and at the top of the README, plus a browser favicon (theme-aware: it adapts to
  light vs. dark browser chrome).
- **Tare Editor** — a new page for fixing the empty-reel tare weight (Filament DB `spoolWeight`
  / Spoolman `spool_weight`) across many filaments at once, without re-running the Bulk Import
  Wizard. It lists every mapped filament with its current tare on both sides, flags ones that
  are missing or where the two systems disagree, and lets you set a value per row or apply one
  value to a multi-selected batch. Saving writes both systems together (and refreshes the
  bridge's baselines so the change isn't re-detected as drift). Tare is shared by every spool of
  a filament, so a correct value matters for the net↔gross weight conversion. Variants are shown
  read-only because they inherit tare from their parent — edit the parent or a standalone
  filament. ([#26](https://github.com/crzykidd/filament-bridge/issues/26))
- **Collapsible navigation on mobile** — on narrow/phone screens the nav sidebar now hides
  off-canvas behind a hamburger button in a slim top bar. Tap it to slide the menu in over a
  dimmed backdrop; tap the backdrop, the ✕, or any nav link to dismiss it (it also closes
  automatically on navigation). The desktop layout is unchanged.

### Fixed

- **OpenPrintTag Cleanup phantom updates** — after a dataset refresh, filaments whose
  data already fully matched OpenPrintTag were incorrectly shown as having pending
  updates; opening the review showed "0 fields changed". Root cause: Python
  `str(200.0)` produces `"200.0"`, but JavaScript stringifies the same JSON number as
  `"200"` (JSON numbers without a fractional part become integers in JS). Spoolman
  returns spool weight and filament weight as floats (Pydantic coerces the API
  response), while `opt_to_spoolman_fields` emits those same values as integers —
  so the backend `_data_differs()` check saw `"200.0" ≠ "200"` and flagged the
  filament as changed, while the frontend comparison saw `"200" == "200"` and showed
  zero changed fields. Fixed by normalising whole-number floats to int before
  stringification in `_normalize_field_value()`. (#31)
- **Sync-log retention now applies when auto-sync is off** — pruning of sync-log entries
  older than `sync_log_retention_days` previously ran only on auto-sync ticks, so installs
  that rely on manual sync (auto-sync is off by default) never pruned and the log grew
  unbounded. Pruning now also runs on every manual sync trigger, the nightly backup job, and
  once at startup. ([#22](https://github.com/crzykidd/filament-bridge/issues/22))

## [0.6.0] — 2026-06-24

### Added

- **Mobile updates & label printing** — print a QR-coded label for each spool and update it
  from your phone. Scanning a label opens a phone-friendly page (or search for the spool from
  the new **Mobile updates** nav item) where you enter a gross scale weight — with a live net
  preview — and change the spool's location; one Save writes both Filament DB and Spoolman.
  The QR encodes a stable bridge URL (`/r/{fil}/{spool}`) that 302-redirects to a configurable
  target, so you can re-point every printed label without reprinting. Labels print through a
  self-hosted **LabelForge** instance using a template you design, with the bridge supplying
  the field values (brand, color, number, QR, …). The whole feature is **off by default**
  behind a single switch, and configured in **Settings → Mobile & Labels**. (QR *rendering*
  needs a LabelForge `dev` build; text fields print on any version.) See
  [docs/mobile-updates.md](docs/mobile-updates.md).
- **Scheduled nightly backups** — the bridge now runs a built-in nightly job (on by
  default) that saves a backup of its own state (mappings, config, open conflicts) and a
  Filament DB snapshot into `DATA_DIR/backups/`, then prunes files past a configurable
  retention window (default 7 days). Spoolman is deliberately left out of the schedule
  because the bridge can't prune Spoolman's own archives. The master switch, the two
  backups, the retention window, and the UTC run hour (default 03:00) are all toggleable in
  **Settings → Scheduled backups**. This resolves the previously-unbounded accumulation of
  manual Filament DB snapshots.
- **Spool location now syncs continuously** — a `location_sync` category mirrors a mapped spool's
  storage location between Spoolman (the free-text `location`) and Filament DB (its `locationId`).
  Move a spool to a new shelf in either system and the bridge propagates it to the other; the
  matching Filament DB location is found-or-created automatically. Compared **by name** (Spoolman
  stores a string, Filament DB a reference). Two axes in **Settings → Location sync**:
  `location_sync_direction` (default `two_way`) and `location_sync_conflict_policy` (default
  `manual`); `newest_wins` is rejected (a location name has no timestamp). Both sides moving the
  same spool to different locations queues one `cross_system` "location" conflict you resolve in the
  queue. Previously location was only set at wizard import and the mobile update — an in-place move
  never reached the other system. (#29)

- **Configurable mobile-scan auth — `mobile_session_days`** (integer, default `30`). Controls
  whether scanning a QR label needs the app password and how long a scan login lasts. `0` makes the
  scan flow **public** — the `/r/` redirect, the `/api/mobile/*` and `/api/labels/*` endpoints, and
  the `/scan/:filId/:spoolId` page bypass the app password (the rest of the app stays
  password-protected); `>= 1` keeps the scan flow behind the normal login and sets the login session
  cookie to live that many days. Default `30` is unchanged from before. Independent of the
  `mobile_labels_enabled` master switch (the feature's 403 still applies). Set it in
  **Settings → Mobile & Labels** ("Scan login (days)") or via `MOBILE_SESSION_DAYS`.

### Fixed

- **Lowering a spool's weight now actually reaches Filament DB** — the mobile "correct
  weight" update (and the cross-system weight-conflict resolution) wrote the new weight
  to Filament DB with a direct overwrite, but Filament DB only accepts a weight *increase*
  that way — a *decrease* must go through its usage endpoint. So a downward correction
  updated Spoolman + the bridge but silently left Filament DB unchanged (and the refreshed
  snapshot then hid the miss from the next sync). Decreases now log a Filament DB usage
  entry (the only way to lower a spool's weight there); increases stay a direct write. A
  downward correction therefore shows up in Filament DB's usage history, labelled as a
  correction. (#28)

- **OpenPrintTag drying time is now stored in the right unit** — the bridge was dividing
  the drying time by 60 and writing **hours** into Filament DB's `dryingTime` field, but
  Filament DB stores `dryingTime` in **minutes** (`480` = 8 h). A material that should dry
  8 h was recorded as 8 (i.e. 8 minutes) — 60× too small. Drying time now passes through in
  minutes end-to-end (OpenPrintTag → Spoolman extra → Filament DB), all in agreement.
  Records written under the old behavior keep the wrong value until you re-run OpenTag
  **Apply** on them. (#27)

- **Resolving a cross-system conflict now actually applies your choice** — previously,
  picking a value for a standard (weight / cost / property / multicolor / material-tags /
  field-mapping) conflict only recorded the choice and wrote nothing upstream, so the
  unchanged divergence was re-detected and a brand-new conflict re-queued every sync cycle.
  Resolving now writes the chosen value to **both** systems and refreshes both snapshots
  (mirroring the lifecycle and master-divergence paths), so it converges and stays resolved.
  Weight conflicts apply as a direct absolute write to both sides (no usage entry).
  **Bulk-resolve converges the same way**, isolating any single failed write (returned in a
  `failed` list, left open) so the rest of the batch still resolves. (#21)

## [0.5.1] — 2026-06-22

### Fixed

- **Archived Spoolman spools are no longer mistaken for deleted records** — the bridge was
  asking Spoolman for archived spools with a query parameter Spoolman doesn't recognize, so
  it silently received only the *active* spools. Once a spool was archived in Spoolman (for
  example when a retired Filament DB spool mirrored across), it vanished from the bridge's
  view and the next sync raised a false **"upstream record deleted (spoolman)"** conflict.
  The bridge now uses Spoolman's `allow_archived` parameter, so archived spools stay visible
  and mirror correctly. Any false deletion conflict already sitting in the queue auto-resolves
  on the next sync once both sides are seen again. This also fixes archived spools being
  invisible to the Bulk Import Wizard.
- **Bulk Import Variances: attaching to an existing Filament DB master no longer asks you to
  pick a Spoolman color as the master** — when a group attaches to an existing Filament DB
  parent (e.g. `ELEGOO PLA (Master)`), that parent *is* the master and every Spoolman color
  attaches to it as a variant. The step previously still selected one Spoolman color as
  "master" (with a master radio, "master" pill, and a "Reconcile conflicting properties"
  box comparing the others against it), which was confusing — the import already attached all
  colors to the Filament DB parent regardless. The Variances step now shows the existing
  Filament DB parent as the master, drops the per-color master radio/pill, and hides the
  reconcile-against-master section for attach groups. Display-only — the import outcome is
  unchanged.

## [0.5.0] — 2026-06-22

### Added

- **OpenPrintTag material settings now sync into Filament DB** — seven standardized
  OpenPrintTag material settings that Spoolman has no native field for (nozzle temp
  min/max, drying temperature, drying time, Shore A/D hardness, and transmission
  distance) are now captured as **typed** (integer/float) Spoolman extra fields and
  mirrored to/from their first-class Filament DB counterparts
  (`temperatures.nozzleRangeMin/Max`, `dryingTemperature`, `dryingTime`,
  `shoreHardnessA`, `shoreHardnessD`, `transmissionDistance`). The bridge registers
  the extra fields on startup; the OpenTag cleanup **Apply** flow populates them from
  the matched OpenPrintTag material (drying time is converted from OpenPrintTag minutes
  to Filament DB hours, ÷60); and the ongoing sync mirrors them under the same
  material-properties direction + conflict policy as the other material fields,
  honoring Filament DB variant inheritance and refreshing both snapshots after a write
  (no ping-pong). Each extra-field key is overridable via a
  `SPOOLMAN_FIELD_OPENPRINTTAG_*` env var.
- **OpenTag weight-model bonus** — when the matched OpenPrintTag material has package
  and container data, the Apply flow now also offers to set Spoolman's native
  `spool_weight` (empty-reel tare, from the container `emptyWeight`) and `weight`
  (nominal full net weight, from the package `nominalNettoFullWeight`), giving the
  weight model an accurate tare from the start.
- **Bulk Import Match step shows each Spoolman filament's active spool count** — every
  Spoolman record on the Match step now displays its number of non-archived spools (e.g.
  `· 0 active spools`, highlighted amber when zero). Makes it obvious at a glance why a
  filament whose only spools are empty/archived (e.g. `Buddy3D PLA Silk Pink`) won't
  carry a spool into Filament DB.

### Fixed

- **Bulk Import: a filament whose only spools are empty/archived is no longer half-imported** —
  with "skip empty & archived" on, the wizard skipped the empty spool but still created the
  filament (and its master), leaving a spool-less Filament DB record with no Spoolman counterpart
  that showed as "unmatched" (e.g. an archived 0 g `Buddy3D PLA Silk Pink`). The import now skips
  the **filament** too when it has no importable spool, so nothing half-syncs. Archived-but-
  *non-empty* spools still import as retired (a filament with one keeps its spool and is created),
  and the ongoing archive/retire mirroring for already-mapped pairs is unaffected.

- **Bulk Import: finish-line filament names are no longer doubled** — a Silk/Matte/etc. variant
  whose Spoolman name carried the finish (e.g. `PLA Silk Pink`) was created in Filament DB with the
  finish word duplicated (`Buddy3D PLA Silk Silk Pink`), because the line base already includes the
  finish and the color suffix re-added it. The color suffix now drops a leading finish word when the
  base already carries it → `Buddy3D PLA Silk Pink`.

- **Bulk Import: a single new color now attaches to its existing Filament DB master instead of
  importing standalone** — the Variances step only formed a variant group (with the "Attach to
  «master»" control) for clusters of **2+** selected colors, so a base line where you picked just
  **one** new color fell through to "ungrouped" and imported as a standalone filament — never
  matched to the master it already has in Filament DB. With several base types this looked like
  "only the first master matches, the others come in standalone." A singleton whose
  (vendor, material, finish) matches an existing FDB parent now forms a group and attaches to that
  master (still overridable to "Create new parent" / "Standalone"); a singleton with no existing
  line stays standalone as before.

- **Bulk Import: a stale "skip" override no longer blocks importing under an existing master** —
  in generic-container mode the wizard execute honored a saved container-name `skip` override
  unconditionally, so a skip you chose during a *past* name-collision kept silently dropping the
  whole cluster on every later import — even after the collision was gone (the master now exists
  and is reusable) and the dry-run preview showed the variants as "create". Execute now honors a
  `skip` only when the cluster *genuinely* collides right now (using the same collision check as
  the preview), so a stale skip is ignored and the variants import under the existing master. Fixes
  "can't sync if the master exists in Filament DB"; preview and execute now agree.

- **Empty spools no longer spam `new_spool` conflicts when "skip empty & archived" is on** —
  with `never_import_empties` enabled, an empty (0 g) unmapped spool on an already-mapped
  filament was re-queued as a `new_spool` conflict every sync cycle (it can never auto-import),
  cluttering the conflict queue. The ongoing sync now honors the gate and skips empty spools the
  same way the wizard does (archived spools were already excluded from new-spool detection), and
  it auto-resolves any lingering `new_spool` conflict for a spool that's since become
  empty/archived (never-importable) so old conflicts clear themselves.

## [0.4.0] — 2026-06-21 (summary)

- Sync Log now shows a human-readable **Record** column (resolved from the mapping, with a live-Spoolman fallback for unmapped records).
- Variances step shows an **OpenPrintTag (OPT)** badge so you can pick the OPT-backed filament as master.
- In-app release notes now render as **Markdown** (no more literal hard-wrap/indent artifacts).
- Fix: generic-container variants now **attach to an existing master** instead of skipping the whole cluster on a false name collision.

[Full notes →](docs/CHANGELOG-0.4.x.md#040--2026-06-21)

## [0.3.1] — 2026-06-21 (summary)

- Fix: the Bulk Import Wizard now imports unmatched Spoolman colors left **checked-by-default** — clicking Next without toggling each row no longer silently drops them.

[Full notes →](docs/CHANGELOG-0.3.x.md#031--2026-06-21)

## [0.3.0] — 2026-06-19 (summary)

- **OpenPrintTag Cleanup overhaul** — idle landing toolbar (Refresh dataset · Match to DB · Show missing values), inline unmatch/change-match from the candidate dropdown, and a "missing values" report that audits OpenPrintTag completeness with per-field toggle chips.
- **Faster & non-blocking** — matching runs off the event loop with a cached result; smart dataset refresh uses a cheap commit-SHA gate and only re-downloads when the upstream dataset actually changed.
- **Full OpenPrintTag schema ingest** — material + packages + containers, with canonical supported-field lists and a self-healing cache schema version.
- **Version awareness** — "Update Available" pill, 24 h check, and a one-time post-upgrade release-notes modal.
- **UX polish** — consistent Back/Next bars on every wizard step; the pre-write backup prompt is now friendly/optional; renamed "OpenTag" → "OpenPrintTag" across the UI.

[Full notes →](docs/CHANGELOG-0.3.x.md#030--2026-06-19)

## [0.2.1] — 2026-06-17 (summary)

- **Bidirectional archive/retire lifecycle sync (FR-21)** — a mapped spool's archived ↔ retired state mirrors both ways, governed by a new `archive_sync` policy category.
- Fix: Synced Records shows the Filament DB color for solid filaments (#2).
- Fix: Dashboard breaks out real filaments vs synthetic master/container parents (#3); help tooltips are no longer clipped by the sidebar/header.

[Full notes →](docs/CHANGELOG-0.2.x.md#021--2026-06-17)

## [0.2.0] — 2026-06-15 (summary)

The foundational release — the bridge's initial public feature set:

- **Continuous sync engine** with the two-axis per-category direction × conflict-policy model, plus the re-runnable **Bulk Import Wizard** and the Dashboard / Synced Records / Conflicts / Sync Log / Settings UI.
- **Field coverage** — net↔gross weight translation (usage-log audit trail), cost sync, structured multicolor/gradient sync, and material-finish tag round-trip.
- **OpenPrintTag (OpenTag) cleanup tool** and the **generic-container** variant parent mode.
- **Single-account auth + API token**, light/dark/system theme, version badge + GitHub update check, and CodeQL scanning in CI.
- **Minimum upstream version enforcement** (Filament DB 1.33.0 / Spoolman 0.22.0).

[Full notes →](docs/CHANGELOG-0.2.x.md#020--2026-06-15)

## Archived releases

Older series are summarised above; the complete notes are archived per minor series:

- [0.4.x — full notes](docs/CHANGELOG-0.4.x.md)
- [0.3.x — full notes](docs/CHANGELOG-0.3.x.md)
- [0.2.x — full notes](docs/CHANGELOG-0.2.x.md)

[Unreleased]: https://github.com/crzykidd/filament-bridge/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/crzykidd/filament-bridge/releases/tag/v0.6.0
[0.2.0]: https://github.com/crzykidd/filament-bridge/releases/tag/v0.2.0
