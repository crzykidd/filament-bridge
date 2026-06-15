---
name: 2026-05-31-matches-table-power-ux
status: completed        # pending | completed | failed
created: 2026-05-31
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-01
result: unified table with Group-By/Sort/Search/filter toolbar, collapsible groups, per-group aggregates; all v1 decision logic preserved; no backend changes needed
---

# Task: Match review v2 — power "group/sort/filter" table (reference-driven)

The v1 grouped match-review tables shipped (commit `854bd61`: four status tables, Material/Brand
subgroups, tri-state checkboxes, Rescan, rehydration). The user wants to evolve the *display* toward
a denser, more powerful pattern — pick a Group-By dimension, sort by any attribute, filter per
column, and expand a group into a columnar detail view.

**Reference image:** `prompts/assets/2026-05-31-grouping-reference.png` (an ammunition-inventory
app). **Mimic the structure and interactions, NOT the visual styling** — the user said "color
doesn't matter." It's the toolbar + collapsible group rows + expand-to-columns behaviour we want,
restyled to match this app's existing Tailwind look.

## Before you start

- Read `CLAUDE.md` (deep-links requirement, "what NOT to do") and `docs/decisions.md` — esp. the
  2026-05-31 "Match-review redesign" entry, which is the v1 this builds on.
- Study `prompts/assets/2026-05-31-grouping-reference.png` and read the v1 you're evolving:
  `frontend/src/pages/Wizard/Step3Matches.tsx`, `frontend/src/api/{types,client,hooks}.ts`,
  and the backend match endpoint/schema (`backend/app/api/wizard.py` `wizard_matches`,
  `backend/app/schemas/api.py` `FilamentRef`/`WizardMatchesResponse`/`MatchDecision`).
- Confirm with the user (or in `docs/decisions.md`) the **one structural question** below before
  building, since it changes the layout materially.

## What the reference shows (target behaviours)

A single powerful table with a toolbar on top:

1. **Toolbar controls:**
   - **Group By** dropdown — choose the grouping dimension (in the ref: Manufacturer). For us:
     Status, Material, or Brand/vendor.
   - **Sort By** dropdown **+ a direction-toggle arrow** (asc/desc).
   - **Search all fields** box + an optional field-scope dropdown ("All Fields").
   - Extra **filter dropdowns** (the ref has Empty / Status / Conditions). For us, candidates:
     Status, Match-confidence band, has-conflict — keep to what's useful, don't over-build.
   - **Collapse All / Expand All** links.
   - Right-aligned **summary stats** (the ref: Boxes / Rounds / Value). For us e.g.
     filament count / spool count / total weight — only if cheap to compute from the payload.
2. **Column header row** with **per-column sort arrows**, and a **per-column filter input row**
   beneath it (the ref's "ID..", "Caliber..", "<,>,exa" numeric filters).
3. **Collapsible group rows** (the ref: Blazer, Federal, …) — each with a select checkbox, a
   chevron, the group name, and **right-aligned aggregates** for that group. Warning affordances
   (the ref's "⚠ 2 low") map to our conflict/ambiguous counts.
4. **Expand a group → member rows laid out in columns** (the ref's Blazer → row with
   ID / Caliber / Manufacturer / GR / Type+badge / Category / Remaining / Value / Shared + inline
   action icons). For us, member columns: select checkbox, Status, Brand, Name, Material, →FDB
   match (name + confidence), and the action affordance (link/create/skip; ambiguous picker).
5. **Bulk-select checkboxes** at the table, group, and row levels (v1 already has tri-state group +
   table checkboxes — reuse that decision→action mapping; don't regress it).

## The one structural question (decide first)

v1 uses **four fixed status tables**. The reference uses **one table with a Group-By dropdown**.
Reconcile these. Recommended: **one table; make Status one of the Group-By options** (default
Group-By = Status, which reproduces the v1 four-section feel, but the user can switch to Material or
Brand). Status then also appears as a column + a filter. Keep the Unmatched-in-FDB rows as
informational (no action checkboxes) regardless of grouping. If the user prefers to keep four hard
tables and only enrich each, do that instead — but confirm before building.

## What to do (high level — flesh out after the structural decision)

1. **Frontend** (`Step3Matches.tsx` + small helpers): build the toolbar (Group By / Sort By +
   direction / search / per-column filters / Collapse-Expand All), the columnar table with
   collapsible group rows + per-group aggregates, and expand-to-columns member rows. Preserve v1's
   decision model, tri-state checkboxes, Rescan, and `saved_decisions` rehydration. Keep
   `DeepLinks` on every member row.
2. **Backend** — only if a target column/aggregate needs a field not already on `FilamentRef`
   (v1 added `material`; `vendor`/`color`/ids/`confidence` already present). Spool-derived
   aggregates (counts/weight) would require fetching spools in `wizard_matches` — treat as optional
   and call it out; don't add silently.
3. **Performance:** grouping/sorting/filtering happen client-side over the already-fetched match
   payload. Keep it responsive for large libraries (the user's whole motivation) — memoize derived
   group/sort/filter results.

## Conventions to honor

- Match the app's existing Tailwind styling; ignore the reference's dark theme/colors.
- Never auto-resolve matches; the checkbox/picker is the decision. Don't change the matcher.
- Doc updates ship in the **same commit** as the code. Commit on `dev`, `feat:`, no
  `Co-authored-by:`. Never `--no-verify`. Never push. Run `pytest` + `npx tsc --noEmit` first.

## When done

1. Update this file's frontmatter: `status`, `completed` (date), `result`.
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/` (failure).
3. Record the structural decision (one table + Group-By Status, or four tables) and any new
   backend fields/aggregates in `docs/decisions.md`.
4. Propose ONE commit covering the modified files (incl. this prompt move and the reference asset).
   Present the file list + a one-line `feat:` message; ask `commit these as "<message>"? (y/n)`. On
   `y`, stage those specific paths and commit on `dev`. Never `git add -A`. Never push.
</content>
