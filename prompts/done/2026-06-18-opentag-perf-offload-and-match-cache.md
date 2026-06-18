---
name: 2026-06-18-opentag-perf-offload-and-match-cache
status: done
created: 2026-06-18
model: opus              # PLAN first (event-loop offload is delicate); then implement
completed: 2026-06-18
result: >
  Offloaded the OpenTag match/completeness/search CPU work off the FastAPI event loop via
  run_in_threadpool (pure helpers _compute_matches/_compute_completeness/_compute_search take
  plain data, no I/O inside the thread). Added a DATA_DIR match-result cache
  (core/opentag_match_cache.py → opentag_matches_cache.json) with computed_at + input
  fingerprints (dataset count+fetched_at fallback, SM filament count, alias/tag/field config
  hash); GET /api/openprinttag/matches serves the cache instantly and recomputes only on
  ?recompute=true, flagging stale_inputs otherwise. Frontend loads cached on Match to DB,
  shows "last matched <time>" + stale hint + Refresh match, aborts the fetch on unmount.
  Docs (opentag-cleanup.md, CHANGELOG, decisions.md) updated. All checks green:
  backend pytest 1136 passed + ruff clean; frontend tsc clean + 84 tests passed.

---

# Task: OpenTag matching — stop blocking the app, and cache the last match result

Two linked fixes so the OpenTag tools never freeze the whole bridge and don't recompute on
every visit:
1. **Offload** the CPU-bound matching off the FastAPI event loop (today it blocks every other
   request while a match runs — that's the "everything is busy" symptom the user hit).
2. **Cache the last match result** so opening the page loads it instantly; recompute only on an
   explicit **Refresh**.

## Verified root cause (don't re-derive)

- `backend/app/api/opentag.py:582` `async def opentag_matches(...)` runs the dataset load +
  scoring **synchronously on the event loop** — there is NO `run_in_threadpool` / `to_thread` /
  `is_disconnected` anywhere in the file. So a match blocks ALL API requests until it finishes.
  Same blocking pattern in `opentag_completeness` (`:1389`) and `opentag_search` (`:1213`).
- The frontend match fetch (`getOpenTagMatches` → `OpenTagCleanup.tsx:1607`, triggered by
  `handleMatchToDb` `:1625`) has **no AbortController** — nothing cancels it on unmount. (Note:
  aborting the client alone does NOT fix the freeze — the server keeps running the blocking
  loop; the offload below is the actual cure.)

## What to do (after the Step-0 plan)

### 1. Offload the heavy work off the event loop
- Do all async I/O on the loop first (await: Spoolman filament fetch via the httpx client,
  BridgeConfig reads for aliases/keywords/field settings, `load_opentag_dataset(...)`), then run
  the **pure-CPU** scoring/parse in a worker thread via `starlette.concurrency.run_in_threadpool`
  (or `anyio.to_thread.run_sync`). Extract the CPU part into a sync helper that takes plain data
  (materials list, SM filaments, resolved config) and returns the response payload.
- **Inside the thread: no httpx, no SQLAlchemy session, no `request` access** (not thread-safe).
  Pass already-fetched plain data in; return plain data out.
- Apply the same offload to `opentag_completeness` and `opentag_search`.

### 2. Cache the last match result
- Persist the computed match result (the `OpenTagMatchesResponse` payload) to a file under
  `DATA_DIR` (mirror the dataset-cache pattern in `core/opentag_cache.py`) or a BridgeConfig
  key, with: `computed_at`, and input fingerprints — dataset identity (commit SHA/count; see
  the sibling smart-refresh prompt — if not yet present, fall back to count + `fetched_at`), the
  Spoolman filament count, and a hash of the alias/keyword/field config.
- **`GET /api/openprinttag/matches` returns the cached result instantly** when present (no
  compute), with `computed_at` and a `stale_inputs` indicator (true when the current dataset/SM
  count/config fingerprints differ from the cached ones).
- **Recompute only on explicit refresh** — add a recompute trigger (e.g. `?recompute=true` or a
  `POST /api/openprinttag/rematch`); it runs the offloaded match, re-caches, and returns the
  fresh result. Decide the exact shape in the plan.
- Invalidate/flag (don't silently serve stale): when inputs changed, still return the cache but
  set `stale_inputs` so the UI can prompt "your filaments/dataset changed since last match —
  refresh?".

### 3. Frontend (`OpenTagCleanup.tsx`)
- On "Match to DB": load the **cached** result (fast); show "last matched <relative time>" and,
  when `stale_inputs`, a subtle "data changed since last match — Refresh" hint.
- Add a **Refresh** affordance on the match view that triggers the recompute.
- Add an **AbortController** to the match/recompute fetch and abort it in the effect cleanup, so
  navigating away cancels the client wait and clears the loading state immediately.

## Edge cases / cautions
- First run (no cache yet): "Match to DB" computes once, then caches.
- Thread-safety: the offloaded function must be pure — verify the matcher
  (`core/opentag_match.py`) and field builders don't touch the DB/httpx/request.
- Don't break the existing apply/decision flow — it operates on live Spoolman state at Apply
  time regardless of the cached display.
- This prompt may land before/after `2026-06-18-opentag-smart-dataset-refresh`. If the dataset
  commit-SHA isn't available yet, fingerprint on `count` + `fetched_at`; note the dependency.

## Before you start
- Read `docs/opentag-cleanup.md`, `docs/sync-model.md` (if it mentions OpenTag), `CLAUDE.md`
  (OpenTag), `backend/app/api/opentag.py` (matches/completeness/search), `backend/app/core/
  opentag_match.py` (confirm purity), `backend/app/core/opentag_cache.py` (cache pattern), and
  `frontend/src/pages/OpenTagCleanup.tsx`.

## Working tree check
`git status --porcelain`; build on the committed OpenTag redesign (landing toolbar, dropdown,
completeness report, inline unmatch). List anything unexpected; ask.

## Step 0 — PLAN (required: offload boundary + cache shape + recompute trigger)
State exactly which code moves into the thread (and proof it's pure), the cache file/shape +
fingerprints, the recompute endpoint/param, and the test matrix. Confirm ambiguities first.

## Tests
- Matching runs without blocking: a second request returns while a (large) match is in flight
  (e.g. assert the matches helper is invoked via run_in_threadpool; or a timing/concurrency
  test).
- `GET matches` returns the cached payload without recomputing when present; recompute trigger
  refreshes + re-caches.
- `stale_inputs` flips when SM count / config / dataset fingerprint changes.
- Offloaded helper is pure (no DB/httpx) — unit-test it on plain inputs.
- Backend `pytest` + `ruff check .`; frontend `npx tsc --noEmit` + `npm test`. All green.

## Conventions to honor
- Reuse the `opentag_cache` file-cache pattern; keep the matcher pure. Doc updates ship in the
  SAME commit (`docs/opentag-cleanup.md`, `CHANGELOG.md` `[Unreleased]`, decision in
  `docs/decisions.md`). Conventional-commits `perf:` or `feat:`. No `Co-authored-by:`. Branch
  `dev`, never `main`, never push.

## When done
1. Frontmatter (`status`/`completed`/`result`); `git mv` to `prompts/done/`.
2. Decision logged in `docs/decisions.md`.
3. Propose ONE commit (specific paths, never `git add -A`); present list + one-liner; STOP.
   Never push.
