---
name: 2026-06-07-fix-opentag-match-performance
status: completed        # pending | completed | failed
created: 2026-06-07
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-06
result: Brand pre-filter index in opentag_matches; progress logging added; 3 new tests; 494/494 pass
---

# Task: Make OpenTag matching fast — brand pre-filter + progress logging

`GET /api/openprinttag/matches` appears to hang ("just sitting", no log entries). Cause: the
matcher scores ALL ~11k OpenTag materials for EVERY Spoolman filament — `find_best_match`
does `for opt in materials` over the full ~11k list (`backend/app/core/opentag_match.py`
~234), and `score_candidate` re-normalizes each material's brand/type/color every call. With
hundreds of SM filaments that's millions of regex/normalize/RGB/jaccard ops in one
synchronous request → minutes, no progress.

## What to do

### 1. Brand pre-filter (the big win)
OpenTag is organized by brand, and each OPTMaterial has `brandName`. In the matches endpoint
(`backend/app/api/opentag.py`), build ONE index before the loop:
`materials_by_brand: dict[str, list[dict]]` keyed by `normalize_vendor(m.get("brandName"))`
(reuse `app/core/matcher.normalize_vendor`). Then for each SM filament, only score the
candidates for its vendor:
`candidates = materials_by_brand.get(normalize_vendor(sm.vendor.name if sm.vendor else None), [])`
and call `find_best_match(sm, candidates, tag_map)`. A SM vendor with no matching OpenTag
brand → empty candidates → no-match (correct; brand is a strong signal). This drops the work
from filaments×11k to filaments×(that brand's count).

Keep `find_best_match` pure (it already takes a `materials` list) — just pass the filtered
list. Don't break its existing behavior/signature for other callers/tests.

### 2. (Optional, if low-risk) precompute normalized material fields
If easy, precompute each material's normalized brand/type/color + finish-id set once (e.g. a
prepared index) so `score_candidate` doesn't re-normalize on every call. Skip if it
complicates the pure matcher — the brand pre-filter alone is the dominant fix.

### 3. Progress logging
In the matches endpoint, `logger.info("opentag matches: scoring %d filaments against %d
materials across %d brands", n_filaments, n_materials, n_brands)` before the loop, and
`logger.info("opentag matches: %d matched, %d no-match", matched, no_match)` after — so it's
visibly working in the log (the user saw "no log entries").

## Verification

- `cd backend && pytest` — tests:
  - the matches endpoint only scores same-brand candidates (e.g. a SM "Elegoo" filament is
    matched against an OpenTag "Elegoo" material and NOT against a same-name different-brand
    material); a SM vendor absent from OpenTag brands yields a no-match row.
  - a dataset with materials across several brands still returns correct best matches (parity
    with the old all-scored result for the matched brand).
  - `find_best_match` unit behavior unchanged (existing tests still pass).
- Sanity: reason that hundreds of SM filaments now complete quickly (each scores only its
  brand's handful of materials).
- `cd frontend && npx tsc --noEmit && npm run build` only if frontend touched (unlikely).

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md`: OpenTag matching pre-filters candidates by normalized brand for
   performance; progress logged.
3. Non-interactive subagent run: when pytest passes, stage ONLY the files this task touched
   (incl. prompt move + docs) and commit on `dev` with one `fix:` (or `perf:`) message.
   Never `git add -A`. Never push.
