---
name: 2026-07-26-master-group-defaults
status: completed          # pending | completed | failed
created: 2026-07-26
model: sonnet
completed: 2026-07-26
result: |
  Three commits landed on dev (not pushed):
  1. feat: seed master/container defaults from family mode on creation —
     core/masters_defaults.py (group_mode_defaults, resolve_family_tare) +
     _execute_spoolman_to_fdb container-payload seeding.
  2. feat: pre-fill merge tare from source and surface the family's tare —
     WizardExecuteResponse.source_tare/master_tare, conflicts.py merge-tare
     gate, Conflicts.tsx pre-fill + "use this" hint.
  3. feat: Master Defaults backfill screen — core/masters_backfill.py,
     api/masters.py (GET/POST /api/masters/defaults[/apply]), frontend
     pages/MasterDefaults, docs/master-defaults.md. Fixes #76.
  All backend/frontend tests + ruff + tsc green before each commit.
  Decision log entry: docs/decisions.md #2026-07-26.
---

# Task: Master-level group defaults (issue #76)

Give FDB masters (variant-family parents) the family's shared defaults so variants
inherit them, backfill existing masters, and stop the merge flow from re-asking for a
tare the family already knows. Three independent commits. GitHub issue: **#76**.

## Before you start

Read, in order:
- `CLAUDE.md` — especially **Sync engine — hard invariants** (weight model, "refresh
  BOTH side snapshots after any propagation" anti-ping-pong rule) and **What NOT to do**
  (the `settings{}` bag is off-limits; all six fields here are top-level, so you're fine).
- `backend/app/core/tare.py` — `apply_tare` is the **exact pattern to mirror** for writing
  a scalar to both sides and refreshing both `_mp_*` snapshots so the next sync cycle
  doesn't re-detect the edit. Also `build_tare_rows` for the master/variant/standalone
  role logic and family grouping (`group_key`/`group_name`).
- `backend/app/api/wizard.py` — `_RECONCILE_FIELD_MAP` (line ~1113, the canonical
  field↔FDB↔SM mapping — REUSE it), `_overlay_reconcile_on_fdb_payload`, and the
  synthetic-container create payload in `_execute_spoolman_to_fdb` (line ~1397).
- `backend/app/core/planner.py` — `_resolve_filament_tare` (line ~125).
- `backend/app/core/masters.py` — `is_master_fdb` (the canonical master detector).
- `backend/app/api/conflicts.py` — the Add/import endpoint (line ~430-490) and its
  preview path; `docs/conflicts.md`.
- `docs/sync-model.md` — the material-property scalar pass (`_sync_material_scalars` /
  baseline keys `_mp_*` in `engine.py`).

**Agreed design decisions (do NOT re-litigate):**
- **Fields:** all six — tare (`spoolWeight`/`spool_weight`), nozzle temp
  (`temperatures.nozzle`/`settings_extruder_temp`), bed temp
  (`temperatures.bed`/`settings_bed_temp`), density, diameter, material
  (`type`/`material`). This is exactly `_RECONCILE_FIELD_MAP`.
- **Master value when variants disagree:** **majority (mode)**. Divergent variants keep
  their own explicit value. Deterministic tie-break (e.g. lowest value wins on a tie) so
  results are reproducible and testable. Skip a field entirely when no member has a value.
- **Backfilling existing masters:** **manual review screen** — nothing writes without a
  user click. **Fill-if-null only:** never overwrite a value the master already holds.
- **Merge tare:** pre-fill the input with the *source* (incoming SM) value but also show
  the *master/family* value so the user can correct it. Keep the `tare_required` 422 only
  for when neither source nor family has a tare.

## Working tree check

Run `git status --porcelain`. The tree should be clean and you should be on `dev`. If any
file this plan touches is already dirty, stop and ask. This prompt file is exempt.

## What to do

### Shared helper (do first — Items 1 & 3 both use it)

Add a small, well-tested helper that computes the per-field majority value across a set of
family members. Put it where both the planner/wizard and a new masters module can import it
without a circular import — a new `backend/app/core/masters_defaults.py` is a good home
(it may import from `masters.py`). Signature roughly:

```python
def group_mode_defaults(values_by_field: dict[str, list]) -> dict[str, Any]:
    """Per field, return the modal (most-common) non-null value across members.
    Deterministic tie-break: lowest value wins. Omit a field when every member is null."""
```

Keep it pure/data-only (take already-extracted value lists, not upstream objects) so it's
trivially unit-testable and reusable in both SM-side and FDB-side callers.

### Item 1 — Seed defaults on master creation  (commit 1)

In `_execute_spoolman_to_fdb`, the synthetic-container create payload (`wizard.py:~1397`,
`container_payload`) currently sets only name/type/vendor/color/optTags. Compute
`group_mode_defaults` across the cluster `members` (the SM filaments) for the six fields,
mapped to FDB keys via `_RECONCILE_FIELD_MAP`, and merge them into the payload. Rules:
- Only add a field when the helper returns a value.
- `temperatures.nozzle`/`temperatures.bed` go into a nested `temperatures` dict.
- Respect `dry_run` (no writes; the existing `container_fdb_id = "dry-run"` branch stays).
- If a reconcile overlay applies on this path, it still wins over the seeded default.
- Do **not** change the "existing container found / find-or-attach" branches — those
  masters are handled by Item 3's backfill, not here.

Tests: extend the wizard SM→FDB execute tests to assert a freshly-created container carries
the mode-derived spoolWeight/temperatures/density/diameter/type from its cluster.

### Item 2 — Merge: pre-fill tare from source, show the family's tare  (commit 2)

Goal: when merging a new SM spool into a family whose FDB master/variants already carry the
tare, the Add dialog pre-fills the incoming (source) value but also shows the family value.

- **Backend:** add `resolve_family_tare(fdb_filaments, master_filamentdb_id) -> float | None`
  — the master's own `spoolWeight`, else the mode of its variant children's effective tare
  (use `group_mode_defaults`). Surface `source_tare` (incoming SM `spool_weight`, via the
  existing `_resolve_filament_tare`) and `master_tare` in the Add **preview** response for
  the SM→FDB direction (extend the relevant preview schema in `schemas/api.py` and the
  conflicts preview path). The import path is unchanged — the UI still sends the chosen
  value as `tare_override`. Keep the `tare_required` 422 only when BOTH are None.
- **Frontend:** in the Conflicts Add dialog (`frontend/src/pages/Conflicts*`), pre-fill the
  tare input with `source_tare` and render `master_tare` beside it (e.g. "family master:
  154 g — use this?") so the user can correct source→family before importing.

Tests: backend unit test for `resolve_family_tare` (master value; fallback to variant mode;
None when nothing known) + a preview test asserting both fields are returned. Frontend:
extend the Conflicts test to assert the pre-fill + the master hint render.

### Item 3 — Backfill existing masters (manual review screen)  (commit 3)

New backend surface + a new frontend page. Model it on the Tare Editor
(`core/tare.py` + its router + `frontend/src/pages/TareEditor`).

- **New module** `backend/app/core/masters_backfill.py` (or extend `masters_defaults.py`):
  - `build_master_default_rows(db, spoolman, filamentdb) -> list[dict]` — one row per
    master (both real `hasVariants` masters and synthetic containers; detect with
    `is_master_fdb`). Per field include: master's current value, the group-mode proposal
    (from the master's variant children's OWN values), and a `would_fill` flag
    (`current is None and proposal is not None`). Include a variant breakdown so the UI can
    show why a value won.
  - `apply_master_defaults(db, *, filamentdb_id, fields, ...)` — PATCH only the requested
    **null** fields on the master with the mode value; **refresh both `_mp_*` snapshots**
    per field exactly like `tare.py:apply_tare` (synthetic masters have no SM side — skip
    the SM snapshot/write for those); `_log` each write. Never overwrite a non-null master
    value. A bulk wrapper with per-row failure isolation (mirror `apply_tare_bulk`).
- **New router** `backend/app/api/masters.py` with `GET /api/masters/defaults` and
  `POST /api/masters/defaults/apply`; register it in `main.py` next to the other routers.
- **New page** `frontend/src/pages/MasterDefaults/` — table grouped by master, per-field
  current vs proposed with a checkbox on fillable cells, bulk apply. Add the route in
  `App.tsx` and a nav entry wherever Tare Editor / Reconcile are linked. Add the typed
  fetch wrapper under `frontend/src/api/`.
- **Docs:** add `docs/master-defaults.md` and link it from `docs/README.md`; note the new
  screen in the relevant user-facing doc.

Tests: backend — row builder (would_fill logic, mode across variants, real + synthetic
masters) and apply (fill-null-only, snapshot refresh, synthetic-master SM skip). Frontend —
render + apply-selection test for the new page.

## Conventions to honor

- **Branch:** work on `dev`. **Commit, do NOT push.**
- **Three commits**, conventional-commit `feat:` prefix, no `Co-authored-by:` trailers.
  Docs ship in the same commit as the code they describe.
- **CHANGELOG:** add/extend a `## [Unreleased]` entry in `CHANGELOG.md` in the SAME commit
  as each item (this repo requires it). Reference **#76** in the entry.
- **Commit bodies:** each references `#76`; the FINAL commit (Item 3) ends its body with
  `Fixes #76`.
- **Tests before each commit:**
  - `cd backend && .venv/bin/python -m pytest`  and  `.venv/bin/python -m ruff check backend/`
  - `cd frontend && npx vitest run`  and  `npx tsc --noEmit`
  All must be green. Never bypass hooks.
- Match surrounding style; keep new modules' docstrings in the house style (see tare.py).

## When done

1. Update this file's frontmatter (`status`, `completed`, `result`).
2. `git mv` this file into `prompts/done/`.
3. Record non-obvious decisions (mode tie-break rule, snapshot-refresh handling for
   synthetic vs real masters, where the shared helper lives) in `docs/decisions.md` with a
   dated `## ` entry, and regenerate the index with `scripts/gen-decisions-index.py`.
4. Leave the three commits on `dev` (do not push). Summarize what landed per commit and
   report the test results.
