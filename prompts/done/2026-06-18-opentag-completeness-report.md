---
name: 2026-06-18-opentag-completeness-report
status: done
created: 2026-06-18
model: opus              # PLAN first (field universe + your-value mapping); then implement
completed: 2026-06-18
result: >
  Shipped GET /api/openprinttag/completeness (raw-OPT-dict completeness, empty-value
  test, conditional secondaryColors, stale-tag surfacing, your-value hints) + the
  "Show missing values" report view (most-missing default sort, hide-complete toggle,
  expandable per-attribute detail, DeepLinks + opt_url slug link). Ingested-field-only
  limitation noted in UI + docs. 5 new backend tests; all four check commands green
  (backend 1123 passed + ruff clean; frontend tsc clean + 84 passed). Docs + CHANGELOG
  + decision logged in the same change. Left uncommitted for orchestrator review.
---

# Task: OpenPrintTag completeness report — "which matched records need a contribution"

A new view (the **Show missing values** toolbar action) that lists each of the user's
**matched** filaments and how complete its OpenPrintTag record is — so the user can find the
OpenPrintTag entries they should go enrich and contribute back upstream (this feeds their
`openprinttag-database` work). Depends on `2026-06-18-opentag-cleanup-landing-toolbar`.

## What this report IS (decided with the user)

- It measures **OpenPrintTag record completeness**, NOT a diff against the user's data. For
  each filament that has an applied OpenPrintTag identity, look at its OpenPrintTag record and
  report which schema attributes that record is **missing**.
- The user's own value (if we have one) is shown in the expanded detail as a "you have this to
  contribute" **hint** — but the missing-count is driven purely by the OpenPrintTag record's
  empty fields.
- **On-screen only** (no export in this pass). Sort by **brand** and by **most-missing**.

## Verified facts (from investigation — don't re-derive)

- An OpenPrintTag material is a plain `dict` (`backend/app/core/opentag_cache.py:230-256`) with
  **all 25 keys always present** on every record. So **missing = empty/null VALUE**, never an
  absent key — test `v in (None, "", [])`. (Verified live: all keys present on all 12,873
  records; e.g. the four print/bed temps are non-empty on only 470 records.)
- Resolve a tagged filament's record via the `by_uuid` index (`opentag.py:546-552`), keyed on
  the `openprinttag_uuid` extra (`:571,576`). The report iterates SM filaments with a non-empty
  `openprinttag_uuid` and looks up `by_uuid[uuid]`.
- **Inspect the RAW OPTMaterial dict directly** for completeness. Do NOT route through
  `opt_to_spoolman_fields` / `_build_candidate` — that path is lossy (strips finishes, remaps/
  drops temps, hard-codes diameter, only emits non-None fields, and omits chamber/preheat/
  drying/hardness/transmission/photo/product entirely). Those per-field helpers are for SM↔OPT
  drift, not OPT self-completeness.

## The completeness field set (FFF; identity excluded — those are always filled)

**Core (always counted when empty):** `type`, `abbreviation`, `color`, `density`,
`nozzleTempMin`, `nozzleTempMax`, `bedTempMin`, `bedTempMax`, `tags` (empty list = missing),
`photoUrl`, `productUrl`.

**Extended (counted when empty):** `chamberTemp`, `preheatTemp`, `dryingTemp`, `dryingTime`,
`hardnessShoreD`, `transmissionDistance`.

**Conditional:** `secondaryColors` — only counts as missing when the filament is **multicolor**
(SM `multi_color_hexes` present, or the OPT record's `tags` include a multicolor arrangement
like `coextruded`/`gradient`); a single-color filament legitimately has none.

**Excluded:** `uuid`/`slug`/`brandSlug`/`brandName`/`name` (identity, always present);
`completenessScore`/`completenessTier` (always null — dead, ignore).

**Known limitation to note (not fix here):** the bridge's parser does not ingest a few upstream
schema fields — `hardness_shore_a`, `heatbreak_temperature`, `max_chamber_temperature`,
typed/multiple photos. The report covers only ingested attributes; mention this in the UI/docs.
(Extending the parser is a possible separate follow-up.)

## "Your value" hint (best-effort, optional per attribute)

Where a sensible mapping exists, show the user's value next to the missing OPT attribute:
`type`←SM material, `color`←SM `color_hex`, `density`←SM density, `nozzleTempMin/Max`←SM
`settings_extruder_temp`, `bedTempMin/Max`←SM `settings_bed_temp`, `tags`←SM finish/material
tags, `secondaryColors`←SM `multi_color_hexes`. The rest (abbreviation, photo/product URL,
chamber/preheat/drying/hardness/transmission) usually have no SM source → blank hint. Blank is
fine — the headline is "OPT record lacks X."

## What to do (after the Step-0 plan)

### Backend
1. New endpoint, e.g. `GET /api/openprinttag/completeness` — load the dataset + `by_uuid`
   (reuse the matches-endpoint setup), iterate SM filaments with a non-empty `openprinttag_uuid`,
   look up the raw OPTMaterial, and compute the missing attributes per the field set above.
2. Response per filament: `{ spoolman_filament_id, brand, name, opt_slug, opt_uuid, opt_url,
   missing_count, attributes: [{ key, label, opt_value (empty), your_value (hint|null) }] }`.
   `opt_url` = the OPT record `productUrl` if present, else a link constructed from `opt_slug`
   to the OpenPrintTag site if a stable URL pattern exists, else null (UI falls back to slug).
   Skip filaments whose `uuid` isn't in `by_uuid` (stale tag) — or surface them as a distinct
   "stale match" note; state which in the plan.

### Frontend (new view under the toolbar)
3. Table columns: **Brand · Filament · OPT match (slug, linked to `opt_url`) · # missing**.
   Row expand → a small table of `attribute · your value (hint) · OpenPrintTag (—, missing)`.
4. **Sort controls:** by Brand (A→Z) and by Most-missing (desc). Default to **most-missing**.
   (Optional: brand filter.) Reuse the page's existing table/badge styling and `DeepLinks`.
5. Filaments with 0 missing either drop out or show as "complete" — recommend hiding by
   default with a toggle to show complete ones.

## Edge cases
- Untagged filaments are excluded (no OPT record to assess).
- Multicolor `secondaryColors` rule above — don't flag single-color filaments for it.
- Large brands/lots of matches: dataset is local + small (~175 SM filaments), so a single
  endpoint pass is fine; no pagination needed.

## Before you start
- Read `docs/opentag-cleanup.md`, `backend/app/core/opentag_cache.py:23-79,230-256` (the OPT
  dict shape), `backend/app/api/opentag.py:546-601` (dataset load + `by_uuid` + tagged
  resolution), and the sibling notes
  `/home/manderse/projects/homelab-configs/projects/openprinttag-database/docs/` for how
  contributions are structured (informs `opt_url` + labels).
- Compare against live data if useful: bridge SQLite / Spoolman (tagged filaments) and the
  cache `/data/opentag_cache.json` in `filament-bridge-filament-bridge-1` (use
  `docker exec … python3`; no `sqlite3` CLI in the container).

## Working tree check
`git status --porcelain`; build on the landing-toolbar view container. List anything
unexpected and ask.

## Step 0 — PLAN (required: field universe confirmation + your-value mapping + stale-tag handling)
State: the exact attribute list + labels, the multicolor rule for secondaryColors, the
your-value mapping, the `opt_url` strategy, stale-tag handling, default sort/hide-complete, and
the test matrix. Confirm ambiguities first.

## Tests
- A filament tagged to a sparse OPT record reports the correct missing set/count (empty-value,
  not absent-key); a rich record reports few/none.
- `secondaryColors` only counted for multicolor filaments.
- Identity + dead fields never counted.
- Sort by brand and by most-missing both correct; hide-complete toggle works.
- Backend `pytest` + `ruff check .`; frontend `npx tsc --noEmit` + `npm test`. All green.

## Conventions to honor
- Inspect the raw OPTMaterial directly; don't reuse the lossy field-row path for completeness.
- Doc updates ship in the SAME commit (`docs/opentag-cleanup.md` — document the report + its
  ingested-field limitation; `CHANGELOG.md` `[Unreleased]`; decision in `docs/decisions.md`).
- Conventional-commits `feat:`. No `Co-authored-by:`. Branch `dev`, never `main`, never push.

## When done
1. Frontmatter (`status`/`completed`/`result`); `git mv` to `prompts/done/`.
2. Decision logged in `docs/decisions.md`.
3. Propose ONE commit (specific paths, never `git add -A`); present list + one-liner; STOP.
   Never push. Separate commit from the other two OpenTag prompts.
