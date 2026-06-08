---
name: 2026-06-08-bulk-import-wizard
status: done
created: 2026-06-08
model: sonnet
completed: 2026-06-07
result: |
  Renamed wizard to "Bulk Import Wizard" (nav + heading). Removed "Ongoing source of
  truth" section from Step2Direction + dropped *_source_of_truth + include_empty_spools
  fields from WizardDirectionRequest. Added global never_import_empties config
  (backend models/config.py, schemas/api.py, api/config.py; Settings toggle; wizard
  execute/preview/variances honor it). Preview labels empty_active by setting.
  702 backend tests pass; frontend tsc + build clean.
---

# Task: Rename to Bulk Import Wizard, drop the ongoing-SoT step, replace empty-spool checkbox with a setting

The "initial sync wizard" is runnable any time and is really a bulk import tool. Rename it,
remove the obsolete ongoing source-of-truth selection (that lives in Settings now), and replace
the misleading per-run "include empty spools" checkbox with a global "Never import empties"
setting (the wizard just shows/labels empties).

## 1. Rename → "Bulk Import Wizard"

- Update the nav/menu label and the wizard page headings/titles to "Bulk Import Wizard". Find
  the nav label (in `frontend/src/App.tsx` or a Layout/Nav component) and the wizard
  shell/step headings (`frontend/src/pages/Wizard/`). Route path may stay `/wizard`.
- Ensure it's clearly runnable any time (re-run friendly). If there's any "wizard already
  completed" hard block, soften it to an informational note — don't prevent re-running.

## 2. Remove the "Ongoing source of truth" selection

`frontend/src/pages/Wizard/Step2Direction.tsx`:
- Remove the "Ongoing source of truth" section (~lines 90-99) and the related state
  (`weightSot`/`matSot`/`newSpoolSot`) and the `*_source_of_truth` fields from the save payload
  (~lines 44-46). These are dead legacy keys set in Settings now.
- Keep the **"Initial import direction"** selection. Update the step heading from
  "Sync direction & source of truth" to something like "Import direction".
- Update the backend wizard save endpoint (`backend/app/api/wizard.py`) to no longer require/
  store those `*_source_of_truth` fields (drop them from the request model if present; don't
  break the direction handling).

## 3. Replace the empty-spool checkbox with a global "Never import empties" setting

- **Backend config**: add `never_import_empties` (default `false`) — `models/config.py`,
  `schemas/api.py` `ConfigResponse`/`ConfigUpdateRequest`, `api/config.py`.
- **Wizard execute honors it** (`backend/app/api/wizard.py` import/seed path): when
  `never_import_empties` is true, SKIP empty/depleted spools (remaining net weight ≈ 0) when
  creating FDB spools — but still import the filament definition. Replace the old
  `include_empty_spools` per-run flag with this setting (remove the request field, or default
  it from the setting). Make the skip per-spool (a filament with one empty + one full imports
  only the full one when the setting is on).
- **Settings UI** (`frontend/src/pages/Settings.tsx`): add a **"Never import empties"** toggle
  (in the import/sync area) with a one-line description: "Empty/depleted spools are skipped on
  import; the filament definition is still imported."
- **Wizard Step2Direction**: REMOVE the "Include empty / depleted spools" checkbox.
- **Wizard preview** (`StepNPreview.tsx`): keep showing the empty-active count, but label it by
  the setting — "Empty/depleted spools (will be imported)" when the setting is off, or
  "Empty/depleted spools (skipped — 'Never import empties' is on)" when on. Pull the setting
  into the preview data (or fetch config) as needed.

## Verification

- `cd backend && pytest` — tests: config round-trips `never_import_empties`; the wizard import
  skips empty spools when the setting is on and imports them when off (one empty + one full →
  only full imported when on); the wizard save no longer needs `*_source_of_truth`.
- `cd frontend && npx tsc --noEmit && npm run build`.
- Reason through: menu reads "Bulk Import Wizard"; Step 2 shows only import direction; the
  empty-spool behavior is driven by the Settings toggle; preview labels reflect it.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md`: wizard renamed to Bulk Import Wizard (re-runnable); ongoing SoT removed
   from the wizard (Settings owns it); empty-spool import controlled by the global
   `never_import_empties` setting. Update CLAUDE.md/configuration.md env table if you env-back
   it (`NEVER_IMPORT_EMPTIES`).
3. Non-interactive subagent run: when pytest + build pass, stage ONLY the files this task
   touched (incl. prompt move + docs) and commit on `dev` with one `feat:` message. Never
   `git add -A`. Never push.
