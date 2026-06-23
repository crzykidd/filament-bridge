---
name: 2026-06-23-scheduled-backups
status: pending          # pending | completed | failed
created: 2026-06-23
model: sonnet
completed:
result:
---

# Task: Scheduled nightly backups (issue #5)

Add an automatic nightly backup job to filament-bridge: it writes the bridge's own
state export and the Filament DB snapshot to `DATA_DIR/backups/`, and prunes files
older than a configurable retention window. Closes GitHub issue #5 ("Create schedule
backups — Schedule a nightly backup … keep x days"). Bundle the backups documentation
(new `docs/backups.md` + index/config wiring) into this same task.

## Decisions already made (do NOT re-ask — implement exactly these)

- **Scope: bridge-state export + FDB snapshot only.** Do **NOT** trigger Spoolman's
  server-side backup from the scheduled job. Rationale: Spoolman writes its archive into
  its own volume and the bridge has no way to prune it, so scheduling it would leak
  storage with no retention control. (The existing manual `POST /backup/spoolman` button
  stays as-is — this task does not remove it.)
- **Two independent toggles, both ON by default:**
  - bridge-state backup (the bridge's own `GET /backup/export` payload)
  - FDB-snapshot backup (the existing `GET /api/snapshot` → file flow)
- **Master enable: ON by default.** The feature runs automatically once deployed.
- **Retention: 7 days default, configurable in Settings.** Applies only to the files the
  bridge writes into `DATA_DIR/backups/` (bridge-state + FDB snapshots). Never touches
  Spoolman's archives or unrelated files.
- **Schedule: nightly at a configurable UTC hour, default 03:00** (minute 0).

## Before you start

- Read `CLAUDE.md` (esp. the env-var table, runtime-editable settings table, and the
  archive/lifecycle + backup notes), `docs/prd.md` FR-24, and `standards.md`.
- Honor the `code-checkin-and-pr` standard: work on the branch you're on (a worktree off
  `dev`), Conventional-Commit prefix `feat:`, **no** `Co-authored-by:` trailers, doc
  updates ship in the SAME commit as the code.
- Mirror existing patterns rather than inventing new ones:
  - **Env fallback → DB override** like `sync_interval_seconds`: env defaults live in
    `backend/app/config.py` (Settings), runtime overrides live in
    `backend/app/models/config.py` `_DEFAULTS` (string-valued KV — new keys are seeded
    automatically by the `_DEFAULTS` loop, **no Alembic migration needed**), surfaced and
    saved via `backend/app/api/config.py`.
  - **Scheduler**: the `AsyncIOScheduler` is created in `backend/app/main.py` (`_scheduler`,
    job id `sync_cycle`, stored on `app.state.scheduler`). The job function `_sync_job`
    early-returns when disabled — mirror that gating pattern.
  - **Reschedule on save**: `api/config.py` already reschedules `sync_cycle` when the
    interval changes (`scheduler.reschedule_job(...)`). Do the equivalent for the backup
    cron when the hour or master-enable changes.

## Working tree check

You are running unattended in an isolated worktree. Run `git status --porcelain` first;
if files this plan must modify are already dirty (other than this prompt), note it and
continue — the worktree starts from a clean `dev`, so it should be clean.

## What to do

### Backend — config
1. `backend/app/config.py` (Settings, env fallback) — add:
   - `backup_schedule_enabled: bool = True`
   - `backup_bridge_state_enabled: bool = True`
   - `backup_filamentdb_enabled: bool = True`
   - `backup_retention_days: int = 7`
   - `backup_hour_utc: int = 3`
   Env var names: `BACKUP_SCHEDULE_ENABLED`, `BACKUP_BRIDGE_STATE_ENABLED`,
   `BACKUP_FILAMENTDB_ENABLED`, `BACKUP_RETENTION_DAYS`, `BACKUP_HOUR_UTC`.
2. `backend/app/models/config.py` `_DEFAULTS` — add the same five as runtime-editable KV
   keys (string-encoded to match the file's convention: booleans as `"true"`/`"false"`,
   ints as quoted numbers). These become editable in Settings; env is the start-up
   fallback (DB value wins when set), same precedence as the interval.

### Backend — shared backup helpers (DRY)
3. Refactor `backend/app/api/backup.py` so the file-producing logic is reusable by both
   the HTTP endpoints and the scheduled job. Extract into a shared module
   (e.g. `backend/app/core/backup_job.py`):
   - `build_state_export(db) -> dict` (the payload `export_backup` already assembles) and a
     writer that dumps it to `DATA_DIR/backups/bridge-state-<UTC ts>.json`.
   - the FDB snapshot fetch+write currently in `trigger_filamentdb_backup` →
     `filamentdb-snapshot-<UTC ts>.json` (keep the existing filename pattern).
   - `run_scheduled_backup(db, filamentdb, *, settings/config)` that, honoring the two
     toggles, writes whichever backups are enabled, then prunes.
   - `prune_backups(dir, retention_days, prefixes=("bridge-state-", "filamentdb-snapshot-"))`
     — delete only files matching those prefixes older than `retention_days` (by the UTC
     timestamp in the filename, or mtime as a fallback). Log what was pruned (mirror the
     state-dump "keep newest N" logging style). Use the project's UTC-timestamp format
     (`%Y%m%dT%H%M%SZ`) consistent with the existing snapshot filename.
   - Keep the existing `/backup/spoolman`, `/backup/filamentdb`, `/backup/export`,
     `/backup/import` endpoints working (have them call the shared helpers).

### Backend — scheduler
4. `backend/app/main.py` — register a second job on `_scheduler`:
   - id `nightly_backup`, `CronTrigger(hour=<backup_hour_utc>, minute=0)` (resolve the
     effective hour the same env→DB way as the interval).
   - The job function (`_backup_job`) opens a DB session, re-reads the live config, and
     **early-returns if `backup_schedule_enabled` is false**; otherwise calls
     `run_scheduled_backup`. Catch+log exceptions so a failed backup never crashes the
     scheduler. Use `app.state.filamentdb`.
   - Optionally run one `prune_backups` pass at startup so stale files clear even if the
     hour hasn't hit yet (nice-to-have, keep it cheap).
5. `backend/app/api/config.py` — surface the five keys in the read/update config paths and
   **reschedule the `nightly_backup` cron** (and add/remove the job, or just reschedule)
   when `backup_hour_utc` or `backup_schedule_enabled` changes, mirroring the existing
   `sync_cycle` reschedule block. Validate `backup_hour_utc` ∈ 0..23 and
   `backup_retention_days` ≥ 1 (reject with the project's error envelope otherwise).

### Frontend — Settings
6. `frontend/src/pages/Settings.tsx` + `frontend/src/api/client.ts` (+ types) — add a
   **"Scheduled backups"** section: master enable toggle, the two sub-toggles
   (bridge-state, Filament DB), a retention-days number input, and an hour-of-day (UTC)
   selector. Mirror the existing settings controls/styling and the save flow. Make the
   sub-toggles visually subordinate to the master enable (disabled/greyed when master off).

### Tests (`backend/tests/`)
7. Add coverage:
   - `prune_backups` keeps files within the window and deletes older ones; ignores
     non-matching filenames.
   - `run_scheduled_backup` respects each toggle combination (both, bridge-only,
     fdb-only) and writes the expected files (mock the FDB client + a temp DATA_DIR).
   - config defaults + clamp/validation (hour range, retention ≥ 1) and the env→DB
     precedence.
   - Frontend: extend `Settings.test.tsx` if practical (render + toggle), but backend
     coverage is the priority.

### Docs (bundle — ship in the same commit)
8. **New `docs/backups.md`** — document the WHOLE backup story:
   - Manual: Settings export/import (bridge state only), the upstream proxy buttons
     (Spoolman server-side, FDB snapshot→bridge volume), and the pre-write safety dialogs.
   - **Scheduled (new):** what it backs up (bridge state + FDB snapshot, not Spoolman and
     WHY), where files land (`DATA_DIR/backups/`), the nightly UTC-hour schedule, the two
     toggles, retention/pruning, and that the bridge's own SQLite still depends on
     host-volume backup. Include the env vars + Settings equivalents.
9. Wire `docs/backups.md` into the indexes: `README.md` docs table, `CLAUDE.md` Project-
   structure docs tree, and `docs/README.md`.
10. `docs/configuration.md` — add the five env vars (env-var table) and the five runtime
    settings (runtime-settings table).
11. `CLAUDE.md` — add the five env vars to the env-var table and the runtime-editable
    settings table (keep wording consistent with the existing rows).
12. `docs/prd.md` — extend **FR-24** (or add **FR-24b: Scheduled backups**) describing the
    nightly job, toggles, retention, and the deliberate Spoolman exclusion. Note this
    resolves the previously-unbounded accumulation of FDB snapshots.
13. `CHANGELOG.md` — add an **Added** entry under `## [Unreleased]` (user-facing prose):
    nightly scheduled backups of bridge state + Filament DB snapshot with configurable
    retention, on by default, toggles in Settings.

## Conventions to honor

- Keep Spoolman OUT of the scheduled path (decision above) — do not add a Spoolman toggle.
- No new Alembic migration (BridgeConfig keys are KV rows seeded from `_DEFAULTS`).
- `DATA_DIR` comes from settings (`settings.data_dir`), never hard-code `/data`.
- Match the existing UTC timestamp format and the `DATA_DIR/backups/` directory the manual
  FDB backup already uses.
- Reference issue #5 in the commit body (the `Fixes #5` closing keyword goes in the
  eventual `dev → main` release PR, not here).

## When done

1. Update this file's frontmatter: `status: completed` (or `failed`), `completed:`
   (2026-06-23), `result:` one line.
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/` (failure).
3. Record the non-obvious decisions in `docs/decisions.md` (Spoolman excluded for lack of
   prune control; on-by-default; two toggles; 7-day default retention; nightly UTC hour;
   no Alembic migration).
4. You are running UNATTENDED — do NOT ask for confirmation. Make ONE `feat:` commit on
   the current (worktree) branch covering every file you changed + the prompt move. Stage
   the specific paths (never `git add -A`). Do NOT push. Suggested message:
   `feat: scheduled nightly backups of bridge state + FDB snapshot with retention (#5)`.
5. End your final message with: the commit SHA, a concise list of files changed, the test
   command + result, and anything you deferred or were unsure about.
