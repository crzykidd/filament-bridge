---
name: 2026-06-08-fix-multicolor-both-colorhex-422
status: completed
created: 2026-06-08
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-07
result: fdb_multicolor_to_sm returns color_hex=None for both multicolor branches; engine omits color_hex when None; 631 tests pass
---

# Task: Fix multicolor 422 — never send both color_hex and multi_color_hexes to Spoolman

Spoolman rejects a filament PATCH that sets BOTH `color_hex` and `multi_color_hexes`
("Value error, Cannot specify both color_hex and multi_color_hexes"). The OpenTag cleanup
(and the multicolor sync) hits this for coaxial/coextruded filaments — confirmed on SM #7
and #147. Spoolman's multicolor representation is `multi_color_hexes` (comma-separated, first
hex is the primary) + `multi_color_direction`, with `color_hex` UNSET.

## Root cause

`backend/app/core/color.py` `fdb_multicolor_to_sm` sets `color_hex` in BOTH multicolor
branches:
```python
if arrangement == "coextruded":
    return {"color_hex": sec[0] if sec else None,            # ← should be None
            "multi_color_hexes": ",".join(sec) if sec else None,
            "multi_color_direction": "coaxial"}
if arrangement == "gradient":
    primary = to_sm_color(color)
    all_hexes = ([primary] if primary else []) + sec
    return {"color_hex": primary,                            # ← should be None
            "multi_color_hexes": ",".join(all_hexes) if all_hexes else None,
            "multi_color_direction": "longitudinal"}
```
(#86 gradient only worked because its OpenTag primary `color` was empty → `color_hex` was
None by accident.) The docstring's claim "Spoolman has no null-primary concept" is wrong —
multicolor filaments correctly have `color_hex` unset.

## What to do

1. **`fdb_multicolor_to_sm`** (`color.py`): for BOTH multicolor branches, return
   `"color_hex": None` and put ALL colors in `multi_color_hexes` (first = primary):
   - coextruded: `multi_color_hexes = ",".join(sec)`, `color_hex = None`, `coaxial`.
   - gradient: `all_hexes = ([primary] if primary else []) + sec`,
     `multi_color_hexes = ",".join(all_hexes)`, `color_hex = None`, `longitudinal`.
   Update the docstring (multicolor → `multi_color_hexes` only; `color_hex` is None).
   The single-color branch (returns `color_hex` only) is unchanged.

2. **Omit `color_hex` when None at the write sites** so Spoolman never sees both:
   - `opt_to_spoolman_fields` (`backend/app/core/opentag_match.py`) already guards
     (`if sm_color["color_hex"] is not None:`), so with the fix it simply won't emit a
     `color_hex` field for multicolor. Verify it also doesn't emit an empty/None one.
   - The engine multicolor FDB→SM write (`backend/app/core/engine.py` `_sync_multicolor`):
     build the `update_filament` payload so `color_hex` is OMITTED when None (don't send
     `{"color_hex": None, "multi_color_hexes": ...}`). For single-color it still sends
     `color_hex` and (None/absent) `multi_color_hexes`.

3. Check `sm_multicolor_signature` / SM-side mc-sig still computes consistently when a
   coextruded SM filament has `color_hex=None` (the new canonical) — no flapping. Adjust if a
   test asserted the old synthesized `color_hex`.

## Verification

- `cd backend && pytest` — tests:
  - `fdb_multicolor_to_sm` coextruded → `{color_hex: None, multi_color_hexes: "<all>",
    multi_color_direction: "coaxial"}`; gradient → `color_hex: None`,
    `multi_color_hexes` = primary+secondaries, `longitudinal`. Single-color unchanged.
  - `opt_to_spoolman_fields` for a coaxial/coextruded OpenTag match yields a field dict that
    contains `multi_color_hexes` + `multi_color_direction` but NO `color_hex` key (so the
    apply PATCH can't trip the "both" 422). Same for gradient.
  - engine `_sync_multicolor` FDB→SM payload omits `color_hex` when None; still sends it for
    single-color.
  - update any existing multicolor test that expected the synthesized coextruded `color_hex`.
- Reason through SM #7 / #147 (coaxial): apply now sends only `multi_color_hexes` →
  Spoolman 200, not 422.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md`: Spoolman multicolor uses `multi_color_hexes` only (first hex =
   primary); the bridge never sets `color_hex` for multicolor (was causing 422).
3. Non-interactive subagent run: when pytest passes, stage ONLY the files this task touched
   (incl. prompt move + docs) and commit on `dev` with one `fix:` message. Never
   `git add -A`. Never push.
