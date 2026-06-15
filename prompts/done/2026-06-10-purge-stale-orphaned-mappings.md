---
name: 2026-06-10-purge-stale-orphaned-mappings
status: done
created: 2026-06-10
model: sonnet
completed: 2026-06-10
result: Implemented _purge_stale_mapping helper + Branch A/B stale checks in engine.py. Branch B: FDB gone + SM cross-ref cleared → purge + auto-resolve open deletion conflict. Branch A: both sides gone → purge. Kept conflict path when live link remains. Added orphaned FilamentMapping cleanup after spool loop. Updated 3 existing tests to set SM cross-ref where still-linked behavior is expected. Added 5 new tests; 887 tests green.
---

# Task: Purge stale orphaned spool mappings (deleted upstream + no live link) instead of leaving them in Synced Records

## The bug

A user deleted all filaments from Filament DB and cleared the Spoolman `filamentdb_id`
cross-reference fields. The **Dashboard shows 0 synced records**, but the **Synced Records
page still lists 3 rows in "conflict" status that show stale field values** when expanded.

Root cause (verified): the engine detects the missing FDB records and queues
`__record_deleted__` (deletion) conflicts, but per the "never delete without user action"
rule it does **not** remove the local `SpoolMapping`/`Snapshot` rows — those only get cleaned
by `_cleanup_orphaned_mapping()` (`api/conflicts.py`) when a human resolves the deletion
conflict. So `build_mapping_rows()` (`api/mappings.py`) keeps listing the orphaned mappings
and renders their stale local snapshot values (`_mp_*`, weights). The Dashboard counts only
`status=="in_sync"` so it shows 0 — hence the divergence.

## The intended behavior (decided with the user)

A deletion conflict is only warranted when there is a **live, still-linked counterpart to
protect** (don't silently delete a surviving, still-linked record — ask). Otherwise it's a
**stale connection** and the bridge should just **remove the mapping from its own DB** (no
conflict, no asking):

- **One side deleted, the OTHER side still exists AND is still linked** → keep current
  behavior: queue a `__record_deleted__` deletion conflict (ask the user whether to delete the
  surviving side too).
- **Both sides gone**, OR **deleted on Filament DB and the Spoolman spool no longer carries the
  `filamentdb_spool_id` cross-reference** (user cleared it / unlinked) → **stale connection**:
  purge the `SpoolMapping` + its `Snapshot` rows from the bridge DB and resolve/close any open
  deletion conflict for it. No conflict surfaced.

This makes a full wipe (like the user's) self-clear on the next sync cycle so Synced Records
matches the Dashboard, while genuine one-sided deletions of still-linked records still prompt.

## Before you start

- Read `CLAUDE.md` ("Never delete records in either upstream without explicit user action" —
  note this fix deletes only **bridge-local** mapping/snapshot rows, never upstream records),
  and the existing deletion flow in `backend/app/api/conflicts.py:_cleanup_orphaned_mapping`.
- `git status --porcelain` first; tree should be clean. Note a parallel agent may be editing
  `frontend/src/pages/Wizard/StepNPreview.tsx` (dark-mode fix) — do not touch frontend files.
- Standards: `code-checkin-and-pr` (work on `dev`, Conventional-Commits prefix).

## Where the logic lives

`backend/app/core/engine.py`, the mapped-spool-pair loop (~lines 2243–2312):
- **Branch A** (~2247): `sm_spool is None` and `mapping.spoolman_spool_id not in sm_all_ids`
  → Spoolman spool gone. Currently always `_queue_deletion_conflict(..., deleted_side="spoolman")`.
- **Branch B** (~2294): `fdb_entry is None` (FDB spool gone), Spoolman spool present.
  Currently always `_queue_deletion_conflict(..., deleted_side="filamentdb")`.

`_queue_deletion_conflict` is at ~214. `fdb_spool_index` maps `filamentdb_spool_id → (fil_id, spool)`.
`sm_spool.extra` is the Spoolman spool's extra-field dict; decode with
`decode_extra_value` (`app.schemas.spoolman`). The cross-ref field key is
`_settings.spoolman_field_filamentdb_spool_id`.

## What to do

### 1. Add a "stale connection" check before queuing a deletion conflict

Define stale = no live, linked counterpart to protect:

- **Branch A (Spoolman spool gone):** if the FDB spool is also absent
  (`mapping.filamentdb_spool_id not in fdb_spool_index`) → **stale → purge** (both gone).
  Otherwise (FDB spool present) → keep current `_queue_deletion_conflict(deleted_side="spoolman")`.
- **Branch B (FDB spool gone, Spoolman spool present):** read the surviving Spoolman spool's
  cross-ref: `decode_extra_value(sm_spool.extra.get(_settings.spoolman_field_filamentdb_spool_id))`.
  If it is empty/`None`/blank (unlinked — the cross-ref was cleared) → **stale → purge**.
  If it still holds a value (still linked to the now-deleted FDB spool) → keep current
  `_queue_deletion_conflict(deleted_side="filamentdb")`.

### 2. Add a purge helper

`_purge_stale_mapping(db, cycle_id, mapping, *, reason: str)`:
- Delete the `SpoolMapping` row.
- Delete its spool `Snapshot` rows: `("spoolman","spool",str(mapping.spoolman_spool_id))` and
  `("filamentdb","spool",mapping.filamentdb_spool_id)` (mirror `_cleanup_orphaned_mapping`).
- Resolve any open `__record_deleted__` `Conflict` for this mapping (match on
  `field_name==DELETION_FIELD`, `spoolman_id==mapping.spoolman_spool_id`,
  `filamentdb_spool_id==mapping.filamentdb_spool_id`, `resolved_at IS NULL`): set
  `resolved_at=now`, `resolution="auto_stale_purge"` (leaves the open queue, keeps an audit row).
- Emit a sync_log entry via `_log(... "auto","info","spool", ... error_message=reason)`.
- Increment `result.skipped` (not `result.conflicts`).

Call it from the two stale branches in the **non-dry-run** path. In **dry_run**, instead append
a `result.preview` entry (`action:"skip"`, reason e.g. `"stale connection — would remove from
bridge (upstream deleted, no live link)"`) and do NOT mutate the DB.

This runs every cycle, so the user's existing 3 orphans (FDB gone + Spoolman unlinked) get
purged + their deletion conflicts auto-resolved on the next real sync cycle.

### 3. (Secondary) Orphaned FilamentMappings

After the spool loop, prune `FilamentMapping` rows that (a) are not `is_synthetic_parent`,
(b) have no remaining `SpoolMapping` referencing them, AND (c) whose `filamentdb_id` is absent
from the current FDB fetch — deleting their filament-level `Snapshot` rows too (the `_mp_*` /
`_cost` baselines `_build_detail` reads). Keep this conservative: only when clearly orphaned.
If this materially expands scope, implement it but call it out in your report.

### 4. Tests (`backend/.venv/bin/python -m pytest`)

Add to the engine tests (mirror existing deletion-conflict tests):
- Branch B, Spoolman spool present but cross-ref `filamentdb_spool_id` cleared → mapping + its
  snapshots purged, NO deletion conflict queued, and a pre-existing open deletion conflict for
  it is marked resolved (`auto_stale_purge`).
- Branch B, Spoolman spool present and cross-ref still set → deletion conflict queued (current
  behavior preserved, NOT purged).
- Branch A, both sides gone → purged.
- Branch A, Spoolman gone but FDB spool present → deletion conflict queued (preserved).
- dry_run → preview entry, DB unchanged.

## Conventions

- Never touch upstream records — bridge-local rows only.
- Match existing `_log` / `result` patterns and the `_cleanup_orphaned_mapping` deletion shape.

## When done

1. Update frontmatter (`status`/`completed`/`result`); `git mv` this file to `prompts/done/`.
2. Record the rule in `docs/decisions.md`: deletion conflict only when a live linked counterpart
   exists; otherwise purge the stale bridge mapping (+snapshots, +auto-resolve its deletion conflict).
3. **Do NOT commit or push.** Leave changes in the working tree and report: file-by-file summary,
   exact pytest counts, anything you were unsure about.

## Tooling
- venv: `backend/.venv/bin/python`. If a bash command fails with `bwrap: Can't mkdir
  .../private_data/filament-db/.claude: Permission denied`, retry it with
  `dangerouslyDisableSandbox: true` (root-owned Mongo dir, not your command).
