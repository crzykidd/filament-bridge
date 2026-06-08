---
name: 2026-06-08-cleanup-filter-and-expand-fix
status: done
created: 2026-06-08
model: sonnet
completed: 2026-06-07
result: Implemented expand fix (groupBy=none always collapsed=false) and two filter toggles (hideMatched, hideAlreadyTagged) applied before withMatch/noMatch split. tsc and build pass.
---

# Task: OpenTag cleanup — fix group-by-None expand + add hide-matched/hide-tagged filters

Frontend-only (`frontend/src/pages/OpenTagCleanup.tsx`).

## 1. Fix the group-by-None "can't expand" bug

When `groupBy === 'none'`, the single group is rendered with `showHeader={false}` (no clickable
header) BUT `collapsed={collapsedGroups[''] ?? true}` defaults to collapsed — so the flat list
renders nothing and there is no header to expand it. Fix: when there is no header
(`showHeader === false`), the group must ALWAYS be expanded. Either pass
`collapsed={groupBy === 'none' ? false : (collapsedGroups[group.key] ?? true)}`, or in
`MatchGroup` render the member cards when `!collapsed || !showHeader`. (Brand/material grouping
keeps its collapse-by-default behavior — those have headers.)

## 2. Add filters: "Hide matched" and "Hide already-tagged"

Add two filter toggles (checkboxes/segmented control) near the existing group/sort controls,
so the user can work the list down in stages:
- **Hide matched** — hides rows that found an OpenTag match (`m.opt_uuid != null` /
  `confidence >= 0.30`), leaving the no-match rows.
- **Hide already-tagged** — hides rows whose Spoolman filament already has an
  `openprinttag_uuid` (reuse the existing `getExistingUuid(...)` helper used by the badge /
  group "tagged" count).

Apply both to the `matches` list BEFORE it is split into `withMatch`/`noMatch` and grouped, so
the grouped display, the no-match `<details>` section, and the group count summaries all
reflect the filter. Default both OFF (show everything). Persist in component state only.

Keep it unobtrusive and match the existing Tailwind styling of the group/sort row. Update the
header counts line ("N matches found, M unmatched, K ignored") to reflect the filtered view, or
add a note that a filter is active — whichever is cleaner.

## Verification

- `cd frontend && npx tsc --noEmit && npm run build` — must pass.
- Reason through: group-by None now shows the flat list immediately (expanded); "Hide matched"
  collapses the matched groups away leaving only no-match rows; "Hide already-tagged" removes
  rows that already carry an openprinttag_uuid; toggling both off restores the full list.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. No docs/decisions entry needed (UI-only).
3. Non-interactive subagent run: when tsc/build pass, stage ONLY the files this task touched
   (incl. prompt move) and commit on `dev` with one `feat:` message. Use a pathspec-scoped
   commit (commit only those paths); if git hits an index lock, wait ~5s and retry once. Never
   `git add -A`. Never push.
