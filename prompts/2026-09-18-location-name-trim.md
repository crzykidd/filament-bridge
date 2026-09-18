---
name: 2026-09-18-location-name-trim
status: pending          # pending | completed | failed
created: 2026-09-18
model: sonnet
completed:
result:
---

# Task: Trim location names in the FDB find-or-create (GitHub #90)

Filament DB 1.76.0 (`hyiger/filament-db#1116`) added `trim: true` to `name` on its
uniquely-named models **and migrates already-stored names on first connect**. The bridge's
FDB location find-or-create matches byte-exactly and creates with the raw Spoolman string,
so an untrimmed Spoolman location name misses its now-trimmed FDB row and the create that
follows collides on the unique name — a 4xx caught per-spool at `engine.py:3907`, logged,
and **repeated every cycle**, with that spool's location never syncing.

Read **GitHub issue #90** (`gh issue view 90`) first — it has the full analysis.

## Before you start

- `CLAUDE.md` — especially the "Sync engine — hard invariants" section. The
  **"after ANY propagation, refresh BOTH side snapshots to the post-write agreed values"**
  rule is load-bearing for step 2 below.
- `docs/decisions.md` 2026-09-18 entry (the compat review that found this).
- `docs/sync-model.md` for where the location pass sits in the cycle.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files this
plan needs to modify. If any have uncommitted changes, list them and ask before touching
them. Surface unrelated dirty files once as awareness; don't block. This file is exempt.

## What to do

Three parts. **All three are required** — part 1 alone trades an error loop for a
ping-pong loop, which the hard invariants forbid.

1. **Trim in the find-or-create.** In `core/locations.py:ensure_fdb_location`:
   - build the prefetch cache as `cache[loc_name.strip()] = loc_id`
   - look up `name.strip()` (both the passed-in cache hit and the post-fetch hit)
   - pass the trimmed name to `filamentdb.create_location(...)` and cache it under the
     trimmed key
   - the existing `if not name or not name.strip(): return None` guard already covers empty
   Apply the same trimming to the three inline cache builders that bypass the helper:
   `api/wizard.py:1936`, `api/mobile.py:309`, and the engine's per-cycle
   `fdb_location_names` map (`engine.py:3093` — note this one is id→name, so trim the
   NAME value it stores).

2. **Snapshot what FDB actually stored.** `engine.py:3913` currently calls
   `_refresh_location_snapshots(db, sm_spool.id, fdb_spool.id, target, target)` where
   `target` is Spoolman's raw string. After part 1 the write resolves to the trimmed FDB
   row, so FDB holds the trimmed name while we'd record the untrimmed one as the FDB
   baseline — next cycle `_fdb_location_name` reads back trimmed, `fdb_location_change`
   fires, and the repeating error becomes a repeating spurious change. Pass the **trimmed**
   value for the FDB side; the Spoolman side keeps its own actual (raw) value. Check the
   FDB→SM leg and `core/conflict_apply.py:267` for the same asymmetry and fix it the same
   way if present.

3. **Normalize the cross-system comparison.** Spoolman does not trim its free-text
   location, so the two sides can legitimately differ by whitespace forever. The
   convergence check at `engine.py:3854`
   (`sm_location_now == fdb_location_now`) must compare stripped values, or a
   both-sides-changed case never registers as converged and queues a bogus conflict.
   Conflict values, log rows and preview rows keep the RAW values for display.

## Tests

Add to the existing location-sync test module (find it under `backend/tests/`):

- FDB location `"Drybox 1"` + Spoolman location `"Drybox 1 "` → resolves to the existing
  id, **no** `create_location` call (assert on the mock).
- Running the location pass twice over that pair produces **no writes on the second
  cycle** — the anti-ping-pong assertion, and the reason parts 2 and 3 exist.
- The ordinary create path (name not present at all) still creates, once.
- A both-sides-changed pair whose names differ only by whitespace converges instead of
  queueing a conflict.

## Conventions to honor

- Match surrounding style; no new deps.
- **CHANGELOG.md `## [Unreleased]`** gets an entry in the SAME commit — a `### Fixed`
  bullet naming the upstream cause and ending `Fixes #90.` Follow the voice of the
  existing entries (explain the failure, not just the change).
- Docs ship with the code: if `docs/sync-model.md` describes the location pass in a way
  this changes, update it in the same commit.
- Conventional-commit prefix `fix:`. **No `Co-authored-by:` trailers.** Commit body ends
  with `Fixes #90`.
- Run before committing: `cd backend && .venv/bin/python -m pytest` and
  `.venv/bin/python -m ruff check backend/` (from the repo root for the ruff path).
- **Never push.**

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. `git mv` this file into `prompts/done/`.
3. Record any non-obvious decisions in `docs/decisions.md` (the 2026-09-18 compat entry
   already describes the bug — add a short implementation note only if you made a
   judgement call, e.g. about case folding, which this task deliberately does NOT do:
   FDB's uniqueness is on the trimmed value, not a case-folded one).
4. Propose ONE commit covering the files you modified (including the prompt move).
   Present the file list and the message; ask `commit these as "<message>"? (y/n)`.
   Stage those specific paths — never `git add -A`. Commit on the current branch.
