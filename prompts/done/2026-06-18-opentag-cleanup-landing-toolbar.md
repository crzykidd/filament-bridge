---
name: 2026-06-18-opentag-cleanup-landing-toolbar
status: done
created: 2026-06-18
model: sonnet             # focused frontend restructure
completed: 2026-06-18
result: >
  Added ToolbarView state ('idle'|'match'|'missing-values') to OpenTagCleanup. Page now
  mounts in idle with an explainer; no fetch on mount. Toolbar buttons: Refresh dataset
  (force re-download + enter match view), Match to DB (load with warm cache if available),
  Show missing values (placeholder view). Dataset-status banner always visible. Reprocess
  button moved to banner, shown only after match is loaded. All existing match-view behavior
  preserved. getOpenTagMissingValues stub added to client.ts. tsc + 84 tests green.
---

# Task: OpenTag Cleanup landing toolbar — don't auto-load; pick an action first

Today the OpenTag Cleanup page runs matching as soon as you open it (slow, and it assumes you
want to match). Change it to an **idle landing state** with a top toolbar; nothing loads until
the user picks an action. This is the foundation the other two OpenTag prompts hang off
(`2026-06-18-opentag-inline-unmatch-rematch`, `2026-06-18-opentag-completeness-report`).

## Decisions already made with the user

- Toolbar actions (left→right): **Refresh dataset**, **Match to DB**, **Show missing values**.
  - `Refresh dataset` and `Match to DB` already exist as behaviors — just move them behind
    explicit buttons instead of on-mount.
  - `Show missing values` opens the completeness report (built in the separate prompt; here
    just add the button + routing/empty-state so it's wired).
- The originally-floated "selective unmatch" button is **dropped** — unmatch is handled inline
  on the Match-to-DB view (separate prompt). (If the user later wants a matched-only list,
  it's a filter on that view, not a toolbar action.)
- Nothing is fetched on entry. The dataset-status banner may still render (it's cheap), but
  the spool match set must NOT load until "Match to DB" (or "Show missing values") is clicked.

## Before you start

- Read `docs/opentag-cleanup.md`, `CLAUDE.md` (OpenTag section), and the existing page
  `frontend/src/pages/OpenTagCleanup.tsx` in full.
- Find the current on-mount load: the `useEffect`/query that fetches `GET /api/openprinttag/matches`
  (and any reprocess/refresh/status calls — `GET /api/openprinttag/status`, the dataset
  refresh action, the existing "Reprocess records" button). The API wrappers live in
  `frontend/src/api/`.

## Working tree check

`git status --porcelain`; the tree currently carries the just-landed OpenTag dropdown/manual-
search change on `dev` (uncommitted or committed depending on order). If `OpenTagCleanup.tsx`
is dirty from that, build on top of it — do not revert it. List anything unexpected and ask.

## What to do

1. Add an **idle landing state**: when the page mounts, render the toolbar (3 buttons) + a
   short explainer + the dataset-status banner; do NOT fetch the match set.
2. Gate the existing match load behind **Match to DB** (reuse the existing matches fetch +
   reprocess logic — just trigger it on click instead of on mount). Show the existing
   match/process view once loaded.
3. Wire **Refresh dataset** to the existing dataset-refresh action.
4. Add **Show missing values** that switches to the completeness-report view. The report
   itself is built in `2026-06-18-opentag-completeness-report`; here, render a placeholder/
   empty-state (e.g. "loading…" / "no report yet") and the view container + the API call stub
   so the other prompt can fill it. Keep the view switch (toolbar selection) in component
   state.
5. Preserve all existing behavior (filters, ignore, apply, etc.) inside the Match-to-DB view —
   only the *entry* changes from auto-load to button-triggered.

## Conventions to honor

- Match the page's existing styling; reuse `HelpTip`, the dataset-status banner, button
  styles already in the file.
- Doc updates ship in the SAME commit: update `docs/opentag-cleanup.md` (the new landing flow)
  and add a `CHANGELOG.md` entry under `[Unreleased]`.
- `npx tsc --noEmit` + `npm test` green. Conventional-commits: `feat:` (or `refactor:` if you
  prefer). No `Co-authored-by:`. Branch `dev`, never `main`, never push.

## When done

1. Update this file's frontmatter (`status`, `completed`, `result`); `git mv` to `prompts/done/`.
2. Record any non-obvious decision in `docs/decisions.md`.
3. Propose ONE commit (stage specific paths, never `git add -A`); present file list + a
   one-line message and STOP for the user. Never push.
