# Changelog — 0.3.x (archived)

Full release notes for the **0.3.x** series. The main
[CHANGELOG.md](../CHANGELOG.md) carries a short summary of each version with a
link back here; this file preserves the complete Keep-a-Changelog detail.

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
