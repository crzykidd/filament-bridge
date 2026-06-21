---
name: 2026-06-09-variance-uses-all-fdb-filaments-PONDER
status: completed        # pending | completed | failed  (DESIGN — needs a decision before build)
created: 2026-06-09
rescoped: 2026-06-21      # re-scoped against shipped wizard work (D3 attach, container reuse, all-FDB collisions)
model: opus              # decide the design first, then hand to sonnet
completed: 2026-06-21
result: Decision 1 shipped — a singleton cluster matching an existing FDB parent now forms a variances group and attaches to that master (wizard.py:705). Decisions 2 (index non-parent/flat FDB filaments) and 3 (adopt unmapped FDB parents) deferred as edge cases — open a fresh prompt if needed.
---

## IMPLEMENTED 2026-06-21 (decision 1)

The core symptom — "with multiple base types only the first master matches, others come in
standalone" — was decision 1 (singleton attach). Shipped: the variances grouping no longer skips a
`len(members) < 2` cluster when its `(vendor, material, finish)` key matches an existing FDB parent
(`fdb_parent_by_key`); it forms a group with `existing_fdb_parent` so the lone color attaches
(overridable). See `wizard.py` (the `clusters.items()` loop) + tests in `test_api.py`
(`test_wizard_variances_singleton_attaches_to_existing_fdb_master`).

**Deferred (edge cases, not needed for the reported scenario):**
- Decision 2 — `fdb_parent_by_key` still only indexes FDB filaments that are already PARENTS
  (`f.id in _parent_ids or f.hasVariants`). A childless lone master, or matching under a flat
  (non-parent) FDB filament, is not handled. The user's masters have children, so this didn't bite.
- Decision 3 — adopting/creating a `FilamentMapping` for an unmapped existing FDB parent on attach.

Open a new focused prompt for 2/3 if a childless-master or flat-filament case shows up.

# Task (DESIGN/PONDER): Variant grouping should match against ALL existing FDB filaments

This is the "big one" flagged 2026-06-09. **Re-scoped 2026-06-21**: a lot of the original
infrastructure has since shipped, so the remaining gap is much narrower and concrete. Read
the "What already shipped" section before designing — don't rebuild what exists.

## The requirement (user's words, paraphrased)

Even if the user does NOT select an already-synced Spoolman filament in this wizard run, the
bridge should still use that filament (and the FDB filament it maps to) when computing variant
grouping. Example: **"ELEGOO PLA Matte Lavender Purple"** is already in FDB. The user does NOT
select it but DOES select **"ELEGOO PLA Matte Navy Blue"** (a single new color). Navy Blue should
land under the SAME line/parent as the existing Lavender Purple, not start a fresh isolated group
or a brand-new container. It must also reckon with FDB filaments the bridge doesn't know about
(no `FilamentMapping`) so we don't create duplicates / collide.

## What already shipped since 2026-06-09 (do NOT rebuild)

- **D3 "attach to existing FDB parent" machinery** — `wizard_variances` computes
  `fdb_parent_by_key` (`wizard.py:680`) and sets `existing_fdb_parent` on a group
  (`wizard.py:738`); StepVariances shows "Attach to «parent»" and the execute path attaches
  members with `parentId = existing_fdb_parent_id` (`_build_attach_parent_for_sm`,
  `wizard.py:812`). **Works for clusters of ≥2 selected variants.**
- **All-FDB name-collision detection** — `_compute_name_collisions` keys `existing` off the FULL
  `fdb_filaments` list (mapped + unmapped), so collisions against unmapped FDB names are already
  caught. (Decision 2's "collision source = all FDB" is DONE.)
- **Container find-or-attach / reuse** — generic_container execute reuses an existing container by
  name instead of failing on 409 (fixed 2026-06-21); the preview no longer flags a reusable
  null-parent container as a blocking collision.
- **Sibling prerequisite landed** — `2026-06-09-master-marker-parent-badge-collision-rename.md`
  (configurable `(Master)` marker, parent badge, collision rename/skip) is in `prompts/done/`.

## The remaining gap (this is the actual work)

1. **Singleton new variants are dropped from grouping.** `wizard.py:705-707` does
   `if len(members) < 2: continue`, so a lone selected color whose cluster key matches an existing
   FDB line falls through to **ungrouped** (`wizard.py:749`) — and `VariancesFilament` (ungrouped)
   has **no** `existing_fdb_parent` field, so it can never attach. This is exactly the Lavender/Navy
   case and it is STILL BROKEN.
2. **`fdb_parent_by_key` only indexes existing PARENTS** (`wizard.py:682`:
   `if f.id in _parent_ids or f.hasVariants`). If "Lavender Purple" exists in FDB as a **flat**
   filament (no children yet), it is NOT in the index, so Navy Blue can't find it. Matching needs
   to consider ALL FDB filaments by cluster key (and/or normalized name), not just records that are
   already parents.
3. **Opportunistic adopt/link of unmapped FDB filaments** is unspecified. When a new SM variant
   slots under an existing-but-unmapped FDB filament/line, do we create the `FilamentMapping`
   (adopt it) on execute, or only reference it?

## Decisions to make (sharpened — several now de-risked)

1. **Singleton attach (the core fix).** When a selected filament's cluster key
   `(vendor, material, finish)` matches an existing FDB line, surface an attach option even for a
   size-1 cluster. Recommended: **lift the `<2` gate when (and only when) the cluster matches an
   existing FDB parent/line** — present it as a one-member group (or attach affordance on the
   ungrouped row) with `existing_fdb_parent` set, default-attach + overridable. Reuses the D3 path
   end-to-end; no new execute machinery.
2. **Match against flat (non-parent) FDB filaments.** Decide whether a new variant matching an
   existing FLAT FDB filament should: (a) attach under it, promoting it to a parent (one level
   deep — FDB supports parent/variant), (b) attach via a generic container, or (c) only collision-
   guard, no attach. This is the one genuinely structural decision — promoting an existing flat
   record to a parent mutates it. Recommended starting point: **(a) in generic_container mode**
   (the container becomes/!reuses the line parent), **(c) in promote_color mode** unless the user
   opts in, to avoid surprising restructures.
3. **Adopt unmapped FDB parents.** Recommended: create the `FilamentMapping` for the existing FDB
   parent when we attach a new child under it (so future syncs recognize the line), but never
   mutate the unmapped record's own fields — only parent a new child. Confirm whether the current
   execute attach already writes a parent mapping (generic_container does for synthetic parents;
   the D3-to-existing-FDB-parent path may not — verify and close the gap).
4. **Scope.** Grouping + collision + attach only. Leave per-field variance reconciliation against
   UNSELECTED records out of v1 (unchanged recommendation).

## Likely implementation shape (after decisions)

- Build `fdb_parent_by_key` (and a name index) from ALL fdb_filaments, not just parents — or add a
  second index for flat filaments, per decision 2.
- Relax the `len(members) < 2` skip at `wizard.py:706` so a singleton whose key hits an existing
  FDB line forms an attachable unit with `existing_fdb_parent` set; otherwise keep it ungrouped.
- If ungrouped rows should also be attachable, add `existing_fdb_parent` to `VariancesFilament`
  (schema `app/schemas/api.py`) and render the attach control on the ungrouped row in StepVariances.
- Ensure execute adopts/creates the parent `FilamentMapping` when attaching under an unmapped FDB
  parent (decision 3).
- Surface in Variances/Preview: "will attach under existing FDB line X" + override to create-new;
  the collision-rename/skip flow already exists.

## Verify against current behavior before building

- Reproduce the Lavender/Navy case on a real import: select ONE new color of an existing FDB line;
  confirm it currently lands ungrouped with no attach option (expected, per gap #1).
- Confirm whether the existing FDB sibling is a parent or a flat filament in the user's data — that
  decides how much of decision 2 actually bites in practice.

## Next step

Resolve decisions 1–4 with the user, THEN convert this into a concrete sonnet build prompt (or
split: a small "singleton attach" prompt that's mostly done-infrastructure, plus a larger
"match flat FDB + adopt unmapped" prompt if decision 2 goes structural).
