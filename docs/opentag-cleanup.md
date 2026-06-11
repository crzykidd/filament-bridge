# OpenTag Cleanup tool

A standalone, on-demand tool that matches your Spoolman filaments against the
[OpenPrintTag](https://openprinttag.org) community database, lets you review every proposed
field, and applies canonical data — to Spoolman, and (where a record is bridge-linked) the
OpenPrintTag identity into Filament DB.

API routes live at `/api/openprinttag/*` (the bare word "opentag" is on ad-blocker filter
lists, so the routes avoid it).

## The dataset

The OpenPrintTag dataset is fetched through Filament DB's `GET /api/openprinttag` feed and
cached locally (`DATA_DIR/opentag_cache.json`, TTL `OPENTAG_CACHE_MAX_AGE_HOURS`, default
24 h). Secondary colors — which the FDB feed leaves empty — are recovered from the raw
OpenPrintTag GitHub tarball and merged in by UUID/slug; if that fetch fails the tool
degrades gracefully to the feed data.

Two buttons on the page:

- **Reprocess records** — re-scan Spoolman and re-score against the cached dataset
  (no download).
- **Refresh dataset** — force a re-download, then reprocess. The first load can take up to
  a minute (Filament DB extracts a multi-MB tarball server-side).

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

## Review

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
