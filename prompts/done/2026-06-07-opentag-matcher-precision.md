---
name: 2026-06-07-opentag-matcher-precision
status: completed
created: 2026-06-07
model: sonnet
completed: 2026-06-06
result: arrangement-from-tags (FDB secondaryColors always empty), polymer-family hard gate (PC≠ASA/ASA≠PETG), finish-aware scoring (penalty+stripping); 562 tests pass
---

# Task: Tighten OpenTag matching — arrangement-from-tags, polymer-family gate, finish-aware

A deep-dive audit (the bridge matcher run over the real Spoolman DB + the real 12,501-record
OpenTag cache) found three systematic failures. Fix them.

## Findings (evidence)

1. **Multicolor never matches (all multicolor SM filaments → no-match).** FDB's denormalized
   OpenTag feed leaves **`secondaryColors` EMPTY on all records**; arrangement is only in
   `tags` (`coextruded`, `gradual_color_change`). `opt_color_profile` keys off
   `secondaryColors`, so it labels everything `single` and the profile pre-filter yields 0
   candidates for any multicolor SM filament. The data IS present (e.g. ELEGOO "Silk PLA
   Black Purple" tagged `coextruded`; AMOLEN has 59 coextruded + 72 gradient).
2. **Cross-polymer mismatches:** PC→ASA, ASA→PETG, PLA→PETG matched at 0.5–0.72 (above the
   0.30 threshold). A PC filament must never match ASA.
3. **Finish ignored:** matte↔silk (ELEGOO Matte Mint Green → Silk PLA Mint Green), solid↔
   transparent (Hatchbox Orange → Transparent Orange PLA; True White → Transparent White).
   Finish weight (0.05) too weak; finish words in the OpenTag name inflate the color-name
   score.

## What to do (`backend/app/core/opentag_match.py`, + endpoint if needed)

### 1. Arrangement profile from TAGS (critical)
`opt_color_profile`: derive the profile from the OpenTag `tags`/`optTags` arrangement
(`coextruded`→`coextruded`, `gradual_color_change`/`gradient`→`gradient`) FIRST; only fall
back to `secondaryColors` if no arrangement tag and secondaries exist. (Reuse
`color.arrangement_from_tags`; note OpenTag `tags` are strings, so also check the string
tags.) After this, a coaxial SM filament finds the brand's coextruded OpenTag entries.
- Apply-side guard: in `opt_to_spoolman_fields`, do NOT overwrite Spoolman's
  `multi_color_hexes` when the OpenTag `secondaryColors` is empty (it always is) — keep the
  SM hexes; still set `multi_color_direction` from the arrangement and the material tags.

### 2. Polymer-family hard gate
Add `material_family(s) -> str` normalizing to a base polymer: PLA and PLA+ → `pla`; PETG →
`petg`; ASA → `asa`; ABS → `abs`; PC → `pc`; TPU/TPE → `tpu`; PA/Nylon (incl. PA-CF/PA6) →
`pa`; PVA → `pva`; else the normalized token. Strip finish words first (so "PLA Silk" → pla).
In the matches endpoint, after brand + color-profile filters, ALSO restrict candidates to the
same `material_family` as the SM filament (empty/unknown SM material → don't gate, score all).
This kills PC→ASA / ASA→PETG. (PLA↔PLA+ stay matchable; the distinct grade can still be
preferred by name similarity.)

### 3. Finish-aware scoring
- Compute a finish set for each side from name + tags using the existing
  `material_tags` map / `finish_ids_from_text` (silk, matte, transparent, translucent, cf,
  glow, glitter, etc.). Add a finish component to the score: reward agreement, and PENALIZE a
  mismatch (e.g. solid-vs-silk, matte-vs-silk, solid-vs-transparent) enough to drop a
  wrong-finish candidate below a correct plain/solid one. Give finish a meaningful weight
  (raise from 0.05; e.g. ~0.15 with a negative penalty on clear mismatch).
- **Strip finish words from BOTH names before the color-name comparison** (extend the
  existing color-name token logic to also remove finish keywords), so "Transparent Orange" →
  {orange} and doesn't out-rank a plain "Orange"; the transparent/solid mismatch is then
  handled by the finish component.
- Rebalance weights to sum sensibly (e.g. material 0.20, vendor 0.20, color-name 0.30, finish
  0.15, hex 0.10, arrangement already gated). Keep `min_confidence` ~0.30; adjust only if a
  test shows a correct match dips below.

## Verification

- `cd backend && pytest` — tests:
  - `opt_color_profile` returns `coextruded`/`gradient` from tag strings even when
    `secondaryColors` is empty (the real-data case); a coaxial SM filament now matches a
    coextruded same-brand OpenTag entry.
  - polymer-family gate: a PC SM filament does NOT match an ASA candidate; ASA does not match
    PETG; PLA matches PLA/PLA+.
  - finish: a solid SM filament does NOT pick a "Transparent X" or "Silk X" candidate over a
    plain "X" of the same color; matte does not match silk; finish-word stripping makes
    "Orange" beat "Transparent Orange".
  - existing matcher/endpoint tests still pass (re-tune expected scores, keep ordering
    assertions).
- After implementing, note in the report that the human audit script
  (`/tmp/opentag_audit.py` style: run the matcher over the SM DB + cache) should be re-run
  to measure improvement (the planner will re-run it).

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md`: OpenTag matcher now derives arrangement from tags (FDB feed has empty
   secondaryColors), hard-gates by polymer family, and is finish-aware (penalty + finish-word
   stripping before color-name compare).
3. Non-interactive subagent run: when pytest passes, stage ONLY the files this task touched
   (incl. prompt move + docs) and commit on `dev` with one `fix:` message. Never `git add -A`.
   Never push.
