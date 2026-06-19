---
name: 2026-06-18-opentag-smart-dataset-refresh
status: done
created: 2026-06-18
model: opus              # PLAN first (cache-shape migration + fetch-gate change); then implement
completed: 2026-06-18
result: >
  Implemented commit-SHA-gated dataset refresh. Cache now stores commit_sha;
  added get_upstream_commit_sha() (vnd.github.sha media type, 15s timeout,
  best-effort → None on failure). load_opentag_dataset gained force_pull/
  force_check intents (force= aliases force_pull); SHA-match bumps fetched_at
  only (unchanged=True, no download). POST /api/openprinttag/refresh defaults to
  hash-checked, ?pull=true forces. Match-cache dataset fingerprint now keys off
  commit_sha (falls back to count:fetched_at). Frontend Refresh shows "already
  up to date" + "Pull contents anyway" when unchanged. Docs + changelog +
  decision updated. Backend 1147 pass + ruff clean; frontend tsc clean + 84 pass.
  Left uncommitted for orchestrator review.
---

# Task: Smart OpenTag dataset refresh — hash-gate the heavy download

The OpenTag dataset is a large GitHub tarball; today every refresh (and every stale re-load)
re-downloads + re-parses it. Gate that behind a cheap **commit-SHA check** so the heavy pull
only happens when the upstream repo actually changed — or when the user explicitly forces it.

## Decided behavior (with the user)

- **Store the upstream commit SHA** alongside the cached dataset (next to `count`/`fetched_at`).
- **Stale auto-reload** (cache older than `OPENTAG_CACHE_MAX_AGE_HOURS`): check the SHA first; if
  it's **unchanged**, **skip the download and just bump the age** (`fetched_at = now`) so the
  cache is fresh again. Download only when the SHA differs.
- **Manual Refresh**: check the SHA; if unchanged → tell the user *"current data is already up
  to date"* and **bump the age**, then offer a **"Pull contents anyway"** button that forces the
  full tarball download regardless of SHA. If the SHA differs → download (optionally note
  "updated").

Net: the expensive tarball download happens only on a real content change or an explicit
"Pull contents anyway."

## Verified plumbing (don't re-derive)

- Dataset source: GitHub tarball `https://api.github.com/repos/OpenPrintTag/openprinttag-database/tarball/main`
  (`backend/app/core/opentag_cache.py:98` `_TARBALL_URL`).
- `load_opentag_dataset(data_dir, max_age_hours, force=False)` (`opentag_cache.py:395`) is the
  single fetch gate: `needs_fetch = force or cache is None or _is_stale(...)` (`:444`). Fetch
  writes via `_save_cache(materials, fetched_at, ...)` (`:331`); cache shape documented at
  `:15-22` (currently `fetched_at`, `count`, `materials`, lexicons). `_is_stale` at `:304`.
- The manual refresh endpoint `POST /api/openprinttag/refresh` (`opentag.py:537`) calls
  `load_opentag_dataset(..., force=True)` and returns `OpenTagDatasetMeta`. Status endpoint
  `opentag_status` (`opentag.py:520`) returns `count`/`fetched_at`/`stale`/`last_count`.
- The total record count is NOT knowable without downloading+parsing the tarball — so it can't
  gate the download. The commit SHA is the cheap signal (count stays as displayed info only).

## What to do (after the Step-0 plan)

### Backend
1. **Cheap upstream-SHA fetch** — add a helper (e.g. `get_upstream_commit_sha()`) that calls
   `GET https://api.github.com/repos/OpenPrintTag/openprinttag-database/commits/main` (consider
   `Accept: application/vnd.github.sha` to get just the SHA as plain text). Short timeout;
   tolerant of failure/rate-limit (GitHub unauth = 60/hr/IP) — on error, return None and let the
   caller fall back to "download" (never hard-fail a refresh because the check failed).
2. **Store `commit_sha`** in the cache file via `_save_cache` (extend the shape + the doc
   comment at `:15-22`); read it back in `_load_cache`/`get_cache_metadata`.
3. **Rework the fetch gate** in `load_opentag_dataset` to distinguish three intents (decide the
   exact param names in the plan, e.g. `force_check` vs `force_pull`):
   - **stale/normal**: if stale (or `force_check`), fetch upstream SHA; if `== cached commit_sha`
     → rewrite the cache with `fetched_at = now` (bump age), keep materials/count/SHA, return a
     result flagged `unchanged=True` (NO tarball download); else download+parse+`_save_cache`
     with the new SHA, `unchanged=False`.
   - **force_pull** ("Pull contents anyway"): skip the SHA check, always download+parse+save.
   - missing cache: always download.
4. **Endpoint shape**: `POST /api/openprinttag/refresh` defaults to the hash-checked path and
   returns `{ unchanged, count, fetched_at, commit_sha }`; a force variant (e.g. `?pull=true`)
   does the unconditional download. Keep the existing timeout/HTTP-error handling.
5. Surface `commit_sha` (and `unchanged`) where useful (status/refresh responses) so the
   match-result cache fingerprint (sibling prompt) can key off dataset identity.

### Frontend (`OpenTagCleanup.tsx` + the dataset-status banner)
6. **Refresh** button → call the hash-checked refresh. If `unchanged`: show
   *"Dataset already up to date (same commit · N records)"* and update the banner's age; render a
   **"Pull contents anyway"** button that calls the force variant. If changed: normal refresh
   (optionally "updated to N records").
7. Banner shows count + age; reflect the bumped age after a hash-only check.

## Edge cases / cautions
- GitHub API failure/timeout/rate-limit on the SHA check → fall back to downloading (or, for a
  background stale check, leave the cache as-is and try later) — never break refresh on a failed
  check. Log scrubbed (`core/log_safe.scrub`, CWE-117) — match the existing `_scrub` usage.
- Existing caches have no `commit_sha` → treat as "unknown" → first refresh downloads and
  records it (don't bypass on a missing stored SHA).
- The bump-age-without-download path must rewrite ONLY `fetched_at` (and keep `commit_sha`,
  `count`, `materials`, lexicons intact).

## Before you start
- Read `docs/opentag-cleanup.md`, `CLAUDE.md` (OpenTag, `OPENTAG_CACHE_MAX_AGE_HOURS`),
  `backend/app/core/opentag_cache.py` (full), `backend/app/api/opentag.py:520-580`
  (status + refresh), and the dataset-status banner in `frontend/src/pages/OpenTagCleanup.tsx`.

## Working tree check
`git status --porcelain`; build on the committed OpenTag work (and, if already landed, the perf/
match-cache prompt). List anything unexpected; ask.

## Step 0 — PLAN (required: cache-shape change + fetch-gate intents + endpoint params)
State the new cache shape, the SHA helper + media type + failure handling, the `load_opentag_
dataset` intent params, the refresh endpoint/param shape, the UI states, and the test matrix.
Confirm ambiguities first.

## Tests
- Cached SHA == upstream → no download, `fetched_at` bumped, `unchanged=True`; materials/count
  untouched.
- Cached SHA != upstream → downloads, new SHA stored, `unchanged=False`.
- `force_pull` downloads even when SHA matches.
- Missing stored SHA → downloads (no false "unchanged").
- SHA-fetch failure → safe fallback (download or leave-as-is per the path), refresh never 500s
  on a failed check.
- Stale auto path bumps age without download when unchanged.
- Backend `pytest` + `ruff check .`; frontend `npx tsc --noEmit` + `npm test`. All green.

## Conventions to honor
- Don't break the existing refresh timeout/HTTP-error envelopes. Doc updates ship in the SAME
  commit (`docs/opentag-cleanup.md` — the smart-refresh flow; `CHANGELOG.md` `[Unreleased]`;
  decision in `docs/decisions.md`). Conventional-commits `feat:`. No `Co-authored-by:`. Branch
  `dev`, never `main`, never push.

## When done
1. Frontmatter (`status`/`completed`/`result`); `git mv` to `prompts/done/`.
2. Decision logged in `docs/decisions.md`.
3. Propose ONE commit (specific paths, never `git add -A`); present list + one-liner; STOP.
   Never push.
