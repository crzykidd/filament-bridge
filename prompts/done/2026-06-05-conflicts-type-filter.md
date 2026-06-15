---
name: 2026-06-05-conflicts-type-filter
status: completed        # pending | completed | failed
created: 2026-06-05
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-05
result: Added client-side type-filter chip bar to Conflicts.tsx; classifyConflict derives bucket from field_name/spoolman_id; tsc + build pass.
---

# Task: Filter the Conflicts page by conflict type

With many open conflicts (especially after a Filament DB wipe produced a pile of
`__record_deleted__` conflicts), the Conflicts page is hard to scan. Add a filter bar
at the top that buckets conflicts by type with live counts, so the user can quickly
isolate e.g. "Deleted record" or "New spool (Filament DB)" conflicts.

This is a frontend-only change (`frontend/src/pages/Conflicts.tsx`). No API/backend
changes — the type is derived client-side from fields already present on
`ConflictResponse`.

## Before you start

- Read `CLAUDE.md` (conventions) and skim `frontend/src/pages/Conflicts.tsx` — the
  page already special-cases the `__record_deleted__` deletion conflict; match its
  Tailwind styling and component idioms.
- Conflict `field_name` values the engine actually emits (verified in
  `backend/app/core/engine.py`): `new_spool`, `__record_deleted__`, `weight`,
  `remaining_weight`, `multicolor`, and arbitrary material-property field paths
  (e.g. `density`, `diameter`, …). Direction of a `new_spool` conflict is implied by
  which id the engine recorded.

## Working tree check

Run `git status --porcelain` and confirm `frontend/src/pages/Conflicts.tsx` has no
uncommitted changes before editing. (Note: there are unrelated untracked home-dir
dotfiles in this repo's status — ignore them.) This prompt file is exempt.

## What to do

All edits are in `frontend/src/pages/Conflicts.tsx`.

### 1. A `classifyConflict` helper + type metadata (module scope)

Define a `ConflictType` union and a classifier mapping each conflict to exactly one
bucket:

- `field_name === '__record_deleted__'` → `'deleted'` → label **"Deleted record"**
- `field_name === 'new_spool'`:
  - `spoolman_id != null` → `'new_spool_sm'` → label **"New spool (Spoolman)"**
  - else → `'new_spool_fdb'` → label **"New spool (Filament DB)"**
  - (Rationale: the engine sets `spoolman_id` for a Spoolman-only spool and
    `fdb_spool_id`/`filamentdb_filament_id` for an FDB-only spool.)
- `field_name === 'weight' || field_name === 'remaining_weight'` → `'weight'` →
  label **"Weight"**
- `field_name === 'multicolor'` → `'multicolor'` → label **"Multicolor"**
- anything else → `'property'` → label **"Property"**

Add a `TYPE_LABELS` record and a `TYPE_ORDER` array (stable chip order:
deleted, new_spool_sm, new_spool_fdb, weight, multicolor, property). Reuse the
existing `DELETION_FIELD` constant already defined in the file.

### 2. Filter state + derived rows (inside `Conflicts`)

- Add `const [typeFilter, setTypeFilter] = useState<ConflictType | 'all'>('all')`.
- Rename the raw list to `allRows` (currently `const rows = data ?? []`).
- Compute `typeCounts`: for each type in `TYPE_ORDER`, the count of `allRows` of that
  type; keep only types with count > 0.
- Compute an `activeFilter`: if `typeFilter` isn't `'all'` and no rows of that type
  exist on the current tab, fall back to `'all'` (prevents a blank list after
  switching tabs or resolving the last of a type).
- Compute `rows` = `allRows` filtered to `activeFilter` (or all when `'all'`). The
  existing render/map and empty-state should consume this filtered `rows`.

### 3. Filter bar UI

- Render a chip row only when `!loading && !error && allRows.length > 0 &&
  typeCounts.length > 1` (no point showing a filter for a single type).
- An **All (N)** chip plus one chip per present type showing `LABEL (count)`.
- Active chip styled distinctly (e.g. `bg-gray-800 text-white`), inactive as
  `bg-gray-100 ... hover:bg-gray-200`; rounded-full pills. Match page styling.
- Clicking a chip sets the filter **and clears `selected`** (so a hidden conflict
  can't be bulk-resolved). The existing tab buttons already clear `selected`.
- Works on both the `open` and `resolved` tabs (it's derived from `allRows`, which is
  per-tab).

### 4. Empty-state copy

Update the "No {tab} conflicts." message so that when a type filter is active it reads
like "No open weight conflicts." (use the lowercased type label).

## Conventions to honor

- `code-checkin-and-pr`: work on `dev`, conventional-commit `feat:` prefix, NO
  `Co-authored-by:` trailer, docs (if any) in the same commit.
- No backend/API/schema changes. Pure presentational addition.
- Keep the existing deletion-conflict special-casing intact.

## Verification

- `cd frontend && npx tsc --noEmit` must pass clean.
- `cd frontend && npm run build` should succeed.
- If the page has test coverage, run `npm test`; otherwise the typecheck/build is the
  gate. Manually reason through: many deleted + a few new_spool conflicts → chips show
  correct counts, clicking "Deleted record" narrows the list, "All" restores it.

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/` (failure).
3. Record any non-obvious decision in `docs/decisions.md` (likely none — note "type
   derived client-side from field_name, no API change" if you want a breadcrumb).
4. The interactive commit-approval step in `prompts/TEMPLATE.md` does not apply when a
   subagent runs this non-interactively: when tsc/build pass, stage ONLY the files this
   task touched (the page + this prompt move + any docs) and commit on `dev` with a
   `feat:` message. Never `git add -A`. Never push.
