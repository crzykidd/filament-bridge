---
name: 2026-06-08-fix-single-hex-multicolor-422
status: done
created: 2026-06-08
model: sonnet
completed: 2026-06-07
result: >
  Count-based color rule implemented in opt_to_spoolman_fields and fdb_multicolor_to_sm.
  opt_color_profile updated to treat < 2 secondaryColors as single. SM #21 now emits
  color_hex: 963877 (not multi_color_hexes). 660 tests pass.
---

# Task: Fix single-color "multicolor" 422 — a lone hex must be color_hex, not multi_color_hexes

Spoolman 422s on the OpenTag apply for filament 21 (a thermochromic
"Temperature Color Change PLA Purple to Red"): `"Must specify at least two colors in
multi_color_hexes"`, input `multi_color_hexes:"963877"` (a SINGLE hex). The OpenTag entry has
ONE `secondary_color` (#963877), no `primary_color`, and a `temperature_color_change` tag
(NOT an arrangement tag). So `opt_to_spoolman_fields` hits the `multi_unknown` branch and emits
a one-hex `multi_color_hexes` → invalid.

## Root cause

`backend/app/core/opentag_match.py` `opt_to_spoolman_fields`, the color block (~lines 187-220).
The `multi_unknown` branch (secondaries present but no arrangement tag) sets `multi_color_hexes`
to whatever hexes exist — even a single one — and (if a primary exists) would set BOTH
`color_hex` and `multi_color_hexes`. Spoolman requires `multi_color_hexes` to have ≥2 colors,
and forbids both fields together.

## Fix — count-based color rule

Rewrite the color block so the single/multi decision is based on the COUNT of distinct hexes
(primary + secondaries), not on the branch:

1. Build `all_hexes` = primary (if any) followed by secondaries, each normalized
   (`lstrip("#").upper()`), de-duplicated, order-preserving.
2. Let `has_arrangement = arrangement in ("coextruded", "gradient")`.
3. Decide:
   - **`len(all_hexes) >= 2`** → multicolor: `result["multi_color_hexes"] = ",".join(all_hexes)`;
     set `multi_color_direction` = `"coaxial"` (coextruded) / `"longitudinal"` (gradient) only
     when `has_arrangement`; **never set `color_hex`** (Spoolman 422s on both).
   - **`len(all_hexes) == 1` and NOT `has_arrangement`** → single color:
     `result["color_hex"] = all_hexes[0]`; no `multi_color_*`. (This is the thermochromic /
     one-secondary case — #21.)
   - **`len(all_hexes) == 1` and `has_arrangement`** → we only have partial multicolor data;
     emit NO color fields (leave Spoolman's existing `multi_color_*` untouched — writing a lone
     `color_hex` would 422 against an existing `multi_color_hexes`).
   - **`len(all_hexes) == 0`** → emit no color fields (preserves the existing
     "arrangement tag but empty secondaryColors → leave Spoolman's multicolor alone" behavior).
   Preserve the existing explanatory comments about why we don't touch `multi_color_*` when we
   lack the hexes.

4. **Also guard `fdb_multicolor_to_sm`** (`backend/app/core/color.py`): if the assembled
   multicolor hex list has fewer than 2 entries, fall back to single — return
   `{color_hex: <the one hex or None>, multi_color_hexes: None, multi_color_direction: None}` —
   so the engine multicolor sync can never emit a one-hex `multi_color_hexes` either.

5. **opt_color_profile** (`opentag_match.py`): in the no-arrangement-tag fallback, treat
   `< 2` `secondaryColors` as `single` (not `multi_unknown`) — a one-color entry isn't
   multicolor. (Keep the tag-based coextruded/gradient classification as-is.)

## Verification

- `cd backend && pytest` — tests:
  - thermochromic case: opt with one `secondaryColors` hex, no primary, no arrangement tag →
    `opt_to_spoolman_fields` sets `color_hex` to that hex and emits NO `multi_color_hexes` /
    `multi_color_direction`.
  - 2 secondaries + coextruded tag → `multi_color_hexes` (2 hexes) + `coaxial`, NO `color_hex`.
  - 2 colors, no arrangement tag → `multi_color_hexes` (2), no direction, no `color_hex`.
  - 1 color + coextruded tag → no `color_hex` and no `multi_color_hexes` (leave Spoolman's).
  - single primary only, no secondaries, no arrangement → `color_hex`.
  - `fdb_multicolor_to_sm` with one secondary → single (`color_hex`, no `multi_color_hexes`).
  - `opt_color_profile`: one-color, no-arrangement entry → `single`.
  - Existing multicolor tests still pass.
- Reason through SM #21: now emits `color_hex: 963877` (single) → Spoolman 200, not 422.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md`: a lone color is written as `color_hex`, never a single-hex
   `multi_color_hexes` (Spoolman requires ≥2); thermochromic/one-color OpenTag entries are
   treated as single-color.
3. Non-interactive subagent run: when pytest passes, stage ONLY the files this task touched
   (incl. prompt move + docs) and commit on `dev` with one `fix:` message. Never `git add -A`.
   Never push.
