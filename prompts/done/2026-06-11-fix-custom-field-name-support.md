---
name: 2026-06-11-fix-custom-field-name-support
status: done
created: 2026-06-11
model: sonnet
completed: 2026-06-11
result: Both bugs fixed. ensure_extra_fields now builds spool field list from settings at call time. Engine orphan guard no longer special-cases "label". 897 tests pass.
---

# Task: Honor configured cross-reference field names (startup field creation + engine label guard)

Found in the 2026-06-11 full-code audit (`prompts/assets/2026-06-11-docs-gap-report.md`,
B3 + B8). Both bugs only bite users who override the cross-ref field env vars — but the
docs promise those overrides work.

## Bug A — `ensure_extra_fields` ignores configured spool-field keys

`services/spoolman.py`: `_REQUIRED_SPOOL_FIELDS` is a module-level list hard-coding the
DEFAULT keys (`filamentdb_id`, `filamentdb_parent_id`, `filamentdb_spool_id`). If a user
sets e.g. `SPOOLMAN_FIELD_FILAMENTDB_ID=fdb_id`, startup creates the default-named fields
and never creates `fdb_id` — every subsequent spool write to the undefined key fails.
The FILAMENT-level section already does this right (builds `runtime_filament_fields` from
`_settings.spoolman_field_*` at call time).

**Fix:** build the spool field list at call time from
`_settings.spoolman_field_filamentdb_id` / `_parent_id` / `_spool_id` (same pattern as the
filament section). Keep sensible display names.

## Bug B — engine orphan guard only works for the default `label` field

`core/engine.py`, new-FDB-spool detection (~line 2845):

```python
label_val = getattr(fdb_spool, fdb_field_name, None) if fdb_field_name == "label" else None
```

With a custom `FILAMENTDB_SPOOLMAN_ID_FIELD`, `label_val` is always `None`, so an FDB
spool that already carries a Spoolman ID (orphan without a SpoolMapping row, e.g. after a
bridge-DB reset) is treated as brand new → duplicate Spoolman spool created.

**Fix:** read the configured field generically — `getattr(fdb_spool, fdb_field_name, None)`
(FDBSpool has `extra="allow"`, so custom fields are present as attributes when the API
returns them); keep `None` fallback. Drop the `== "label"` special-case.

## Tests

- `ensure_extra_fields` with overridden settings creates the overridden keys (mock client;
  assert POST paths `/api/v1/field/spool/<custom_key>`).
- Engine: with `filamentdb_spoolman_id_field = "customField"` and an FDB spool carrying
  `customField="42"` but no SpoolMapping, the cycle does NOT create a new SM spool.
- Full backend suite green.

## Before you start

- Read `services/spoolman.py:ensure_extra_fields` (both halves) and the engine's
  new-spool-detection block; `backend/app/config.py` for the settings names.

## Working tree check

Run `git status --porcelain` first. A large uncommitted docs batch (README, docs/*,
CLAUDE.md, prompts/*) is expected — leave it alone. If `services/spoolman.py` or
`core/engine.py` are dirty, stop and ask.

## When done

1. Update frontmatter; `git mv` to `prompts/done/`.
2. Brief `docs/decisions.md` entry.
3. Propose ONE commit (`fix:` prefix, no Co-authored-by), on `dev`.
