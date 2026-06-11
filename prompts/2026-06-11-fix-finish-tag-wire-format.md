---
name: 2026-06-11-fix-finish-tag-wire-format
status: pending
created: 2026-06-11
model: sonnet
completed:
result:
---

# Task: Fix wizard finish-tag write-back — JSON-array encoding where CSV is required

Found in the 2026-06-11 full-code audit (`prompts/assets/2026-06-11-docs-gap-report.md`, B2).

## The bug

The bridge's canonical wire format for the Spoolman `filamentdb_material_tags` text extra
is a **CSV string** (`"17"` / `"16,17"`, then JSON-quoted by `encode_extra_value` like all
text extras). `core/material_tags.py:serialize_material_tags` exists exactly for this and
its docstring records that a JSON array form (`"[17, 28]"`) made Spoolman 400.

- Engine path (`_sync_finish_tags`, FDB→SM): correct —
  `encode_extra_value(serialize_material_tags(ids))`.
- OpenTag path (`opt_to_spoolman_fields`): correct — uses `serialize_material_tags`.
- **Wizard path** (`api/wizard.py`, Pass 2.6 "Spoolman finish-tag write-back",
  ~line 1480): WRONG — `encoded = encode_extra_value(finish_ids)` where `finish_ids` is a
  Python list → wire value `"[17]"`. Per the documented Spoolman behavior this 400s; the
  failure is swallowed as a warning, so the SM extra silently never gets stamped on import.

`parse_material_tags` tolerates both forms on read, so nothing downstream corrects it.

## What to do

1. In `api/wizard.py` Pass 2.6, change the encoding to
   `encode_extra_value(serialize_material_tags(finish_ids))` (import already available or
   add it).
2. Grep for any other `encode_extra_value(` call that passes a list for the material-tags
   field; fix the same way. (The cross-ref extras pass strings — fine.)
3. Tests: a wizard-execute test (or a focused unit test of the Pass-2.6 helper logic)
   asserting the SM PATCH payload for `extra.filamentdb_material_tags` is the JSON-quoted
   CSV string (e.g. `'"17"'`), not a JSON array.
4. Full backend suite green.

## Before you start

- Read `core/material_tags.py` (serialize/parse docstrings), the engine `_sync_finish_tags`
  FDB→SM branch, and `api/wizard.py` Pass 2.6.

## Working tree check

Run `git status --porcelain` first. A large uncommitted docs batch (README, docs/*,
CLAUDE.md, prompts/*) is expected from the docs-overhaul session — leave it alone. If
`api/wizard.py` is dirty, stop and ask.

## When done

1. Update frontmatter; `git mv` to `prompts/done/`.
2. One-line note in `docs/decisions.md`.
3. Propose ONE commit (`fix:` prefix, no Co-authored-by), on `dev`.
