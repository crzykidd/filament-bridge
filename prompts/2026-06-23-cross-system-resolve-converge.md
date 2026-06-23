---
name: 2026-06-23-cross-system-resolve-converge
status: pending
created: 2026-06-23
model: sonnet
completed:
result:
---

# Task: Make cross_system conflict resolution converge (GitHub #21)

Fix the confirmed bug where resolving a standard (`cross_system`) conflict is **record-only**
— it writes nothing upstream and never advances the snapshot baseline, so the next sync cycle
re-detects the unchanged divergence and **re-queues a brand-new conflict**. The user's value
pick has no effect on the data. Closes #21 (FR-16).

## Confirmed mechanism (already verified)
- `QUEUE_CONFLICT` branches in `engine.py` queue the conflict but do **not** refresh snapshots
  (only the PUSH and NOOP branches do).
- The resolve endpoint (`backend/app/api/conflicts.py:336-344`) records the chosen value +
  `resolved_at` but writes nothing upstream and never touches snapshots.
- Empirically: cycle1 → 1 open conflict; record-only resolve; cycle2 → a NEW open conflict
  (total rows = 2). It re-queues every cycle until the underlying data is manually made to agree.

## The fix (decided design)
Generalize the **lifecycle** resolve path (`core/conflict_apply.py:apply_lifecycle_conflict`,
which already writes the chosen value to BOTH systems + refreshes both snapshots) to **all**
`cross_system` conflict field types. Add `apply_cross_system_conflict(conflict, resolution, db,
spoolman, filamentdb)` and route every `cross_system` conflict through it from `resolve_conflict`
(replace the record-only branch). Keep the lifecycle path (either fold it into the dispatcher as
the `field_name == "lifecycle"` case, or keep calling `apply_lifecycle_conflict` from the
dispatcher — your choice, no behavior change for lifecycle).

For each conflict `field_name`, the dispatcher must:
1. Compute the **target value** for `resolution` ∈ {`spoolman`, `filamentdb`, `manual`} from the
   values stored on the conflict row (`spoolman_value`, `filamentdb_value`) or `payload.value`.
2. **Write the target to BOTH sides** (idempotent — one side may already match), using the SAME
   client calls + conversions the corresponding engine pass uses.
3. **Refresh BOTH snapshot keys** to the converged value (anti-ping-pong), using the SAME
   snapshot keys the pass uses (so the differ does not re-detect next cycle).
4. Record `resolution` / `resolved_value` / `resolved_at`.
On any upstream write failure: raise so the endpoint returns **502 and leaves the conflict open**
(mirror the lifecycle/master_divergence handling).

### Decisions already made (implement exactly)
- **ALL field types in one PR** (do not phase).
- **Weight is a DIRECT ABSOLUTE write to both sides — NO usage entry.** The converged value is a
  net remaining weight `W`:
  - Spoolman: `update_spool(sm_id, {"remaining_weight": W})`.
  - Filament DB: `update_spool(fdb_fil, fdb_spool, {"totalWeight": W + tare})` where
    `tare = FDB filament.spoolWeight` (use the project default tare if missing, same as the engine).
  - `resolution=spoolman` → `W = spoolman_value` (already net). `resolution=filamentdb` →
    `W = filamentdb_value - tare` (stored FDB value is gross totalWeight). `resolution=manual` →
    `payload.value` interpreted as the **net** remaining weight (Spoolman units); FDB gets `W + tare`.
  - Refresh snapshots: SM `remaining_weight = W`, FDB `totalWeight = W + tare`.
  - This intentionally bypasses the usage-delta path — a human-approved reconciliation is a
    correction, consistent with the existing weight-INCREASE path in the engine.

## Field types to handle (study each queueing pass and MIRROR its write + snapshot key)
Find every `_queue_conflict(...)` site in `backend/app/core/engine.py` and its enclosing pass;
reuse that pass's exact write calls, conversion helpers, and `_merge_snapshot`/`_upsert_snapshot`
keys. Do NOT reinvent conversions — reuse `core/weight.py`, `core/color.py`,
`core/material_tags.py`, `core/fields.py`, etc.

- **`weight`** (engine ~3224; PUSH paths ~3249/3314) — see the decided absolute-write rule above.
  Snapshot keys: SM `remaining_weight`, FDB `totalWeight`.
- **`multicolor`** (pass ~800-980, queue ~933) — convert via `core/color.py`; write
  `update_filament` on both (SM multi-color fields / FDB `color`+`secondaryColors`); snapshot key
  `_mc_sig` on both filament snapshots.
- **`cost`** (pass ~1060-1150, queue ~1148) — SM filament `price` / FDB `cost`; `update_filament`
  both; snapshot key `_cost`.
- **`material_tags`** (pass ~2150-2260, queue ~2185) — finish tags; SM extra
  `filamentdb_material_tags` (CSV of ints) / FDB `optTags`; snapshot key `_finish_sig`.
- **Material-property fields** routed through `_sync_material_props` (temps; queue ~1388),
  `_sync_material_scalars` (`material`/`density`/`diameter`/`spool_weight`/`netFilamentWeight`;
  queue ~1593/1680), and `_sync_opentag_material_fields` (the 7 typed OPT fields; queue ~1867/1951)
  — snapshot key `_mp_<sm_field>`. Mirror each pass's read-modify-write (e.g. FDB `temperatures`
  object RMW so sibling temps survive) and field name remaps (SM `material` ↔ FDB `type`).
- **Dynamic `FIELD_MAPPINGS` extra fields** (via `_apply_field_changes`, queue ~611) — generic
  SM extra ↔ FDB field; resolve the mapping the same way the pass does and write/snapshot generically.
- **`lifecycle`** (queue ~3414) — already handled by `apply_lifecycle_conflict`; route it through
  the dispatcher unchanged.

If a field_name can't be mapped to a known write path, **do not silently no-op** — log and raise
a 422 from the endpoint ("unsupported conflict field for apply") so it's visible, not a silent
record-only regression.

## Before you start
- Read `CLAUDE.md` (weight-model + anti-ping-pong sections, the `_queue_conflict`/snapshot notes),
  `docs/prd.md` FR-16/FR-13, `docs/conflicts.md`, and `standards.md`.
- Honor `code-checkin-and-pr`: branch you're on (worktree off `dev`), `fix:` prefix, no
  `Co-authored-by:`, docs in the same commit.
- Study `core/conflict_apply.py:apply_lifecycle_conflict` (the template) and
  `apply_master_divergence` (the 502-on-failure pattern).

## Working tree check
You're in an isolated worktree off `dev` (clean). Run `git status --porcelain` first.

## Tests (this is the proof the bug is fixed)
- **Regression test per field family**: queue the conflict (or seed one), resolve via the endpoint
  for each of `spoolman` / `filamentdb` / `manual`, run a SECOND `run_sync_cycle` with the post-write
  state, and assert: (a) **no new open conflict** is queued, and (b) both sides hold the converged
  value (and snapshots match). Mirror the existing both-changed tests in `tests/test_engine.py`
  (`test_both_sides_changed_creates_conflict_no_writes`, `_seed_weight_config`, the mock clients).
- **Update** `tests/test_api.py::test_resolve_conflict_records_choice_and_does_not_apply` — it
  encodes the OLD (broken) "no upstream write" intent; it must become "resolve applies + converges."
- Upstream-failure path: a write that raises → endpoint returns 502, conflict stays open, no
  partial snapshot advance that would hide the divergence.
- Run the FULL suite: `cd backend && .venv/bin/python -m pytest -q` (baseline was 1207 passing) and
  `cd frontend && npx vitest run` + `npx tsc --noEmit` if you touch the frontend. `ruff check backend/`.

## Frontend
The Conflicts UI already lets the user pick a value/enter manual for standard conflicts. Verify the
existing resolve call still works; the response now reflects an applied resolution. Update any copy
that implies "record-only / does not change your data" so it matches the new behavior. Minimal FE
changes expected — backend is the substance.

## Docs (same commit)
- `docs/prd.md` FR-16 — replace "Standard (cross_system) conflicts are record-only … does NOT write
  the value upstream" with the new converge-on-resolve behavior (write chosen value to both sides +
  refresh). Keep the master_divergence section as-is.
- `docs/conflicts.md` — update the cross_system resolution semantics.
- `CHANGELOG.md` `## [Unreleased]` — a **Fixed** entry referencing #21 (terse, the issue carries detail).

## When done
1. Update this file's frontmatter (`status`, `completed: 2026-06-23`, `result`).
2. `git mv` it into `prompts/done/`.
3. Add a `docs/decisions.md` entry: cross_system resolve now converges (write chosen value to both
   sides + refresh); weight resolves as a direct absolute write (no usage entry); rationale + the
   generalized-lifecycle approach.
4. You run UNATTENDED — do NOT ask for confirmation. Make ONE `fix:` commit on the current worktree
   branch covering every changed file + the prompt move (stage specific paths, never `git add -A`,
   never push). Suggested message:
   `fix: converge cross_system conflicts on resolve (write chosen value to both sides) (#21)`
5. Final message: commit SHA, full file list, test command + pass/fail counts, and any field type
   you could not fully wire (with why) — be explicit, since partial coverage is the main risk here.
