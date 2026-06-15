---
name: 2026-06-14-wizard-preview-container-collision-unselected
status: completed
created: 2026-06-14
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-14
result: Fixed _preview_container_names guard in wizard_preview to only include action=="create" items; added 2 regression tests in test_name_collision.py
---

# Task: Wizard preview — don't flag container name collisions for UNSELECTED (already-linked) clusters

## Bug

In the Bulk Import Wizard, selecting a single new filament to import (e.g. "PETG Chalky
Blue") and going to Preview shows **container name collisions** for clusters the user did
NOT select — specifically clusters that already exist / are already linked in Filament DB
(e.g. "Hatchbox PLA (Master)", "ELEGOO PLA (Master)"). The "Planned writes" list is
correct (only the 2 writes for the selected filament); only the "Name collisions" section
is wrong.

## Root cause (already diagnosed — verify, then fix)

`backend/app/api/wizard.py` → `wizard_preview` builds `_preview_container_names` by
iterating `plan.filament_items` filtered ONLY by `item.resolved` (around lines 2387-2389):

```python
for item in plan.filament_items:
    if not item.resolved:
        continue
    ...
```

But the planner (`backend/app/core/planner.py:338-340`) marks **already-linked** filaments
(those with an existing FilamentMapping) as `action="skip", resolved=True,
detail="already linked"`. So `item.resolved` is True for already-linked clusters, and their
container display names get computed → `_compute_name_collisions` then reports them as
`vs_existing` container collisions even though they are NOT part of the user's selection
and are NOT being created.

For contrast, the *plan-item* (non-container) collision path in `_compute_name_collisions`
(`wizard.py` ~line 2005) already correctly filters `item.action == "create"`. The container
path should be consistent: only filaments actually being **created** should contribute a
proposed container name.

## Before you start

- Read `backend/app/api/wizard.py:2380-2400` (the `_preview_container_names` build) and
  `_compute_name_collisions` (~1987-2068).
- Read `backend/app/core/planner.py:292-400` to confirm the `_FilamentPlanItem` action /
  resolved semantics: `create` → resolved=True; `link` → resolved=True; already-linked
  existing mapping → `action="skip", resolved=True`; no decision / user-skipped →
  `action="skip", resolved=False`.
- Confirm the diagnosis yourself before editing.

## Working tree check

`git status --porcelain` first. Tree clean except unrelated dotfiles. If a file this plan
touches is dirty, list it and ask. This prompt file is exempt.

## What to do

1. In `wizard_preview` (`backend/app/api/wizard.py`), change the `_preview_container_names`
   build loop so it only includes filaments that are actually being created — i.e. replace
   the `if not item.resolved: continue` guard with `if item.action != "create" or item.error: continue`.
   (Generic-container masters are only synthesized for created filaments; already-linked /
   skipped clusters must not contribute a container name and therefore must not produce a
   container collision.)
2. Do NOT change `_compute_name_collisions` itself, the execute path, or the planner — the
   execute path already writes only the selected records (the "Planned writes" total is
   correct). This is a preview-display fix scoped to how `_preview_container_names` is built.
3. Sanity-check there is no other place in `wizard_preview` that derives container/collision
   data from `item.resolved` where it should be `item.action == "create"`.

## Tests

4. Add a regression test (prefer `backend/tests/test_name_collision.py`; use
   `backend/tests/test_variant_parent_mode.py` patterns if you need generic_container mode
   fixtures). Scenario:
   - variant_parent_mode = `generic_container`.
   - One cluster already exists in FDB AND has an existing FilamentMapping (so the planner
     returns it as `action="skip", resolved=True, detail="already linked"`), with a
     container name that WOULD collide with an existing FDB filament.
   - The user selects (match decision `create`) a DIFFERENT, new filament in a different
     cluster.
   - Assert the preview's `name_collisions` does NOT include a container collision for the
     already-linked cluster (and, ideally, that a created cluster whose container genuinely
     collides still IS reported — to prove the fix didn't over-filter).
   - If a full `/wizard/preview` API test is heavier than warranted, a focused test that
     drives `wizard_preview` (or the `_preview_container_names` construction) directly is
     acceptable — match the style already used in test_name_collision.py.
5. Keep all existing wizard/preview/collision tests green.

## Conventions to honor

- Surgical, preview-only change. No upstream writes.
- **Full backend suite via throwaway venv** (sandbox skips `itsdangerous` tests otherwise):
  `python3 -m venv $TMPDIR/v && $TMPDIR/v/bin/pip install -q -r backend/requirements.txt &&
  cd backend && $TMPDIR/v/bin/pytest`. Confirm `test_name_collision.py` (and
  `test_variant_parent_mode.py`) ran. Then `ruff check backend/`, and in `frontend/`
  `npx tsc --noEmit` + `npm test`. All green.

## When done

1. Update frontmatter (`status`, `completed` 2026-06-14, `result`).
2. `git mv` this file to `prompts/done/` (or `prompts/failed/`).
3. Record the fix in `docs/decisions.md` only if the wizard collision behavior is already
   documented there; otherwise no doc change needed.
4. Propose ONE `fix:`-prefixed commit (file list + one-liner; ask y/n). On `y`, stage those
   specific paths and commit on `dev` (never `main`, never `git add -A`, never push, no
   `Co-authored-by:`).
