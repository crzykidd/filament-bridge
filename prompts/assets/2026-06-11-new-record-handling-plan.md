# Signed-off plan — New-record handling policies, auto-import, scoped "Add"

Companion to `prompts/2026-06-11-new-record-handling-policies.md`. Signed off 2026-06-11.

## LOCKED DECISIONS (do not deviate)
- **Q1 (new_spool_policy):** settings-driven. Keys `new_filament_policy` + `new_spool_policy`,
  values `manual_review` | `auto_import`, **default `manual_review`** for fresh AND existing
  installs (migration backfills `manual_review`). Honor the setting uniformly — no "smart"
  hybrid. `auto_import` → mapped-filament spools auto-create, unmapped-filament spools wait
  on the filament policy. `manual_review` → queue an actionable conflict.
- **Q2 (variant auto-import):** REUSE the existing `variant_parent_mode` setting as the
  control — **do NOT add a new setting.** When auto-importing a brand-new filament that is a
  variant-cluster member (detect via `matcher.sm_variant_cluster_key`):
  - `variant_parent_mode == unset` → **HOLD** for review (queue new_filament conflict).
  - `variant_parent_mode == promote_color | generic_container` → auto-import and **group per
    that mode** (reuse the wizard/planner grouping). If per-cycle grouping proves too large
    for this cut, fall back to standalone-create when a mode is set and LOG it — but prefer
    honoring the mode.
  - Standalone (non-variant) filaments always auto-create when policy=auto_import.
- **OQ-1 accepted:** defaulting `new_spool_policy=manual_review` means new spools on
  already-mapped filaments now queue instead of auto-creating. This is intended (review by
  default; user enables auto in Settings).
- **OQ-3:** endpoint = `POST /api/conflicts/{conflict_id}/import` (conflict-keyed).
- **OQ-4:** single endpoint with a `dry_run` flag (preview vs execute).

---

(Full plan below — implement faithfully.)

## Mental model
Filament = container; FDB hierarchy parent → variant → spool. Sync top-down: a spool only
syncs once its filament is mapped. Unmapped filament ⇒ spools HELD per policy, never dropped.
Two axes: direction (`new_spool_sync_direction`, existing) = which way; policy (new) =
review-vs-auto. Auto-create only when direction allows AND policy == auto_import.

## 1. Config schema
- `schemas/api.py ~31`: `NewRecordPolicy = Literal["manual_review","auto_import"]`.
- `ConfigResponse ~241` (after new_spool_sync_direction): `new_filament_policy: NewRecordPolicy = "manual_review"`, `new_spool_policy: NewRecordPolicy = "manual_review"`.
- `ConfigUpdateRequest ~275`: both as `NewRecordPolicy | None = None`.
- `models/config.py _DEFAULTS ~22`: `"new_filament_policy": '"manual_review"'`, `"new_spool_policy": '"manual_review"'` (seed_defaults on_conflict_do_nothing).
- `api/config.py _config_response ~136`: read both with default "manual_review".
- `main.py _migrate_sync_config ~122`: idempotent backfill both → "manual_review" if absent.
- Frontend config type + Settings.tsx: add both fields (covered by tsc/npm test).
- No existing shape breaks (all additive/defaulted).

## 2. Auto-import paths (engine.py)
- Read policies in run_sync_cycle near new_spool_direction (~2208); thread into
  `_handle_new_sm_spool`/`_handle_new_fdb_spool` (new kwargs) at call sites ~2862/2901.
- Spool tier: mapped-filament path (~2009 / ~2118) is the auto-create — gate behind
  `new_spool_policy == auto_import`; under manual_review, queue an ACTIONABLE new_spool
  conflict carrying fdb/sm filament ids. Unmapped-filament path (~1973 / ~2093): hold pending
  filament policy — if new_filament_policy=auto_import, auto-create the filament first then
  fall through to spool create; else queue new_spool + paired new_filament conflict. Never
  create a spool whose filament doesn't exist.
- New-filament auto-create: NO create code exists in engine today. Factor a shared
  single-record import helper that wraps `api/wizard._execute_spoolman_to_fdb` (SM→FDB) /
  `_execute_fdb_to_spoolman` (FDB→SM) scoped to one filament; the engine AND the §3 endpoint
  call it (engine ≡ endpoint ≡ wizard). Reuse `_plan_spoolman_to_fdb` (single-element lists).
  This gives FilamentMapping + cross-refs + `_seed_snapshots` (both sides) for free.
- variant_parent_mode handling per LOCKED Q2 above.
- Version gates: cycle-level gate (~2223) already returns early before new-record paths;
  multicolor_supported (~2234) already governs structured color. No new gating.
- Weight model + snapshot-both-sides reused verbatim via the wizard execute path (FR-11).

## 3. Scoped-import endpoint
- `POST /api/conflicts/{conflict_id}/import` in `api/conflicts.py` (next to resolve_conflict).
- Request (`ConflictImportRequest`): `dry_run: bool=False`, `filament_action: "create"|"link"="create"`,
  `filamentdb_id: str|None`, `tare_override: float|None`, `master_filamentdb_id: str|None`.
- Response: reuse `WizardExecuteResponse` (execute) / wizard preview rows (dry_run).
- Scope `_plan_spoolman_to_fdb` to one record (find SM filament via conflict.spoolman_id's
  spool .filament for new_spool; direct for new_filament). Call the shared helper from §2.
- Direction inferred from conflict (spoolman_id set → SM→FDB; filamentdb_spool_id set → FDB→SM).
- On zero-failure execute: mark new_spool conflict resolved (resolution="imported"), resolve
  any paired new_filament conflict. try/except → 502 + leave conflict open on upstream fail.
  Call sync_compatibility_errors first → 409 if blocked.
- New `new_filament` conflict type: field_name="new_filament", entity_type="filament"
  (no schema migration — columns suffice). Dedup guard like `_has_open_conflict`.

## 4. README + docs
- README: new "Concepts" section (container model + hold-until-filament).
- configuration.md (both policy keys), conflicts.md (new_filament type + import endpoint),
  sync-model.md (top-down hierarchy + auto paths + snapshot-both-sides), decisions.md
  (two-axis design, Q2 variant handling, new conflict type + endpoint placement),
  CLAUDE.md runtime-settings table (both policy keys).

## 5. Test matrix (test_engine.py unless noted)
- new_filament_auto_import_creates_fdb; new_filament_manual_review_queues (both conflicts);
  new_spool_held_until_filament; new_spool_auto_import_mapped_filament;
  new_spool_manual_review_mapped_filament_queues; auto_import_no_pingpong (mirror
  test_archived_imported_spool_no_pingpong — 2 cycles, cycle 2 NOOP);
  variant_member_unset_mode_held; variant_member_mode_set_grouped (honors variant_parent_mode).
- test_conflicts: conflict_import creates record+mappings+resolves (+ dry_run preview-only,
  + filament_action=link).
- migration: defaults both policies to manual_review.
- frontend: config type accepts new fields.
- Sandbox: test_api/test_auth/test_debug/test_sync_policy fail at collection on itsdangerous
  (env-only) — ignore; ensure no NEW failures.

## Risk
Shared single-record helper must keep the existing wizard endpoint byte-identical — run the
full wizard test suite. Keep it a thin scoping wrapper, not a refactor of the execute bodies.
