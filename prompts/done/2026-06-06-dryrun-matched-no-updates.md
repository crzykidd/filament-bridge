---
name: 2026-06-06-dryrun-matched-no-updates
status: completed
created: 2026-06-06
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-06
result: dry-run preview now emits "matched" entries for in-sync spool pairs; Dashboard renders them with a Show/Hide toggle
---

# Task: Dry-run preview shows already-matched, in-sync pairs as "Matched — no updates"

On the sync dry-run preview, paired records that are already in sync currently produce
NO preview entry, so they're invisible — the preview only lists changes/conflicts/skips.
The user wants already-matched, no-change pairs to appear as a "Matched — no updates" row
so the dry run is a complete inventory of paired records, not just a diff.

## Before you start

- Read `CLAUDE.md`. Re-verify line numbers — the engine shifted across recent commits.
  Don't revert recent changes.
- Context: `run_sync_cycle(dry_run=True)` builds `result.preview` (a list of dict
  entries). The frontend renders it. Current preview `action` values: `create`,
  `update`, `conflict`, `skip` (`frontend/src/api/types.ts` `SyncPreviewEntry` ~46-47;
  backend `SyncPreviewEntry`/preview entries in `schemas/api.py` + `engine.py`). The
  Dashboard renders the dry-run preview (`frontend/src/pages/Dashboard.tsx`).

## What to do

### 1. Backend — emit a "matched" entry for no-change spool pairs

In `core/engine.py`, the mapped spool-pair loop runs the weight sync + field sync for
each pair (per-pair `diff_spool_pair` → weight/field passes). For each pair, track whether
ANY preview entry was appended for it during that iteration (weight pass + field-mapping
pass). Add a local flag (e.g. `pair_emitted = False`) set to True wherever a preview entry
is appended for the pair in dry-run.

At the END of the pair iteration, in `dry_run` only, if nothing was emitted and the pair
was a real in-sync pair (had prior snapshots — not a first-sight baseline, which already
emits its own "skip/baseline" entry), append:
```python
result.preview.append({
    "action": "matched",
    "entity_type": "spool",
    "direction": None,
    "label": _preview_label(sm_spool=sm_spool, fdb_filament=fdb_filaments.get(fdb_filament_id)),
    "field": None,
    "old": None, "new": None,
    "reason": "in sync — no updates",
    "spoolman_id": sm_spool.id,
    "fdb_filament_id": fdb_filament_id,
    "fdb_spool_id": fdb_spool.id,
})
```
Scope the "matched" status to the spool pair (weight + field changes). Filament-level
multicolor/cost changes are emitted as their own separate preview rows by their own
passes — that's fine; do not try to unify them into the spool's matched flag. Do NOT emit
"matched" in a real (non-dry-run) cycle.

### 2. Schema + frontend — render the new action

- `schemas/api.py`: add `"matched"` to the `SyncPreviewEntry.action` Literal.
- `frontend/src/api/types.ts`: add `'matched'` to `SyncPreviewEntry.action`.
- `frontend/src/pages/Dashboard.tsx` (the dry-run preview renderer): render `matched`
  rows in a muted style (e.g. gray, a "Matched" badge, "no updates" reason). Because there
  may be many, add a lightweight **"Show matched (N)"** toggle (default: shown) so the
  user can collapse them and focus on the rows that need action. Keep the existing
  rendering of create/update/conflict/skip unchanged. If the preview has a counts summary,
  include a matched count.

## Conventions to honor

- `code-checkin-and-pr`: `dev`, conventional-commit `feat:` prefix, NO `Co-authored-by:`,
  docs in same commit if any. No behavior change to real (non-dry-run) sync.

## Verification

- `cd backend && pytest` — add a test: a matched, in-sync spool pair (prior snapshots,
  no weight/field changes) yields exactly one `action == "matched"` preview entry in a
  dry run, and ZERO such entries in a real cycle. A pair with a real change still yields
  its update/conflict entry and NOT a "matched" entry.
- `cd frontend && npx tsc --noEmit && npm run build` — must pass.
- Reason through: a dry run with 3 in-sync pairs + 1 changed pair shows 3 "Matched — no
  updates" rows + 1 update row; the toggle hides/shows the matched rows.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md`: dry-run preview now lists in-sync pairs as "matched — no updates"
   (dry-run only; spool-pair scoped).
3. Non-interactive subagent run: when pytest + tsc + build pass, stage ONLY the files this
   task touched (incl. prompt move + docs) and commit on `dev` with one `feat:` message.
   Never `git add -A`. Never push.
