---
name: 2026-06-06-import-set-netfilamentweight
status: completed        # pending | completed | failed
created: 2026-06-06
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-06
result: _fdb_filament_payload_from_sm now sets netFilamentWeight from sm.weight (fallback: first spool initial_weight by id); field omitted when neither available; 8 new tests pass
---

# Task: Set netFilamentWeight on FDB filament create so the spool % bar renders

When the wizard imports a Spoolman filament into Filament DB, the created FDB filament
gets `spoolWeight` (tare) and its spool gets `totalWeight` (gross) — but
`netFilamentWeight` (the filament's full capacity) is never set. Filament DB needs
`netFilamentWeight` to compute the spool fill %, so imported filaments show "—" in the
Spool column. Set it on import.

## Why this is import-only (context, not work)

FDB computes `remaining = totalWeight − spoolWeight − Σ(usageHistory.grams)` and
`% = remaining / netFilamentWeight`. The bridge already logs Spoolman weight decrements as
FDB usage entries (FR-9), so once `netFilamentWeight` is set the % bar both renders and
tracks downward automatically as usage accrues — no ongoing-sync change needed. New FDB
filaments are only ever created during the wizard import, so the fix lives in the planner.

## Before you start

- Read `CLAUDE.md`. Re-verify line numbers — files shifted across recent commits. Don't
  revert recent changes.
- Verified facts: `_fdb_filament_payload_from_sm` in `backend/app/core/planner.py` (~63-96)
  builds the FDB create payload and currently sets `spoolWeight` (~92) but not
  `netFilamentWeight`. Spoolman's full net filament weight is `SpoolmanFilament.weight`
  (`backend/app/schemas/spoolman.py:51`); each spool also has `initial_weight`
  (`spoolman.py:73`). FDB has `netFilamentWeight` on the filament
  (`backend/app/schemas/filamentdb.py:112/145`).

## Working tree check

`git status --porcelain` — files: `backend/app/core/planner.py` (+ wherever the spools for
a filament are available to pass through, similar to how `effective_cost` is threaded),
tests, `docs/decisions.md`. Ignore unrelated untracked home-dir dotfiles. This prompt is
exempt.

## What to do

In `backend/app/core/planner.py` `_fdb_filament_payload_from_sm` (and its caller
`_plan_spoolman_to_fdb`, mirroring how `effective_cost` is resolved/threaded):

- Resolve the filament capacity: `net_filament_weight = sm.weight` (the Spoolman
  filament's full net weight). If `sm.weight` is None, fall back to a representative
  spool's `initial_weight` (first spool, by id, with a non-null `initial_weight`) — reuse/
  mirror the `resolve_effective_cost` selection style for determinism. If still None, omit
  the field (leave FDB to show "—" as today — don't fabricate a value).
- Set `payload["netFilamentWeight"] = net_filament_weight` only when non-null.
- Do NOT change `spoolWeight`, `totalWeight`, the spool `planned_gross`, or any weight
  math. This is purely an additional create-payload field.

It will automatically appear in the Phase-4 "planned writes" preview (that lists payload
fields), so no preview change is needed.

## Conventions to honor

- `code-checkin-and-pr`: `dev`, conventional-commit `fix:` prefix (import bug), NO
  `Co-authored-by:`, docs in same commit.
- Scope strictly to setting the field on create. Backfilling already-imported filaments is
  a possible follow-up — note it, don't build it.

## Verification

- `cd backend && pytest` — add tests:
  - FDB create payload includes `netFilamentWeight` = `sm.weight` when set;
  - falls back to a spool's `initial_weight` when `sm.weight` is None;
  - omits the field entirely when neither is available (no key, not null/0);
  - the field shows up in the wizard planned-writes preview.
- `cd frontend && npx tsc --noEmit && npm run build` if you touch frontend (you likely
  won't).

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md`: import now sets FDB `netFilamentWeight` from Spoolman filament
   `weight` (fallback spool `initial_weight`) so the spool % renders and tracks via usage
   entries; backfill of pre-existing imports deferred.
3. Non-interactive subagent run: when pytest (+ any build) passes, stage ONLY the files
   this task touched (incl. prompt move + docs) and commit on `dev` with one `fix:`
   message. Never `git add -A`. Never push.
