---
name: 2026-06-24-location-sync
status: done
created: 2026-06-24
model: sonnet
completed: 2026-06-24
result: >
  Shipped the location_sync category in the continuous engine (GitHub #29). Compare-by-name:
  FDB locations fetched once per cycle into an {_id: name} map threaded into both snapshot
  builders; differ gained sm_location_change/fdb_location_change; a dedicated location pass
  (after the lifecycle pass, independent of weight) routes through resolve_sync_action —
  SM→FDB find-or-creates via ensure_fdb_location, FDB→SM writes the name, both-changed→one
  cross_system "location" conflict; both snapshots refresh after any push. #21 dispatcher
  got a location handler. Config (DB-only, mirrors archive_sync): location_sync_direction
  (two_way) + location_sync_conflict_policy (manual), newest_wins rejected 422. Settings.tsx
  gained a Location sync card. Backend 1304 passed (baseline 1285, +19), ruff clean; frontend
  tsc clean, 129 vitest passed, build OK.
---

# Task: Sync spool location in the continuous engine (GitHub #29)

The ongoing sync engine never diffs or propagates spool **location**, so a location change made
directly in Spoolman (or Filament DB) never reaches the other side. Add location as a synced
category, modelled exactly like the existing `archive_sync` category.

## Confirmed gap
No `location`/`locationId` handling in `core/engine.py` or `core/differ.py`; the snapshot builders
(`_sm_snapshot_dict` / `_fdb_snapshot_dict`) omit it; the differ `ChangeSet` has weight / archive /
material-fields but no location. Location is only written at wizard import + the mobile update.

## Decision (confirmed)
A new **`location_sync`** category, two axes like the others:
- `location_sync_direction` — `two_way` (default) | `spoolman_to_filamentdb` | `filamentdb_to_spoolman`.
- `location_sync_conflict_policy` — `manual` (default) | `spoolman_wins` | `filamentdb_wins`.
  **Reject `newest_wins` (422)** — a location string has no comparable timestamp (same as `archive_sync`).
Compare by **name**: Spoolman `location` is a free-text string; Filament DB stores a `locationId`
(reference), so resolve `locationId` → location name to diff, and find-or-create on a SM→FDB push.

## Model details
- Spoolman spool `location: str | None`. Write via `spoolman.update_spool(id, {"location": name})`.
- Filament DB spool `locationId` (reference). Find-or-create the location by name via
  `core/locations.py:ensure_fdb_location(filamentdb, name)` → id, then
  `filamentdb.update_spool(fil, spool, {"locationId": id})`. To get the current FDB location NAME,
  resolve `locationId` against `filamentdb.get_locations()` (`[{_id, name}]`).

## Before you start
- Read `core/engine.py` (the per-pair loop, the weight pass and esp. the **archive/retire lifecycle
  pass** `~3371` — copy its shape; `_upsert_snapshot`/`_merge_snapshot`; the `resolve_sync_action`
  call sites; `_sm_snapshot_dict`/`_fdb_snapshot_dict` `~434/461`), `core/differ.py` (`ChangeSet`,
  how `sm_archive_change`/`fdb_retire_change` are built `~49/109`), `core/sync_policy.py`
  (`resolve_sync_action`), `core/conflict_apply.py:apply_cross_system_conflict` (#21 dispatcher — add
  a `location` handler), `core/locations.py:ensure_fdb_location`, `api/config.py` +
  `models/config.py` (the `archive_sync_*` keys are the exact pattern to copy), and how the engine
  fetches `fdb_filaments_all` (you'll also need the FDB locations list once per cycle).
- Honor `code-checkin-and-pr`: worktree off `dev`, `feat:` prefix, no `Co-authored-by:`. UNATTENDED.

## What to do

### 1. Config (copy the `archive_sync_*` pattern exactly)
`location_sync_direction` (default `two_way`) + `location_sync_conflict_policy` (default `manual`) in
`config.py` env, `models/config.py` `_DEFAULTS`, `ConfigResponse`/`ConfigUpdateRequest`,
`_config_response`. Reject `newest_wins` for `location_sync_conflict_policy` (422, like archive).

### 2. Snapshots carry the location NAME
- `_sm_snapshot_dict`: add `"location"` = the SM spool's `location` string (or None).
- `_fdb_snapshot_dict`: add `"location"` = the FDB spool's location **name**, resolved from its
  `locationId` via an id→name map. Fetch the FDB locations once per cycle (e.g. `filamentdb.get_locations()`
  → `{_id: name}`) and thread it into the snapshot builder + the pass (like `field_maps` is threaded).
  An unknown/missing `locationId` → None.

### 3. Differ
Add `sm_location_change` / `fdb_location_change` (`FieldChange | None`) to `ChangeSet`, set when the
current name differs from the snapshot name (string compare, None-safe). Mirror the archive/retire
detection block.

### 4. Engine pass (model on the lifecycle pass)
A dedicated location pass per mapped pair: read the changes from the changeset, call
`resolve_sync_action(sm_changed, fdb_changed, direction=location_direction, policy=location_policy)`.
- `PUSH_SM_TO_FDB`: `ensure_fdb_location(SM name)` → id; `filamentdb.update_spool(fil, spool, {"locationId": id})`.
- `PUSH_FDB_TO_SM`: `spoolman.update_spool(sm_id, {"location": FDB name})`.
- `QUEUE_CONFLICT` (both changed, two_way+manual / wins-fallback): queue a `cross_system` conflict
  `field_name="location"` (dedup via `_has_open_conflict`), values = the two location names.
- `NOOP`: converge the snapshot names so it isn't re-detected.
- After ANY push, refresh BOTH snapshot `location` names to the converged value (anti-ping-pong) —
  exactly like the lifecycle/weight passes. A one-sided change is a clean push (no conflict).
- Order: a safe spot is alongside/after the lifecycle pass. Location is independent of weight, so it
  doesn't need the weight-settles-first ordering, but keep it inside the same per-pair block.

### 5. #21 conflict dispatcher
Add a `field == "location"` branch to `core/conflict_apply.py:apply_cross_system_conflict`: resolve to
the chosen location name (spoolman/filamentdb/manual), write it to BOTH sides
(`ensure_fdb_location`→`locationId` on FDB; `location` string on SM), refresh both snapshot `location`
names, record the resolution. Mirror the existing per-field handlers.

### 6. Frontend
Add a **"Location sync"** category to `Settings.tsx` (direction + conflict policy selects), mirroring
the Archive/retire category exactly. Add the two keys to `ConfigResponse`/`ConfigUpdateRequest` TS
types. `newest_wins` should be unavailable for location (like archive).

## Tests
- Engine: SM-only location change → FDB `locationId` written (find-or-create) + both snapshots refresh;
  FDB-only change → SM `location` string written; **both-changed (two_way+manual) → one `cross_system`
  `location` conflict**, no writes; resolve → converges; a SECOND cycle on the converged state does NOT
  re-queue (anti-ping-pong). One-way directions: locked-side drift is NOOP.
- Differ: location change detection (incl. None↔value, no-op when equal).
- Snapshot: FDB `locationId` → name resolution (known id, unknown id → None).
- `apply_cross_system_conflict` location handler (spoolman/filamentdb/manual).
- Config: `newest_wins` rejected (422) for `location_sync_conflict_policy`.
- Run `cd backend && .venv/bin/python -m pytest -q` (baseline 1285) + `ruff check .`, and
  `cd frontend && npx tsc --noEmit && npx vitest run && npm run build` (baseline 129). (Worktree has
  no node_modules — symlink the main repo's, run, remove before commit; say so.)

## When done
1. Frontmatter; `git mv` to `prompts/done/`.
2. Docs: `docs/sync-model.md` (a Location section + the new pass in the per-cycle list),
   `docs/configuration.md` + `CLAUDE.md` (env + runtime-settings tables — copy the `archive_sync_*`
   rows), `docs/conflicts.md` (the `location` cross_system conflict), `docs/prd.md` (extend the
   relevant FR), `docs/decisions.md`, `CHANGELOG.md` (Added/Fixed entry referencing #29).
3. ONE `feat:` commit on the worktree branch (specific paths, never `git add -A`, never push).
   Suggested: `feat: sync spool location in the continuous engine (location_sync category) (#29)`.
4. Final message: commit SHA, file list, both test commands + pass/fail counts, where the location
   pass sits in the cycle, and anything deferred/uncertain.
