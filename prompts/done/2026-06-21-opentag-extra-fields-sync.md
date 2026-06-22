---
name: 2026-06-21-opentag-extra-fields-sync
status: completed        # pending | completed | failed
created: 2026-06-21
model: opus              # research + design first, then implementation
completed: 2026-06-21
result: Phase 2 done — 7 typed OPT material extras + weight-model bonus; OPT→SM via Apply, SM↔FDB via new engine pass (inheritance + anti-ping-pong); tests + ruff green.
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

**Decisions — SIGNED OFF 2026-06-21:**
1. **Scope: the 7 material extra fields PLUS the weight-model bonus** — also populate native
   `spool_weight` from OPT container `emptyWeight` and native `weight` from package full weight
   (requires the material-slug → package → container lookup). Note: writing `spool_weight` changes
   the tare used in net↔gross weight conversion — handle that interaction carefully + anti-ping-pong.
2. **Typed fields** — register the new Spoolman extra fields as integer/float (not the legacy all-
   `text` pattern). `ensure_extra_fields` must create them with the correct `field_type`.
3. **OPT → Spoolman via the existing review/confirm Apply flow** — extend the current OpenPrintTag
   apply path (where the user reviews and confirms OPT values) to also write these new fields.
   NOT automatic each cycle. dryingTime converts OPT minutes → FDB hours (÷60) at write time.
4. **Spoolman ↔ FDB: ride the EXISTING field-sync logic** — on initial sync write the values, then
   on ongoing sync follow the same merge / one-way / conflict-resolution as the other material
   fields (the material-properties category's `direction` + `conflict_policy`). No bespoke
   precedence. MUST honor `should_skip_inherited` for FDB variants and refresh BOTH snapshots after
   any FDB write (anti-ping-pong), same as the existing scalar/temperature sync.
5. Confirm FDB `dryingTime` unit is hours (apply ÷60). Dataset check: OPT `dryingTime` sample 360
   ≈ 6 h, i.e. minutes → ÷60. Verify against FDB API once more during build.

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
