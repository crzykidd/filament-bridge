---
name: 2026-06-21-opentag-extra-fields-sync
status: pending          # pending | completed | failed
created: 2026-06-21
model: opus              # research + design first, then implementation
completed:
result:
---

# Task: Spoolman extra fields for OpenPrintTag settings → sync the FDB-supported ones

**DO NOT EXECUTE YET.** Sequencing (user decision 2026-06-21): ship the release-notes
Markdown fix and cut a release FIRST; this OpenPrintTag-extra-fields work lands in the
release AFTER that. This file is the plan to pick up then.

## Goal

OpenPrintTag carries many standardized material settings. Spoolman natively tracks only
some of them (temps, density, diameter, spool_weight, multi-color, etc.). For the
OpenPrintTag settings Spoolman does NOT natively track, create Spoolman **extra fields**
so those values live in Spoolman, then extend the sync so the bridge writes the subset
that **Filament DB supports** into FDB during sync. Net effect: a filament tagged in
OpenPrintTag ends up with its full standardized settings represented in Spoolman and
mirrored into Filament DB.

## Before you start (read these)

- `docs/prd.md` (sync model, FRs), `docs/spoolman-writes.md` (every field the bridge
  writes to Spoolman today, and when), `docs/configuration.md` (env-var + extra-field
  conventions), `docs/opentag-cleanup.md`, `docs/sync-model.md`.
- `backend/app/core/opentag_cache.py` — `SUPPORTED_MATERIAL_FIELDS` /
  `SUPPORTED_PACKAGE_FIELDS` / `SUPPORTED_CONTAINER_FIELDS` (the full OPT field set the
  audit already enumerates) and the parsed OPT data shapes.
- `backend/app/core/opentag_match.py` / `app/api/opentag.py` — how OPT data maps onto
  Spoolman fields today (the apply flow), and the `openprinttag_slug`/`uuid` identity.
- `backend/app/services/spoolman.py` — `ensure_extra_fields()` (how the bridge creates
  required Spoolman extra fields on startup) and the extra-field write path.
- `backend/app/core/fields.py` — field-mapping resolution (auto-match + explicit
  `FIELD_MAPPINGS`); `backend/app/core/engine.py` — where filament fields are synced.
- `backend/app/services/filamentdb.py` + FDB API docs — which fields/settings FDB
  actually supports writing (incl. the `settings{}` passthrough — but respect the
  scoped-write rule in CLAUDE.md: only the two OpenTag identity keys may touch
  `settings{}`; new structured fields go on first-class FDB fields, not the bag, unless
  the user explicitly approves otherwise).

## Phase 1 — research & propose (no code; get sign-off)

1. Build a 3-column matrix: **OpenPrintTag field → Spoolman (native? extra? none) →
   Filament DB (supported field? none)**. Use `SUPPORTED_*_FIELDS` as the OPT column.
2. Derive the target set: OPT fields that **FDB supports** AND Spoolman does **not**
   natively track. Those are the new Spoolman extra fields to create. (OPT fields FDB
   can't store are out of scope; OPT fields Spoolman already tracks natively need no
   extra field.)
3. For each target field propose: extra-field `name` (follow the existing
   `SPOOLMAN_FIELD_*` env-var override pattern + a sensible default key), Spoolman extra
   field **type** (text/integer/float/choice), the OPT source path, and the FDB target
   field. Note units / value conversions.
4. Decide sync direction & precedence per field (OPT/Spoolman → FDB is the primary
   direction here) and how it interacts with the existing two-axis direction/conflict
   policy and anti-ping-pong snapshot rules. Flag any field where a conflict policy is
   needed.
5. Write the proposal into `docs/decisions.md` (or a docs/ design note) and PAUSE for
   user review before Phase 2.

## Phase 1 findings & proposal (completed 2026-06-21 — awaiting sign-off)

Sources: `core/opentag_cache.py:178-223` (SUPPORTED_*_FIELDS), `core/fields.py:17-31`
(`FDB_SYNCABLE_FIELDS` — the writable FDB allow-list), `schemas/spoolman.py` (native fields),
`core/opentag_match.py:417-568` (`opt_to_spoolman_fields` — what's already consumed),
`docs/spoolman-writes.md`. **Key constraint:** the OPT data the bridge consumes today is all
*material-level*; package/container dicts are cached but only read by the completeness audit, so
package/container fields need a new material-slug→package→container lookup before they can sync.

**Proposed NEW Spoolman extra fields** (OPT material fields FDB can store but Spoolman lacks
natively & we don't sync yet). Coverage = # of OPT materials populating it (of ~13k):

| key (env-overridable `SPOOLMAN_FIELD_*`) | OPT source | FDB target (writable) | coverage | conversion |
|---|---|---|---|---|
| `openprinttag_nozzle_temp_min` | `nozzleTempMin` | `temperatures.nozzleRangeMin` | 662 | °C int |
| `openprinttag_nozzle_temp_max` | `nozzleTempMax` | `temperatures.nozzleRangeMax` | 662 | °C int (also feeds native `settings_extruder_temp` today) |
| `openprinttag_drying_temp` | `dryingTemp` | `dryingTemperature` | 329 | °C |
| `openprinttag_drying_time` | `dryingTime` | `dryingTime` | 329 | **OPT minutes → FDB hours (÷60)** — sample 360=6h |
| `openprinttag_hardness_shore_a` | `hardnessShoreA` | `shoreHardnessA` | 682 | numeric |
| `openprinttag_hardness_shore_d` | `hardnessShoreD` | `shoreHardnessD` | 164 | numeric |
| `openprinttag_transmission_distance` | `transmissionDistance` | `transmissionDistance` | 125 | mm float |

Out of scope (no FDB home / settings-only): abbreviation, bed/chamber min, preheatTemp,
heatbreakTemperature (always null), photoUrl, productUrl, all package geo + container geo fields.
Already native/synced: type, color, secondaryColors, density, bedTempMax, diameter, tags, etc.

**High-value follow-up (separate, NOT new extra fields):** OPT container `emptyWeight`→native
`spool_weight`→FDB `spoolWeight`, and package `nominalNettoFullWeight`→native `weight`. These are
native Spoolman targets (no extra field) but aren't populated from OPT today and need the
package/container lookup. Better weight-model accuracy; decide separately.

**Decisions needed before Phase 2 (USER SIGN-OFF):**
1. Approve the 7-field set above (add/drop any)?
2. Extra-field **type**: keep the existing all-`text` pattern (JSON-encoded) or introduce typed
   integer/float fields? (All current bridge extras are `text`.)
3. **Write entry point**: populate via the explicit OpenTag **Apply** flow (review/confirm —
   recommended, matches current OPT behavior) or automatically each sync cycle (`_sync_opentag_identity`)?
4. **Direction/precedence**: ride the existing material-properties category (obeys its
   direction/conflict policy) or a new category? OPT-wins silently or surface a conflict when FDB
   was manually edited? Honor `should_skip_inherited` for variants + the both-snapshots refresh
   (anti-ping-pong) on every FDB write.
5. Confirm FDB `dryingTime` unit is hours (apply ÷60) before mapping.

## Phase 2 — implement (after Phase-1 sign-off)

1. Add the new extra-field definitions + `SPOOLMAN_FIELD_*` env vars (defaults in
   `app/config.py`, documented in `docs/configuration.md` and CLAUDE.md's env table).
2. Extend `ensure_extra_fields()` to create the new fields on startup (and surface a
   health warning if creation fails, matching existing behavior).
3. Populate the fields from OpenPrintTag in the OPT apply flow (and/or the
   `_sync_opentag_identity` pass) so Spoolman holds the OPT values.
4. Extend the sync engine + `core/fields.py` mapping so the FDB-supported subset writes
   to Filament DB during sync, honoring direction/conflict policy and refreshing BOTH
   snapshots after a write (anti-ping-pong).
5. Update `docs/spoolman-writes.md` (new fields + when written), `docs/configuration.md`,
   CLAUDE.md env table, and add a `CHANGELOG.md` `[Unreleased]` entry.

## Conventions to honor

- Extra-field names configurable via env (`SPOOLMAN_FIELD_*`) with defaults — match the
  existing identity/material-tags field pattern exactly.
- Never write to FDB `settings{}` except the approved OpenTag identity keys (CLAUDE.md).
- Check extra fields exist before writing; never assume.
- Tests: unit tests for the field matrix/mapping + an engine test that a tagged filament
  propagates the new fields to FDB. Run `ruff check backend/` and `pytest`; `tsc` +
  `vitest` if any UI surfaces the fields.

## When done

1. Update frontmatter (`status`, `completed`, `result`); `git mv` to `prompts/done/`.
2. Record decisions in `docs/decisions.md`.
3. Do NOT commit/push — leave for the orchestrator/session owner to review and commit on
   `dev` per the user's standing rule.
