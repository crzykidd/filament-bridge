---
name: 2026-06-07-opentag-multicolor-aware-match
status: completed
created: 2026-06-07
model: sonnet
completed: 2026-06-06
result: Profile pre-filter (single/coextruded/gradient) + opt_to_spoolman_fields sets multi_color_direction + handles empty primary via fdb_multicolor_to_sm; 538 tests pass
---

# Task: OpenTag matching + apply — make it multicolor/arrangement aware

The OpenTag matcher ignores whether a filament is single-color vs multicolor and its
arrangement, so a multicolor Spoolman filament can wrongly match a solid OpenTag product (or
the wrong arrangement). Spoolman tells us the arrangement; OpenTag encodes it in optTags.
Use it as a hard pre-filter, and complete the multicolor apply mapping.

## Grounding (verified)

- Spoolman: multicolor = `multi_color_hexes` non-empty; `multi_color_direction` is
  `"coaxial"` (18 in the user's DB) or `"longitudinal"` (11).
- Equivalence (already in `backend/app/core/color.py`): **coaxial ↔ coextruded = optTag 29**,
  **longitudinal ↔ gradient = optTag 28** (`TAG_COEXTRUDED=29`, `TAG_GRADIENT=28`,
  `arrangement_from_tags`, `sm_multicolor_to_fdb`/`fdb_multicolor_to_sm`).
- OpenTag OPTMaterial: `color` (primary hex, may be EMPTY for pure dual-color),
  `secondaryColors` (hex[]), `tags` (strings incl. "coextruded"/"gradual_color_change").

## Color-profile model

Define a profile for each side: `single` | `coextruded` | `gradient` | `multi_unknown`.
- Spoolman: no `multi_color_hexes` → `single`; else `coaxial`→`coextruded`,
  `longitudinal`→`gradient`, else `multi_unknown`.
- OpenTag: no `secondaryColors` → `single`; else tag 29 → `coextruded`, tag 28 → `gradient`,
  else `multi_unknown` (also treat the tag string "coextruded"/"gradual_color_change" via the
  existing arrangement detection). Reuse `color.arrangement_from_tags` where possible.

## Phase 1 — Profile pre-filter (matching)

In the matches endpoint (`backend/app/api/opentag.py`), after the brand pre-filter, ALSO
filter candidates to those whose profile is compatible with the SM filament's profile:
- `single` matches only `single`.
- `coextruded` matches only `coextruded`.
- `gradient` matches only `gradient`.
- `multi_unknown` (either side) matches any multicolor profile (lenient), never `single`.
Add a pure helper (e.g. in `opentag_match.py`) `sm_color_profile(sm)` /
`opt_color_profile(opt, tag_map)` and `profiles_compatible(a, b)`. Keep `find_best_match`
pure — pass the already-filtered candidate list (as with the brand filter). A SM filament
with no compatible candidate → no-match.

## Phase 2 — Complete the multicolor apply mapping

In `opentag_match.opt_to_spoolman_fields` (the OpenTag→Spoolman field mapping):
- When the matched OpenTag entry is multicolor, set `multi_color_direction` from its
  arrangement (`coextruded`→`"coaxial"`, `gradient`→`"longitudinal"`).
- Handle empty primary `color`: if `opt["color"]` is empty/absent but `secondaryColors` is
  present, derive `color_hex` + `multi_color_hexes` consistently with the bridge's existing
  `color.fdb_multicolor_to_sm` (for coextruded the primary is the first secondary; for
  gradient the first hex is primary, the rest are secondaries). Prefer REUSING
  `fdb_multicolor_to_sm(opt_color, secondaryColors, opt_tags_as_optTags)` so SM↔FDB stay
  consistent — build the optTags list from the OpenTag arrangement and call it.
- Single-color matches: unchanged (`color` → `color_hex`, no multi fields).

## Verification

- `cd backend && pytest` — tests:
  - profile detection for SM (coaxial/longitudinal/single) and OpenTag (tag 29/28/none,
    empty-primary dual-color).
  - matches endpoint: a coaxial SM filament is matched only against coextruded OpenTag
    candidates (NOT a solid same-brand/material, NOT a gradient); a single SM filament never
    matches a multicolor OpenTag entry; longitudinal↔gradient.
  - `opt_to_spoolman_fields` for a coextruded match sets `multi_color_direction="coaxial"`,
    `multi_color_hexes` from secondaryColors, and a sensible `color_hex` even when `color`
    is empty; gradient sets `"longitudinal"`.
- Reason through the user's data (18 coaxial / 11 longitudinal) matching correctly.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md`: OpenTag matching hard-filters by color profile (single/coextruded/
   gradient) using SM arrangement ↔ optTag 29/28; apply sets multi_color_direction + handles
   empty primary color (reusing color.fdb_multicolor_to_sm).
3. Non-interactive subagent run: when pytest passes, stage ONLY the files this task touched
   (incl. prompt move + docs) and commit on `dev` with one `fix:` (or `feat:`) message.
   Never `git add -A`. Never push.
