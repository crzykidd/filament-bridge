---
name: 2026-06-10-applyall-failure-snapshot-fix-and-lint
status: completed        # pending | completed | failed
created: 2026-06-10
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-10
result: Bug fix + test applied; ruff F401 lint cleared; 862 tests green.
---

# Task: Fix apply_all snapshot-refresh-on-failure bug + clear ruff F401 lint errors

Two small changes, one commit:

1. **Bug fix** — in the Phase B `apply_all` resolution action, a record whose upstream write
   fails still gets its snapshot refreshed to the new value, falsely marking it as synced and
   suppressing re-detection. Refresh only the records that actually wrote.
2. **Lint** — clear the 8 `ruff check backend/` F401 (unused-import) errors introduced by the
   Phase A/B work.

## Before you start

- This is the filament-bridge project; read `CLAUDE.md` (esp. the weight-model
  snapshot-refresh / anti-ping-pong notes and the conflict rules).
- `git status --porcelain` first. The only expected uncommitted file is THIS prompt and the
  other pending prompt(s) under `prompts/`. If `backend/app/core/conflict_apply.py` or the
  test files are dirty, stop and report — they should be clean (committed in `8b806b3`).
- Standards: `code-checkin-and-pr` (work on `dev`, Conventional-Commits prefix, no
  `Co-authored-by:`).

## 1. Bug fix — `backend/app/core/conflict_apply.py`, function `_action_apply_all`

Currently the snapshot refresh at the end unconditionally stamps every record (master + all
variants on the FDB side, every mapped SM filament on the SM side) with `new_value`, even for
records whose `update_filament` call raised (those failures are caught, logged, and
execution continues).

Implement exactly this:

- Right after `master_id, variant_ids = await _get_variant_line(...)`, declare two sets:
  ```python
  failed_fdb_ids: set[str] = set()
  failed_sm_ids: set[int] = set()
  ```
- In the **FDB variant** write loop's `except` block, add `failed_fdb_ids.add(vid)` (alongside
  the existing warning + error `_log`).
- In the **SM filament** write loop's `except` block, add `failed_sm_ids.add(sid)` (alongside
  the existing warning + error `_log`).
- In the snapshot-refresh block, skip refreshing any record in the failed set:
  ```python
  for fid in fdb_ids_to_refresh:
      if fid in failed_fdb_ids:
          continue
      _merge_snapshot(db, "filamentdb", "filament", fid, {snap_key: new_value})
  for sid in sm_ids_in_line:
      if sid in failed_sm_ids:
          continue
      _merge_snapshot(db, "spoolman", "filament", str(sid), {snap_key: new_value})
  ```
- Update the refresh block's comment to explain: failed records keep their old baseline so the
  next cycle re-detects/retries; inherited variants (never written) still resolve to the
  master's `new_value` via inheritance, so refreshing their snapshot is correct.

Do **not** change the existing behavior that the master write is unguarded (a master-write
failure still propagates and leaves the conflict unresolved) or that a downstream failure does
**not** abort `apply_all` (the conflict still resolves). Only the snapshot-refresh selection
changes.

### Test — add to `backend/tests/test_conflict_apply.py`

Add a test (model it on the existing `test_apply_all_refreshes_snapshots`, place it adjacent):

```python
@pytest.mark.asyncio
async def test_apply_all_skips_snapshot_refresh_for_failed_write(db):
    """apply_all: a record whose downstream write fails is NOT snapshot-refreshed,
    so it re-detects next cycle. The successful master is still refreshed and the
    conflict still resolves."""
    _add_filament_mapping(db, VARIANT_FDB_ID, SM_FIL_ID, parent_id=MASTER_FDB_ID)
    conflict = _add_conflict(db, field_name="density", sm_value=1.38)
    db.commit()

    master = _fdb_master_detail(density=1.30, variant_ids=[VARIANT_FDB_ID])
    variant = _fdb_variant_detail(density=1.24, inherited=["density"])
    fdb = _fake_fdb_client(variant_detail=variant, master_detail=master)
    sm = _fake_spoolman_client()
    sm.update_filament = AsyncMock(side_effect=RuntimeError("spoolman down"))

    await apply_master_divergence(conflict, "apply_all", db, sm, fdb)
    db.commit()

    sm_snap = _get_snap(db, "spoolman", "filament", str(SM_FIL_ID))
    assert (sm_snap or {}).get("_mp_density") != 1.38      # failed write → not stamped
    master_snap = _get_snap(db, "filamentdb", "filament", MASTER_FDB_ID)
    assert (master_snap or {}).get("_mp_density") == 1.38  # master succeeded → refreshed
    db.refresh(conflict)
    assert conflict.resolved_at is not None                # still resolves
```

(`AsyncMock` is already imported in that test module.)

## 2. Lint — clear the F401 errors

Run `ruff check backend/ --fix` to auto-remove the unused imports, then confirm
`ruff check backend/` exits clean. The 8 flagged imports are:
- `backend/app/core/conflict_apply.py`: `SyncLog` (line ~23), `Snapshot` (line ~24), and the
  function-local `from app.schemas.filamentdb import FDBFilamentDetail` (line ~402).
- `backend/tests/test_conflict_apply.py`: `call`, `patch` (line ~19),
  `build_divergence_context` (line ~35), `SpoolMapping` (line ~40).
- `backend/tests/test_engine_scalars.py`: `SpoolmanSpool` (line ~31).

After `--fix`, eyeball the diff to confirm only import lines changed and nothing still-used was
removed (ruff F401 only removes provably-unused names, but verify the test files still import
everything their bodies reference).

## 3. Verify

- `cd backend && .venv/bin/python -m pytest -q` → full suite green (expect 862 after the new
  test; was 861).
- `ruff check backend/` → clean (0 errors).

## Conventions to honor

- No behavior change beyond the snapshot-refresh selection. No `settings{}` writes.
- Keep the resolve-anyway-on-downstream-failure semantics.

## When done

1. Update this file's frontmatter (`status`, `completed`, `result`).
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/`.
3. In `docs/decisions.md`, refine the Phase B note: `apply_all` now skips the snapshot refresh
   for any record whose upstream write failed (the prior behavior stamped a synced baseline on
   failed records).
4. **Do NOT `git commit` and do NOT push.** Leave all changes (incl. the prompt move) in the
   working tree and report back — file-by-file summary, exact pytest counts, and `ruff check
   backend/` result. The orchestrating agent will review and commit.

## Tooling notes

- Python venv: `backend/.venv/bin/python` (no `python` on PATH).
- If a bash command fails with `bwrap: Can't mkdir .../private_data/filament-db/.claude:
  Permission denied`, that's a sandbox-setup failure from a root-owned MongoDB data dir under
  `private_data/`, not your command — retry with the sandbox disabled
  (`dangerouslyDisableSandbox: true`).
