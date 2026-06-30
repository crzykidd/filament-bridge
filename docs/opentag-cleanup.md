# OpenPrintTag Cleanup tool

A standalone, on-demand tool that matches your Spoolman filaments against the
[OpenPrintTag](https://openprinttag.org) community database, lets you review every proposed
field, and applies canonical data — to Spoolman, and (where a record is bridge-linked) the
OpenPrintTag identity into Filament DB.

API routes live at `/api/openprinttag/*` (the bare word "opentag" is on ad-blocker filter
lists, so the routes avoid it).

## Landing state and toolbar

The page opens in an **idle landing state** — nothing is fetched on mount. A top toolbar
offers three actions:

- **Refresh dataset** — check OpenPrintTag for a newer dataset, then run matching and enter
  the Match-to-DB view. This is **smart**: it first does a cheap upstream commit-SHA check
  (one tiny request) and only downloads + re-parses the multi-MB tarball when the upstream
  repo actually changed. If the dataset is unchanged it just freshens the cache age, shows
  *"Dataset already up to date (commit · N records)"*, and offers a **Pull contents anyway**
  button that forces a full re-download regardless of the commit. See
  [Smart refresh](#smart-refresh-commit-sha-gate) below.
- **Match to DB** — load the match review view. The **last match result is cached**, so
  this returns instantly when a prior match exists (no re-scoring). Only the first match
  (or an explicit refresh) actually computes. Switches to the match review view.
- **Show missing values** — an optional tool to find which of your tagged filaments most need
  data contributed to OpenPrintTag. Audits the OpenPrintTag database (not your spools): for
  each tagged filament it lists every supported field the community database leaves empty, so
  you can decide what to go submit. See [completeness report](#completeness-report-show-missing-values).

The **dataset-status banner** (count, age, stale flag) is always visible — it reads the
local cache status cheaply without fetching from OpenPrintTag.

Once a match has been loaded, the banner shows **last matched &lt;time&gt;** and a
**Refresh match** button that re-scores against the current dataset without re-downloading.
If the underlying inputs changed since the cached match was computed — the dataset was
refreshed, the Spoolman filament count changed, or a relevant setting (manufacturer
mappings, finish-tag map, extra-field names) was edited — a **"data changed since last
match — Refresh"** hint appears next to it. Applying writes (main Apply or the updates
review) automatically forces a recompute so the view reflects what was just written.

### Performance: non-blocking scoring + result cache

Matching is CPU-bound (scoring every Spoolman filament against the brand-gated slice of the
~11k-entry dataset). Two measures keep it from freezing the bridge:

- **Offloaded off the event loop.** The pure-CPU scoring runs in a worker thread
  (`starlette.concurrency.run_in_threadpool`). All I/O — the dataset load, the BridgeConfig
  read, and the Spoolman filament fetch — is awaited on the event loop *first*; only plain
  data is passed into the thread. So a match in flight no longer blocks other API requests.
  The completeness report and manual search are offloaded the same way.
- **Result cache.** `GET /api/openprinttag/matches` persists the computed result to
  `DATA_DIR/opentag_matches_cache.json` (alongside `computed_at` and input fingerprints) and
  serves it instantly on the next visit. The fingerprint covers the dataset identity
  (the upstream `commit_sha`, falling back to `count`+`fetched_at`), the Spoolman filament
  count, and a hash of the alias/tag/field config; when any differs from the cached inputs
  the cache is still served but flagged with
  `stale_inputs` so the UI can prompt for a refresh. Recompute only happens on the first
  match or when called with `?recompute=true` (the **Refresh match** / **Refresh dataset**
  buttons).

## The dataset

The OpenPrintTag dataset is fetched directly from the
[OpenPrintTag GitHub tarball](https://github.com/OpenPrintTag/openprinttag-database) and
cached locally (`DATA_DIR/opentag_cache.json`, TTL `OPENTAG_CACHE_MAX_AGE_HOURS`, default
24 h). Brand names, material properties, and secondary colors are all parsed in a single
tarball download — no Filament DB involvement. Only `class: FFF` materials are included
(SLA and others are skipped).

### Smart refresh (commit-SHA gate)

The tarball is large, so the bridge avoids re-downloading it unless the upstream data
actually changed. The cache file stores the upstream `main` HEAD **commit SHA**
(`commit_sha`) alongside the materials. The refresh decision works as follows:

- **Stale auto-reload** (cache older than `OPENTAG_CACHE_MAX_AGE_HOURS`) and **manual
  Refresh** both run a cheap `GET …/commits/main` with the `application/vnd.github.sha`
  media type (returns just the 40-char SHA as plain text). If the SHA **matches** the
  cached one, the bridge rewrites only `fetched_at` (bumping the age) and reports
  `unchanged=true` — **no tarball download**. If it **differs** (or no SHA was stored yet,
  e.g. a pre-SHA cache), the tarball is downloaded and the new SHA recorded.
- **Pull contents anyway** forces a full download regardless of the commit (`POST
  /api/openprinttag/refresh?pull=true`). The default refresh (`?pull=false`) is the
  SHA-checked path and returns `{ unchanged, count, fetched_at, commit_sha }`.
- The SHA check is **best-effort**: any failure (timeout, connectivity, GitHub rate-limit —
  unauthenticated GitHub allows 60 requests/hour/IP — or an unexpected body) returns `None`
  and the bridge falls back to downloading. A failed check never makes a refresh error out.

The match-result cache fingerprint keys its dataset identity off this `commit_sha` when
present (falling back to `count:fetched_at` when the SHA is unknown), so a hash-only refresh
that doesn't change the dataset doesn't spuriously invalidate the cached match.

### Cached data model (full supported schema)

The single tarball download is parsed into three cache structures (all in
`opentag_cache.json`):

- **`materials`** — one OPTMaterial dict per `class: FFF` material. Carries the full
  upstream `properties` set: nozzle/bed/chamber temps (bed: `bedTempMin` + `bedTempMax`;
  chamber: **distinct `chamberTempMin`/`chamberTempMax`** plus a back-compat collapsed
  `chamberTemp`), density, drying temp/time, preheat temp, **`hardnessShoreA`** and
  `hardnessShoreD`, transmission distance, `nozzleDiameterMin`, `cureWavelength`, tags,
  photo URL, the material-level product URL, and primary/secondary colors.
  (`heatbreakTemperature` is mapped for forward-compat but absent from the current dataset.)
- **`packages_by_material`** — `{ material_slug: [package, …] }` (a material has 1→N
  packages). Each package carries `slug`, `uuid`, `gtin` (barcode), `brandSpecificId` (the
  **SKU**), package-level `url`, `nominalNettoFullWeight`, `filamentDiameter`,
  `filamentDiameterTolerance`, and `containerSlug` (FK into the container index). The
  product **URL lives at the package level**, not the material level — a material with no
  package URL but a populated `materials.productUrl` is not "missing" a URL.
- **`containers_by_slug`** — `{ container_slug: container }`. Each container carries `uuid`,
  `name`, `class`, `brand`, `emptyWeight` (the **spool tare** — a likely future weight-model
  input; currently ingested but unused), `outerDiameter`, `innerDiameter`, `holeDiameter`,
  and `width`.

The canonical "every supported field" lists live as module constants in
`backend/app/core/opentag_cache.py` — `SUPPORTED_MATERIAL_FIELDS`,
`SUPPORTED_PACKAGE_FIELDS`, `SUPPORTED_CONTAINER_FIELDS` — and are the source of truth for
the completeness report's emptiness checks.

The cache file carries a `schema_version` (`CACHE_SCHEMA_VERSION`). Bumping it self-heals
an older-shaped cache by forcing a re-parse from the tarball (mirroring the
`lexicon_version` self-heal), so new fields populate without a manual Refresh.

## How matching works

Per Spoolman filament:

1. **UUID short-circuit.** A filament whose `openprinttag_uuid` extra already maps to a
   known material matches at 100% — no fuzzy scoring.
2. **Brand pre-filter.** Only materials of the filament's brand are scored. Vendor-name
   gaps between systems are bridged by the **Manufacturer mappings** setting
   (`prusa=prusament, polyterra=polymaker` seeded on new installs); hyphens/case are
   normalized automatically.
3. **Color-profile gate.** Single-color filaments only match single-color materials;
   coextruded/gradient only match compatible multicolor profiles.
4. **Polymer-family gate.** A PC filament can never match ASA, etc. (PLA and PLA+ are the
   same family by design — grades live in the name, per the OpenPrintTag spec.)
5. **Structured scoring** (sums to 1.0): material 0.15, brand 0.15, color-*multiset*
   0.40 (order-independent, count-aware — a name with "Silver & Blue" scores both colors
   separately), modifier Jaccard 0.15 (silk/matte/gradient words), finish-tag agreement
   ±0.10, color-hex proximity 0.05, full-string tiebreaker 0–0.05.

Matches below 30% land in the **unmatched** list with a reason (unknown manufacturer, no
material for that brand, multicolor with no multicolor candidates, or simply no confident
match). Fix unknown manufacturers by adding a mapping in Settings, then **Refresh match**.

For a detailed breakdown of how scoring works — including the mined lexicons, n-gram
separator rule, color multiset formula, and a worked AMOLEN example — see
[opentag-matching.md](opentag-matching.md).

## Updates available banner

When the matches are loaded, a banner appears at the top if any already-tagged filaments
(those carrying an `openprinttag_uuid` extra) have values that differ from the latest
OpenPrintTag dataset. The count excludes filaments the user has suppressed via **Ignore future
updates** (see below).

### Numeric comparison and float normalisation

Field values are compared as strings after normalisation (lowercase, trimmed). Whole-number
floats are normalised to integers before stringification so that Spoolman's `200.0` (a
Pydantic `float`) and OpenPrintTag's `200` (an integer) are treated as equal. This matches
the behaviour of the frontend, where the JSON number `200` is parsed by JavaScript as an
integer and `String(200) = "200"` (not `"200.0"`). Without this alignment, fields like
`spool_weight` and `weight` could show as "changed" in the backend diff while the frontend
review showed "0 fields changed".

Click **Review updates** to switch to the focused updates view.

## Updates review view

The **Review updates** view shows only the filaments with drifted data. For each:

- A collapsible **field table** showing current Spoolman value → updated OpenPrintTag value per
  changed field (identity fields slug/uuid are not shown here — they never trigger the banner).
- A **per-row checkbox** and a **Select all / Deselect all** toolbar button.
- **Search** by name or vendor, **group by** brand/material, and **sort** by brand or name.
- **Apply selected** → calls the existing `POST /api/openprinttag/apply` endpoint with only
  the selected filaments. On success those filaments drop out of the "updates available" set.
- **Ignore future updates** per filament — persists a Spoolman extra field
  (`openprinttag_ignore = "1"`) so the filament is excluded from the updates count until
  un-ignored. See below.
- **Ignored filaments** section (collapsible) at the bottom of the view, with an
  **Un-ignore** button for each.

## Ignore future updates

Each filament in the Updates Review view has an **Ignore future updates** button. Clicking
it writes `openprinttag_ignore = "1"` to the Spoolman filament's extra fields via
`POST /api/openprinttag/ignore/{id}?ignored=true`. Clicking **Un-ignore** clears the flag
(`ignored=false`). The field is registered at startup alongside the other OpenPrintTag extra
fields; it must exist before any write can succeed.

Because the flag is stored on the Spoolman filament record, it:
- Survives bridge restarts and cache clears.
- Travels with the record if the filament is re-imported.
- Is checkable on every `GET /api/openprinttag/matches` run (the backend reads it and sets
  `ignored_updates: true` / `has_update: false` on that match row, and excludes it from
  `updates_count`).

The flag is visible in Spoolman's extra-field UI as "OpenPrintTag Ignore Updates".

## Completeness report ("Show missing values")

The **Show missing values** toolbar action opens an optional, read-only **completeness report**
backed by `GET /api/openprinttag/completeness`.

**This tool audits OpenPrintTag, not your spools.** It answers one question: *for the records
in my library, which OpenPrintTag-supported fields does the community database leave empty, so
I can decide what to go contribute?* Your own Spoolman data is **never read or compared** —
your inventory only **scopes which OpenPrintTag records to audit**. For each Spoolman filament
with a non-empty `openprinttag_uuid`, the bridge resolves its OpenPrintTag record and lists
every supported-but-empty field across the **material, each of its packages, and each package's
container**.

- **No spool-data comparison.** There is no "your value" column and no read of Spoolman field
  values anywhere in the report — only the OpenPrintTag field labels that are missing.
- **No applicability / N-A pre-judging.** Every supported field is listed when empty,
  regardless of whether it makes sense for that material — *you* decide what's worth
  submitting (e.g. skip chamber temp for PLA yourself). The report never hides a field by
  material type.
- **Missing = empty value, not absent key.** A field is listed only when its value is `null`,
  an empty string, or an empty list (an empty `tags` list counts).
- **Source of truth = `SUPPORTED_*_FIELDS`.** Emptiness is checked against the canonical
  `SUPPORTED_MATERIAL_FIELDS` / `SUPPORTED_PACKAGE_FIELDS` / `SUPPORTED_CONTAINER_FIELDS`
  constants in `core/opentag_cache.py` — adding a field to the parser automatically extends
  the audit.
- **`heatbreakTemperature` is excluded.** The ingest confirmed it has **0 upstream
  occurrences** (a forward-compat placeholder, `None` on every record), so reporting it would
  falsely show "missing" everywhere. It is filtered out of the material audit (see
  `_REPORT_EXCLUDED_MATERIAL_KEYS` in `api/opentag.py`).
- **Material URL vs package URL are distinct fields.** A record may have an empty material
  `productUrl` while its package `url` is set (or vice-versa). They are reported at their own
  levels — "Product URL" under Material, "Product URL (package)" under the package — so a
  set package URL no longer masks a real material-URL gap (and vice-versa).
- **Packages are 1→N.** Each package gets its own section (e.g. 1 kg vs 5 kg), listing that
  package's empty fields. A material with **no package data at all** is surfaced as its own
  gap ("No package data").
- **Conditional secondary colors.** Counted only when the filament is multicolor (Spoolman
  `multi_color_hexes` set, or the OPT record carries a `coextruded`/`gradient` arrangement
  tag), since a single-color filament legitimately has none.
- **Never listed:** identity fields (uuid/slug/brand/name — always present) and the dead
  `completenessScore`/`completenessTier` fields.
- **Stale tags.** A filament whose `openprinttag_uuid` is no longer in the current dataset is
  surfaced as a distinct **"stale tag"** row (not silently dropped) — re-match it or refresh.

**Response shape.** Each item is
`{ spoolman_filament_id, brand, name, opt_slug, opt_uuid, opt_url, missing_count,
sections: [ { scope, fields: [<labels>] } ], stale_match }`, where `scope` is `"material"`,
`"package:<slug>"`, `"package:none"`, or `"container:<slug>"`. The top-level response also
carries an `audited_fields` block — `[{ scope, fields: [{key, label, conditional}] }]` grouped
by `"material"`, `"package"`, and `"container"` — listing every field the report can check,
derived from `SUPPORTED_*_FIELDS` minus `heatbreakTemperature`. The UI renders per-field
toggle chips from this list so chips appear for ALL audited fields, not just currently missing
ones.

**Controls:** the table shows Brand · Filament · OpenPrintTag match (slug, linked to the
record's product URL when present) · # missing. Expanding a row shows the missing supported
fields grouped by section (Material / Package <size> / Container).

**Per-field toggle chips** (above the table, grouped Material / Package / Container) let you
include or exclude individual audited fields from the gap tally. All fields are included by
default; click a chip to exclude it (struck through, muted), click again to restore. Excluded
fields drop out of each record's sections and the `missing_count` is recomputed client-side —
a record whose recomputed count reaches 0 is treated as "complete" and hidden by the
hide-complete toggle. Exclusions persist in `localStorage`
(`fb_opt_missing_excluded_fields`) across page reloads, per browser. A **Reset** affordance
clears all exclusions, and an excluded-count indicator shows how many are currently excluded.
Excluding all fields → empty report (fine; user did that).

Sort by **Most missing** (default) or **Brand (A→Z)**; records with zero gaps (for the selected
fields) are hidden by default with a **Show complete records** toggle — gapped records always
show. The data is local and small, so the whole report is computed in a single pass (offloaded
to a worker thread) with no pagination.

## Review (full review view)

Each filament card shows the best candidate (★) and up to ten alternates in a dropdown,
with a field-by-field table: current Spoolman value vs the OpenPrintTag value. Per field you can
edit the proposed value or mark it **keep mine**; per filament you can **ignore** the match
entirely. Group by brand/material, sort, and filter (hide matched / hide already-tagged) to
work through a large library; "Ignore all" works per group.

### Change-match and unmatch (the candidate dropdown)

The candidate dropdown is the single control for both **re-pointing** and **clearing** a
match:

- **Already-tagged rows now list alternates too.** A filament whose `openprinttag_uuid`
  already maps to a record still pins that exact match at the top (★, 100%), but the bridge
  now also runs the normal gate pipeline and scores the rest of the brand's catalogue, so the
  dropdown offers up to ten alternates you can re-point to (e.g. to fix a tag applied to the
  wrong colour). Picking an alternate stages a re-match — Apply writes the new slug/uuid.
  (A brand with only one dataset entry shows just the current match plus the unmatch option.)
- **"— unmatch (clear OpenPrintTag identity) —"** is the last dropdown option, shown only for rows
  that already carry an OpenPrintTag identity. Selecting it **stages an unmatch** that is carried
  through the normal **Apply** flow (it is not an immediate write — consistent with the rest
  of the page). On Apply, the bridge clears the identity:
  - blanks `openprinttag_slug` + `openprinttag_uuid` on the Spoolman filament, and
  - removes only those two keys from the linked Filament DB filament's `settings{}` bag
    (the approved scoped *removal* exception — every other settings key is preserved).

  `openprinttag_ignore` is **not** touched by an unmatch (that is a separate suppression
  concern). After Apply, the row reads as untagged and the next match cycle re-evaluates it
  from scratch. There is also a standalone `POST /api/openprinttag/clear/{id}` endpoint that
  performs the same clear immediately if a caller needs it outside the Apply flow.

Badges: a grey **OPT** chip means the filament is already tagged and in sync with the
candidate; amber means it's tagged but the data has drifted; a **multicolor mismatch** chip
warns when Spoolman has multicolor data but the candidate is single-color.

The **Manufacturer** row appears whenever the Spoolman vendor name and the OpenPrintTag brand
name differ in any visible way, including case-only differences (e.g. "Elegoo" vs
"ELEGOO").  Accepting it re-points **only this filament** to a vendor with OpenPrintTag's
exact canonical spelling (created in Spoolman if no vendor with that exact name exists;
this is the only path in the tool that can create a vendor).  The existing vendor is
never renamed; other filaments under the old vendor are never touched.  A case-only
diff intentionally creates a near-duplicate vendor — that trade-off is accepted.

### Manual search

Each card has a **Search OpenPrintTag manually…** link (below the field table, always
visible when the card is expanded and not ignored). Click it to open a per-card search
box. Type a keyword (e.g. "Silk Gold", "Matte Dark Blue"); results are scored against
the same brand+material context as the automatic match and rendered with confidence
badges. Clicking a result injects it as the active candidate — the field table, slug,
and confidence badge all update immediately. The injected candidate is de-duplicated
against any existing candidates so re-searching does not bloat the list.

This is useful for unmatched filaments (confidence &lt; 30%) or cases where the
automatic best match is clearly wrong.

## Apply

The **Review & Confirm →** button appears at both the top and bottom of the review view,
and the Confirm step's **Back / Apply N writes** bar likewise appears at both top and bottom.
Both placements are identical in behavior — scroll position doesn't matter.

The Confirm step lists every pending write (old → new, grouped per filament) before
anything happens; Apply first shows the friendly backup dialog (an **optional** one-click
Spoolman/Filament DB backup — it no longer blocks on an acknowledgement). Per filament, the
bridge then:

1. PATCHes the confirmed fields to Spoolman (multicolor writes always pair
   `multi_color_hexes` with a direction; `color_hex` is never sent alongside them),
2. writes `openprinttag_slug` / `openprinttag_uuid` extras, and
3. merges the same two identity keys into the linked Filament DB filament's `settings{}`
   bag (the approved scoped exception — all other settings keys are preserved).

For a staged **unmatch**, Apply instead clears the identity (blanks the SM slug/uuid extras
and removes those two keys from the FDB `settings{}` bag) — the SM write is authoritative and
the FDB removal is best-effort (a missing FDB mapping is fine). The result row reports status
`cleared`.

Errors are per-filament; one failure never aborts the batch. The ongoing sync engine keeps
the identity keys flowing afterwards, so a filament cleaned here looks identical to one
imported from OpenPrintTag directly.
