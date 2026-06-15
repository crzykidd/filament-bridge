---
name: 2026-06-10-planner-validate-stale-mappings
status: done
created: 2026-06-10
model: sonnet
completed: 2026-06-10
result: implemented planner stale-mapping validation (Phase A + Phase C) and execute cleanup helpers; 882 tests pass (6 new)
---

# Task: Wizard planner must validate mappings against live FDB (recreate stale instead of skipping)

## Problem

The re-import planner trusts the local mapping tables blindly. In
`backend/app/core/planner.py:_plan_spoolman_to_fdb`:

- **Phase A (filament, lines 229-236):** if a `FilamentMapping` exists for an SM filament →
  marked `action="skip"`, `detail="already linked"` — even though `existing.filamentdb_id` may
  point to a Filament DB filament that **no longer exists** (user deleted it).
- **Phase C (spool):** if the SM spool id is in `mapped_sm_spool_ids` (any `SpoolMapping`) →
  marked `skip` / "already linked" — even if `mapping.filamentdb_spool_id` points to a deleted
  FDB spool.

Result: after the user deletes FDB records (but a stale bridge mapping lingers), re-running the
wizard SKIPS those records as "already linked" and never recreates them in Filament DB. Combined
with cleared Spoolman cross-refs, the user is stuck with records that won't import.

## Goal

Make the planner treat a mapping whose FDB target is **gone** as **stale**: do not skip it as
"already linked"; instead route it through the normal decision path (so it gets created/linked
per the user's wizard decision), and mark the stale mapping for cleanup so the recreated record
replaces it.

## Before you start

- Read `CLAUDE.md`. Read `backend/app/core/planner.py:195-336` (`_plan_spoolman_to_fdb`,
  Phase A/B/C). Note the live FDB indexes already available in the function:
  `fdb_by_id` (line ~215, FDB filament id → filament) and the `existing_fdb_spool_ids` parameter
  (line ~205, set of live FDB spool ids). These are the source of truth for "does the FDB record
  still exist."
- Note the naming-collision fix (just committed) also edited this file — work on the current
  `planner.py`. `git status --porcelain` first; tree should be clean apart from an uncommitted
  `README.md` and queued prompt files (leave those).
- Check how `wizard_execute` (`backend/app/api/wizard.py`) consumes plan items and where it
  creates/links + writes the `FilamentMapping`/`SpoolMapping` rows, so a stale mapping is cleaned
  up / overwritten rather than duplicated when the record is recreated.
- Standards: `code-checkin-and-pr`. Stay within `core/planner.py` and `api/wizard.py` (execute
  cleanup of stale mappings only). Do NOT touch engine/debug/mappings/frontend.

## What to do

1. **Phase A (filament):** when `existing = fil_map_by_sm.get(sm_fil.id)` is found, validate
   `existing.filamentdb_id in fdb_by_id`. If it IS present → keep current "skip / already linked".
   If it is **absent** (stale) → do NOT skip; fall through to the normal decision logic
   (`decisions_by_sm` → link/create/skip) as if no mapping existed, and record that this SM
   filament's stale `FilamentMapping` should be removed on execute (so the new create/link writes
   a fresh, correct mapping). Add a `detail`/log note like "stale mapping (FDB filament gone) —
   recreating".

2. **Phase C (spool):** when deciding to skip a spool because it's in `mapped_sm_spool_ids`,
   validate the mapping's `filamentdb_spool_id` is in `existing_fdb_spool_ids` (live). If the FDB
   spool is gone → treat as stale: do not skip; plan the spool for creation under its (re)created
   filament, and mark the stale `SpoolMapping` for removal on execute.

3. **Execute cleanup (`wizard.py`):** when executing a create/link for an item that had a stale
   mapping, delete the stale `FilamentMapping`/`SpoolMapping` (and its `Snapshot` rows if trivially
   reachable — mirror `_cleanup_orphaned_mapping` in `api/conflicts.py`) before/at writing the new
   mapping, so there's exactly one correct mapping afterward and no orphan left behind. Keep this
   minimal and well-contained.

   NOTE: a separate prompt (`prompts/2026-06-10-purge-stale-orphaned-mappings.md`) handles purging
   stale mappings during the SYNC engine. This prompt handles the WIZARD re-import path only. Don't
   implement engine-side purging here.

## Tests (`backend/.venv/bin/python -m pytest`)

- Stale `FilamentMapping` (filamentdb_id not in the FDB fetch) + a "create" decision → planner
  plans `create` (not skip), and execute recreates + replaces the stale mapping (no leftover orphan).
- Valid `FilamentMapping` (filamentdb_id present) → still `skip`/"already linked" (unchanged).
- Stale `SpoolMapping` (filamentdb_spool_id gone) → spool planned for create, stale mapping removed.
- Valid SpoolMapping → still skipped.
- Full suite green.

## When done

1. Update frontmatter; `git mv` this file to `prompts/done/`.
2. `docs/decisions.md`: record "planner validates mappings against live FDB; stale (FDB target
   gone) → recreate + replace mapping, instead of skipping as already-linked."
3. **Do NOT commit or push.** Leave changes in the working tree; report file-by-file summary +
   exact pytest counts.

## Tooling
- Backend venv `backend/.venv/bin/python`. `bwrap: Can't mkdir .../private_data/...` → retry that
  command with `dangerouslyDisableSandbox: true`.
