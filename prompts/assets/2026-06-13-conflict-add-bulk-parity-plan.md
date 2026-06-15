# Signed-off plan — Conflict "Add" parity + imported-filament visibility

Companion to `prompts/2026-06-13-conflict-add-bulk-parity-and-filament-visibility.md`. Signed off 2026-06-13.

## LOCKED DECISIONS
- **Display data:** persist a JSON identity blob `{vendor,name,color_hex,material}` on a NEW
  nullable `FilamentMapping.identity` column (option a). Written in the SHARED wizard execute
  create sites (covers wizard + conflict-Add + engine auto-import via one path). Reuse the
  existing `engine.py` helpers `_sm_filament_identity` / `_fdb_filament_identity`. Does NOT
  touch filament snapshots (zero ping-pong risk).
- **Backfill (OQ-1):** opportunistic — when an existing `FilamentMapping.identity is None` and
  the SM/FDB filament is in hand during a sync pass, set it (self-heals the 4 legacy rows next
  cycle). `build_mapping_rows` must also degrade gracefully on NULL → name/vendor/color = None.
- **Row discriminator (OQ-3):** add `kind: Literal["spool","filament"] = "spool"` to
  `MappingRow` (+ TS). Filament-only rows are `kind="filament"`; FE hides relink/unlink for
  them. Do NOT use magic/negative ids.
- **Suggestions (OQ-2): ADD FUZZY FALLBACK** — user confirmed. Run the exact-key
  `match_filaments` first; when it yields no candidate (the common new-filament case), fall
  back to a scoped rank built from the matcher's OWN normalizers (`normalize_vendor`,
  `normalize_name`/`strip_color_and_words` for base-name, `normalize_color`): vendor-exact +
  base-name match + color closeness → score in [0,1), top ~8. NOT a new algorithm — composes
  existing normalizers.
- **Placement (OQ-4):** filament-only rows stay in Synced Records (with a subtle "filament
  only — no spool in Spoolman" hint), not a separate view.
- **single_record_import:** confirmed a thin wrapper over `_execute_spoolman_to_fdb` — NO
  drift; preserve the single create-path. Document that single-record parenting uses explicit
  `master_filamentdb_id` (no auto-cluster) in docs/conflicts.md.

## 1. Model + migration
`models/mapping.py`: add `identity: Mapped[str | None] = mapped_column(String, nullable=True)`
to `FilamentMapping`. Alembic revision `add identity to filament_mappings` (add_column,
nullable, no data migration). Hand-write upgrade/downgrade if autogen is unreliable here.

## 2. Write identity (shared path)
`wizard.py` `_execute_spoolman_to_fdb`: at the FilamentMapping create (~1584) set
`identity=json.dumps(_sm_filament_identity(item.sm_filament))`; on the elif-update branch
(~1592) backfill when currently NULL. `_execute_fdb_to_spoolman` create (~1749): set identity
from whichever side carries vendor/name/color (`_fdb_filament_identity(fdb_fil)` or the linked
SM filament). Synthetic parents (~1158/1256): leave NULL. single_record_import needs NO
separate write (delegates to the above). Add opportunistic engine backfill per OQ-1.

## 3. build_mapping_rows (`api/mappings.py:100`)
After the spool loop, add a filament-only loop:
- `spool_mapped_fm_ids = {m.filament_mapping_id for m in spool_mappings if m.filament_mapping_id}`.
- For each `fm`: skip if `is_synthetic_parent` or `spoolman_filament_id is None` or
  `fm.id in spool_mapped_fm_ids`. Else emit MappingRow with `kind="filament"`,
  spool ids/weights None, identity parsed from `fm.identity` (NULL→None), ids from fm,
  status from a NEW shared helper `filament_mapping_status(db, fm, open_conflict_fdb_ids)`
  EXTRACTED from the dashboard logic in `api/sync.py` (e14f053) and called by BOTH sync.py and
  mappings.py (no drift). `conflict_id` = first open conflict with `filamentdb_filament_id==fm.filamentdb_id`.
- Schema: loosen `MappingRow.spoolman_spool_id`→`int|None=None`, `filamentdb_spool_id`→`str|None=None`,
  add `kind`. Mirror in `frontend/src/api/types.ts`.

## 4. SyncedRecords.tsx
Filament rows mostly render already (— weights, `name ?? '—'`, DeepLinks null-handles spool id
→ falls back to SM filament link). Confirm ColorDisplay tolerates null color. For
`row.kind==='filament'`: hide/disable relink+unlink, add "filament only" hint. is_empty=false so
the hide-empty filter keeps them.

## 5. Suggestions endpoint
`GET /api/conflicts/{conflict_id}/filament-suggestions` in `api/conflicts.py`. Require
`spoolman_id` set + field_name in (new_filament,new_spool); resolve to SM filament id (for
new_spool, look up via get_spools like the import endpoint at ~391-408). Run `match_filaments`
([that SM fil], fdb_filaments) → matched/ambiguous = score 1.0; else FUZZY FALLBACK (above).
Response: `FilamentSuggestionsResponse{suggestions:[FilamentSuggestion{filamentdb_id,name,
vendor,color,material,score,is_master_container,parent_id,variant_label}]}` ranked desc, top ~8.
Reuse `_is_master_fdb` (extract to shared helper). Client: `getFilamentSuggestions(conflictId)`
in client.ts + types.

## 6. Conflict Add link UI (`Conflicts.tsx` NewRecordAddFlow)
Replace the bare 24-char field: on `filamentAction==='link'`, lazily fetch suggestions, render a
`<select>` (label `vendor · name · color (score%)`, "Master" tag) that sets `filamentdbId`;
keep a manual 24-char hex override below (takes precedence when filled, validate 24 hex).
runPreview/runExecute unchanged (post filament_action=link, filamentdb_id). "Create new" unchanged.

## 7. Tests (run FULL suite via throwaway venv — sandbox lacks itsdangerous)
`python3 -m venv $TMPDIR/v && $TMPDIR/v/bin/pip install -r backend/requirements.txt pytest pytest-asyncio`
then `$TMPDIR/v/bin/python -m pytest backend/tests`. Cases: filament-only row emitted +
identity populated; synthetic master excluded; no double-emit when spools exist; NULL identity
fallback; filament status parity with sync.py; suggestions endpoint exact + fuzzy fallback;
suggestions 400 for wrong conflict type/direction; add-link via suggestion creates mapping and
record then shows in build_mapping_rows; wizard execute + single_record_import set identity;
FE: NewRecordAddFlow dropdown+override; SyncedRecords filament-only row render. ruff + tsc + npm.

## Files
models/mapping.py, alembic/versions/*, api/mappings.py, api/conflicts.py, api/sync.py
(+ new core/filament_status.py), api/wizard.py, core/engine.py (backfill), core/single_record_import.py
(none expected), schemas/api.py, frontend: api/client.ts, api/types.ts, pages/Conflicts.tsx,
pages/SyncedRecords.tsx, docs/conflicts.md, docs/wizard.md, docs/decisions.md.
