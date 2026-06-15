---
name: 2026-06-09-variance-uses-all-fdb-filaments-PONDER
status: pending          # pending | completed | failed  (DESIGN — needs a decision before build)
created: 2026-06-09
model: opus              # decide the design first, then hand to sonnet
completed:
result:
---

# Task (DESIGN/PONDER): Variant matching should use ALL known FDB filaments

This is the "big one" the user flagged to ponder — DO NOT build it blind. It needs a design
decision first (below). Captured 2026-06-09.

## The requirement (user's words, paraphrased)

- Even if the user does NOT select an already-synced Spoolman filament in this wizard run, the
  bridge should still use that filament (and the FDB filament it maps to) when computing variant
  grouping / variance matches.
- Example: "ELEGOO PLA Matte Lavender Purple" is already synced (exists in FDB). The user does NOT
  select it, but DOES select "ELEGOO PLA Matte Navy Blue". The new one should be matched/grouped
  against ALL known FDB filaments — i.e. it should land under the SAME line/parent as the existing
  Lavender Purple, not start a fresh isolated group.
- It must also account for filaments that already exist in Filament DB that the bridge does NOT
  know about (no `FilamentMapping`), otherwise we get name collisions on create.

In short: the variance/grouping step currently reasons mostly about the CURRENT run's selection;
it should instead reason against the FULL existing FDB catalog (bridge-mapped + unmapped).

## Why it's not a blind build (the decisions to make)

1. **Auto-attach vs suggest.** When a new SM filament's cluster key
   `(vendor, material, finish)` matches an existing FDB parent/line, do we:
   (a) auto-attach the new variant under that existing FDB parent (extend the existing line),
   (b) default-attach but show it as overridable in the Variances step, or
   (c) only suggest and require explicit user confirm?
   Recommended: **(b)** — default to attaching to the existing line (reuses the D3
   "attach to existing FDB parent" machinery that already exists), surfaced and overridable in the
   Variances step. This matches the Lavender/Navy example without surprising structural changes.

2. **Unknown (unmapped) FDB filaments.** For FDB filaments with no `FilamentMapping`:
   (a) use them purely as collision sources (detect name clashes, don't link), or
   (b) also offer to adopt/link them (create a mapping) when a clear match exists, or
   (c) ignore unless names collide?
   Recommended: **(a) + opportunistic (b)** — always include ALL FDB filaments in collision
   detection AND in the candidate set for attaching new variants; when a new SM variant would slot
   under an existing-but-unmapped FDB parent, surface it as an attach suggestion (and create the
   mapping on execute). Never silently mutate an unmapped FDB filament beyond parenting a new child.

3. **Scope of "matching".** Does this affect only variant GROUPING (which parent a new color sits
   under), or also the per-field variance reconciliation? Recommended: start with grouping +
   collision; leave field-variance reconciliation against unselected records out of v1.

## Likely implementation shape (after decisions)

- Load the full FDB filament list once (the wizard already fetches FDB filaments; ensure it's the
  complete set, including parents and unmapped records). Build an index by cluster key
  `(vendor_norm, material_norm, finish_norm)` AND by normalized name.
- In the planner / variance step, for each new SM filament: look up an existing FDB parent/line by
  cluster key; if found, default to attaching (D3 path) instead of synthesizing a new container.
- Feed the full FDB name set into the existing `name_collisions` detection so collisions against
  unmapped FDB filaments are caught (verify current `vs_existing` already considers ALL FDB names,
  not just bridge-mapped ones — extend if not).
- Surface in the Variances/Preview UI: "will attach under existing FDB line X" with an override to
  create-new-instead, and the collision-rename/skip flow (built in the sibling prompt
  `2026-06-09-master-marker-parent-badge-collision-rename.md`).

## Dependencies / sequencing

- Build AFTER `2026-06-09-master-marker-parent-badge-collision-rename.md` lands (it adds the
  configurable marker, the parent badge, and the editable collision rename/skip that this feature
  leans on).
- This prompt is intentionally left `pending` with `model: opus` — resolve decisions 1–3 with the
  user, THEN write the concrete sonnet build prompt (or convert this one).
