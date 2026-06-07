---
name: 2026-06-06-fix-opentag-refresh-timeout-errors
status: completed        # pending | completed | failed
created: 2026-06-06
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-06
result: Renamed /opentag/* → /openprinttag/* routes; added 120 s FDB timeout; structured 504/502 fetch errors; frontend loading state; all tests pass.
---

# Task: Fix OpenTag cleanup refresh — rename ad-blocker-blocked path; long timeout + errors

## Root cause (confirmed from the browser console)

The refresh/matches requests fail with `net::ERR_BLOCKED_BY_CLIENT` — the user's ad blocker
blocks any URL containing the token **`opentag`** (it collides with the "Qubit OpenTag" web
analytics product, which EasyList/uBlock filter lists block). Our API routes
`/api/opentag/matches|refresh|apply` match that filter and are killed in the browser before
they reach the backend — hence "Failed to fetch" with NOTHING in the bridge log.

## Primary fix — rename the API path off the blocked token

Rename the bridge's OpenTag cleanup API routes from `/opentag/...` to **`/openprinttag/...`**
(the string `openprinttag` does NOT contain the blocked `opentag` substring, and FDB already
serves `/api/openprinttag` through the same ad blocker, so it's proven safe):

- Backend `backend/app/api/opentag.py`: change the route decorators
  `/opentag/matches` → `/openprinttag/matches`, `/opentag/refresh` →
  `/openprinttag/refresh`, `/opentag/apply` → `/openprinttag/apply`. (The router is mounted
  with prefix `/api`, so full paths become `/api/openprinttag/...`.)
- Frontend `frontend/src/api/client.ts`: update `getOpenTagMatches`, `postOpenTagRefresh`,
  `postOpenTagApply` to the new paths.
- Keep the frontend SPA route (`/opentag-cleanup`) and component names as-is (a client-side
  route is not a network request, so it isn't blocked) — though renaming it to
  `/openprinttag-cleanup` for consistency is fine if trivial. Function/type names can stay.
- Grep for any other references to the old `/opentag/` API paths and update them.

## Secondary fix — slow-fetch hardening (the cold fetch is genuinely slow)

Even unblocked, the first fetch downloads FDB's ~3MB tarball (20–60s). Make it robust:
1. `filamentdb.get_openprinttag()`: use a long per-request timeout (do NOT change the global
   15s): `await self._http.get("/api/openprinttag", timeout=httpx.Timeout(120.0))`.
2. `opentag_cache.load_opentag_dataset` / the endpoints: wrap the FDB fetch and map failures
   to clear `api_error(...)` (see `app/api/errors.py`) so the UI shows a real message:
   - `httpx.TimeoutException` → 504 `opentag_fetch_timeout` ("Timed out fetching the OpenTag
     dataset from Filament DB — it downloads a large file on first load; try again.")
   - 404 `httpx.HTTPStatusError` → 502 `opentag_unavailable` ("This Filament DB version
     doesn't expose /api/openprinttag — upgrade Filament DB.")
   - other `httpx.HTTPStatusError`/`httpx.RequestError` → 502 `opentag_fetch_failed`.
   Add `logger.info(...)` before the fetch and `logger.error(...)` on failure (the user saw
   "no entry in the log"). Apply to both refresh and matches (matches also fetches when stale).
3. Frontend `OpenTagCleanup.tsx`: show a clear loading state during refresh/initial load
   (~30–60s cold) and render the backend error `message` on failure.

## Verification

- `cd backend && pytest` — tests: routes respond at the new `/openprinttag/...` paths (and
  the old `/opentag/...` paths 404); `get_openprinttag` uses the 120s override; fetch
  failures map to the 504/502 `api_error` codes with a `logger.error`; success unchanged.
- `cd frontend && npx tsc --noEmit && npm run build`.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md`: OpenTag cleanup API renamed to `/openprinttag/*` to dodge
   ad-blocker filters on the `opentag` token; long fetch timeout + mapped errors.
3. Non-interactive subagent run: when pytest + tsc + build pass, stage ONLY the files this
   task touched (incl. prompt move + docs) and commit on `dev` with one `fix:` message.
   Never `git add -A`. Never push.
