---
name: 2026-06-10-synced-records-see-conflict-link
status: done
created: 2026-06-10
model: sonnet
completed: 2026-06-11
result: Implemented. conflict_id already present in backend schema and build_mapping_rows(). SyncedRecords.tsx updated to render "See conflict" button (useNavigate to /conflicts?highlight=<id>). Conflicts.tsx reads highlight param via useSearchParams, expands + highlights + scrolls to the matching row, shows not-found notice if already resolved. New tests: SyncedRecords.test.tsx (5 tests), 4 new tests in Conflicts.test.tsx. Backend 887 passed, frontend 30 passed.
---

# Task: "See conflict" deep-link from a Synced Records conflict row to that conflict in the Conflicts page

## Goal

In the Synced Records list, a row with `status === "conflict"` should show a **"See conflict"**
link/button that navigates to the Conflicts page and jumps straight to that specific conflict
(highlight + scroll-to + expand it).

## Before you start

- Read `CLAUDE.md`. This is filament-bridge.
- Backend: `backend/app/api/mappings.py` — `build_mapping_rows()` already computes per-row conflict
  ids (`conflict_id_by_sm` / `conflict_id_by_fdb`, mapping `spoolman_spool_id`/`filamentdb_spool_id`
  → first open `Conflict.id`). The `MappingRow` schema currently exposes status but (verify)
  likely not the conflict id. Look at the `MappingRow` model in `backend/app/schemas/api.py`.
- Frontend: `frontend/src/pages/SyncedRecords.tsx` (the row rendering) and
  `frontend/src/pages/Conflicts.tsx` (the target). Check how routing works (`react-router-dom`)
  and how Conflicts rows are keyed/rendered (collapsible rows by conflict id).
- `git status --porcelain` first; tree should be clean apart from an uncommitted `README.md` and
  queued prompt files (leave those). Stay within `mappings.py`, `schemas/api.py`,
  `SyncedRecords.tsx`, `Conflicts.tsx`, `api/types.ts` (and `api/client.ts` only if needed).
  Do NOT touch engine/planner/debug/wizard files.
- Standards: `code-checkin-and-pr`.

## What to do

1. **Backend** — expose the open-conflict id on each conflict-status `MappingRow`. Add
   `conflict_id: int | None` to the `MappingRow` schema and populate it in `build_mapping_rows`
   from the already-computed `conflict_id_by_sm`/`conflict_id_by_fdb` (null when not in conflict).
   Add the field to the frontend `MappingRow` type in `api/types.ts`.

2. **Frontend — Synced Records** — for rows where `status === "conflict"` and `conflict_id` is
   set, render a clear **"See conflict"** link/button (icon + label, dark-mode aware) that
   navigates to the Conflicts page targeting that id — e.g. `useNavigate()` to
   `/conflicts?highlight=<conflict_id>` (match the app's existing route path for Conflicts; check
   `App.tsx`).

3. **Frontend — Conflicts page** — on load, read the `highlight` query param (e.g.
   `useSearchParams`). If present: scroll the matching conflict row into view, visually highlight
   it briefly (e.g. a ring/flash that fades), and expand it (the page already has collapsible
   rows). Handle the case where the conflict isn't in the current (open) list — if it's already
   resolved or not found, fail gracefully (no crash; optionally a small "conflict not found / may
   be resolved" notice). Clear/ignore the param after handling so refreshes don't re-flash.

4. Match the existing dark-mode `dark:` Tailwind convention.

## Tests

- Backend (`backend/.venv/bin/python -m pytest`): assert `build_mapping_rows` populates
  `conflict_id` on a conflict-status row and leaves it null otherwise. Extend existing mappings
  tests.
- Frontend (`cd frontend && npm test`, vitest): a SyncedRecords test that a conflict row renders
  the "See conflict" link with the right target; a Conflicts test that the `highlight` param
  expands/marks the matching row (mock data). Keep light if the existing harness makes routing
  hard — at minimum cover the backend field + the link rendering.

## When done

1. Update frontmatter; `git mv` this file to `prompts/done/`.
2. `docs/decisions.md`: note the `conflict_id` on MappingRow + the highlight deep-link.
3. **Do NOT commit or push.** Leave changes in the working tree; report file-by-file summary +
   exact backend + frontend test counts.

## Tooling
- Backend venv `backend/.venv/bin/python`. npm: `NPM_CONFIG_CACHE=/home/mande/.cache/npm`.
- `bwrap: Can't mkdir .../private_data/...` → retry that command with `dangerouslyDisableSandbox: true`.
