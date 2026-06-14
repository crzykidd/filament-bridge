---
name: 2026-06-13-reconcile-master-variant-annotation
status: completed        # pending | completed | failed
created: 2026-06-13
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-13
result: Reconcile endpoint excludes master/container parents from only_in_filamentdb; matched variant rows carry variant_of name annotation; 5 new tests all green
---

# Task: Reconcile — don't show master/container parents as "missing"; annotate variants

The read-only Reconcile report (`backend/app/api/reconcile.py`, `frontend/src/pages/Reconcile.tsx`,
just shipped in commit 98f3a5b) currently dumps bridge-owned **master/container parent**
FDB filaments into the "Only in Filament DB" bucket as if they need action. They have no
Spoolman counterpart *by design* — there is nothing to do about them.

**Decided behavior (user choice):** (1) EXCLUDE master/container parents from
`only_in_filamentdb` and from the missing count, and (2) annotate the *matched* variant
rows with a small "Variant of <master name>" subtitle so the parent relationship is still
visible. The master itself never appears as its own row.

## Before you start

- Read `CLAUDE.md` (variant/parent model; synthetic container parents). Read:
  - `backend/app/api/reconcile.py` (the whole file — it's short; you're amending the
    assembly of `only_fdb_rows` and `matched_rows`).
  - `backend/app/api/wizard.py:362-410` — the wizard already detects masters. Reuse its
    approach: synthetic-parent ids from `FilamentMapping.is_synthetic_parent`, the
    `hasVariants` flag on `FDBFilament`, and the configured container marker via
    `_resolve_container_parent_marker(db)` (importable from `app.api.wizard`). Look at the
    `_is_master_fdb` closure there as the reference implementation.
  - `backend/app/schemas/filamentdb.py:97-119` — `FDBFilament` has `parentId: str | None`
    and `hasVariants: bool`.
  - `backend/app/schemas/api.py` — `ReconcileMatchRow`, `ReconcileMissingRow`,
    `ReconcileSummary` (you'll add a field to the match row).
  - `frontend/src/api/types.ts` (the `ReconcileMatchRow` interface) and
    `frontend/src/pages/Reconcile.tsx` (the matched section render).

## Working tree check

`git status --porcelain` first. Tree should be clean except unrelated dotfiles. If a file
this plan touches is dirty, list it and ask. This prompt file is exempt.

## What to do

### Backend (`reconcile.py` + `schemas/api.py`)

1. **Add `variant_of: str | None = None`** to `ReconcileMatchRow` in `schemas/api.py`
   (the small-font "Variant of …" label; None for non-variants).

2. In `reconcile.py`, after fetching `fdb_filaments`, build:
   - `fdb_by_id: dict[str, FDBFilament]` for parent-name resolution.
   - A `_is_master(fdb)` predicate mirroring the wizard's `_is_master_fdb`:
     synthetic-parent id set (query `FilamentMapping.is_synthetic_parent == True` →
     `.filamentdb_id`), OR `fdb.hasVariants`, OR name ends with `f" {marker}"` where
     `marker = _resolve_container_parent_marker(db)` (guard empty marker). Add `db` is
     already a dependency.

3. **Exclude masters from `only_in_filamentdb`**: filter `mr.unmatched_fdb` through
   `not _is_master(fdb)` before building `only_fdb_rows`. The summary's
   `only_in_filamentdb` count must reflect the filtered list (it already derives from
   `len(only_fdb_rows)` — keep that).

4. **Annotate matched rows**: for each matched pair, if the FDB filament has a non-null
   `parentId` that resolves in `fdb_by_id`, set `variant_of` to that parent filament's
   `name` (else None). Use the parent's `name` from the FDB record; if the parent isn't in
   `fdb_by_id`, leave `variant_of=None` (don't fabricate).

5. Leave `only_in_spoolman`, `ambiguous`, spool roll-ups, and the `linked` flag unchanged.

### Frontend (`types.ts` + `Reconcile.tsx`)

6. Add `variant_of?: string | null` to the `ReconcileMatchRow` TS interface.

7. In the matched section of `Reconcile.tsx`, when a row has `variant_of`, render it as a
   small, muted subtitle under the filament name — e.g. `Variant of {variant_of}` in
   `text-xs text-gray-500 dark:text-gray-400` (match the page's existing muted-text
   classes). No other layout change.

### Tests

8. Extend `backend/tests/test_reconcile.py`:
   - A master/container parent FDB filament (e.g. `hasVariants=True`, or a
     `FilamentMapping(is_synthetic_parent=True)` row) with no SM counterpart must NOT appear
     in `only_in_filamentdb` and must NOT be counted in the summary.
   - A matched pair whose FDB filament has a `parentId` resolving to a master must carry
     `variant_of == "<master name>"`.
   - A matched pair with no `parentId` must have `variant_of is None`.
   - Keep the existing reconcile tests green.

## Conventions to honor

- Read-only report; no writes/links. Keep the endpoint thin.
- Match surrounding style. Reuse wizard master-detection rather than re-deriving it.
- **Full backend suite via throwaway venv** (sandbox skips `itsdangerous` tests otherwise):
  `python3 -m venv $TMPDIR/v && $TMPDIR/v/bin/pip install -q -r backend/requirements.txt &&
  cd backend && $TMPDIR/v/bin/pytest`. Confirm `test_reconcile.py` ran. Then
  `ruff check backend/`, and in `frontend/` `npx tsc --noEmit` + `npm test`. All green.

## When done

1. Update frontmatter (`status`, `completed` 2026-06-13, `result`).
2. `git mv` this file to `prompts/done/` (or `prompts/failed/`).
3. Note the decision in `docs/decisions.md` (masters are intentional; shown as a
   "Variant of …" annotation on matched rows, never as missing).
4. Propose ONE `feat:`/`fix:`-prefixed commit (file list + one-liner; ask y/n). On `y`,
   stage those specific paths and commit on `dev` (never `main`, never `git add -A`, never
   push, no `Co-authored-by:`).
