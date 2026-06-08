---
name: 2026-06-08-prewrite-backup-safeguard
status: done
created: 2026-06-08
model: sonnet
completed: 2026-06-07
result: Implemented. BackupSafetyDialog gates Wizard Execute, OpenTag Apply, and Enable auto-sync. Spoolman backup proxied via POST /api/backup/spoolman. 672 backend tests pass, frontend build clean.
---

# Task: Pre-write backup safeguard — one-click Spoolman backup + FDB reminder before destructive writes

Alpha data-safety feature. Before the three actions that write to upstream systems, show a
reusable dialog that lets the user back up Spoolman in one click (proxying Spoolman's backup
API) and reminds them to back up Filament DB (mongodump — no API), then proceed.

Gate these three actions:
1. **Wizard Execute** — `frontend/src/pages/Wizard/Step6Execute.tsx` (`handleExecute`, button ~131).
2. **OpenTag Apply** — `frontend/src/pages/OpenTagCleanup.tsx` (`handleApply` ~821; the
   "Apply N writes" button ~506 / `onApply` ~1142).
3. **Enable auto-sync** (only when ENABLING, not disabling) — `frontend/src/pages/Dashboard.tsx`
   (the auto-sync toggle that calls the set-auto-sync client method).

## Backend

1. **Spoolman client** (`backend/app/services/spoolman.py`): add
   `async def trigger_backup(self) -> dict:` → `POST /api/v1/backup`, `raise_for_status()`,
   return the JSON body (or `{}` if empty). This is a safe server-side backup.
2. **Backup router** (`backend/app/api/backup.py`): add `POST /backup/spoolman` that takes
   `request: Request`, calls `await request.app.state.spoolman.trigger_backup()`, and returns
   `{"success": True, "detail": <path-or-message>}`. On `httpx` error, return
   `{"success": False, "detail": "<status + body>"}` (catch and report — do not 500). Add a
   small Pydantic response model. (Spoolman writes the backup into its own data volume — say so
   in the detail/docstring.)

## Frontend

1. **API client** (`frontend/src/api/client.ts` + types): add `backupSpoolman()` →
   `POST /api/backup/spoolman` returning `{ success: boolean; detail: string }`.
2. **Reusable dialog** — new `frontend/src/components/BackupSafetyDialog.tsx`:
   - Props: `{ open, actionLabel, onCancel, onProceed }`.
   - Body: an alpha warning that this writes to Spoolman + Filament DB.
   - **Spoolman:** a "Back up Spoolman now" button → calls `backupSpoolman()`, shows a spinner
     then "✓ Spoolman backed up" (with the returned detail) or "✗ <error>".
   - **Filament DB:** note there's no backup API; show a copy-pasteable
     `docker exec <mongo-container> mongodump --archive=/data/db/fdb-$(date +%F).archive`
     with a copy button, and a one-line "replace <mongo-container> with your Mongo container".
   - An acknowledgment checkbox: "I've backed up my data (or accept the risk)".
   - Footer: **Cancel** and **Proceed** (`Proceed {actionLabel}`). **Proceed is disabled until
     EITHER the Spoolman backup succeeded OR the checkbox is checked.**
   - Style to match existing modals/Tailwind. Keep it self-contained.
3. **Wire the three actions**: clicking the action button opens the dialog instead of running
   immediately; `onProceed` closes the dialog and runs the original logic (`handleExecute` /
   `handleApply` / enabling auto-sync). For the auto-sync toggle, ONLY gate the enable path —
   disabling auto-sync runs immediately, no dialog. Pass a fitting `actionLabel` to each
   ("Run initial sync" / "Apply N writes" / "Enable auto-sync").

## Verification

- `cd backend && pytest` — test: `POST /api/backup/spoolman` calls the Spoolman client's
  `trigger_backup` and returns `success: true` with its detail (mock the spoolman client /
  app.state); on a raised httpx error it returns `success: false` (no 500).
- `cd frontend && npx tsc --noEmit && npm run build`.
- Reason through: clicking Execute / Apply / Enable-auto-sync opens the dialog; "Back up
  Spoolman now" hits the proxy; Proceed is gated on backup-success-or-ack; Cancel aborts;
  disabling auto-sync is NOT gated.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md`: a pre-write backup safeguard dialog gates the wizard execute, OpenTag
   apply, and enable-auto-sync actions; Spoolman is backed up via its API, FDB via mongodump
   (no API). Update `docs/spoolman-writes.md` only if relevant (it's a backup, not a field
   write — probably skip).
3. Non-interactive subagent run: when pytest + build pass, stage ONLY the files this task
   touched (incl. prompt move + docs) and commit on `dev` with one `feat:` message. Never
   `git add -A`. Never push.
