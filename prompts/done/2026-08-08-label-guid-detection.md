---
name: 2026-08-08-label-guid-detection
status: done
created: 2026-08-08
model: sonnet
completed: 2026-08-08
result: >
  Detection now keys on the FDB spool GUID (sm_xref_fdb_spool_ids built from
  sm_spools_all's filamentdb_spool_id extra), not the label-presence check.
  Both SM-id-into-label writebacks (engine.py _handle_new_fdb_spool,
  wizard.py _execute_fdb_to_spoolman) are now conditional on label being
  blank. Added README ALERT, 3 backend tests
  (tests/test_fdb_label_guid_detection.py), CHANGELOG [Unreleased] entry,
  and docs/decisions.md entry (index regenerated). 1491 backend tests pass,
  ruff clean. Fixes #87.
---

# Task: FDB→SM new-spool detection by GUID, not the user-set `label` (Fixes #87)

The bridge's FDB→Spoolman new-spool pass decides "already synced?" by checking whether the
FDB spool `label` is non-empty. `label` is a **user-supplied** field; the bridge only stuffs the
Spoolman spool ID into it as a convenience when it's blank. The real cross-reference is the **FDB
spool GUID** (stored on the Spoolman side in the `filamentdb_spool_id` extra and in SQLite
`SpoolMapping`). Because detection keys on `label`, a spool the user hand-labels (e.g. via FDB
1.73.0's "Next #") is wrongly treated as synced and **never created in Spoolman**. Fix: detect by
GUID, and never overwrite a user-set `label`.

## Before you start

- Read `CLAUDE.md` (esp. "Sync engine — hard invariants" and "What NOT to do") and the sync-model
  pointer. Honor the `code-checkin-and-pr` standard: work on `dev`, conventional-commit prefix,
  **no `Co-authored-by:` trailers, do NOT push**.
- This is issue **#87** — read it (`gh issue view 87`) for the full model/bug/fix write-up.
- Spoolman extra values are JSON-encoded — decode with `decode_extra_value` (see `core/fields.py`
  and existing use at `core/dryrun.py:119`). Encode with `encode_extra_value`.

## Working tree check

Run `git status --porcelain` first. The tree should be clean except this prompt. If
`backend/app/core/engine.py`, `backend/app/api/wizard.py`, `README.md`, or `CHANGELOG.md` have
uncommitted changes, stop and ask before touching them.

## What to do

1. **Detect by GUID (backend/app/core/engine.py, FDB→SM new-spool loop ~4235-4250).**
   - Before the `for fdb_f in fdb_filaments_all:` loop that handles `new_spool_direction in
     ("two_way", "filamentdb_to_spoolman")`, build a set of FDB GUIDs already referenced by
     Spoolman spools:
     ```python
     sm_xref_fdb_spool_ids = {
         gid for s in sm_spools_all
         if (gid := decode_extra_value(s.extra.get(_settings.spoolman_field_filamentdb_spool_id)))
     }
     ```
     (`sm_spools_all` is in scope — see engine.py:3064. Confirm `decode_extra_value` is imported;
     add the import if needed.)
   - In the inner loop, **replace** the `label_val` skip:
     ```python
     if fdb_spool.id in mapped_fdb_spool_ids:
         continue
     label_val = getattr(fdb_spool, fdb_field_name, None)
     if label_val:
         continue   # <-- DELETE these two lines
     ```
     with a GUID-based cross-ref-orphan skip:
     ```python
     if fdb_spool.id in mapped_fdb_spool_ids:
         continue
     if fdb_spool.id in sm_xref_fdb_spool_ids:
         continue   # already in Spoolman (SpoolMapping lost) — don't duplicate
     ```
     Do NOT rebuild the mapping here — out of scope; skipping to avoid duplicates preserves
     today's behavior.

2. **Conditional writeback — never overwrite a user `label`.**
   - `engine.py:2961` (inside `_handle_new_fdb_spool` auto_import) currently writes the SM ID into
     the label unconditionally. Guard it so it only writes when the label is blank:
     ```python
     if not getattr(fdb_spool, fdb_field_name, None):
         await filamentdb.update_spool(fdb_filament.id, fdb_spool.id,
                                       {fdb_field_name: str(new_sm_spool.id)})
     ```
   - Apply the same "only if blank" guard to the wizard's parallel writeback at
     `backend/app/api/wizard.py:2264` (`update_spool(... {fdb_field_name: str(new_sm_spool_id)})`).
     The wizard create-payload at `wizard.py:2008` is a *fresh* spool create — leave it as-is
     (no pre-existing user value to protect).

3. **README ALERT.** Add a visible callout (near the sync/known-behavior section, or top-level
   caveats — match existing README alert style) with this content, worded cleanly:
   > **⚠️ ALERT — spool labels:** If you want the Filament DB spool **label** (friendly spool ID)
   > to equal the Spoolman spool ID, **leave it blank** — the bridge fills a blank label with the
   > Spoolman spool ID on sync. If you put your own value in `label`, the bridge keeps it (never
   > overwrites it) and still syncs the spool via its internal GUID, but that label will no longer
   > match the Spoolman ID.

4. **Tests** (`backend/tests/`, follow existing engine-test patterns, e.g.
   `test_stale_new_filament_cleanup.py`):
   - New FDB spool **with a user `label`** and no mapping/xref → imported to Spoolman (reaches
     `_handle_new_fdb_spool`), and the existing `label` is **NOT** overwritten.
   - New FDB spool **with blank `label`** → imported; `label` receives the SM ID.
   - FDB spool whose GUID is already in a Spoolman spool's `filamentdb_spool_id` extra but has
     **no `SpoolMapping`** → **not** imported/duplicated.

5. **CHANGELOG.md** — add an entry under `## [Unreleased]` (fix:) naming the behavior change and
   `Closes #87`.

## Conventions to honor

- Match surrounding code style; keep the anti-ping-pong invariant (refresh snapshots after any
  write) if you touch propagation — but this change is detection + a conditional write, so no new
  snapshot handling should be needed beyond what `_handle_new_fdb_spool` already does.
- Run before committing: `cd backend && .venv/bin/python -m pytest` and
  `.venv/bin/python -m ruff check backend/`. All green.

## When done

1. Update this file's frontmatter (`status`, `completed`, `result`), then `git mv` it to
   `prompts/done/`.
2. Add a `docs/decisions.md` entry (2026-08-08) recording the label-is-user-field / detect-by-GUID
   decision; re-run `scripts/gen-decisions-index.py` (add the heading to that script's CATEGORIES
   first) so the index matches.
3. Commit on `dev` (never `main`, never push) with a `fix:` message ending its body with
   `Fixes #87`. Stage only the specific paths you changed (never `git add -A`). Report the final
   `git diff --stat` and the commit hash.
