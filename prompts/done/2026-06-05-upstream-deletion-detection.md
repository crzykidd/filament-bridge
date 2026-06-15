---
name: 2026-06-05-upstream-deletion-detection
status: completed
created: 2026-06-05
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-05
result: Deletion conflicts queued via DELETION_FIELD sentinel; dedup, resolve-cleanup, frontend rendering, and 10 new tests all green
---

# Task: Detect upstream-deleted records and queue them as conflicts

The bridge never re-validates that a mapped record still exists upstream. When a
record is deleted in Filament DB (or Spoolman), the sync cycle today just writes a
`skip`/`error` log line and moves on — the `SpoolMapping` row and its cached
`Snapshot`s persist, so the Dashboard and Synced Records page keep counting the pair
as `in_sync`. Symptom that triggered this: user wiped the Filament DB database and
the bridge still showed "3 synced".

**Decision (from the user):** an orphaned mapping (its upstream record is gone) must
be **queued in the Conflicts queue** for an explicit human decision — never
auto-resolved, never silently dropped. This is consistent with the hard rule
"conflicts are never auto-resolved" and "never delete records without explicit user
action."

## Before you start

- Read `docs/prd.md` (FR-13/FR-16 conflicts, FR-15 dashboard, FR-19 synced records)
  and `CLAUDE.md` (conflict + deletion rules).
- Read `docs/decisions.md` — note the existing **"resolve = record, apply next
  cycle"** philosophy for conflicts. The conflict router performs no upstream writes.
- Match the existing conflict-queueing pattern in `backend/app/core/engine.py`
  (`_queue_conflict`, line ~128) and the `Conflict` model
  (`backend/app/models/conflict.py`).

## Working tree check

Run `git status --porcelain` and cross-reference the files below. If any have
uncommitted changes, list them and ask before touching. Surface unrelated dirty files
once as awareness; don't block. This prompt file is exempt.

## Key facts about the current code (verified)

- **Sync cycle**: `backend/app/core/engine.py` `run_sync_cycle()`.
  - Fetches `sm_spools_all`, `sm_filaments_all`, `fdb_filaments_all` (lines ~922-926).
  - `sm_spools` dict is built from **non-archived** spools only:
    `{s.id: s for s in sm_spools_all if not s.archived}` (line 935).
  - `fdb_spool_index` maps `fdb_spool_id → (fdb_filament_id, FDBSpool)` from the
    current fetch (lines 939-943).
  - The mapped-pair loop is lines ~970-1010. **This is where to add detection.**
    - `if sm_spool is None:` (line 974) currently logs `skip`
      ("SM spool not in active set (archived?)") and `continue`s. **This conflates
      archived with deleted.**
    - `if fdb_entry is None:` (line 1000) currently logs an `error`
      ("FDB spool not found in current fetch") and `continue`s.
- **Conflict model** (`backend/app/models/conflict.py`): has `entity_type`,
  `spoolman_id`, `filamentdb_filament_id`, `filamentdb_spool_id`, `field_name`
  (required), `spoolman_value`/`filamentdb_value` (JSON text), `detected_at`,
  `resolved_at`, `resolution`, `resolved_value`. No migration needed if you reuse
  these columns (preferred).
- **Dashboard/Synced Records status** is computed in
  `backend/app/api/mappings.py` `build_mapping_rows()`. It already flips a row to
  `status="conflict"` when an **open** conflict references that spool's
  `spoolman_id` or `filamentdb_spool_id`. So **queueing a deletion conflict that
  carries the mapping's ids will automatically make the row show as `conflict`
  instead of `in_sync`** — that alone fixes the misleading count.
- `_queue_conflict()` does NOT dedup. Field conflicts don't pile up because they only
  fire on a snapshot *diff*. A deletion persists every cycle, so **you must dedup** or
  it will enqueue a new conflict every interval.

## What to do

### 1. Distinguish "deleted" from "archived" (Spoolman side)

In the `sm_spool is None` branch, check whether the id exists at all in the full
fetch. Build a set once near line 935:

```python
sm_all_ids = {s.id for s in sm_spools_all}  # includes archived
```

- If `mapping.spoolman_spool_id not in sm_all_ids` → the Spoolman spool was
  **deleted** → queue a deletion conflict (see step 3).
- If it's present but archived (current behavior) → keep the existing `skip` log.
  Do NOT treat archival as deletion.

### 2. FDB side

In the `fdb_entry is None` branch (line ~1000): `fdb_spool_index` is built only from
the current FDB fetch, so a missing entry means the FDB spool no longer exists →
**deleted** → queue a deletion conflict. Keep a log line too, but downgrade from
`error` to the deletion path.

(Note: a wiped FDB also drops the parent filament + `FilamentMapping`. Spool-pair
detection covers the user-visible "synced records" symptom; you may optionally extend
the same approach to orphaned `FilamentMapping`s, but spool pairs are the priority.)

### 3. Queue a deletion conflict (with dedup)

Add a helper, e.g. `_queue_deletion_conflict(db, cycle_id, mapping, *, deleted_side)`
where `deleted_side` is `"spoolman"` or `"filamentdb"`. It must:

- **Dedup**: before inserting, query for an existing **open** deletion conflict for
  this mapping and skip if found:
  ```python
  exists = (
      db.query(Conflict)
      .filter(
          Conflict.resolved_at.is_(None),
          Conflict.field_name == DELETION_FIELD,
          Conflict.spoolman_id == mapping.spoolman_spool_id,
          Conflict.filamentdb_spool_id == mapping.filamentdb_spool_id,
      )
      .first()
  )
  if exists:
      return
  ```
- Use a sentinel `field_name` constant, e.g. `DELETION_FIELD = "__record_deleted__"`,
  defined once at module top.
- Populate ids from the mapping (`spoolman_id`, `filamentdb_filament_id`,
  `filamentdb_spool_id`) so `build_mapping_rows()` links it to the row.
- Encode which side is gone. Put a small JSON descriptor on the **surviving** side's
  value and `null` on the deleted side, e.g. for an FDB deletion:
  `spoolman_value = {"exists": true, "deleted_side": "filamentdb"}`,
  `filamentdb_value = null`. The frontend (step 5) keys off `deleted_side`.
- Emit a `_log(... action="conflict", direction="conflict", entity_type="spool",
  error_message="upstream record deleted (<side>)")` line so the Sync Log shows it.
- Then `continue` the loop (do not fall through to diffing a half-missing pair).

Only run this in the `not dry_run` path for the *insert*; in `dry_run` add a preview
entry (action `"conflict"`, reason `"record deleted upstream (<side>)"`) mirroring the
existing dry-run preview shape, and do NOT write to the DB.

### 4. Resolution cleanup (so the orphan can actually be cleared)

A recorded resolution alone won't drop the stale mapping, so the "synced" count would
stay wrong after the user resolves. Extend the resolve flow minimally:

- In `backend/app/api/conflicts.py`, when resolving a conflict whose
  `field_name == DELETION_FIELD`, after recording the resolution, **delete the orphaned
  `SpoolMapping` row and its `Snapshot` rows** for the gone record. This is bridge-local
  state only — NOT an upstream write — so it's permitted. Guard it behind the deletion
  sentinel so normal field-conflict resolution is unchanged.
- Do this for both `resolve_conflict` and `bulk_resolve`.
- Removing the mapping + snapshots makes the Dashboard count drop and the row
  disappear from Synced Records — the actual fix the user is after.
- Keep it record-only for any **upstream** action (e.g. re-creating the deleted
  record): that stays a Phase-2 follow-up, consistent with the existing pattern. Note
  it in `docs/decisions.md`.

### 5. Frontend: render deletion conflicts legibly

`frontend/src/pages/Conflicts.tsx` renders `conflict.field_name` as the heading and a
Spoolman-vs-FDB value diff. A raw `__record_deleted__` heading + null/descriptor
values will look broken. Special-case it:

- When `field_name === "__record_deleted__"`, show a heading like
  **"Record deleted upstream"** and a one-line explanation of which side is gone
  (read `deleted_side` from the descriptor value), instead of the value diff.
- The resolution controls can stay, but relabel them for this case if cheap
  (e.g. "Keep / re-link" vs "Remove mapping"). At minimum it must not render the
  generic field diff with empty values.
- Match existing Tailwind styling and component structure on the page.

### 6. Tests

- Backend: add a test in the engine test suite that maps a spool pair, runs a cycle,
  then removes the FDB spool from the mocked fetch and runs again — assert exactly one
  open deletion conflict is created, that a second cycle does NOT create a duplicate,
  and that the Dashboard/`build_mapping_rows` status for that mapping becomes
  `conflict`. Add the symmetric Spoolman-deletion case, and a **negative** case proving
  an *archived* (not deleted) Spoolman spool still logs `skip` and creates no conflict.
- Add a conflicts-API test: resolving a `__record_deleted__` conflict removes the
  `SpoolMapping` and its `Snapshot` rows; resolving a normal field conflict does not.
- Run `cd backend && pytest`. Frontend: `cd frontend && npm test` if the page has
  coverage; otherwise typecheck/build.

## Conventions to honor

- `code-checkin-and-pr`: work on `dev`, conventional-commit prefix (`feat:` here —
  new user-facing deletion-detection behavior), no `Co-authored-by:` trailer, docs in
  the same commit as the code.
- Don't add a DB migration unless you genuinely need a new column — reuse the existing
  `Conflict` columns + sentinel `field_name`.
- Never auto-resolve; never write to upstream from this code path. Deleting
  bridge-local mappings/snapshots on user-initiated resolve is fine.

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/` (failure).
3. Record the deletion-conflict design + the "resolve deletes bridge-local mapping,
   upstream re-create is Phase 2" decision in `docs/decisions.md`.
4. Propose ONE commit (incl. the prompt move). Present the file list + one-line
   `feat:` message and ask `commit these as "<message>"? (y/n)`. On `y`, stage those
   specific paths and commit on `dev`. Never `git add -A`. Never push.
