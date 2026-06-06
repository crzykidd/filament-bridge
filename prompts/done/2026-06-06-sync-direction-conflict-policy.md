---
name: 2026-06-06-sync-direction-conflict-policy
status: completed
created: 2026-06-06
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-06
result: >
  Replaced per-category SoT with two-axis (direction + conflict policy) model. Pure
  resolver sync_policy.py; engine rewired through resolver; Settings UI updated; 329
  backend tests green; tsc + build clean.
---

# Task: Per-category sync direction + conflict policy (replace source-of-truth)

Redesign the sync direction/conflict model. Today "source of truth" doubles as a
one-way direction: only the SoT side's lone changes propagate, the other side's lone
change is silently ignored, and both-changed always queues a conflict. Replace this with
two independent, per-category axes:

- **Write direction** (the "lock"): `two_way` | `spoolman_to_filamentdb` |
  `filamentdb_to_spoolman`. One-way = the *other* side is never written (locked).
- **Conflict policy** (two-way, both-sides-changed only): `manual` | `spoolman_wins` |
  `filamentdb_wins` | `newest_wins`.

**Categories:** `weight` and `material_properties`. `material_properties` covers the
generic field sync, multicolor/color, density, diameter, temps, AND cost (cost was
already decided to follow material-props).

Big combined change (one commit, per the user). Do the phases in order; run backend
tests after each backend phase.

## Decisions baked in (from the user)

1. **Two-way: a lone change ALWAYS propagates** to the other side (no SoT gating). The
   conflict policy applies ONLY when both sides changed since the last snapshot.
2. **One-way modes never queue conflicts** — the source side wins; the locked
   destination's own drift is a NOOP (left alone; it gets overwritten next time the
   source changes). Only `two_way` + `manual` (or `newest_wins` fallback) queues.
3. **Policies available per category:** weight → manual / spoolman_wins / filamentdb_wins
   / **newest_wins**; material_properties → manual / spoolman_wins / filamentdb_wins
   (NO newest_wins — Spoolman exposes no per-filament modified timestamp, so it can't be
   honest at the filament level).
4. **newest_wins (weight only):** this is the tiebreaker for a TRUE both-changed
   conflict (both differ from the last snapshot). The common case where only one side
   differs is a lone change handled by two-way propagation — newest_wins is not involved
   there. Comparison: Spoolman spool `last_used` (fallback `registered`) vs the FDB
   filament's `updatedAt`. **Anchor to the bridge's last-sync time:** a side only counts
   as the winner if its source timestamp is *after* that pair's snapshot `captured_at`
   (the bridge's last-sync time). If either side's timestamp is missing, unparseable, not
   after `captured_at`, or the two are equal/indeterminate → fall back to QUEUE_CONFLICT
   (manual). This is best-effort and skew-prone (two different servers' clocks) — document
   that clearly. The reliable signal is frequent syncing, which turns most would-be
   conflicts into ordered lone changes.
5. **Migration preserves today's behavior:** map each old SoT to a one-way direction —
   `spoolman` → `spoolman_to_filamentdb`, `filamentdb` → `filamentdb_to_spoolman`;
   policy = `manual`. (Old defaults: weight=spoolman → SM→FDB; material_properties=
   filamentdb → FDB→SM.) No one's sync changes until they opt into two-way.
6. **Weight auto-win is allowed but the UI warns** it can discard real consumption.
7. **Multicolor moves under `material_properties`** (today it's ungated two-way). After
   migration it follows material_properties' direction (default FDB→SM) — a deliberate,
   documented behavior change. Note it in decisions.
8. Leave `new_spool_source_of_truth` and new-spool creation as-is (out of scope; note it
   stays unenforced as today).

## Before you start

- Read `CLAUDE.md` (hard rule: conflicts never *silently* auto-resolved — but a
  user-configured policy is an explicit choice, not silent; still, default is `manual`).
  Read `docs/decisions.md`.
- Re-verify all line numbers below against current code; the file has shifted across
  recent commits. Don't revert recent matcher/cost/variances changes.

## Working tree check

`git status --porcelain` — files: `backend/app/core/sync_policy.py` (new),
`backend/app/core/engine.py`, `backend/app/core/fields.py`,
`backend/app/api/config.py`, `backend/app/schemas/api.py`,
`backend/app/models/config.py`, `backend/app/main.py` (migration call),
`frontend/src/pages/Settings.tsx`, `frontend/src/api/types.ts` + `client.ts`, tests,
`docs/decisions.md`. Ignore unrelated untracked home-dir dotfiles. This prompt is exempt.

## Phase 1 — Pure resolver + config model + migration

### 1a. Resolver (`backend/app/core/sync_policy.py`, new)
```python
from enum import Enum
class SyncAction(str, Enum):
    PUSH_SM_TO_FDB = "push_sm_to_fdb"
    PUSH_FDB_TO_SM = "push_fdb_to_sm"
    QUEUE_CONFLICT = "queue_conflict"
    NOOP = "noop"

def resolve_sync_action(*, sm_changed, fdb_changed, direction, policy,
                        sm_ts=None, fdb_ts=None) -> SyncAction:
    if not sm_changed and not fdb_changed:
        return SyncAction.NOOP
    if direction == "spoolman_to_filamentdb":
        return SyncAction.PUSH_SM_TO_FDB if sm_changed else SyncAction.NOOP
    if direction == "filamentdb_to_spoolman":
        return SyncAction.PUSH_FDB_TO_SM if fdb_changed else SyncAction.NOOP
    # two_way
    if sm_changed and not fdb_changed:
        return SyncAction.PUSH_SM_TO_FDB
    if fdb_changed and not sm_changed:
        return SyncAction.PUSH_FDB_TO_SM
    # both changed -> policy
    if policy == "spoolman_wins":
        return SyncAction.PUSH_SM_TO_FDB
    if policy == "filamentdb_wins":
        return SyncAction.PUSH_FDB_TO_SM
    if policy == "newest_wins":
        if sm_ts is not None and fdb_ts is not None and sm_ts != fdb_ts:
            return SyncAction.PUSH_SM_TO_FDB if sm_ts > fdb_ts else SyncAction.PUSH_FDB_TO_SM
        return SyncAction.QUEUE_CONFLICT
    return SyncAction.QUEUE_CONFLICT  # manual
```
Unit-test every branch exhaustively.

### 1b. Config keys (`backend/app/models/config.py` `_DEFAULTS`, `api/config.py`, `schemas/api.py`)
Add new keys (flat, JSON in BridgeConfig):
`weight_sync_direction`, `weight_conflict_policy`,
`material_properties_sync_direction`, `material_properties_conflict_policy`.
Add Literal types: `SyncDirection2 = Literal["two_way","spoolman_to_filamentdb",
"filamentdb_to_spoolman"]`; `ConflictPolicy = Literal["manual","spoolman_wins",
"filamentdb_wins","newest_wins"]`. Extend `ConfigResponse` + `ConfigUpdateRequest` with
the four new fields (validate weight policy may be any of 4; material_properties policy
must NOT be newest_wins — reject with 422). Keep the old SoT fields in ConfigResponse for
now (read-only echo) OR remove them — your call, but the engine must stop reading them.

### 1c. Migration (`backend/app/main.py` startup, idempotent)
Add `migrate_sync_config(db)`: if a new key is absent, derive it from the old key and
persist via `set_config_value`:
- `weight_sync_direction` = `spoolman_to_filamentdb` if old `weight_source_of_truth`
  == "spoolman" else `filamentdb_to_spoolman`; `weight_conflict_policy` = "manual".
- `material_properties_sync_direction` = `spoolman_to_filamentdb` if old
  `material_properties_source_of_truth` == "spoolman" else `filamentdb_to_spoolman`;
  `material_properties_conflict_policy` = "manual".
Run once at startup. Idempotent (skip keys already present). Fresh installs (only
defaults present) get the same mapping → one-way + manual = today's effective behavior.

## Phase 2 — Rewire the sync passes through the resolver

Load per-category settings at cycle start (`run_sync_cycle` ~1160): read
`weight_sync_direction/policy` and `material_properties_sync_direction/policy`. Stop
reading `weight_source_of_truth`/`material_properties_source_of_truth`. `resolve_field_map`
should no longer bake direction from SoT — make all field mappings direction-neutral
(the differ already reports which side changed); the engine decides via the resolver.

For EACH pass, compute `sm_changed`/`fdb_changed`, call `resolve_sync_action(...)` with
the relevant category's direction+policy, then execute the returned `SyncAction` using
that pass's EXISTING write mechanics. Keep each pass's special write logic intact:

- **Weight pass** (`engine.py` ~1328-1458): category=weight. `sm_changed` =
  `cs.sm_weight_change is not None or cs.weight_conflict`; `fdb_changed` similarly. For
  `newest_wins`, pass `sm_ts` = parsed `sm_spool.last_used or sm_spool.registered`,
  `fdb_ts` = parsed FDB filament `updatedAt` (it's on the read model via extra="allow";
  add a helper to read+parse it), but **null out any side's timestamp that is not strictly
  after that pair's snapshot `captured_at`** (the bridge last-sync time) so a stale
  timestamp can't win — the resolver then falls back to QUEUE_CONFLICT. PUSH_SM_TO_FDB
  keeps the decrease→`log_usage` /
  increase→`update_spool(totalWeight)` logic; PUSH_FDB_TO_SM keeps the net-recompute +
  `update_spool(remaining_weight)` logic; QUEUE_CONFLICT calls `_queue_conflict(... "weight")`.
- **Multicolor pass** (~522-724): category=material_properties. Map its `sm_changed`/
  `fdb_changed`. Replace its hardcoded both→conflict / one-sided→always-write branches
  with the resolver. Keep the SM↔FDB multicolor payload builders.
- **Cost pass** (~732-913): category=material_properties. Replace the `matprop_sot`
  gating with the resolver. Keep effective-cost resolution + FDB cost / SM filament price
  writes.
- **Generic field sync** (`_apply_field_changes` ~284-507): category=material_properties.
  The differ gives `field_conflicts` (both changed), `sm_field_changes`, `fdb_field_changes`
  per field. For each field, derive `sm_changed`/`fdb_changed` and call the resolver, then
  apply via the existing FDB-PUT / SM-extra write code. Honor `should_skip_inherited`.

### Conflict dedup (correctness fix — required)
When a pass would `QUEUE_CONFLICT`, FIRST check for an existing OPEN conflict for the same
`(entity_type, field_name, spoolman_id/fdb ids)` and skip if present — mirror the existing
deletion-conflict dedup. Without this, a both-changed conflict re-queues every cycle (the
snapshot isn't advanced on conflict). Add `_has_open_conflict(...)` helper and use it in
all passes (also retrofit weight/cost/multicolor/field conflict sites).

### Snapshot advancement
On a successful PUSH, advance BOTH snapshots to the agreed value exactly as the passes do
today (`_store`/`_upsert_snapshot`, using the merge helper for filament snapshots so
`_mc_sig`/`_cost` coexist). On NOOP or QUEUE_CONFLICT, do NOT advance (unchanged).

## Phase 3 — Settings UI (`frontend/src/pages/Settings.tsx` + types/client)

Replace the three `SotSelect` rows with per-category controls for **Weight** and
**Material properties**, each showing:
- a **Direction** selector: Two-way · Spoolman → Filament DB · Filament DB → Spoolman
  (label the one-way options to make clear which side is read-only/locked).
- a **On conflict** selector (enabled/relevant only when direction = Two-way): Manual
  review · Spoolman wins · Filament DB wins · (Weight only) Newest wins.
- For **Weight**, when an auto-win/newest policy is selected, show an inline warning that
  auto-resolving weight conflicts can discard real consumption history.
Keep the existing threshold/precision/variant-keyword controls. Keep the "New spools"
row as-is if present (still maps to the unchanged old key) or hide it — minimal change.
Update `frontend/src/api/types.ts` (`ConfigResponse`/`ConfigUpdateRequest`) and
`client.ts` for the four new fields; wire load/save.

## Conventions to honor

- `code-checkin-and-pr`: `dev`, ONE `feat:` commit, NO `Co-authored-by:`, docs in same
  commit. Never bypass hooks.
- Don't change weight math, the usage-log behavior, tare handling, or the `settings{}` bag.
- Default behavior after deploy MUST equal today's (migration → one-way + manual).

## Verification

- `cd backend && pytest` — add tests:
  - resolver: exhaustive table over (sm_changed, fdb_changed) × directions × policies,
    incl. newest_wins ordering + missing/equal-timestamp fallback to QUEUE_CONFLICT.
  - migration: old `weight_source_of_truth=spoolman` → `weight_sync_direction=
    spoolman_to_filamentdb`/policy manual; idempotent on re-run.
  - engine, per category: two_way lone SM change → FDB; two_way lone FDB change → SM
    (the NEW behavior); two_way both + spoolman_wins → SM wins, no conflict; two_way both
    + manual → one conflict and NOT re-queued on a second identical cycle (dedup);
    one-way SM→FDB ignores lone FDB drift (NOOP). Weight newest_wins picks the newer side.
  - config API rejects newest_wins for material_properties (422).
- `cd frontend && npx tsc --noEmit && npm run build` — must pass.

## When done

1. Frontmatter (`status`/`completed`/`result`); `git mv` to `prompts/done/`.
2. `docs/decisions.md`: the two-axis model; one-way never queues / two-way lone-change
   always propagates; newest_wins is weight-only (no SM filament mtime); multicolor now
   under material_properties; conflict dedup added; migration preserves prior behavior.
3. Non-interactive subagent run: when pytest + tsc + build pass, stage ONLY the files this
   task touched (incl. prompt move + docs) and commit on `dev` with one `feat:` message.
   Never `git add -A`. Never push.
