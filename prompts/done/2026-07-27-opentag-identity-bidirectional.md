---
name: 2026-07-27-opentag-identity-bidirectional
status: completed          # pending | completed | failed
created: 2026-07-27
model: sonnet
completed: 2026-07-27
result: >
  Rewrote _sync_opentag_identity (engine.py) into a stateless bidirectional reconciliation keyed
  on openprinttag_uuid. Added the FDB→SM fill leg (spoolman.update_filament with both extra keys),
  kept the SM→FDB leg on merge_filament_settings() (the scoped settings{} exception, unchanged),
  and added a divergence branch routed through resolve_sync_action (material_properties direction
  + policy) that queues a deduped cross_system conflict rather than overwriting. Call site now
  always invokes the pass (dry_run passed through) so it surfaces in dry-run preview. Added
  backend/tests/test_engine_opentag_identity.py (7 tests: fill, push regression, in-sync,
  divergence+dedup, two direction-gating cases, dry-run). Full backend suite: 1482 passed. Ruff
  clean. Updated CHANGELOG.md, docs/sync-model.md, docs/decisions.md (+ regenerated the decisions
  index). Fixes #81.
---

# Task: Make the OpenPrintTag identity sync bidirectional (FDB → Spoolman leg)

Closes **#81**. Today `core/engine.py:_sync_opentag_identity` only pushes the OpenPrintTag
identity (`openprinttag_slug` / `openprinttag_uuid`) **Spoolman → Filament DB**. A filament
matched to OpenPrintTag **on the FDB side** never has its identity flow back to Spoolman, so
Spoolman's `openprinttag_uuid` stays empty and the OpenTag Cleanup tool treats it as unmatched.
Add the missing FDB → Spoolman leg so the identity syncs both ways like every other field.

## Before you start

- Read the full issue: `gh issue view 81`.
- Read `CLAUDE.md` §"Sync engine — hard invariants" and §"What NOT to do" — especially the
  **scoped `settings{}` exception**: the ONLY permitted writer to FDB `settings{}` is
  `FilamentDBClient.merge_filament_settings()`, and only for the two OpenTag identity keys.
  **Reading** FDB `settings{}` is fine; this task adds no new write path.
- Hard rule: **conflicts are never auto-resolved** — a genuine identity divergence must queue a
  conflict, never silently overwrite.
- Study the model to mirror: `_sync_opentag_material_fields` (`engine.py:1905`) — the existing
  bidirectional OPT pass — for how it fetches FDB detail, writes SM extras, queues conflicts, and
  produces dry-run preview rows. And `_queue_conflict` / `_has_open_conflict` (`engine.py:202`,
  `:420`).
- Test harness to mirror: `backend/tests/test_engine_opentag_fields.py` (mocked spoolman/filamentdb
  clients + `run_sync_cycle`).

## Working tree check

Run `git status --porcelain`. The branch is `dev`. The files this task touches:
`backend/app/core/engine.py`, `backend/tests/test_engine_opentag_fields.py` (or a new sibling test
file), `CHANGELOG.md`, `docs/sync-model.md`, `docs/decisions.md`. The prompt file
`prompts/2026-07-27-opentag-identity-bidirectional.md` is expected to change. If any *other* of
those files are already dirty, list them and ask before touching. **Do NOT commit and do NOT
push** — leave everything staged/unstaged in the working tree for Opus to review and commit.

## What to do

Rewrite `_sync_opentag_identity` (`engine.py:4233`) from a one-way push into a **stateless
bidirectional reconciliation**, keyed on the canonical `openprinttag_uuid`. Also update its call
site (`engine.py:~4210`).

### Signature / call-site changes
- Add params: `spoolman: SpoolmanClient`, `dry_run: bool`, `matprop_direction: str`,
  `matprop_policy: str`. (`matprop_direction`/`matprop_policy` are already resolved in the cycle
  function at `engine.py:~3014` — pass them exactly like the `_sync_opentag_material_fields` call
  at `engine.py:~4087`.)
- The current call is guarded by `if not dry_run:`. Change it to **always** call the pass, passing
  `dry_run` through, so the new leg surfaces in dry-run `result.preview` (wizard/trigger dry runs).

### Per-mapping logic (skip `is_synthetic_parent` mappings)
Let `slug_f = _settings.spoolman_field_openprinttag_slug`, `uuid_f = _settings.spoolman_field_openprinttag_uuid`.
```
allow_fdb_to_sm = matprop_direction in ("bidirectional", "filamentdb_to_spoolman")
allow_sm_to_fdb = matprop_direction in ("bidirectional", "spoolman_to_filamentdb")
```
For each mapping:
1. `sm_fil = sm_filaments.get(m.spoolman_filament_id)`; skip if None.
   `sm_slug = decode_extra_value(sm_fil.extra.get(slug_f))`, `sm_uuid = decode_extra_value(sm_fil.extra.get(uuid_f))`.
2. Fetch FDB detail lazily: `fdb_detail = await filamentdb.get_filament(m.filamentdb_id)` (on
   exception: log, `result.errors += 1`, continue — mirror the material-fields pass).
   `fdb_settings = getattr(fdb_detail, "settings", None) or {}`.
   `fdb_slug = fdb_settings.get("openprinttag_slug")`, `fdb_uuid = fdb_settings.get("openprinttag_uuid")`.
   **Do NOT rely on `_hasOwnOptLink`** — it's an underscore key not exposed on the Pydantic model;
   presence of `settings.openprinttag_uuid` is the signal. If the keys are absent, there is no FDB
   identity (don't fabricate an inherited one — inherited-variant propagation is out of scope).
3. `sm_has = bool(sm_uuid)`, `fdb_has = bool(fdb_uuid)`.
   - **both empty** → continue.
   - **SM only** (`sm_has and not fdb_has`) → SM→FDB, gated on `allow_sm_to_fdb`: call
     `filamentdb.merge_filament_settings(m.filamentdb_id, {"openprinttag_slug": sm_slug,
     "openprinttag_uuid": sm_uuid})` (only include keys that are truthy). This is today's behavior.
   - **FDB only** (`fdb_has and not sm_has`) → **NEW leg** FDB→SM, gated on `allow_fdb_to_sm`:
     `await spoolman.update_filament(m.spoolman_filament_id, {"extra": {slug_f:
     encode_extra_value(fdb_slug), uuid_f: encode_extra_value(fdb_uuid)}})` (include only truthy
     keys).
   - **both set, `sm_uuid == fdb_uuid`** → in sync; continue (a slug-only mismatch may be left
     alone — keep it simple).
   - **both set, different uuid** → divergence. Compute
     `action = resolve_sync_action(sm_changed=True, fdb_changed=True, direction=matprop_direction,
     policy=matprop_policy)` and act on it:
       - `QUEUE_CONFLICT` → `_queue_conflict(db, cycle_id, "filament", "OpenPrintTag identity",
         spoolman_id=…, fdb_filament_id=…, spoolman_value=sm_uuid, filamentdb_value=fdb_uuid,
         conflict_type="cross_system")`, deduped via `_has_open_conflict(...)`; `result.conflicts += 1`.
       - `PUSH_FDB_TO_SM` → overwrite SM extras from FDB (same write as the FDB-only leg).
       - `PUSH_SM_TO_FDB` → merge SM identity into FDB (same write as the SM-only leg).
       - `NOOP` → skip.
4. **Dry-run**: in `dry_run` mode perform NO writes/queues — instead append a `result.preview` row
   (`action` = `"update"` with the direction, or `"conflict"`) mirroring the shape used in
   `_sync_opentag_material_fields`, and bump `result.updated` / `result.conflicts` accordingly. In
   live mode, emit a `_log(...)` entry per write (direction `"filamentdb_to_spoolman"` /
   `"spoolman_to_filamentdb"`, field `"OpenPrintTag identity"`) and bump `result.updated`.

### Anti-ping-pong / correctness
- No snapshot baseline is needed: after a fill both sides carry the same uuid → next cycle hits the
  equal branch → no-op. **Verify** the identity extras (`openprinttag_slug`/`openprinttag_uuid`) are
  NOT also handled by any snapshot-diffed pass (they should NOT be in `OPENTAG_EXTRA_FIELDS` — those
  are the material-setting extras). If they somehow are, stop and flag it.
- Keep FDB `settings{}` writes exclusively through `merge_filament_settings()` — no other settings
  write, no other keys.

## Tests

Add to `backend/tests/test_engine_opentag_fields.py` (or a new `test_engine_opentag_identity.py` in
the same style — mocked clients + `run_sync_cycle`, `matprop_direction="bidirectional"`). Cover:
1. **FDB→SM fill**: FDB `settings.openprinttag_uuid`+slug set, SM extras empty → after cycle,
   `spoolman.update_filament` called with both keys; assert the payload.
2. **SM→FDB push** (regression): SM extras set, FDB settings empty → `merge_filament_settings`
   called (unchanged behavior).
3. **In sync**: both sides same uuid → neither write called.
4. **Divergence → conflict**: both set, different uuid, policy `manual` → a `Conflict` row is
   queued (field `"OpenPrintTag identity"`), no overwrite; a second cycle does NOT duplicate it.
5. **Direction gating**: with `material_properties_sync_direction="spoolman_to_filamentdb"`, the
   FDB→SM fill is NOT performed (and vice-versa for `filamentdb_to_spoolman`).
6. **Dry-run**: FDB→SM fill case with `dry_run=True` → no `update_filament` write, a preview row
   present.

Run: `cd backend && .venv/bin/python -m pytest` and `.venv/bin/python -m ruff check backend/`.
Everything must be green.

## Conventions to honor

- **CHANGELOG**: add an entry under `## [Unreleased]` in `CHANGELOG.md` in the SAME change set —
  e.g. `- OpenPrintTag identity now syncs Filament DB → Spoolman as well (previously one-way);
  matches made on the Filament DB side flow back to Spoolman. Divergent tags queue a conflict.
  (Fixes #81)`.
- **Docs in the same change set**: update `docs/sync-model.md` where the OpenTag identity pass is
  described (note it is now bidirectional + conflict-on-divergence), and add a dated entry to
  `docs/decisions.md` recording the design (bidirectional identity, direction-gated on
  `material_properties`, conflict on uuid divergence, FDB writes still via the scoped
  `merge_filament_settings` exception). If `docs/decisions.md` gets a new `## ` heading, regenerate
  its index with `scripts/gen-decisions-index.py`.
- Match surrounding style; no `Co-authored-by:` trailers anywhere.

## When done

1. Update this file's frontmatter (`status`, `completed`, `result`).
2. `git mv` this file into `prompts/done/`.
3. **Do NOT commit and do NOT push.** Instead, report back to Opus: a summary of the changes, the
   list of modified files, and the pytest + ruff output. Opus will review the diff and commit.
