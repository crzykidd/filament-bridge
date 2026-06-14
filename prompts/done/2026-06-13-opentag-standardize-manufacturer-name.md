---
name: 2026-06-13-opentag-standardize-manufacturer-name
status: completed        # pending | completed | failed
created: 2026-06-13
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-13
result: vendor row now surfaces on any visible diff (incl. case-only); apply find-or-creates by exact trimmed name, re-pointing this filament only
---

# Task: OpenTag apply — standardize the manufacturer name (re-point this filament only)

When a Spoolman filament is matched to an OpenPrintTag material, the bridge already maps
name, material, finish tags, color(s), density, diameter, temps, and slug/uuid, and the
apply path already supports re-pointing the vendor (find-or-create vendor → `vendor_id` on
the PATCH). **The gap:** the vendor row is suppressed whenever the SM vendor and OpenTag
brand are equal *after `normalize_vendor`* — so a case/spelling difference like
"Elegoo" → "ELEGOO" is never surfaced and never applied. The manufacturer is therefore
only ever standardized via an explicit alias mapping (e.g. `prusa=prusament`), never for
plain casing differences.

**Decided behavior (user choice): "re-point this filament only."** Surface the vendor row
whenever the raw brand strings differ in any visible way (including case-only), and on
apply find-or-create a vendor with OpenTag's **exact** brand name and point *this* filament
at it. Do NOT rename the existing shared vendor record; do NOT touch other filaments under
the old vendor. It is acceptable (and expected) that a case-only difference creates a
near-duplicate vendor (e.g. a new "ELEGOO" alongside the existing "Elegoo") — the user
explicitly accepted that trade-off.

## Before you start

- Read `CLAUDE.md` (no upstream deletes; vendor is a Spoolman relation, resolved to
  `vendor_id`). Read these specific spots:
  - `backend/app/api/opentag.py:223-257` — `_build_field_rows` (the vendor-suppression
    condition to change is at lines 246-250).
  - `backend/app/api/opentag.py:311-368` — `_build_sm_patch` (extracts the chosen vendor
    NAME; already correct — leave it).
  - `backend/app/api/opentag.py:775-836` — the apply loop's vendor index build +
    `_ensure_vendor` find-or-create (the matching key to change is here).
  - `backend/app/core/opentag_match.py:570-576` — `opt_to_spoolman_fields` already emits
    `result["vendor"] = opt.get("brandName")`. Leave it.
  - `backend/app/core/matcher.py:28-36` — `normalize_vendor` (what's being used today for
    the suppression/lookup; you're moving the vendor comparison + lookup OFF normalized
    and ONTO exact-name for this feature).

## Working tree check

Run `git status --porcelain` first. The reconcile feature was just committed; the tree
should be clean except unrelated dotfiles. If any file this plan touches has uncommitted
changes, list them and ask before editing. This prompt file is exempt.

## What to do

1. **Surface the vendor row on any visible difference** — in `_build_field_rows`
   (`opentag.py:246-250`), change the vendor special-case so the row is OMITTED only when
   the raw strings are equal after a plain `.strip()` (case-sensitive), and INCLUDED
   otherwise. I.e. replace the `normalize_vendor(sm_value) == normalize_vendor(opt_value)`
   suppression with `(sm_value or "").strip() == (opt_value or "").strip()`. Keep the rest
   of the row construction identical (suggested_value = opt brand).

2. **Re-point by exact vendor name on apply** — in `opentag_apply`
   (`opentag.py:781-800`), change the vendor index + `_ensure_vendor` to match by EXACT
   (trimmed) vendor name instead of `normalize_vendor`:
   - Build `vendor_id_by_name: dict[str, int] = {v.name.strip(): v.id for v in existing_vendors}`
     (first occurrence wins is fine; document the choice in a comment).
   - `_ensure_vendor(name)`: `key = name.strip()`; if `key` is empty return `None`; if
     `key in vendor_id_by_name` return that id; else `create_vendor({"name": name})`,
     cache `vendor_id_by_name[key] = created.id`, log, return the id.
   - Everything downstream (`patch["vendor_id"] = vendor_id`, `fields_written` tracking,
     the change-log entry) stays as-is.
   - Add a short comment explaining WHY exact-name (not normalized): standardizing on
     OpenTag's canonical spelling requires distinguishing "Elegoo" from "ELEGOO"; the
     accepted trade-off is that a case-only diff creates a separate canonical vendor and
     re-points only this filament.

3. **Do NOT** rename any existing vendor, and do NOT change other filaments. No new env
   var, no settings toggle — this is the always-on behavior for the apply path.

### Tests (this is where the care is — existing tests assert the OLD behavior)

4. In `backend/tests/test_opentag.py`:
   - **Invert** `test_build_field_rows_vendor_row_absent_when_normalized_match`
     (around line 4705): under the new behavior a case-only difference MUST now surface the
     vendor row. Rename it to `test_build_field_rows_vendor_row_present_when_only_case_differs`
     and assert exactly one vendor row with `spoolman_value == "PRUSAMENT"`,
     `opentag_value == "Prusament"`, `suggested_value == "Prusament"`.
   - **Keep** `test_build_field_rows_vendor_row_absent_when_names_same` (≈4691) — exact-equal
     names must still suppress the row. Verify it still passes.
   - **Keep** `test_build_field_rows_vendor_row_present_when_names_differ` (≈4673) — still valid.
   - **Verify** `test_apply_vendor_resolves_existing_no_duplicate` (≈4727) and
     `test_apply_vendor_creates_when_missing` (≈4801) still pass: both use the exact name
     "Prusament" matching an exact existing/absent "Prusament", so exact-name matching
     preserves them. Fix only if the index change breaks them.
   - **Add** `test_apply_vendor_case_only_diff_creates_canonical_and_repoints`: existing
     vendors = `[SpoolmanVendor(id=5, name="Elegoo")]`; decision vendor field value
     "ELEGOO". Assert `create_vendor` IS called once with `{"name": "ELEGOO"}`, the PATCH
     carries the NEW vendor_id (not 5), and "vendor" is in `fields_written`. This locks in
     the re-point-not-reuse semantics.
   - Run `test_opentag_golden.py` and the rest of the suite; fix any field-row/vendor
     fallout from the surfacing change (e.g. golden snapshots that now include a vendor row).

5. **Frontend check (likely no change):** the OpenTag review UI iterates `fields`
   generically, so the newly-surfaced vendor row should render and flow through apply
   automatically. Confirm by reading `frontend/src/pages/OpenTagCleanup.tsx` — only edit if
   the vendor field is special-cased/hidden there. If `npm test`/`tsc` is unaffected, leave
   the frontend alone.

## Conventions to honor

- Match surrounding style; keep the diff surgical (two code edits + tests).
- **Run the FULL backend suite via a throwaway venv** (sandbox lacks `itsdangerous`, so
  `test_api`/`auth` skip silently otherwise): `python3 -m venv $TMPDIR/v &&
  $TMPDIR/v/bin/pip install -q -r backend/requirements.txt && cd backend &&
  $TMPDIR/v/bin/pytest`. Confirm `test_opentag.py` actually ran. Then `ruff check backend/`,
  and in `frontend/` `npx tsc --noEmit` + `npm test`. All green before proposing the commit.
- If a sandbox restriction blocks the venv pip/pytest, retry with the sandbox disabled.

## When done

1. Update this file's frontmatter: `status`, `completed` (2026-06-13), `result` (one line).
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/` (failure).
3. Record the decision in `docs/decisions.md`: OpenTag apply standardizes the manufacturer
   by re-pointing THIS filament to an exact-named canonical vendor (find-or-create by exact
   name; case-only diffs intentionally create a separate vendor; existing vendor never
   renamed). Update `docs/opentag-cleanup.md` and/or `docs/spoolman-writes.md` if either
   enumerates the vendor-write behavior — ship doc edits in the same commit.
4. Propose ONE commit covering the files this session modified (including the prompt move).
   Present the file list + a one-line `feat:`-prefixed message; ask
   `commit these as "<message>"? (y/n)`. On `y`, stage those specific paths and commit on
   `dev` (never `main`, never `git add -A`, never push, no `Co-authored-by:`).
