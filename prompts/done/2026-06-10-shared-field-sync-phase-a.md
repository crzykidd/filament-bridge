---
name: 2026-06-10-shared-field-sync-phase-a
status: completed        # pending | completed | failed
created: 2026-06-10
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-10
result: Added _sync_material_scalars pass (material/density/diameter/spool_weight/weight), conflict_type column + master_divergence conflicts, fixed _build_detail display, tests in test_engine_scalars.py, updated prd.md/spoolman-writes.md/decisions.md
---

# Task: Phase A — sync native shared filament fields, honest Synced Records display, queue master-divergence (record-only)

The bridge syncs weight, cost, temperatures, color/multicolor, and finish tags — but the
native Spoolman filament fields with a direct Filament DB counterpart are **not synced at
all**: `material`, `density`, `diameter`, `spool_weight`, `weight`. The generic FR-11
mapper only matches Spoolman *extra* fields by name; native fields are invisible to it, and
`_sync_material_props` only covers bed/nozzle temperature.

Phase A: (1) sync those five native fields under the existing two-axis `material_properties`
direction+policy; (2) fix the Synced Records detail view, which hardcodes the Filament DB
column to `None` for material/density/diameter/color; (3) where a Spoolman→FDB write would
set a value on a variant that **diverges from its master's inherited value**, do **not**
silently override — queue a new `master_divergence` conflict (record-only this phase). The
approval workflow that resolves those is **Phase B** (separate prompt).

## Before you start

- Read `CLAUDE.md` (weight model, master/variant model, "What NOT to do") and `docs/prd.md`
  FR-11 (field mapping) + FR-13/FR-16 (conflicts) + FR-19 (Synced Records).
- Read `docs/decisions.md` — the `should_skip_inherited` rule and the conflict
  "resolve = record, apply next cycle" note. This task revises the inherited-field rule
  (see below); log the revision.
- Standards: `code-checkin-and-pr` (work on `dev`, Conventional-Commits prefix, docs in the
  same commit, no `Co-authored-by:`).

## Key design facts (verified — do not re-litigate)

1. **Master/variant.** A filament line splits into a **master/parent** (shared physical
   props: `type`, `density`, `diameter`, `temperatures`, `spoolWeight`,
   `netFilamentWeight`) and **color variants** (children via `parentId`, holding
   `color`/`secondaryColors`/`cost`/their own spools). `GET /api/filaments/:id`
   server-resolves inheritance; `_inherited[]` (the `FDBFilamentDetail.inherited_fields`
   list, aliased from `_inherited`) names which **top-level** fields are currently inherited.

2. **Overriding a field does NOT detach the variant.** Confirmed against the FDB API spec:
   setting a field on a variant creates a per-variant override and drops just that field
   from `_inherited[]`; `parentId` is retained and all other fields keep inheriting. A
   variant only becomes standalone by explicitly clearing `parentId`. So a field override
   is a pure field-level write — it never restructures the hierarchy, never invokes the
   wizard's `variant_parent_mode` rules, never creates a record.

3. **Spoolman is flat: one filament per color → maps 1:1 to one FDB record** (`filamentdb_id`,
   usually a variant). There is no fan-in. The temp pass (`engine.py:1122` `_sync_material_props`)
   already reads the resolved FDB value and writes it straight to the mapped variant — model
   the new native-scalar work on it and on `_sync_cost`.

## Field correspondence (all filament-level)

| Spoolman field | FDB field (`fdb_path`) | Notes |
|---|---|---|
| `material` | `type` | name remap (string) |
| `density` | `density` | float |
| `diameter` | `diameter` | float |
| `spool_weight` | `spoolWeight` | tare; float |
| `weight` | `netFilamentWeight` | net filament; float |

Do **not** touch `color_hex` (owned by `_sync_multicolor`), `price`/`cost` (`_sync_cost`),
temps (existing temp pass), or `name`/`vendor`. `article_number`/`comment` have no FDB
counterpart — out of scope.

## What to do

### 1. Engine — native scalar sync pass

Add `MATERIAL_PROP_SCALAR_PAIRS: list[tuple[str, str, str, callable]]` of
`(label, fdb_path, sm_field, normalizer)` and a sibling loop inside `_sync_material_props`
(or a parallel `_sync_material_scalars` helper invoked from the same call site, ~`engine.py:2288`).
Reuse the temp loop's diff/route machinery exactly:

- Per-field baseline keyed `_mp_<sm_field>` per side via `_merge_snapshot` (coexists with
  temp/cost/`_mc_sig` keys). Store the **resolved** FDB value on the FDB side.
- First-sight → store baseline, no write. Both-changed-into-agreement → refresh silently.
- Route each change through `resolve_sync_action(sm_changed, fdb_changed,
  direction=matprop_direction, policy=matprop_policy)`.
- Normalizer per field to avoid float-jitter false diffs (mirror `_norm_temp`; for strings,
  trim/normalize; for floats, round to a sensible precision).

**PUSH_FDB_TO_SM:** `await spoolman.update_filament(m.spoolman_filament_id, {sm_field: fdb_now})`.
The FDB side has no master concern here.

**PUSH_SM_TO_FDB — the master/variant gate (the revised inherited-field rule):**
Let `resolved = get_fdb_field_value(fdb_fil, fdb_path)`, `top = fdb_path.split(".")[0]`,
`inherited = top in fdb_fil.inherited_fields`, `has_parent = fdb_fil.parentId is not None`.
- **Standalone (`not has_parent`) OR field already overridden (`not inherited`):** write
  directly — `await filamentdb.update_filament(m.filamentdb_id, {fdb_path: sm_now})`
  (for `material`, `fdb_path` is `type`). Store baseline, log update.
- **Inherited AND `sm_now == resolved`:** skip — value already matches the master, leave it
  inherited (no redundant override). Log a `skip` with reason
  `"matches inherited master — left inherited"`.
- **Inherited AND `sm_now != resolved`:** **do NOT write.** Queue a `master_divergence`
  conflict (see §2) with dedup, then continue. (Resolution = Phase B.)

This is the deliberate softening of the old blanket `should_skip_inherited` rule: we override
on genuine divergence (via approval, Phase B) instead of always skipping; and we don't stamp
redundant overrides. Leave the FR-11 generic mapper's `should_skip_inherited` usage in
`_apply_field_changes` UNCHANGED — this task adds a dedicated pass, it does not rework the
extra-field mapper.

### 2. Conflict model — add `conflict_type`, queue master_divergence (record-only)

- Add a `conflict_type` column to `models/conflict.py` (`String`, not null, server/default
  `"cross_system"`). Alembic migration (`alembic revision --autogenerate`); existing rows
  default to `cross_system`. Leave the existing deletion sentinel (`DELETION_FIELD`) logic
  as-is.
- Extend the `_queue_conflict` helper (in `engine.py`) to accept `conflict_type="cross_system"`
  and persist it.
- For a master-divergence: `entity_type="filament"`, `spoolman_id=<sm filament id>`,
  `filamentdb_filament_id=<variant id>`, `field_name=<label, e.g. "density">`,
  `spoolman_value=<incoming sm_now>`, `filamentdb_value=<resolved master value>`,
  `conflict_type="master_divergence"`. Dedup via `_has_open_conflict` (extend it to match on
  `conflict_type` + field + ids so a cross-system and a divergence conflict on the same pair
  don't collide).
- Surface `conflict_type` in `ConflictResponse` (schemas/api.py) and `_to_response`
  (`api/conflicts.py`). **Do not** add resolution actions here — resolving a
  `master_divergence` via the existing endpoint records-only (no apply); Phase B owns the
  apply workflow. (Optionally render these distinctly in the Conflicts list, but full UI is B.)

### 3. Snapshot storage for the display

The new pass already stores `_mp_<sm_field>` (resolved value) in the **FDB filament snapshot**.
For color: if the FDB resolved color hex isn't already persisted in the FDB filament snapshot
by `_sync_multicolor`, add a minimal `_merge_snapshot` of the resolved color hex (e.g. key
`_mc_color`) in that pass so the display can read it.

### 4. Synced Records display fix (`api/mappings.py:_build_detail`)

Replace the hardcoded `filamentdb=None` for `material`/`density`/`diameter`/`color` with the
real FDB snapshot values:
- `material` → `fdb_fil.get("_mp_material")`
- `density`  → `fdb_fil.get("_mp_density")`
- `diameter` → `fdb_fil.get("_mp_diameter")`
- `color`    → the FDB color key from §3 (`fdb_fil.get("_mc_color")` or the existing key)

Keep weight/temp/cost/bed/nozzle rows. Update the docstring.

### 5. Tests (`backend && pytest`)

Cover the new pass: standalone write, already-overridden write, redundant-skip
(matches inherited), divergence → `master_divergence` queued (no write), `material→type`
remap, FDB→SM write, conflict under `manual` policy, first-sight baseline. Plus `_build_detail`
returns real FDB values (snapshot fixture with `_mp_*`). Mirror existing temp/cost pass tests.

## Conventions to honor

- Match existing pass structure exactly (snapshot keys, `_log` audit entries, result counters,
  dry-run `result.preview` shape).
- Two-axis policy only — never auto-resolve a conflict; divergences queue, not overwrite.
- No writes to the FDB `settings{}` bag. No new env vars.
- Update `docs/prd.md` FR-11 and `docs/spoolman-writes.md` to list the newly-synced fields,
  in the **same commit** as the code.

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/`.
3. Record in `docs/decisions.md`: (a) native shared-field sync + 1:1 variant-direct routing
   (no fan-in); (b) revision of the blanket `should_skip_inherited` rule → "override on
   divergence via approval, skip only when redundant with inherited master"; (c) the new
   `conflict_type` column + `master_divergence` conflicts are record-only pending Phase B.
4. Propose ONE commit (`feat:` prefix) covering all modified files incl. the prompt move and
   doc updates. Present the file list + one-line message; ask before committing. Work on
   `dev`, never `main`. No `git add -A`. No push.
