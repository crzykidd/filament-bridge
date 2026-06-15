---
name: 2026-06-05-variances-reconcile-execute-summary
status: completed
created: 2026-06-05
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-05
result: All 4 phases implemented — variances enrichment (material_type/diameter/color_hex), per-group reconcile UI + persistence (wizard_variances_reconcile BridgeConfig key), execute overlays canonical values on FDB create payload + SM write-back PATCH (non-fatal), planned_writes pre-flight summary in preview + UI section with All/FDB/Spoolman filter chips. 265 backend tests pass; tsc + build green.
---

# Task: Variances detail + per-field reconciliation (write both sides) + Execute pre-flight write summary

Four interlocking changes to the initial-sync wizard (Spoolman → Filament DB
direction), to be done together:

1. **Enrich the Variances step display** — show the full comparable detail set,
   including material **type** (Filament DB's `type`, which Spoolman lacks), diameter,
   and color.
2. **Per-field reconciliation on Variances** — when a variant group has a property
   variance, let the user choose which member spool's value is canonical, *or* type a
   manual override, per comparable field.
3. **Write the canonical value to BOTH systems on Execute** — the reconciled value
   seeds the new Filament DB filament *and* is PATCHed back to the Spoolman filament(s)
   so Spoolman is corrected to match. (User: "my data in spoolman is not 100% right so
   I select the spool to use as the guide and/or I update the values. this should sync
   both sides of the equation.")
4. **Execute pre-flight write summary** — before the Execute button, show one clean,
   filterable list (All / Filament DB / Spoolman) of every write that will happen.

This is a large, multi-layer change. **Do it in the phases below, in order, and run the
test suite after each backend phase.** Commit once at the end (one combined commit, per
the user's request).

## Before you start

- Read `CLAUDE.md` and `docs/prd.md` (FR-5/FR-6 wizard variances, weight model,
  variant/parent model). Read `docs/decisions.md` for the variant-inheritance and
  "resolve = record" rules.
- This is an **upstream-write feature**: Execute will now PATCH existing Spoolman
  filaments (not just create). That is consistent with the wizard's role as the
  user-enabled guided initial sync, but every such write MUST appear in the phase-4
  pre-flight summary — nothing silent.
- **Out of scope (explicitly):** spool size / 1000g-vs-2000g / `initial_weight`
  handling. Do not touch weight-size logic. Tare handling stays exactly as-is.

## Working tree check

Run `git status --porcelain`. The files this touches: `backend/app/api/wizard.py`,
`backend/app/core/planner.py`, `backend/app/schemas/api.py`,
`backend/app/services/spoolman.py` (maybe), `backend/app/core/fields.py` (read only),
`frontend/src/pages/Wizard/StepVariances.tsx`,
`frontend/src/pages/Wizard/StepNPreview.tsx`, `frontend/src/api/types.ts` +
`frontend/src/api/client.ts`, plus tests. If any have uncommitted changes, list them
and ask before editing. Ignore the unrelated untracked home-dir dotfiles in the status.
This prompt file is exempt.

## Verified current-state facts (from research — re-verify line numbers before editing)

- **Variances data**: `GET /api/wizard/variances` (`backend/app/api/wizard.py` ~line
  434-560) returns `VariancesResponse` → `VariancesGroupRow` → `VariancesFilament`
  (`backend/app/schemas/api.py` ~331-347). `VariancesFilament` currently carries
  `material, density, spool_weight, settings_extruder_temp, settings_bed_temp` (+
  `ref: FilamentRef`). It does **not** carry `type`, `diameter`, or color. Spoolman
  filament has **no `type` field** — only freeform `material` (`SpoolmanFilament` in
  `backend/app/schemas/spoolman.py` ~40-62). FDB `type` lives on the matched FDB
  filament.
- **Conflict compare** (frontend `StepVariances.tsx` ~27-41 `computeConflicts`) checks
  material, density, spool_weight, extruder temp, bed temp. Backend builds initial
  conflicts in the variances endpoint.
- **Variant decisions persistence**: there IS a POST that persists SM variant grouping
  decisions to `BridgeConfig` under key `wizard_sm_variant_decisions`
  (`set_config_value(db, "wizard_sm_variant_decisions", ...)` ~line 424). Extend this
  same persistence path for reconciled fields — do NOT invent a parallel mechanism.
  Config helpers: `get_config_value` / `set_config_value` in `backend/app/api/config.py`;
  `BridgeConfig` model in `backend/app/models/config.py`.
- **FDB create payload** is built in `backend/app/core/planner.py`
  `_fdb_filament_payload_from_sm()` (~63-96): sets name, vendor, `type` (= material,
  fallback "Unknown"), color, density, spoolWeight, and `temperatures.{nozzle,bed}`
  from `settings_extruder_temp/settings_bed_temp`. **Note it does NOT set `diameter`
  today** — add it.
- **Execute** `POST /api/wizard/execute` (~1282): Pass 1 creates masters/ungrouped,
  Pass 2 creates variants with `parentId = master_fdb_id`. Variants inherit shared
  props from the parent in FDB (one level deep). Cross-refs stored in `FilamentMapping`.
- **Write clients**:
  - FDB: `filamentdb.create_filament(payload)`, `update_filament(id, payload)`
    (`backend/app/services/filamentdb.py` ~82-161; PUT strips computed fields incl.
    `settings`, `_inherited`).
  - Spoolman: `spoolman.update_filament(filament_id, payload)` → PATCH
    `/api/v1/filament/{id}` already EXISTS (`backend/app/services/spoolman.py` ~120-124).
    Use it for the write-back. SM native settable fields: `name, material, color_hex,
    density, diameter, spool_weight, settings_extruder_temp, settings_bed_temp,
    multi_color_*`, plus `extra`.
- **Preview** `GET /api/wizard/preview` (~1188-1279) returns `WizardPreviewResponse`
  with `plan_rows: list[WizardExecuteRecord]` + flag arrays. Frontend `StepNPreview.tsx`
  renders it read-only. This is the natural home for the phase-4 write summary (it is
  literally the pre-execute review step; Execute (Step 6) immediately follows). Put the
  summary on the Preview step.

## Canonical reconcilable fields and their two-sided mapping

Reconciliation applies to **shared** variant-line properties (NOT color, which
legitimately differs per variant). Use this canonical set and mapping:

| Canonical key | FDB target            | Spoolman target           |
|---------------|-----------------------|---------------------------|
| `type`        | `type`                | `material`                |
| `density`     | `density`             | `density`                 |
| `diameter`    | `diameter`            | `diameter`                |
| `nozzle_temp` | `temperatures.nozzle` | `settings_extruder_temp`  |
| `bed_temp`    | `temperatures.bed`    | `settings_bed_temp`       |
| `spool_weight`| `spoolWeight`         | `spool_weight`            |

(Color name is display-only — see Phase 1. Do not reconcile color; the multicolor path
owns it.)

## Phase 1 — Enrich the Variances display (backend + frontend)

Backend (`schemas/api.py` + `wizard.py` variances endpoint):
- Add to `VariancesFilament`: `material_type: str | None` (the matched FDB filament's
  `type` if Step-3 matched one, else null), `diameter: float | None`, and
  `color_hex: str | None` (Spoolman `color_hex`) for display.
- In the variances endpoint, look up each SM filament's matched FDB filament (via the
  persisted match decisions / `FilamentMapping`) to populate `material_type`. If no
  match, leave null and the UI shows "—".
- Extend the backend conflict computation to also compare `diameter` and `material_type`.

Frontend (`StepVariances.tsx`):
- Render the full detail set per member row: name, vendor, color (swatch + hex), **type**,
  material, density, diameter, nozzle temp, bed temp, tare. Keep the existing
  master/variant radio + conflict badges.
- Extend `computeConflicts` to include `diameter` and `material_type`.
- Update `frontend/src/api/types.ts` `VariancesFilament` to match the new schema.

## Phase 2 — Per-field reconciliation UI + persistence

Schema (`schemas/api.py`):
- Add `ReconciledField { field: str; value: Any; source: Literal["spoolman_filament",
  "manual"]; source_spoolman_filament_id: int | None }` and a per-group
  `VariancesGroupReconcile { master_spoolman_filament_id: int; fields:
  list[ReconciledField] }`. Add a `reconcile: list[VariancesGroupReconcile]` field to
  the existing variant-decisions POST request schema (extend, don't fork).

Backend persistence:
- In the existing variant-decisions POST handler, persist `reconcile` to `BridgeConfig`
  under a new key `wizard_variances_reconcile` via `set_config_value`. (Keep
  `wizard_sm_variant_decisions` as-is.)

Frontend (`StepVariances.tsx`):
- For each group, for each canonical field that has a conflict (members disagree),
  show a small control: a chip per distinct member value (clicking selects that value
  as canonical) plus a manual-entry input ("Use custom…"). Default selection = the
  current master's value. Non-conflicting fields need no control (single value wins).
- Collect the per-group reconciled fields and include them in the payload sent by the
  existing "save variant decisions" call (or on advancing to Preview). Wire the new
  field through `frontend/src/api/client.ts` + `types.ts`.

## Phase 3 — Apply reconciled values to BOTH systems on Execute

Load `wizard_variances_reconcile` from `BridgeConfig` at the start of execute.

FDB create (in `planner._fdb_filament_payload_from_sm()` or where the payload is
finalized before `create_filament`):
- Also populate `diameter` from the SM filament (bug-fix: it's missing today).
- Overlay reconciled canonical values onto the **master/parent** filament's FDB payload,
  mapping each canonical key to its FDB target (table above; `nozzle_temp`/`bed_temp`
  nest under `temperatures`). Do NOT set these shared fields on variant-child payloads —
  let them inherit from the parent (respect FDB one-level inheritance; see
  `should_skip_inherited` rationale in `core/fields.py`).

Spoolman write-back (new, after the FDB filament for the group is created/known):
- For each SM member filament in the group (master + variants), build a PATCH payload of
  only the canonical fields whose current SM value **differs** from the reconciled value,
  mapped to the SM target column (table above; `type` → `material`). Call
  `spoolman.update_filament(sm_filament_id, payload)`.
- Skip the PATCH entirely if no field differs. Log each write to the sync log.
- These write-backs MUST be represented in the phase-4 preview summary.

Guard rails:
- Never write color via this path. Never touch the FDB `settings{}` bag.
- If a Spoolman PATCH fails, log the error and continue (don't abort the whole execute);
  surface it in the execute result.

## Phase 4 — Execute pre-flight write summary (filterable)

Backend (`wizard.py` preview endpoint + `schemas/api.py`):
- Add a structured write-op list to `WizardPreviewResponse`:
  `PlannedWrite { system: Literal["filamentdb","spoolman"]; entity_type:
  Literal["filament","spool"]; action: Literal["create","update"]; target_label: str;
  fields: list[PlannedWriteField] }` where `PlannedWriteField { name: str; old: Any;
  new: Any }` (old = null for creates).
- Populate it from the dry-run plan: FDB filament creates, FDB variant creates, FDB
  spool creates (totalWeight + cross-ref), AND the Spoolman filament write-backs computed
  by the phase-3 reconciliation logic (compute them in the dry run too, without writing).
  Reuse the same planning function execute uses so preview and execute can't diverge.

Frontend (`StepNPreview.tsx`):
- Add a "Planned writes" section: a filter toggle **All / Filament DB / Spoolman** (chip
  buttons, same style as the new Conflicts type-filter chips) and a list of write ops,
  each showing system badge, action, target label, and the field-level old→new diffs.
- Keep the existing flag-summary sections. Update `types.ts`/`client.ts` for the new
  response fields.

## Conventions to honor

- `code-checkin-and-pr`: work on `dev`, single combined commit, conventional-commit
  `feat:` prefix, NO `Co-authored-by:` trailer, docs in the same commit.
- No changes to weight/size logic. No color reconciliation. Never touch FDB `settings{}`.
- Reuse existing helpers (`get_config_value`/`set_config_value`, `get_fdb_field_value`,
  `encode/decode_extra_value`, the FilamentRef builders) rather than reinventing.

## Verification

- `cd backend && pytest` — must pass. Add tests:
  - variances endpoint now returns `material_type`/`diameter`/`color_hex`;
  - reconcile decisions persist + reload from `BridgeConfig`;
  - execute overlays reconciled values into the FDB create payload (assert payload) and
    issues the expected Spoolman `update_filament` PATCH only for differing fields (mock
    the clients, assert calls); no PATCH when values already match;
  - preview emits `PlannedWrite` entries for both systems and they match what execute does.
- `cd frontend && npx tsc --noEmit && npm run build` — must pass. Run `npm test` if the
  wizard steps have coverage.
- Manually reason through: a 3-variant group where one member has wrong density → user
  picks the correct member's density → preview shows 1 FDB filament create with that
  density + N Spoolman filament updates setting density; filtering to "Spoolman" shows
  only those.

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/` (failure).
3. Record the non-obvious decisions in `docs/decisions.md`: (a) reconciled shared props
   write to the FDB parent only and variants inherit; (b) Execute now PATCHes existing
   Spoolman filaments to correct them, surfaced in the preview write summary; (c) color
   is never reconciled; (d) spool-size/initial_weight explicitly deferred.
4. The interactive commit-approval step in `prompts/TEMPLATE.md` does not apply to a
   non-interactive subagent run: when all tests/build pass, stage ONLY the files this
   task touched (incl. this prompt move + docs) and commit on `dev` with ONE `feat:`
   message. Never `git add -A`. Never push.
