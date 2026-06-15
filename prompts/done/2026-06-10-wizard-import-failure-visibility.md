---
name: 2026-06-10-wizard-import-failure-visibility
status: done
created: 2026-06-10
model: sonnet
completed: 2026-06-10
result: >
  Added `label` field to WizardExecuteRecord (backend schema + wizard.py + frontend types).
  All res.add() call sites now pass a human-readable label. Step6Execute shows a prominent
  red "Failed (N)" section with per-record label + error, plus a table for created/updated/skipped.
  Backend: 863 passed. Frontend: npm test blocked by permission — test file written but not run.
---

# Task: Make Bulk Import per-record failures visible in the Execute step

## Problem

When the Bulk Import Wizard execute runs, individual records can fail (e.g. FDB 409 name
collision, create/link errors). The backend already records these per record via
`res.add(db, "filament"|"spool", "failed", error=<msg>, ...)` in `backend/app/api/wizard.py`
(many call sites around lines 1167–1684). But the user reports "I can't see what is going on" —
the failure reasons are not clearly surfaced in the UI, so a re-import that fails looks like it
silently did nothing.

Goal: the Execute step must clearly show, per failed record, **what failed and why** (record
name/identifier + the error message), not just a count.

## Before you start

- Read `CLAUDE.md`. This is filament-bridge.
- Trace the execute result flow end to end before changing anything:
  - Backend: `backend/app/api/wizard.py` — the execute endpoint, the `res` accumulator object
    (find its class / `res.add(...)` definition and the response model it serializes to; the
    status mapping is near line 827: `{"created":"create","updated":"update","skipped":"skip",
    "failed":"error"}`). Confirm whether each result row carries the `error` string and a
    human-readable record label in the response payload.
  - Schema: `backend/app/schemas/api.py` — the wizard execute response model and the per-record
    result item model. Ensure the per-record item exposes `status`, a record label/name, and the
    `error` (and `detail`) text.
  - Frontend: `frontend/src/pages/Wizard/Step6Execute.tsx` — how it renders the execute result.
    Find where failures are (or aren't) shown.
- `git status --porcelain` first; tree should be clean. Do NOT touch `core/engine.py`,
  `core/planner.py`, `api/debug.py`, `api/mappings.py`, or other wizard step components — other
  prompts own those. Stay within the execute response path + `Step6Execute.tsx` (+ `api/types.ts`
  / `api/client.ts` only if the response type needs a field added).

## What to do

1. **Backend** — ensure the execute response returns, for every record, a per-record result that
   includes: `status` (created/updated/skipped/failed), a human-readable label (filament/spool
   name or id), and the `error` message (for failed) / `detail` (for skipped). If the response
   currently only returns aggregate counts (or omits the error text / label), extend the response
   model and the `res` accumulator to include them. Don't change execute *behavior* — only what it
   reports.

2. **Frontend (`Step6Execute.tsx`)** — render a clear results breakdown. At minimum:
   - A prominent **"Failed (N)"** section listing each failed record: its label + the exact error
     message (e.g. "Name collision: …", the 409 reason, etc.). Make failures visually distinct
     (red/danger styling, with `dark:` variants — match the app's dark-mode convention used in the
     other wizard steps).
   - Keep created/updated/skipped visible too (skipped should show its `detail`, e.g. "already
     linked"), but failures must be impossible to miss.
   - If the response groups by entity (filament vs spool), show both.
   - Use the existing `DeepLinks`/styling components where they fit.

3. Make sure dark mode looks right for the new sections (the rest of the wizard uses Tailwind
   `dark:` variants — see `Step2Direction.tsx` for the convention).

## Tests

- Backend (`backend/.venv/bin/python -m pytest`): if you extend the execute response model, add/adjust
  a test asserting a failed record's `error` text and label appear in the execute response.
- Frontend (`cd frontend && npm test`, runner is vitest): add a `Step6Execute` test (or extend one)
  rendering an execute result that includes a failed record, asserting the error message is shown.
- Both suites green.

## When done

1. Update frontmatter; `git mv` this file to `prompts/done/`.
2. Note in `docs/decisions.md` if you changed the execute response contract.
3. **Do NOT commit or push.** Leave changes in the working tree and report: file-by-file summary,
   exact backend + frontend test counts, and the final execute-response shape (so the next prompts
   know the contract).

## Tooling
- Backend venv: `backend/.venv/bin/python`. Frontend: `NPM_CONFIG_CACHE=/home/mande/.cache/npm`
  for npm (default `$TMPDIR` is unset → `/npmcache` is unwritable); `npm test` runs vitest.
- If a bash command fails with `bwrap: Can't mkdir .../private_data/filament-db/.claude: Permission
  denied`, retry it with `dangerouslyDisableSandbox: true` (root-owned Mongo dir, not your command).
