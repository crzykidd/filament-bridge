---
name: 2026-06-08-docs-claude-prd-refresh
status: completed
created: 2026-06-08
model: sonnet
completed: 2026-06-08
result: CLAUDE.md and docs/prd.md updated — module lists corrected, wizard renamed, two-axis model documented, PUID/PGID + BridgeConfig settings added, FR-2/FR-7/FR-8/FR-17/FR-19/FR-23c updated.
---

# Task: Refresh CLAUDE.md + docs/prd.md (most-stale internal/spec docs)

Documentation-only. Touch ONLY `CLAUDE.md` and `docs/prd.md` (+ prompt move). ONE `docs:`
commit. A parallel agent edits README/configuration and CHANGELOG/decisions — do NOT touch those.
Verify everything against the code.

## A. CLAUDE.md (most stale)

1. **Project-structure block** — update to match reality:
   - `backend/app/api/`: add `debug.py` (debug reset tools), `opentag.py`, `sync_log.py`,
     `wizard.py`, `errors.py` (currently only lists sync/conflicts/mappings/config/backup/health).
   - `backend/app/core/`: add `sync_policy.py`, `planner.py`, `dryrun.py`, `color.py`,
     `material_tags.py`, `version.py`, `opentag_match.py`, `opentag_cache.py`,
     `opentag_secondary.py` (currently only engine/differ/matcher/weight/fields). Mirror the
     PRD's structure block which already has these.
   - `frontend/src/pages/`: add `Settings.tsx` and `OpenTagCleanup.tsx`.
   - Root files: add `docker-entrypoint.sh` (the chown-then-gosu entrypoint) and confirm
     `docker-compose.dev.yml` is present.
2. **Env-var table**: add `PUID` / `PGID` (entrypoint env, default 1000) and a one-line note on
   the entrypoint permissions behavior. Add a short **"Runtime-editable settings (BridgeConfig)"**
   note covering `debug_mode`, `never_import_empties`, `sync_log_retention_days`, and that
   `sync_interval_seconds` is runtime-editable (env is the fallback).
3. **Wizard rename**: "guided initial sync wizard" / "multi-step initial sync wizard" →
   **"Bulk Import Wizard"** (re-runnable).
4. **Source-of-truth wording**: the Architecture-decisions line "Source of truth is
   user-configurable per data category" is superseded by the **two-axis direction + conflict-policy**
   model (`core/sync_policy.py`); reword to match (Settings owns it; the wizard only picks
   initial import direction).

## B. docs/prd.md

1. **FR-2** (Direction selection): it still says the wizard configures ongoing per-category
   sync settings — that step was REMOVED from the wizard (it now captures import direction
   only; the two-axis direction+conflict-policy model lives in Settings). Reduce FR-2 to
   import-direction selection and reference Settings/FR-8 for the ongoing two-axis model.
2. **Wizard rename**: "Initial sync wizard" / "Execute initial sync" headings → **"Bulk Import
   Wizard"** (re-runnable). FR-7 should note the `never_import_empties` skip behavior applied at
   preview/execute.
3. **Add brief FRs / notes** for the shipped features not in the PRD: Debug mode + reset tools
   (`POST /api/debug/clear-spoolman-fdb-refs`, `POST /api/debug/reset-bridge-state`, 403 unless
   `debug_mode`); Scheduler runtime interval + sync-log retention (FR-8 currently implies
   env-only interval); Sync Log windows view + clear-log (FR-17); Synced Records hide-empty
   filter (FR-19). Keep them concise.
4. The structure block (lines ~48-62) is already current; the deployment line (~73) may note
   the standard-vs-dev compose split if trivial.

## Verification

- No code touched. `git diff --stat` shows only CLAUDE.md + docs/prd.md (+ prompt move).
- No remaining "initial sync wizard" phrasing; CLAUDE.md module lists match the actual dirs.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. Pathspec-scoped commit of ONLY those two files + prompt move, `docs:` message. Retry once on
   index lock. Never `git add -A`. Never push.
