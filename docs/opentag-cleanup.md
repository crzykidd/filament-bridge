# OpenTag Cleanup tool

A standalone, on-demand tool that matches your Spoolman filaments against the
[OpenPrintTag](https://openprinttag.org) community database, lets you review every proposed
field, and applies canonical data — to Spoolman, and (where a record is bridge-linked) the
OpenPrintTag identity into Filament DB.

API routes live at `/api/openprinttag/*` (the bare word "opentag" is on ad-blocker filter
lists, so the routes avoid it).

## The dataset

The OpenPrintTag dataset is fetched directly from the
[OpenPrintTag GitHub tarball](https://github.com/OpenPrintTag/openprinttag-database) and
cached locally (`DATA_DIR/opentag_cache.json`, TTL `OPENTAG_CACHE_MAX_AGE_HOURS`, default
24 h). Brand names, material properties, and secondary colors are all parsed in a single
tarball download — no Filament DB involvement. Only `class: FFF` materials are included
(SLA and others are skipped).

Two buttons on the page:

- **Reprocess records** — re-scan Spoolman and re-score against the cached dataset
  (no download).
- **Refresh dataset** — force a re-download from OpenPrintTag, then reprocess. The first
  load downloads and parses a multi-MB tarball (typically a few seconds).

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
5. **Scoring** (sums to 1.0): material match 0.20, brand 0.20, color-*name* similarity
   0.25 (+0.05 when both names reduce to the same base color via the **Color word
   mappings** — "Jet Black" and "Galaxy Black" both → black), color-*hex* proximity up to
   0.15, finish-tag agreement ±0.15 (a silk vs matte mismatch is penalized).

Matches below 30% land in the **unmatched** list with a reason (unknown manufacturer, no
material for that brand, multicolor with no multicolor candidates, or simply no confident
match). Fix unknown manufacturers by adding a mapping in Settings, then Reprocess.

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

## Review (full review view)

Each filament card shows the best candidate (★) and up to five alternates in a dropdown,
with a field-by-field table: current Spoolman value vs the OpenTag value. Per field you can
edit the proposed value or mark it **keep mine**; per filament you can **ignore** the match
entirely. Group by brand/material, sort, and filter (hide matched / hide already-tagged) to
work through a large library; "Ignore all" works per group.

Badges: a grey **OPT** chip means the filament is already tagged and in sync with the
candidate; amber means it's tagged but the data has drifted; a **multicolor mismatch** chip
warns when Spoolman has multicolor data but the candidate is single-color.

The **Manufacturer** row only appears when the Spoolman vendor and the OpenTag brand
actually differ — accepting it re-points the filament to the right vendor (created in
Spoolman if needed; this is the only path in the tool that can create a vendor).

## Apply

The Confirm step lists every pending write (old → new, grouped per filament) before
anything happens; Apply is gated behind the backup dialog. Per filament, the bridge then:

1. PATCHes the confirmed fields to Spoolman (multicolor writes always pair
   `multi_color_hexes` with a direction; `color_hex` is never sent alongside them),
2. writes `openprinttag_slug` / `openprinttag_uuid` extras, and
3. merges the same two identity keys into the linked Filament DB filament's `settings{}`
   bag (the approved scoped exception — all other settings keys are preserved).

Errors are per-filament; one failure never aborts the batch. The ongoing sync engine keeps
the identity keys flowing afterwards, so a filament cleaned here looks identical to one
imported from OpenPrintTag directly.
