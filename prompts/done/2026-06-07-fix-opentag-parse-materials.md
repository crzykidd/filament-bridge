---
name: 2026-06-07-fix-opentag-parse-materials
status: completed        # pending | completed | failed
created: 2026-06-07
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-06
result: fixed get_openprinttag to extract materials from OPTDatabase wrapper; cache self-heals malformed entries; matcher skips non-dicts; 10 new tests, 491/491 pass
---

# Task: Fix OpenTag parsing — extract `materials` from FDB's OPTDatabase response

`GET /api/openprinttag/matches` 500s with `AttributeError: 'str' object has no attribute
'get'` in `opentag_match.score_candidate` (`opt.get("type")`), because `opt` is a string.
Root cause: FDB's `GET /api/openprinttag` returns an **OPTDatabase OBJECT**, not a flat list:
```
{ "brands": OPTBrand[], "materials": OPTMaterial[], "cachedAt": str,
  "totalFFF": number, "totalSLA": number }
```
The bridge's `get_openprinttag()` does `return resp.json()` and treats the whole dict as the
materials list, so downstream code iterates the dict's 5 KEYS (strings) — hence the log
"saved 5 materials" and the AttributeError when a string is passed to the matcher.

## What to do

### 1. Extract the materials array (`backend/app/services/filamentdb.py`)
In `get_openprinttag()`, return the nested `materials` list, defensively:
```python
data = resp.json()
if isinstance(data, dict):
    return data.get("materials", []) or []
return data  # already a list (defensive)
```
Update the docstring to note FDB returns an OPTDatabase wrapper; the bridge returns its
`materials` array (OPTMaterial dicts). (`brandName` is already on each OPTMaterial, so the
matcher doesn't need the separate `brands` list.)

### 2. Self-heal the already-bad cache (`backend/app/core/opentag_cache.py`)
The existing `DATA_DIR/opentag_cache.json` was written with the malformed data (string
entries), and the matches endpoint loads it with `force=False`, so it would keep failing
until a manual refresh. Make the loader treat a malformed cache as stale: if the cached
`materials` is not a non-empty list of dicts (e.g. `not all(isinstance(m, dict) for m in
materials)`), re-fetch (as if stale) instead of returning it. So it self-heals on the next
`/openprinttag/matches` call without requiring a manual Refresh.

### 3. Defensive matcher (`backend/app/core/opentag_match.py`)
In `find_best_match`/`score_candidate`, skip any candidate that isn't a dict (guard against
future shape drift) so one bad entry can't 500 the whole endpoint.

## Verification

- `cd backend && pytest` — tests:
  - `get_openprinttag` returns the `materials` array when the (mocked) FDB response is the
    OPTDatabase wrapper `{brands, materials:[{...},{...}], cachedAt, totalFFF, totalSLA}`;
    returns a list unchanged if already a list; returns `[]` when `materials` missing.
  - cache loader re-fetches when the cached `materials` contains non-dict entries (malformed
    self-heal), and serves a valid fresh cache normally.
  - matcher tolerates a non-dict entry in the materials list without raising.
  - `/openprinttag/matches` returns 200 with real per-field matches given a wrapper-shaped
    FDB response (not 500).
- `cd frontend && npx tsc --noEmit && npm run build` (only if frontend touched — likely not).

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md`: FDB `/api/openprinttag` returns an OPTDatabase wrapper; bridge
   extracts `.materials`; cache self-heals on malformed data.
3. Non-interactive subagent run: when pytest (+ any build) passes, stage ONLY the files this
   task touched (incl. prompt move + docs) and commit on `dev` with one `fix:` message.
   Never `git add -A`. Never push.
