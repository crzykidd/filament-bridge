---
name: 2026-05-30-dashboard-dryrun-detail
status: completed
created: 2026-05-30
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-05-30
result: backend preview entries standardized with SyncPreviewEntry shape + skip coverage; frontend renders 4 collapsible sections with DeepLinks; 154 tests green
---

# Task: Dashboard dry-run — show a per-category detail list, not just counts

The Dashboard "Dry run" button (`POST /api/sync/dry-run`, the **ongoing/auto sync**
dry-run — FR-14) currently reports only five tallies ("Conflicts: 56" and nothing
else). Make it show **what** would happen: a collapsed list broken into the four
categories **Created / Updated / Conflicts / Skipped**, each expandable into per-record
rows. The backend already returns a `preview` array, but the frontend throws it away and
the entries are too thin to be useful — this prompt fixes both ends.

> **Not this:** this is the *ongoing-sync* dry-run surfaced on `Dashboard.tsx`. It is a
> different feature from the FR-4 initial-import wizard preview
> (`GET /api/wizard/preview`, see `prompts/2026-05-30-reconcile-preview-dryrun.md`,
> still WIP in the working tree). Do **not** modify the wizard preview here; just mirror
> its row/deep-link conventions for consistency.

## Scope guardrails (read first)

- **Dry-run + display only.** Touch only the `dry_run=True` branches of the engine and
  the frontend. Do **not** change any live-sync (`not dry_run`) behaviour, snapshotting,
  or write path. The dry-run must still write NOTHING to either upstream.
- **No new conflict resolution.** This surfaces detail; it does not let the user act on
  it. Never auto-resolve (hard project rule).
- **Categories:** the collapsible list has exactly **Created, Updated, Conflicts,
  Skipped**. `Errors` stays as the existing count badge (errors are real failures, not a
  planned action) — do not add an Errors expand section.

## Before you start

- **Read `CLAUDE.md`** (weight model, FDB/Spoolman gotchas, hard rules — esp. "don't
  auto-resolve", "dry-run writes nothing").
- Use the `vexp` `run_pipeline` MCP tool for code context, not grep/glob.
- Study the pieces you will change/reuse:
  - `backend/app/core/engine.py` — `run_sync_cycle` and the per-spool handlers. The
    dry-run preview entries are appended at these `result.preview.append({...})` sites:
    field conflict, FDB→SM field update, SM→FDB field update (in `_apply_field_changes`),
    new-spool "no_filament_mapping" conflicts, new-spool creates (both directions),
    weight conflict, SM→FDB & FDB→SM weight updates, and the deferred `colorName` update.
  - `CycleResult` dataclass (`engine.py`, ~L44) and `CycleResultResponse`
    (`backend/app/schemas/api.py`, ~L48) — `preview: list[dict]` is already plumbed end
    to end through `app/api/sync.py::_to_response`. No new endpoint needed.
  - `frontend/src/pages/Dashboard.tsx` (~L154-165) — renders only the five counts and
    ignores `syncResult.preview`. `frontend/src/api/types.ts` (`CycleResultResponse`).
  - `frontend/src/components/DeepLinks.tsx` — reuse for the two upstream icon links per
    row (every row must carry the IDs to build them).
  - `backend/tests/test_api.py::test_dry_run_returns_preview_and_applies_nothing` (~L126)
    — extend this; don't fork it.

## Working tree check

Run `git status --porcelain`. **Heads-up — these are already dirty from the FR-4 wizard
preview WIP:** `backend/app/api/wizard.py`, `backend/app/schemas/api.py`,
`backend/tests/test_api.py`. This task's natural footprint overlaps `schemas/api.py`
(if you add a typed preview-entry model) and `tests/test_api.py`. Before editing either,
confirm with the user how to coexist with the WIP — prefer **additive** edits (new model
class / new test fn) that don't touch the wizard-preview lines. Files this task adds/edits
that are NOT expected to be dirty: `backend/app/core/engine.py`,
`frontend/src/pages/Dashboard.tsx`, `frontend/src/api/types.ts` (+ maybe a small new
frontend component). List any other unrelated dirty files once as awareness. This prompt
file is exempt.

## What to do

### 1. Standardize the dry-run preview entry shape (backend, `engine.py`)
Every `result.preview.append(...)` in a `dry_run` branch should emit a consistent dict so
the frontend can group and render uniformly. Target shape:

```python
{
  "action": "create" | "update" | "conflict" | "skip",   # the 4 categories
  "entity_type": "spool" | "filament",
  "direction": "spoolman_to_filamentdb" | "filamentdb_to_spoolman" | None,
  "label": "<human-readable record name>",   # e.g. "Elegoo PLA Black — SM #142 → FDB <name>"
  "field": "weight" | "colorName" | <fdb_path> | None,    # for update/conflict
  "old": <value> | None, "new": <value> | None,           # for update; for weight-conflict use the two sides
  "reason": "<why>" | None,                               # for conflict & skip
  "spoolman_id": int | None,
  "fdb_filament_id": str | None,
  "fdb_spool_id": str | None,
}
```

- Add one small **pure** helper (e.g. `_preview_label(*, sm_spool=None, fdb_filament=None)`)
  that builds `label` from whatever is in hand — Spoolman side has
  `sm_spool.filament.vendor.name` / `sm_spool.filament.name` / `sm_spool.filament.color_hex`
  / `sm_spool.id`; FDB side has `fdb_filament.name`. Degrade gracefully to IDs when a name
  isn't available (e.g. the archived-spool skip below has no live `sm_spool`).
- Update the EXISTING dry-run appends to use this shape and to carry `label` + (for
  conflicts) a `reason` + the two conflicting values. Specifically enrich:
  - **weight conflict** → `reason: "both sides changed weight"`, `old`=SM `remaining_weight`,
    `new`=FDB `totalWeight` (label which is which in the reason or keep separate keys —
    your call, just be unambiguous).
  - **field conflict** → `reason: "both sides changed"`, include the two values.
  - **"no_filament_mapping" conflicts** (new SM spool / new FDB spool) → keep the
    `reason` they already have; add `label`.
  - **creates** (both directions) → add `label` from the target filament name.
  - **updates** (field, weight ×2, colorName) → add `label`; they already carry old/new.

### 2. Add the MISSING `skip` preview entries (backend, `engine.py`)
Skips currently increment `result.skipped` but append **nothing** to `preview`, so the
"Skipped" section would be empty. In each `dry_run` path, append a `skip` entry with a
`reason`:
- Mapped pair where the Spoolman spool is archived / not in the active set
  (`sm_spool is None` branch) → `reason: "Spoolman spool archived or not in active set"`.
- First time a pair is seen (baseline-only, `sm_snap is None or fdb_snap is None`) →
  `reason: "first sync of this pair — baseline stored, no diff yet"`.
- In `_apply_field_changes`: the inherited-field skip → `reason: "inherited from parent"`;
  the protected-multicolor color skip → `reason: "multicolor color protected in Spoolman"`.
  (`_apply_field_changes` already receives `result` and `dry_run`.)
- **Leave the two `result.errors += 1` paths as errors** (FDB spool absent in fetch;
  mapped FDB filament not found) — those are failures, not skips.

> Keep all of this inside `if dry_run:` branches. Live-sync logging/behaviour is unchanged.

### 3. Decide entry typing (backend, coordinate with dirty `schemas/api.py`)
`CycleResultResponse.preview` is `list[dict[str, Any]]` today. Either (a) keep it as
loose dicts and rely on the standardized shape, or (b) add a typed `SyncPreviewEntry`
Pydantic model and type `preview: list[SyncPreviewEntry]`. Prefer (b) for frontend type
safety **only if** it can be done as a purely additive edit alongside the wizard-preview
WIP in `schemas/api.py`; otherwise do (a). Confirm with the user per the working-tree
check before editing that file.

### 4. Render the categories (frontend, `Dashboard.tsx` + types)
- Update `CycleResultResponse` / add a `SyncPreviewEntry` type in
  `frontend/src/api/types.ts` to match the chosen backend shape.
- Replace the static count row (Dashboard.tsx ~L154-165) — or keep the count row and add
  below it — with **four collapsible sections** (native `<details>`/`<summary>` is fine,
  matching existing styling): `Created (n)`, `Updated (n)`, `Conflicts (n)`,
  `Skipped (n)`, where `n` is `preview.filter(p => p.action === ...).length`. Sections
  with zero entries render collapsed/empty (or are hidden — your call, keep it tidy).
- Each row shows the `label`, the `direction` (e.g. a small "SM→FDB" tag), the `field`
  and `old → new` for updates, the `reason` for conflicts/skips, and a `DeepLinks` pair
  built from `spoolman_id` / `fdb_filament_id`. Keep it compact and read-only — no buttons
  that mutate.
- Keep `Errors: n` as the existing inline badge.

## Conventions to honor

- Read-only dry-run; never write to upstreams; never auto-resolve.
- Reuse the existing label fields off the Spoolman/FDB models — don't refetch or recompute
  names with new I/O. The label helper is pure.
- Structured logs unchanged; respect `LOG_LEVEL`. Never touch the FDB `settings{}` bag.
- Frontend matches existing Dashboard/wizard styling and the typed api client.

## Verification

- `cd backend && pytest` green. Extend
  `test_dry_run_returns_preview_and_applies_nothing`:
  - asserts (still) that NO mutating client call happens in dry-run.
  - asserts each `preview` entry has `action` in the 4 categories and a non-empty `label`.
  - asserts a `skip` entry is produced for the archived-spool and first-baseline paths
    (previously these added nothing to `preview`).
  - asserts a weight-conflict entry carries both conflicting values + a `reason`.
- `cd frontend && npm run build` green; the four collapsible sections render with correct
  counts and per-row detail.
- **End-to-end on the local stack** (`docker-compose.dev.yml`; re-seed
  `private_data/spoolman-livedata.db`): trigger the Dashboard dry-run, confirm the four
  sections populate and that the per-category counts sum consistently with the tally row,
  and that NOTHING was written to FDB or Spoolman (both unchanged after the call).

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/` (failure).
3. Record any non-obvious decisions in `docs/decisions.md` (e.g. the chosen preview-entry
   shape, loose-dict vs typed model, the label-degradation rule).
4. Propose ONE commit (no `Co-authored-by:`). Suggested message:
   `feat: dashboard dry-run shows per-category detail (created/updated/conflicts/skipped)`.
   Present the file list and ask `commit these as "<message>"? (y/n)` before staging.
   Stage specific paths only; commit on `dev`; no push.
