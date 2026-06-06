---
name: 2026-06-06-conflict-screen-more-info
status: completed
created: 2026-06-06
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-06
result: Added snapshot-derived identity header (label, vendor, name, color swatch, material, SM/FDB ids) to every conflict card; backend helper + schema fields + 2 tests; tsc + build clean.
---

# Task: Show more identifying info on each Conflict card

The Conflicts screen currently shows only the entity type, a generic title ("Record
deleted upstream" / the field name), and the detected time — you can't tell *which*
filament/spool a conflict is about without clicking the deep-link icons. Enrich each
conflict with identifying info: vendor + name + color (swatch + hex), material, the
Spoolman spool id, and the FDB filament/spool ids — sourced from the bridge's snapshots.

## Before you start

- Read `CLAUDE.md`. Work on `dev`, `feat:` commit, no `Co-authored-by:`.
- The `Conflict` model carries: `entity_type` ("spool"|"filament"), `spoolman_id`,
  `filamentdb_filament_id`, `filamentdb_spool_id`, `field_name`, `spoolman_value`,
  `filamentdb_value`. The API shapes it via `_to_response` in
  `backend/app/api/conflicts.py`; the schema is `ConflictResponse`
  (`backend/app/schemas/api.py` ~104-118). The frontend renders cards in
  `frontend/src/pages/Conflicts.tsx` (`ResolveRow` + the resolved-tab card).
- Identifying data lives in the bridge `snapshots` table (the same data the
  SyncedRecords page already reads). For a **spool** conflict, the Spoolman spool snapshot
  (`source="spoolman", entity_type="spool", entity_id=str(spoolman_id)`) has nested
  `filament.name`, `filament.vendor.name`, `filament.color_hex`, `filament.material`. For a
  **filament** conflict, the Spoolman filament snapshot
  (`source="spoolman", entity_type="filament", entity_id=str(spoolman_id)`) has
  `name`, `vendor.name`, `color_hex`, `material`. Look at how `build_mapping_rows` /
  `_snapshot` in `backend/app/api/mappings.py` read snapshots and reuse that pattern.

## What to do

### Backend
- Add identifying fields to `ConflictResponse`: `label: str | None` (e.g.
  "ELEGOO Beige"), `vendor: str | None`, `name: str | None`, `color_hex: str | None`,
  `material: str | None`. (The ids — `spoolman_id`, `filamentdb_filament_id`,
  `filamentdb_spool_id` — are already present; keep them.)
- In `conflicts.py`, add a helper `_conflict_identity(db, c)` that loads the relevant
  Spoolman snapshot (spool snapshot for `entity_type=="spool"`, filament snapshot for
  `"filament"`), parses `name`/`vendor`/`color_hex`/`material`, and returns them plus a
  composed `label` (`"{vendor} {name}".strip()` falling back to `f"SM #{spoolman_id}"`).
  Tolerate a missing snapshot (all None / id-based label). Wire it into `_to_response`
  (pass `db`).

### Frontend (`Conflicts.tsx`)
- On each conflict card (both the open `ResolveRow` and the resolved card), add a compact
  identity header: a color swatch (reuse/port the `ColorSwatch` pattern from
  `StepVariances.tsx`) + the `label`, with small muted chips for `material`, the hex,
  the **SM spool id** (`spoolman_id`), the **FDB filament id**, and (if present) the **FDB
  spool id**. Keep the existing deep-link icons and the resolve controls.
- Keep the deletion-conflict amber banner and the field-conflict value diff (Spoolman vs
  Filament DB) as they are — just add the identity header above them so you can tell what
  record it is at a glance.
- Update `frontend/src/api/types.ts` `ConflictResponse` with the new fields.

## Conventions to honor

- `feat:` commit, `dev`, no `Co-authored-by:`, docs in same commit if any.
- Read-only enrichment — do not change conflict detection/resolution logic.

## Verification

- `cd backend && pytest` — add a test: a spool conflict whose Spoolman spool snapshot
  exists returns `label`/`vendor`/`name`/`color_hex`/`material` populated; a conflict with
  no snapshot returns a graceful id-based label and null fields.
- `cd frontend && npx tsc --noEmit && npm run build` — must pass.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md`: conflict cards now carry snapshot-derived identity (label, vendor,
   name, color, material, ids) — only if non-obvious.
3. Non-interactive subagent run: when pytest + tsc + build pass, stage ONLY the files this
   task touched (incl. prompt move + docs) and commit on `dev` with one `feat:` message.
   Never `git add -A`. Never push.
