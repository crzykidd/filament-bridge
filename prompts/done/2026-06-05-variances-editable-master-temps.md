---
name: 2026-06-05-variances-editable-master-temps
status: completed
created: 2026-06-05
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-05
result: Fixed canonical-key bug (frontend now emits nozzle_temp/bed_temp/type, not raw SM names) and added editable nozzle/bed inputs on master rows; regression test added and all checks pass.
---

# Task: Editable temps on the Variances master row + fix reconcile field-key mismatch

Two changes to `frontend/src/pages/Wizard/StepVariances.tsx` (one is a bug fix that
unblocks the other):

1. **BUG FIX (do this first):** the per-group reconcile UI emits `ReconciledField.field`
   using raw Spoolman field names (`material`, `settings_extruder_temp`,
   `settings_bed_temp`), but the backend `_RECONCILE_FIELD_MAP`
   (`backend/app/api/wizard.py` ~746-753) keys on CANONICAL names
   (`type`, `nozzle_temp`, `bed_temp`, `density`, `diameter`, `spool_weight`). The
   backend does `if canonical_key not in _RECONCILE_FIELD_MAP: continue`, so reconcile
   decisions for **temps and type are silently dropped** today — they never reach FDB or
   Spoolman. The frontend must emit canonical keys.
2. **FEATURE:** make the **master** row's temps editable inline (nozzle + bed number
   inputs). Editing sets the group's canonical temp values (reconcile, source `manual`)
   which then flow to the FDB parent filament and the Spoolman write-back on execute.

## Before you start

- Read `CLAUDE.md` for conventions. SM-direction wizard only.
- Context: the master member of a variant group becomes the FDB **parent**; its shared
  property values are what variants inherit and what gets written to both systems. So the
  master row is the right place to set canonical temps.
- The reconcile plumbing (state `reconcileByGroup`, the save in `handleSave`, backend
  apply in execute/preview) already exists from commit 66d5370 — you are wiring master
  temp edits into it and fixing the key names, NOT building reconcile from scratch.

## Working tree check

`git status --porcelain` — file touched: `frontend/src/pages/Wizard/StepVariances.tsx`
(and possibly `docs/decisions.md`). Ignore unrelated untracked home-dir dotfiles. This
prompt file is exempt. No backend change is expected — the backend map is already
correct; the frontend is what's wrong.

## Verified current state (re-verify line numbers before editing)

- `computeConflicts` (~27-41) compares fields by Spoolman names: `material`, `density`,
  `spool_weight`, `settings_extruder_temp`, `settings_bed_temp`, `diameter` (and
  `material_type`).
- Reconcile state: `reconcileByGroup: Record<number, Record<string, ReconciledField>>`
  (~135), keyed `[groupIdx][field]`.
- Reconcile UI (~625-713) builds `ReconciledField` objects with `field` = the raw
  conflict field name (e.g. `settings_extruder_temp`) — THIS is the mismatch.
- `handleSave` (~315-326) flattens `reconcileByGroup` into `VariancesGroupReconcile[]`
  and POSTs via `postWizardSmVariants`.
- Master member row temps are rendered read-only (~568-572):
  `{settings_extruder_temp ?? '—'}° / {settings_bed_temp ?? '—'}°`.
- Backend canonical keys (`backend/app/api/wizard.py` ~746-753):
  `type → (type, material)`, `density → (density, density)`,
  `diameter → (diameter, diameter)`, `nozzle_temp → (temperatures.nozzle,
  settings_extruder_temp)`, `bed_temp → (temperatures.bed, settings_bed_temp)`,
  `spool_weight → (spoolWeight, spool_weight)`.

## What to do

### 1. Fix the canonical-key mapping (bug)

Add a frontend constant mapping conflict/SM field names → backend canonical keys:

```ts
const CONFLICT_FIELD_TO_CANONICAL: Record<string, string> = {
  material: 'type',
  density: 'density',
  diameter: 'diameter',
  settings_extruder_temp: 'nozzle_temp',
  settings_bed_temp: 'bed_temp',
  spool_weight: 'spool_weight',
}
```

Everywhere a `ReconciledField` is constructed (the existing reconcile-conflict UI AND
the new master-temp editor), set `field` to the CANONICAL key
(`CONFLICT_FIELD_TO_CANONICAL[rawField]`). Keep using the raw field name for *display*
labels and for keying `reconcileByGroup[groupIdx]` if you like — but the value persisted
in `ReconciledField.field` MUST be canonical so the backend applies it.

- Exclude `material_type` from reconcile entirely (it's a derived/display-only FDB field,
  not in the canonical map). If `computeConflicts` currently emits a `material_type`
  conflict that produces a reconcile row, drop it from the reconcilable set (display the
  mismatch chip only).
- Be consistent: when reading back `current` selection / dedup, use whichever key space
  you standardize on. Recommended: key `reconcileByGroup[groupIdx]` by the CANONICAL key
  to avoid double-mapping confusion, and translate the raw conflict field to canonical at
  the point you look it up.

### 2. Editable master temps

On the **master** member row only (where `isMaster` is true), replace the read-only
temps chip with two compact number inputs (nozzle and bed), e.g.
`🌡 [nozzle]° / [bed]°`, styled to match the existing orange temps chip area. Non-master
rows keep the read-only chip unchanged.

Behavior:
- The input's displayed value = the reconcile override if set
  (`reconcileByGroup[groupIdx]['nozzle_temp']?.value` / `['bed_temp']?.value`), else the
  master filament's original `settings_extruder_temp` / `settings_bed_temp`.
- On change, upsert a `ReconciledField` into `reconcileByGroup[groupIdx]` under the
  canonical key (`nozzle_temp` / `bed_temp`) with:
  `{ field: 'nozzle_temp'|'bed_temp', value: <parsed int or null>, source: 'manual',
  source_spoolman_filament_id: null }`. Parse to integer; empty input → `null` (clears to
  unset — handle so it doesn't persist `NaN`).
- These entries are picked up by the existing `handleSave` flatten + POST, and by execute/
  preview, with no backend changes — once the canonical key is correct.

Scope: temps only, master only (as requested). Do NOT make type/diameter/density editable
in this task, and do NOT add editing to standalone rows — note both as possible
follow-ups in your report.

Nice-to-have (only if low-risk): when the master's temp is overridden, have
`getLiveConflicts` compare members against the overridden value so the conflict badges
reflect the edit. If this meaningfully complicates the diff, skip it and note it.

## Conventions to honor

- `code-checkin-and-pr`: work on `dev`, conventional-commit `fix:` prefix (the headline
  is a reconcile bug fix), NO `Co-authored-by:` trailer, docs in same commit.
- Don't touch backend reconcile logic — it's correct. Don't touch weight/size logic.

## Verification

- `cd frontend && npx tsc --noEmit && npm run build` — must pass.
- Reason through: in the SUNLU PLA group, edit the master (Blue) nozzle from 185→200.
  `reconcileByGroup[groupIdx]['nozzle_temp']` = `{value:200, source:'manual', field:
  'nozzle_temp', source_spoolman_filament_id:null}`. After Save & Next, the Preview
  "Planned writes" should show FDB parent temperatures.nozzle=200 and a Spoolman PATCH
  setting settings_extruder_temp=200 on the members whose value differs. (Confirm by
  reading the preview/execute code path — the fix should make this actually happen,
  whereas before the key mismatch dropped it.)
- If wizard component tests exist, run `npm test`. Consider adding/adjusting a backend
  test asserting a reconcile decision with canonical key `nozzle_temp` produces the
  expected FDB payload + SM PATCH (the existing Phase-3 tests may have only covered
  density/diameter/spool_weight, which happened to match — temps/type were untested,
  which is why the bug slipped through). If you add a backend test, run `cd backend &&
  pytest`.

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/` (failure).
3. Record in `docs/decisions.md`: the canonical-key contract between the frontend
   reconcile UI and `_RECONCILE_FIELD_MAP` (frontend emits canonical keys), and that
   master temps are editable as manual reconcile overrides.
4. Non-interactive subagent run: when tsc/build (and any pytest you added) pass, stage
   ONLY the files this task touched (incl. the prompt move + docs) and commit on `dev`
   with one `fix:` message. Never `git add -A`. Never push.
