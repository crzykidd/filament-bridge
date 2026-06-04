---
name: 2026-06-01-wizard-variances-merge
status: pending          # pending | completed | failed
created: 2026-06-01
model: sonnet            # opus = research/planning, sonnet = coding
completed:               # filled when the work is done
result:                  # one-line summary of the outcome
---

# Task: Wizard — filter downstream steps to chosen items + merge Weights & Variants into one "Variances" step

Two coupled problems in the initial-sync wizard (spoolman direction is primary):

1. **Downstream steps ignore the Matches decisions.** After the user picks a subset to sync on the
   Matches step, the Weights and Variants steps re-fetch and show the **entire** library — so the
   user is forced to deal with items they chose to skip, and can't continue with just their
   filtered selection.
2. **Weights and Variants are really one decision.** The Variants step warns that grouped filaments
   have *different* empty-reel (tare) weights — but Filament DB stores tare as a single
   filament-level value, so only one weight can survive per filament/variant group. Resolving tare
   and choosing variant groupings belong on the same screen.

This prompt does both as **one large, self-contained change** suitable for autonomous execution.

## Before you start

- Read `CLAUDE.md` (esp. weight model translation, the `spoolWeight`/tare-is-filament-level gotcha,
  variant model, "what NOT to do") and `docs/prd.md` FR-5 (weights) + FR-6 (variants). Read
  `docs/decisions.md` — esp. the 2026-05-31 "SM-keyed master-promote" and "Match-review redesign"
  entries (this builds directly on both).
- **This is a multi-file refactor — read every file you'll touch before editing:**
  - Backend `backend/app/api/wizard.py`:
    - `wizard_matches` GET (L215-262 area) persists nothing new; decisions live in
      `wizard_match_decisions` (SM-keyed: `{spoolman_filament_id, action: link|create|skip,
      filamentdb_id}`), written by `wizard_save_matches` (L197-201).
    - `wizard_weights` GET (**L215**) — loops over **all** non-archived spools; **no** decision
      filter. Builds `WeightPreviewRow` per spool. This is bug #1 for weights.
    - `wizard_variants` GET (**L277**) — spoolman branch clusters **all** SM filaments
      (`sm_variant_cluster_key`), suggests a master (most spools, then shortest name), computes
      `sm_prop_conflicts` per member; **no** decision filter. Bug #1 for variants.
    - `wizard_save_sm_variants` POST (**L345**) → persists `wizard_sm_variant_decisions`
      (`SMVariantDecision{master_spoolman_filament_id, variant_spoolman_filament_ids[]}`); already
      rejects a group whose master was `skip`-ed.
    - `_execute_spoolman_to_fdb` (3-pass executor) consumes `wizard_match_decisions` +
      `wizard_sm_variant_decisions`; tare overrides arrive in the execute request body
      (`WizardTareOverride`).
    - Helpers: `_sm_ref` (L89), weight conversion `spoolman_to_fdb_gross`.
  - Backend `backend/app/core/matcher.py`: `sm_variant_cluster_key`, `sm_prop_conflicts`,
    `strip_color_and_words`.
  - Backend `backend/app/schemas/api.py`: `FilamentRef` (L203, now has `material`),
    `WeightPreviewRow` (L248), `WizardWeightsResponse`, `SMVariantGroupRow`/`SMVariantMemberRow`/
    `SMVariantDecision`/`VariantPropConflict`/`WizardVariantsResponse`, `WizardTareOverride`.
  - Frontend `frontend/src/pages/Wizard/`: `index.tsx` (STEPS array + routes + `WizardCtx` +
    `tareOverrides`/`setTareOverrides`), `Step3Matches.tsx`, `Step4Weights.tsx`,
    `Step5Variants.tsx` (the `SMVariants` + `FDBVariants` split), `Step6Execute.tsx`,
    `StepNPreview.tsx`.
  - Frontend `frontend/src/api/{client,types}.ts`, `frontend/src/components/DeepLinks.tsx`.

- **Confirmed design decisions (do not re-litigate):**
  1. **Filter everything downstream to the "chosen to sync" set.** An SM filament is *included*
     iff its `wizard_match_decisions` action is `link` or `create`. `skip` and *no decision* are
     excluded. Weights, Variants, the new merged step, preview, and execute all operate on this set
     only.
  2. **Merge Weights + Variants into one step called "Variances".** New wizard order:
     Connectivity → Direction → Matches → **Variances** → Preview → Execute (6 steps). Delete the
     two separate steps.
  3. **Tare: the master's weight wins, with a visible warning.** Because FDB stores one
     filament-level `spoolWeight`, every filament in a variant group lands with **one** tare = the
     **master's** (user-editable). Show a clear per-group warning, e.g. *"All variants in this group
     will use the master's empty-reel (tare) weight: N g."* Standalone (ungrouped) filaments each get
     their own editable tare. Tare is **per filament/group, not per spool** (correct FDB model) —
     this replaces the old per-spool override input.
  4. **Variant group membership is editable.** Beyond un-checking auto-clustered members (→ flat),
     the user can **add** any other included SM filament to a group and **remove** one (→ standalone).
     Clusters from the GET are *hints only*; the saved `SMVariantDecision[]` is authoritative.
     Terminology note: variant grouping is **filament-level** (each SM filament = one color variant).
     The user said "spool"; treat it as "add/remove a filament (variant) to/from the group."
  5. **Conflicts recompute live.** When the master or membership changes, the conflict flags
     (material/density/spool_weight/temps via `sm_prop_conflicts`) must update. Return the comparable
     props per member so the client recomputes, or re-derive on save — don't show stale conflicts.

## Working tree check

Before any edits, run `git status --porcelain` and cross-reference the files this plan modifies
(`backend/app/api/wizard.py`, `backend/app/schemas/api.py`, `backend/tests/test_api.py`,
`frontend/src/pages/Wizard/index.tsx`, `frontend/src/pages/Wizard/Step3Matches.tsx`, the new
`StepVariances.tsx`, removed `Step4Weights.tsx`/`Step5Variants.tsx`,
`frontend/src/api/{client,types}.ts`, `docs/decisions.md`). If any have uncommitted changes, list
them and ask before touching. Surface unrelated dirty files once as awareness; don't block. This
prompt file is exempt.

## What to do

### Backend

1. **Shared "included SM filament ids" helper.** Add a pure helper (in `wizard.py` or `matcher.py`)
   that reads `wizard_match_decisions` and returns the set of SM filament ids with action in
   `{link, create}`. Reuse it everywhere below so the filter is defined once.

2. **Filter `wizard_weights`** (spoolman branch): only emit `WeightPreviewRow`s for spools whose
   `s.filament.id` is in the included set. Leave the filamentdb branch functional (filter to linked
   + to-create FDB filaments if cheap; otherwise leave as-is and note it). Don't break the existing
   response shape — the merged step still needs weight data.

3. **Filter `wizard_variants`** (spoolman branch): cluster only included SM filaments. Keep the
   master heuristic + `sm_prop_conflicts`.

4. **New combined endpoint `GET /wizard/variances`** (spoolman direction) returning, for the included
   set, everything the merged page needs in one call:
   - The suggested variant groups (master + members + per-member conflicts) — reuse the
     `wizard_variants` clustering.
   - The pool of included filaments **not** in any cluster (so the UI can offer them as "add to
     group" candidates and render standalone tare rows).
   - Per filament: comparable props for live conflict recompute (material/density/spool_weight/
     nozzle/bed), its spool ids, and a resolved current tare + `tare_source` (reuse the
     `spoolman_to_fdb_gross`/`spool_weight` logic from `wizard_weights`).
   Add the response/request schemas to `backend/app/schemas/api.py` (e.g. `VariancesResponse`,
   reusing `FilamentRef`/`VariantPropConflict`). Keep `GET /wizard/variants` + `GET /wizard/weights`
   if other code/tests need them, or remove and update callers — your call, but keep tests green.

5. **Persistence:** keep `POST /wizard/variants/sm` (`wizard_sm_variant_decisions`). Decide tare
   persistence: tare overrides currently ride in the **execute request body** as
   `WizardTareOverride` (per spool). Preserve that contract — see frontend step 9 for how the merged
   step expands a per-group/per-filament tare to per-spool overrides. (If you prefer to persist tare
   like the other decisions, add a `POST /wizard/variances` and have execute read it — but then keep
   preview≡execute. Default: keep the request-body contract; less churn.)

6. **Preview & execute parity.** `wizard_preview` and `_execute_spoolman_to_fdb` must already see
   only included items (they read the same decision keys) — verify, and make the preview's
   `variant_plan` reflect membership edits + the master-tare rule. Execute is the source of truth;
   preview must match it.

### Frontend

7. **Stepper** (`index.tsx`): replace the `weights` + `variants` entries with one
   `{ path: 'variances', label: 'Variances' }`; update the `<Routes>` to render the new
   `StepVariances`. Keep `tareOverrides`/`setTareOverrides` on `WizardCtx` (the merged step sets
   them; `Step6Execute` still consumes them).

8. **New `StepVariances.tsx`** (spoolman direction) — replaces `Step4Weights` + the `SMVariants`
   half of `Step5Variants`:
   - Fetch `GET /wizard/variances`. Render each variant group: master radio, member rows with
     include checkbox (un-check → standalone), an **"+ add member"** control (search/select among
     included filaments not already grouped) and **remove** per member. Per group show the
     **master-tare warning** and **one editable tare input** (the master's). Recompute and show
     conflicts live as master/membership change.
   - Render standalone (ungrouped) included filaments with their own editable tare.
   - Save: build `SMVariantDecision[]` from current groupings → `POST /wizard/variants/sm`; build
     the per-spool `WizardTareOverride[]` (step 9) → `setTareOverrides(...)`; then `next()`.
   - Keep `DeepLinks` on every filament row. Preserve the "no groups → standalone tares only" and
     empty states.
9. **Tare expansion:** the user edits one tare per group (master) / per standalone filament, but the
   execute contract is per-spool. On save, expand: every spool of every filament in a group gets the
   group's master tare; every spool of a standalone filament gets that filament's tare. Emit those as
   `WizardTareOverride[]` (`spoolman_spool_id` + `tare`). This keeps `Step6Execute` unchanged.
10. **FDB direction:** the merged step must not regress the `filamentdb` import direction. Simplest:
    keep the existing `FDBVariants` grouping UI + a weight review section together on the Variances
    step for that direction (move the code over). Spoolman is the rich-UX focus; FDB just stays
    functional.
11. **Types/client** (`frontend/src/api/{types,client}.ts`): mirror the new `VariancesResponse`; add
    `getWizardVariances`. Remove now-dead `getWizardWeights`/`getWizardVariants` calls only if you
    removed the endpoints.
12. **Matched-rows display fix (small, include it):** on `Step3Matches`, the user reports the Matched
    group "shows without dedicated rows." Check the group's default-collapsed state / matched-group
    rendering and make matched members render as proper rows like the others.

### Tests (`backend/tests/test_api.py`)

13. Cover:
    - **Filtering:** `wizard_weights` / `wizard_variants` / `wizard_variances` only include
      `link|create` SM filaments; `skip` and undecided are excluded.
    - **Variances endpoint:** groups + ungrouped pool + per-filament props/spools/tare returned;
      conflicts present for clustered members.
    - **Membership edits → persistence:** a saved `SMVariantDecision` with an *added* (non-clustered)
      member and with a *removed* member round-trips to `wizard_sm_variant_decisions`; a group reduced
      to master-only dissolves to flat.
    - **Tare/master rule end-to-end (executor):** a 3-filament group seeds FDB with the **master's**
      tare applied to all members' spools; `WizardTareOverride` expansion covers every spool.
    - Preview≡execute for the merged flow; per-record isolation + idempotency preserved.
    Frontend tests are light in this repo — add one only if a harness exists; otherwise rely on
    `tsc` + manual.

## Conventions to honor

- Match surrounding style; keep planner/helpers pure; per-record isolation + idempotency (NFR-4) are
  hard requirements. Never delete upstream records. Conflicts are flagged, never auto-resolved.
- Doc updates ship in the **same commit** as the code. Commit on `dev`, Conventional-Commits
  (`feat:`), no `Co-authored-by:`. Never `--no-verify`. Never push.
- Before proposing the commit: `cd backend && pytest` and `cd frontend && npx tsc --noEmit` must pass.

## When done

1. Update this file's frontmatter: `status`, `completed` (date), `result` (one line).
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/` (failure).
3. Record in `docs/decisions.md`: downstream-filter-by-match-decisions rule; Weights+Variants merged
   into the "Variances" step; master-tare-wins (one filament-level tare per group) + warning;
   editable variant membership (clusters are hints, saved decisions authoritative); tare expansion to
   per-spool overrides to preserve the execute contract.
4. Propose ONE commit covering the modified files (incl. the prompt move). Present the file list +
   a one-line `feat:` message; ask `commit these as "<message>"? (y/n)`. On `y`, stage those
   specific paths and commit on `dev`. Never `git add -A`. Never push.
</content>
