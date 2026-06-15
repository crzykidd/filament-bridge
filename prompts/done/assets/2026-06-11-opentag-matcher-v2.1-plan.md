# Signed-off plan — OpenTag matcher v2.1 (soften gates + descriptor capture)

Companion to `prompts/2026-06-11-opentag-matcher-v2.1-soften-gates.md`. Signed off 2026-06-11.

## LOCKED DECISIONS
- **PLA-biopolymer bucket (user-confirmed):** `PLA_BIOPOLYMER_BUCKET = {"pla", "pha",
  "pla/pha", "lw-pla", "htpla", "rpla"}` — mutually gate-compatible. Everything else stays
  strictly separate (ABS, ASA, PETG, PC, PA/nylon, TPU, etc.).
- **Gates stay GATES, not penalties** (preserves candidate-set bounding + the no-match
  multicolor_mismatch UX; avoids re-weighting). Family gate → widened by the bucket;
  color-profile gate → name-aware + softened.
- **Descriptor capture = option (a):** seed/`*fill` composite tokens folded into the MODIFIER
  lexicon (rides the existing 0.15 modifier component → **NO score re-weight**).
- **Bump `LEXICON_VERSION` 2 → 3** (new COMPOSITE_DESCRIPTOR_SEED changes mined output →
  warm caches must re-mine in-process).

## 1. Polymer-family gate (`backend/app/api/opentag.py:609-617`)
Add to `opentag_match.py` (near `material_family`):
```python
PLA_BIOPOLYMER_BUCKET = frozenset({"pla","pha","pla/pha","lw-pla","htpla","rpla"})
def families_gate_compatible(sm_fam, opt_fam) -> bool:
    if not opt_fam or opt_fam == sm_fam: return True
    return sm_fam in PLA_BIOPOLYMER_BUCKET and opt_fam in PLA_BIOPOLYMER_BUCKET
```
- Do NOT collapse LW-PLA/HTPLA to "pla" inside `material_family` (keep the 0.15 material
  component able to reward exact PLA matches; equivalence lives only in the gate). Confirm the
  literal tokens `material_family` emits for these are exactly the bucket strings (PHA→"pha",
  LW-PLA→"lw-pla", HTPLA→"htpla", PLA/PHA→"pla" via prefix, rPLA→"rpla").
- Rewrite the gate to use `families_gate_compatible(sm_fam, material_family(c.get("type") or
  c.get("abbreviation") or "", tag_map))`. woodfill(pha) now passes for a pla SM filament;
  ASA-vs-PETG / PC-vs-PETG stay False.

## 2. Color-profile gate (`opentag.py:598-604`) — name-aware + soft
- Add `opt_color_arity(opt, ...) -> int = max(hex_count, name_color_count)` where
  name_color_count = `sum(decompose_name(opt.name, opt.brandName, opt.type, ...).colors.values())`
  and hex_count = `(1 if opt.color else 0) + len(non-empty secondaryColors)`.
- New `color_profile_compatible_soft(sm_profile, sm_arity, opt, ...)`:
  - If BOTH sides have a real arrangement tag (coextruded/gradient) AND complete hex data →
    keep the existing strict `profiles_compatible` discrimination (don't break legit
    single-vs-multi where data is complete).
  - Otherwise (incomplete/absent arrangement) → keep candidate when `opt_color_arity >= 2`
    for a multicolor SM side, OR both arities ≤ 1.
- sm_arity = `max(name colors count, (1+len(multi_color_hexes.split(","))) if present)`.
- Build the `ngram_index`/`effective_synonyms` ONCE in `opentag_matches` and pass to both the
  gate and `find_best_match` (consistency; avoids per-candidate rebuild). purple-to-red (name
  arity 2) now reaches scoring → 0.40 color multiset ranks it #1 over green-to-yellow.

## 3. Distinctive descriptor capture (option a)
- `opentag_lexicon.py`: add `COMPOSITE_DESCRIPTOR_SEED = frozenset({"woodfill","steelfill",
  "stonefill","copperfill","bronzefill","corkfill","glowfill","metalfill","marblefill",
  "brassfill", ...})`, unioned UNCONDITIONALLY into the modifier lexicon (same as MODIFIER_SEED
  at ~612 and the counts variant ~772). Keep STOP_WORDS as-is (the compound `steelfill` is one
  token, survives `_residual_tokens`).
- `decompose_name` (`opentag_match.py` unigram branch ~255): before the discard `else`, add
  `elif len(tok) >= 6 and tok.endswith("fill"): mods.add(tok)` — catches novel `*fill` names.
- Effect: SM "PLA Woodfill" → modifiers {"woodfill"}; OPT woodfill → {"woodfill"} → Jaccard
  1.0 (+0.15); steelfill → {"steelfill"} → 0.0. woodfill ranks #1. No re-weight (modifiers
  already 0.15).

## 4. Re-weighting — NONE. Weight vector unchanged:
`material 0.15 + brand 0.15 + color-multiset 0.40 + modifier-jaccard 0.15 + finish ±0.10 +
hex 0.05 + string ≤0.05`. Confirm AMOLEN still ranks #1 (unaffected).

## 5. Tests (`backend/tests/test_opentag_golden.py` — make cases appendable via a param table)
- **New:** purple-to-red ranks #1 for CC3D "Temperature Color Change Purple to Red" (green-to-
  yellow strictly below); woodfill ranks #1 for ColorFabb "PLA Woodfill" (steelfill +
  copperfill below).
- **Gate-level units:** the purple-to-red and woodfill candidates are NOT filtered out by the
  gates; `families_gate_compatible`: PLA↔PHA/LW-PLA/HTPLA True, ASA↔PETG False, PC↔PETG False,
  PETG↔PETG True, anything↔"" True.
- **Cross-family regression (proves no over-merge):** ASA "Black" vs a PETG candidate → the
  PETG entry is gate-dropped for the ASA SM filament.
- **Preserved:** AMOLEN #1, Orange-vs-Copper, Hatchbox red single, matte/silk, multiset/jaccard
  units — all still pass.

## 6. Perf: unchanged order — brand pre-filter still bounds candidates to one brand; the gate's
extra `decompose_name` only fires on incomplete-arrangement candidates; build ngram_index once.

## 7. Docs: update `docs/opentag-matching.md` (PLA bucket, name-aware color arity, `*fill`
modifiers) + `docs/decisions.md` (gate-softening + bucket boundary). Bump LEXICON_VERSION note.

## Files: opentag.py, opentag_match.py, opentag_lexicon.py, test_opentag_golden.py,
docs/opentag-matching.md, docs/decisions.md.
