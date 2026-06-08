---
name: 2026-06-08-synclog-windows-delete
status: done
created: 2026-06-08
model: sonnet
completed: 2026-06-07
result: Implemented windows param + DELETE endpoint on backend; view selector, cycle grouping, clear button on frontend. 685 backend tests pass, frontend build clean.
---

# Task: Sync Log — show all / last N sync windows + clear-log

The Sync Log is hard to read. Add the ability to view by sync WINDOW (cycle) and to clear the
log. (Time-based retention + scheduler rotation are a SEPARATE later job — not here.)

## Backend (`backend/app/api/sync_log.py`)

A "sync window" = one sync cycle (`cycle_id`). Add:
1. A `windows: int | None` query param to `GET /sync-log`: when set, return only the log
   entries belonging to the most recent N distinct `cycle_id`s (newest cycles first; entries
   within still newest-first). Implement by selecting the most recent N distinct cycle_ids
   (by max timestamp) then filtering. When `windows` is None, behave as today (limit/offset).
   Note: some entries may have a null `cycle_id` (e.g. wizard/opentag) — treat each null as not
   belonging to a cycle window (exclude from window filtering, or group under "manual"); pick
   the simpler correct behavior and note it.
2. `DELETE /sync-log` — clears all SyncLog rows; returns `{deleted: <count>}`. (Used by the
   "Clear log" button.)
3. Optionally include the distinct recent cycle list / count in the response if trivial for the
   UI to label windows — only if easy.

## Frontend (`frontend/src/pages/SyncLog.tsx` + client/types)

- Add a view selector: **All** / **Last 10 windows** / **Last 25 windows** (drives the
  `windows` param; "All" uses the existing limit/offset pagination).
- Group/label entries by sync window (cycle) with a small header per cycle (cycle's time +
  entry count) so a "window" is visually distinct — keep it lightweight.
- Add a **"Clear log"** button (with a confirm) → `DELETE /sync-log` → refresh.
- Keep the existing entity_type/direction/action filters and local-time formatting
  (`formatLocal`) intact.
- `client.ts`: add `clearSyncLog()` and the `windows` param to `getSyncLog`.

## Verification

- `cd backend && pytest` — tests: `windows=N` returns only entries from the most recent N
  cycle_ids; `DELETE /sync-log` removes all rows and returns the count.
- `cd frontend && npx tsc --noEmit && npm run build`.
- Reason through: selecting "Last 10 windows" shows the last 10 cycles grouped; "Clear log"
  empties it after confirm.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. No docs/decisions entry needed unless non-obvious.
3. Non-interactive subagent run: when pytest + build pass, stage ONLY the files this task
   touched (incl. prompt move). Use a PATHSPEC-SCOPED commit (a parallel agent edits OTHER
   files — Conflicts.tsx/conflicts.py/ColorDisplay.tsx — concurrently; never `git add -A`).
   `feat:` message. Retry once on index lock. Never push.
