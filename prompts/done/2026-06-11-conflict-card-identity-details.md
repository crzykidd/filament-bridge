---
name: 2026-06-11-one-conflict-per-item-plus-identity
status: completed
created: 2026-06-11
model: sonnet
completed: 2026-06-11
result: Both bugs fixed. Bug 1: _upsert_new_record_conflict helper (delete-then-insert) replaces old check-then-skip pattern; conflict_type stored as 'new_filament'/'new_spool' for clarity; classifyConflict already keys on field_name so no UI change needed there. Bug 2: identity JSON blob (vendor/name/color_hex/material) stored in spoolman_value/filamentdb_value at queue time; _conflict_identity reads blob as fallback when no snapshot exists; ConflictDetail panel renders vendor·name (id) line with ColorDisplay swatch. All gates pass (784 backend, 72 frontend).
---

# Task: One open conflict per item (replace-on-resync) + show identity on the cards

The new-record handling (commit 07e3809) accumulates DUPLICATE conflicts and shows no
identity. Verified live: 155 `new_filament` conflict rows for only **138 distinct** filaments
(re-queued every cycle), all stored with the wrong `conflict_type='cross_system'`, and cards
show only "SM #136" with no name/vendor/color. Two fixes.

> Scope note (decided with user): the *count* of unsynced records is NOT the problem — one
> conflict per unsynced filament/spool is acceptable. The bug is **duplicates** and **no
> info**. Do NOT add aggregation / ignore-policy / flood-suppression here.

## Bug 1 — exactly ONE open conflict per item; replace on every re-sync

**Desired behavior (user-specified, option B — unconditional replace):** each sync cycle, for
each item (filament or spool) that currently meets a conflict condition, **DELETE any existing
OPEN conflict for that same item+type and INSERT the fresh one.** Net invariant: at most one
open conflict per `(item, conflict-kind)` at all times, and its stored reason always reflects
the latest cycle. No "is the reason the same?" diffing — just delete-old-add-new (simplest,
always-current). This also **auto-collapses the current 155→138 duplicates on the next sync**
(no manual purge needed).

Implementation:
- The duplication comes from the new_filament queue path added in 07e3809: conflicts are
  written with `conflict_type='cross_system'` but the `_has_open_conflict` dedup guard looks
  for them under a different key, so it never matches → re-queues. (new_spool is 154/154, no
  dupes — its guard already works; match its behavior.)
- Replace the "queue only if not _has_open_conflict" pattern for new_filament (and verify
  new_spool) with a small **upsert-by-item** helper: before inserting, `DELETE FROM conflicts
  WHERE resolved_at IS NULL AND <item match> AND <kind match>`, then insert the fresh row.
  - `<item match>` = `spoolman_id = :id` for SM-side, `filamentdb_filament_id`/
    `filamentdb_spool_id` for FDB-side.
  - `<kind match>` = the `field_name` discriminator (`'new_filament'` / `'new_spool'`). Pin
    the stored `conflict_type` to a CONSISTENT value and make the queue write, the upsert
    delete, and the `Conflicts.tsx classifyConflict` all agree on it. (Either a real
    `conflict_type='new_filament'`/`'new_spool'`, or keep `cross_system` and key everything on
    `field_name` — pick one; recommend a distinct conflict_type for clarity, but check the UI
    classifier + any existing migrations/tests first.)
- Keep this scoped so it never deletes a DIFFERENT open conflict on the same item (e.g. a
  genuine cross_system field conflict on a mapped record must not be wiped by a new_record
  upsert) — match on item AND kind, never item alone.
- **Test:** run two sync cycles over the same unmapped filament + spool → exactly ONE open
  new_filament and ONE open new_spool conflict remain (not two); a pre-seeded duplicate is
  collapsed to one on the next cycle; an unrelated cross_system conflict on a mapped item
  survives the upsert.

## Bug 2 — identity on new_filament / new_spool cards

Cards show only the bare id. The conflict row stores a description string (e.g. `"Spoolman
filament 136 has no FDB match; spool 159 is held until the filament is imported"`) but no
vendor/name/color, and these unmapped records have no snapshot, so the existing snapshot-based
card enrichment has nothing.
- **Fix:** when queuing (engine, in the same upsert path), persist the record's
  **vendor · name · color_hex · material** as a JSON blob in `spoolman_value` /
  `filamentdb_value` (the engine holds the SM/FDB object at queue time). Backward-compatible:
  a non-JSON legacy value → plain-string fallback.
- Surface it in `backend/app/api/conflicts.py` (extend the conflict row schema with optional
  `vendor` / `name` / `color_hex`, default None; parse the JSON blob; prefer existing
  snapshot enrichment for conflict kinds that have snapshots — don't regress those).
- Render **vendor · name + color swatch** on the card in `frontend/src/pages/Conflicts.tsx`
  (reuse `ColorDisplay`/`ColorSwatch`), leading with the human identity, id in parens — e.g.
  *"New filament (Spoolman) — ELEGOO · PLA Wood filled · 🟤 (SM #136)"*. Degrade gracefully
  for legacy rows without the blob.

## Before you start
Read the new-record paths in `backend/app/core/engine.py` (`_handle_new_sm_spool` ~1973,
`_handle_new_fdb_spool` ~2093, the new_filament queue path from 07e3809,
`_queue_conflict`/`_has_open_conflict`), `backend/app/api/conflicts.py`,
`backend/app/models/conflict.py`, `backend/app/schemas/api.py`,
`frontend/src/pages/Conflicts.tsx`, `docs/conflicts.md`.

## Working tree check
`git status --porcelain`; expect clean (HEAD c10a14e + queued prompts). If dirty, list + ask.

## Tests + gates
Bug 1 dedup/upsert tests (above) + conflict_type/classifier agreement; Bug 2 identity
persisted + surfaced + legacy fallback + a Conflicts.test.tsx render assertion. Backend
pytest + ruff; frontend tsc + npm test (sandbox itsdangerous modules env-only — ignore, no NEW
failures).

## When done
Update frontmatter; `git mv` to `prompts/done/`; update `docs/conflicts.md` (one-per-item
replace semantics + card identity); propose ONE `fix:` commit (specific paths, never
`git add -A`) and STOP for the user to run it. Never push.
