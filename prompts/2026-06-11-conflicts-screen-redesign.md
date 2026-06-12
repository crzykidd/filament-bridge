---
name: 2026-06-11-conflicts-screen-redesign
status: pending          # pending | completed | failed
created: 2026-06-11
model: sonnet
completed:
result:
---

# Task: Conflicts screen redesign — detail panels, per-type actions, and the "Add" flow

Prompt **#2 of 3**. **Depends on #1** (`2026-06-11-new-record-handling-policies`) for the
scoped single-record import endpoint the "Add" button calls. Do not start until #1 has
landed; rebase your understanding on the post-#1 code (new policies, new endpoint).

## Why

The Conflicts screen currently offers only **Dismiss** for `new_spool` conflicts, and hides
the richer actions the backend already supports. The user wants: per-record **details**
(what the item is + both-side values), **real actions** with a recommended default, and for
new spools an **"Add"** action that imports the record via the scoped wizard logic from #1.

## Grounding (verified this session)

The engine already supports more than the UI exposes:
- **`master_divergence`** conflicts carry 3 real actions — `apply_all` / `variant_override`
  / `ignore` (upstream writes) — via `core/conflict_apply.py` / `api/conflicts.py`. Surface
  them as buttons with a recommended default, not buried.
- **`cross_system`** conflicts hold both-side values (`spoolman` / `filamentdb` / `manual`)
  — already enough for a side-by-side detail panel.
- **`deletion`** conflicts resolve record-only + clean up the bridge mapping.
- **`new_spool`** is the one that gains the new **"Add"** action (wired to #1's endpoint).

Frontend: `frontend/src/pages/Conflicts.tsx` + its API wrappers; backend list/resolve in
`backend/app/api/conflicts.py`.

## What to do

1. **Per-conflict detail panel** (expand row): show what the item is — **clearly labeled
   SPOOL vs FILAMENT** — with a side-by-side **Spoolman value | Filament DB value** grid for
   the conflicted field(s). Reuse the DeepLinks + the Synced Records detail-grid styling.
2. **Per-type action buttons with a recommended default:**
   - `master_divergence` → `Apply to all` / `Override this variant` / `Ignore`, with the
     recommended one highlighted and a one-line explanation of each.
   - `cross_system` / weight / material → `Use Spoolman` / `Use Filament DB` / `Manual`, with
     a recommendation (e.g. the side that changed, or per the configured policy).
   - `deletion` → clear "remove bridge link" framing.
   - `new_spool` → **"Add"** (primary) + keep **Dismiss** (secondary).
3. **`new_spool` framing + "Add" flow:** the conflict must read like *"New spool — its
   filament isn't in Filament DB yet"* when the filament is unmapped. "Add" opens a compact
   flow (modal or inline) reusing #1's scoped-import endpoint: if the filament is unmapped,
   capture the link-or-create-filament decision (+ optional tare); show a preview from the
   endpoint; confirm → import → the conflict resolves and the record appears in Synced
   Records. Support **bulk Add** for multiple selected `new_spool` conflicts (the screen
   already has checkboxes).
4. Keep the existing Open/Resolved tabs, sort, expand/collapse, and bulk-select working.

## Conventions to honor

- Don't invent backend behavior — use #1's endpoint + the existing resolve actions. If #1's
  endpoint shape differs from what you expect, adapt to it (read its code/docs).
- Match existing component styling (StatusBadge, DeepLinks, HelpTip, detail grid).
- Update `docs/conflicts.md` to describe the new actions/flow, same commit.
- REQUIRED: `cd backend && pytest` + `ruff check`; `cd frontend && npx tsc --noEmit` +
  `npm test`. (Sandbox `itsdangerous` collection failures are env-only — ignore; no NEW
  failures.) Add/extend `Conflicts.test.tsx`.
- Conventional-commits `feat:`. No `Co-authored-by:`. Branch `dev`, never `main`, never push.

## When done

Update frontmatter; `git mv` to `prompts/done/`; log decisions; propose ONE `feat:` commit
(specific paths, never `git add -A`) and STOP for the user to run it. Never push.
