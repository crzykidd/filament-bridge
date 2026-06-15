---
name: 2026-06-06-fix-spool-import-stale-xref-and-tare
status: completed        # pending | completed | failed
created: 2026-06-06
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-06
result: Fixed stale xref blocking spool creation (planner Phase C + engine new-spool detection) and resolved tare not written to FDB spoolWeight; 362/362 tests pass
---

# Task: Fix spool import — stale cross-refs skip spool creation; resolved tare not written to FDB spoolWeight

Two real bugs, diagnosed against live data, that together break the spool/% on import.
Both are spool-import correctness → one `fix:` commit.

## Bug A — stale `filamentdb_spool_id` cross-ref makes the planner SKIP spool creation

When Filament DB is wiped/recreated (or an FDB spool deleted), the Spoolman spools still
carry the OLD `filamentdb_spool_id` extra (pointing at a now-deleted FDB spool). On
re-import the planner sees that cross-ref and marks the spool `action="skip"` ("already
linked") — so it creates the FDB **filament** but never its **spool**. Verified live: SM
spool 128 (filament 111 "Beige") was skipped with `filamentdb_spool_id =
6a23ad20a92ec8d964afdbed`, while the current FDB filaments are all `6a244efb...` — i.e. a
stale ref to a deleted spool. Result: 3 filament_mappings but only 2 spool_mappings; Beige
has no spool in FDB.

The same flaw exists in the ongoing engine's new-spool detection (it skips a SM spool that
has a cross-ref but no SpoolMapping, treating it as an intentionally-unlinked orphan,
without checking the referenced FDB spool still exists).

### Fix A
A cross-ref should only cause a skip if the referenced FDB spool **actually exists in the
current FDB data**. If the xref is stale (the FDB spool id isn't present), treat the spool
as a **create** (the cross-ref write-back will overwrite the stale id with the new FDB
spool id automatically — no separate clearing needed).

- **Planner** (`backend/app/core/planner.py`, Phase C ~219-251): the skip condition is
  currently `if sm_spool.id in mapped_sm_spool_ids or xref:`. Change so that a bare `xref`
  only skips when `xref in existing_fdb_spool_ids`. Thread the set of current FDB spool ids
  into `_plan_spoolman_to_fdb` (the wizard execute has the FDB filaments/spools available —
  build `{spool.id for f in fdb_filaments for spool in f.spools}` and pass it in). A
  spool that is genuinely in `mapped_sm_spool_ids` (has a live SpoolMapping) still skips as
  today.
- **Ongoing engine** (`backend/app/core/engine.py`, new-spool detection — the
  `_handle_new_sm_spool` caller that does `if fdb_spool_id: continue`): only `continue`
  (skip) when `fdb_spool_id` is present AND exists in `fdb_spool_index`; otherwise fall
  through to create. (`fdb_spool_index` already maps all current FDB spool ids.)

## Bug B — the wizard's resolved tare is not written to FDB filament `spoolWeight`

The user sets the empty-reel tare in the wizard (Variances step: per-group/per-filament
tare, default 200g, or the spool/filament value). That tare is used to compute the spool's
gross `totalWeight`, but the FDB **filament** `spoolWeight` is written from the RAW
Spoolman filament field `sm.spool_weight` (`planner.py _fdb_filament_payload_from_sm` ~92),
which is **NULL for many filaments**. So FDB gets `netFilamentWeight` (recent fix) but no
`spoolWeight`, and the % math is wrong. Verified: many Spoolman filaments (Orange, Matte
Black, Beige id 59, …) have empty `spool_weight` while the user did set a tare in the
wizard.

### Fix B
Set the FDB filament `spoolWeight` to the **resolved tare** the wizard actually uses for
that filament — the SAME value used to compute the spool gross — not raw `sm.spool_weight`.
The resolution chain already exists in the wizard/planner (`tare_by_sm_spool` overrides →
spool `spool_weight` → filament `spool_weight` → `DEFAULT_TARE_GRAMS` = 200; see
`_sm_filament_tare` and the Phase-C tare logic that computes `used_tare`). Because the
Variances step enforces one tare per group/filament, a single per-filament tare is
well-defined. Thread the resolved tare into `_fdb_filament_payload_from_sm` (alongside the
`netFilamentWeight`/`effective_cost`/`spools` it already receives) and set
`payload["spoolWeight"] = resolved_tare`. Only omit if truly unresolvable (it should always
resolve to at least the 200g default).

## Before you start

- Read `CLAUDE.md` and `docs/spoolman-writes.md`. Re-verify line numbers — files shifted.
  Don't revert recent matcher/cost/variances/sync-policy/netFilamentWeight changes.
- Recent related commits: `68c018f` (netFilamentWeight on import), `dff4b3e` (effective
  cost threading) — mirror how `spools`/`effective_cost` are threaded into
  `_fdb_filament_payload_from_sm` for the tare value.

## Working tree check

`git status --porcelain` — files: `backend/app/core/planner.py`,
`backend/app/api/wizard.py` (planner caller / FDB spool-id set / tare resolution),
`backend/app/core/engine.py` (new-spool detection), tests, `docs/decisions.md`. Ignore
unrelated untracked home-dir dotfiles. This prompt is exempt.

## Verification

- `cd backend && pytest` — add tests:
  - **Bug A planner:** a SM spool whose `filamentdb_spool_id` xref points to an id NOT in
    the current FDB spool set is planned as `action="create"` (not skip); a SM spool whose
    xref IS in the current FDB set (or that has a live SpoolMapping) still skips. A
    standalone filament (one spool, stale xref) yields a create.
  - **Bug A engine:** ongoing new-spool detection creates the SM spool when its xref is
    stale (not in `fdb_spool_index`), and skips when the xref exists.
  - **Bug B:** FDB filament create payload `spoolWeight` = the resolved tare (e.g. user
    override or 200 default) even when `sm.spool_weight` is None; equals the per-spool/
    filament value when set. Confirm the gross/tare used for the spool matches the
    filament `spoolWeight` written.
- `cd frontend && npx tsc --noEmit && npm run build` only if frontend touched (unlikely).

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md`: cross-ref skip now validates the FDB spool still exists (stale
   xref → recreate); FDB `spoolWeight` is written from the wizard's resolved tare, not raw
   Spoolman `spool_weight`. Update `docs/spoolman-writes.md` if the spoolWeight source note
   needs correcting.
3. Non-interactive subagent run: when pytest (+ any build) passes, stage ONLY the files
   this task touched (incl. prompt move + docs) and commit on `dev` with one `fix:`
   message. Never `git add -A`. Never push.
