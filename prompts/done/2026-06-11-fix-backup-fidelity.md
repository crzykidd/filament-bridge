---
name: 2026-06-11-fix-backup-fidelity
status: pending
created: 2026-06-11
model: sonnet
completed:
result:
---

# Task: Backup export/import — preserve `is_synthetic_parent` + `conflict_type`

Found in the 2026-06-11 full-code audit (`prompts/assets/2026-06-11-docs-gap-report.md`, B4).

## Bug A — round-trip data loss

`api/backup.py` export omits two columns that import therefore can't restore:

1. `FilamentMapping.is_synthetic_parent` — restoring a backup from a `generic_container`
   install turns bridge-owned container parents into ordinary mappings: the engine's
   synthetic-parent exclusions and the "spool on container parent" guard stop applying.
   (Also note: import upserts filament mappings by `spoolman_filament_id`, which is NULL
   for every synthetic parent — `filter_by(spoolman_filament_id=None).first()` would match
   an arbitrary synthetic row. Key synthetic-parent upserts on `filamentdb_id` +
   `is_synthetic_parent=True` instead.)
2. `Conflict.conflict_type` — restored `master_divergence` conflicts come back as
   `cross_system`, so the resolve endpoint treats them as record-only and the UI loses the
   action workflow.

**Fix:** add both fields to the export dicts and the import inserts/upserts; handle the
NULL-`spoolman_filament_id` upsert as above. Decide whether to bump
`BACKUP_SCHEMA_VERSION`: prefer keeping it at 1 and tolerating missing keys on import
(`.get(..., False)` / `.get(..., "cross_system")`) so old backups still import.

## Note on auth keys (decision 2026-06-11)

The export intentionally INCLUDES `auth_secret`, `admin_password_hash`, and `api_token`
so a restore is full-fidelity — the user approved this. Do not redact them; just add one
sentence to `docs/security.md` noting that a bridge backup export contains the auth
secrets and should be stored accordingly.

## Tests

- Export → import round-trip preserves `is_synthetic_parent` and `conflict_type`.
- Synthetic-parent rows upsert correctly (no cross-matching on NULL).
- Old-shape backup (no new keys) still imports.
- Full backend suite green.

## Before you start

- Read `api/backup.py`, `models/mapping.py`, `models/conflict.py`, and the FR-24 section
  of `docs/prd.md`.

## Working tree check

Run `git status --porcelain` first. A large uncommitted docs batch (README, docs/*,
CLAUDE.md, prompts/*) is expected — leave it alone. If `api/backup.py` is dirty, stop and ask.

## When done

1. Update frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md` entry covering the secret-exclusion decision and the
   schema-compat choice.
3. Propose ONE commit (`fix:` prefix, no Co-authored-by), on `dev`.
