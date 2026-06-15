---
name: 2026-06-05-variances-show-type-diameter-temps
status: completed        # pending | completed | failed
created: 2026-06-05
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-05
result: Member + standalone rows now show SM material type chip (blue), diameter chip (gray, with dash fallback), and nozzle/bed temp chip (orange) — no backend changes needed
---

# Task: Always show material type, diameter, and temps on every Variances row

On the wizard Variances step (Spoolman → Filament DB import), material **type** and
**diameter** (and temps) don't appear on the rows — neither variant-group members nor
standalone filaments. The user needs to see type and diameter to make grouping/reconcile
decisions. This is a display fix (mostly frontend).

## Root cause (already diagnosed — verify, don't re-investigate from scratch)

In `frontend/src/pages/Wizard/StepVariances.tsx`:
- The **type** badge renders `material_type` (`{filData.material_type && …}` ~line 554
  for members, ~line 774 for standalone). But `material_type` is sourced **only from a
  linked FDB match** — see `backend/app/api/wizard.py` ~lines 473-482, the
  `sm_to_fdb_type` map, which only fills from `wizard_match_decisions` where
  `action == "link"`. In a fresh import nothing is linked, so `material_type` is null
  everywhere and the badge is hidden. Meanwhile Spoolman's native `material` field
  (e.g. "PLA") — already populated on every `VariancesFilament` (`material=m.material` /
  `material=sm.material`) — IS the effective type for a Spoolman-origin filament.
- **diameter** renders only when `!= null` (~line 559 / ~779). If the SM filament's
  diameter is unset it silently disappears.
- **temps** (`settings_extruder_temp` / `settings_bed_temp`) are populated in the
  payload but **never rendered** — only used in `computeConflicts`.

`VariancesFilament` (frontend `frontend/src/api/types.ts` ~307-324, backend
`backend/app/schemas/api.py`) already carries `material`, `material_type`, `diameter`,
`color_hex`, `settings_extruder_temp`, `settings_bed_temp`. So no new fields are needed —
this is a rendering change. Re-verify these line numbers before editing; they may shift.

## Before you start

- Read `CLAUDE.md` for conventions. This is SM-direction wizard display only.
- Spoolman has NO `type` field — `material` is the type. FDB has `type`. So: the primary
  type shown = `material`; the FDB-matched `material_type` is only a secondary
  "differs from FDB" indicator.

## Working tree check

Run `git status --porcelain`. Files touched: `frontend/src/pages/Wizard/StepVariances.tsx`
(primary); possibly `backend/app/api/wizard.py` only if a runtime check shows diameter/
temps aren't actually populated (see step 4). Ignore unrelated untracked home-dir
dotfiles. This prompt file is exempt.

## What to do (frontend: `StepVariances.tsx`)

Apply the SAME treatment to BOTH the variant-group member row (~529-612) and the
standalone filament row (~755-826). Render a compact, scannable set of property chips on
each row (small labeled pills, consistent with existing chip styling — not tiny gray text
that's easy to miss):

1. **Type** — always render a type chip from `filData.material` (e.g. "PLA"). If
   `material` is null, show "Type: —". Drop the misleading "FDB:" prefix as the primary
   label.
   - If `material_type` (the linked-FDB type) is present AND differs from `material`,
     additionally show a small amber "FDB: {material_type}" mismatch chip next to it.
     If it matches or is null, don't show the FDB chip.
2. **Diameter** — always render a diameter chip: `{diameter} mm` when set, else
   "⌀ —" / "Diameter: —" when null. (Do not fabricate a default — show the dash so the
   user can see it's unset.)
3. **Temps** — render a temps chip showing nozzle/bed:
   e.g. "Nozzle {settings_extruder_temp ?? '—'}° · Bed {settings_bed_temp ?? '—'}°".
   Render it when at least one temp is non-null; if both are null you may omit or show
   "Temps: —" — pick the cleaner look and keep it consistent between member and
   standalone rows.

Keep the existing color swatch, hex, master badge, conflict box, and action buttons
intact. Just add the type/diameter/temps chips into the same flex-wrap header row.

## Step 4 — runtime sanity check on diameter/temps population

The schema populates `diameter`/temps from the SM filament list. Confirm the SM list
fetch the variances endpoint uses actually returns these (i.e. they're not dropped
upstream). Quick check: `SpoolmanFilament` in `backend/app/schemas/spoolman.py` has
native `diameter`, `settings_extruder_temp`, `settings_bed_temp`, and
`backend/app/services/spoolman.py get_filaments()` returns full filament objects. If the
list endpoint genuinely omits diameter (Spoolman list vs detail), and only the detail
endpoint has it, note that — but do NOT add per-filament detail fetches without flagging
it first (could be N calls). Most likely the list already includes them and the only bug
is the frontend hiding nulls. If population is fine, no backend change is needed.

## Conventions to honor

- `code-checkin-and-pr`: work on `dev`, conventional-commit `fix:` prefix (display bug),
  NO `Co-authored-by:` trailer, docs in same commit if any.
- Don't change reconcile/execute logic. Don't fabricate property values.

## Verification

- `cd frontend && npx tsc --noEmit && npm run build` — must pass.
- Reason through against the user's screenshot data: a SUNLU PLA group (members Black,
  Blue) and standalone ELEGOO/Hatchbox/STLFlix rows should each now show a "PLA" type
  chip; diameter shows "1.75 mm" if set or "—" if not; temps chip shows nozzle/bed.
- If there are component tests for the wizard, run `npm test`.

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/` (failure).
3. Record any non-obvious decision in `docs/decisions.md` (e.g. "Variances type display
   uses SM `material`; FDB-matched `material_type` shown only as a mismatch chip").
4. Non-interactive subagent run: when tsc/build pass, stage ONLY the files this task
   touched (incl. the prompt move + docs) and commit on `dev` with one `fix:` message.
   Never `git add -A`. Never push.
