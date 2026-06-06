---
name: 2026-06-05-cost-spool-first-sync
status: completed
created: 2026-06-05
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-06
result: "Added spool-first cost resolution, wizard create payload cost, ongoing bidirectional cost sync with matprop SoT, and filament snapshot merge (_mc_sig+_cost coexist); 17 new tests, 286 total passing"
---

# Task: Sync filament cost — spool price first, filament price fallback (wizard + ongoing)

The bridge doesn't account for cost today. Spoolman stores `price` on BOTH the filament
(`SpoolmanFilament.price`) and each spool (`SpoolmanSpool.price`). Filament DB stores
`cost` at the **filament level only** (no per-spool cost). The effective cost rule:
**use the spool's price if set, else fall back to the filament's price.** Apply this in
the initial wizard import AND in ongoing sync, with cost governed by the existing
`material_properties_source_of_truth` setting (bidirectional, conflicts queued).

## Decisions baked in (from the user)

- Scope: **wizard import + ongoing sync**.
- Ongoing direction/conflict: **follow `material_properties_source_of_truth`** — cost is
  a material property and behaves like density/temps (SoT picks the authoritative side;
  both-sides-changed-and-disagree → queue a conflict, never auto-resolve).
- Effective SM cost = spool price first, filament price fallback. Because FDB cost is
  filament-level, resolve a single effective cost per filament deterministically:
  **the price of a representative spool (first spool by id whose `price` is not None);
  if no spool has a price, use the filament's `price`.**
- FDB cost is filament-level, so the FDB→SM write-back targets the Spoolman **filament**
  `price` (not per-spool prices — those are the user's actual purchase prices and must
  not be overwritten by a filament-level value).

## Before you start

- Read `CLAUDE.md` (conflict rules, weight/cost handling) and `docs/decisions.md`.
- Verified facts: `SpoolmanFilament.price` (`backend/app/schemas/spoolman.py:48`),
  `SpoolmanSpool.price` (`:72`), FDB `cost` is filament-level
  (`backend/app/schemas/filamentdb.py:108/139`; FDBSpool has NO cost). `cost` is already
  in `FDB_SCALAR_FIELDS` (`core/fields.py:18`) but auto-match only maps Spoolman EXTRA
  keys, and price is native — so cost is NOT synced today.

## Working tree check

`git status --porcelain` — files: `backend/app/core/engine.py`,
`backend/app/core/planner.py`, `backend/app/api/wizard.py` (preview planned-writes +
execute), a small helper location (`core/fields.py` or similar), tests, `docs/decisions.md`.
Ignore unrelated untracked home-dir dotfiles. This prompt is exempt. NOTE: `matcher.py`
was recently edited (tare change) — don't revert it.

## What to do

### 1. Effective-cost helper

Add a pure helper, e.g. in `backend/app/core/fields.py`:
```python
def resolve_effective_cost(filament_price, spools) -> float | None:
    # spool-first: first spool (by id) with a non-null price; else filament price
    for s in sorted(spools, key=lambda s: s.id):
        if s.price is not None:
            return s.price
    return filament_price
```
Keep it tolerant of empty spool lists. Unit-test it directly.

### 2. Wizard import — set FDB cost on filament create

`backend/app/core/planner.py` `_fdb_filament_payload_from_sm()` (~63-96) currently omits
`cost`. Set `payload["cost"] = resolve_effective_cost(sm.price, <that filament's
spools>)`. The spools for the filament are available in the wizard execute/plan context —
thread them in (the planner already works per-filament with its spool set; pass the spool
list or the resolved cost). Only include `cost` in the payload when it resolves non-null.

Also surface cost in the Phase-4 "planned writes" preview (`wizard.py` preview
`_compute_planned_writes` / `WizardExecuteRecord` plumbing added in commit 66d5370): the
FDB filament create write should list `cost` among its fields when set.

### 3. Ongoing sync — dedicated filament-level cost pass

Model this structurally on the **multicolor** filament-level pass in
`backend/app/core/engine.py` (~545-700). Iterate `filament_mappings`. For each:
- Compute `sm_cost_now = resolve_effective_cost(sm_fil.price, <sm spools for this
  filament>)` and `fdb_cost_now = fdb_detail.cost` (or list value).
- Read filament snapshots; compare `_cost` then-vs-now per side. Baseline on first sight
  (store, no write), exactly like multicolor.
- **Both sides changed and disagree → queue a conflict** with `field_name="cost"`
  (`_queue_conflict(..., entity_type="filament", spoolman_value=sm_cost_now,
  filamentdb_value=fdb_cost_now)`), never auto-resolve.
- One-sided change → apply in the direction permitted by
  `material_properties_source_of_truth`, matching EXACTLY how the existing material-prop
  field sync treats direction. Re-read `resolve_field_map` (`core/fields.py`) and
  `_apply_field_changes` (`engine.py` ~227-470) and mirror that SoT semantics — do not
  invent new behavior. SM→FDB writes `filamentdb.update_filament(fdb_id, {"cost": ...})`;
  FDB→SM writes `spoolman.update_filament(sm_fil_id, {"price": ...})` (the Spoolman
  FILAMENT price, per the decision above).
- Log every write via `_log(..., field_name="cost")`; support `dry_run` preview entries
  exactly like the multicolor pass.

**CRITICAL — shared filament snapshot:** the multicolor pass stores the filament snapshot
as `{"_mc_sig": ...}` via `_upsert_snapshot`, which REPLACES the row's `data`. If the cost
pass writes `{"_cost": ...}` the same way, the two passes will clobber each other's keys
every cycle (perpetual baseline reset / flapping). Fix this: make filament-snapshot writes
**merge** keys (read existing data, update the one key, write back) — add a small
`_merge_snapshot` helper and use it in BOTH the cost pass AND the multicolor `_store`
(update multicolor to merge so `_cost` survives, and cost to merge so `_mc_sig` survives).
Add a test asserting both keys coexist across a cycle.

### 4. (Optional, low-cost) Variances display

If easy, add a small cost chip to the Variances rows for visibility. Not required —
skip if it adds risk.

## Conventions to honor

- `code-checkin-and-pr`: `dev`, conventional-commit `feat:` prefix, NO `Co-authored-by:`,
  docs in same commit.
- Never auto-resolve conflicts. Never overwrite per-spool Spoolman prices from a
  filament-level value. Don't touch weight math or the `settings{}` bag.

## Verification

- `cd backend && pytest` — add tests:
  - `resolve_effective_cost`: spool price wins; falls back to filament price when no spool
    has one; handles empty spools.
  - wizard execute: FDB filament create payload includes the spool-first cost; appears in
    the planned-writes preview.
  - ongoing cost pass: SM price change → FDB `cost` update when matprop_sot favors SM;
    FDB cost change → SM filament `price` update when matprop_sot favors FDB; both changed
    → one `cost` conflict; first-sight baseline writes no cost; **`_mc_sig` and `_cost`
    coexist in the filament snapshot after a cycle** (regression for the clobber hazard).
- No frontend type/build changes expected unless you do step 4; if you touch frontend,
  run `cd frontend && npx tsc --noEmit && npm run build`.

## When done

1. Update frontmatter (`status`/`completed`/`result`); `git mv` to `prompts/done/` (or
   `prompts/failed/`).
2. Record in `docs/decisions.md`: effective cost = spool price → filament price fallback;
   FDB cost is filament-level so FDB→SM writes the Spoolman filament price; cost follows
   material-props SoT; filament snapshots now merge keys (`_mc_sig` + `_cost`).
3. Non-interactive subagent run: when pytest (+ any frontend build) passes, stage ONLY the
   files this task touched (incl. prompt move + docs) and commit on `dev` with one `feat:`
   message. Never `git add -A`. Never push.
