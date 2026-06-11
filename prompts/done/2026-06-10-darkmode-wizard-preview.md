---
name: 2026-06-10-darkmode-wizard-preview
status: done
created: 2026-06-10
model: sonnet
completed: 2026-06-10
result: Added dark: variants throughout StepNPreview.tsx — info box, stat cards, flag cards, amber banner, list text, PlannedWritesList, FlagSection, CollisionRow. Light mode unchanged. No new files created.
---

# Task: Fix dark-mode styling on the Bulk Import "Preview (dry run)" step

## Problem

The Bulk Import Wizard's Preview step (`frontend/src/pages/Wizard/StepNPreview.tsx`) renders
light-mode-only colors against the app's dark background: white stat cards, a light-yellow
warning banner, a light-gray info box, and light-gray text — none have `dark:` variants. The
rest of the wizard (e.g. `Step2Direction.tsx`) correctly uses Tailwind `dark:` variants.

## Before you start

- Read `CLAUDE.md`. This is filament-bridge; frontend uses Tailwind with `dark:` variants
  (class-based dark mode). Reference `frontend/src/pages/Wizard/Step2Direction.tsx` and other
  wizard steps for the convention (e.g. cards: `bg-white dark:bg-gray-800 border-gray-200
  dark:border-gray-700`; muted text: `text-gray-500 dark:text-gray-400`).
- `git status --porcelain` first; tree should be clean apart from an uncommitted `README.md` and
  queued prompt files (leave those). **Only** edit `frontend/src/pages/Wizard/StepNPreview.tsx`.
- Standards: `code-checkin-and-pr`.

## What to do

Add appropriate `dark:` variants throughout `StepNPreview.tsx` so the Preview step matches the
dark theme. Known light-only spots to fix (verify/clean up any others in the file):

- The info/help box (~line 104): `bg-gray-50 border-gray-200 text-gray-600` → add
  `dark:bg-gray-800/50 dark:border-gray-700 dark:text-gray-300` (or match the convention used
  elsewhere).
- The summary stat cards (~line 119): `bg-white rounded-lg border border-gray-200` → add
  `dark:bg-gray-800 dark:border-gray-700`; card label `text-gray-500` → `dark:text-gray-400`.
- The flagged/attention stat cards (~line 129): `bg-white border-amber-200` → add
  `dark:bg-gray-800 dark:border-amber-700`; labels `text-gray-500` → `dark:text-gray-400`.
- The amber warning banner (~line 137): `bg-amber-50 border-amber-200` + its text → add
  `dark:bg-amber-900/20 dark:border-amber-700` and amber text `dark:text-amber-200` (match how
  amber/warning is themed elsewhere if there's a precedent).
- The list/detail sections' text (e.g. ~lines 189, 210, 211, 235, 236): `text-gray-700` →
  `dark:text-gray-200/300`, `text-gray-500` → `dark:text-gray-400`, `text-gray-800` →
  `dark:text-gray-100/200`, and any `bg-white` row backgrounds → `dark:bg-gray-800`.
- Preserve the numeric value colors (green/blue/amber counts) — just ensure adequate contrast in
  dark mode (add a `dark:` shade only if a value is hard to read on the dark card).

Keep light-mode appearance unchanged. Don't restructure the component — only add `dark:`
classes (and adjust a base shade only where needed for contrast).

## Tests

This is presentational. Run `cd frontend && npm test` to confirm nothing broke (vitest). No new
test required, but if a quick render assertion is trivial, add one. Eyeball that every
previously light-only element now has a `dark:` counterpart (grep the file for `bg-white`,
`bg-amber-50`, `bg-gray-50`, and `text-gray-` without an adjacent `dark:`).

## When done

1. Update frontmatter; `git mv` this file to `prompts/done/`.
2. (Optional) one-line note in `docs/decisions.md` if you want, else skip — it's a styling fix.
3. **Do NOT commit or push.** Leave changes in the working tree; report the diff summary + the
   frontend test result.

## Tooling
- npm: `NPM_CONFIG_CACHE=/home/mande/.cache/npm` (default `$TMPDIR` unset → `/npmcache`
  unwritable). `bwrap: Can't mkdir .../private_data/...` → retry that command with
  `dangerouslyDisableSandbox: true`.
