---
name: 2026-06-04-wizard-variant-resolution-redesign
status: completed
created: 2026-06-04
model: sonnet
completed: 2026-06-04
result: D1–D4 implemented; 218 tests pass, ruff clean, tsc clean.
---

# Task: Wizard variant-resolution redesign (D1–D4) — vendor+material grouping, per-member exclude, FDB-parent attach, empty-spool toggle

The Spoolman→Filament DB initial-sync wizard's Variances step is broken in a way small
tweaks won't fix: two filaments that are clearly the same vendor+material differing only by
color (e.g. ELEGOO **Brown** + **Beige**, both PLA) land as two *standalone* filaments with
**Variant groups: 0**, there is no manual-group path, and the wizard never loads Filament
DB's existing state so it can only ever create fresh duplicate parents. This task
implements the four locked decisions (D1–D4) from `docs/wizard-redesign.md`.

**Read `docs/wizard-redesign.md` first — it is the spec.** This prompt is the execution
plan; the spec has the conceptual model (color lives at the filament level; the parent IS
the "type"; two filaments + two spools is correct, *Variant groups: 0* is the bug).

## Before you start

- Read, in order:
  - `docs/wizard-redesign.md` (the spec — D1–D4 + the conceptual model + touch points).
  - `CLAUDE.md` — variant model, weight/tare model, the `spoolWeight`-is-filament-level
    gotcha, and the **hard rules** (never auto-resolve conflicts; never delete; map-not-copy).
  - `docs/decisions.md`, especially **2026-05-31 "Spoolman→FDB variant grouping: SM-keyed
    master-promote"** and **2026-06-03 "Wizard: merged Variances step"** — this task
    *extends* both; it must not contradict "master = a real filament" or "clusters are
    hints only".
  - `docs/prd.md` FR-5 (weights) + FR-6 (variants).
- **This is a multi-file change across backend schema + API + matcher + frontend. Read
  every file you'll touch before editing.** Key locations (verify line numbers — they
  drift):
  - `backend/app/core/matcher.py` — `sm_variant_cluster_key` (L97), `sm_prop_conflicts` (L105).
  - `backend/app/api/wizard.py` — `_included_sm_ids` (L113), `wizard_variances` (L387–478),
    `wizard_save_sm_variants` (L368), the plan builder `_build_sync_plan` (~L612) with its
    Pass-1 masters / Pass-2 variants (`variant_master_sm_id`), `_compute_empty_active`
    (L973), `_compute_variant_groups` (L999), `wizard_preview` (L1059).
  - `backend/app/schemas/api.py` — `SMVariantDecision` (L302), `VariancesFilament` (L322),
    `VariancesGroupRow` (L339), `VariancesResponse` (L347), `EmptyActiveEntry` (L423).
  - `backend/app/schemas/filamentdb.py` — `FDBFilament.parentId` (L116),
    `FDBFilamentDetail` `parent`/`variants` refs (L161–168).
  - `frontend/src/pages/Wizard/StepVariances.tsx` (SM branch = `SMVariancesStep`),
    `Step2Direction.tsx`, `StepNPreview.tsx`, `frontend/src/api/types.ts`,
    `frontend/src/api/client.ts`.

## Working tree check

Before editing, run `git status --porcelain` and cross-reference the files this plan
modifies. If any have uncommitted changes, list them and ask. Surface unrelated dirty
files once; don't block. This prompt file is exempt.

## Locked decisions & defaults for the open questions

D1–D4 are confirmed (see spec). The spec's open questions are resolved for THIS task as:
- **Q1 (line separation within vendor+material):** **Do not** parse finish/line tokens out
  of names in this pass. Group by `vendor + material` only and rely on **D2** (per-member
  exclude, pre-flagged by `sm_prop_conflicts`) to peel off divergent lines like PLA Matte /
  Silk / glow / color-changing. Document this as a deliberate simplification.
- **Q2 (where attach is decided):** Matches = color identity (unchanged). Variances =
  grouping **and** existing-FDB-parent attach targets.
- **Q3 (empty-spool toggle placement):** On the **Direction step (Step 2)**, persisted as
  wizard config, applied globally.
- **Q4 (Matches formatting) and Q5 (source-of-truth behavior):** out of scope here.

## What to do

Implement in this order (D1+D2 together, then D4, then D3 — D3 is the heaviest and touches
the execute path).

### D1 — Grouping key becomes `vendor + material` (drop base_name)

1. Change `sm_variant_cluster_key` (`matcher.py`) to key on `(normalize_vendor(vendor),
   normalize_name(material))` only — drop the `base_name` (color-stripped) component. Update
   its docstring and return-type/tuple arity. Different colors under the same vendor+material
   are now the variant-group signal.
2. Fix every caller of the tuple (it had arity 3): `wizard_variances` (`wizard.py:418-426`
   unpacks `(vendor_norm, material_norm, base_name)`), the legacy `wizard_variants` SM
   branch (~L314), and `_compute_variant_groups` if it keys on the same tuple. The group's
   display `base_name` should now derive from the vendor+material (e.g. `"<Vendor> <Material>"`)
   or the master's name — pick one and keep `VariancesGroupRow.base_name` populated sensibly.
3. Keep the master heuristic (most spools, tie-break shortest name) and the
   "singletons (cluster < 2) are not groups" rule.

### D2 — Per-member exclude, pre-flagged by the conflict signal

4. `wizard_variances` already computes `conflicts` per member via `sm_prop_conflicts`.
   Surface a **suggested-exclude** signal: a member is pre-flagged when it has ≥1 conflict
   with the suggested master. Add a field to `VariancesFilament`, e.g.
   `suggest_exclude: bool = False`, set true when `len(conflicts) > 0` for non-masters.
   (Conflicts are still never auto-resolved — this only *suggests*, the user decides.)
5. Frontend `SMVariancesStep`: render the new vendor+material groups (they'll now be
   non-empty for Brown/Beige). For each non-master member, show a **"don't include →
   standalone"** control, and **pre-check it as excluded** when `suggest_exclude` is true
   (with the conflict reason shown inline — the existing conflict banner already does this).
   Excluding a member moves it to the Standalone section as its own filament (its own tare).
   This reuses the existing `groupMembership` / `toggleMember` state — wire the
   pre-exclusion into the initial `groupMembership` so suggested-excludes start unchecked.
6. **Manual grouping (the missing path):** add a way to build a group from Standalone rows —
   checkbox-select 2+ standalone filaments + a "Group as variants" action that creates a new
   editable group (pick master via the existing radio). The save path
   (`postWizardSmVariants` → `wizard_save_sm_variants`) already accepts arbitrary
   `{master, variants}` payloads, so this is frontend state only.

### D4 — "Include empty/depleted spools" toggle (global, on Direction step)

7. Backend: add a wizard config key `wizard_include_empty_spools` (bool, **default
   `false`**), read/written via the existing `get_config_value`/`set_config_value` helpers.
   Add a GET/POST (or fold into the existing direction-config endpoints) so Step 2 can read
   and persist it.
8. Define "empty/depleted spool" exactly as `_compute_empty_active` does today: not archived
   AND `remaining_weight == 0.0` (`wizard.py:976`). Add a single helper (mirror
   `_included_sm_ids`'s "one definition" pattern), e.g. `_spool_is_excluded_empty(spool, db)`
   or a set-builder, and apply it:
   - **Plan builder** (`_build_sync_plan` / wherever spools become create items): when the
     toggle is `false`, do **not** create empty spool records — but still create/resolve the
     filament/color definitions they belong to (separate the color from the inventory record,
     per D4).
   - **`wizard_variances` spool-id collection** (`spool_ids_per_filament`, L409-412) and the
     **weights** path: respect the toggle so tare/weight rows don't include skipped empties.
   - **Preview** (`wizard_preview` / `_compute_empty_active`): when the toggle is `false`,
     the "Empty active spools" panel reports what's being **skipped** (informational), not an
     unresolved flag; when `true`, they're imported normally. Update the panel copy in
     `StepNPreview.tsx` to reflect "skipped by setting" vs "will import".
9. Frontend Step 2: add the toggle ("Include empty / depleted spools"), persist on change.

### D3 — Load FDB state; resolve each incoming color as Link / Attach / Create

This is the core fix and the heaviest piece. **Match (color identity) stays on Matches;
this adds parent attachment on Variances.**

10. **Reconstruct the FDB parent/variant tree.** `wizard_variances` must now also load
    `request.app.state.filamentdb.get_filaments()` (as other endpoints already do). An FDB
    *parent line* is identifiable by `(vendor, material)` of its filaments and the
    `parentId` links (`FDBFilament.parentId`; a parent is a filament that others point to,
    or one with `parentId is None` that has children). Build a map
    `(normalize_vendor, normalize_name(material)) -> existing FDB parent {id, name}`.
11. **Surface attach targets.** For each vendor+material group in the variances response,
    if an existing FDB parent line matches that key, include it on `VariancesGroupRow`, e.g.
    `existing_fdb_parent: FilamentRef | None`. The frontend then offers, per group, a choice:
    **"Attach to existing FDB parent «ELEGOO PLA»"** vs **"Create new parent"** (default to
    attach when an existing parent is present — it's the safer, non-duplicating action).
12. **Persist the attach decision.** Extend `SMVariantDecision` with an optional
    `existing_fdb_parent_id: str | None = None`. Semantics:
    - `existing_fdb_parent_id is None` → today's behavior: promote the master, stamp
      `parentId` on the non-masters at create (SM-keyed master-promote, unchanged).
    - `existing_fdb_parent_id` set → **all** members (including what was the "master") are
      created as variants with `parentId = existing_fdb_parent_id`; **no new parent is
      created and no master is promoted.** Don't modify or delete the existing FDB parent
      (hard rule) — only set `parentId` on the new variants.
13. **Honor it in the plan/execute path.** In `_build_sync_plan`'s Pass-1/Pass-2
    (`variant_master_sm_id`), thread the attach target through so that for an attach group:
    every member resolves as a Create with `parentId = existing_fdb_parent_id` (skip the
    master-promote pass for that group). For a create-new group, behavior is unchanged.
    Update `_compute_variant_groups` so Preview counts attach groups as variant groups too
    (Preview must stop reporting **Variant groups: 0** for Brown/Beige).
14. Frontend `StepVariances.tsx`: render the per-group attach-vs-create choice, send
    `existing_fdb_parent_id` in the `postWizardSmVariants` payload. Update
    `frontend/src/api/types.ts` + `client.ts` for all new/changed fields
    (`suggest_exclude`, `existing_fdb_parent`, `existing_fdb_parent_id`, the empty-spool
    config endpoint).

### Verify

15. `cd backend && ruff check . && pytest`. Add/adjust tests for: the new cluster key
    (Brown+Beige cluster into one group), `suggest_exclude` flagging on a conflicting member,
    the empty-spool toggle excluding empty spool creation while keeping the filament, and an
    attach decision producing variants with `parentId = existing` and **no** new parent /
    no master-promote. Frontend: `cd frontend && npm test` and `npx tsc --noEmit`.
16. If practical, drive the live flow (the `verify` skill / running app) with the
    Brown+Beige case and confirm Preview shows a variant group (not 0) and the empty-spool
    toggle changes the counts.

## Conventions to honor

- Match existing code style; reuse helpers (`_included_sm_ids` pattern, `get/set_config_value`,
  `normalize_vendor`/`normalize_name`, `sm_prop_conflicts`). Keep "clusters/flags are hints;
  the GUI decision is authoritative" and "conflicts are surfaced, never auto-resolved."
- **Never** modify or delete an existing FDB parent or any upstream record — attach only sets
  `parentId` on newly-created variants.
- Pydantic v2 models; new fields get defaults so the contract stays backward compatible.
- Doc updates ship in the **same commit** as the code. Commit on `dev`, Conventional-Commits
  (`feat:` for this), no `Co-authored-by:`. Never `--no-verify`. Never push to `main`.

## When done

1. Update this file's frontmatter: `status`, `completed` (date), `result` (one line).
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/` (failure).
3. In `docs/decisions.md`, add a dated entry recording the locked D1–D4 model (cluster key
   change, suggest-exclude, empty-spool toggle + default `false`, the `existing_fdb_parent_id`
   attach contract) and the Q1 simplification (no line-token parsing). Then either delete
   `docs/wizard-redesign.md` or mark it **implemented → see decisions.md** at the top.
4. Propose ONE commit covering the modified files (incl. the prompt move and doc updates).
   Present the file list + a one-line `feat:` message; ask `commit these as "<message>"?
   (y/n)`. On `y`, stage those specific paths and commit on `dev`. Never `git add -A`.
   Never push.
</content>
