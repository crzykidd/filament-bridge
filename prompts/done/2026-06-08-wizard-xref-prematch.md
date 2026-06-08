---
name: 2026-06-08-wizard-xref-prematch
status: done
created: 2026-06-08
model: sonnet
completed: 2026-06-07
result: Implemented xref pre-match pass in match_filaments; wizard_matches builds xref map from SM spool extras; 7 new tests added; 667 tests pass.
---

# Task: Wizard recognizes already-linked records via the filamentdb_id cross-reference

The initial-sync wizard shows an ALREADY-SYNCED filament as "unmatched". Example: SM filament
86 ("PLA Silk Shiny Gradient Black & Shiny Red Gold") is mapped to FDB
`6a260f0ebba9189cd60f81de` and its Spoolman spool carries `filamentdb_id` /
`filamentdb_spool_id` extras — yet the wizard lists it unmatched.

Root cause: `match_filaments` (`backend/app/core/matcher.py`) does PURE FUZZY matching on
`_key(vendor, name, color)` and never consults the existing cross-reference IDs. For #86
(multicolor) the SM `color_hex` is None while FDB's `color` is `#000000`, so the fuzzy key
mismatches → unmatched. `wizard_matches` (`backend/app/api/wizard.py:233`) just calls
`match_filaments(sm_filaments, fdb_filaments)` with no xref input.

## Fix — pre-match by existing cross-reference, then fuzzy the rest

1. **`wizard_matches`** (`api/wizard.py`): also fetch Spoolman spools
   (`await request.app.state.spoolman.get_spools()`), and build a map
   `xref_by_sm_filament: dict[int, str]` = `{ spool.filament.id : decode_extra_value(
   spool.extra[<filamentdb_id field>]) }` for spools whose `filamentdb_id` extra is a non-empty
   string. (Use `_settings.spoolman_field_filamentdb_id` for the key; reuse one filament id →
   xref per filament; ignore archived spools.) Pass this map into `match_filaments`.
2. **`match_filaments`** (`core/matcher.py`): accept an optional
   `xref_by_sm_filament: dict[int, str] | None = None`. Run a FIRST pass before fuzzy:
   build `fdb_by_id = {f.id: f for f in fdb_filaments}`; for each SM filament whose
   `xref_by_sm_filament[sm.id]` resolves to an existing FDB filament, append a
   `MatchedPair(sm, fdb, confidence=1.0)` and mark BOTH the sm and that fdb id as consumed so
   they're excluded from the fuzzy pass and from `unmatched_*`. Then run the existing fuzzy
   matching over the REMAINING sm/fdb only. (A stale xref — fdb id no longer present — falls
   through to fuzzy/unmatched, not matched.)
   - Keep backward-compat: `xref_by_sm_filament=None` → behaves exactly as today.
   - Optional: add a `source: str` ("xref" | "fuzzy") to `MatchedPair` (default "fuzzy") so the
     UI/debugging can tell them apart — only if trivial; do not break existing callers/tests.
3. This makes the wizard idempotent on re-run: already-linked records (incl. multicolor ones
   whose color key wouldn't fuzzy-match) are recognized as matched.

NOTE (do NOT fix here): fuzzy matching of multicolor filaments by `color_hex` is a separate
gap (SM multicolor has `color_hex=None`); leave it for a follow-up. This task only adds xref
pre-matching.

## Verification

- `cd backend && pytest` — tests:
  - a SM filament with `xref_by_sm_filament[id]` pointing to an existing FDB filament is
    `matched` (confidence 1.0) even when vendor/name/color would NOT fuzzy-match (e.g.
    multicolor: SM color_hex None, FDB color "#000000"); that FDB filament is not in
    `unmatched_fdb`.
  - a stale xref (fdb id absent) falls through to fuzzy/unmatched.
  - `xref_by_sm_filament=None` (or empty) → identical behavior to before (existing matcher
    tests still pass).
- Reason through SM #86: xref `6a260f…de` exists in FDB → matched, no longer "unmatched".

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md`: the wizard pre-matches records by the `filamentdb_id` cross-reference
   before fuzzy matching, so already-linked records (incl. multicolor) are recognized on re-run.
3. Non-interactive subagent run: when pytest passes, stage ONLY the files this task touched
   (incl. prompt move + docs) and commit on `dev` with one `fix:` message. Never `git add -A`.
   Never push.
