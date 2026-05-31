---
name: 2026-05-30-unified-dryrun-plan
status: completed
created: 2026-05-30
model: opus              # opus = research/planning, sonnet = coding
completed: 2026-05-31
result: Planner extracted to core/planner.py; plan_dry_run in core/dryrun.py; 167 orphans → update; 56 false conflicts removed; 164 tests green.
---

# Task: Unify the Dashboard dry-run into a matcher-driven plan (created / updated / conflicted / skipped)

The Dashboard "Dry run" button (`POST /api/sync/dry-run`) reports only counts, and on an
**empty/uninitialized** bridge it dumps everything into "conflicts" and silently drops the
rest. Make the dry-run a real **plan** that always reports — regardless of bridge state —
how many records would be **created**, **updated**, **conflicted**, and **skipped**, with
an expandable per-record list under each category.

## Why this is needed (verified diagnosis — read before designing)

The Dashboard button calls `run_sync_cycle` (core/engine.py) — the **steady-state** engine.
It diffs *already-linked* pairs and **never runs the matcher**, so on a fresh bridge DB:
- It can't compute "would create" / "would match" (no matcher, no mappings).
- Every unmapped Spoolman spool falls into the `no_filament_mapping` branch → bucketed as a
  **conflict** (a placeholder, not a real conflict).
- Spools that already carry a `filamentdb_spool_id` cross-ref extra but have no
  `SpoolMapping` row hit a silent `continue` (engine.py ~L862-865) and vanish — neither
  created, updated, conflicted, nor skipped.

Verified against the live dev data (2026-05-30): 223 active Spoolman spools; 167 already
carry `filamentdb_*` cross-ref extras; 223 − 167 = **56** → exactly the "56 conflicts",
all `no_filament_mapping`. The bridge-dev DB has **zero** mappings.

**Decision (made with the user):** *unify* — the dry-run auto-runs the matcher and shares
the wizard's planner, so it produces real created/updated/conflicted/skipped whether the
bridge is empty or already linked. (Other options — keep two tools, or reclassify without a
matcher — were rejected.)

## Scope guardrails (read first)

- **Read-only.** The dry-run must call NO mutating FDB/Spoolman endpoint. Reads are fine.
- **Do NOT change live sync.** `run_sync_cycle(dry_run=False)` and `wizard_execute` keep
  their current behaviour. In particular **never wire the matcher's auto-create into live
  `run_sync_cycle`** — auto-sync must still require a completed wizard (hard rule:
  initial-sync creates/mappings are the wizard's job). The matcher runs only to *compute the
  preview*.
- **Never auto-resolve.** Ambiguous matches and real conflicts are surfaced, not resolved.
- **Preview ≡ execute (by attribution).** Each bucket must mirror what the real executor
  would do, using the **same planner code**, so preview can't drift from execute:
  - *create / matched(link)* rows mirror `wizard_execute`'s planner (the initial import).
  - *updated / conflict / skipped on already-linked pairs* mirror `run_sync_cycle`'s
    steady-state diff.
  The UI should make clear that the create/match portion is performed by the **initial-sync
  wizard**, not by "Trigger sync".

## Before you start

- **Read `CLAUDE.md`** (weight model, hard rules: no auto-resolve, dry-run writes nothing,
  initial sync is the wizard's job) and the FR-4 prompt
  `prompts/2026-05-30-reconcile-preview-dryrun.md` (its planner is the thing you share).
- Use `vexp` `run_pipeline` for context, not grep/glob.
- Study and REUSE (do not reinvent):
  - `backend/app/core/matcher.py::match_filaments` → returns `matched` (1:1, → **updated**),
    `ambiguous` (multiple FDB candidates, → **conflict**), `unmatched_spoolman`
    (→ **created**), `unmatched_fdb`. This is the auto-decision source.
  - `backend/app/api/wizard.py::_plan_spoolman_to_fdb` + `_SyncPlan`/`_FilamentPlanItem`/
    `_SpoolPlanItem` (the FR-4 planner — pure, no writes) and `wizard_preview`'s mapping of
    plan actions → record rows. **Note:** this planner currently reads *saved wizard
    decisions* (`wizard_match_decisions`); for the dry-run you'll feed it
    **auto-decisions from the matcher** instead, so it reports without the wizard having run.
  - `backend/app/core/engine.py::run_sync_cycle` — the steady-state per-pair diff
    (weight/field/conflict/skip) for *already-linked* pairs.
  - `backend/app/schemas/api.py::CycleResultResponse` (`preview: list[dict]`),
    `backend/app/api/sync.py::dry_run_sync`/`_to_response`.
  - `frontend/src/pages/Dashboard.tsx` (~L154-165, renders only counts),
    `frontend/src/api/types.ts`, `frontend/src/components/DeepLinks.tsx`.

## Working tree check

Run `git status --porcelain`. **Already dirty from the FR-4 wizard-preview WIP:**
`backend/app/api/wizard.py`, `backend/app/schemas/api.py`, `backend/tests/test_api.py`.
This task **depends on** the FR-4 planner (`_plan_spoolman_to_fdb`) — confirm with the user
whether to (a) land/commit the FR-4 WIP first, or (b) build on the uncommitted tree. Before
editing those three files, surface them and ask. Files this task additionally
adds/edits: a shared planner module (see step 1), `backend/app/core/engine.py` or a new
`backend/app/core/dryrun.py`, `backend/app/api/sync.py`, `frontend/src/pages/Dashboard.tsx`,
`frontend/src/api/types.ts`, `backend/tests/*`. List unrelated dirty files once as
awareness. This prompt file is exempt.

## What to do

### 1. Put the planner where both callers can share it
`_plan_spoolman_to_fdb` lives in `wizard.py` today. Move it (and its `_SyncPlan` dataclasses
+ the pure flag/label helpers it needs) into a shared module, e.g. `backend/app/core/planner.py`,
and have `wizard.py` import from there. This is what guarantees preview ≡ execute. Keep it
pure (no writes; reads via passed-in fetched state).

### 2. Build auto-decisions from the matcher (no wizard required)
Add a function that turns `match_filaments(sm_filaments, fdb_filaments)` into the same
`decisions_by_sm` shape the planner consumes:
- `matched` (confidence 1:1) → decision `{action: "link", filamentdb_id: <fdb.id>}`.
- `unmatched_spoolman` → decision `{action: "create"}`.
- `ambiguous` → **do not** auto-pick; mark as a **conflict** (carry the candidate FDB ids so
  the future decision UI can offer the choice). The planner has no "conflict" action, so
  handle ambiguity before/around the planner (e.g. exclude from decisions and emit a
  conflict row directly).
- Honor the configured `import_direction`. For the non-default direction, mirror
  `wizard_preview`'s current behaviour rather than inventing new logic.

### 3. Compose the unified dry-run plan
Produce one classification over every relevant record into the four buckets, combining:
- **Already-linked pairs** (a `SpoolMapping`/`FilamentMapping` exists): run the existing
  steady-state diff from `run_sync_cycle` → **updated** (changed), **conflict** (both sides
  changed — real FR-13), or **skipped** (no change / baseline / archived).
- **Unlinked records**: matcher auto-decisions → planner → **created** (new FDB filament +
  spool), **updated** (matched/link to existing FDB), **conflict** (ambiguous), **skipped**
  (archived / `remaining_weight==0` empty-active is a *warning badge*, not its own bucket).
- **Cross-ref orphans** (SM spool has `filamentdb_spool_id` extra but no `SpoolMapping` —
  the 167): **stop silently dropping them.** Recommended default: bucket as **updated** with
  reason `"re-link from existing cross-ref"` (the cross-ref already encodes the mapping; a
  fresh bridge DB should rebuild it). This is a real sub-decision — confirm the default with
  the user; the only unacceptable outcome is the current silent `continue`.

Implement this as a read-only planner (e.g. `core/dryrun.py::plan_dry_run(...)`) that
`POST /api/sync/dry-run` calls. The live `POST /sync/trigger` path is untouched.

### 4. Standardize the preview entry shape
Each row (loose dict is fine, or a typed `SyncPreviewEntry` model — coordinate with the
dirty `schemas/api.py`):
```python
{
  "action": "create" | "update" | "conflict" | "skip",
  "entity_type": "filament" | "spool",
  "direction": "spoolman_to_filamentdb" | "filamentdb_to_spoolman" | None,
  "label": "<human-readable: vendor name color — SM #id / FDB name>",
  "field": <str> | None, "old": <any> | None, "new": <any> | None,   # updates
  "reason": <str> | None,                                            # conflict & skip
  "candidates": [<fdb_id>, ...] | None,                              # ambiguous conflicts
  "spoolman_id": <int> | None, "fdb_filament_id": <str> | None, "fdb_spool_id": <str> | None,
}
```
Build `label` from already-fetched fields (Spoolman: `sm.vendor.name`/`sm.name`/`color_hex`/
spool `id`; FDB: `name`). Degrade to IDs when a name isn't in hand.

### 5. Frontend — four collapsible sections (Dashboard.tsx + types)
- Update `frontend/src/api/types.ts` to the chosen entry shape.
- Replace/extend the count row with four collapsible sections (`<details>`/`<summary>`,
  existing styling): `Created (n)`, `Updated (n)`, `Conflicts (n)`, `Skipped (n)` where
  `n = preview.filter(p => p.action === ...).length`. `Errors` stays an inline badge.
- Each row shows `label`, a small direction tag, `field` + `old → new` for updates, `reason`
  (and candidate count for ambiguous) for conflicts/skips, and a `DeepLinks` pair from
  `spoolman_id`/`fdb_filament_id`. Read-only — no mutating buttons.
- Add a one-line note that "Created/Matched" items are applied by the **initial-sync
  wizard**, with a link to it (so the user understands "Trigger sync" alone won't create).

## Conventions to honor

- Read-only dry-run; delegate HTTP to existing service clients; never write to upstreams.
- One shared planner — no parallel copy of payload/weight/match logic. Reuse `matcher`
  normalization and the existing weight conversion.
- Structured logs, respect `LOG_LEVEL`; never touch the FDB `settings{}` bag.

## Verification

- `cd backend && pytest` green. New/updated tests:
  - **Empty bridge DB** (no mappings) with seeded SM + FDB state: the plan returns a
    **non-zero `created`** count (unmatched SM), a **non-zero `updated`** count where SM
    matches existing FDB, `conflict` ONLY for ambiguous (multi-candidate) matches, and
    cross-ref-orphan spools land in `updated`(re-link) or the agreed bucket — **never
    silently dropped**.
  - Asserts NO mutating client call happens (mock that fails on POST/PUT/PATCH).
  - Asserts the matcher is actually invoked (vs the old all-conflict behaviour).
  - **Already-linked pair** with a one-sided weight change → `updated`; both-sided →
    `conflict`; no change → `skipped`.
  - Every entry has a category `action` and a non-empty `label`.
  - A regression test that `run_sync_cycle(dry_run=False)` behaviour is unchanged.
- `cd frontend && npm run build` green; four sections render with correct counts + rows.
- **End-to-end on the local stack** (`docker-compose.dev.yml`; re-seed
  `private_data/spoolman-livedata.db`; empty bridge DB): trigger the Dashboard dry-run and
  confirm the buckets are sensible for the 223-active / 167-cross-ref / 56-uncrossed data
  (creates + matches dominate; conflicts only where ambiguous; the 167 no longer vanish),
  the per-category counts sum consistently, and **nothing was written** to FDB or Spoolman.

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/` (failure).
3. Record the non-obvious decisions in `docs/decisions.md`: where the shared planner now
   lives, the matcher→decisions mapping, the ambiguous→conflict rule, and the cross-ref-orphan
   bucket choice. Note in `docs/reconcile-backlog.md` how this relates to the FR-4 preview.
4. Propose ONE commit (no `Co-authored-by:`). Suggested message:
   `feat: unified matcher-driven dry-run plan (created/updated/conflicted/skipped)`.
   Present the file list and ask `commit these as "<message>"? (y/n)` before staging. Stage
   specific paths only; commit on `dev`; no push.
