---
name: 2026-06-11-filament-level-counts-dashboard-execute
status: completed
created: 2026-06-11
model: sonnet
completed: 2026-06-11
result: >
  Dashboard now shows Spools (existing 4-card grid, now labelled) + Filaments
  (in_sync / pending / conflict / total) sections. filament_counts computed in
  api/sync.py from FilamentMapping rows, excluding synthetic NULL-sm-id masters.
  WizardExecuteResponse gained 8 per-type breakdown fields (created_filaments /
  created_spools / etc.); Step6Execute.tsx shows "Nf / Ns" under each non-zero card.
  8 backend tests, 7 new frontend tests (Dashboard.test.tsx + 3 Step6Execute tests).
  Docs updated: decisions.md + wizard.md. 718 backend tests pass, ruff clean, tsc
  clean, 53 frontend tests pass.
---

# Task: Surface filament-level sync state — dashboard counts + execute filaments-vs-spools breakdown

## Why

The bridge is spool-centric. A filament with no (or only archived) spools, or a
variant/container filament, can be created in FDB and yet appear NOWHERE in the bridge UI
counts, because everything user-facing is keyed on spools. The user wants filament-level
visibility:

1. **Dashboard** — show how many *filaments* are in sync (in_sync / pending / conflict /
   total), alongside the existing *spool* counts.
2. **Wizard execute-complete summary** — break out *filaments created vs spools created*
   (and updated/skipped/failed) instead of one flat "Created N".

> Sequencing: run this AFTER `2026-06-11-import-archived-empty-spools` has landed (it edits
> overlapping files: wizard execute, schemas/api.py, build_mapping_rows). Do the working-tree
> check and rebase your understanding on the post-fix code.

## Grounding (verified line refs)

- **Dashboard counts** — `backend/app/api/sync.py:114-147` builds
  `counts = {in_sync, pending, conflict, unlinked, total}` from `build_mapping_rows`
  (`api/mappings.py`), which iterates **`SpoolMapping` only**. There is no filament-level
  count anywhere. `SyncStatusResponse.counts` is `dict[str,int]` (schemas/api.py:90-98).
- **Execute counts** — `WizardExecuteResponse` (schemas/api.py:553-559) is flat
  created/updated/skipped/failed. But `WizardExecuteRecord` (schemas/api.py:537) carries a
  `type` field ("filament" | "spool"), and the response returns the record list — so the
  per-type breakdown is derivable without re-counting server-side (though an explicit
  server-side breakdown is cleaner; your call).
- **Frontend** — dashboard: `frontend/src/pages/Dashboard.tsx`; execute summary:
  `frontend/src/pages/Wizard/Step6Execute.tsx` (+ test `Step6Execute.test.tsx`).
- **Models** — `FilamentMapping`, `SpoolMapping` in `backend/app/models/mapping.py`.
  Conflicts in `models/conflict.py`. Filament snapshots are stored (source-keyed,
  entity_type='filament') but hold only an `_mp_*` comparison projection — no display fields.

## What to do

### A. Filament-level dashboard counts
1. Add a filament-level status computation. Definition of a filament's status (keep it
   simple and consistent with the spool model):
   - **conflict** — an open conflict references this filament (or any of its spools).
   - **pending** — the FilamentMapping exists but one/both filament-side snapshots are
     missing (not yet baselined).
   - **in_sync** — both filament snapshots present and the mapping is linked.
   Exclude FilamentMappings with NULL `spoolman_filament_id` (synthetic FDB-only "(Master)"
   container parents) from the counts — they are not real cross-system pairs.
2. Return these as a separate map on the dashboard payload, e.g.
   `filament_counts: {in_sync, pending, conflict, total}`, alongside the existing spool
   `counts`. Extend `SyncStatusResponse` (don't break the existing `counts` shape — the
   frontend and tests depend on it).
3. `Dashboard.tsx` — render a Filaments summary (in sync / pending / conflict / total) next
   to the existing Spools summary. Match existing card/StatusBadge styling. Label the
   existing block clearly as "Spools" so the two are unambiguous.

### B. Execute filaments-vs-spools breakdown
4. In the execute-complete summary, show per-type counts. Preferred: add explicit fields to
   `WizardExecuteResponse` (e.g. `created_filaments`, `created_spools`, and the same for
   updated/skipped/failed) computed from the records in `_execute_*`; OR derive in
   `Step6Execute.tsx` by grouping the returned records by `type` + `action`. Pick one and be
   consistent. The four top-line cards (Created/Updated/Skipped/Failed) should each show or
   expand to "X filaments, Y spools".
5. Keep the existing flat totals too (don't remove Created/Updated/Skipped/Failed) — just add
   the filament/spool split.

### C. Tests
6. Backend: dashboard status returns correct `filament_counts` for a fixture with a mix of
   linked filaments (some with spools, some spool-less, one synthetic master excluded, one
   with an open conflict). Execute response (or its records) yields the right per-type split.
7. Frontend: `Dashboard.tsx` renders both summaries; `Step6Execute.tsx` shows the
   filament/spool breakdown. Update `Step6Execute.test.tsx`.

## Conventions to honor

- Don't break the existing `counts` dict shape or its consumers.
- Exclude synthetic NULL-`spoolman_filament_id` masters from user-facing filament counts.
- Update `docs/` where the dashboard/wizard behavior is described (e.g. `docs/wizard.md`,
  and any dashboard/FR-15 doc), same commit as code.
- REQUIRED before proposing the commit: `cd backend && pytest` + `ruff check`;
  `cd frontend && npx tsc --noEmit` + `npm test`. (Note the pre-existing `itsdangerous`
  import failures in this sandbox are unrelated — ignore them; ensure no NEW failures.)
- Conventional-commits `feat:` (new user-facing visibility). No `Co-authored-by:`. Branch
  `dev`, never `main`, never push.

## When done

1. Update frontmatter (`status`, `completed`, `result`).
2. `git mv` to `prompts/done/`.
3. Log any non-obvious decision in `docs/decisions.md`.
4. Propose ONE commit (specific paths, never `git add -A`); present file list + a one-line
   message and STOP for the user to run the commit. Never push.
