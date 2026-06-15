---
name: 2026-06-08-fix-colorname-tokenization
status: completed        # pending | completed | failed
created: 2026-06-08
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-07
result: tokenize on non-alphanumeric + drop multicolor descriptor noise; 7 new tests; 631 passing
---

# Task: Fix color-name tokenization so "Green/Purple" matches "Green Purple" (multicolor names tie)

The OpenTag matcher ties all of a brand's dual-color variants at the same confidence, so the
correct color combo isn't preferred. Example: SM "Matte PLA Dual Color **Green/Purple**" (#147)
scores the OpenTag "Green Purple", "Blue Pink", "Brown White", etc. ALL at 67%.

Root cause (in `backend/app/core/opentag_match.py` `_color_name_tokens`): the name is split on
WHITESPACE only, so "Green/Purple" becomes the single token `green/purple` and never matches
the space-separated "Green Purple". Confirmed:
```
SM "Matte PLA Dual Color Green/Purple"     → {'green/purple', 'dual', 'color'}
OPT "PLA Matte Dual Color Green Purple"    → {'green', 'purple', 'dual', 'color'}
OPT "PLA Matte Dual Color Blue Pink"       → {'blue', 'pink', 'dual', 'color'}
```
SM∩GreenPurple = {dual,color} = SM∩BluePink → identical similarity → all tie.

## What to do

In `_color_name_tokens`:
1. **Tokenize on non-alphanumeric**, not whitespace: split the (vendor/material/finish-stripped)
   name with a regex like `re.split(r"[^a-z0-9]+", text.lower())` so `/`, `-`, `&`, etc.
   separate tokens. "Green/Purple" → {"green","purple"}; "Black & Red Gold" → {"black","red","gold"}.
2. **Drop generic multicolor-descriptor noise tokens** that aren't colors and appear across all
   dual/tri candidates — at least: `color`, `dual`, `tri`, `multi`, `multicolor`, `tricolor`,
   `dualcolor`. (Keep this a small explicit NOISE set; do NOT strip actual color words.)
   After this, SM "Green/Purple" → {"green","purple"}; "Green Purple" → {"green","purple"}
   (Jaccard 1.0); "Blue Pink" → {"blue","pink"} (disjoint → 0.0).

Result: the matching color combo scores strictly highest; non-matching combos are penalized on
the name component. Single-color names are unaffected ("Orange" → {"orange"}).

Keep `_name_similarity` as-is (its empty-set → 0.5 neutral still applies if stripping leaves a
name with no color tokens).

## Verification

- `cd backend && pytest` — tests:
  - `_color_name_tokens("Matte PLA Dual Color Green/Purple","AMOLEN","PLA",...) == {"green","purple"}`
    (split on `/`, noise removed); `"PLA Matte Dual Color Green Purple"` (no vendor) → same set.
  - `score_candidate`/`find_best_match` for SM "...Green/Purple": the "Green Purple" OpenTag
    candidate scores STRICTLY higher than "Blue Pink"/"Brown White" of the same brand+material,
    and `find_best_match` returns Green Purple as best (or at least ranks it #1 in alternates).
  - single-color unaffected: "Orange" → {"orange"}; existing single-color matcher tests pass.
  - a name with only descriptors ("Dual Color") → empty set → neutral (no crash).
- Re-run the spirit of the earlier audit mentally: dual-color filaments now prefer the exact
  color combo.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md`: color-name tokens split on non-alphanumeric + drop multicolor
   descriptor noise, so multi-color names rank the correct combo highest (only if non-obvious).
3. Non-interactive subagent run: when pytest passes, stage ONLY the files this task touched
   (incl. prompt move + docs) and commit on `dev` with one `fix:` message. Never `git add -A`.
   Never push.
