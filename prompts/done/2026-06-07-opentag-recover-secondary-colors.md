---
name: 2026-06-07-opentag-recover-secondary-colors
status: completed
created: 2026-06-07
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-07
result: Recover OpenTag secondary_colors from raw GitHub tarball, merge into cache, colors flow as cleanup updates, multicolor_mismatch amber badge; 622 backend tests pass, frontend builds clean
---

# Task: Recover OpenTag secondary colors (FDB's feed drops them) + show colors + flag multicolor mismatch

Filament DB's OpenTag parser only reads flat `secondary_color_0..4` keys, but the OpenTag
database stores them as a `secondary_colors` ARRAY — so `secondaryColors` is EMPTY on all
12,501 records in FDB's `/api/openprinttag` feed (which the bridge consumes). Result: the
OpenTag cleanup can't bring in gradient/multicolor colors. Fix it by recovering
`secondary_colors` from OpenTag's RAW tarball and merging them into the dataset, then surface
the colors as cleanup updates and flag multicolor mismatches.

## Verified OpenTag raw schema (material YAML)

`data/materials/<brand>/<material>.yaml` has:
```yaml
uuid: ccf32809-fbef-527a-8487-ccb75ceafab6
slug: amolen-pla-silk-shiny-gradient-black-shiny-red-gold
type: PLA
secondary_colors:
- color_rgba: '#000000ff'
- color_rgba: '#98282fff'
- color_rgba: '#ddb95dff'
tags: [silk, gradual_color_change, ...]
properties: { density: 1.28 }
```
Single-color materials use `primary_color: { color_rgba: '#000000ff' }` (FDB reads that
correctly — leave primary alone). We only need to recover the `secondary_colors` ARRAY.

## Phase 1 — Recover secondary_colors from the raw tarball

- New module (e.g. `backend/app/core/opentag_secondary.py`): `fetch_secondary_colors(http)`
  → fetch `https://api.github.com/repos/OpenPrintTag/openprinttag-database/tarball/main`
  (gzipped tar, ~3MB) with a LONG timeout (e.g. 120s); untar in-memory (`tarfile` over
  `io.BytesIO`); for each member whose path contains `/data/materials/` and ends `.yaml`,
  `yaml.safe_load` it; if it has a non-empty `secondary_colors`, extract the hexes:
  `[ _rgba_to_hex(c["color_rgba"]) for c in secondary_colors if c.get("color_rgba") ]`
  where `_rgba_to_hex('#000000ff') -> '000000'` (strip '#', drop trailing alpha, uppercase,
  take first 6). Build and return `{ uuid: [hexes], ... }` (also map by `slug` as a fallback
  key). Skip entries with no uuid/slug or no secondaries. Pure-ish (takes the http client);
  handle fetch/parse errors by returning `{}` (non-fatal) + a logged warning.
- Requires `PyYAML` — add to `backend/requirements.txt` if not present.

## Phase 2 — Merge into the dataset + cache

- In `backend/app/core/opentag_cache.py` `load_opentag_dataset`: after fetching FDB's
  OPTMaterial list, call `fetch_secondary_colors` and, for each material whose
  `secondaryColors` is empty, fill it from the map keyed by `uuid` (fallback `slug`).
  Cache the MERGED dataset to `opentag_cache.json` (same staleness/force logic) so the merge
  happens once per refresh, not per request. If the raw fetch fails, proceed with FDB's feed
  unchanged (degrade gracefully).
- Update the matches metadata/log to note how many materials got secondaries recovered.

## Phase 3 — Colors flow as cleanup updates (mostly already wired)

With `secondaryColors` now populated, `opt_to_spoolman_fields`'s `if secondary:` branch
already produces `color_hex` + `multi_color_hexes` + `multi_color_direction` (via
`fdb_multicolor_to_sm`). Verify:
- Those appear as review rows (default OpenTag, keep-mine supported) and write on apply.
- The multicolor apply now sets `multi_color_direction` WITH `multi_color_hexes` (so the
  earlier direction-without-hexes 422 does NOT recur). The empty-secondaries guard from
  commit 0fef4b8 stays as a fallback for any record still lacking secondaries.
- `opt_color_profile` should treat a record with populated `secondaryColors` OR an
  arrangement tag as multicolor (it already considers tags; ensure secondaries also count).

## Phase 4 — Flag multicolor mismatch

Add a per-match flag `multicolor_mismatch: bool` to the matches response = the SM filament is
multicolor (`sm_color_profile != "single"`) while the matched OpenTag entry is NOT (no
`secondaryColors` AND no arrangement tag). Since the matcher hard-filters by profile this is
mostly relevant for the no-match case — also expose it on no-match rows (e.g. a reason like
"Spoolman is multicolor; no multicolor OpenTag match"). Frontend (`OpenTagCleanup.tsx`): show
a small amber warning badge on the filament card when `multicolor_mismatch` is true.

## Verification

- `cd backend && pytest` — tests:
  - `_rgba_to_hex('#98282fff') == '98282F'`; `fetch_secondary_colors` parses a small
    in-memory tar of sample material YAMLs into `{uuid: [hexes]}` (mock the http/tar).
  - `load_opentag_dataset` fills empty `secondaryColors` from the recovered map by uuid;
    degrades to FDB feed when the raw fetch returns `{}`.
  - a gradient material now yields `color_hex` + `multi_color_hexes` + `multi_color_direction`
    in `opt_to_spoolman_fields`, and the apply patch sets them together (no 422).
  - `multicolor_mismatch` true when SM is multicolor but the matched OpenTag entry has no
    secondaries/arrangement; false otherwise.
- `cd frontend && npx tsc --noEmit && npm run build`.
- Reason through SM #86: OpenTag now provides `[000000, 98282F, DDB95D]` (gradient) → review
  shows the colors (default OpenTag, you can keep yours) → apply writes them with the
  longitudinal direction.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md`: bridge recovers OpenTag `secondary_colors` from the raw tarball
   (FDB's feed drops them — flat `secondary_color_N` vs the `secondary_colors` array), merges
   by uuid, and flags multicolor mismatches.
3. Non-interactive subagent run: when pytest + build pass, stage ONLY the files this task
   touched (incl. prompt move + docs + requirements.txt) and commit on `dev` with one `feat:`
   message. Never `git add -A`. Never push.
