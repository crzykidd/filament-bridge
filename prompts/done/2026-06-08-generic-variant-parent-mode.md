---
name: 2026-06-08-generic-variant-parent-mode
status: completed
created: 2026-06-08
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-08
result: added variant_parent_mode config (unset/promote_color/generic_container), wizard gate, synthetic container parent synthesis with idempotent re-run, engine exclusions, Settings UI, Alembic migration, 13 new tests (734 total pass)
---

# Task: Add a "generic container parent" variant-parent mode to the import wizard

Give the user a choice for how the Bulk Import Wizard builds Filament DB's parent/variant
structure from flat Spoolman filaments. Today the wizard **promotes one color** to be the
parent. Add a second mode that **synthesizes a colorless container parent** (no color, no
spools, bridge-owned, never synced to Spoolman) with every Spoolman color as a child variant.
The mode is an explicit user choice with no implicit default.

## Background — read this first (the "why")

This was designed in an Opus session on 2026-06-08 after researching filament-db issues
[#597](https://github.com/hyiger/filament-db/issues/597) and
[#605](https://github.com/hyiger/filament-db/issues/605) and the filament-db v1.30–v1.35 release
history. Key findings that shape this task:

- **filament-db has no formal "generic parent" type.** A parent is just a top-level filament
  that *may* have its own color/spools/temps, or none. The "generic container parent" is a
  **user convention**, fully supported by the model (variants inherit unset fields from the
  parent; variants are one level deep only).
- **#597 (hatched white parent swatch) is already fixed upstream** in filament-db **v1.35.2**.
  The parent swatch now renders a **composite of the group's colors** (parent's own color +
  each variant's), falling back to the cross-hatch only when *no* colors are known. So the
  original motivation ("the hatch is ugly, force colorless parents") is gone — a colored parent
  AND a colorless parent both render fine now. Choosing the container pattern is therefore a
  **pure organizational preference** (count = children, no spools on the parent, uniform
  structure), not a rendering fix. Say this plainly in the user doc.
- **The architectural crux:** Spoolman is flat and has **no parent concept**. A synthesized
  container parent therefore has **no Spoolman counterpart** — it can only ever be a
  **bridge-owned, FDB-only record** that is created once on import and never participates in
  sync. This is the one genuinely new piece of engineering; everything else reuses existing
  clustering + parentId + D3-attach machinery.
- filament-db's *own* Spoolman/remote importer flattens everything (no parent/variant). Our
  bridge already reconstructs clusters, so we have latitude here.

Also read: `CLAUDE.md` (variant model, FDB/Spoolman data-model gotchas), `docs/prd.md`
(wizard FRs), `docs/decisions.md` (recent entries), and the existing wizard code listed below.

## Decisions already made (do not re-litigate)

1. **Mode is an explicit setting, default = unset.** New config key `variant_parent_mode`
   with values `unset` | `promote_color` | `generic_container`. Fresh installs default to
   `unset`; the user must choose before the wizard will run. `promote_color` reproduces
   today's exact behavior.
2. **`generic_container` synthesizes a parent for EVERY filament — even single-color clusters.**
   Uniform structure: every imported color is always a child; the parent is always a colorless
   container. (Yes, this roughly doubles FDB filament record count — that's accepted.)
3. **The synthetic parent is bridge-owned and never synced** to Spoolman. No color, no temps,
   no spools. Children carry all real data and sync 1:1 exactly as today.
4. **The existing D3 "attach to existing FDB parent" path stays** as a per-group override in
   both modes.
5. **A user-facing doc is required**, linked from the Settings UI (see deliverables).

## Working tree check

Before editing, run `git status --porcelain` and cross-reference the files below. If any have
uncommitted changes, list them and ask the user before touching them. Surface unrelated dirty
files once as awareness; don't block. This prompt file is exempt.

## What to do

### 1. Config — new `variant_parent_mode` setting
- Add `variant_parent_mode` to `BridgeConfig` (persisted, SQLite) in `backend/app/models/config.py`
  and the runtime config plumbing in `backend/app/config.py` / `backend/app/api/config.py`.
  Values: `unset` (default) | `promote_color` | `generic_container`. Validate the enum.
- Surface it in the Settings UI (`frontend/src/pages/Settings.tsx`) as a required choice with a
  short description and a **"Read the details" link to the new doc**. When `unset`, show it as
  needing a decision (e.g. a callout), not silently defaulting.

### 2. Gate the wizard on a chosen mode
- Wizard preview/execute endpoints (`backend/app/api/wizard.py`, Spoolman→FDB direction) must
  return a clear, structured error when `variant_parent_mode == unset` — e.g. 409 with a message
  telling the user to choose a mode in Settings. The frontend wizard should surface this and link
  to Settings. Do **not** silently fall back to `promote_color`.

### 3. Schema — let a FilamentMapping represent a bridge-owned parent
- In `backend/app/models/mapping.py`, `FilamentMapping.spoolman_filament_id` is currently
  `unique=True, nullable=False`. Make it **nullable** (SQLite allows multiple NULLs under a
  UNIQUE constraint, so the unique stays valid for real ids). Add **`is_synthetic_parent`**
  (bool, default `False`). The synthetic-parent row has `spoolman_filament_id = NULL`,
  `is_synthetic_parent = True`, `filamentdb_id` = the container's FDB id, `filamentdb_parent_id`
  = NULL.
- Write the Alembic migration (`cd backend && alembic revision --autogenerate -m "..."`; review
  it — autogenerate is imperfect on SQLite nullable/unique changes; hand-edit if needed).

### 4. Wizard execution — synthesize containers in `generic_container` mode
- In the Spoolman→FDB execute path (`_execute_spoolman_to_fdb` in `backend/app/api/wizard.py`,
  currently the master-promotion logic around `wizard.py:388` and passes 1–3 around
  `wizard.py:832–1192`), branch on `variant_parent_mode`:
  - `promote_color`: existing behavior, unchanged.
  - `generic_container`:
    - For **every** cluster (including size-1 — today's 2+ grouping gate must not apply here),
      ensure a synthetic container parent exists:
      - **Look it up first** (idempotency — the wizard is re-runnable): find an existing
        `FilamentMapping` with `is_synthetic_parent=True` matching this cluster (by cluster key /
        container name + vendor). If found, reuse its `filamentdb_id`. Never create duplicates.
        As a recovery path when the SQLite row is missing (e.g. after a state reset), the parent
        can also be recognized from Spoolman: the set of distinct non-empty `filamentdb_parent_id`
        extra-field values across this cluster's Spoolman children IS the set of FDB parent ids
        the bridge owns — reuse that id and re-create the missing synthetic `FilamentMapping` row
        rather than minting a second parent.
      - Otherwise `POST /api/filaments` to create a colorless container: `name` = the cluster
        display name (vendor + material + finish line — derive from
        `core/matcher.py:sm_variant_cluster_key` / `extract_finish_line`; e.g. "ELEGOO PLA",
        "Prusament PLA Silk"), `vendor`, `type`/material set (FDB requires only name+vendor+type).
        Send **`color: null`** (the FilamentInput schema marks `color` nullable and NOT
        required — verified against filament-db's `public/openapi.json`; the UI form defaults a
        color but the API accepts null), no `secondaryColors`, no temps, no spools,
        `parentId` = null. The v1.35.2 swatch fix renders a null-color parent as the composite
        of its children's colors. Record the synthetic FilamentMapping row.
    - Create **all** Spoolman colors in the cluster as variants with `parentId` = the container's
      FDB id. Each child gets its own color/name/temps/spools exactly as today.
- Update the planner/dry-run (`core/planner.py`, `core/dryrun.py`) so the preview shows
  "create container parent X + N color children" for `generic_container`, including size-1 groups.

### 5. Keep the synthetic parent out of sync
- **No Spoolman record is ever created for the synthetic parent.** It has no inventory, no
  properties of its own, and Spoolman's flat model has no parent slot. The relationship is
  already tracked entirely by data the bridge writes anyway: each child Spoolman filament carries
  the existing `filamentdb_parent_id` extra field = the synthetic parent's FDB id. Do NOT invent
  a placeholder Spoolman filament/vendor for the parent.
- The differ/engine reconciliation that flags FDB filaments lacking a Spoolman mapping (orphan
  detection / deletion-conflict generation) must **skip rows where `is_synthetic_parent=True`**.
  Grep `core/engine.py`, `core/differ.py`, and anywhere mappings are reconciled against upstream
  snapshots. A synthetic parent must never: be pushed to Spoolman, produce a conflict, or be
  reported as an orphan. Add focused tests pinning this.
- **Parent-level spool guard:** FDB still allows a user to attach a spool directly to a container
  parent. Such a spool has no Spoolman home (the parent has no Spoolman counterpart). The bridge
  must NOT silently invent a Spoolman filament for it — instead skip it and surface a one-line
  warning in the sync log (e.g. "spool on container parent <name> — move it to a color variant").
  Add a test for this case.

### 6. User-facing doc
- Add `docs/variant-parent-mode.md` explaining: the two modes; the generic-container model and
  its uniform "every color is a child" structure; the **consequence that the container parent
  has no Spoolman record and never syncs**; and the note that filament-db v1.35.2 already fixed
  the parent-swatch rendering (so colored parents look fine too — this is a preference, not a
  fix). Link it from the Settings setting. Keep it concise and user-oriented.

## Conventions to honor

- Match existing wizard/planner structure and naming; reuse `sm_variant_cluster_key` /
  `extract_finish_line` rather than re-deriving cluster identity.
- Tests: add backend tests alongside `backend/tests/test_api.py` (see existing
  `test_wizard_execute_*` cases, e.g. `test_wizard_execute_attach_existing_fdb_parent`). Cover:
  unset-mode gating, single-color container synthesis, multi-color container synthesis,
  re-run idempotency (no duplicate parent), and synthetic-parent sync-exclusion.
- Docs ship in the **same commit** as the code (CLAUDE.md rule). Update `CHANGELOG.md`
  `[Unreleased]`, and add/extend the env-var + runtime-settings tables in `CLAUDE.md` for the
  new `variant_parent_mode` key. Update `docs/spoolman-writes.md` only if write behavior changes
  (it shouldn't — the container is FDB-only).
- Conventional-Commit prefix `feat:`. No `Co-authored-by:`. Branch is `dev` (never `main`).

## Open questions to resolve while implementing (decide + note in decisions.md)

- **Existing installs**: how to treat `unset` for an install that already ran the wizard under
  today's promote-color semantics. Suggested: leave existing mappings untouched; only gate
  *new* wizard runs on a chosen mode. Confirm there's no disruptive migration.
- **Container naming collisions**: if two clusters normalize to the same display name within a
  vendor, ensure lookup keys on the full cluster tuple, not just the name string.

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/` (failure).
3. Record the non-obvious decisions (synthetic-parent bridge-ownership, nullable
   `spoolman_filament_id`, unset-gating, #597-already-fixed rationale) in `docs/decisions.md`.
4. Propose ONE commit covering the modified files (including the prompt move). Present the file
   list and a one-line `feat:` message; ask `commit these as "<message>"? (y/n)`. On `y`, stage
   those specific paths and commit on `dev`. Never `git add -A`. Never push.
