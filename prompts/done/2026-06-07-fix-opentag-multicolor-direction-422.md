---
name: 2026-06-07-fix-opentag-multicolor-direction-422
status: completed        # pending | completed | failed
created: 2026-06-07
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-07
result: Removed multi_color_direction assignment from empty-secondaryColors branch; 571 tests pass
---

# Task: Fix OpenTag apply 422 on multicolor — don't set multi_color_direction without hexes

The OpenTag apply errors (Spoolman 422) for multicolor filaments (e.g. SM #86 "Silk
Gradient", longitudinal). Confirmed via Spoolman's log + the bridge error log: `PATCH
/api/v1/filament/86 → 422`.

Root cause: `opt_to_spoolman_fields` in `backend/app/core/opentag_match.py`, in the branch
where OpenTag's `secondaryColors` is EMPTY (always, for FDB's denormalized feed) but an
arrangement tag is present, sets `result["multi_color_direction"] = "coaxial"/"longitudinal"`
WITHOUT setting `multi_color_hexes`. Spoolman rejects a `multi_color_direction` with no
`multi_color_hexes` → 422 → the whole filament PATCH fails.

It's also pointless: the Spoolman filament ALREADY has its correct multicolor hexes +
direction (that's how it was matched — `sm_color_profile` read `sm.multi_color_direction`).
The apply has nothing new to add for multicolor when OpenTag carries no secondary colors.

## What to do

In `opt_to_spoolman_fields`, in the empty-`secondaryColors` branch (the lines ~88-94 that
set `multi_color_direction` to "coaxial"/"longitudinal"): **remove the
`multi_color_direction` assignment entirely.** When OpenTag provides no `secondaryColors`,
emit NO `multi_color_*` fields at all — leave Spoolman's existing multicolor data untouched.
(The `if secondary:` branch, which DOES set both hexes and direction together, is unchanged
and remains correct for any future feed that populates `secondaryColors`.)

Update the inline comment to reflect that we intentionally don't touch SM multicolor fields
when OpenTag has no secondary colors.

## Verification

- `cd backend && pytest` — tests:
  - `opt_to_spoolman_fields` for a multicolor (coextruded/gradient-tagged) OpenTag entry with
    EMPTY `secondaryColors` returns a field dict that contains NEITHER `multi_color_direction`
    NOR `multi_color_hexes` (so the SM PATCH won't 422). Native fields (material, density,
    finish tags) are still present.
  - a (hypothetical) OpenTag entry WITH `secondaryColors` still sets both
    `multi_color_hexes` and `multi_color_direction` together (existing behavior).
  - update any existing test that asserted `multi_color_direction` is set for the empty-
    secondaries case.
- Reason through: SM #86 (longitudinal) now produces a PATCH with no multi_color_* fields →
  no 422 → applies cleanly.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md`: OpenTag apply no longer writes `multi_color_direction` when OpenTag
   has no `secondaryColors` (Spoolman 422s direction-without-hexes; SM already has the
   arrangement).
3. Non-interactive subagent run: when pytest passes, stage ONLY the files this task touched
   (incl. prompt move + docs) and commit on `dev` with one `fix:` message. Never
   `git add -A`. Never push.
