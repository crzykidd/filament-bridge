---
name: 2026-06-08-fix-multicolor-direction-required
status: done
created: 2026-06-08
model: sonnet
completed: 2026-06-08
result: Fixed. opt_to_spoolman_fields always sets multi_color_direction when multi_color_hexes is set; multi_unknown defaults to coaxial. 712 tests passing. One existing test (asserting old buggy behavior) updated to reflect correct behavior.
---

# Task: Fix multicolor 422 — multi_color_hexes must always carry a multi_color_direction

Spoolman 422 on OpenTag apply for thermochromic filaments (SM #12, #13 — "temperature color
changing" PLA): `"Multi-color filament must have multi_color_direction set."` These OpenTag
entries have 2 secondary colors and a `temperature_color_change` tag but NO arrangement tag
(coextruded/gradient), so `opt_to_spoolman_fields` classifies them `multi_unknown` and emits
`multi_color_hexes` (2 colors) WITHOUT `multi_color_direction`. Spoolman requires the two
together.

## Root cause

`backend/app/core/opentag_match.py`, the count-based color rule (~lines 210-216): in the
`len(all_hexes) >= 2` branch it sets `multi_color_direction` only `if has_arrangement`. For
`multi_unknown` (no arrangement tag) the direction is omitted → 422.

## Fix

In the `len(all_hexes) >= 2` branch, ALWAYS set `multi_color_direction` whenever
`multi_color_hexes` is set:
- `gradient` arrangement → `"longitudinal"`
- `coextruded` arrangement → `"coaxial"`
- **no/unknown arrangement (multi_unknown)** → default to `"coaxial"` (Spoolman just requires
  *a* direction; coaxial is the safe default — these are thermochromic entries with no real
  spatial arrangement).

Update the rule's comment to say the direction is ALWAYS set for multicolor (defaulting to
coaxial for unknown arrangements), so a future edit doesn't reintroduce the gap. `color_hex`
still must NOT be set alongside `multi_color_hexes`. The `len == 1` / `len == 0` branches are
unchanged.

(If `fdb_multicolor_to_sm` in `backend/app/core/color.py` has any path that could emit
`multi_color_hexes` without a direction, guard it the same way — but the multi_unknown path
goes through opt_to_spoolman_fields directly, so the fix above is the primary one.)

## Verification

- `cd backend && pytest` — tests:
  - `opt_to_spoolman_fields` for a `multi_unknown` entry (2 secondaryColors, a non-arrangement
    tag like `temperature_color_change`, no coextruded/gradient) → emits BOTH `multi_color_hexes`
    AND `multi_color_direction == "coaxial"`, and NO `color_hex`.
  - coextruded (≥2) → `coaxial`; gradient (≥2) → `longitudinal` (unchanged).
  - the single-color (len==1) and len==0 cases unchanged.
- Reason through SM #12/#13: now send `multi_color_hexes` + `multi_color_direction: coaxial`
  → Spoolman 200, not 422.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md`: multicolor writes always include `multi_color_direction` (Spoolman
   requires it with `multi_color_hexes`); multi_unknown defaults to coaxial.
3. Non-interactive subagent run: when pytest passes, stage ONLY the files this task touched
   (incl. prompt move + docs) and commit on `dev` with one `fix:` message. Never `git add -A`.
   Never push.
