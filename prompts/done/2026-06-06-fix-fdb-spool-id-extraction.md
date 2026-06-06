---
name: 2026-06-06-fix-fdb-spool-id-extraction
status: completed
created: 2026-06-06
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-06
result: extract_created_spool_id added; both wizard.py + engine.py call sites fixed; 10 new tests; 372 passed
---

# Task: Fix FDB spool-id extraction — we're storing the filament id as the spool id

CRITICAL correctness bug. After creating an FDB spool via `create_spool` (POST
`/api/filaments/:id/spools`), the bridge extracts `raw.get("_id")` as the new spool id —
but that endpoint returns the **filament document** (with its `spools` array), so
`raw["_id"]` is the **filament** id, not the spool's `_id`. The bug stores the filament id
as `filamentdb_spool_id` in `SpoolMapping`, writes it back to Spoolman's
`filamentdb_spool_id` extra, and uses it as the sync target.

**Verified live:** every `spool_mappings` row has `filamentdb_spool_id ==
filamentdb_filament_id` (e.g. mapping 3: spool 128 → filament `...b0` → spool_id `...b0`).
Consequence: the deletion-detection looks up the (filament) id in `fdb_spool_index` (keyed
by real spool `_id`s), never finds it, and **falsely reports "Record deleted upstream"**
for spools that actually exist. It also breaks per-spool weight/field syncs and the
Spoolman cross-ref.

## Affected call sites (both have the identical bug)

- `backend/app/api/wizard.py` ~1091-1092:
  `raw = await filamentdb.create_spool(fdb_id, spool_payload)` /
  `new_fdb_spool_id = raw.get("_id") or raw.get("id") or ""`
- `backend/app/core/engine.py` ~1172-1173 (`_handle_new_sm_spool`):
  `raw = await filamentdb.create_spool(fdb_filament.id, spool_payload)` /
  `new_fdb_spool_id = raw.get("_id") or raw.get("id", "")`

Both set the spool's identifying field before the call: the payload includes
`{fdb_field_name: str(sm_spool.id)}` where `fdb_field_name` =
`_settings.filamentdb_spoolman_id_field` (default `"label"`). So the just-created spool is
the one in the response whose `label` (that field) equals `str(sm_spool.id)`.

## Before you start

- Read `CLAUDE.md` and `docs/spoolman-writes.md`. Re-verify line numbers — files shifted.
  Don't revert recent changes.
- FDB spool subdocuments use `_id`. The detail/list spool models alias `_id`.

## What to do

### 1. Add a robust extractor

Add a helper (in `backend/app/services/filamentdb.py` as a module function or a
`create_spool`-adjacent method) that returns the created spool's `_id` from the response,
defensively handling both possible FDB return shapes:

```python
def extract_created_spool_id(resp: dict, *, label_field: str, label_value: str) -> str:
    # Response is the filament doc with a spools[] array: match the spool we just added
    # by its label/cross-ref field.
    spools = resp.get("spools")
    if isinstance(spools, list) and spools:
        for sp in spools:
            if str(sp.get(label_field, "")) == str(label_value):
                sid = sp.get("_id") or sp.get("id")
                if sid:
                    return str(sid)
        # fallback: newest-added spool (last in array) that isn't the filament id
        last = spools[-1]
        sid = last.get("_id") or last.get("id")
        if sid:
            return str(sid)
    # Response is a bare spool subdocument
    sid = resp.get("_id") or resp.get("id")
    return str(sid) if sid else ""
```
Prefer label-match; only fall back when no match. Never return the filament's own `_id`
when a spools array is present.

### 2. Use it at both call sites

Replace the `raw.get("_id")` extraction in `wizard.py` and `engine.py` with
`extract_created_spool_id(raw, label_field=fdb_field_name, label_value=str(sm_spool.id))`.
Use the correct `fdb_field_name` in scope at each site
(`_settings.filamentdb_spoolman_id_field`). The corrected id then flows into the
`SpoolMapping.filamentdb_spool_id`, the Spoolman cross-ref write-back, and the SyncLog —
all of which currently get the wrong value.

### 3. Note the existing corrupt data (don't migrate)

Existing `spool_mappings` / Spoolman cross-refs / the 3 open `__record_deleted__` conflicts
were written with the filament id as the spool id and are corrupt. The user is actively
re-importing test data, so after this fix a fresh import produces correct mappings.
Do NOT build a migration; just note in `docs/decisions.md` that pre-fix mappings are
corrupt and should be cleared/re-imported (and the stale deletion conflicts dismissed).

## Verification

- `cd backend && pytest` — add tests:
  - `extract_created_spool_id`: given a filament-shaped response with `spools: [{_id: "SPOOLID", label: "128"}, ...]` and `label_value="128"`, returns `"SPOOLID"` — NOT the filament `_id`. Falls back to the last spool when no label match. Handles a bare-spool response. Returns "" on empty.
  - wizard execute: mock `create_spool` to return a filament dict whose `_id` differs from the inner spool `_id`; assert the created `SpoolMapping.filamentdb_spool_id` is the spool `_id` (not the filament id), and the Spoolman cross-ref write-back uses the spool `_id`.
  - engine `_handle_new_sm_spool`: same assertion for the SpoolMapping + cross-ref.
- `cd frontend && npx tsc --noEmit && npm run build` only if frontend touched (it won't be).

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md`: FDB `create_spool` returns the filament doc; the bridge now
   extracts the created spool's `_id` by matching the label, not the filament `_id`.
   Pre-fix mappings are corrupt → re-import.
3. Non-interactive subagent run: when pytest passes, stage ONLY the files this task touched
   (incl. prompt move + docs) and commit on `dev` with one `fix:` message. Never
   `git add -A`. Never push.
