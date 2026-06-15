---
name: 2026-06-07-opentag-onscreen-status
status: completed
created: 2026-06-07
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-06
result: Added GET /api/openprinttag/status (no-fetch metadata) + instant dataset banner + staged fetch/match status messages in OpenTagCleanup.tsx
---

# Task: OpenTag cleanup — on-screen status (dataset state + staged progress)

The OpenTag Cleanup page can sit for ~30–60s on the first run (cold dataset fetch from FDB)
with no visible feedback. Add real on-screen status: show the dataset state instantly, and
show staged progress ("Fetching dataset…" → "Matching N filaments…") during the run. (Server
log lines already exist from the perf commit `30ecb58`.)

## Background (current behavior)

- `GET /api/openprinttag/matches` fetches the dataset if the local cache is missing/stale,
  then matches all Spoolman filaments (now fast — brand pre-filtered). The slow part is the
  one-time cold fetch (~3MB tarball via FDB).
- `POST /api/openprinttag/refresh` forces a fresh fetch and returns dataset metadata
  (`fetched_at`, `count`, `stale`). `backend/app/core/opentag_cache.py` has
  `get_cache_metadata()`.
- Frontend page: `frontend/src/pages/OpenTagCleanup.tsx`; client fns in
  `frontend/src/api/client.ts` (`getOpenTagMatches`, `postOpenTagRefresh`, `postOpenTagApply`).

## What to do

### 1. Lightweight status endpoint (backend)
Add `GET /api/openprinttag/status` in `backend/app/api/opentag.py` that returns the local
cache metadata WITHOUT fetching (use `opentag_cache.get_cache_metadata()`): `{ exists: bool,
fetched_at: str | null, count: int, stale: bool, max_age_hours: int }`. Fast and side-effect
free, so the page can render instantly. Add the response schema + client fn + types.

### 2. Frontend staged status (`OpenTagCleanup.tsx`)
- On mount: call the status endpoint and show a dataset banner — e.g. "OpenTag dataset:
  {count} materials, fetched {relative time}" or "No dataset cached yet." with the Refresh
  button. Instant, no spinner-of-doom.
- Loading flow: drive a `status` string state and show it prominently while working:
  - If the dataset is missing/stale (from the status call) OR the user clicks Refresh: set
    status "Fetching the OpenTag dataset from Filament DB… (first load downloads ~11k
    records — up to a minute)" and call `POST /openprinttag/refresh`.
  - Then set status "Matching your Spoolman filaments…" and call `GET /openprinttag/matches`.
  - If the dataset is already fresh on mount, skip the fetch stage — just "Matching your
    Spoolman filaments…" → matches.
  - Show a spinner + the current status line; on done, render the match cards and update the
    dataset banner. On error, render the backend message (keep existing error handling).
- Keep the existing review → confirm → apply flow intact; this only improves the loading UX.

## Verification

- `cd backend && pytest` — test: `GET /api/openprinttag/status` returns the metadata shape
  without triggering a fetch (assert the FDB client's `get_openprinttag` is NOT called when a
  fresh cache exists; returns `exists:false` cleanly when no cache file).
- `cd frontend && npx tsc --noEmit && npm run build` — must pass.
- Reason through: cold first run shows "Fetching dataset…" then "Matching…" then results;
  warm run skips straight to "Matching…"; the dataset banner shows count + age.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md`: added `/openprinttag/status`; the page shows dataset state + staged
   fetch/match progress (only if non-obvious).
3. Non-interactive subagent run: when pytest + tsc + build pass, stage ONLY the files this
   task touched (incl. prompt move + docs) and commit on `dev` with one `feat:` message.
   Never `git add -A`. Never push.
