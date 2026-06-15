# Signed-off plan — OpenTag matcher v2

Companion to `prompts/2026-06-11-opentag-matcher-v2.md`. Signed off 2026-06-11.

## LOCKED DECISIONS
- **Drop the base-color collapses** in `DEFAULT_COLOR_KEYWORDS` (esp. `silver→grey`,
  `galaxy→black`, `cool→grey`, `jet→black`, `sky→blue`, etc.). Reduce to a synonyms-only
  `COLOR_SYNONYMS` map: keep only true equivalences (`gray→grey`, `violet→purple`,
  `magenta→pink`, `transparent→clear`, `navy→blue`). Base colors kept as identity entries.
- **Weights** (sum 1.0 at perfect): colors (multiset) **0.40**, modifiers (set) **0.15**,
  material family **0.15**, brand **0.15**, finish **±0.10**, hex **0.05** (demoted from
  0.15), full-string-similarity tie-breaker **+0.05** max.
- **N-grams do NOT cross `&`/`/` separators** (those mark color-conjunction boundaries).
- `opentag_color_keywords` setting recolored to **synonyms-only** (feeds COLOR_SYNONYMS
  overrides), no longer the primary mechanism. `opentag_vendor_aliases` unchanged.
- Manual search endpoint scores a **synthetic `SpoolmanFilament(name=q, vendor=brand,
  material=material)`** through the same `score_candidate` — no duplicate scorer.
- **PAUSE-TO-REVIEW (user requested):** implement the mining + scorer, then run mining
  against a freshly-fetched dataset and **STOP**, reporting the **top ~80 mined modifiers +
  mined colors** (with frequencies) back for the user to eyeball/tune. Do NOT finalize
  scoring weights/thresholds or claim done until the user approves the mined lexicon. Provide
  a `scripts/dump_lexicon.py` (or a flag) so the dump is reproducible.

## Plan (implement faithfully)

### 1. Token decomposition — `decompose_name(...) -> ParsedName` (pure, both sides identical)
`ParsedName(material_family, finish_ids: frozenset[int], modifiers: frozenset[str],
colors: Counter/multiset)`. Pipeline: `_norm` → `material_family()` (opentag_match.py:444) →
`finish_ids_from_text()` (material_tags.py:181) → strip brand/material/finish (refactor
`_color_name_tokens` ~525 into an order-preserving `_residual_tokens(...)` returning the
ordered token list; keep `_color_name_tokens = set(_residual_tokens(...))` as a back-compat
wrapper) → split residual into modifiers vs colors via the mined lexicons with **longest
n-gram first** (trigram→bigram→unigram sliding window, consume matched spans). SM side uses
`sm.name` only (vendor/material are separate fields); OPT side uses `opt["name"]`.

### 2. Scoring — replace `score_candidate` body (KEEP signature, add `lexicon=None` kwarg)
- **Color multiset:** `A,B = Counter(sm_colors), Counter(opt_colors)`;
  `matched=sum((A&B).values()); denom=matched+sum((A-B).values())+sum((B-A).values());
  color_score = matched/denom` (1.0 iff identical multiset); **neutral 0.5 when either side
  has zero colors.** Canonicalize via COLOR_SYNONYMS BEFORE building Counters. ×0.40.
- **Modifiers:** Jaccard of the two sets ×0.15; neutral 0.5×0.15 floor when both empty;
  extras only mildly cost via Jaccard denominator (never hard penalty).
- finish: reuse `_finish_score` rescaled to ±0.10. hex: 0.05 tie-breaker.
  full-string `SequenceMatcher` ratio: +0.05 max tie-breaker.
- AMOLEN target: near-exact ~0.95 vs "Dual Color Blue & Fuchsia" ~0.47.

### 3. Lexicon mining — new `core/opentag_lexicon.py` (pure, deterministic, no rand/time)
`mine_lexicons(materials) -> {"modifiers":[...], "colors":[...]}`:
1. residual corpus via `_residual_tokens` per material (brand+material+finish removed).
2. subtract known colors (COLOR_SYNONYMS keys ∪ seed base colors).
3. n-gram extraction (uni/bi/tri-gram, contiguous, not crossing `&`/`/`); global `Counter`.
4. thresholds (module constants — TUNE during the pause): `MODIFIER_MIN_COUNT=5`,
   `MODIFIER_MIN_BRANDS=2`; bigram/trigram promoted to a unit only when it behaves like a
   phrase (co-occurs far above the product of its unigram frequencies — the "bigram-lift"
   rule; document carefully so `dual color`/`color change` promote but `shiny gradient`
   does not). Colors: stricter `COLOR_MIN_COUNT=8`, `COLOR_MIN_BRANDS=3`.
5. subtract tokens covered by a longer kept n-gram (drop standalone `dual`/`color` once
   `dual color` kept).
6. seed-merge `MODIFIER_SEED` (dual color, triple color, tri color, color change,
   temperature change, uv change, shiny, gradient, galaxy, sparkle, glitter, glow, marble,
   matte, silk, basic, rainbow, s series, multi, metallic, pearl, …) unioned UNCONDITIONALLY.
   Sort longest-first then alpha → deterministic. Store as `{1:set,2:set,3:set}` for matching.

Cache: extend `opentag_cache.json` (`_save_cache` ~331) with `lexicon_version:1` +
`lexicon:{modifiers,colors}`. `load_opentag_dataset` computes lexicon once at fetch; warm
cache reads it back; a `lexicon_version` bump (or missing) triggers in-place recompute WITHOUT
network re-fetch (self-heal like `_materials_valid` ~378). Return dict gains `"lexicon"`.
`api/opentag.py:opentag_matches` reads `dataset["lexicon"]`, builds n-gram match dicts once,
threads `lexicon=` into `find_best_match`→`score_candidate`. `lexicon=None` → seed-only
fallback (keeps existing unit tests valid).

### 4. Color lexicon = base-color identities ∪ mined colors; COLOR_SYNONYMS applied only for
true synonyms before multiset compare.

### 5. Manual search — `GET /api/openprinttag/search?brand=&material=&q=&limit=20` in
`api/opentag.py` → `OpenTagSearchResponse{results:[OpenTagCandidate]}`. Warm-cache load, same
brand pre-filter (alias-resolved) + optional family gate, score a synthetic SM filament
through `score_candidate` with the lexicon, sort desc, top N. Frontend: search box per card
in `OpenTagCleanup.tsx` (~305) + `getOpenTagSearch` in `client.ts` + `OpenTagSearchResponse`
in `types.ts`; on pick, inject chosen candidate via the existing `onCandidateChange` path.
Apply wire format unchanged.

### 6. Back-compat: matches/apply wire formats UNCHANGED (only additive `search` endpoint +
additive `lexicon` cache key). `score_candidate`/`find_best_match` gain optional `lexicon=`.
Remove the `_base_color` bonus branch (recommend delete `_base_color` + its 3 tests); keep
`_name_similarity`/`_color_name_tokens` shims (tests reference them).

### 7. Tests: golden set `test_opentag_golden.py` (~12 real cases; AMOLEN ranks #1 + Dual
Color strictly below; Orange-vs-Copper preserved; Hatchbox Red single; ELEGOO dual-color
tri-pack; Prusament alias; matte-vs-silk). `test_opentag_lexicon.py`: tokenization,
n-gram mining (dual color mined, shiny gradient NOT; determinism; seed-merge), color-multiset
scoring, cache persistence (lexicon written on fetch; warm read; version-bump in-place
recompute without network). Frontend tsc + npm test (+ search type/fn).

### 8. Docs: new `docs/opentag-matching.md` (token model, mined lexicons, n-grams,
color-multiset, search, AMOLEN worked example) linked from `docs/README.md` +
`docs/opentag-cleanup.md`; README line (matching uses dynamic mined values + link);
`docs/decisions.md` entry; CLAUDE.md `opentag_color_keywords` role-change note.

## OPEN QUESTIONS resolved by user
- N-gram thresholds: PAUSE and show mined lexicon for review (above). silver→grey: DROP.
  Weights: as locked. Separators break n-grams: yes. Synthetic-filament search: yes.

## Sequencing
Single `feat:` commit AFTER the pause-review is approved. NOTE: overlaps `api/client.ts` +
`api/types.ts` + `OpenTagCleanup.tsx` with the Conflicts-UI work — must run AFTER #2 lands.
