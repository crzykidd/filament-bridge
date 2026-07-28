---
name: 2026-07-27-wizard-family-tare
status: completed
created: 2026-07-27
model: sonnet
completed: 2026-07-27
result: |
  One commit landed on dev (not pushed), SHA 8ef54b4:
  fix: wizard variances resolve tare from existing FDB master, not just
  Spoolman — Fixes #78

  Added shared helpers in core/matcher.py (build_fdb_parent_key_map,
  existing_fdb_parent_id_for_sm, build_family_tare_by_sm_id — the last calls
  masters_defaults.resolve_family_tare) and reused them at all three sites:
  wizard_variances preview (grouped + defensive ungrouped branch), the
  execute tare gate (_resolve_filament_tare gained an optional family_tare
  4th resolution step), and the planner (_plan_spoolman_to_fdb precomputes
  family_tare_by_sm_id once, used for both the new FDB filament's own
  spoolWeight and per-spool planned_gross). New tare_source value
  "filamentdb_master", added to the VariancesFilament Literal. Frontend
  (StepVariances.tsx) shows a "from the Filament DB master" badge on the
  group tare and standalone rows; pre-fill already worked via the existing
  tareBySMId init (keyed on m.tare, not tare_source).

  Tests: backend 1475 passed (2 new: a variances-preview test and an
  execute-gate test asserting no rejection + gross = net + family tare),
  ruff clean. Frontend 199 passed (1 new render test asserting no "required"
  badge + the source label + pre-filled input value), tsc clean.

  Design decisions logged in docs/decisions.md (2026-07-27 entry, index
  regenerated): build_family_tare_by_sm_id lives in matcher.py (not
  masters_defaults.py) since masters_defaults has zero app.* imports and
  matcher already sits between wizard.py/planner.py, so matcher ->
  masters_defaults is a safe one-way edge. Ungrouped-branch fallback is
  currently unreachable dead code (any FDB-parent match promotes a singleton
  into `groups`, never `ungrouped`) — kept anyway for symmetry per the
  handoff's explicit instruction and as a guard against future clustering
  changes.

  Nothing deferred; no blockers.
---

# Task: Wizard variances — resolve tare from the existing FDB master (issue #78)

The Bulk Import Wizard's Variances step still shows "required" for the empty-reel tare on a
variant group that attaches to an **existing Filament DB master** — even after #76 backfilled
that master's tare — because the wizard resolves tare from the **Spoolman side only**. Feed the
existing-FDB-parent tare into the wizard the same way #76 did for the Conflicts "Add" path.
GitHub issue: **#78** (read it — it has the full diagnosis and the exact line numbers).

## Before you start

Read:
- Issue #78 (`gh issue view 78`) — symptom, root cause, and the three fix sites.
- `backend/app/core/masters_defaults.py` — `resolve_family_tare(fdb_filaments, master_id)`
  (master's own `spoolWeight`, else mode of variant children). **Reuse it — do not reinvent.**
- `backend/app/api/wizard.py` — `wizard_variances` (GET `/wizard/variances`, ~line 690): the
  grouped-member tare at ~785 and the ungrouped tare at ~821 both call `_sm_filament_tare`
  (Spoolman-only); the group already carries `existing_fdb_parent` (~770/814). Also the
  execute **tare gate** at ~2800–2836 (`_resolve_filament_tare`).
- `backend/app/core/planner.py` — `_resolve_filament_tare` (~125) and where `planned_gross`
  is computed (~500–535).
- `CLAUDE.md` "Sync engine — hard invariants" — the **"never guess 200 g"** rule. This fix
  only ever falls back to a *known* family tare, never a default.

## Working tree check

Run `git status --porcelain`; confirm you're on `dev` and clean. If any file this plan
touches is already dirty, stop and report. This prompt file is exempt.

## What to do

The goal: when a new Spoolman color attaches to an existing FDB master (or its variant
family) that already has a tare, the wizard uses that tare — preview shows it, and execute
neither rejects nor writes a wrong gross. Three coordinated changes, all reusing
`resolve_family_tare`:

### 1 — Preview (`wizard_variances`)

For each grouped member (and the ungrouped branch), when `_sm_filament_tare(m)` returns
`None` (`tare_source == "needs_input"`) **and** the group has an `existing_fdb_parent`, fall
back to `resolve_family_tare(fdb_filaments, existing_fdb_parent.filamentdb_filament_id)`. When
that yields a value, set `tare` to it and `tare_source` to a new distinct value
`"filamentdb_master"`. Only apply the fallback to the group's members (ungrouped singletons
that matched an existing FDB line via `existing_fdb_parent` get it too — same rule). Leave the
Spoolman-sourced path (`"spoolman"`) untouched. Add `"filamentdb_master"` anywhere
`tare_source` is a typed/validated field.

### 2 — Execute tare gate + planner gross (server-side, authoritative)

Make the execute path resolve the same family tare so a group attaching to a master with a
known tare is **not** rejected by the gate and its FDB spool gross is computed with the real
tare — regardless of whether the frontend re-sent the pre-filled value as an override.

- In the SM-direction tare gate (`wizard.py` ~2800–2836): before appending an SM filament to
  `_missing_tare_names`, if `_resolve_filament_tare(...)` is `None`, resolve the SM filament's
  existing FDB parent (reuse the SAME clustering the preview uses — `fdb_parent_by_key` keyed
  by `(vendor_norm, material_norm, finish_norm)` — factor it into a small shared helper rather
  than duplicating) and, if that parent has a `resolve_family_tare`, treat the tare as known
  (don't gate).
- In `_plan_spoolman_to_fdb` (`planner.py`): when the per-spool Spoolman tare is `None`,
  fall back to the same existing-FDB-parent family tare for `planned_gross` (so the created
  FDB spool's `totalWeight = net + family_tare`). The planner already receives `fdb_filaments`.
  Thread the resolved parent-tare in cleanly (e.g. precompute `family_tare_by_sm_id` once and
  pass it, or resolve inside using a shared helper) — keep preview ≡ execute.

Preserve the invariant: never fall back to `DEFAULT_TARE_GRAMS`. A group whose master has no
tare anywhere still returns `None` → still gated → still requires input.

### 3 — Frontend

In the Variances UI (`frontend/src/pages/Wizard/…` — find the component rendering the
per-group "…use this empty-reel tare: N g" line and the per-member tare input), render the
`"filamentdb_master"` source with a short label so the user knows the value came from the
Filament DB master (e.g. "from the Filament DB master") — distinct from a Spoolman-sourced
value. Ensure a `filamentdb_master`-sourced tare pre-fills the group's tare field just like a
Spoolman-sourced one.

## Conventions to honor

- Branch `dev`. **Commit, do NOT push.** One commit (or two — backend, then frontend — your
  call; keep each green).
- Conventional-commit `fix:` prefix, no `Co-authored-by:` trailers. Docs with code.
- Add a `## [Unreleased]` `### Fixed` entry to `CHANGELOG.md` in the same commit, referencing
  #78. Commit body ends with `Fixes #78`.
- Tests before committing, all green:
  - `cd backend && .venv/bin/python -m pytest` + `.venv/bin/python -m ruff check backend/`
  - `cd frontend && npx vitest run` + `npx tsc --noEmit`
- Add backend tests: a variances-preview test asserting an existing-FDB-master group with a
  Spoolman-tareless member returns `tare` = the master's tare with `tare_source ==
  "filamentdb_master"`; and an execute-gate test asserting such a group is NOT rejected and
  the created FDB spool's gross uses the family tare. Add a frontend test for the label/pre-fill.

## When done

1. Update this file's frontmatter (`status`, `completed`, `result`); `git mv` it to
   `prompts/done/`.
2. Record any non-obvious decision (the shared clustering helper, the new `tare_source` value)
   in `docs/decisions.md` (dated `## ` entry) and regenerate the index with
   `scripts/gen-decisions-index.py`.
3. Leave the commit(s) on `dev` (do not push). Report commit SHAs, test results, and anything
   deferred.
