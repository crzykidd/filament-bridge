---
name: 2026-06-11-opentag-updates-review
status: completed
created: 2026-06-11
model: sonnet            # mostly frontend; one backend design decision (ignore flag persistence)
completed: 2026-06-11
result: >
  Implemented banner + updates-review view + per-filament ignore (Spoolman extra field).
  Backend: openprinttag_ignore field, has_update/ignored_updates/updates_count on matches,
  POST /api/openprinttag/ignore/{id} endpoint, 75 new tests (212 total opentag).
  Frontend: UpdatesReviewSection component, banner on main page, postOpenTagIgnore API call.
  All tests pass: pytest 725, ruff clean, tsc clean, npm test 53.
---

# Task: OpenTag cleanup — "updates available" banner + focused bulk-update review view

Independent of the new-record/conflicts/settings prompts (touches only the OpenTag cleanup
tool: `frontend/src/pages/OpenTagCleanup.tsx`, `backend/app/api/opentag.py`, schemas). Can
run any time.

## Why

On the OpenTag cleanup page, an already-tagged filament whose current OpenTag dataset values
differ from what's on the Spoolman filament is flagged (yellow). The user wants to act on
those in bulk: a top-level summary + button → a focused view of just those filaments showing
**current vs updated** values, with select-all/per-row selection, manufacturer
grouping/sort/search, and an optional **"ignore future updates"** per filament.

## Grounding (verified)

- The page already computes the differ state client-side: `OpenTagCleanup.tsx` ~line 170-195
  — `dataDiffers` = the selected candidate has a non-identity field whose
  `normalizeFieldValue(spoolman_value) !== normalizeFieldValue(opentag_value)`. There's also
  an amber "OPT" badge for already-tagged filaments (~201-225).
- "Update available" = filament **already has** `extra.openprinttag_uuid` (already linked)
  **AND** `dataDiffers` is true. (A brand-new match isn't an "update" — that's initial
  tagging.)
- The matches endpoint (`GET /api/openprinttag/matches`) returns per-field
  `spoolman_value` / `opentag_value`; the apply endpoint (`POST /api/openprinttag/apply`,
  `opentag.py:~654-790`) already writes user-selected fields to Spoolman (+ slug/uuid to FDB
  settings). Reuse apply for the bulk update — do NOT build a parallel write path.

## What to build

1. **"Updates available" summary on the main cleanup page:** a banner/stat —
   *"N filaments have updated OpenPrintTag values"* + a **Review updates** button. N = count
   of already-tagged filaments with `dataDiffers`. Compute from the existing matches data
   (client-side is fine; or add a small count to the matches response if cleaner).
2. **Focused review view** (new route/page or a filtered mode of the existing page) showing
   ONLY those filaments. For each: **current value → updated value** per changed field,
   per-row checkbox, **select all**, and a clear count of selected.
   - **Manufacturer grouping** (collapsible groups) and/or sort by a few keys
     (manufacturer, name, # changed fields) + a search box. Pick what's cleanest; grouping
     by manufacturer is the priority.
   - **Apply selected** → call the existing apply endpoint with just the selected
     filaments/fields. On success, those drop out of the "updates available" set.
3. **"Ignore future updates" per filament (optional but desired):** a per-filament action to
   suppress future update flagging. **DESIGN DECISION (call out + recommend in your work):**
   persist this where it travels with the record and is checkable on each matches run.
   Recommended: a Spoolman extra field (e.g. `openprinttag_pin` / `openprinttag_ignore`)
   storing a flag (or the pinned uuid/version), so a future dataset change won't re-flag it
   until the user un-ignores. Alternative: a bridge-local suppression table. Whichever you
   choose, the matches/“updates available” computation must exclude ignored filaments, and
   there must be a way to see/undo ignores. If the backend persistence makes this a bigger
   lift than the rest, implement the banner + focused view first and gate "ignore" behind a
   clear TODO — but prefer doing it.

## Conventions to honor

- Reuse the existing matches + apply endpoints and the `dataDiffers`/field-compare logic —
  don't duplicate. Match existing styling (ColorSwatch, badges, HelpTip).
- If you add an ignore flag, document the new Spoolman extra field in `CLAUDE.md`'s env-var
  table + `docs/spoolman-writes.md` + `docs/opentag-cleanup.md`, same commit. Update
  `docs/opentag-cleanup.md` for the new updates-review flow regardless.
- REQUIRED: `cd backend && pytest` + `ruff check`; `cd frontend && npx tsc --noEmit` +
  `npm test`. (Sandbox `itsdangerous` collection failures are env-only — ignore; no NEW
  failures.) Add/extend the OpenTag page tests.
- Conventional-commits `feat:`. No `Co-authored-by:`. Branch `dev`, never `main`, never push.

## When done

Update frontmatter; `git mv` to `prompts/done/`; log any decision (esp. the ignore-flag
storage) in `docs/decisions.md`; propose ONE `feat:` commit (specific paths, never
`git add -A`) and STOP for the user to run it. Never push.
