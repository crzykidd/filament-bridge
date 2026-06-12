---
name: 2026-06-11-import-archived-empty-spools
status: pending          # pending | completed | failed
created: 2026-06-11
model: opus              # PLAN first (engine ripple), then implement via sonnet
completed:
result:
---

# Task: Stop hard-excluding archived spools — gate empty/archived import on `never_import_empties`

## The verified root cause (proven against live data, do not re-litigate)

A user imported 3 Spoolman filaments via the wizard. All 3 filaments are created in FDB,
but only 2 appear in Synced Records. The user assumed a name collision — it is NOT
(preview shows 0 collisions). The real cause:

- Spoolman filament **63 "Light Purple PLA"** has exactly **one** spool, **#65**, and it
  is **`archived = 1`** and **empty** (`used_weight 1047.98 > initial_weight 1000.0` →
  remaining ≤ 0).
- The wizard builds its spool lists from **non-archived spools only**. The `if not
  s.archived` filter drops archived spools *before* the `never_import_empties` gate is
  ever consulted. So an archived/used-up spool can never be imported, **even when
  `never_import_empties` is unchecked** (the default, which means "do import empties").
- Result: no spool created → no `SpoolMapping` → the filament (which imports fine, since
  filaments are created regardless of spools) is invisible in Synced Records, because that
  view lists one row per spool mapping.

For comparison, filament 53 has spools #55 (active, imported) + #143 (archived, dropped);
filament 106 has #122 (active, imported). Only the archived ones are lost.

**The desired behavior (from the user):** honor the `never_import_empties` setting. When
it is **unchecked** (`never_import_empties = false`, the default), empty spools — including
archived/used-up ones — **should be imported**. When checked, skip empties.

## Where the bug lives (verified line refs)

The `if not s.archived` hard-exclusion is repeated across the wizard. Every spool-iteration
site that builds import/preview state needs review:

- `backend/app/core/planner.py:316` — `if not getattr(s, "archived", False):` builds
  `sm_spools_by_filament`; archived spools never become spool plan items. **This is the
  one that stops Light Purple's spool from being created.**
- `backend/app/api/wizard.py:464` — `spools_per_filament` (variant master heuristic).
- `backend/app/api/wizard.py:611-621` — `spool_ids_per_filament` + `spools_per_filament` in
  the variances endpoint. Note lines 612-614 show the pattern clearly: archived dropped
  first, THEN the `include_empty` gate — the gate only ever sees active spools.
- `backend/app/api/wizard.py:291, 397, 1129, 1880` — other archived checks (xref map,
  empties counter, etc.) — audit each for whether it should now include archived.
- Empty-spool gate logic (the part to reuse/extend): `never_import_empties` →
  `include_empty = not never_import_empties` at `wizard.py:252, 589-590, 2110-2111,
  2267-2268` and `core/dryrun.py:143-144`.

## The fix (semantics to implement — confirm in the plan)

1. **Archived spools are no longer categorically excluded from import.** They flow through
   the same empty-spool gate as active spools:
   - `never_import_empties = false` → import empty spools, **including archived ones**.
   - `never_import_empties = true` → skip empty spools (remaining ≤ 0), archived or not.
2. **Import archived spools into FDB as RETIRED spools**, not active. FDB spools carry a
   `retired` flag (seen in snapshots as `"retired": false`). Preserve the archived/retired
   state — do NOT resurrect a retired Spoolman spool as an active FDB spool. Spool #65 →
   FDB retired spool → `SpoolMapping` created → Light Purple shows in Synced Records.
3. **Weight model still applies** — an empty/archived spool imports with its real
   (near-zero) remaining weight via the existing net↔gross conversion. Do not special-case
   the weight.
4. **Master heuristic** — decide whether archived spools count toward the "which member is
   the master" heuristic (`spools_per_filament`). Recommend keeping it active-only so
   retired inventory doesn't skew master selection; state the choice in the plan.

## Transparency (the user's other complaint — "no details on the sync log")

5. **Wizard preview** must make archived/empty handling visible — a bucket/count like
   "Archived/empty spools (will import as retired)" so the user sees what's happening
   instead of records silently vanishing. The existing "Empty active spools" stat at
   `wizard.py:1880` is active-only; extend or add a sibling for archived.
6. **Sync log / execute outcomes** must record a meaningful detail for these imports
   (e.g. "spool #65 imported as retired (archived in Spoolman)"), not a bare `create` with
   `—`. Check the `_ExecResult.add(...)` detail path used in `_execute_spoolman_to_fdb`.

## Guardrails — the ongoing engine (why this is plan-first)

Bringing archived spools into scope ripples past the wizard into `core/engine.py` /
`differ.py` / snapshots. The plan MUST address:

- The engine must NOT re-animate a retired FDB spool or fight the archived↔retired state on
  every cycle (ping-pong risk — see the FR-11 bug class in `docs/decisions.md` and
  `docs/sync-model.md`: snapshot BOTH sides after any propagation).
- Snapshots for retired/archived spools must seed correctly so they read as in-sync, not as
  a perpetual pending/conflict.
- Confirm `services/spoolman.py` already returns archived spools (it does — see its
  docstring at line 107: "Fetch all spools (active + archived)… Caller is responsible for
  filtering"). So the data is already available; this is purely about the *callers*.

## Before you start

- Read `CLAUDE.md` (weight model, Spoolman/FDB data-model gotchas, "What NOT to do"),
  `docs/sync-model.md`, `docs/wizard.md`, `docs/configuration.md` (the
  `never_import_empties` setting), `docs/spoolman-writes.md`, `docs/decisions.md`.
- Note the gotcha already in CLAUDE.md: Spoolman `?archived=true` returns ONLY archived
  spools, not "include archived."

## Working tree check

Run `git status --porcelain`; cross-reference the files this touches. If any are dirty,
list them and ask before touching. This prompt file is exempt.

## Step 0 — PLAN before coding (required; model=opus)

Write a short plan covering: the exact archived/empty gate semantics (item 1-2), every
`if not s.archived` site and whether it changes, the retired-spool FDB representation, the
engine/snapshot guardrails, the preview/sync-log transparency surface, and the test matrix.
Confirm anything ambiguous with the user before implementing.

## What to do (after the plan is agreed)

1. Route archived spools through the empty-spool gate at every identified site; import them
   as retired FDB spools with mappings.
2. Add preview visibility + sync-log detail for archived/retired imports.
3. Engine/snapshot guardrails so retired spools stay in-sync and never ping-pong.
4. Tests:
   - Wizard execute with `never_import_empties=false`: an archived-only filament (fixture
     mirroring SM filament 63 / spool 65) imports its spool as retired → SpoolMapping
     exists → appears in `build_mapping_rows`.
   - `never_import_empties=true`: empty/archived spools are skipped.
   - Engine cycle after such an import logs no spurious update/conflict for the retired
     spool (no ping-pong).
   - Backend pytest + ruff; frontend tsc + npm test (preview bucket renders).

## Conventions to honor

- Reuse the existing `never_import_empties` / `include_empty` plumbing — do not invent a new
  setting.
- Idempotent, failure-isolated writes; never abort the batch on one spool.
- Update `docs/wizard.md`, `docs/configuration.md`, `docs/spoolman-writes.md` and log the
  decision in `docs/decisions.md`, in the same commit as the code.
- REQUIRED checks before proposing the commit: `cd backend && pytest` + `ruff check`, and
  `cd frontend && npx tsc --noEmit` + `npm test`. All green.
- Conventional-commits: `fix:` (archived spools were silently dropped). No `Co-authored-by:`.
  Branch `dev`, never `main`, never push.

## When done

1. Update this file's frontmatter (`status`, `completed`, `result`).
2. `git mv` to `prompts/done/` (or `prompts/failed/`).
3. Record the decision in `docs/decisions.md`.
4. Propose ONE commit (stage specific paths, never `git add -A`); present file list + a
   one-line message and STOP for the user to run the commit. Never push.
