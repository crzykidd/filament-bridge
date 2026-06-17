---
name: 2026-06-17-archive-retire-bidirectional-sync
status: completed
created: 2026-06-17
model: opus              # PLAN first (engine + active-set filter ripple), then implement via sonnet
completed: 2026-06-17
result: Bidirectional archive/retire lifecycle sync for mapped spool pairs — split archived filter, post-weight lifecycle pass with both-sides snapshot refresh, archive_sync config category, cross_system lifecycle conflict + scoped apply_lifecycle_conflict resolver; import gate preserved. Code + tests + docs done.
---

# Task: Mirror archive/retire state bidirectionally for already-synced spools (FR-21 symmetric)

Make a spool's archived/retired lifecycle state stay consistent across both systems
**after** it is synced. Today this is import-only and one-directional (FR-21 is "Partial"):
once a mapped spool is archived in Spoolman it silently drops out of sync (FDB stays live),
and a spool retired in FDB never propagates to Spoolman at all. Users archive/retire
depleted spools routinely, so the pair drifts. This task closes the gap with a two-way,
boolean lifecycle sync for **mapped pairs only**.

## Decisions already made with the user (do not re-litigate)

1. **Keep the bulk-import gate.** Unmapped archived spools must still NOT be auto-imported
   during ongoing sync (mirrors the wizard's `never_import_empties` import gate). The import
   gate and the post-sync mirror are intentionally asymmetric: import is about not cluttering
   FDB with already-dead inventory; mirroring is about keeping *already-paired* spools honest.
2. **Mirror both directions of the flip** — archive→retire AND un-archive→un-retire (and the
   reverse). It is the same boolean-diff mechanism; un-archiving a paired spool re-enables its
   weight sync.
3. **New independent policy category** `archive_sync` with the usual two axes
   (`archive_sync_direction` default `two_way`, `archive_conflict_policy` default `manual`).
   Reuse `resolve_sync_action` verbatim — do NOT invent a new resolver.
4. **No new conflict type** — reuse `cross_system`. A genuine divergence (both sides flipped
   to opposite states since last snapshot) queues a conflict; the common one-sided flip is a
   clean push, not a conflict (honors the "never auto-resolve conflicts" hard rule).
5. **Reword the import setting** so it's clear it covers archived spools too (see step 6).

## The one structural change (the crux)

The engine filters archived SM spools out of the working set **before** the mapping loop:

- `backend/app/core/engine.py:2505` — `sm_spools = {s.id: s for s in sm_spools_all if not s.archived}`

Because of this, a mapped spool that flips to `archived` vanishes from the set and the diff
loop never sees the transition — it currently falls into the "not in active set (archived?)"
skip branch (`engine.py:~2668`). **Split the filter by purpose:**

- **New-spool detection** (unmapped spools) keeps using the *active-only* set → an unmapped
  archived spool is still never auto-imported during sync. Preserves decision #1.
- **Mapped-pair diffing** uses *active + archived* → a mapped spool that flips to archived
  now reaches the differ so it can be mirrored.

`services/spoolman.py` already returns active + archived (docstring ~line 107: "Fetch all
spools… Caller is responsible for filtering"), so the data is available — this is purely
about which callers see archived spools.

Also: the existing deletion/stale-connection branch (`engine.py:~2599-2730`) must not treat
"missing because archived" as a deletion. Today missing-because-archived is handled by the
skip log; once mapped archived spools stay in scope, that branch needs to route them to the
new lifecycle pass instead of deletion detection.

## Where everything plugs in (verified file:line refs)

- **Differ** — `backend/app/core/differ.py`. Extend `SpoolPairChangeset` (the `@dataclass`
  ~line 30) with `sm_archive_change: FieldChange | None`, `fdb_retire_change: FieldChange |
  None`, `archive_conflict: bool`. In `diff_spool_pair` (~line 49) add a boolean compare
  alongside the weight diff (~line 75): `sm_spool.archived` vs `sm_snapshot["archived"]`,
  `fdb_spool.retired` vs `fdb_snapshot["retired"]`. No threshold (booleans).
- **Snapshots already carry the state** — `_sm_snapshot_dict` / `_fdb_snapshot_dict`
  (`engine.py:~426-451`) use `model_dump()`, so `archived` and `retired` are already
  persisted. Detection works against existing snapshot data; no migration needed.
- **Config category** — add `archive_sync_direction` (`"two_way"`) and
  `archive_conflict_policy` (`"manual"`) to the BridgeConfig defaults
  (`backend/app/models/config.py:~14-20`, next to `weight_sync_*` /
  `material_properties_sync_*`). Surface in the Settings UI + API schema
  (`backend/app/schemas/api.py`) like the other two categories.
- **Resolver** — `backend/app/core/sync_policy.py:resolve_sync_action` (~line 27) used as-is:
  `sm_changed=sm_archive_changed, fdb_changed=fdb_retire_changed, direction, policy`. No
  timestamps (`sm_ts`/`fdb_ts` = None — booleans aren't newest-wins eligible; reject/ignore
  `newest_wins` for this category).
- **Engine pass ordering — weight FIRST, then lifecycle.** The new lifecycle pass runs
  **after** the weight pass (weight pass is ~`engine.py:2781-2963`), NOT before. A spool is
  usually archived/retired right as it hits ~0 g, so the final weight decrement — and its FDB
  usage-log audit entry (`POST …/usage` with `source:"spoolman"`) — MUST be propagated and
  both snapshots refreshed BEFORE the archive/retire bit is mirrored. Otherwise the spool
  lands retired/archived on the far side carrying a stale (too-high) weight and missing its
  final usage entry. On a resolved lifecycle push:
  - SM→FDB: `filamentdb.update_spool(fid, sid, {"retired": <bool>})`
  - FDB→SM: `spoolman.update_spool(sm_id, {"archived": <bool>})`
  - then **refresh BOTH snapshots** to the converged value (the anti-ping-pong step — same
    pattern as the weight pass at `engine.py:~2876-2883` / `~2926-2934`). Mandatory; see the
    2026-06-10 weight ping-pong decision in `docs/decisions.md`.
  - **Do NOT skip the weight pass for an about-to-be-archived spool** — the weight must
    settle first. (A spool that was ALREADY archived/retired on both sides in a prior cycle
    naturally NOOPs the weight pass, since its snapshots already converged — no special skip
    needed.)
- **Client writes already support it** — `spoolman.update_spool(id, payload)`
  (`services/spoolman.py:~146`) PATCHes any dict; `filamentdb.update_spool(fid, sid, payload)`
  (`services/filamentdb.py:~158`) PUTs any dict and `retired` survives `_strip_computed`.
  No client changes needed (confirm in the plan).
- **Conflict** — reuse `_queue_conflict` (engine) with `entity_type="spool"`,
  `field_name="lifecycle"` (or `"archived_retired"` — pick one, state it), JSON-encoded bool
  values, `conflict_type="cross_system"`. Verify the Conflicts UI + resolution + apply path
  (`core/conflict_apply.py`) render and resolve a boolean lifecycle conflict sensibly
  (resolution "spoolman"/"filamentdb" → write the chosen state to the other side, then
  refresh both snapshots).

## State machine to implement (mapped pair, two_way)

| SM `archived` | FDB `retired` | vs snapshot | Action |
|---|---|---|---|
| true  | false | SM flipped         | push → FDB `retired=true` |
| false | true  | FDB flipped        | push → SM `archived=true` |
| false | true  | SM flipped (un-archive) | push → FDB `retired=false` |
| true  | false | FDB flipped (un-retire)  | push → SM `archived=true`* |
| true  | true  | both flipped same  | NOOP, refresh both snapshots (converged) |
| false | false | both un-flipped    | NOOP, refresh both snapshots |
| flip to opposite states | both changed, diverging | `QUEUE_CONFLICT` (rare) |

\* Resolve the genuinely-ambiguous rows via `resolve_sync_action(sm_changed, fdb_changed, …)`
— don't hand-roll the truth table. The table is the expected *outcome* to test against, and
`direction` may restrict a push (e.g. `spoolman_to_filamentdb` never writes SM).

**Weight + archive in the same cycle.** When a spool is both depleted (weight changed) and
archived/retired in the same cycle, the weight pass settles first (logs the FDB usage entry,
refreshes both snapshots to the post-decrement weight), then the lifecycle pass mirrors the
archive bit. End state: far side retired/archived AND carrying the correct decremented weight
with its final usage entry recorded.

## Transparency

- **Sync log** — log lifecycle pushes with a readable detail, e.g. "spool #65 retired in FDB
  (archived in Spoolman)" / "spool #65 archived in Spoolman (retired in FDB)". Not a bare
  `update` with `—`.
- **Settings reword (decision #5)** — the import gate is `never_import_empties`. Wherever it
  is surfaced (Settings UI label + help text, `docs/configuration.md`, CLAUDE.md runtime-
  settings table, `docs/wizard.md`), make explicit that it skips **empty AND archived**
  spools *at import*, and that ongoing sync mirrors archive/retire for already-synced spools
  regardless of this setting. Suggested label: "Skip empty & archived spools on import".
  Do NOT rename the config key (`never_import_empties`) — only the human-facing text.

## Before you start

- Read `CLAUDE.md` (weight model, data-model gotchas, "What NOT to do"),
  `docs/sync-model.md` (passes, snapshots, anti-ping-pong), `docs/prd.md` (FR-21 — flip it
  from Partial to done), `docs/configuration.md`, `docs/spoolman-writes.md`,
  `docs/decisions.md` (the 2026-06-10 weight ping-pong entry — same snapshot-both-sides rule),
  and the completed `prompts/done/2026-06-11-import-archived-empty-spools.md` (the import-gate
  half of this story).
- CLAUDE.md gotcha: Spoolman `?archived=true` returns ONLY archived spools, not "include
  archived" — don't re-fetch the wrong way; the existing client already returns both.

## Working tree check

Run `git status --porcelain`; cross-reference the files this touches. If any are dirty, list
them and ask before touching. This prompt file is exempt.

## Step 0 — PLAN before coding (required; model=opus)

Write a short plan covering: the active-set filter split (new-spool detection vs mapped-pair
diffing) and the deletion-branch interaction; the differ changeset additions; the new config
category + Settings/API surface; the engine lifecycle pass placement and the both-sides
snapshot refresh; the weight-pass skip when both sides are dead; the conflict reuse +
resolution/apply path; the un-archive/un-retire direction; and the test matrix. Confirm
anything ambiguous with the user before implementing.

## What to do (after the plan is agreed)

1. Split the archived-spool filter so mapped archived spools reach the diff loop while
   unmapped archived spools stay excluded from new-spool import.
2. Add archive/retire change detection to the differ.
3. Add the `archive_sync` config category (direction + policy) with Settings UI + API.
4. Add the engine lifecycle pass (resolve → write via existing clients → refresh BOTH
   snapshots → skip weight when both dead). Handle the conflict path via `cross_system`.
5. Reword the `never_import_empties` human-facing text (not the key).
6. Sync log detail + docs.
7. Tests (below).

## Test matrix

- Mapped spool flips `archived=true` in SM (FDB unchanged) → engine sets FDB `retired=true`,
  both snapshots refreshed, **no ping-pong** next cycle, no conflict.
- Mapped spool flips `retired=true` in FDB (SM unchanged) → engine sets SM `archived=true`,
  converges, no ping-pong.
- **Depletion + archive in the same cycle (the ordering guarantee):** a mapped spool's
  remaining drops to ~0 g AND `archived` flips true in the same cycle → the engine logs the
  final usage decrement in FDB first (correct post-decrement `totalWeight`, usage entry with
  `source:"spoolman"`), THEN sets `retired=true`. Assert FDB ends retired with the correct
  decremented weight and the usage entry present — never retired-with-stale-weight, never a
  lost final usage entry.
- Un-archive (true→false) mirrors back to FDB `retired=false` and re-enables weight sync.
- Both flip to the same state → NOOP, snapshots converge, no conflict.
- Genuine divergence (one archives, other un-retires) with `policy=manual` → one
  `cross_system` lifecycle conflict queued; resolving it writes the chosen state to the
  other side and refreshes both snapshots (no re-queue next cycle).
- `direction=spoolman_to_filamentdb` → FDB-side flip does NOT write SM.
- **Unmapped** archived spool during sync is still NOT imported (import gate preserved).
- Reuse / extend the regression spirit of `test_engine.py::test_archived_imported_spool_no_pingpong`.
- Backend `pytest` + `ruff check`; frontend `npx tsc --noEmit` + `npm test`. All green.

## Conventions to honor

- Reuse `resolve_sync_action`, `_queue_conflict`, the existing client `update_spool` methods,
  and the both-sides snapshot-refresh pattern — do not invent parallel machinery.
- Idempotent, failure-isolated writes; never abort the cycle on one spool.
- Doc updates ship in the SAME commit as the code: `docs/prd.md` (FR-21 → done),
  `docs/sync-model.md` (new lifecycle pass), `docs/configuration.md` (new category + reworded
  gate), `docs/spoolman-writes.md` (now writes `archived`), CLAUDE.md (runtime-settings table
  gains `archive_sync_direction`/`archive_conflict_policy`; note archived spools now write
  `retired`/`archived`), and a `docs/decisions.md` entry. Add a `CHANGELOG.md` entry.
- Conventional-commits: `feat:` (new symmetric lifecycle sync). No `Co-authored-by:`.
  Branch `dev`, never `main`, never push.

## When done

1. Update this file's frontmatter (`status`, `completed`, `result`).
2. `git mv` to `prompts/done/` (or `prompts/failed/`).
3. Record the decision in `docs/decisions.md` (the 2026-06-17 design entry already seeds the
   "why"; append the as-built details).
4. Propose ONE commit (stage specific paths, never `git add -A`); present file list + a
   one-line message and STOP for the user to run the commit. Never push.
