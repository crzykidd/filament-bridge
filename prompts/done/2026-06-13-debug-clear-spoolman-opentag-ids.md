---
name: 2026-06-13-debug-clear-spoolman-opentag-ids
status: completed
created: 2026-06-13
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-13
result: Added POST /api/debug/clear-spoolman-opentag-ids + Settings danger-zone button; 5 new backend tests all green; 1 new frontend test; 1080 passed, ruff clean, tsc clean, 84 frontend tests green
---

# Task: Debug tool — bulk-clear OpenPrintTag ids from Spoolman filaments

Add a gated debug endpoint + Settings danger-zone button that blanks the OpenPrintTag
identity/state extras on every Spoolman **filament** that has any set, to speed up
re-running the matcher during testing. The three extras (all on the FILAMENT, not the
spool) are `openprinttag_slug`, `openprinttag_uuid`, and `openprinttag_ignore`.

This is the filament-level analog of the existing `clear-spoolman-fdb-refs` (which clears
spool-level cross-refs). Spoolman-only — no bridge DB writes, no FDB writes, no record
deletion.

## Before you start

- Read `CLAUDE.md` (debug tools are 403 unless `debug_mode`; OpenPrintTag identity lives on
  Spoolman filament extra fields). Read:
  - `backend/app/api/debug.py` (whole file) — mirror `_blank_spoolman_xrefs` /
    `clear_spoolman_fdb_refs`, the `_require_debug_mode` gate, the `_XREF_EXTRAS` constant
    pattern, and the `ClearRefsResponse` model.
  - `backend/app/services/spoolman.py:128` (`get_filaments`) and `:158`
    (`update_filament(filament_id, payload)`).
  - `backend/app/config.py:68-72` — the three field-name settings:
    `spoolman_field_openprinttag_slug`, `spoolman_field_openprinttag_uuid`,
    `spoolman_field_openprinttag_ignore`.
  - `backend/tests/test_debug.py` — mirror the existing clear-refs tests.
  - `frontend/src/api/client.ts:282` (`clearSpoolmanFdbRefs`) and
    `frontend/src/pages/Settings.tsx:1229-1251` (the "Clear Spoolman cross-refs" danger-zone
    block — copy its structure, including the confirm step).

## Working tree check

`git status --porcelain` first. Tree should be clean except unrelated dotfiles. If a file
this plan touches is dirty, list it and ask. This prompt file is exempt.

## What to do

### Backend (`backend/app/api/debug.py`)

1. Add a module constant near `_XREF_EXTRAS`:
   ```python
   _OPENTAG_EXTRAS = [
       settings.spoolman_field_openprinttag_slug,
       settings.spoolman_field_openprinttag_uuid,
       settings.spoolman_field_openprinttag_ignore,
   ]
   ```
2. Add an async helper `_blank_spoolman_opentag_ids(spoolman) -> tuple[int, int, str | None]`
   mirroring `_blank_spoolman_xrefs`, but iterating **`get_filaments()`** and writing via
   **`update_filament(filament.id, {"extra": {k: blank for k in keys_to_blank}})`**. Blank =
   `encode_extra_value("")`. Only filaments with at least one of the three OpenTag extras
   actually set count as `cleared`; per-filament failures increment `failed` without
   aborting; a failed initial fetch returns `(0, 0, str(exc))`.
3. Add `POST /api/debug/clear-spoolman-opentag-ids` (response_model `ClearRefsResponse` —
   reuse it; same `{cleared, failed}` shape). Call `_require_debug_mode(db)` first; on
   helper error raise `HTTPException(502, detail=error)`; else return
   `ClearRefsResponse(cleared=..., failed=...)`. Mirror `clear_spoolman_fdb_refs` exactly.
4. Update the module docstring at the top of `debug.py` to document the new endpoint.
   (Leave `full-reset` as-is — do NOT fold OpenTag clearing into full-reset; this is a
   standalone tool.)

### Frontend

5. `frontend/src/api/client.ts`: add
   `export const clearSpoolmanOpentagIds = () => request<ClearRefsResponse>('/debug/clear-spoolman-opentag-ids', { method: 'POST' })`.
6. `frontend/src/pages/Settings.tsx`: in the Danger zone (after the "Clear Spoolman
   cross-refs" block, before "Reset bridge DB"), add a new block "Clear Spoolman OpenPrintTag
   ids (Spoolman only)":
   - State: `clearingOpentag` / `clearOpentagMsg` (mirror `clearingRefs` / `clearRefsMsg`).
   - A confirm step consistent with the cross-refs button (mirror its dialog, or a
     `window.confirm` — but it MUST confirm before firing).
   - Handler calls `clearSpoolmanOpentagIds()`, sets a result message like
     `Cleared OpenPrintTag ids on N filament(s) (M failed)`.
   - Help text: "Blanks `openprinttag_slug`, `openprinttag_uuid`, and `openprinttag_ignore`
     on every Spoolman filament that has any set. Writes to Spoolman only — does NOT touch
     the bridge DB or Filament DB. Speeds up re-running the OpenTag matcher in testing."
   - Match the existing red-button styling and the `effectiveDebugMode` gating (it's already
     inside the `{effectiveDebugMode && (...)}` block).
   - Import `clearSpoolmanOpentagIds` in the existing client import line.

### Tests

7. `backend/tests/test_debug.py`: add tests mirroring the clear-refs ones —
   - 403 when `debug_mode` is off.
   - With debug on: filaments carrying the three OpenTag extras get them blanked;
     `cleared` counts only filaments that had at least one set; filaments with none are
     skipped. Assert `update_filament` was called with the blanked extras.
   - 502 when `get_filaments` raises.
8. `frontend/src/pages/Settings.test.tsx`: if the existing tests assert on the danger-zone
   buttons, extend minimally so the new button doesn't break them. (If they don't, no change.)

## Conventions to honor

- Spoolman-only; never delete records; never write to the bridge DB or FDB here.
- Reuse `ClearRefsResponse`, `_require_debug_mode`, `encode_extra_value`. Keep it parallel to
  the existing clear-refs code.
- **Full backend suite via throwaway venv** (sandbox skips `itsdangerous`/debug tests
  otherwise): `python3 -m venv $TMPDIR/v && $TMPDIR/v/bin/pip install -q -r backend/requirements.txt &&
  cd backend && $TMPDIR/v/bin/pytest`. Confirm `test_debug.py` ran (not skipped). Then
  `ruff check backend/`, and in `frontend/` `npx tsc --noEmit` + `npm test`. All green.

## When done

1. Update frontmatter (`status`, `completed` 2026-06-13, `result`).
2. `git mv` this file to `prompts/done/` (or `prompts/failed/`).
3. Record the new debug tool in `docs/decisions.md` only if other debug tools are documented
   there; otherwise no doc change is needed (it's a debug-only convenience). If
   `docs/configuration.md` or `docs/security.md` enumerates the `/api/debug/*` endpoints,
   add this one there in the same commit.
4. Propose ONE `feat:`-prefixed commit (file list + one-liner; ask y/n). On `y`, stage those
   specific paths and commit on `dev` (never `main`, never `git add -A`, never push, no
   `Co-authored-by:`).
