---
name: 2026-06-07-matches-show-search-spoolman-id
status: completed        # pending | completed | failed
created: 2026-06-07
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-07
result: Added SM #<id> label to matched/unmatched_sm/ambiguous rows and Spoolman id to search haystack
---

# Task: Show + search the Spoolman ID on the wizard Matches step

On the wizard step-3 Matches page (`frontend/src/pages/Wizard/Step3Matches.tsx`) it's hard
to locate a single filament: the Spoolman ID isn't shown on rows, and the search box only
matches name/vendor/material/FDB-name. Add the Spoolman filament ID to the row display AND
to the search filter so the user can type the id to find one.

## What to do (frontend only)

- **Display:** in the match row (the member row that renders name/vendor/DeepLinks, ~line
  109-152), show the Spoolman filament id as a small muted label, e.g. `SM #123`, when
  `row.sm?.spoolman_filament_id` (a.k.a. `row.smId`) is present. Place it near the name or the
  DeepLinks, matching existing Tailwind styling. (FDB-only rows have no SM id — omit it.)
- **Search:** include the Spoolman id in the search haystack (the `search` filter, ~line
  322-326): add `String(r.smId ?? '')` to the joined `hay` string so typing the id (e.g.
  "123") filters to that row. Keep the existing name/vendor/material/fdb-name terms.

Keep grouping/sorting/column-filters and everything else unchanged.

## Verification

- `cd frontend && npx tsc --noEmit && npm run build` — must pass.
- Reason through: each SM-backed row now shows "SM #<id>"; typing an exact id in the search
  box narrows to that filament; FDB-only rows are unaffected.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. No docs/decisions entry needed (trivial UI add).
3. Non-interactive subagent run: when tsc/build pass, stage ONLY the files this task touched
   (incl. prompt move) and commit on `dev` with one `feat:` message. Never `git add -A`.
   Never push.
