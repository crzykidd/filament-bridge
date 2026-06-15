---
name: 2026-06-06-variances-show-density
status: completed        # pending | completed | failed
created: 2026-06-06
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-06
result: Added density chip (e.g. "1.24 g/cm³" / "ρ —") to variant-group member rows and standalone filament rows in StepVariances.tsx; tsc + build pass
---

# Task: Show density on every Variances row

The Variances step renders type, diameter, and temps chips on each row, and the conflict
badge can say "suggested standalone — density differ" — but the density value itself isn't
shown, so the user can't see what differs. Add a density chip to every row (variant-group
members AND standalone filaments), matching the existing chip treatment.

## Before you start

- Read `CLAUDE.md`. Frontend-only change in `frontend/src/pages/Wizard/StepVariances.tsx`.
  Work on `dev`, `fix:` prefix (display gap), no `Co-authored-by:`.
- `density` is already on `VariancesFilament` (frontend type + backend payload, used in
  `computeConflicts`). This is purely a rendering addition — no schema/backend change.

## What to do

In `frontend/src/pages/Wizard/StepVariances.tsx`, next to the existing diameter/temps
chips on BOTH the variant-group member row and the standalone filament row, add a density
chip, styled consistently with the other property chips:

- Show `{density} g/cm³` when set (e.g. "1.24 g/cm³"), and a dash (e.g. "ρ —" or
  "density —") when null — always render it so a missing value is visible (same philosophy
  as the diameter chip). Re-verify the exact chip locations against current code; mirror
  the diameter chip's markup/classes.

## Verification

- `cd frontend && npx tsc --noEmit && npm run build` — must pass.
- Reason through the screenshot case (ELEGOO Yellow PLA, "density differ"): the row now
  shows its density value chip alongside type/diameter/temps.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. No `docs/decisions.md` entry needed (trivial display addition).
3. Non-interactive subagent run: when tsc/build pass, stage ONLY the files this task
   touched (incl. the prompt move) and commit on `dev` with one `fix:` message. Never
   `git add -A`. Never push.
