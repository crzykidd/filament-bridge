# OpenTag Cleanup tool

A standalone, on-demand tool that matches your Spoolman filaments against the
[OpenPrintTag](https://openprinttag.org) community database, lets you review every proposed
field, and applies canonical data — to Spoolman, and (where a record is bridge-linked) the
OpenPrintTag identity into Filament DB.

API routes live at `/api/openprinttag/*` (the bare word "opentag" is on ad-blocker filter
lists, so the routes avoid it).

## Landing state and toolbar

The page opens in an **idle landing state** — nothing is fetched on mount. A top toolbar
offers three actions:

- **Refresh dataset** — re-download the OpenPrintTag dataset from OpenPrintTag, then run
  matching and enter the Match-to-DB view. The first load downloads and parses a multi-MB
  tarball (typically a few seconds).
- **Match to DB** — scan Spoolman filaments and match against the cached dataset (no
  download if the cache is fresh). Switches to the match review view.
- **Show missing values** — switch to the [completeness report](#completeness-report-show-missing-values),
  which lists each tagged Spoolman filament and which attributes its OpenPrintTag record
  still leaves empty.

The **dataset-status banner** (count, age, stale flag) is always visible — it reads the
local cache status cheaply without fetching from OpenPrintTag.

Once a match has been loaded, a **Reprocess records** button appears in the banner to
re-scan Spoolman and recompute matches against the current dataset without downloading
again.

## The dataset

The OpenPrintTag dataset is fetched directly from the
[OpenPrintTag GitHub tarball](https://github.com/OpenPrintTag/openprinttag-database) and
cached locally (`DATA_DIR/opentag_cache.json`, TTL `OPENTAG_CACHE_MAX_AGE_HOURS`, default
24 h). Brand names, material properties, and secondary colors are all parsed in a single
tarball download — no Filament DB involvement. Only `class: FFF` materials are included
(SLA and others are skipped).

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
   same family by design — grades live in the name, per the OpenTag spec.)
5. **Structured scoring** (sums to 1.0): material 0.15, brand 0.15, color-*multiset*
   0.40 (order-independent, count-aware — a name with "Silver & Blue" scores both colors
   separately), modifier Jaccard 0.15 (silk/matte/gradient words), finish-tag agreement
   ±0.10, color-hex proximity 0.05, full-string tiebreaker 0–0.05.

Matches below 30% land in the **unmatched** list with a reason (unknown manufacturer, no
material for that brand, multicolor with no multicolor candidates, or simply no confident
match). Fix unknown manufacturers by adding a mapping in Settings, then Reprocess.

For a detailed breakdown of how scoring works — including the mined lexicons, n-gram
separator rule, color multiset formula, and a worked AMOLEN example — see
[opentag-matching.md](opentag-matching.md).

## Updates available banner

When the matches are loaded, a banner appears at the top if any already-tagged filaments
(those carrying an `openprinttag_uuid` extra) have values that differ from the latest
OpenTag dataset. The count excludes filaments the user has suppressed via **Ignore future
updates** (see below).

Click **Review updates** to switch to the focused updates view.

## Updates review view

The **Review updates** view shows only the filaments with drifted data. For each:

- A collapsible **field table** showing current Spoolman value → updated OpenTag value per
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
(`ignored=false`). The field is registered at startup alongside the other OpenTag extra
fields; it must exist before any write can succeed.

Because the flag is stored on the Spoolman filament record, it:
- Survives bridge restarts and cache clears.
- Travels with the record if the filament is re-imported.
- Is checkable on every `GET /api/openprinttag/matches` run (the backend reads it and sets
  `ignored_updates: true` / `has_update: false` on that match row, and excludes it from
  `updates_count`).

The flag is visible in Spoolman's extra-field UI as "OpenPrintTag Ignore Updates".

## Completeness report ("Show missing values")

The **Show missing values** toolbar action opens a read-only **completeness report** backed
by `GET /api/openprinttag/completeness`. For each Spoolman filament that already carries an
`openprinttag_uuid`, the bridge resolves its OpenPrintTag record and reports which schema
attributes that record leaves **empty** — so you can go enrich those entries and contribute
them back to the OpenPrintTag database.

It measures **OpenPrintTag record completeness, not a diff against your data.** The missing
count is driven purely by the OPT record's empty fields. Your own Spoolman value (where a
sensible mapping exists) is shown beside each missing attribute only as a *"you have this to
contribute"* hint; a blank hint is normal and never affects the count.

- **Missing = empty value, not absent key.** Every OpenPrintTag record carries all of its
  keys; a field is counted only when its value is `null`, an empty string, or an empty list
  (an empty `tags` list counts as missing).
- **Counted attributes** (FFF). Core: material type, abbreviation, primary color, density,
  nozzle temp min/max, bed temp min/max, tags, photo URL, product URL. Extended: chamber
  temp, preheat temp, drying temp, drying time, hardness (Shore D), transmission distance.
  Conditional: **secondary colors** — counted only when the filament is multicolor (Spoolman
  `multi_color_hexes` set, or the OPT record carries a `coextruded`/`gradient` arrangement
  tag), since a single-color filament legitimately has none.
- **Never counted:** identity fields (uuid/slug/brand/name — always present) and the dead
  `completenessScore`/`completenessTier` fields (always null in the dataset).
- **Stale tags.** A filament whose `openprinttag_uuid` is no longer present in the current
  dataset is surfaced as a distinct **"stale tag"** row (not silently dropped) — re-match it
  or refresh the dataset.

**Controls:** the table shows Brand · Filament · OPT match (slug, linked to the record's
product URL when present) · # missing. Expanding a row shows a per-attribute table of
*your value (hint)* vs *OpenPrintTag (— missing)*. Sort by **Most missing** (default) or by
**Brand (A→Z)**; complete records are hidden by default with a **Show complete records**
toggle. The data is local and small, so the whole report is computed in a single pass with
no pagination.

**Known limitation (ingested fields only).** The report covers only the attributes the
bridge's dataset parser ingests. A few upstream OpenPrintTag schema fields are not yet
ingested — `hardness_shore_a`, `heatbreak_temperature`, `max_chamber_temperature`, and
typed/multiple photos — and are therefore not assessed here. The UI notes this. Extending
the parser to ingest them is a possible separate follow-up.

## Review (full review view)

Each filament card shows the best candidate (★) and up to ten alternates in a dropdown,
with a field-by-field table: current Spoolman value vs the OpenTag value. Per field you can
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
- **"— unmatch (clear OpenTag identity) —"** is the last dropdown option, shown only for rows
  that already carry an OpenTag identity. Selecting it **stages an unmatch** that is carried
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

The **Manufacturer** row appears whenever the Spoolman vendor name and the OpenTag brand
name differ in any visible way, including case-only differences (e.g. "Elegoo" vs
"ELEGOO").  Accepting it re-points **only this filament** to a vendor with OpenTag's
exact canonical spelling (created in Spoolman if no vendor with that exact name exists;
this is the only path in the tool that can create a vendor).  The existing vendor is
never renamed; other filaments under the old vendor are never touched.  A case-only
diff intentionally creates a near-duplicate vendor — that trade-off is accepted.

### Manual search

Each card has a **Search OpenTag manually…** link (below the field table, always
visible when the card is expanded and not ignored). Click it to open a per-card search
box. Type a keyword (e.g. "Silk Gold", "Matte Dark Blue"); results are scored against
the same brand+material context as the automatic match and rendered with confidence
badges. Clicking a result injects it as the active candidate — the field table, slug,
and confidence badge all update immediately. The injected candidate is de-duplicated
against any existing candidates so re-searching does not bloat the list.

This is useful for unmatched filaments (confidence &lt; 30%) or cases where the
automatic best match is clearly wrong.

## Apply

The Confirm step lists every pending write (old → new, grouped per filament) before
anything happens; Apply is gated behind the backup dialog. Per filament, the bridge then:

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
