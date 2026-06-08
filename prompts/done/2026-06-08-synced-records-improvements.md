---
name: 2026-06-08-synced-records-improvements
status: done
created: 2026-06-08
model: sonnet
completed: 2026-06-07
result: All four improvements implemented and verified. Backend: MappingRow gains multi_color_hexes, multi_color_direction, remaining_weight, is_empty, conflict_id; build_mapping_rows populates them. Frontend: hide-empty toggle, ColorDisplay, conflict status badge links to /conflicts, per-filter empty-state messages. 703 backend tests pass; frontend tsc + build clean.
---

# Task: Synced Records — hide empty spools, multicolor color, link conflicts, fix Unlinked

Improve the Synced Records page (`frontend/src/pages/SyncedRecords.tsx`,
`backend/app/api/mappings.py`).

## Backend (`mappings.py` + `MappingRow` in `schemas/api.py`)

`build_mapping_rows` builds rows from spool mappings + snapshots. Add to `MappingRow`:
- `multi_color_hexes: str | None`, `multi_color_direction: str | None` — from the Spoolman
  filament snapshot (so multicolor records can show a swatch instead of blank `color`).
- `remaining_weight: float | None` (or an `is_empty: bool`) — from the Spoolman spool snapshot,
  so the UI can hide empty/depleted spools (remaining ≈ 0).
- `conflict_id: int | None` — for a row whose status is `conflict`, the id of the open Conflict
  that references this spool (you already index open conflicts by spool id in
  `build_mapping_rows`), so the UI can deep-link to it.
Default all to None. Keep the existing `status` logic (conflict / unlinked / in_sync).

## Frontend (`SyncedRecords.tsx`)

- **Hide empty spools**: add a "Hide empty spools" toggle that filters out rows where remaining
  weight ≈ 0 (`is_empty`). Default OFF.
- **Multicolor color**: replace the plain `{row.color}` cell with the shared `<ColorDisplay>`
  component (created earlier — `frontend/src/components/ColorDisplay.tsx`), passing
  `colorHex`/`multiColorHexes`/`multiColorDirection` so multicolor shows a gradient/coaxial
  swatch + label instead of `—`.
- **Link conflicts**: for a row with `status === 'conflict'`, make the status badge (or an
  icon) link to the Conflicts page for that record (e.g. route to `/conflicts` — if a
  per-conflict anchor/filter is easy via `conflict_id`, use it; otherwise just navigate to
  `/conflicts`). Keep it simple.
- **Unlinked**: the `unlinked` filter currently shows nothing because `unlinked` means "a
  paired spool whose mapping has no parent filament mapping" — verify that status is actually
  being computed in `build_mapping_rows`, and if a filter yields no rows, render a clear
  empty-state message ("No unlinked records") instead of a blank table. (If the status is never
  set due to a bug, fix the computation.)
- Keep the existing status filter + search + `formatLocal` timestamps.

## Verification

- `cd backend && pytest` — test: `MappingRow`/`build_mapping_rows` includes
  multi_color_hexes/direction, remaining_weight (or is_empty), and conflict_id (set for a
  conflict-status row, None otherwise).
- `cd frontend && npx tsc --noEmit && npm run build`.
- Reason through: empty spools hide on toggle; a multicolor record shows a swatch+label; a
  conflict row links to Conflicts; each filter (incl. Unlinked) shows either rows or a clear
  empty-state.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. No docs/decisions entry needed unless non-obvious.
3. Non-interactive subagent run: when pytest + build pass, stage ONLY the files this task
   touched (incl. prompt move) and commit on `dev` with one `feat:` message. Never `git add -A`.
   Never push.
