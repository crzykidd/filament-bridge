---
name: 2026-06-11-new-record-handling-policies
status: completed
created: 2026-06-11
model: opus              # PLAN first (engine + config + new endpoint + hierarchy), then implement
completed: 2026-06-11
result: |
  Implemented two-tier new-record handling policy. Added new_filament_policy +
  new_spool_policy config keys (default: manual_review). Engine now queues actionable
  new_filament conflicts and optionally auto-imports filaments/spools via
  import_single_sm_filament/import_single_fdb_filament (shared helper in
  app/core/single_record_import.py). New endpoint POST /api/conflicts/{id}/import
  handles scoped single-record import with dry_run support. Anti-ping-pong invariant
  verified by test_auto_import_no_pingpong. 738 tests pass, ruff clean, tsc clean,
  53 frontend tests pass.
---

# Task: New-record handling — new-filament + new-spool policies, auto-import, and scoped "Add"

This is prompt **#1 of 3** (must land before the Conflicts UI redesign, which calls the
endpoint added here). Plan-first — it touches the engine, config schema, a new endpoint,
and the filament→spool hierarchy.

## Verified root cause (proven this session — do not re-litigate)

- `new_spool_sync_direction` (`config.py`, default `"two_way"`) **only gates which
  direction's detection runs** (`engine.py:~2854/2869`). It does NOT decide auto-create vs
  conflict.
- The real branch is in `_handle_new_sm_spool` (`engine.py:~1973`): if the spool's
  **filament has a mapping** → the engine **auto-creates** the FDB spool; if the filament
  is **unmapped** → it **always queues a `new_spool` conflict**, regardless of direction.
- **The ongoing engine never creates filaments** — `create_filament` appears nowhere in
  `engine.py`; only the wizard creates them. **There is no new-filament policy at all.**
- Net: a brand-new Spoolman filament sits unmapped forever, and every spool under it floods
  the conflict queue with only a "Dismiss" option. New-record handling is half-built.

## The mental model to implement (and document)

A **filament is a container**; in Filament DB the hierarchy is parent → variant → **spool**.
Sync flows **top-down**: a spool can only sync once its filament exists and is mapped. If the
filament isn't mapped, the spool is **held** (queued for review, or auto-handled per policy)
— **never silently dropped**.

## What to build

### A. Two new policies (both default to **Manual review**)

- **`new_filament_policy`**: `manual_review` (default) | `auto_import`.
- **`new_spool_policy`**: `manual_review` (default) | `auto_import`.

Decide in the PLAN how these compose with the existing `new_spool_sync_direction`
(direction axis = which way new records flow; policy axis = review vs auto). Recommended:
keep direction as-is and add the two policy keys; a record is auto-created only when its
direction is enabled AND its policy is `auto_import`. Add to `config.py` defaults,
`api/config.py` response + `ConfigUpdateRequest`, and the `ConfigResponse`/types. Don't
break existing config shape. Migrate via `_migrate_sync_config` if needed
(default existing installs to `manual_review` — safe, no behavior change).

### B. Auto-import paths (respecting the hierarchy)

- **New filament, `auto_import`:** ongoing engine creates the unmapped filament in the
  target system using the planner/wizard defaults, writes the FilamentMapping + cross-refs,
  snapshots BOTH sides. Reuse `_plan_spoolman_to_fdb` / the wizard execute helpers — do NOT
  duplicate create logic. Respect `variant_parent_mode` (if `unset`, a variant filament
  can't be auto-grouped — fall back to standalone create or hold; state the choice in the
  plan), version gates (`MIN_FDB`/`MIN_SPOOLMAN`), and the weight model.
- **New spool, `auto_import`:** if the filament is mapped, create the spool (this path
  mostly exists — `engine.py:~2009`); if the filament is unmapped, the spool is **held**
  pending the filament policy (auto-create the filament first if `new_filament_policy=auto`,
  else queue/hold). Never create a spool whose filament doesn't exist.
- **manual_review (either tier):** queue an *actionable* conflict (see C) — not just a
  dismissible notice.
- **Anti-ping-pong:** after any auto-create, snapshot BOTH sides to the agreed state
  (FR-11 invariant — see `docs/sync-model.md`). Add an engine test proving a second cycle is
  a NOOP for an auto-created record (mirror `tests/test_engine.py::test_archived_imported_spool_no_pingpong`).

### C. Scoped single-record import endpoint (powers the "Add" button in prompt #2)

Add an endpoint (e.g. `POST /api/conflicts/{id}/import` or `POST /api/wizard/import-record`)
that imports ONE conflicted new record (and its filament if needed) using the existing
planner + execute, scoped to that single filament/spool. The planner
(`_plan_spoolman_to_fdb`) already accepts filtered single-element lists. Inputs it needs: a
filament decision (link to an existing FDB filament id OR create), optional tare override,
optional variant grouping. Return a preview, then execute on confirm (or do
preview+execute in one call with a decision payload — settle in the plan). On success it
resolves/removes the `new_spool` (and any `new_filament`) conflict and writes the mapping.

### D. README + docs

- **README:** add a **"Concepts"** section documenting the container model (filament →
  variant → spool) and the **hold-until-filament** rule above. This is the canonical
  explainer the user asked for.
- `docs/configuration.md`: document `new_filament_policy` + `new_spool_policy`.
- `docs/conflicts.md` + `docs/sync-model.md`: document the new-record hierarchy + auto paths.
- `docs/decisions.md`: log the policy-axis design + the variant_parent_mode/unset handling.

## Before you start

Read `CLAUDE.md`, `docs/sync-model.md`, `docs/conflicts.md`, `docs/wizard.md`,
`docs/variant-parent-mode.md`, `docs/configuration.md`. Key code: `engine.py`
(`_handle_new_sm_spool` ~1973, `_handle_new_fdb_spool` ~2096, the new-spool dispatch
~2854-2906), `core/planner.py` (`_plan_spoolman_to_fdb`), `api/wizard.py` (execute helpers),
`api/conflicts.py`, `core/conflict_apply.py`, `models/config.py`, `api/config.py`,
`main.py` (`_migrate_sync_config`), `core/sync_policy.py`.

## Working tree check

`git status --porcelain`; if files this touches are dirty, list them and ask. This prompt is
exempt. (Expected clean except untracked dotfiles + sibling prompts.)

## Step 0 — PLAN before coding (required; model=opus)

Plan covering: exact config schema (policy keys + how they compose with direction +
migration), the auto-create code paths (reuse points, variant_parent_mode/unset handling,
version gates, snapshot-both-sides), the scoped-import endpoint shape (preview/execute,
decision payload, conflict resolution), and the test matrix. Confirm anything ambiguous
with the user before implementing.

## What to do (after plan agreed)

Implement A–D. Tests: policy gating (manual queues / auto creates) for both tiers; spool
held until filament exists; scoped-import endpoint creates record + mapping + resolves
conflict; engine no-ping-pong after auto-create; migration defaults to manual_review.
Backend pytest + ruff; frontend tsc + npm test (config types).

## Conventions to honor

- Reuse planner/execute — never duplicate create logic. Idempotent, failure-isolated,
  snapshot-both-sides. Respect version gates + weight model + variant_parent_mode.
- Docs ship in the same commit. Conventional-commits `feat:`. No `Co-authored-by:`.
  Branch `dev`, never `main`, never push.
- Note for the sandbox: `test_api.py`/`test_auth.py`/`test_debug.py`/`test_sync_policy.py`
  fail at collection on missing `itsdangerous` (env-only, in requirements) — ignore; ensure
  no NEW failures.

## When done

Update frontmatter; `git mv` to `prompts/done/`; log decision in `docs/decisions.md`;
propose ONE `feat:` commit (specific paths, never `git add -A`) and STOP for the user to
run it. Never push.
