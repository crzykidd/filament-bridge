---
name: 2026-06-08-fix-new-spool-conflict-lifecycle
status: done
created: 2026-06-08
model: sonnet
completed: 2026-06-07
result: Both fixes implemented and tested. Dedup guard added to _handle_new_sm_spool and _handle_new_fdb_spool. Clear-on-map pass added after mapped_sm/fdb_spool_ids are built. 4 new tests, 676 passed total.
---

# Task: Fix new_spool conflict lifecycle — dedup + clear when the spool gets mapped

Symptom: an already-synced filament's spools (e.g. SM filament 1's spools 1 [empty] and 47
[used]) show open `new_spool` conflicts ("Spoolman spool N has no FDB filament match") even
though they are now mapped. The conflicts were created on cycles BEFORE the filament was
mapped (02:35–04:16), the mappings were created at 05:23+, and nothing cleared the stale
conflicts. They were also duplicated every cycle (4 each).

Two bugs in `backend/app/core/engine.py`:

1. **No dedup for `new_spool` conflicts.** `_queue_conflict` (line ~176) does an unconditional
   `db.add(Conflict(...))`. The field-conflict passes guard with `_has_open_conflict(...)`
   first, but `_handle_new_sm_spool` (line ~1380) and `_handle_new_fdb_spool` (line ~1496) call
   `_queue_conflict` for `new_spool` WITHOUT that guard → a fresh conflict every cycle.
2. **Stale `new_spool` conflicts are never cleared when the spool becomes mapped** (via the
   wizard OR a later cycle).

## Fix

1. **Dedup at the new-spool sites:**
   - In `_handle_new_sm_spool`, before queuing the `new_spool` conflict, check
     `_has_open_conflict(db, "spool", "new_spool", spoolman_id=sm_spool.id)` and skip queuing
     (still `return`, still count appropriately) if one is already open.
   - In `_handle_new_fdb_spool`, do the same keyed on the FDB spool id
     (`_has_open_conflict(db, "spool", "new_spool", fdb_spool_id=<the fdb spool id it stores>)`).
     Check exactly which id field that path sets on the conflict and match it.
2. **Clear stale `new_spool` conflicts for now-mapped spools** — in the sync cycle, right
   after the spool mappings are loaded (where `mapped_sm_spool_ids` / `mapped_fdb_spool_ids`
   are built, ~line 1642-1646), and only when `not dry_run`: resolve every OPEN conflict with
   `field_name == "new_spool"` whose `spoolman_id` is in `mapped_sm_spool_ids` OR whose
   `filamentdb_spool_id` is in `mapped_fdb_spool_ids`. Mark them resolved
   (`resolved_at = <now>`, `resolution = "auto"` / a clear value like `"resolved_mapped"`,
   `resolved_value` optional) so they leave the open queue. Use the same timestamp approach the
   codebase already uses for datetimes (don't introduce a new now() pattern). Log a sync-log
   line per cleared conflict (optional but nice). This handles both wizard-created and
   engine-created mappings.

Keep deletion-conflict behavior (`DELETION_FIELD`) untouched — this is only about `new_spool`.

## Verification

- `cd backend && pytest` — tests:
  - dedup: invoking `_handle_new_sm_spool` twice for the same unmapped SM spool results in
    exactly ONE open `new_spool` conflict (second call skips via `_has_open_conflict`).
  - clear-on-map: given an open `new_spool` conflict for spool X and a `SpoolMapping` for spool
    X, a (non-dry-run) sync cycle resolves that conflict (it's no longer in the open set).
  - a `new_spool` conflict for a still-unmapped spool is NOT cleared.
  - dry-run does not resolve or create.
- Reason through SM filament 1 / spools 1 & 47: now mapped → their stale `new_spool` conflicts
  are auto-resolved on the next cycle; no new duplicates are created.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md`: `new_spool` conflicts are deduped and auto-resolved once the spool is
   mapped (was piling up + going stale).
3. Non-interactive subagent run: when pytest passes, stage ONLY the files this task touched
   (incl. prompt move + docs) and commit on `dev` with one `fix:` message. Never `git add -A`.
   Never push.
