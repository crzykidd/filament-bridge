---
name: 2026-06-11-opentag-direct-source
status: completed
created: 2026-06-11
model: sonnet
completed: 2026-06-11
result: >
  Direct tarball fetch implemented. opentag_secondary.py deleted.
  FilamentDBClient.get_openprinttag() removed. load_opentag_dataset() no longer
  takes fdb_client. All tests updated + new _parse_tarball/_fetch_from_tarball
  fixture tests added. UI copy, docs/opentag-cleanup.md, docs/prd.md,
  README.md, and docs/decisions.md updated. 942 backend tests pass, ruff clean,
  40 frontend tests pass, tsc clean.
---

# Task: Fetch the OpenTag dataset directly from the OpenPrintTag database, not via Filament DB

User decision 2026-06-11: the OpenTag Cleanup tool must source its dataset from the
OpenPrintTag database itself, not from Filament DB's `GET /api/openprinttag` proxy feed.

## Why

- The FDB proxy adds a needless dependency (404 on older FDB, cold-fetch takes up to a
  minute while FDB extracts the tarball server-side) and its feed **drops
  `secondaryColors`** — which is why `core/opentag_secondary.py` already downloads the raw
  OpenPrintTag GitHub tarball a second time just to recover them. Going direct = one
  download, full data, no FDB coupling.
- The UI literally says "Fetching the OpenTag dataset from Filament DB…", which confused
  the user — the data is OpenPrintTag's.

## Current architecture (read first)

- `core/opentag_cache.py:load_opentag_dataset` → `FilamentDBClient.get_openprinttag()`
  (FDB feed, returns a list of denormalized OPTMaterial dicts) → merges secondary colors
  from `core/opentag_secondary.py:fetch_secondary_colors()` (raw tarball from
  `https://api.github.com/repos/OpenPrintTag/openprinttag-database/tarball/main`) → caches
  to `{DATA_DIR}/opentag_cache.json` with TTL `OPENTAG_CACHE_MAX_AGE_HOURS`.
- Consumers: `api/opentag.py` (matches endpoint builds brand/uuid indexes) and
  `core/opentag_match.py` (scorer reads `uuid, slug, brandName, name, type, abbreviation,
  color, secondaryColors, tags, optTags, density, nozzleTempMax, bedTempMax`).

## What to do

1. **New direct loader** in (or alongside) `core/opentag_cache.py`: download the raw
   tarball ONCE (reuse the URL/timeout/client pattern from `opentag_secondary.py`) and
   parse it into material dicts with **exactly the same key shape the FDB feed produced**,
   so `opentag_match.py` and `api/opentag.py` need no scoring/index changes.
   - Inspect the tarball layout: materials live under `data/materials/**/*.yaml`; brands
     under a sibling `data/brands/**` tree (verify — derive the brand name for each
     material from its YAML and/or its path, matching what FDB's `brandName` contained).
   - **Field-mapping ground truth:** the user's live cache from the FDB feed is at
     `private_data/filament-bridge/opentag_cache.json` (gitignored, readable locally).
     Compare a few entries against the same materials' raw YAML to derive the exact
     mapping (e.g. `color_rgba` → bare hex `color`, temp min/max keys → `nozzleTempMax`/
     `bedTempMax`, tag lists, `type`/`abbreviation`). Preserve value formats (hex case,
     ints vs floats) so existing UUID matches and scoring behave identically.
   - Fold in secondary colors during the same parse (the `secondary_colors[].color_rgba`
     logic from `opentag_secondary.py`); then **delete the separate
     fetch_secondary_colors merge step** (keep the module only if the wizard/engine use it
     elsewhere — grep; if unused, remove it and its tests, or repurpose its helpers).
2. **Cache semantics unchanged:** same cache file, TTL, `force` refresh, self-heal for
   malformed caches, `count`, `fetched_at`. A cache written by the old FDB-feed version
   must still load (shape is the same — that's the point).
3. **Error handling rewrite in `api/opentag.py`:** the 404 "upgrade Filament DB" and
   FDB-connection branches no longer apply. Map failures to: GitHub unreachable /
   rate-limited (502 with a clear message), timeout (504). Keep messages user-readable.
   `FilamentDBClient.get_openprinttag()` becomes unused — remove it and its tests.
4. **UI copy:** `OpenTagCleanup.tsx` status line → "Fetching the OpenTag dataset from
   OpenPrintTag…" (keep the record-count hint); the "Refresh dataset" button title says
   re-download from OpenPrintTag. Any other "from Filament DB" strings on that page.
5. **Docs:** update `docs/opentag-cleanup.md` (dataset section), `docs/prd.md` FR-23b
   dataset line, README OpenTag section step 1, and the
   `OPENTAG_CACHE_MAX_AGE_HOURS` row in `docs/configuration.md` if it mentions FDB.
   Note the deployment implication in opentag-cleanup.md: the bridge container now needs
   outbound HTTPS to `api.github.com` for this tool (it already did for secondary colors,
   so this is not a new requirement — say so).
6. **decisions.md** entry: why direct, shape-compatibility guarantee, FDB feed retired.

## Tests

- Parser: build a small fixture tarball (in-memory `tarfile` like the existing
  `opentag_secondary` tests do, if any — else create one) with 2–3 material YAMLs + brand
  data → assert the emitted dicts match the FDB-feed shape exactly (keys, hex format,
  brandName, secondaryColors populated, tags).
- Cache: TTL/force/self-heal still pass (adjust mocks from `fdb_client.get_openprinttag`
  to the new fetch seam).
- `api/opentag.py`: matches endpoint works against the new loader (existing tests
  adjusted); GitHub-failure → 502/504 paths.
- Scorer regression: the existing `opentag_match` tests must pass UNCHANGED — if any need
  edits, the shape compatibility is broken; stop and reconsider.
- Full backend suite green; frontend `npm test` + `tsc --noEmit` for the copy change.

## Working tree check

Run `git status --porcelain` first. `docker-compose.dev.yml` has an intentional
uncommitted user edit — leave it. Unrelated untracked dotfiles in the repo root — leave
them. If the opentag backend/frontend files are dirty, stop and report.

## When done

1. Update frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md` entry.
3. Propose ONE commit (`feat:` prefix, no Co-authored-by), on `dev`.
