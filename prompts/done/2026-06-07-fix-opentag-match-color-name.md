---
name: 2026-06-07-fix-opentag-match-color-name
status: completed
created: 2026-06-07
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-06
result: Added _color_name_tokens + _name_similarity helpers; rebalanced score_candidate weights (color-name 0.35 dominates); Orange now beats Copper for same brand+material; 509 tests pass.
---

# Task: Fix OpenTag matching — use the color NAME, not just hex proximity

The matcher picks the wrong color variant. Example: Spoolman "Orange / Hatchbox / PETG"
(hex CB6D30) matched "Hatchbox / Copper PETG" (hex AF784D) at 91%, because
`score_candidate` (`backend/app/core/opentag_match.py` ~150-201) scores brand (0.30) +
material (0.40) + hex-proximity (0.20) + finish (0.10) but **never compares the color
NAME**. Within a brand+material, both "Orange" and "Copper" get the full 0.70 baseline, and
the tiebreaker is RGB distance — which is unreliable (CB6D30 is closer in RGB to copper
AF784D than to the OpenTag Orange's hex). The color NAME is the correct discriminator.

## What to do

Add a **name / color-name similarity** component to `score_candidate` and rebalance the
weights so the color name dominates within a brand+material:

Proposed weights (sum ≈ 1.0):
- material/type:        0.25 (exact) / 0.125 (substring)
- vendor/brand:         0.25 (exact) / 0.125 (substring)
- **color-name match:   0.35**  ← new, the key discriminator
- color hex proximity:  0.10
- finish tag overlap:   0.05

Color-name similarity:
- Build a "color name" from each side by stripping vendor + material/type + finish words
  (reuse `normalize_vendor`, `strip_finish_words`, and remove the material token) from the
  names: SM uses `sm.name` (e.g. "Orange"); OpenTag uses `opt.get("name")` (e.g.
  "Copper PETG" → "copper"). Tokenize, normalize, and compute overlap (token Jaccard, or
  containment for single-token color names).
- Score: full 0.35 when the remaining color tokens match (e.g. {"orange"} == {"orange"}),
  partial for partial overlap (e.g. "Pumpkin Orange" vs "Orange"), 0 when disjoint
  ("orange" vs "copper"). If one side has no remaining color token, treat as neutral
  (e.g. half weight) rather than 0 so naming gaps don't nuke an otherwise-good match.
- Add a small helper `_color_name_tokens(name, vendor, material, tag_map) -> set[str]` and a
  `_name_similarity(...)`; keep them pure + unit-tested.

With this, the "Orange" Spoolman filament scores the OpenTag **Orange** Hatchbox PETG above
the **Copper** one (Copper loses the 0.35 name component), fixing the example.

Update the docstring weight list to match. Keep brand pre-filtering (the endpoint) and the
`min_confidence` threshold as-is (re-tune only if a test shows a good match now falls below
0.30 — unlikely since the right match gains the name points).

## Verification

- `cd backend && pytest` — tests:
  - same brand+material, two color variants: a SM "Orange" filament scores the OpenTag
    "Orange" candidate strictly higher than the "Copper" candidate (the reported bug), and
    `find_best_match` returns Orange as best.
  - exact color-name match contributes the full name weight; disjoint names contribute 0;
    partial overlap contributes partial.
  - a SM name with no distinguishable color token degrades gracefully (neutral, not 0) and
    still matches on brand+material+hex.
  - existing matcher tests still pass (adjust expected scores for the rebalanced weights as
    needed, but keep the *ordering* assertions meaningful).
- Reason through the screenshot case: Orange→Orange now wins.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md`: OpenTag matching now weights the color NAME (the key within-
   brand/material discriminator), with hex proximity demoted to a minor signal.
3. Non-interactive subagent run: when pytest passes, stage ONLY the files this task touched
   (incl. prompt move + docs) and commit on `dev` with one `fix:` message. Never
   `git add -A`. Never push.
