---
name: 2026-06-21-empty-archived-spool-conflict-fix
status: completed
created: 2026-06-21
model: opus
completed: 2026-06-21
result: Engine now honors never_import_empties — empty unmapped spools are skipped (not re-queued as new_spool conflicts) and lingering empty/archived new_spool conflicts auto-resolve. 3 tests; 1174 passing.
---

# Task: Honor never_import_empties in the ongoing sync engine

An empty (0 g) unmapped spool on a mapped filament was re-queued as a `new_spool` conflict every
sync cycle despite `never_import_empties` being on (it can never auto-import). The engine never
referenced the setting; only the wizard did.

## What was done

- `backend/app/core/engine.py`:
  - Derived `never_import_empties` from config in `run_sync_cycle`.
  - New-spool detection loop now skips a zero-remaining spool when the gate is on (logs a `skip`
    instead of queuing a `new_spool` conflict). Archived spools were already excluded via the
    active-only `sm_spools` set.
  - Extended the stale-conflict pass to auto-resolve open `new_spool` conflicts for spools that
    are now archived (always) or empty-with-gate-on (`resolution="resolved_not_imported"`).
- `backend/tests/test_never_import_empties_engine.py`: 3 tests (skip-when-on, control conflict
  when off, lingering-conflict auto-resolve).
- CHANGELOG `[Unreleased]` + `docs/decisions.md` entry (incl. the out-of-scope note: ongoing
  engine still never imports unmapped archived spools as retired when the gate is OFF — flagged
  for later, the affected user runs with the gate ON).

Verified: `pytest` 1174 passing, `ruff` clean.

## Notes

- Reproduced/diagnosed against the live bridge (Amolen SM spool 208, 0 g, active). The later
  production DB load had archived-but-non-empty spools (no empties), so the empties path is
  covered by unit tests rather than that dataset.
