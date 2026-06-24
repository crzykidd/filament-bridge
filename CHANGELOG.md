# Changelog

All notable changes to **filament-bridge** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). The bare
version lives in `backend/app/__init__.py`; the `v` prefix is added only on the git tag and
GitHub release.

## [Unreleased]

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

## [0.4.0] — 2026-06-21

### Added

- **Sync Log shows the record name** — the log had only ids; each row now carries a human-readable
  "Record" column (e.g. `Amolen PLA Basic-High Speed Cream Yellow`) resolved from the
  filament/spool mapping, with a best-effort live-Spoolman fallback so even not-yet-mapped records
  (e.g. `new_filament` conflicts) are named. Makes triaging "why didn't X import" far easier.
- **Variances step shows the OpenPrintTag (OPT) badge** — each filament in the variant-grouping
  step now displays an "OPT" pill when it's tagged in OpenPrintTag, so when you pick the master
  for a cluster you can choose the OPT-backed one (which carries the standardized settings) rather
  than a variant that isn't in OpenPrintTag.

### Fixed

- **In-app release notes now render as Markdown** instead of preformatted text, fixing the
  odd wrapping caused by CHANGELOG hard-wrap lines and 2-space list-continuation indents
  showing literally in the update-available and post-upgrade modals.

- **Bulk Import Wizard (generic-container mode): adding variants under an existing master no
  longer skips the whole cluster** — when the colorless container name (e.g. `ELEGOO PLA
  (Master)`) already existed in Filament DB, the preview reported it as a name collision
  ("This container name already exists — rename it or skip"), so the cluster was skipped and
  nothing imported — even though the execute step *reuses* an existing container by
  find-or-attach. The preview now recognizes an existing null-parent container as a reuse
  target rather than a collision, so the new variants attach to the master you already have.
  A genuine clash (the name taken only by a non-container/variant record, or two clusters in
  the batch generating the same name) is still flagged.

## [0.3.1] — 2026-06-21

### Fixed

- **Bulk Import Wizard: new Spoolman colors left checked-by-default are now actually
  imported** — on the Match step, unmatched Spoolman filaments render with their import
  checkbox already ticked, but the decision was only recorded when you explicitly toggled
  a row. Clicking **Next** without touching the checkboxes dropped those rows, so the
  Execute step created nothing in Filament DB — most visibly when adding new color variants
  under an existing "use existing master" parent (the variants silently vanished). The save
  step now persists the displayed default (`create`) for untouched unmatched rows, so a
  plain Next imports them; unchecking a row still records an explicit skip. Ambiguous rows
  are unchanged (they have no safe default and still require an explicit pick).

## [0.3.0] — 2026-06-19

### Changed

- **OpenPrintTag "missing values" report now audits OpenPrintTag, not your spools** — the
  completeness report (`GET /api/openprinttag/completeness`) was reworked from a spool-data
  diff into a pure OpenPrintTag audit: for each tagged Spoolman filament it lists **every
  OpenPrintTag-supported field that is empty** across the **material, each package, and each
  package's container** (using the new `SUPPORTED_*_FIELDS` schema constants as the source of
  truth). The **"Your value (hint)" column and all Spoolman-value comparison are removed** — the
  report shows only the missing OpenPrintTag fields; the user decides what to contribute (no
  applicability/N-A pre-judging). Material `url` and package `url` are now **distinct** line
  items (a set package URL no longer masks a real material-URL gap, and vice-versa), and each
  package is reported separately (1 kg vs 5 kg); a material with no package data is flagged as
  its own gap. **`heatbreakTemperature` is excluded** (0 upstream occurrences — a forward-compat
  placeholder that would otherwise show "missing" on every record). Response items now carry
  `sections: [{scope, fields}]` instead of `attributes: [{…, your_value}]`. The expand view
  groups missing fields by Material / Package / Container; complete records stay hidden by
  default.
- **UI: renamed "OpenTag" → "OpenPrintTag" in all user-facing strings** — nav label, page title, button tooltips, table headers, status banners, and doc H1/link labels now read "OpenPrintTag". Component filenames, routes, API paths, TS identifiers, config keys, and extra-field names are unchanged.

### Fixed

- **Wizard Match step: the top "select all" now reliably selects and clears** — unselectable
  rows (FDB-only, synthetic-master, id-less) were counted in the select-all/group tri-state
  denominators, so the checkbox was stuck indeterminate and could only ever select, never
  clear — and group checkboxes broke when grouping by material/brand (masters scattered into
  those groups). The tri-state now uses the same selectable-row predicate that bulk-toggle
  acts on, so select-all/clear-all works consistently regardless of grouping.

### Added

- **"Show missing values" completeness report: per-field toggle chips + clearer purpose copy** —
  the `GET /api/openprinttag/completeness` response now carries an `audited_fields` block
  (`[{ scope, fields: [{key, label, conditional}] }]` grouped by `"material"`, `"package"`,
  `"container"`) listing the full audited-field set, derived from `SUPPORTED_*_FIELDS` minus
  `heatbreakTemperature` (`secondaryColors` included but flagged `conditional: true`). The UI
  renders a chip for every audited field (grouped Material / Package / Container) above the
  report table — all included by default; click to exclude (struck through, muted), click again
  to restore. Excluded fields are dropped from each record's sections and `missing_count` is
  recomputed client-side; a record whose recomputed count reaches 0 is treated as "complete"
  and obeys the hide-complete toggle. Sort (most-missing) uses the recomputed count. Exclusions
  persist per-browser in `localStorage` (`fb_opt_missing_excluded_fields`); a **Reset**
  affordance and an excluded-count indicator are provided. `localStorage` absent/corrupt →
  all-included. The report intro, toolbar tooltip, and idle-state help copy are reworded to
  frame the tool as an optional contribution helper — auditing OpenPrintTag, not your spools —
  matching `docs/opentag-cleanup.md`.

- **Version badge: "Update Available" pill + daily check + post-upgrade release notes modal** —
  the update-available pill label changed from "↑ vX.Y.Z" to **"Update Available"** (version
  stays in the hover title); the GitHub check TTL increased from 6 h to **24 h** (lazy-on-load,
  no scheduler). `GET /api/version` now also fetches the **running** version's GitHub release
  via `/releases/tags/v{current}` and returns three new fields: `current_release_notes`,
  `current_release_name`, `current_release_url` (all `null` on 404/dev/failure). On the
  frontend, a second independent `localStorage` key (`fb_last_running_version`) triggers a
  one-time modal showing the now-running version's release notes after an upgrade; first run
  silently seeds the key with no modal; post-upgrade modal takes precedence over the
  update-available modal when both could fire.

- **OpenPrintTag dataset: ingest the full supported schema (material + packages + containers)** —
  the dataset cache now carries the complete OpenPrintTag schema instead of a material-only
  subset. The material parse keeps every upstream `properties` key: **distinct chamber
  min/max** (`chamberTempMin`/`chamberTempMax`, plus the back-compat collapsed `chamberTemp`),
  `hardnessShoreA` (alongside `hardnessShoreD`), and `heatbreakTemperature` (mapped for
  forward-compat; absent from the current dataset). Two new tarball passes — over the *same*
  single download — populate `packages_by_material` (`{material_slug: [package, …]}` with
  `slug`, `uuid`, `gtin`, `brandSpecificId` (SKU), package-level `url`,
  `nominalNettoFullWeight`, `filamentDiameter`, `filamentDiameterTolerance`, `containerSlug`)
  and `containers_by_slug` (`uuid`, `name`, `class`, `brand`, `emptyWeight` (spool tare),
  `outerDiameter`, `innerDiameter`, `holeDiameter`, `width`). The product URL is now correctly
  understood to live at the *package* level. Canonical "every supported field" lists
  (`SUPPORTED_MATERIAL_FIELDS` / `SUPPORTED_PACKAGE_FIELDS` / `SUPPORTED_CONTAINER_FIELDS`) are
  exported as module constants for the completeness report to check emptiness against. The
  cache file gains a `schema_version` (`CACHE_SCHEMA_VERSION`) that self-heals an older-shaped
  cache by forcing a re-parse from the tarball (mirroring the `lexicon_version` self-heal) — no
  manual Refresh needed. Container `emptyWeight` (= spool tare) is ingested but not yet used;
  it is a candidate input for a future weight-model improvement.

- **OpenTag Cleanup: smart dataset refresh (commit-SHA gate)** — the OpenPrintTag dataset is
  a large GitHub tarball, so the bridge no longer re-downloads it on every refresh or stale
  reload. The cache now stores the upstream `main` HEAD **commit SHA** (`commit_sha`)
  alongside the materials. Both the stale auto-reload and the manual **Refresh dataset**
  button first do a cheap `GET …/commits/main` (using `application/vnd.github.sha` to get
  just the SHA): a matching SHA simply bumps the cache age and returns `unchanged=true` with
  no tarball download; a differing/unknown SHA downloads and records the new SHA. The default
  `POST /api/openprinttag/refresh` is the SHA-checked path (returns
  `{ unchanged, count, fetched_at, commit_sha }`); `?pull=true` ("**Pull contents anyway**")
  forces a full download regardless. The SHA check is best-effort — any failure
  (timeout/connectivity/GitHub rate-limit) falls back to downloading and never errors a
  refresh. The UI shows *"Dataset already up to date (commit · N records)"* + a **Pull
  contents anyway** button when unchanged, and freshens the banner age. The match-result
  cache fingerprint now keys its dataset identity off `commit_sha` (falling back to
  `count:fetched_at`), so a hash-only refresh doesn't spuriously invalidate the cached match.
- **OpenTag Cleanup: non-blocking matching + cached match result** — the CPU-bound match,
  completeness, and manual-search work now runs in a worker thread
  (`starlette.concurrency.run_in_threadpool`) instead of on the FastAPI event loop, so a
  match in flight no longer freezes every other bridge request (all upstream I/O is awaited
  first; only plain data crosses into the thread). The last match result is cached to
  `DATA_DIR/opentag_matches_cache.json` with `computed_at` + input fingerprints (dataset
  `count`+`fetched_at`, Spoolman filament count, alias/tag/field config hash), so
  `GET /api/openprinttag/matches` returns instantly on revisit; recompute happens only on
  the first match or with `?recompute=true`. When the inputs changed since the cached match,
  the cache is still served but flagged `stale_inputs`. The UI loads the cached result on
  **Match to DB**, shows **last matched &lt;time&gt;** with a "data changed — Refresh" hint,
  renames "Reprocess records" to **Refresh match** (forces recompute), and aborts the
  in-flight match fetch on unmount.
- **OpenTag Cleanup: inline unmatch + change-match from the candidate dropdown** — already-tagged
  rows now list scored alternates beside the pinned exact match (the exact-UUID short-circuit no
  longer suppresses fuzzy scoring), so you can re-point a wrong tag in one click. A new blank
  **"— unmatch (clear OpenTag identity) —"** option (shown only for tagged rows) stages an
  unmatch that the normal **Apply** step carries out: it blanks `openprinttag_slug` /
  `openprinttag_uuid` on the Spoolman filament and removes only those two keys from the linked
  Filament DB filament's `settings{}` bag (an approved scoped *removal* exception mirroring the
  existing identity merge — every other settings key is preserved; idempotent; best-effort on the
  FDB side). `openprinttag_ignore` is left untouched. Also adds a standalone
  `POST /api/openprinttag/clear/{id}` endpoint for an immediate clear outside the Apply flow.
  Closes the "no in-app way to clear/untag" gap (previously required editing Spoolman extras by
  hand or the debug bulk-clear).
- **OpenTag Cleanup: completeness report ("Show missing values")** — the toolbar action now
  opens a real report (`GET /api/openprinttag/completeness`) listing each tagged Spoolman
  filament and which attributes its OpenPrintTag record leaves empty, so users can find the
  entries worth enriching and contributing upstream. It measures OPT-record completeness (not a
  diff against the user's data); the user's value is shown only as a best-effort "you have this
  to contribute" hint. Missing is keyed on empty value (`null`/`""`/`[]`), not absent key, read
  from the raw OpenPrintTag record. `secondaryColors` counts only for multicolor filaments;
  identity and dead `completenessScore`/`completenessTier` fields are never counted. Stale tags
  (uuid no longer in the dataset) are surfaced distinctly. Sort by most-missing (default) or
  brand, with a hide-complete toggle. Covers only attributes the bridge ingests — a few upstream
  fields (hardness Shore A, heatbreak temperature, max chamber temperature, typed photos) are not
  yet ingested and are noted as out of scope.

### Changed

- **Consistent wizard navigation** — every wizard step and the OpenTag review/confirm flow
  now render a **Back / Next** action bar at both the top and bottom of the page via a shared
  `WizardActionBar` component. Previously three steps (Matches, Variances SM path, Preview)
  already had both bars via hand-rolled `const actionBar` blocks; five locations (Step 1
  Connectivity top, Step 2 Direction top, Step 6 Execute top, FDB-direction Variances top, and
  OpenTag confirm top) were missing a top bar, and the OpenTag review step was missing its
  bottom bar. All gaps are now filled. The Execute step's forward button remains red
  (destructive action). Terminal/result views (Execute result, OpenTag done) remain nav-free.

- **Backup dialog is now a friendly optional prompt** — `BackupSafetyDialog` (shown before
  Wizard Execute, OpenTag Apply, and enabling auto-sync) no longer blocks on an acknowledgement
  checkbox. The "Beta feature" / risk framing is removed; the Proceed button is always enabled,
  recolored indigo, and labeled "Continue". The one-click Spoolman and Filament DB backup
  buttons are retained as an optional convenience. The two Settings Danger-Zone debug clears
  (Clear Spoolman cross-refs, Clear Spoolman OpenPrintTag ids) are moved to a new
  `DebugConfirmDialog` component that preserves the strict gate: warning header, acknowledgement
  checkbox required, red Confirm button. The shared backup-buttons block is extracted into a
  `BackupButtons` sub-component used by both dialogs.

- **OpenTag Cleanup: idle landing state + top toolbar** — the page no longer runs matching on
  mount. A top toolbar with three buttons — **Refresh dataset**, **Match to DB**, and **Show
  missing values** — lets users pick an action before any network call is made. "Match to DB"
  triggers the existing match/reprocess flow; "Refresh dataset" forces a dataset re-download then
  re-enters the match view; "Show missing values" switches to a completeness-report placeholder
  (report built separately). The dataset-status banner still renders immediately (cheap
  status-only call). All existing match-view behavior (filters, groups, ignore, apply, candidate
  dropdown, manual search) is preserved unchanged inside the match view.

### Fixed

- **OpenTag Cleanup: candidate dropdown now shows for single-candidate brands** — a brand with
  only one OpenPrintTag dataset entry (e.g. TTYT3D) previously rendered a dead-end static label
  instead of the picker, so there was no obvious way to confirm or change the match. The
  dropdown now appears whenever there's at least one candidate, with an "all filaments listed"
  hint when the list isn't truncated. The "Search OpenTag manually…" affordance was moved above
  the field table and made a prominent button so re-matching is easy to find.

## [0.2.1] — 2026-06-17

### Added

- **Bidirectional archive/retire lifecycle sync (FR-21)** — a mapped spool's lifecycle
  state now mirrors between Spoolman (`archived`) and Filament DB (`retired`) in both
  directions: archiving/retiring one side flips the other, and un-archiving/un-retiring
  mirrors back too (re-enabling weight sync). A new `archive_sync` policy category
  (`archive_sync_direction`, default `two_way`; `archive_conflict_policy`, default `manual`)
  governs it from Settings → Archive / retire sync; `newest_wins` is rejected (422) since
  the state is a boolean with no timestamp. The wizard import gate is preserved — *unmapped*
  archived spools are still never auto-imported; only *mapped-pair* diffing includes archived
  spools. The lifecycle pass runs **after** the weight pass, so a depleted-and-archived spool
  settles its final decrement and FDB usage-log entry (and refreshes both snapshots) before
  the archive bit mirrors. A one-sided flip is a clean push; only a both-sides-diverge-to-
  opposite-states case queues a `cross_system` lifecycle conflict, whose human resolution
  writes the chosen state to both systems. The "Never import empties" setting was relabeled
  "Skip empty & archived spools on import" to clarify it is import-only (config key unchanged).

### Fixed

- **Synced Records now shows the Filament DB color for solid filaments (#2)** — the FDB color
  cell rendered "—" for purely-solid filaments (e.g. "Beige") even when the color was set and
  in sync. The display value (`_mc_color`) was written only by the multicolor sync pass, which
  skips solid filaments, so most filaments never captured a color for display. The engine now
  captures a representative display hex for **every** mapped filament (solid and multicolor)
  each cycle. Multicolor filaments (which store `color=null` with the real hexes in
  `secondaryColors`) also now resolve a representative hex instead of "—", and the FDB color is
  normalized to the Spoolman convention so a truly in-sync color reads as matched. Existing
  records self-heal on the next sync cycle.
- **Dashboard count clarity for master/container filaments (#3)** — when `generic_container`
  mode is in use, the "Connected systems → Filament DB" line now breaks out real filaments and
  synthetic master/container parents separately (e.g. `filaments: 37  masters: 13` instead of a
  lone `filaments: 50`), so it reconciles with the rest of the bridge (which excludes masters).
  The Spools and Filaments dashboard sections also gained help text clarifying they are counted
  independently — a filament can hold several spools, so the two totals legitimately differ and
  green-but-unequal totals are not a mismatch. Master detection is now a single shared helper
  (`core/masters.is_master_fdb`) reused by the wizard, reconcile, and health surfaces.
- **Help tooltips no longer clipped by the sidebar or page header** — the `?` HelpTip bubble
  was absolutely positioned within the page flow and got cut off near the left edge and top of
  the screen. It now renders in a portal with fixed positioning, flips above/below to stay in
  view, and clamps horizontally so it's always fully visible. Dashboard section headers
  (Spools / Filaments / Connected systems) were also made larger and higher-contrast so the
  sections read as distinct blocks.

## [0.2.0] — 2026-06-15

### Added

- **Minimum upstream version enforcement** — the bridge now declares minimum supported
  versions (Filament DB **1.33.0**, Spoolman **0.22.0**) in `core/version.py`. When a *known*
  upstream version is below its minimum, **all sync is hard-blocked**: the sync trigger /
  dry-run endpoints and the wizard execute return `409 upstream_version_unsupported`
  ("Sync disabled — upgrade …"), auto-sync cannot be enabled, and `run_sync_cycle` skips the
  cycle (so the scheduler becomes a no-op). `GET /api/sync/status` reports `sync_blocked` +
  `sync_blocked_reasons`, the Dashboard shows a red "Sync disabled" banner and disables the
  sync buttons, and `/api/health` warns per system. An unknown/unreadable version does not
  block (that's a connectivity concern). Minimums are documented in the README Prerequisites.
- **Expandable Synced Records rows** — each row in Synced Records now expands (collapsed by
  default; with Expand-all / Collapse-all) to a compact side-by-side detail showing the
  per-side last-known values for the things the bridge syncs — Spoolman (emerald) vs
  Filament DB (blue): weight (net/gross), bed/nozzle temp, cost, plus material/density/
  diameter/color as Spoolman context. Values come from the stored snapshots (no extra upstream
  fetch); the `/api/mappings` response gained an optional `detail` array.
- **Seeded OpenTag matcher defaults on new installs** — fresh installs now seed
  `opentag_vendor_aliases` (`prusa=prusament, polyterra=polymaker`) and
  `opentag_color_keywords` (`galaxy=black, cool=grey, jet=black`) so the Settings
  fields start with real, editable defaults instead of greyed-out examples. Seeding
  uses `on_conflict_do_nothing`, so **existing installs are never clobbered** — an
  upgrade keeps whatever value the user already had (including an intentionally blank one).

- **Light/dark/system theme** — the UI now supports three color modes: Light, Dark, and System
  (tracks OS preference; default). Choice persists in `localStorage` (`fb_theme`). A pre-paint
  inline script in `index.html` applies the theme class before React loads, preventing any
  white flash. An "Appearance" section at the top of Settings exposes the three-way segmented
  control; a compact three-button toggle (☀/⊙/☾) also appears at the bottom of the sidebar.
  Dark styling covers the shared chrome (Layout, sidebar, modals), all primary pages
  (Dashboard, Conflicts, SyncedRecords, SyncLog, Settings, Login, OpenTagCleanup) and Wizard
  steps 1, 2, 3, 5 (Variances), and 6. Inner sub-components of the remaining large Wizard step
  (StepNPreview) are partially polished and will be completed incrementally. A `gray-750` offset
  surface color was added to the Tailwind theme for raised dark header rows (table column headers
  and group headers).

- **Version badge + GitHub update check + release-notes popup** — the sidebar now
  shows the current version (with a `-dev+<sha>` suffix on dev builds) linking to
  its GitHub release. When a newer release is detected on GitHub (checked server-side,
  cached 6 hours), an "↑ vX.Y.Z" pill appears; a one-time modal pops up with the
  release notes and a link to the full release. Dev/channel builds suppress the update
  nag. New env vars `BRIDGE_CHANNEL` (default `release`) and `BRIDGE_COMMIT`
  (default empty) are baked in at image build time. New public endpoint `GET /api/version`.
  New Dockerfile build args `BUILD_CHANNEL` / `GIT_COMMIT`.

- **Single-account auth + API token** — the bridge is now protected by optional password
  authentication (default enabled, `AUTH_ENABLED` env var). First visit shows a setup screen
  to set the admin password; subsequent visits show a login form. Sessions use a stateless
  signed `fb_session` httpOnly cookie (itsdangerous, 30-day max-age). An optional single API
  token (enable/disable + regenerate in Settings → Security) allows machine access via
  `Authorization: Bearer` or `X-API-Key`. All `/api/*` routes except `/api/health`,
  `/api/auth/status`, `/api/auth/login`, and `/api/auth/setup` require authentication.
  Set `AUTH_ENABLED=false` to bypass auth entirely (for locked-out recovery — see
  `docs/security.md` for the procedure). New runtime settings: `api_token` (read-only display),
  `api_token_enabled`. New env var: `AUTH_ENABLED` (bool, default `true`).
- **First-login required-settings gate** — after authentication (or on every load when auth is
  disabled), the UI checks `required_settings_unset` in the config response. When non-empty (e.g.
  `variant_parent_mode` is still `"unset"`), a dismissible modal prompts the user to visit Settings
  and configure the listed items before using the bridge.

- **Configurable container-parent marker** (`container_parent_marker`) — runtime-editable string
  (env `CONTAINER_PARENT_MARKER`, default `"(Master)"`) appended to generic-container parent names
  so they visually separate from their color-variant children. An empty string disables the suffix.
  Wired through `BridgeConfig`, `ConfigResponse`/`ConfigUpdateRequest`, and the Settings UI
  (inside the Variant parent mode section, shown only when `generic_container` is selected):
  a checkbox "Append a marker to container parent names" controls on/off; when checked, a text
  input pre-filled with `(Master)` lets the user customise the marker. Changing the marker does
  not rename existing containers; the re-run resilient-409 backstop handles any resulting collision.
- **Editable container-name override at Preview** — when a proposed generic-container name collides
  with an existing Filament DB record (or another container in the same batch), the Preview step
  now renders an editable text box pre-filled with the proposed name and a "Skip cluster" control.
  The override persists as `wizard_container_name_overrides` in `BridgeConfig`; execute reads it
  and uses the user-chosen name (or suppresses the entire cluster on skip). Skipping a cluster
  also suppresses all its member filaments in both Pass 1 and Pass 2 of execute so no orphan
  records are created. Works regardless of marker setting: an empty-marker collision surfaces the
  same rename/skip UI.
- **"Master / Parent" badge for synthetic container parents in wizard Matches step** — bridge-owned
  FDB container parents (created by `generic_container` mode) previously showed as "Unmatched (FDB)"
  (alarming, actionable). They now render as a distinct purple "Master / Parent" badge, are excluded
  from the "unmatched" counter, and offer no skip/link actions. Detection order: `FilamentMapping`
  with `is_synthetic_parent=True` (authoritative), then `hasVariants=True` (fallback for
  non-bridge parents), then name-suffix heuristic.

- **OpenTag color-words map** (`OPENTAG_COLOR_KEYWORDS`) — new runtime-editable setting that maps
  color/marketing words to canonical base colors (e.g. `galaxy=black`, `cool=grey`, `jet=black`).
  The OpenTag matcher uses the map to award base-color credit when both the Spoolman name and the
  OpenTag name reduce to the same base color even though the token sets are disjoint ("Jet Black"
  and "Galaxy Black" both → "black"). The seed map is in `core/opentag_match.py:DEFAULT_COLOR_KEYWORDS`
  and covers base colors, lightness modifiers, and common marketing names. User entries are merged
  on top. Configurable via the new "Color word mappings" field in Settings.
- **OpenTag unmatched section enriched** — each row in the OpenTag Cleanup unmatched section now
  shows: color swatch, material badge, Spoolman deep link (`DeepLinks`), confidence badge, a red
  "No manufacturer" error badge when the vendor is missing, and the `no_match_reason` string so
  users understand why the filament didn't match.
- **Spool age preserved on import** — when the bridge creates a spool in Filament DB it now sets
  `purchaseDate` from Spoolman's `registered` date and `openedDate` from Spoolman's `first_used`
  date (both truncated to date-only to match Filament DB's field format). Applies to both the
  Bulk Import Wizard and ongoing new-spool sync, so a roll's age isn't lost moving to Filament DB.
- **Wizard top action bar** — primary Back/Next/Save action buttons now appear at both the top
  and bottom of each long wizard step (Matches, Variances, Preview) so users don't have to scroll
  to the bottom to proceed.
- **Variances sort control** — segmented Brand A→Z / Material A→Z sort buttons above the
  auto-groups, standalone, and manually-grouped sections in the Variances step.
- **OpenTag "Reprocess records" button** — new button on the OpenTag Cleanup dataset-status banner
  re-scans Spoolman and recomputes matches against the current cached dataset without re-downloading
  it; useful for iterating after correcting Spoolman names.
- **OpenTag SM filament deep link** — SM filament ID in the OpenTag Cleanup card header is now a
  clickable `DeepLinks` component (links to `{spoolmanUrl}/filament/show/{id}`).
- **OpenTag 10-candidate dropdown** — raised the alternate-candidate cap from 5 to 10 so the
  candidate selector shows up to 10 choices.
- **Actionable name-collision rows in Preview** — each collision entry now shows an explanatory
  warning and a "Fix variant mapping" button that navigates back to the Variances step.
- **Vendor in planned-writes spool rows** — spool rows in the Preview planned-writes list now
  include the vendor/manufacturer name in the label.
- **Settings pinned to sidebar bottom** — Settings link is now visually separated at the bottom
  of the sidebar navigation.

### Generic container parent mode

- **Generic container parent mode** — new `variant_parent_mode` setting (`unset` / `promote_color`
  / `generic_container`) for the Bulk Import Wizard (Spoolman → Filament DB). In
  `generic_container` mode the wizard synthesises a colorless, bridge-owned FDB container parent
  for every cluster (including single-color clusters); every imported color becomes a child
  variant. The container carries the finish tags (Silk / Matte / CF / …) shared by the whole
  cluster so the line reads as e.g. "PLA Silk" and variants inherit them. The container has no
  Spoolman counterpart and never participates in sync. The wizard is gated on a chosen mode
  (no silent default). See `docs/variant-parent-mode.md`.
- **Unsaved-changes guard on Settings** — navigating away from the Settings page (in-app nav
  or browser refresh/close) with unsaved edits now prompts for confirmation; an "Unsaved changes"
  indicator appears next to Save. The app router was migrated to a data router
  (`createBrowserRouter`) to enable `useBlocker`.
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

- **Bed / nozzle temperature now sync between Filament DB and Spoolman** — editing a
  filament's bed (or nozzle) temperature in Filament DB never propagated to Spoolman even
  under two-way sync, because these are *native* filament fields on both sides
  (`temperatures.bed`/`nozzle` ↔ `settings_bed_temp`/`settings_extruder_temp`) and the ongoing
  field-mapper only matched Spoolman *extra* fields. A new `_sync_material_props` engine pass
  syncs them both directions under the material_properties direction + policy (with per-field
  snapshot baselines and conflict queuing, mirroring the cost sync). SM→FDB writes preserve
  sibling temperatures via read-modify-write. (The wizard's initial import already handled these
  via its own map; only ongoing sync was missing them.)
- **Runaway weight-decrement loop in two-way sync** — a single Spoolman-side decrement
  (e.g. one print) could compound across sync cycles and drive a mapped spool to 0 g,
  ping-ponging the value SM↔FDB with a doubling delta. Two bugs: (1) `fdb_to_spoolman_net`
  subtracted `usageHistory` from `totalWeight`, but Filament DB already reduces `totalWeight`
  when usage is logged — double-counting every gram; (2) after a weight push only the source
  side's snapshot was refreshed, so the propagated change was re-detected as a fresh change on
  the other side next cycle. Net is now `totalWeight − tare` (no usage subtraction) and both
  snapshots are refreshed to the agreed state after every push, so weight sync converges.
- **Settings helper-text contrast in dark mode** — the small descriptive text under
  each settings field used `dark:text-gray-500`, which was too dark to read on the
  dark background; bumped to `dark:text-gray-400`.
- **OpenTag download hint tracks dataset size** — the "first load downloads…" status
  message no longer hardcodes "≈11k records". Each successful grab persists the record
  count to BridgeConfig (`opentag_last_count`); `GET /api/openprinttag/status` now returns
  a `last_count` field (the largest count ever seen, surviving cache-file deletion) and the
  UI shows e.g. "12,104+ records". Falls back to "thousands of records" before the first grab.
- **OpenTag VOXEL-pla brand gate** — `normalize_vendor()` now replaces hyphens and underscores
  with spaces before collapsing whitespace. This fixes a 0% / unmatched result for Spoolman vendor
  `"VOXEL-pla"` against OpenTag brand `"Voxel PLA"`: both now normalize to `"voxel pla"` and land
  in the same brand bucket so scoring can run.
- **OpenTag color scoring — "Jet Black" matches "Galaxy Black"** — the hex proximity weight was
  increased from 0.10 → 0.15 (hex is ground truth) and the color-name component was split into
  0.25 token-similarity + 0.05 base-color bonus (via the new color-words map). "PLA Jet Black"
  (#222F2E) now surfaces `prusament-pla-prusa-galaxy-black` above the 30% threshold.
- **P0.1 Double finish word in container name** — `_container_display_name` now calls
  `strip_finish_words` on the raw `material` field before composing the container name, so a
  Spoolman filament with `material = "PLA Silk"` produces "ELEGOO PLA Silk (Master)" rather than
  "ELEGOO PLA Silk Silk (Master)".
- **P0.2 Container marker changed to `(Master)`** — the parenthesised form visually separates
  the marker from the filament name so "ELEGOO PLA (Master)" is distinct from color children
  like "ELEGOO PLA Red". The marker is now user-configurable (see `container_parent_marker`
  above); an empty marker disables the suffix entirely.
- **P0.3 optTags on container reuse** — when a pre-existing container is reused on re-run, the
  wizard now PATCHes the shared finish tags (Silk / Matte / CF / …) onto the container if any are
  missing. Existing unrelated tags are preserved (merge, not clobber).
- **P1.1 Resilient 409 on filament create** — a 409 Conflict from Filament DB during container or
  child filament creation is now caught per-record (not per-batch). The record is marked as
  `failed` with detail `"name collision: <name>"`; the rest of the batch continues unaffected.
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

### Security

- **SPA static-file route confined to the static root** — the catch-all frontend route
  resolved the request path against the static directory and served any file that existed,
  so a crafted path (e.g. URL-encoded `../`) could escape it. The resolved path is now
  required to stay within the static root before it is served (path-traversal / CWE-22).
- **Untrusted values sanitized before logging** — exception text and upstream API response
  bodies logged by the OpenTag-ignore and conflict apply/import handlers are now flattened
  (CR/LF and control chars stripped via `core/log_safe.scrub`) so they cannot forge or
  inject extra log lines (CWE-117).
- **CodeQL code scanning** added to CI (security-extended suite, Python + JS/TS) as a
  required check on `main`.

[Unreleased]: https://github.com/crzykidd/filament-bridge/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/crzykidd/filament-bridge/releases/tag/v0.2.0
