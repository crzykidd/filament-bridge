---
name: 2026-05-31-sm-variant-grouping
status: completed        # pending | completed | failed
created: 2026-05-31
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-05-31    # filled when the work is done
result: SM-keyed variant grouping (cluster + master-promote + parentId-at-create + conflict flags); recovered from a crashed session, all 8 files implemented, 69 backend tests + tsc green
---

# Task: Spoolman→FDB variant grouping — build the parent/variant tree before the write

Let the user collapse a set of flat Spoolman filaments (e.g. "ELEGOO PLA Red",
"ELEGOO PLA Blue", …) into one Filament-DB parent + variants during the initial-sync
wizard, **before** the write. The grouping is smart-matched, then the user prunes
members and picks one member as the **master** (= the FDB parent). This is the
`import_direction="spoolman"` (primary) flow into a greenfield FDB.

## Before you start

- Read `CLAUDE.md` (variant model, weight translation, "what NOT to do") and
  `docs/prd.md` variant sections. Read `docs/decisions.md`.
- Read the current code paths you will change: `backend/app/api/wizard.py`
  (esp. `_execute_spoolman_to_fdb` ~L405, `wizard_variants` ~L259, `wizard_preview`
  ~L770, `_compute_variant_groups` ~L743, `_strip_color` ~L252), `backend/app/core/planner.py`
  (`_plan_spoolman_to_fdb` ~L96, `_FilamentPlanItem` ~L27, `_SyncPlan.variant_updates` L57/175),
  `backend/app/schemas/api.py` (`VariantDecision` L277), `backend/app/core/matcher.py`
  (`normalize_vendor`/`normalize_name`), `backend/app/services/filamentdb.py`
  (`create_filament` L145, `update_filament`), `frontend/src/pages/Wizard/Step5Variants.tsx`,
  `frontend/src/pages/Wizard/index.tsx`, `frontend/src/api/{client,types}.ts`.
- **Confirmed design decisions** (do not re-litigate):
  1. Master = parent. Each SM filament still maps 1:1 to an FDB filament; grouping only
     orders master-before-variants and stamps `parentId` on the non-masters. Master is a
     real filament with its own color + spools (NOT an abstract synthesized parent).
  2. Shared properties (material/density/spoolWeight/temps) must agree → **flag conflicts**
     in the preview; never auto-pick a value.
  3. New persistence key `wizard_sm_variant_decisions` (SM-keyed). Leave the FDB-keyed
     `wizard_variant_decisions` + `VariantDecision` + `_execute_fdb_to_spoolman` path
     untouched (used by the fdb→spoolman direction). The two coexist.
- **Why today is broken:** variant decisions are keyed on FDB ids that don't exist in a
  greenfield FDB; the executor's Phase B (`wizard.py:462-473`) only parents ids already in
  `fdb_by_id`, so freshly-created filaments never get `parentId`. The `/wizard/variants`
  GET clusters over FDB filaments (empty in this flow).
- **Smart-match caveat:** `_strip_color(name, color_hex)` strips a *hex code*, not the color
  *word* — so it under-clusters real names like "ELEGOO PLA Red". Cluster on
  `(normalize_vendor, normalize_name(material), base-name)` where base-name strips BOTH the
  hex and a small known color-word lexicon (red/blue/black/white/grey/gray/green/yellow/
  orange/purple/pink/silver/gold/transparent/natural/…). Treat clusters as **hints**; the GUI
  is authoritative (user adds/removes members + picks master).

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files this
plan modifies (`backend/app/api/wizard.py`, `backend/app/core/planner.py`,
`backend/app/schemas/api.py`, `backend/tests/test_api.py`,
`frontend/src/pages/Wizard/Step5Variants.tsx`, `frontend/src/api/{client,types}.ts`,
`docs/decisions.md`). If any have uncommitted changes, list them and ask before touching.
Surface unrelated dirty files once as awareness; don't block. This prompt file is exempt.

## What to do

### Backend

1. **Schemas** (`backend/app/schemas/api.py`) — add, keeping `VariantDecision` as-is:
   - `SMVariantDecision { master_spoolman_filament_id: int, variant_spoolman_filament_ids: list[int] }`
   - `SMVariantsRequest { groups: list[SMVariantDecision] }`
   - `VariantPropConflict { field: str, master_value: Any, member_value: Any }`
   - `SMVariantMemberRow { ref: FilamentRef, is_master: bool, conflicts: list[VariantPropConflict] }`
   - `SMVariantGroupRow { base_name: str, vendor: str|None, material: str|None,
     suggested_master: FilamentRef, members: list[SMVariantMemberRow] }`
   - Extend the variants GET response to carry `direction`, `sm_groups` (spoolman) and keep
     `fdb_groups` (legacy). Extend `WizardPreviewResponse` with
     `variant_plan: list[SMVariantGroupRow]`.

2. **Shared helpers** — factor a cluster-key helper (`vendor, material, color-word+hex-stripped
   base name`) and a pure `_sm_prop_conflicts(master, member) -> list[VariantPropConflict]`
   (compare material/density/spoolWeight/nozzle/bed). Reuse from endpoint + planner so they
   agree. Put pure helpers where they're testable (matcher.py or planner.py).

3. **Endpoint** (`backend/app/api/wizard.py`):
   - `GET /wizard/variants`: branch on `import_direction`. **spoolman** → fetch SM filaments
     (+ spools for the master heuristic), cluster (≥2 members), suggest master (most spools,
     tie-break shortest name), compute per-member conflicts → return `sm_groups`. **filamentdb**
     → keep current FDB clustering → `fdb_groups`.
   - Add `POST /wizard/variants/sm` (`wizard_save_sm_variants`) → persist `SMVariantDecision[]`
     to `wizard_sm_variant_decisions`. Validate: reject a group whose master has a `skip`
     match-decision. Leave the legacy `POST /wizard/variants` persisting to the old key.

4. **Planner** (`backend/app/core/planner.py`):
   - `_plan_spoolman_to_fdb`: replace `parent_of_fdb` param with `master_of_sm: dict[int,int]`
     (variant_sm_id → master_sm_id).
   - `_FilamentPlanItem`: add `variant_master_sm_id: int|None = None` and
     `prop_conflicts: list = dc_field(default_factory=list)`. Set on variant items.
   - Drop `variant_updates` usage here; echo `master_of_sm` on the plan. Keep purity.
   - Group with empty variant list after pruning → members are flat creates (no parent).

5. **Executor** (`_execute_spoolman_to_fdb`, `wizard.py:405`) — replace Phase B with two passes:
   - Pass 1 (masters + ungrouped, `variant_master_sm_id is None`): create/link as today;
     build `master_sm_id → fdb_id`; write FilamentMapping.
   - Pass 2 (variants): resolve `parent_fdb_id = master_map[variant_master_sm_id]`. On `create`
     inject `parentId` into the create payload; on `link` call
     `update_filament(fdb_id, {"parentId": parent_fdb_id})`. Set
     `FilamentMapping.filamentdb_parent_id`. Master missing/failed → emit `failed` for the
     variant (no orphan parentId).
   - Pass 3 (spools): unchanged; `parent_id` for the cross-ref extra now comes from the master
     map. Keep the `label` (= `filamentdb_spoolman_id_field`) key on spool creates (test
     depends on it).
   - Preserve per-record isolation + idempotency (re-setting an existing parentId is a no-op).

6. **Preview** (`wizard_preview`, `wizard.py:770`): for spoolman direction build `master_of_sm`
   from `wizard_sm_variant_decisions`, pass to the same planner (keeps preview≡execute), and
   populate `variant_plan` (tree + conflict flags). Make no writes.

### Frontend

7. `frontend/src/pages/Wizard/Step5Variants.tsx` — direction-aware:
   - **spoolman:** render each `SMVariantGroupRow`: per-member checkbox (exclude → flat) + a
     master radio; show conflicts as inline warnings. Save → build `SMVariantDecision[]` →
     `POST /wizard/variants/sm`. Group reduced to master-only dissolves to flat.
   - **filamentdb:** keep current behavior (reads `fdb_groups`).
   - Mirror new types in `frontend/src/api/types.ts`; add client calls in
     `frontend/src/api/client.ts`. Stepper routes in `index.tsx` unchanged.

### Tests (`backend/tests/test_api.py` + pure units)

8. Cover: `_sm_prop_conflicts` (agreement→empty, each differing field→one conflict, None
   handling); cluster helper (vendor+material+base-name, color-word strip, singletons excluded,
   master heuristic); planner with `master_of_sm` (variant items carry master id; master-skip
   flagged; dissolve→flat; conflicts populated); executor (greenfield 3-filament group → 1
   master create + 2 variant creates with `parentId` in payload + FilamentMapping
   `filamentdb_parent_id`; link-variant → `update_filament(parentId)`; master-skip → variant
   `failed`; idempotent re-run; spool extra `filamentdb_parent_id` = master id); preview
   (`variant_plan` tree + flags, no writes, preview≡execute); persistence (SM POST → new key,
   legacy POST → old key, coexist). Mirror existing `test_wizard_execute_*` /
   `test_preview_makes_no_writes` patterns.

## Conventions to honor

- Match surrounding style; keep planner + helpers pure (no I/O). Per-record isolation and
  idempotency are hard requirements (NFR-4). Never delete upstream records. Conflicts are
  flagged, never auto-resolved.
- Doc updates ship in the **same commit** as the code. Commit on `dev`, Conventional-Commits
  prefix (`feat:`), no `Co-authored-by:`. Never `--no-verify`. Never push.

## When done

1. Update this file's frontmatter: `status` (completed/failed), `completed` (date), `result`
   (one line).
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/` (failure).
3. Record decisions in `docs/decisions.md`: SM-keyed master-promote model, new
   `wizard_sm_variant_decisions` key, conflict-flag policy, and "un-group after a successful
   run is out of scope". Correct the existing Phase-B rationale that documents the FDB-keyed
   approach as intentional.
4. Propose ONE commit covering the modified files (including the prompt move). Present the
   file list + a one-line `feat:` message; ask `commit these as "<message>"? (y/n)`. On `y`,
   stage those specific paths and commit on `dev`. Never `git add -A`. Never push.
