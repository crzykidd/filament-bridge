---
name: 2026-06-08-fdb-snapshot-backup
status: done
created: 2026-06-08
model: sonnet
completed: 2026-06-08
result: All changes implemented and verified. 708 backend tests pass. Frontend tsc + build clean. Committed on dev.
---

# Task: Add Filament DB one-click backup (GET /api/snapshot) — dialog button + README fix

Filament DB DOES have a backup API after all: **`GET /api/snapshot`** returns a full JSON
backup (`{version, createdAt, collections}` — filaments, nozzles, printers, locations, print
history, catalogs, incl. tombstones; schema v4). `POST /api/snapshot` restores (destructive).
Add a symmetric one-click "Back up Filament DB now" to the pre-write safety dialog, and correct
the README/docs (which currently say FDB has no backup API and recommend only mongodump).

## Backend

1. **FDB client** (`backend/app/services/filamentdb.py`): add
   `async def get_snapshot(self) -> dict:` → `GET /api/snapshot`, `raise_for_status()`, return
   the parsed JSON. Use a generous timeout (the snapshot can be large).
2. **Backup router** (`backend/app/api/backup.py`): add `POST /backup/filamentdb` mirroring the
   existing `POST /backup/spoolman`. It calls `request.app.state.filamentdb.get_snapshot()`,
   writes the JSON to `DATA_DIR/backups/filamentdb-snapshot-<UTC-timestamp>.json` (create the
   `backups` dir if missing; use the configured `DATA_DIR`), and returns
   `{"success": True, "detail": "<saved path>"}`. On error, return `{"success": False,
   "detail": "<status/body>"}` (catch httpx + IO errors — never 500). Reuse the same response
   model as the Spoolman proxy if it fits.
   - Note: unlike Spoolman (which backs up into its OWN volume), FDB's snapshot is downloaded,
     so the bridge persists it into the bridge's data volume. Make that clear in the
     detail/docstring.

## Frontend

1. **API client** (`client.ts` + types): add `backupFilamentDb()` →
   `POST /api/backup/filamentdb` returning `{ success, detail }`.
2. **BackupSafetyDialog** (`frontend/src/components/BackupSafetyDialog.tsx`): add a second
   button, **"Back up Filament DB now"**, next to the Spoolman one, with the same spinner/
   ✓/✗ states. Remove the mongodump copy-paste block (no longer the primary path) OR keep it
   demoted to a small "or back up the raw Mongo volume" note. Update the Proceed gating so it
   is enabled when the acknowledgment checkbox is checked OR **either** backup succeeded (keep
   it simple and forgiving). Keep Cancel/Proceed and the actionLabel behavior.

## README / docs

- `README.md` **Backups** section: replace the "Filament DB — no backup API" text. Filament DB
  backs up via `GET /api/snapshot` (a JSON snapshot; restore via `POST /api/snapshot`), e.g.
  `curl http://<fdb-host>:3000/api/snapshot -o fdb-snapshot.json` — or the bridge's one-click
  button. Keep mongodump/volume snapshot as a secondary "raw database" option.
- `docs/prd.md` / `docs/decisions.md`: if either states FDB has no backup API, correct it to
  note `/api/snapshot`. (Update the backup-safeguard decision entry to mention the FDB button.)

## Verification

- `cd backend && pytest` — test: `POST /api/backup/filamentdb` calls the FDB client's
  `get_snapshot`, writes a file under DATA_DIR/backups, and returns success:true with the path
  (mock the client + a temp DATA_DIR); on a raised error returns success:false (no 500).
- `cd frontend && npx tsc --noEmit && npm run build`.
- Reason through: the pre-write dialog now backs up BOTH systems one-click; Proceed enabled on
  ack or either backup.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. Update `docs/decisions.md` as above.
3. Non-interactive subagent run: when pytest + build pass, stage ONLY the files this task
   touched (incl. prompt move + docs) and commit on `dev` with one `feat:` message. Never
   `git add -A`. Never push.
