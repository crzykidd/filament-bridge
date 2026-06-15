---
name: 2026-06-08-ui-local-time
status: done
created: 2026-06-08
model: sonnet
completed: 2026-06-07
result: Created frontend/src/utils/datetime.ts with formatLocal/parseUtc. Converted all timestamp renders across Dashboard, Conflicts, SyncLog, SyncedRecords, and OpenTagCleanup to use formatLocal/parseUtc. tsc and build pass.
---

# Task: Render all timestamps in the browser's local timezone (not UTC)

The UI shows timestamps in UTC (raw ISO strings from the API). Render them in the viewer's
local timezone instead. Frontend-only.

## What to do

1. Create a shared helper `frontend/src/utils/datetime.ts`:
   - `formatLocal(value: string | null | undefined, opts?: { dateOnly?: boolean; seconds?: boolean }): string`
     — parse the ISO/UTC string and format it in the browser's local timezone via
     `toLocaleString` (date + time, e.g. `2026-06-08 10:24` style; include seconds when
     `opts.seconds`). Return `'—'` for null/empty/unparseable. Ensure UTC strings WITHOUT a `Z`
     suffix are treated as UTC (the backend emits naive-UTC in places) — append `Z` if the
     string looks like a bare ISO datetime with no timezone offset, so it converts correctly.
   - Optionally `formatRelative(value)` (e.g. "3 min ago") if trivial — not required.
2. Find every place the UI renders a timestamp and route it through `formatLocal`. Search the
   frontend for raw timestamp rendering — fields like `detected_at`, `resolved_at`,
   `created_at`, `updated_at`, `last_sync_at`, `next_sync_at`, `ts`, `timestamp`, `date`,
   `fetched_at`, `cachedAt`, and any existing `new Date(...).toLocaleString()` / `.slice(0,...)`
   /`.replace('T',' ')` patterns. Pages to check at minimum: `Dashboard.tsx`, `Conflicts.tsx`,
   `SyncLog.tsx`, `SyncedRecords.tsx`, `OpenTagCleanup.tsx` (status/cache time), and any
   component showing dates. Replace ad-hoc formatting with `formatLocal`.
3. Keep it display-only — do not change what the API returns or send-side values.

## Verification

- `cd frontend && npx tsc --noEmit && npm run build` — must pass.
- Reason through: a UTC timestamp like `2026-06-08T05:27:48` now renders in local time
  consistently across Dashboard, Conflicts, Sync Log, Synced Records.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. No docs/decisions entry needed.
3. Non-interactive subagent run: when tsc/build pass, stage ONLY the files this task touched
   (incl. prompt move) and commit on `dev` with one `feat:` message. Never `git add -A`.
   Never push.
