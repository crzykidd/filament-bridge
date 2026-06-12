---
name: 2026-06-11-opentag-matcher-v2.1-soften-gates
status: pending          # pending | completed | failed
created: 2026-06-11
model: opus              # matcher scoring/gate logic — PLAN first, then implement
completed:
result:
---

# Task: OpenTag matcher v2.1 — soften hard metadata gates + capture distinctive descriptors

Follow-up to matcher v2 (commit c10a14e). v2 made *scoring* name-driven, but two pre-v2
**hard pre-filter gates** still drop candidates the name clearly matches. Plan-first — gate
changes affect ALL matching, so golden tests must lock the new cases AND the existing ones
against regression.

## Two proven failure cases (verified against the live cache)

Both gates live in `backend/app/api/opentag.py:598-617` (`opentag_matches`), applied to
`filtered_candidates` BEFORE `find_best_match`.

**Case 1 — color-profile gate drops a name-perfect match.**
SM `CC3D · Temperature Color Change Purple to Red` (PLA) should match
`cc3d-temperature-color-change-pla-purple-to-red`, but the top suggestion is the
zero-color-overlap `...-green-to-yellow (67%)`. Evidence:
- `purple-to-red`: `color=None, secondaryColors=['#963877']` → `opt_color_profile = 'single'`
- `green-to-yellow`: 2 secondaryColors → `'multi_unknown'`
- SM name decomposes to colors `{purple, red}` (multi). `profiles_compatible(multi, 'single')`
  is false → **purple-to-red is filtered out before scoring.** Its name ("Purple to Red") —
  a perfect 2-color match — is never seen. The gate trusts incomplete OpenPrintTag *hex* data
  over the name.

**Case 2 — polymer-family gate + dropped descriptor.**
SM `ColorFabb · PLA Woodfill` should match `colorfabb-woodfill`, but matches `steelFill (68%)`.
Evidence:
- ColorFabb composites are inconsistently typed in OpenPrintTag: `colorfabb-woodfill`,
  `bronzefill`, `copperfill`, `corkfill`, `glowfill` are **type=PHA** (family `pha`);
  `colorfabb-steelfill` is **type=PLA** (family `pla`). SM "PLA Woodfill" → family `pla`.
- The polymer-family hard gate (`opentag.py:609-617`) excludes family mismatches → **woodfill
  (pha) is dropped**, steelfill (pla) survives and wins.
- Secondary issue: `decompose_name("woodFill"/"steelFill"/"PLA Woodfill")` → NO colors, NO
  modifiers (the "*fill*" descriptor is residual noise). So even unfiltered, woodfill and
  steelfill are indistinguishable and a tie-breaker picks wrong.

## Root cause (one theme)
The hard gates (color-profile, polymer-family) pre-filter on **metadata** (hex color counts,
`type` family) that is often **incomplete or inconsistent** in OpenPrintTag, and they run
BEFORE the name-driven v2 scorer — so a near-perfect NAME match can be eliminated and never
ranked. v2's scoring is name-first; the gates are still metadata-first.

## The fix (settle exact approach in the plan)

1. **Soften the polymer-family gate** (`opentag.py:609-617`): don't hard-exclude on family
   mismatch. Options (recommend in plan): (a) treat the PLA biopolymer family as one bucket —
   PLA, PHA, PLA/PHA, LW-PLA, HTPLA composites are mutually compatible (ColorFabb literally
   mixes PLA/PHA); and/or (b) convert the gate to a strong score PENALTY instead of exclusion,
   so a near-perfect name match still surfaces while a genuine ASA-vs-PETG mismatch stays low.
   Keep genuinely-incompatible families apart (PC≠PETG≠ASA≠nylon) — the goal is to stop
   punishing closely-related/ inconsistently-typed families, not to drop family signal.
2. **Soften / name-aware color-profile gate** (`opentag.py:598-604`): when the OPT entry's
   hex color data is incomplete, derive the arrangement from the **name's decomposed color
   count** (v2 already produces it) rather than the hex `secondaryColors`. And/or convert the
   gate to a penalty so a full name-color multiset match (weight 0.40) overcomes a profile
   mismatch. Net: `purple-to-red` (2 name colors) must be scored, not filtered.
3. **Capture distinctive residual descriptors.** "*fill*" composites (woodfill, steelfill,
   stonefill, copperfill, bronzefill, corkfill, glowfill, metalfill, …) and similar
   distinctive non-color/non-modifier tokens must contribute to matching so `woodfill`
   matches `woodfill`, not `steelfill`. Options: mine "*fill"-suffix tokens + a seed list as a
   new token category (material-variant), OR add a **residual-overlap** scoring component
   (shared distinctive residual words beyond brand/material/finish/color/modifier) so the name
   still discriminates. Don't rely on the 0.05 string-similarity tie-breaker alone — it's too
   weak and the gate kills the candidate first.

## Plan must also cover
- **No regression:** the AMOLEN "Shiny Gradient Silver & Shiny Blue" #1 and Orange-vs-Copper
  golden cases (test_opentag_golden.py) must still pass, plus a real ASA/PC/PETG cross-family
  pair must STILL be correctly separated after softening the family gate.
- Whether softening gates to penalties needs a re-weight of the score components.
- Performance: gates also exist to shrink the candidate set per filament — confirm softening
  doesn't blow up scoring cost (brand pre-filter still bounds it to one brand's materials).

## Before you start
Read matcher v2 docs/code: `docs/opentag-matching.md`, `backend/app/core/opentag_match.py`
(decompose_name, score_candidate, opt_color_profile, sm_color_profile, profiles_compatible,
material_family), `backend/app/core/opentag_lexicon.py`, `backend/app/api/opentag.py:585-640`
(the gates + candidate selection), `backend/tests/test_opentag_golden.py`. Note the gates were
added pre-v2 (commits around f330344 "polymer-family gate", d2d4d88 "brand-gate").

## Working tree check
`git status --porcelain`; expect clean (matcher v2 is committed at c10a14e). If dirty, list +
ask. This prompt is exempt.

## Step 0 — PLAN before coding (model=opus)
Decide the exact gate-softening approach (hard-relax vs penalty, per gate), the PLA-family
bucket membership, the descriptor-capture mechanism (mined "*fill" category vs residual-overlap
score component) with weights, and the golden/regression test matrix. Confirm ambiguous calls
with the user.

## What to do (after plan agreed)
Implement the gate softening + descriptor capture. Golden tests (extend test_opentag_golden.py):
- `cc3d-temperature-color-change-pla-purple-to-red` ranks #1 for the CC3D temp-change SM
  filament (green-to-yellow strictly below).
- `colorfabb-woodfill` ranks #1 for ColorFabb "PLA Woodfill" (steelfill strictly below).
- AMOLEN + Orange-vs-Copper preserved; a cross-family pair (e.g. ASA vs PETG) stays separated.
Plus unit tests for the softened gates / descriptor matching. Update `docs/opentag-matching.md`
+ `docs/decisions.md`. Backend pytest + ruff; frontend tsc + npm test (sandbox itsdangerous
modules env-only — ignore, no NEW failures).

## When done
Update frontmatter; `git mv` to `prompts/done/`; log the decision; propose ONE `fix:` commit
(specific paths, never `git add -A`) and STOP for the user to run it. Never push.
