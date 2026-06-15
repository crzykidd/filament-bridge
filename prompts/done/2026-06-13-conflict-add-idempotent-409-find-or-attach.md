---
name: 2026-06-13-conflict-add-idempotent-409-find-or-attach
status: completed
created: 2026-06-13
model: sonnet
completed: 2026-06-13
result: >
  Added _find_fdb_by_name() helper + find-or-attach on 409 in three sites in
  _execute_spoolman_to_fdb (container pre-pass, Pass 1, Pass 2). Four new tests
  in test_conflicts_import.py mirror the live ELEGOO PLA Red doom-loop scenario.
  Full venv suite: 1061 passed, 2 pre-existing failures (socksio). ruff/tsc/npm green.
---

# Task: Make filament create-path idempotent — find-or-attach on 409 (fixes conflict-Add doom loop)

## Proven root cause (from live bridge logs)

Conflict "Add" in `generic_container` mode tries to create the synthetic `(Master)` container
+ the variant **every time**. Once they exist (first Add, or a prior wizard import), every
retry 409s and the create-path *skips the cluster*, so nothing attaches and the conflict never
resolves. Live logs:
```
Add #1 → created master + variant + spool ✓ (conflict resolved)
Add #2 → 409 creating container 'ELEGOO PLA (Master)' — skipping cluster
         409 creating FDB filament (SM 172 'ELEGOO PLA Red') — skipping   ← the "2 failures"
Add #3 → same 2× 409 ...  (doom loop; conflict stays open forever)
```
The records ARE in FDB the whole time (verified: `ELEGOO PLA (Master)` + `ELEGOO PLA Red`
variant w/ 1 spool exist) — the Add just can't recognize them, 409s, and reports failure.

This is the same `_execute_spoolman_to_fdb` path the Bulk Import Wizard uses, so the fix
benefits both (the bulk planner already validates mappings vs live FDB — commit 81bf1ee — but
the execute-time 409 handlers do NOT find-or-attach).

## The fix — find-or-attach instead of fail-and-skip on 409

In `backend/app/api/wizard.py::_execute_spoolman_to_fdb`:

1. **Synthetic container create 409** (~line 1246, `if _is_409(exc):`): instead of recording
   a `failed` record + `continue` (skip cluster), **look up the existing FDB container by its
   display name** (vendor+material[+finish] — the same name it tried to create), and use that
   existing filament's id as `container_fdb_id` (attach the cluster's members to it). Only fail
   if no existing match can be found. Ensure a `FilamentMapping(is_synthetic_parent=True,
   filamentdb_id=<existing>)` exists for it (don't duplicate if one already maps that id).
2. **Variant/standalone create 409** (the `409 creating FDB filament (SM ... name ...)` sites
   ~1357/1430): instead of `failed` + skip, **look up the existing FDB filament by name**
   (reuse the bridge's name-normalization / matcher used to build the create name), and treat
   it as a LINK to that existing filament — set its `parentId` to the container if attaching,
   create/refresh the FilamentMapping, proceed to spool creation, and let the conflict resolve.
   Only fail if no existing match is found.
3. Net invariant: **re-running Add (or adding a sibling variant under an existing master) is
   idempotent** — it links to the existing records and resolves the conflict, never 409-fails.

### Lookup key
Use the SAME normalized name the create used (the planner builds FDB names as
vendor+material+finish+color — see `_patch_fdb_name`/container display-name logic). Match
case-insensitively against live `fdb_filaments` (already fetched in the execute). Prefer an
exact normalized-name match; if multiple, prefer one whose `parentId` matches the intended
container (variant) or is null (container). Document the tie-break.

## Also address
- **Conflict resolution on idempotent-link:** when the Add links to pre-existing records (no
  new creates), the conflict must STILL resolve (the import endpoint resolves on
  `failed == 0`). Verify the find-or-attach path returns success (no `failed` records) so
  `/conflicts/{id}/import` marks it resolved.
- **Single-record Add UX note (confirm in implementation):** in `generic_container` mode a
  single Add attaches to the existing/looked-up master rather than spawning a duplicate. This
  is the desired behavior — a single Add should not create a second `(Master)`.

## Tests (run the FULL suite in a throwaway venv — sandbox lacks itsdangerous)
`python3 -m venv "$TMPDIR/v" && "$TMPDIR/v/bin/pip" install -q -r backend/requirements.txt pytest pytest-asyncio`
then `cd backend && "$TMPDIR/v/bin/python" -m pytest -q`.
- Re-running an Add for a record whose master+variant already exist → links to them, ZERO
  failures, conflict resolves (mirror the live ELEGOO PLA Red scenario, generic_container).
- Adding a second variant of the same vendor+material (sibling) → attaches to the existing
  master, no 409 failure.
- A genuinely new record still creates fresh (no regression).
- Container 409 with no findable existing match still fails cleanly (true error).
- Full backend suite + ruff + frontend tsc/npm green.

## When done
Update frontmatter; `git mv` to `prompts/done/`; update `docs/conflicts.md` + `docs/wizard.md`
(idempotent find-or-attach on 409) + `docs/decisions.md`. Propose ONE `fix:` commit (specific
paths, never `git add -A`), STOP for the user to run it. Never push.
