---
name: 2026-06-10-full-reset-both-sides
status: done
created: 2026-06-10
model: sonnet
completed: 2026-06-10
result: >
  Implemented POST /api/debug/full-reset (debug_mode-gated). Factored
  _blank_spoolman_xrefs() and _reset_bridge_tables() helpers shared by all
  three endpoints. Added FullResetResponse model. Added Full reset button in
  Settings with confirm dialog. Relabeled existing buttons with scope labels.
  Backend: 876 passed. Frontend: 21 passed (7 new Settings tests).
---

# Task: One-shot "Full reset" (bridge DB + Spoolman cross-refs together) + clarify the two existing cleanups

## Problem

Settings (Debug section) exposes two cleanup actions that each clean only ONE system, and
running one without the other leaves a half-cleaned, inconsistent state that breaks re-import:

- `POST /api/debug/clear-spoolman-fdb-refs` — blanks the three cross-ref extras on **Spoolman**
  spools only. Leaves all bridge mappings/conflicts/snapshots.
- `POST /api/debug/reset-bridge-state` — deletes the five **bridge** tables (FilamentMapping,
  SpoolMapping, Snapshot, Conflict, SyncLog) + resets `wizard_completed`. Doesn't touch Spoolman.

A user who runs only one ends up with bridge mappings pointing at deleted records, or Spoolman
links to records the bridge forgot — and the wizard then skips/fails confusingly.

Goal: add a single **"Full reset"** action that does BOTH (clear the bridge DB *and* blank the
Spoolman cross-refs), and relabel the two existing buttons so it's obvious each is one-sided.

## Before you start

- Read `CLAUDE.md` and `backend/app/api/debug.py` (both existing endpoints — note they are gated by
  `debug_mode` via `_require_debug_mode`, and `reset-bridge-state` writes NO upstream data while
  `clear-spoolman-fdb-refs` writes to Spoolman).
- `git status --porcelain` first. There may be uncommitted changes from a just-committed prior
  prompt — tree should otherwise be clean. Stay within `api/debug.py`, `schemas/api.py` (if needed),
  `frontend/src/pages/Settings.tsx`, `frontend/src/api/client.ts`, `frontend/src/api/types.ts`. Do
  NOT touch engine/planner/mappings/wizard files.
- Standards: `code-checkin-and-pr`.

## What to do

### 1. Backend — `POST /api/debug/full-reset`

Add a new gated endpoint (debug_mode required) that performs both cleanups in one call:
- Reuse the existing reset-bridge-state logic (delete the 5 tables + reset `wizard_completed`)
  and the existing clear-spoolman-fdb-refs logic (blank the three cross-ref extras on every
  Spoolman spool that has them). Factor the shared logic into helpers so the two existing endpoints
  and the new one all call the same code (no duplicated delete/blank logic).
- Return a combined response: the per-table deleted counts AND `{cleared, failed}` for the Spoolman
  side. If the Spoolman fetch/write fails, still complete the bridge-DB reset and report the Spoolman
  error in the response (don't 502 the whole thing after the local reset already ran — or run the
  Spoolman side FIRST and the local reset second; pick the order that fails safest and document it).
- Add the response model to `schemas/api.py`.

### 2. Frontend — Settings

- Add a **"Full reset (bridge DB + Spoolman links)"** button in the Debug section that calls the
  new endpoint, with a clear confirm dialog stating: it clears all bridge mappings/conflicts/
  snapshots/log, re-arms the setup wizard, AND blanks the Filament DB cross-reference fields on
  Spoolman spools — and that it does **NOT** delete any records in Filament DB or Spoolman. Show the
  combined result counts on success.
- **Relabel the two existing buttons** so their one-sided scope is obvious, e.g.:
  - "Clear Spoolman FDB refs" → **"Clear Spoolman cross-refs (Spoolman only)"**
  - "Reset bridge sync state" → **"Reset bridge DB (bridge only)"**
  and add a one-line helper under each saying what it does NOT clean, plus a note that "Full reset"
  does both. Keep behavior of the existing two unchanged.
- Add the `fullReset` client function in `api/client.ts` and its response type in `api/types.ts`.
- Match the dark-mode `dark:` convention already used in `Settings.tsx`.

## Tests

- Backend (`backend/.venv/bin/python -m pytest`): test the new endpoint — 403 when debug_mode off;
  with debug_mode on (and a mocked Spoolman client on `app.state.spoolman`), it deletes the bridge
  tables AND issues the blank-extras writes, and returns combined counts. Mirror existing debug.py
  tests if present.
- Frontend (`cd frontend && npm test`): a Settings test that the Full reset button calls the endpoint
  (mock the client) — extend existing Settings tests if any, else keep light.

## When done

1. Update frontmatter; `git mv` this file to `prompts/done/`.
2. Note the new endpoint in `docs/decisions.md` (and update `CLAUDE.md`'s debug-endpoint / runtime
   settings notes if they enumerate the debug endpoints).
3. **Do NOT commit or push.** Leave changes in the working tree; report file-by-file summary + exact
   test counts.

## Tooling
- Backend venv `backend/.venv/bin/python`. npm: `NPM_CONFIG_CACHE=/home/mande/.cache/npm`.
- `bwrap: Can't mkdir .../private_data/...` → retry that command with `dangerouslyDisableSandbox: true`.
