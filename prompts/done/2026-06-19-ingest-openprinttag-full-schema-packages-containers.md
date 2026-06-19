---
name: 2026-06-19-ingest-openprinttag-full-schema-packages-containers
status: done
created: 2026-06-19
model: opus              # PLAN first (cache-shape change + parser); then implement
completed: 2026-06-19
result: >
  Done. opentag_cache.py now parses the full supported schema: extended material
  properties (chamberTempMin/Max distinct + back-compat chamberTemp, hardnessShoreA,
  heatbreakTemperature forward-compat) and two new tarball passes → packages_by_material
  and containers_by_slug (same single download). Canonical supported-field constants
  (SUPPORTED_MATERIAL_FIELDS / SUPPORTED_PACKAGE_FIELDS / SUPPORTED_CONTAINER_FIELDS)
  exported for the report. Cache gains schema_version (CACHE_SCHEMA_VERSION=2) with a
  re-parse self-heal mirroring lexicon_version. _save_cache/_load_cache/get_cache_metadata
  carry the new keys; materials/commit_sha/fetched_at untouched. Docs (opentag-cleanup.md,
  CHANGELOG, decisions.md) updated in the same change. Tests + ruff green (1151 passed);
  live-verified against the real tarball. Deviation: heatbreak_temperature does not exist
  in the upstream dataset (mapped forward-compat → None). NOT committed — left in working
  tree for orchestrator review.
---

# Task: Ingest the FULL OpenPrintTag supported schema — material + packages + containers

The completeness report must show **every OpenPrintTag-supported field that's empty** for a
matched record. Today the parser keeps only a subset of **material** fields and drops the
**package** and **container** layers entirely — so the report both omits real gaps and
mis-reports (e.g. "Product URL missing" when the URL exists at the package level). This task
makes the dataset cache carry the complete supported schema. (Enabling step for
`2026-06-19-rebuild-openprinttag-missing-report`.)

## Verified facts (from investigation)

- Parser `backend/app/core/opentag_cache.py:_parse_tarball` (~`:152-278`) reads only
  `data/brands/` + `data/materials/`. The OPTMaterial dict (~`:245-271`) **drops** these
  upstream material `properties` keys: `hardness_shore_a`, `heatbreak_temperature`,
  `max_chamber_temperature` (chamber collapsed to one value), plus multiple/typed photos and
  the material-level `url` vs package `url` distinction.
- The tarball ALSO contains (currently never opened):
  - `data/material-packages/` — ~3,667 docs. Fields seen: `slug`, `class`, `material.slug` (FK),
    `nominal_netto_full_weight` (net g), `filament_diameter` (µm), `uuid`, `gtin`,
    `container.slug` (FK), `url` (variant/product URL), `brand_specific_id` (**the SKU**),
    `filament_diameter_tolerance`. Example `material-packages/elegoo/elegoo-pla-red-1kg.yaml`:
    `brand_specific_id: SPUS-EL-3D-P06`, `url: …?variant=…`, `nominal_netto_full_weight: 1000`,
    `filament_diameter: 1750`, `container.slug: elegoo-cardboard-spool-1kg`. (ELEGOO packages
    have NO `gtin` — a real contributable gap; other brands do.)
  - `data/material-containers/` — ~79 docs. Fields: `uuid`, `slug`, `name`, `class`, `brand`,
    `empty_weight` (tare g), `outer_diameter`, `inner_diameter`, `hole_diameter`, `width`.
    Example `elegoo-cardboard-spool-1kg.yaml`: `empty_weight: 154`, `outer_diameter: 200`,
    `hole_diameter: 54`, `width: 65`.
- Cache file shape + `LEXICON_VERSION`/self-heal docs are in `opentag_cache.py:15-79`; cache
  written by `_save_cache` (~`:331`); the dataset commit-SHA gate + `fetched_at` live there too.

## What to do (after the Step-0 plan)

1. **Capture the full material schema.** Extend the material parse so the OPTMaterial dict carries
   ALL upstream `properties` keys (add `hardness_shore_a`, `heatbreak_temperature`,
   `max_chamber_temperature`; stop collapsing chamber) plus the material-level `url`. Keep
   existing key names/back-compat; only ADD. Existing consumers (matcher, completeness) keep
   working.
2. **Parse packages** into a new cache key, e.g. `packages_by_material: {material_slug: [ {slug,
   uuid, gtin, brand_specific_id (SKU), url, nominal_netto_full_weight, filament_diameter,
   filament_diameter_tolerance, container_slug}, … ]}` (a material has 1→N packages).
3. **Parse containers** into `containers_by_slug: {slug: {uuid, name, class, brand, empty_weight,
   outer_diameter, inner_diameter, hole_diameter, width}}`.
4. **Define the canonical "supported field" schema** (material + package + container) somewhere
   reusable (e.g. a module constant) so the report (next prompt) checks emptiness against the
   exact supported set. This is the source of truth for "all fields supported".
5. **Cache versioning/self-heal:** the new keys change the cache shape — bump the cache schema
   version (mirror the `LEXICON_VERSION` self-heal pattern) so existing caches re-parse cleanly.
   `_save_cache`/`_load_cache`/`get_cache_metadata` carry the new keys. Existing `materials`/
   `commit_sha`/`fetched_at` untouched.

## Notes / edge cases
- Packages/containers are separate YAML docs keyed by `material.slug` / `container.slug` — build
  the indexes during the same tarball pass; don't add a second download.
- `container.empty_weight` is the **spool tare** — note it as a possible future win for the weight
  model, but OUT OF SCOPE here (just ingest it).
- Don't change the matcher's behavior; it can keep using the existing material fields.

## Before you start
Read `backend/app/core/opentag_cache.py` in full, `CLAUDE.md` (OpenTag section), and the
homelab-configs note `projects/3dprinting/docs/filament-db-ecosystem.md` if useful. Inspect the
live cache/tarball for exact field shapes (`docker exec filament-bridge-filament-bridge-1
python3 …`; no sqlite3 CLI).

## Working tree
`git status --porcelain`; build on current `dev`. List anything unexpected; ask.

## Step 0 — PLAN (required: cache-shape change + supported-schema definition)
State the new cache keys + shapes, the supported-field schema constant, the version-bump/self-heal,
and the test matrix. Confirm ambiguities first.

## Tests
- Packages/containers parsed: `packages_by_material['elegoo-pla-red']` has the 1kg package with
  `brand_specific_id='SPUS-EL-3D-P06'`, `url` set, `gtin` empty; container index has
  `elegoo-cardboard-spool-1kg` with `empty_weight=154`.
- Full material schema present (e.g. a record with `hardness_shore_d` set parses it; chamber
  min/max distinct).
- Cache self-heals from an old-shape file (version bump triggers re-parse).
- `cd backend && .venv/bin/python -m pytest -q && .venv/bin/ruff check .` green; frontend
  unaffected.

## Conventions / when done
Doc updates same commit (`docs/opentag-cleanup.md` data-model note, `CHANGELOG.md` `[Unreleased]`,
`docs/decisions.md`). Conventional-commits `feat:`. No `Co-authored-by:`. Branch `dev`, never
`main`, never push. Update frontmatter, `git mv` to `prompts/done/`, propose ONE commit, STOP.
