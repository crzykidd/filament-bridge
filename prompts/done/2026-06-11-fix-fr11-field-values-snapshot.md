---
name: 2026-06-11-fix-fr11-field-values-snapshot
status: done
created: 2026-06-11
model: sonnet
completed: 2026-06-11
result: Fixed. _field_values now persisted via _merge_snapshot after _apply_field_changes; first-sight baseline fetches fdb_detail when field_maps active. 4 new tests green. 891/891 suite green.
---

# Task: Fix FR-11 field-mapping sync — FDB `_field_values` are never persisted (perpetual false changes)

Found in the 2026-06-11 full-code audit (`prompts/assets/2026-06-11-docs-gap-report.md`, B1).

## The bug

`core/differ.py:diff_spool_pair` compares mapped-field values against
`fdb_snapshot.get("_field_values", {})` — but the engine **never stores** `_field_values`.
`engine.py:_fdb_snapshot_dict(spool, filament_detail=None, field_maps=None)` only embeds
`_field_values` when BOTH optional args are passed, and every call site in
`run_sync_cycle` (first-sight baseline ~line 2452, weight SM→FDB refresh ~2570, weight
FDB→SM refresh ~2620, NOOP refresh ~2658) and `api/wizard.py:_seed_snapshots` passes only
the spool.

Consequence: for every pair with field mappings active (`FIELD_MAPPINGS` env or
auto-matched Spoolman extra fields), `fdb_then` is always `None`, so any mapped field with
a non-None FDB value reads as "FDB changed" **every cycle**:

- default direction (`filamentdb_to_spoolman`): the same value is PATCHed to the Spoolman
  extra field every cycle + a sync-log "update" row every cycle (log spam, pointless writes)
- `two_way`: when the SM side also changes, every mapped field becomes a spurious conflict

The SM side is fine — `_sm_snapshot_dict(spool, field_maps)` stores `_extra_decoded` at
the same call sites.

## What to do

1. Persist the FDB-side mapped-field values in the FDB spool snapshot wherever the engine
   refreshes it. The values come from the FDB **detail** view (inheritance resolves there).
   `_apply_field_changes` already fetches `fdb_detail` per pair — the cleanest shape is
   probably:
   - In the mapped-pair loop, when `field_maps` is non-empty, fetch the detail once per
     pair (or reuse/restructure so `_apply_field_changes` shares it) and pass
     `filament_detail=detail, field_maps=field_maps` to `_fdb_snapshot_dict` at all four
     snapshot-refresh sites.
   - ALSO refresh `_extra_decoded`/`_field_values` after a successful FR-11 push so the
     just-written value isn't re-detected: after the batched FDB PUT (SM→FDB) update the
     FDB snapshot's `_field_values` for the written paths; after an FDB→SM extra write
     update the SM snapshot's `_extra_decoded` for that key. Mind the ordering — the
     weight-pass snapshot refresh currently runs BEFORE `_apply_field_changes`, so a
     post-push merge into the snapshot (like `_merge_snapshot` does for filament-level
     keys) is the safe pattern. Watch out: spool snapshots are full-replace
     (`_upsert_snapshot`), so either merge into the dict before upserting or add a small
     merge helper for spool snapshots.
   - Avoid double-fetching the FDB detail per pair (it's already fetched in
     `_apply_field_changes`; don't add a second fetch per pair).
2. Wizard `_seed_snapshots` can stay as-is (first engine cycle will baseline
   `_field_values` if you ensure the first-sight path stores them — confirm it does).
3. Tests (backend, pytest):
   - With a field mapping active and NO changes on either side, a second sync cycle
     performs no FR-11 writes and emits no FR-11 sync-log updates (this currently fails).
   - An FDB-side change is detected exactly once; the cycle after the push is a NOOP.
   - SM-side change under default direction stays NOOP (locked side), as today.
4. While in `core/version.py`: fix the stale header comment ("the health check surfaces a
   warning (it does NOT hard-block…)") — minimums DO hard-gate sync now; say so.
5. Full backend suite green (`backend/.venv/bin/python -m pytest` or `cd backend && pytest`).

## Before you start

- Read `CLAUDE.md` (weight/anti-ping-pong section), `docs/sync-model.md` (snapshots
  section), `backend/app/core/engine.py` (mapped-pair loop + `_apply_field_changes` +
  `_sm_snapshot_dict`/`_fdb_snapshot_dict`), `backend/app/core/differ.py`.
- The anti-ping-pong invariant (decisions.md, 2026-06-10): after any propagation, refresh
  BOTH sides to the post-write agreed values.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files this
plan needs to modify. The working tree currently carries a large uncommitted docs batch
(README, docs/*, CLAUDE.md, prompts/*) from the docs-overhaul session — that's expected;
don't touch those files. If `engine.py`/`differ.py` themselves are dirty, stop and ask.

## When done

1. Update this file's frontmatter; `git mv` to `prompts/done/`.
2. Record the fix in `docs/decisions.md` (brief entry: what was broken, the snapshot-merge
   approach chosen).
3. Propose ONE commit (`fix:` prefix, no Co-authored-by), on `dev`. Never push to main.
