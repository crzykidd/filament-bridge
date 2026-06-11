---
name: 2026-06-10-shared-field-sync-phase-b-master-divergence
status: completed        # pending | completed | failed
created: 2026-06-10
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-10
result: resolve→apply workflow for master_divergence: 3 actions (apply_all/variant_override/ignore), snapshot refresh, sibling auto-resolve, divergence-context endpoint, specialized UI card; 25 backend + 10 frontend tests passing
---

# Task: Phase B — master-divergence resolution workflow (resolve → apply, with three actions)

**Depends on Phase A** (`prompts/done/2026-06-10-shared-field-sync-phase-a.md`), which adds
the `conflict_type` column and queues `master_divergence` conflicts (record-only) when a
Spoolman→FDB sync would set a master-level field on a variant to a value that diverges from
its master's inherited value.

Phase B builds the approval workflow that resolves those conflicts and actually writes
upstream. Today the conflict resolve endpoint is **record-only** — `api/conflicts.py` states
"This router performs no upstream writes." Phase B implements the long-deferred resolve→apply
path, scoped to `master_divergence` conflicts, with three resolution actions.

## Before you start

- Read Phase A's `docs/decisions.md` entry and the `master_divergence` conflict shape it
  defines (field, variant id, incoming Spoolman value, resolved master value, `conflict_type`).
- Read `api/conflicts.py` (current record-only resolve / bulk-resolve), `core/engine.py`
  weight-propagation snapshot-refresh pattern (so applies don't ping-pong), and
  `services/filamentdb.py` + `services/spoolman.py` (the async clients + how the sync API
  endpoints inject them).
- Read `CLAUDE.md` master/variant model and the hard rule: conflicts are never auto-resolved
  (this is human-approved resolution — allowed; silent auto-apply is not).
- Standards: `code-checkin-and-pr`.

## The three resolution actions (user-confirmed)

For a `master_divergence` conflict on field F, variant V (mapped Spoolman filament S), value
`new` (the incoming Spoolman value), master M = V's `parentId`:

| Action | Filament DB | Spoolman |
|---|---|---|
| **`apply_all`** | Write `new` to the master M (`update_filament(M, {fdb_path: new})`). For any variant in the line that has its **own override** of F, overwrite it to `new` too so the whole line is uniform (list these). | Write `new` to **every** Spoolman filament mapped to a variant in the line. |
| **`variant_override`** | Write `new` as a per-variant override on V only (`update_filament(V, {fdb_path: new})`). Master + siblings untouched. | No change (S is the source of `new`). |
| **`ignore`** | No write; V stays inheriting M. | No write. Store `_mp_<sm_field>` baseline = current values both sides so it won't re-queue. |

`fdb_path` for `material` is `type`; others are same-name (`density`/`diameter`/`spoolWeight`/`netFilamentWeight`).

## What to do

### 1. Make conflict resolution able to write upstream (async + clients)

The resolve endpoint must perform upstream writes for `master_divergence`. Convert
`POST /conflicts/{id}/resolve` to `async def` and inject `SpoolmanClient` + `FilamentDBClient`
the same way the sync endpoints (`api/sync.py`) do. Keep existing `spoolman`/`filamentdb`/`manual`
resolution for **other** conflict types behaving exactly as today (record-only). Branch on
`conflict_type`.

Put the apply logic in a dedicated `core/conflict_apply.py` (testable, async), called from the
router. Reuse engine helpers where sensible (`_merge_snapshot`, `_log`, sync_log writes).

### 2. Resolution request schema

Extend `ConflictResolveRequest` (schemas/api.py) with an optional `action: Literal["apply_all",
"variant_override", "ignore"] | None`. For `master_divergence` conflicts `action` is required
(422 if missing); for other types it's ignored. Validate that the conflict is open and is a
`master_divergence` before applying an `action`.

### 3. Apply logic (`core/conflict_apply.py`)

Resolve the line live to avoid stale data:
- Fetch V (`GET /api/filaments/:V`) → `parentId` = M.
- Enumerate the line's variants: M's `_variants` (from `GET /api/filaments/:M`), or list
  filaments with `parentId == M`, plus M itself if relevant. Map each variant id → its
  `SpoolMapping`/`FilamentMapping` to find the paired Spoolman filament id.

**`apply_all`:**
- `await filamentdb.update_filament(M, {fdb_path: new})`.
- For each variant with its own override of F (F not in that variant's `_inherited`), also
  `update_filament(variant, {fdb_path: new})`.
- For each mapped Spoolman filament in the line, `await spoolman.update_filament(sid, {sm_field: new})`.
- **Refresh `_mp_<sm_field>` snapshots on BOTH sides for every touched record to the agreed
  `new` value** (mirror the engine's post-weight-write snapshot refresh — otherwise next cycle
  re-detects and re-queues). 
- Auto-resolve any other open `master_divergence` conflicts for the **same field + same line**
  (they're now satisfied). Mark this conflict resolved with `resolution="apply_all"`,
  `resolved_value=new`.

**`variant_override`:**
- `await filamentdb.update_filament(V, {fdb_path: new})`.
- Refresh `_mp_<sm_field>` snapshots for V + S to `new`.
- Resolve this conflict (`resolution="variant_override"`). Siblings untouched.

**`ignore`:**
- No upstream writes. Store `_mp_<sm_field>` baseline = current resolved values on both sides
  for V/S so the divergence won't immediately re-queue. Resolve (`resolution="ignore"`).

All writes log to `sync_log` (action update, direction, field_name). Never touch `settings{}`.
Wrap each upstream call; on failure, log an error sync_log entry and surface a 502-style
`api_error` without marking the conflict resolved.

### 4. Divergence context for the UI

Add `GET /conflicts/{id}/divergence-context` (only valid for `master_divergence`) returning:
master id + name + current value of F; and the list of line variants
`[{fdb_id, name, color_hex, spoolman_filament_id, current_value, inherited: bool}]`. Fetch live
from FDB and join to mappings/snapshots. This powers the "lists them" requirement.

### 5. Frontend (`frontend/src/pages/Conflicts.tsx` + api wrapper)

For conflicts with `conflict_type === "master_divergence"`, render a specialized card:
- Header: field, variant name/color, **incoming value vs master value**.
- Fetch and show the divergence-context variant list (each variant, its current value,
  inherited vs overridden, both deep-link icons per the DeepLinks convention).
- Three buttons → resolve with the matching `action`:
  - **"Apply to all variants"** (`apply_all`) — with a confirm summarizing how many FDB +
    Spoolman records will change.
  - **"Make this variant's own setting"** (`variant_override`).
  - **"Ignore"** (`ignore`).
- After resolution, refresh the queue (sibling conflicts may have auto-cleared).
Other conflict types keep their existing resolution UI unchanged.

### 6. Tests

- Backend: each action's upstream writes (assert the right `update_filament` calls on both
  clients), snapshot refresh prevents re-detection, `apply_all` auto-resolves sibling
  same-field/same-line divergences, `ignore` baseline suppresses re-queue, `material→type`
  remap, async endpoint wiring, 422 when `action` missing for divergence / ignored for other
  types, upstream-failure path doesn't resolve the conflict.
- Frontend: divergence card renders, three actions call the endpoint with the right `action`.

## Conventions to honor

- Human-approved resolution only — no silent auto-apply. Other conflict types stay record-only.
- Post-write snapshot refresh on every touched record (anti-ping-pong), matching the engine's
  weight pattern.
- No `settings{}` writes. No new env vars. Deep links via the shared `DeepLinks` component.

## When done

1. Update frontmatter: `status`, `completed`, `result`.
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/`.
3. Record in `docs/decisions.md`: the resolve→apply mechanism (scoped to `master_divergence`),
   the three actions and their write semantics, and the snapshot-refresh anti-ping-pong note.
4. Propose ONE commit (`feat:` prefix) covering all modified files incl. the prompt move and
   doc updates. Present file list + one-line message; ask before committing. Work on `dev`,
   never `main`. No `git add -A`. No push.
