---
name: 2026-06-08-scheduler-settings
status: done
created: 2026-06-08
model: sonnet
completed: 2026-06-07
result: 697 pytest pass; tsc + vite build clean. Runtime interval reschedule, prune helper, Settings Scheduler & Logs section all implemented.
---

# Task: Scheduler + log retention settings (runtime interval, auto-sync toggle, sync-log days)

Make the auto-sync scheduler configurable from Settings, and add sync-log retention. The app
logs to stdout (no log files — Docker rotates container logs), so there is NO in-app log-file
rotation; retention applies to the `sync_log` DB table.

## Backend

1. **Runtime sync interval** (`backend/app/config.py` already has `sync_interval_seconds` env
   default; `backend/app/models/config.py` + `api/config.py`): add a BridgeConfig override
   `sync_interval_seconds` (stored in minutes-friendly seconds; UI uses minutes). Expose it +
   `auto_sync_enabled` in `ConfigResponse`/`ConfigUpdateRequest`.
2. **Reschedule on change** (`backend/app/main.py`): give the interval job a stable id; store
   the scheduler on `app.state`. When the config-update endpoint changes
   `sync_interval_seconds`, reschedule the job (`scheduler.reschedule_job(id, trigger="interval",
   seconds=N)`). Clamp to a sane minimum (e.g. ≥ 30s).
3. **Sync-log retention** (`api/config.py` + a prune helper): add config
   `sync_log_retention_days` (default 30; 0 = keep forever). At the start of each auto-sync tick
   (in `main.py`'s scheduled job) AND on demand, when retention_days > 0, delete `SyncLog` rows
   older than `now - retention_days`. Keep it cheap (one DELETE). Log how many were pruned.
4. Keep the existing `set_auto_sync` guard (refuse enable until wizard completed).

## Frontend (`frontend/src/pages/Settings.tsx` + client/types)

- Add a **"Scheduler & Logs"** settings section:
  - **Auto-sync enabled** toggle (reads/writes `auto_sync_enabled`). Enabling must go through
    the existing `BackupSafetyDialog` (reuse the component — same as Dashboard's enable path);
    disabling is immediate. If the wizard isn't completed, show the backend's refusal message.
  - **Sync interval (minutes)** number input. Show a warning when the interval is **> 5
    minutes**: "Longer intervals give both systems more time to change the same record between
    syncs, raising the chance of merge conflicts." Convert minutes ↔ seconds for the API.
  - **Sync-log retention (days)** number input (0 = keep forever) with a one-line note.
  - A small note: "Application logs go to the container's stdout — rotation is handled by your
    Docker logging driver."
- Wire into the existing Settings save flow (`ConfigResponse`/`ConfigUpdateRequest` types +
  client). Keep all existing settings intact.

## Verification

- `cd backend && pytest` — tests: config round-trips `sync_interval_seconds` +
  `sync_log_retention_days` + `auto_sync_enabled`; the prune helper deletes only SyncLog rows
  older than the cutoff (and is a no-op when retention_days=0). (Rescheduling can be asserted by
  checking the config-update path calls reschedule / clamps the minimum — mock the scheduler if
  needed.)
- `cd frontend && npx tsc --noEmit && npm run build`.
- Reason through: changing the interval in Settings reschedules without restart; >5min shows
  the warning; retention prunes old sync-log rows; enabling auto-sync from Settings shows the
  backup dialog.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md`: sync interval + sync-log retention are runtime-configurable; no in-app
   log-file rotation (stdout/Docker). Update CLAUDE.md/configuration.md env table only if you
   add a new env var (`SYNC_LOG_RETENTION_DAYS` if you choose to env-back it).
3. Non-interactive subagent run: when pytest + build pass, stage ONLY the files this task
   touched (incl. prompt move + docs) and commit on `dev` with one `feat:` message. Never
   `git add -A`. Never push.
