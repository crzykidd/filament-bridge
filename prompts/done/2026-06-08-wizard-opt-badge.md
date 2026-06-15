---
name: 2026-06-08-wizard-opt-badge
status: done
created: 2026-06-08
model: sonnet
completed: 2026-06-07
result: Added OptBadge component and rendered it on matched/unmatched_sm/ambiguous rows where r.sm?.openprinttag === true. tsc and build passed.
---

# Task: Bulk Import Wizard — show an OpenPrintTag badge on tagged rows

The wizard match step already has an `openprinttag` boolean on each SM-backed row (added with
the "OpenPrintTag-tagged only" filter). Surface it visually with a small badge on the row, the
same idea as the OpenTag Cleanup page's "OPT" badge, so the user can see which filaments are
already OpenPrintTag-tagged.

## What to do (frontend only — `frontend/src/pages/Wizard/Step3Matches.tsx`)

- For each match row whose SM filament has `openprinttag === true` (i.e. `r.sm?.openprinttag`),
  render a small **"OPT"** badge (a tag/chip) inline near the name / SM-id, consistent with the
  existing row styling and similar to the cleanup page's badge (a compact pill, e.g.
  `bg-gray-100 text-gray-500 border-gray-200` with a small tag glyph, `title="OpenPrintTag
  tagged"`). FDB-only rows (no SM side) get no badge.
- Keep the existing "OpenPrintTag-tagged only" filter, search, grouping, and the SM-id display
  intact.

## Verification

- `cd frontend && npx tsc --noEmit && npm run build` — must pass.
- Reason through: rows for OpenPrintTag-tagged filaments now show the OPT badge; untagged and
  FDB-only rows don't.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. No docs/decisions entry needed.
3. Non-interactive subagent run: when tsc/build pass, stage ONLY the files this task touched
   (incl. prompt move) and commit on `dev` with one `feat:` message. Use a PATHSPEC-SCOPED
   commit (a parallel agent edits OTHER files concurrently; never `git add -A`). Retry once on
   index lock. Never push.
