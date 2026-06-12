---
name: 2026-06-11-settings-page-redesign
status: pending          # pending | completed | failed
created: 2026-06-11
model: sonnet
completed:
result:
---

# Task: Settings page redesign — tight, grouped, 2-column; surface the new policies

Prompt **#3 of 3**. **Depends on #1** (`2026-06-11-new-record-handling-policies`) for the new
`new_filament_policy` / `new_spool_policy` config keys to surface. Start after #1 lands;
rebase on the post-#1 config shape. (Independent of #2.)

## Why

The Settings page (`frontend/src/pages/Settings.tsx`) has grown into loosely-ordered
sections with a misleading top "Scheduler & Logs" block and a catch-all "Other settings"
bucket. The user wants it tightened: common areas grouped, 2-column where it makes sense,
and the sync-related settings consolidated.

## Grounding (current sections, verified)

In render order today: 1 Appearance · 2 **Scheduler & Logs** (auto-sync toggle,
`sync_interval_seconds`, `sync_log_retention_days`, app-logs note) · 3 Weight sync
(direction + policy) · 4 Material properties sync (direction + policy) · 5 New spools
(direction + `never_import_empties`) · 6 Variant parent mode (+ `container_parent_marker`) ·
7 **Other settings** (`sync_weight_threshold_grams`, `weight_precision_decimals`,
`variant_line_keywords`, `opentag_vendor_aliases`, `opentag_color_keywords`, Save) ·
8 Backup · 9 Wizard Status (read-only) · 10 Security (auth) · 11 Debug mode (danger zone).

Reusable sub-components already exist: `DirectionSelect`, `WeightConflictSelect`,
`MatPropConflictSelect`, `AppearanceSection`, `HelpTip`.

## What to do (regroup — keep all existing controls + behaviors)

Reorganize into tight, logical sections; use a 2-column layout where it reads well. Target
grouping:

1. **Sync** (rename "Scheduler & Logs" — it's all sync ops): auto-sync toggle, sync
   interval, sync-log retention. Then the three direction/policy cards — **Weight**,
   **Material properties**, **New records** — grouped under here. Move
   `sync_weight_threshold_grams` + `weight_precision_decimals` (today in "Other settings")
   **next to Weight sync** where they belong.
2. **New records:** the **New filaments** policy + **New spools** policy dropdowns (from #1,
   default Manual review), plus `never_import_empties`. Surface the direction axis too.
   Make the spool-vs-filament hierarchy legible (a short helper line: spools wait for their
   filament).
3. **Import & matching:** Variant parent mode (+ container marker), `variant_line_keywords`,
   `opentag_vendor_aliases`, `opentag_color_keywords` — these are all wizard/matcher tuning.
4. **Appearance**, **Backup**, **Wizard status**, **Security**, **Debug/danger zone** stay
   as their own sections (bottom).

Keep all conditional/disabled logic intact (conflict policy disabled unless two_way; container
marker hidden unless generic_container; security section auth-only; debug danger zone). Keep
the single Save flow + the per-field changed-only PUT payload working. Don't change any config
keys or the API — this is layout/grouping only (plus rendering the two new policy dropdowns
from #1).

## Conventions to honor

- Pure presentational regroup + the two new dropdowns — no backend/API/config-key changes.
- Reuse existing sub-components + HelpTip copy; match current styling/spacing.
- 2-column responsive (collapse to 1 column on narrow widths).
- Update `docs/configuration.md` if section names referenced there change.
- REQUIRED: `cd backend && pytest` + `ruff check`; `cd frontend && npx tsc --noEmit` +
  `npm test`. (Sandbox `itsdangerous` failures env-only — ignore; no NEW failures.) Extend
  `Settings.test.tsx` if present.
- Conventional-commits `feat:` (or `refactor:` if you prefer for a pure regroup). No
  `Co-authored-by:`. Branch `dev`, never `main`, never push.

## When done

Update frontmatter; `git mv` to `prompts/done/`; log any decision; propose ONE commit
(specific paths, never `git add -A`) and STOP for the user to run it. Never push.
