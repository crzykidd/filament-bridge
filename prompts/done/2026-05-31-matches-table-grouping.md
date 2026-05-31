---
name: 2026-05-31-matches-table-grouping
status: completed
created: 2026-05-31
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-05-31
result: Rebuilt Step3Matches into four grouped/sortable tables with tri-state checkboxes, Rescan, and saved-decision rehydration; added material to FilamentRef; 197 backend tests pass, tsc clean
---

# Task: Wizard match review — groupable/sortable tables, bulk-select, and rescan-keeping-choices

The match-review step (`Step3Matches`) is a flat wall of rows that's hard to weed through with
a large library. Turn each of the four status sections into a proper **table** you can subgroup
(by Material or Brand), sort, and bulk-select — with checkboxes at the row, subgroup, and table
level. Add a **Rescan** button that re-pulls both upstreams while keeping the user's in-progress
choices, and make those choices survive leaving and returning to the step.

**Location grouping is explicitly OUT of scope** (location lives on spools, not filaments — a
separate concern). A companion prompt `2026-05-31-spool-location-sm-to-fdb.md` handles syncing
spool location SM→FDB.

## Before you start

- Read `CLAUDE.md` ("what NOT to do", deep-links requirement) and the FR-3/FR-4 match-review
  sections of `docs/prd.md`. Read `docs/decisions.md` (matcher → decisions mapping).
- Read the code you will change:
  - Frontend: `frontend/src/pages/Wizard/Step3Matches.tsx` (the whole file — it's the page),
    `frontend/src/pages/Wizard/index.tsx` (stepper/`WizardCtx`), `frontend/src/api/types.ts`
    (`FilamentRef`, `MatchDecision`, `WizardMatchesResponse`, `MatchPairRow`, `AmbiguousRow`),
    `frontend/src/api/client.ts` (`getWizardMatches`, `postWizardMatches`),
    `frontend/src/api/hooks.ts` (`useApi` — check whether it exposes a refetch; you'll need one
    for Rescan), `frontend/src/components/DeepLinks.tsx`.
  - Backend: `backend/app/api/wizard.py` (`_sm_ref` L89, `_fdb_ref` L98, `wizard_matches` GET
    L167, `wizard_save_matches` POST L199 → persists `wizard_match_decisions`),
    `backend/app/schemas/api.py` (`FilamentRef` L203, `MatchPairRow` L213, `AmbiguousRow` L222,
    `WizardMatchesResponse` L227, `MatchDecision` L234).
  - Source field names you need: SM material = `SpoolmanFilament.material`
    (`backend/app/schemas/spoolman.py:47`); FDB material = `FDBFilament.type`
    (`backend/app/schemas/filamentdb.py:105`). FilamentRef does **not** carry material today.

- **Confirmed design decisions** (do not re-litigate):
  1. **Status is the top-level grouping → keep the four separate tables** (Matched, Ambiguous,
     Unmatched-in-Spoolman, Unmatched-in-Filament-DB). Match status decides what action is even
     possible, so it stays the outer split. Subgrouping (Material/Brand) happens *inside* each
     table.
  2. **Subgroup dimensions this prompt: Material and Brand (vendor) only.** A single per-table
     (or shared) control picks the active subgroup dimension; rows cluster under collapsible
     subgroup headers. Sorting is available on the visible columns.
  3. **Checkboxes replace the per-row action buttons** for the binary include/exclude decision:
     - Matched table: checked = `link` (to its matched FDB filament), unchecked = `skip`.
     - Unmatched-in-Spoolman table: checked = `create`, unchecked = `skip`.
     - **Ambiguous table keeps an explicit candidate picker** — a checkbox alone can't say *which*
       FDB filament. A row counts as included only once a candidate is chosen (`link` + that
       `filamentdb_id`); its checkbox toggles between that chosen link and `skip`.
     - Unmatched-in-Filament-DB table is **informational** (nothing to decide in the SM→FDB flow):
       it's still groupable/sortable for scanning, but has **no checkboxes**.
     - Subgroup-header checkbox: tri-state (checked / unchecked / indeterminate) — toggles every
       row in that subgroup to its "included" action / to `skip`. Table-level checkbox does the
       same for the whole table.
  4. **Default actions are unchanged from today:** matched rows default to `link`, unmatched-SM
     rows default to `create`. A row with no explicit decision uses its default.
  5. **Rescan keeps choices.** The Rescan button re-fetches `GET /wizard/matches` and re-applies
     existing decisions, keyed by `spoolman_filament_id` (decisions are SM-keyed; FDB-side link
     targets are keyed by `filamentdb_id` and stay valid). Drop decisions whose SM filament no
     longer appears after the rescan. Do **not** wipe the user's choices on rescan.
  6. **Choices survive leaving the step.** Persisted `wizard_match_decisions` are returned by the
     matches GET and used to hydrate the table on load (and after rescan).

## Working tree check

Before any edits, run `git status --porcelain` and cross-reference the files this plan modifies
(`frontend/src/pages/Wizard/Step3Matches.tsx`, `frontend/src/api/{types,client,hooks}.ts`,
`backend/app/api/wizard.py`, `backend/app/schemas/api.py`, `backend/tests/test_api.py`,
`docs/decisions.md`). If any have uncommitted changes, list them and ask before touching.
Surface unrelated dirty files once as awareness; don't block. This prompt file is exempt.

## What to do

### Backend

1. **Surface material on the ref** (`backend/app/schemas/api.py`): add `material: str | None = None`
   to `FilamentRef`. In `backend/app/api/wizard.py`, set it in `_sm_ref` (`material=sm.material`)
   and `_fdb_ref` (`material=fdb.type`).

2. **Return saved decisions for rehydration** (`backend/app/schemas/api.py` +
   `backend/app/api/wizard.py`): add `saved_decisions: list[MatchDecision] = Field(default_factory=list)`
   to `WizardMatchesResponse`. Give `wizard_matches` a `db: Session = Depends(get_db)` dependency,
   read `wizard_match_decisions` from config (`get_config_value(db, "wizard_match_decisions", [])`),
   validate into `MatchDecision`, and include them in the response. Persistence on save is
   unchanged (`wizard_save_matches` already writes the key).

### Frontend

3. **Mirror types** (`frontend/src/api/types.ts`): add `material?: string | null` to `FilamentRef`;
   add `saved_decisions: MatchDecision[]` to `WizardMatchesResponse`.

4. **Refetch support** (`frontend/src/api/hooks.ts`): ensure `useApi` exposes a `refetch()` (add it
   if missing) so Rescan can re-run `getWizardMatches` without a full remount. Keep the existing
   call sites working.

5. **Rebuild `Step3Matches.tsx`** as four grouped/sortable tables:
   - Hydrate `decisions` state from `data.saved_decisions` on load (and merge, not clobber, after a
     rescan — re-key by `spoolman_filament_id`, prune SM ids that vanished).
   - Per table: a subgroup selector (Material | Brand) and column sorting; collapsible subgroup
     headers showing counts.
   - Checkboxes per the semantics in decision #3 (row / subgroup-header tri-state / table-level).
     Keep `DeepLinks` on every row. Keep the Ambiguous candidate picker; keep the per-row
     confidence + `vendor_dedup_hint` display on Matched.
   - A **Rescan** button (near Back/Save) → `refetch()`; show a spinner; preserve choices.
   - `handleSave` still builds the reconciled `MatchDecision[]` and POSTs via `postWizardMatches`,
     then `next()`. Preserve the current reconciliation (matched default `link`, unmatched-SM
     pushed only when decided, ambiguous pushed only when decided).

### Tests (`backend/tests/test_api.py`)

6. Cover: `_sm_ref`/`_fdb_ref` now populate `material` (SM `material`, FDB `type`); `GET
   /wizard/matches` echoes persisted `wizard_match_decisions` as `saved_decisions` (and returns
   `[]` when none saved); existing match-review tests still pass. Frontend tests are light in this
   repo — add one only if there's an existing harness to extend; otherwise rely on `tsc` + manual.

## Conventions to honor

- Match surrounding style. Keep the deep-links on every record (CLAUDE.md). Never auto-resolve —
  the user's checkbox/picker is the decision. Don't change the matcher itself.
- Doc updates ship in the **same commit** as the code. Commit on `dev`, Conventional-Commits
  (`feat:`), no `Co-authored-by:`. Never `--no-verify`. Never push.
- Run `cd backend && pytest` and `cd frontend && npx tsc --noEmit` before proposing the commit.

## When done

1. Update this file's frontmatter: `status`, `completed` (date), `result` (one line).
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/` (failure).
3. Record in `docs/decisions.md`: status-as-top-group (four tables) + Material/Brand subgrouping,
   checkbox→action mapping, rescan-keeps-choices via SM-id re-keying, and decision-rehydration via
   `saved_decisions` on the matches GET.
4. Propose ONE commit covering the modified files (incl. the prompt move). Present the file list +
   a one-line `feat:` message; ask `commit these as "<message>"? (y/n)`. On `y`, stage those
   specific paths and commit on `dev`. Never `git add -A`. Never push.
</content>
</invoke>
