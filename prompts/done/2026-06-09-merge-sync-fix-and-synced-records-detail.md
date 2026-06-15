---
name: 2026-06-09-merge-sync-fix-and-synced-records-detail
status: completed
created: 2026-06-09
completed: 2026-06-10
model: opus
plan_stage_done: 2026-06-09
result: >
  Executed Stage 2. PLUS fixed an urgent production bug reported mid-execution: a runaway,
  compounding weight-decrement loop in two-way sync (commit 32545b9) — root cause = FDB reduces
  totalWeight on usage logging so fdb_to_spoolman_net's usageHistory subtraction double-counted,
  compounded by one-sided snapshot refresh causing a ping-pong; verified FDB usage semantics live.
  Task B (bed/nozzle temp two-way sync via new _sync_material_props pass, commit 019bf94). Task A
  (expandable Synced Records detail rows, commit b6bce4c). All pytest green (the 6 itsdangerous
  failures are a pre-existing env gap); frontend builds; FDB temperature/usage write paths verified
  against the live :3000 stack. CLAUDE.md weight model corrected; decisions.md updated.
---

# Two tasks: (B) fix two-way material-property merge sync, (A) Synced Records expandable detail

User is asleep; will NOT approve anything. Execute both autonomously. Test against the
**already-running local dev stack** (do NOT tear it down) or the pytest sandbox.
Local endpoints (verified up 2026-06-09): bridge `localhost:8090`, Spoolman `localhost:7912`,
Filament DB `localhost:3000`, mongo internal. Docker CLI needs `dangerouslyDisableSandbox: true`
(user is in the `docker` group but the command sandbox blocks the socket). pytest runs fine in-sandbox.
Container data is all test data — safe to mutate.

Standards: branch `dev`, never `main`, never push unless asked. Conventional-commit prefixes.
Doc/CHANGELOG updates ship in the same commit. No `Co-authored-by:`. See [[new-install-defaults-no-clobber]]
and [[workflow-inline-vs-prompt]].

---

## TASK B — Two-way / merge material-property sync bug (PRIORITY: production bug)

### Symptom
Spools synced SM→FDB fine (initial import). Every category set to MERGE / two_way. User edits
**bed temp in Filament DB** → it NEVER reaches Spoolman, despite two-way sync.

### Root cause (confirmed by code trace — the resolver is NOT the bug)
`core/sync_policy.resolve_sync_action` is correct and symmetric (test_sync_policy covers
`test_two_way_lone_fdb_change_propagates` → PUSH_FDB_TO_SM). The change never *reaches* the
resolver for bed temp. Three defects:

- **H1 (primary):** The only ongoing-sync mapper, `core/fields.py:resolve_field_map`, auto-matches
  Spoolman **extra-field keys** to identically-named FDB fields (`fields.py:70-74`). Bed temp is FDB
  dotted `temperatures.bed` (`fields.py:26`) ↔ Spoolman **native filament** field `settings_bed_temp`
  (`schemas/spoolman.py:56`). Name mismatch + native-vs-extra mismatch → no `FieldMapping` is ever
  produced → `differ.py:96-126` (iterates only `field_maps`) never sees it → no FDB→SM write. The
  wizard's initial import works only because it uses a SEPARATE hard-coded map
  (`wizard.py:885`, `planner.py:180-181`: `bed_temp -> ("temperatures.bed","settings_bed_temp")`)
  that the engine does NOT share.
- **H2:** Even if mapped, `engine.py:_apply_field_changes` PUSH_FDB_TO_SM always writes to the
  **spool** `extra` bag: `spoolman.update_spool(id, {"extra": {fm.sm_key: ...}})` (engine.py ~556).
  Bed temp is a filament-level NATIVE field. So an explicit env mapping would still write the wrong
  target. The FDB→SM write for these must be `spoolman.update_filament(sm_fil_id, {"settings_bed_temp": v})`.
- **H3:** `_fdb_snapshot_dict(fdb_spool)` is called WITHOUT `filament_detail`/`field_maps` at
  engine.py:1806, 1963, 1998 → the `_field_values` block (engine.py:362-368) is never persisted →
  `differ.py:94` always reads `{}` → FDB-side change detection for dotted/mapped fields is unreliable.

### Material-property field set + bed-temp representation
Category "material_properties" (routed via `material_properties_sync_direction` /
`_conflict_policy`) covers the mapped scalars/dotted fields in `fields.py:17-31` plus dedicated
passes `_sync_multicolor`, `_sync_cost`, `_sync_finish_tags`.
- Bed temp: FDB `temperatures.bed` ↔ SM native filament `settings_bed_temp`.
- Nozzle temp: FDB `temperatures.nozzle` ↔ SM native filament `settings_extruder_temp`.

### Fix (preferred design — mirror the working `_sync_cost` pass)
Add a dedicated **`_sync_material_props`** pass in `engine.py`, parallel to `_sync_cost` /
`_sync_multicolor`, iterating **filament mappings** (these are filament-level NATIVE fields, not
spool extras):
1. Built-in canonical map of `(fdb_path, sm_native_field)` pairs. Reuse/centralize the wizard pairs
   (move `_RECONCILE_FIELD_MAP` or define in `core/fields.py`). Minimum set to wire now:
   `temperatures.bed=settings_bed_temp`, `temperatures.nozzle=settings_extruder_temp`. Consider also
   `temperatures.bedFirstLayer`, `temperatures.nozzleFirstLayer` if SM has native equivalents (check
   `SpoolmanFilament` schema — only add pairs that exist on both sides; do NOT invent fields).
2. For each filament pair, read FDB value via `get_fdb_field_value(detail, path)` and SM native value
   off the snapshot/live filament. Maintain a **per-field snapshot baseline** like `_sync_cost`
   (`_get_snapshot`/`_merge_snapshot`) so a lone-side change is detectable and "both changed into
   agreement" refreshes baseline silently.
3. Resolve with `resolve_sync_action(direction=matprop_direction, policy=matprop_policy)`.
   - PUSH_FDB_TO_SM → `spoolman.update_filament(sm_fil_id, {"<sm_native_field>": value})` (native! on filament)
   - PUSH_SM_TO_FDB → `filamentdb.update_filament(fdb_id, {"temperatures": {"bed": value}})` (nested merge — confirm FDB PUT accepts partial temperatures; if it replaces the whole object, read-modify-write the temperatures dict)
   - CONFLICT (merge, both changed, disagree) → queue a conflict, never auto-resolve (hard rule).
4. Log every action to SyncLog like the other passes. Respect "never delete".

NOTE: also fix H3 — thread `filament_detail`+`field_maps` into the three `_fdb_snapshot_dict` calls
so `_field_values` persists (needed for other mapped fields AND for Task A's FDB-side detail).
If `_sync_material_props` owns temps with its own baseline, H3 is lower-risk but still a latent bug —
fix it.

### Full test pass on "merging functions" (pytest — primary, deterministic)
IMPORTANT: existing engine tests stub `resolve_field_map` → `[]`, so `_apply_field_changes` is never
exercised. Do NOT stub the new pass to empty. Add `backend/tests/test_material_props_sync.py` (or
extend test_engine) covering, with mocked spoolman/filamentdb clients:
- FDB-only bed-temp change, two_way + merge → asserts `spoolman.update_filament(.., {"settings_bed_temp": ..})` called.
- SM-only change, two_way + merge → asserts `filamentdb.update_filament(.., {"temperatures": {"bed": ..}})`.
- Both changed, disagree, merge → conflict queued, no upstream write.
- Both changed into agreement → baseline refreshed, no write, no conflict.
- First sight (no baseline) → baseline stored, no spurious write.
- direction=filamentdb_to_spoolman → FDB change propagates, SM change does NOT (and vice versa for spoolman_to_filamentdb).
- Nozzle temp same matrix (at least the FDB→SM case).
- Regression: re-run full `test_sync_policy`, `test_engine`, `test_differ`, `test_fields`.
Also exercise: `resolve_sync_action`, the new `_sync_material_props`, `differ` with populated
`_field_values`, snapshot round-trip of `_field_values`.

### Live e2e validation (secondary — against running docker stack)
Reproduce the user's exact scenario end-to-end:
1. Ensure a filament pair is synced (or sync one SM→FDB). Set material_properties to two_way + merge
   via the bridge config (Settings API / config endpoint).
2. Change bed temp in Filament DB (`PUT /api/filaments/:id` at :3000 with new `temperatures.bed`).
3. Trigger a sync cycle (bridge `POST /api/sync/run` or wait for interval) and confirm Spoolman
   filament `settings_bed_temp` updated (`GET :7912/api/v1/filament/{id}`).
4. Confirm the reverse (SM change → FDB) and the conflict case.
Bridge API likely needs auth — check docker-compose.dev.yml for `AUTH_ENABLED`; if on, use the API
token or temporarily set AUTH_ENABLED=false. Hitting Spoolman/FDB directly needs no auth.

---

## TASK A — Synced Records expandable detail rows
Expand each row to show, in small neat font, the per-side values (Spoolman vs Filament DB) for the
things we sync. **All collapsed by default.**

### Mirror the Conflicts.tsx pattern (house style)
`frontend/src/pages/Conflicts.tsx`: `expandedIds: Set<number>` state + `toggleExpand` (clone Set)
(:304,338-345), Expand-all/Collapse-all buttons shown when >1 row (:347-353,461-477), `▾` chevron
with `transition-transform ${expanded?'rotate-180':''}` `text-gray-400 dark:text-gray-500` (:270-272),
`e.stopPropagation()` on interactive header children. Expanded body = side-by-side grid (:99-113):
Spoolman = **emerald** (`bg-emerald-50 dark:bg-emerald-900/20`, `text-emerald-700 dark:text-emerald-400`),
Filament DB = **blue** (`bg-blue-50 dark:bg-blue-900/20`, `text-blue-700 dark:text-blue-400`). Values
`font-mono text-xs`, null → `—` in `text-gray-400 dark:text-gray-500`. Divider `border-t border-gray-100 dark:border-gray-700`.

### Keep the table; add an expand row
`frontend/src/pages/SyncedRecords.tsx` is a `<table>` (rows :112-148). Add a leading chevron cell +
on expand render a second full-width `<tr><td colSpan={N}>` holding the detail grid. Add expand state
+ Expand/Collapse-all controls copied from Conflicts. Match dark-mode classes already in the file.

### Backend: extend the mappings payload (Option B — symmetric detail)
`backend/app/api/mappings.py:build_mapping_rows` already loads both snapshots. Project a `detail`
object per row:
- **Spoolman side (fully available in snapshot):** from the nested `filament` block of `sm_snap`
  (`SpoolmanFilament`, schemas/spoolman.py:40-61): material/type, density, diameter,
  `settings_extruder_temp`, `settings_bed_temp`, color_hex, spool_weight + `remaining_weight` (net).
- **Filament DB side:** from `fdb_snap` (`totalWeight` gross, label, retired) PLUS
  `fdb_snap.get("_field_values")` once H3 persists it. Until a sync cycle backfills `_field_values`,
  FDB material props render `—` (acceptable; note it).
Add optional nested model to `MappingRow` (`schemas/api.py:153-172`), e.g. `detail: MappingDetail|None`
with a typed list of `{field, label, spoolman, filamentdb}` rows (mirror `OpenTagFieldRow` shape so
the frontend grid is trivial). Keep optional — don't break existing callers.
Frontend: extend `MappingRow` in `frontend/src/api/types.ts:153-173` (+ a `MappingDetail` interface);
`getMappings` endpoint unchanged.

Fields to show in the detail (only those the bridge syncs): weight (net SM / gross FDB), material/type,
bed temp, nozzle temp, density, diameter, color, plus the cross-ref IDs. Use the canonical pairs from
Task B so the two features stay consistent.

### Test
- Backend: extend `test_api.py` mappings test to assert `detail` is populated from snapshots
  (SM side present; FDB side present when `_field_values` exists, `—`/null otherwise).
- Frontend: `npm run build` clean. Manual: collapsed by default, expand shows both sides, dark mode OK.

---

## Execution order & wrap-up
1. Task B fix + pytest pass (priority; it's the prod bug). 2. Task B live e2e against docker.
3. Task A backend + frontend + tests. 4. `cd backend && ruff check . && python3 -m pytest`
   (note: 2 pre-existing failures from missing `itsdangerous` in this env are unrelated).
   `cd frontend && npm run build`. 5. Update CHANGELOG `[Unreleased]` (Fixed: two-way material
   property sync; Added: Synced Records expandable detail). Update CLAUDE.md only if a setting/field
   changes. 6. Commit to `dev` in focused commits (`fix:` for B, `feat:` for A). Do NOT push.
7. Log non-obvious decisions in `docs/decisions.md`. Move this file to `prompts/done/` and set
   frontmatter `status: completed` with a result summary. 8. Report: root cause, fix, test results
   (pytest + live e2e), files changed, proposed commit messages — leave the rest for the user to review.
