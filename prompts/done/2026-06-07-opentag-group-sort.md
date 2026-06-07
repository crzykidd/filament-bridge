---
name: 2026-06-07-opentag-group-sort
status: completed        # pending | completed | failed
created: 2026-06-07
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-06
result: Added Group by (None/Brand/Material, default Brand) and Sort by (Confidence/Brand/Material/Name, default Confidence) controls to OpenTagCleanup review step; collapsible group sections via useMemo; tsc + build pass.
---

# Task: OpenTag cleanup — group + sort the filament matches

The OpenTag Cleanup review list is a flat list. Add grouping (by brand / material) and
sorting (by confidence / brand / material / name) to make a large match list manageable.

## Current state

`frontend/src/pages/OpenTagCleanup.tsx` renders a flat list of `FilamentCard`s from the
matches response. Each match (`OpenTagFilamentMatch`) carries `spoolman_name`,
`spoolman_vendor`, `spoolman_material`, `opt_brand`, `confidence`, plus the per-field rows.
Bulk Select all / Ignore all already exist.

## What to do (frontend only)

Add a controls row in the review header:
- **Group by:** `None` | `Brand` | `Material` (default `Brand`). When grouped, render
  collapsible group sections with a header showing the group name + count (e.g.
  "Hatchbox (7)"). Use `spoolman_vendor` for Brand and `spoolman_material` for Material;
  put empties under an "Unknown / no vendor" group.
- **Sort by:** `Confidence` (default, high→low) | `Brand` | `Material` | `Name`. Sorting
  applies within groups when grouped, or to the flat list when `Group by = None`. Provide a
  direction note where it matters (confidence defaults high→low; name/brand/material A→Z).
- Keep Select all / Ignore all working across the (re)organized list, and keep the per-card
  review/confirm/apply flow intact. Match existing Tailwind styling; groups collapsible with
  a chevron, default expanded.

Implement purely with derived/memoized state (`useMemo`) over the existing matches array —
no backend change (all needed fields are already on each match).

## Verification

- `cd frontend && npx tsc --noEmit && npm run build` — must pass.
- Reason through: group by Brand → matches cluster under vendor headers with counts; sort by
  Confidence → highest-probability first within each group; switching to Group by None → flat
  list sorted by the chosen key; Select all / Ignore all still affect every match.
- No backend change; no pytest needed unless backend touched.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md` only if non-obvious (likely skip).
3. Non-interactive subagent run: when tsc/build pass, stage ONLY the files this task touched
   (incl. prompt move) and commit on `dev` with one `feat:` message. Never `git add -A`.
   Never push.
