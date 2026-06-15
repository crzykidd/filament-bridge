---
name: 2026-06-07-opentag-bulk-select-ignore
status: completed        # pending | completed | failed
created: 2026-06-07
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-06
result: Added bulk "Select all" / "Ignore all" bar with live count to OpenTagCleanup review step
---

# Task: OpenTag cleanup — bulk "Select all" / "Ignore all" for filament matches

The OpenTag Cleanup page only has a per-filament "ignore match" toggle. Add bulk controls to
ignore-all / select-all (un-ignore) every filament match at once.

## Current state

`frontend/src/pages/OpenTagCleanup.tsx` tracks ignored matches in an `ignoredIds:
Set<number>` of `spoolman_filament_id`. Each `FilamentCard` has an `onIgnore(ignored)`
toggle; the confirm/apply step skips ids in `ignoredIds`.

## What to do (frontend only)

- Add a bulk-action bar in the review step header (near the dataset banner / Refresh) with:
  - **Select all** — clears `ignoredIds` (every match is selected/applied).
  - **Ignore all** — sets `ignoredIds` to ALL current match `spoolman_filament_id`s.
  - A live count, e.g. "{selected} of {total} selected" (selected = total − ignored).
- Disable/grey the bulk buttons when there are no matches. Keep the per-card ignore toggle
  working (it just adds/removes one id). Re-deriving the confirm write-list already keys off
  `ignoredIds`, so no other wiring is needed.
- Match the page's existing Tailwind styling; keep it unobtrusive.

## Verification

- `cd frontend && npx tsc --noEmit && npm run build` — must pass.
- Reason through: "Ignore all" → every card greys out, confirm shows nothing to write;
  "Select all" → all cards active again; the count updates; per-card toggle still works.
- (No backend change; no pytest needed unless you touch backend.)

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md` only if non-obvious (likely skip — trivial UI add).
3. Non-interactive subagent run: when tsc/build pass, stage ONLY the files this task touched
   (incl. prompt move) and commit on `dev` with one `feat:` message. Never `git add -A`.
   Never push.
