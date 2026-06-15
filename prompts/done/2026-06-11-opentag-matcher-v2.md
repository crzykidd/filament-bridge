---
name: 2026-06-11-opentag-matcher-v2
status: completed
created: 2026-06-11
completed: 2026-06-11
model: sonnet
result: shipped — v2 scorer, mined lexicons (LEXICON_VERSION=2), cache persistence, search endpoint + UI, 37 new tests (17 golden + 20 lexicon), docs
---

# Task: OpenTag matcher v2 — structured token scoring + mined modifier/color lexicons

Plan-first redesign of the OpenPrintTag matcher. **SEQUENCING: must run AFTER
`2026-06-11-opentag-updates-review` lands** — both edit `opentag_match.py`/`opentag.py`/
`OpenTagCleanup.tsx`. Do the working-tree check and rebase on that work first.

## The problem (verified in code)

The current scorer (`backend/app/core/opentag_match.py`) mismatches because it throws away
the discriminating signal:
- **Colors collapse to ONE base color** — `_base_color()` (~line 111) reduces all color
  tokens to a single canonical color via `DEFAULT_COLOR_KEYWORDS` (silver→grey, etc.). A
  multi-color name loses its extra colors.
- **Modifiers are STRIPPED, not matched** — the "modifier words that prefix a color token"
  set (~line 103) discards `shiny`, `gradient`, etc., so they can't reward a match.

Concrete failure: Spoolman **"Silk Shiny Gradient Silver & Shiny Blue"** (AMOLEN, PLA Silk)
does NOT surface the near-exact OpenPrintTag entry
`amolen-pla-silk-shiny-gradient-silver-shiny-blue` ("PLA Silk Shiny Gradient Silver & Shiny
Blue") in the top candidates — a worse "Dual Color Blue & Fuchsia (65%)" wins. A ~perfect
match scores below garbage because its distinctive tokens are stripped and its colors are
collapsed.

## The redesign

**Structured token scoring.** Decompose each name (Spoolman side AND each OPT candidate)
into a typed token bag: `brand · material · finish · {modifiers} · {colors}`. Score by
component, treating sets as sets:
- **material + finish** — gate / strong weight (reuse existing `strip_finish_words` /
  finish-tag detection). Brand is already pre-filtered.
- **colors** — match as a **multiset**, order-independent, count-aware. `{silver,blue}` vs
  `{silver,blue}` = full; subset = partial; extras on either side = penalty. **Never collapse
  to a single base color.**
- **modifiers** — match as a **set**, as POSITIVE signal (shiny, gradient, galaxy, dual
  color, triple color, S-Series, sparkle, glow, marble, basic, UV/temperature color change,
  …). Stop stripping them.
- Small bonus for high full-string similarity as a tie-breaker.

This must make the failing example score ~95–100% and rank "Dual Color Blue & Fuchsia" far
below.

**Mined lexicons (build during dataset load).** Extend `core/opentag_cache.py`: when the
~12.8k-material OpenPrintTag dataset loads, tokenize all material names, subtract known
brands/materials/finishes/colors, and the recurring residual tokens = **modifiers**. Persist
a mined `modifiers` + `colors` reference alongside the cache (TTL-gated like the dataset),
**merged over a hand-seed list** (so rare-but-important modifiers aren't missed).
- **Hard part — multi-word modifiers:** "dual color", "triple color", "color change",
  "shiny gradient", "s-series" need **n-gram (bigram/trigram) extraction**, not just
  unigrams. The PLAN must specify the n-gram mining + how multi-word tokens are matched.
- **Colors:** keep `DEFAULT_COLOR_KEYWORDS` ONLY for true synonyms (gray/grey,
  violet/purple, magenta/pink). DROP the conflating entries (e.g. galaxy=black, cool=grey) —
  those are modifiers or distinct colors, not collapses. Optionally mine a color lexicon too.

**Manual search fallback (long tail).** Add a brand/material-scoped **search box** to the
cleanup UI (`OpenTagCleanup.tsx`): user types free text → fuzzy-search the OPT dataset within
the pre-filtered brand → ranked results using the same scorer. Backend: a search endpoint
(e.g. `GET /api/openprinttag/search?brand=&material=&q=`) returning scored candidates.

## Before you start

Read `CLAUDE.md` (OpenTag concepts), `docs/opentag-cleanup.md`, the memory/decisions on the
matcher, and the current code: `core/opentag_match.py` (scorer, `_base_color` ~111, modifier
strip set ~103, `_color_name_tokens` ~525, finish/material helpers), `core/opentag_cache.py`
(dataset load + cache), `core/material_tags.py` (finish detection), `api/opentag.py`
(matches/refresh/apply + the new search endpoint), `OpenTagCleanup.tsx`. Honor the runtime
settings `opentag_color_keywords` / `opentag_vendor_aliases` (keep working; recolor their
role around the new model).

## Working tree check

`git status --porcelain`; rebase on the merged `opentag-updates-review` changes. If relevant
files are dirty from unrelated work, list and ask. This prompt is exempt.

## Step 0 — PLAN before coding (required; model=opus)

Plan covering: the exact token decomposition + per-component weights + the scoring formula
(show it produces the right ranking for the AMOLEN example and a few other cases); the
modifier/color lexicon mining algorithm incl. **n-gram extraction + thresholds + seed merge
+ cache persistence shape**; how multi-word modifiers are tokenized/matched on both sides;
the search endpoint + UI; backward-compat with the existing matches/apply flow and the
`opentag_color_keywords` setting; and the test matrix (include the AMOLEN case + a basket of
real names as golden tests). Confirm ambiguous calls with the user before implementing.

## What to do (after plan agreed)

Implement the structured scorer, the mined lexicons + cache persistence, the manual search
endpoint + UI, and a **golden-set regression test** of real Spoolman→OPT names (the AMOLEN
case must rank #1) plus unit tests for tokenization, n-gram mining, and color-multiset
scoring. Backend pytest + ruff; frontend tsc + npm test.

### Documentation (explicit deliverables — user requested)

- **New doc page** (e.g. `docs/opentag-matching.md`) — "How OpenTag matching works":
  explain the structured token model (brand · material · finish · {modifiers} · {colors}),
  the **dynamically-mined** modifier/color lexicons (built from the OpenPrintTag dataset at
  load + seed merge, incl. n-grams), the color-multiset scoring, and the manual search
  fallback. Worked example using the AMOLEN "Shiny Gradient Silver & Shiny Blue" case
  showing why it now ranks #1. Link it from `docs/README.md` and cross-link
  `docs/opentag-cleanup.md`.
- **README** — add a short line under the OpenTag/feature section: matching is done using
  **dynamic values mined from the OpenPrintTag dataset** (modifiers, colors) rather than a
  static keyword hack, with a **link to `docs/opentag-matching.md`** for details.
- **`docs/decisions.md`** — entry recording the matcher-v2 design: why the
  collapse-to-one-color + strip-modifiers model was replaced, the structured-token + mined-
  lexicon approach, and the n-gram mining decision.
- **CLAUDE.md** — update the OpenTag-matcher env-var/settings notes if the role of
  `opentag_color_keywords` changes (now synonyms-only, not the primary mechanism).

## Conventions to honor

- Reuse finish/material helpers; don't duplicate. Keep matches/apply wire formats stable.
- Lexicon mining must be deterministic (no `Math.random`/time-based ordering) and cached.
- REQUIRED checks before proposing the commit: backend `pytest` + `ruff check`; frontend
  `npx tsc --noEmit` + `npm test`. (Sandbox `itsdangerous` collection failures are env-only —
  ignore; no NEW failures.)
- Conventional-commits `feat:`. No `Co-authored-by:`. Branch `dev`, never `main`, never push.

## When done

Update frontmatter; `git mv` to `prompts/done/`; log the matcher-v2 design in
`docs/decisions.md`; propose ONE `feat:` commit (specific paths, never `git add -A`) and STOP
for the user to run it. Never push.
