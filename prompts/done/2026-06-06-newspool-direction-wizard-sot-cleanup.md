---
name: 2026-06-06-newspool-direction-wizard-sot-cleanup
status: completed        # pending | completed | failed
created: 2026-06-06
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-06
result: new_spool_sync_direction enforced in engine; wizard writes new direction+policy keys; old *_source_of_truth fields removed from config API + UI; 339 tests pass
---

# Task: New-spool sync direction + wizard adopts new keys + remove dead source-of-truth

Follow-up cleanup to the two-axis sync redesign (commit 495f53d). Three changes:

1. **New-spool creation gets a real, enforced direction.** Today new spools are created
   bidirectionally regardless of the (dead, unread) `new_spool_source_of_truth`. Replace
   it with `new_spool_sync_direction` (`two_way` | `spoolman_to_filamentdb` |
   `filamentdb_to_spoolman`), default `two_way`, and ENFORCE it in the engine's new-spool
   detection.
2. **The wizard's per-category "source of truth" step writes the NEW keys.** It currently
   persists the old `*_source_of_truth` keys, which the engine no longer reads — so the
   wizard's ongoing-sync selection is dead. Translate its choices into the new
   direction+policy keys so onboarding configures ongoing sync again.
3. **Remove the dead old source-of-truth fields** from the Settings config API and UI.

## Decisions baked in (from the user)

- New spools: enforced direction, default `two_way` (= today's bidirectional behavior).
- Wizard SoT step: set the new direction+policy keys (translate, same mapping as the
  495f53d migration: `spoolman` → `spoolman_to_filamentdb`, `filamentdb` →
  `filamentdb_to_spoolman`, policy = `manual`).
- Remove the old `weight_/material_properties_/new_spool_source_of_truth` fields from the
  Settings config API + UI (keep only the one-time migration reads).

## Before you start

- Read `CLAUDE.md`. Re-verify all line numbers — the file shifted across recent commits.
  Don't revert recent matcher/cost/variances/sync-policy changes.
- Reference the 495f53d migration in `backend/app/main.py` (`_migrate_sync_config`) and
  the new config keys (`weight_sync_direction`, `weight_conflict_policy`,
  `material_properties_sync_direction`, `material_properties_conflict_policy`) for the
  exact value vocabulary and helpers (`get_config_value`/`set_config_value`).

## Working tree check

`git status --porcelain` — files: `backend/app/models/config.py`,
`backend/app/api/config.py`, `backend/app/schemas/api.py`, `backend/app/main.py`,
`backend/app/api/wizard.py`, `backend/app/core/engine.py` (new-spool detection ~1722-1745
and the `_handle_new_*` callers), `frontend/src/pages/Settings.tsx`,
`frontend/src/api/types.ts` (+ maybe `client.ts`), tests, `docs/decisions.md`. Ignore
unrelated untracked home-dir dotfiles. This prompt is exempt.

## What to do

### 1. New-spool sync direction (enforced)

- `models/config.py` `_DEFAULTS`: add `"new_spool_sync_direction": '"two_way"'`. Remove
  the old `"new_spool_source_of_truth"` default.
- `schemas/api.py`: add `new_spool_sync_direction: SyncDirection2` to `ConfigResponse` and
  `new_spool_sync_direction: SyncDirection2 | None = None` to `ConfigUpdateRequest`
  (reuse the `SyncDirection2` Literal added in 495f53d). Remove the three old
  `*_source_of_truth` fields from `ConfigResponse` and `ConfigUpdateRequest`.
- `api/config.py` `_config_response`: emit `new_spool_sync_direction` (default
  `"two_way"`); drop the three old SoT lines.
- `core/engine.py`: read `new_spool_sync_direction` at cycle start. In the new-spool
  detection section (~1722-1745), gate the two creation paths:
  - call `_handle_new_sm_spool` (SM→FDB create) only when direction is `two_way` or
    `spoolman_to_filamentdb`.
  - call `_handle_new_fdb_spool` (FDB→SM create) only when direction is `two_way` or
    `filamentdb_to_spoolman`.
  Keep the existing orphan/cross-ref skip logic unchanged.
- `main.py` `_migrate_sync_config`: add a migration for the new key — if
  `new_spool_sync_direction` is absent, set it to `"two_way"` (the old
  `new_spool_source_of_truth` was unenforced/bidirectional, so two_way preserves current
  behavior). Idempotent.

### 2. Wizard writes the new keys

- `api/wizard.py` (~192-200): the direction step currently loops over the three old SoT
  keys and `set_config_value`s them. Change it to translate the wizard's per-category
  selection into the NEW keys and persist those instead (stop writing the old keys):
  - weight selection → `weight_sync_direction` (spoolman→spoolman_to_filamentdb,
    filamentdb→filamentdb_to_spoolman) + `weight_conflict_policy="manual"`.
  - material selection → `material_properties_sync_direction` (same mapping) +
    `material_properties_conflict_policy="manual"`.
  - new-spool selection → `new_spool_sync_direction` (same spoolman/filamentdb→one-way
    mapping; the wizard's binary choice maps to a one-way direction).
- KEEP the wizard's request schema fields (`WizardDirectionRequest` in `schemas/api.py`
  ~214-216) as the wizard's input vocabulary — the wizard UI still presents the binary
  per-category choice; only the persistence target changes. (A richer wizard UI with full
  direction+policy is a later nicety — note it, don't build it.) Do not break the existing
  wizard frontend payload.

### 3. Remove dead old fields from Settings UI

- `frontend/src/api/types.ts`: remove the three `*_source_of_truth` fields from
  `ConfigResponse`/`ConfigUpdateRequest`; add `new_spool_sync_direction`.
- `frontend/src/pages/Settings.tsx`: the weight/material rows already use the new
  direction+policy controls (495f53d). Ensure no leftover old-SoT references remain, and
  make the **New spools** row a Direction selector (Two-way / Spoolman → Filament DB /
  Filament DB → Spoolman) bound to `new_spool_sync_direction`. Wire load/save.

## Conventions to honor

- `code-checkin-and-pr`: `dev`, ONE `feat:` commit, NO `Co-authored-by:`, docs in same
  commit. Don't change weight math, the resolver, or other categories' behavior.
- Post-deploy behavior for new spools MUST equal today's (two_way default).

## Verification

- `cd backend && pytest` — add tests:
  - new-spool direction: `two_way` creates both ways; `spoolman_to_filamentdb` creates
    the FDB spool from a new SM spool but does NOT create an SM spool from a new FDB spool
    (and vice versa for `filamentdb_to_spoolman`).
  - migration: `new_spool_sync_direction` defaults to `two_way`; idempotent.
  - wizard direction POST now persists the new keys (assert
    `weight_sync_direction`/`material_properties_sync_direction`/`new_spool_sync_direction`
    + manual policies) and no longer the old `*_source_of_truth` keys.
  - config API: `new_spool_sync_direction` round-trips; old SoT fields are gone (and the
    response no longer includes them).
- `cd frontend && npx tsc --noEmit && npm run build` — must pass.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md`: new-spool creation is now a real enforced direction (default
   two_way); the wizard configures the new direction+policy keys; old source-of-truth
   fields removed from the config surface (migration-only reads remain).
3. Non-interactive subagent run: when pytest + tsc + build pass, stage ONLY the files this
   task touched (incl. prompt move + docs) and commit on `dev` with one `feat:` message.
   Never `git add -A`. Never push.
