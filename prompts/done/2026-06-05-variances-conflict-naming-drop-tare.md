---
name: 2026-06-05-variances-conflict-naming-drop-tare
status: completed        # pending | completed | failed
created: 2026-06-05
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-05
result: Removed spool_weight from sm_prop_conflicts so tare-only diff no longer triggers suggest_exclude; standalone badge now names specific conflicting fields (e.g. "suggested standalone — diameter, nozzle temp differ")
---

# Task: Don't let tare break variant grouping; name the specific prop conflict

Two related changes to the wizard Variances step (Spoolman → Filament DB):

1. **Empty-reel tare (`spool_weight`) must NOT count as a variant-prop conflict.** Today
   two filaments that are identical except for their tare (e.g. ELEGOO PLA Beige tare
   160 vs ELEGOO PLA Black tare 154) get the non-master one auto-flagged
   `suggest_exclude` and shown as "suggested standalone", so they don't auto-group. This
   is self-contradictory: the group already unifies tare ("All variants in this group
   will use the master's empty-reel tare"). Tare is a physical/estimated reel weight, not
   a property that distinguishes a product line.
2. **The "suggested standalone" badge must name WHICH property conflicts** (e.g.
   "suggested standalone — diameter, nozzle temp differ") instead of the generic
   "(prop conflict)".

## Before you start

- Read `CLAUDE.md` for conventions. SM-direction wizard only. No upstream writes here.
- Background: `sm_prop_conflicts(master, member)` in `backend/app/core/matcher.py`
  (~182-201) compares material, density, diameter, spool_weight, settings_extruder_temp,
  settings_bed_temp and returns a list of `{field, master_value, member_value}` for each
  mismatch. It feeds three call sites (all should change consistently via this one edit):
  `wizard.py` ~375 and ~535 (variances rows), `planner.py` ~188 (execute prop_conflicts).
- `suggest_exclude` is set in `wizard.py` (~545) as `bool(conflicts) and not is_master`.
  Removing spool_weight from the conflict list means a tare-only difference yields no
  conflicts → no suggest_exclude → the member auto-groups.

## Working tree check

`git status --porcelain` — files: `backend/app/core/matcher.py`,
`frontend/src/pages/Wizard/StepVariances.tsx`, plus a test file and maybe
`docs/decisions.md`. Ignore unrelated untracked home-dir dotfiles. This prompt is exempt.

## What to do

### 1. Backend — drop `spool_weight` from the conflict check

In `backend/app/core/matcher.py` `sm_prop_conflicts`, remove the
`("spool_weight", master.spool_weight, member.spool_weight)` entry from the `checks`
list. Add a brief comment: tare is unified per variant group (the group's empty-reel tare
applies to all members) and is not a variant-distinguishing property, so a tare
difference must not flag a member for exclusion.

This makes the ELEGOO PLA Beige/Black case auto-group (assuming they don't also differ on
a real material property). It also removes spool_weight from the reconcile UI conflict set
— which is correct, because tare already has its own dedicated per-group input.

### 2. Frontend — mirror the change + name the conflict

In `frontend/src/pages/Wizard/StepVariances.tsx`:

- The client-side `computeConflicts` (~27-41, commented "mirrors backend
  sm_prop_conflicts") still includes `spool_weight` — remove that line so the live
  recompute matches the backend.
- Add a human-friendly field-label map for display, e.g.:
  ```ts
  const CONFLICT_FIELD_LABELS: Record<string, string> = {
    material: 'material/type',
    density: 'density',
    diameter: 'diameter',
    settings_extruder_temp: 'nozzle temp',
    settings_bed_temp: 'bed temp',
  }
  ```
- Replace the standalone badge (~902-903) text "suggested standalone (prop conflict)"
  with one that names the conflicting fields from the row's `conflicts` array, e.g.
  `suggested standalone — {diameter, nozzle temp} differ`. Build the list from
  `f.conflicts.map(c => CONFLICT_FIELD_LABELS[c.field] ?? c.field)`, dedupe, join with
  ", ". If for some reason `conflicts` is empty but `suggest_exclude` is true, fall back
  to a plain "suggested standalone". Handle singular/plural cleanly ("differ" is fine for
  both, or use "differs" when one).
- For consistency, also use `CONFLICT_FIELD_LABELS` in the in-group "Conflicts with
  master:" box (~668-671) so field names read the same everywhere. Keep showing the
  `(member_value vs master_value)` detail.

## Conventions to honor

- `code-checkin-and-pr`: work on `dev`, conventional-commit `fix:` prefix, NO
  `Co-authored-by:` trailer, docs in same commit.
- Don't change tare handling, reconcile apply logic, or weight math.

## Verification

- `cd backend && pytest` — add/adjust tests:
  - `sm_prop_conflicts`: two filaments differing ONLY in `spool_weight` → returns `[]`
    (no conflict). A real difference (e.g. diameter or nozzle temp) still returns that
    field.
  - variances endpoint: a cluster of two filaments identical except tare → forms ONE
    group with both members and `suggest_exclude=False` on the non-master (no longer
    pushed to ungrouped/standalone).
- `cd frontend && npx tsc --noEmit && npm run build` — must pass. Run `npm test` if
  wizard tests exist.
- Reason through the screenshot case: ELEGOO PLA Beige (master) + Black differ only on
  tare → now one group, Black NOT suggested standalone. If they also differed on, say,
  diameter, the badge would read "suggested standalone — diameter differ".

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/` (failure).
3. Record in `docs/decisions.md`: tare (`spool_weight`) is excluded from
   variant-prop-conflict detection because tare is unified per group; conflict badges now
   name the specific differing fields.
4. Non-interactive subagent run: when pytest + tsc + build pass, stage ONLY the files
   this task touched (incl. prompt move + docs) and commit on `dev` with one `fix:`
   message. Never `git add -A`. Never push.
