---
name: 2026-06-08-debug-mode-reset-tools
status: done
created: 2026-06-08
model: sonnet
completed: 2026-06-08
result: |
  Implemented. debug_mode config flag gates two new endpoints (POST /api/debug/clear-spoolman-fdb-refs
  and POST /api/debug/reset-bridge-state). Frontend Debug mode toggle + Danger zone in Settings.tsx.
  9 backend tests, 721 total pass. Frontend tsc + build clean.
---

# Task: Debug mode + reset tools — clear Spoolman FDB refs and reset bridge state

For clean re-testing (wiped Filament DB, but Spoolman still carries stale `filamentdb_*` xref
extras and/or the bridge still has stale mappings → deletion-conflict flood), add a gated
Debug section with two destructive reset actions.

## Backend

1. **Config flag** `debug_mode` (bool, default `false`): `models/config.py` defaults,
   `schemas/api.py` `ConfigResponse`/`ConfigUpdateRequest`, `api/config.py` `_config_response`.
2. **New router** `backend/app/api/debug.py` (register in `main.py`). BOTH endpoints must
   return **403** unless `debug_mode` is currently true (read from BridgeConfig):
   - `POST /api/debug/clear-spoolman-fdb-refs` — fetch all Spoolman spools; for each spool that
     has any of the three cross-ref extras set
     (`_settings.spoolman_field_filamentdb_id` / `_filamentdb_spool_id` /
     `_filamentdb_parent_id`), PATCH it to blank those extras (`encode_extra_value("")` for
     each present key). Return `{"cleared": <count of spools updated>}`. Errors per-spool are
     logged but don't abort the batch (report a `failed` count too).
   - `POST /api/debug/reset-bridge-state` — delete all rows from `FilamentMapping`,
     `SpoolMapping`, `Snapshot`, `Conflict`, and `SyncLog` (local only — touches NEITHER
     upstream system). Do NOT clear BridgeConfig (keep settings, urls, debug_mode). Return the
     per-table deleted counts. (Leave `wizard_completed`/`auto_sync_enabled` as-is, OR reset
     `wizard_completed` to false — pick reset-to-false so the user can cleanly re-run the
     wizard; note the choice.)
3. Reuse `decode_extra_value`/`encode_extra_value` and the Spoolman client's `update_filament`/
   `update_spool`/`get_spools` as appropriate. The xref extras live on the SPOOL entity.

## Frontend

1. `client.ts` + types: `getConfig` already returns config; add `setDebugMode` via the existing
   config-update path (debug_mode is just another config field). Add `clearSpoolmanFdbRefs()`
   and `resetBridgeState()` calling the two endpoints (typed responses with the counts).
2. **Settings.tsx**: add a **"Debug mode"** toggle (its own small section, clearly labeled as
   for development/testing). When debug_mode is ON, render a **"Danger zone"** block (red-bordered)
   with two buttons:
   - **"Clear Filament DB references from Spoolman"** — on click, open the existing
     `BackupSafetyDialog` (it writes to Spoolman); on proceed, call `clearSpoolmanFdbRefs()` and
     show the cleared/failed counts. Strong confirm copy ("blanks filamentdb_id/spool_id/parent_id
     on every Spoolman spool — irreversible").
   - **"Reset bridge sync state"** — a plain confirm (local-only, no upstream write); on confirm
     call `resetBridgeState()` and show the deleted counts. Copy: "clears the bridge's mappings,
     snapshots, conflicts, and sync log — does NOT touch Spoolman or Filament DB."
   When debug_mode is OFF, the Danger zone is hidden.

## Verification

- `cd backend && pytest` — tests: both endpoints 403 when `debug_mode` is false; with it true,
  `clear-spoolman-fdb-refs` blanks the three extras on spools that had them (mock the Spoolman
  client; assert update_spool called with blanked extras + the count); `reset-bridge-state`
  deletes mappings/snapshots/conflicts/sync_log and returns counts (seed some rows, assert empty
  after); config round-trips `debug_mode`.
- `cd frontend && npx tsc --noEmit && npm run build`.
- Reason through: turning on Debug mode reveals the Danger zone; clearing refs blanks Spoolman
  xrefs (via backup-gated dialog); resetting state empties the bridge's local tables — clean
  slate for re-testing.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md`: a gated Debug mode exposes reset tools (clear Spoolman FDB xrefs;
   reset bridge local state) for clean re-testing; endpoints 403 unless debug_mode is on.
   Add `DEBUG_MODE` to the env table only if you env-back it (optional).
3. Non-interactive subagent run: when pytest + build pass, stage ONLY the files this task
   touched (incl. prompt move + docs) and commit on `dev` with one `feat:` message. Never
   `git add -A`. Never push.
