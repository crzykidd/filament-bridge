# Variant Parent Mode

The **Variant parent mode** setting controls how the Bulk Import Wizard
(Spoolman → Filament DB direction) builds the parent/variant hierarchy in
Filament DB from flat Spoolman filaments.

Spoolman has no parent concept — every filament is a flat, top-level record.
Filament DB supports a one-level parent/variant model: a parent filament can
have multiple color variants as children. The bridge must decide how to
construct that hierarchy during import.

You must choose a mode before the wizard can run. There is no silent default.

---

## Mode: Promote a color to parent (`promote_color`)

This reproduces the wizard's original behavior.

The bridge clusters Spoolman filaments by vendor + material + finish line
(e.g., "ELEGOO PLA Silk"). Within each cluster:

- The filament with the most active spools (tie-broken by shorter name) is
  **promoted** to be the Filament DB parent. It gets its own color, temps, and
  spools.
- All other colors in the cluster become **variants** (children) of that parent.
- Single-color clusters (only one filament in the cluster) are imported flat —
  no parent/variant structure is created for them.

**When to use:** You want to keep record count low and the promoted color works
well as a representative of the group.

---

## Mode: Generic container parent (`generic_container`)

The bridge creates a **colorless container parent** for every cluster —
including single-color clusters.

- The container has: name (vendor + material + finish, e.g., "ELEGOO PLA"),
  type/material, vendor, and the finish tags (Silk / Matte / CF / …) shared by
  every member of the cluster. No color, no temperatures, no spools.
- Finish tags belong to the whole line, so they sit on the container and the
  color variants inherit them (Filament DB `optTags` are array-fallback
  inheritable). Only finishes shared by *all* members of the cluster are placed
  on the container.
- **Every** Spoolman color becomes a child variant of its cluster's container,
  regardless of cluster size.
- This roughly doubles the Filament DB filament record count (one container per
  cluster plus one record per color).

### The container is bridge-owned and never syncs

The synthetic container parent has **no Spoolman counterpart**. Spoolman is
flat and has no parent concept. The bridge:

- Creates the container in Filament DB only (FDB-only record).
- Tracks it with a `FilamentMapping` row that has `is_synthetic_parent = true`
  and no Spoolman filament id.
- Never pushes or syncs the container to Spoolman.
- Never generates conflicts or orphan warnings for the container.

Each color variant still syncs 1:1 with its Spoolman filament exactly as in
`promote_color` mode.

**If you attach a spool directly to a container parent in Filament DB**, the
bridge will skip it and log a warning: "spool on container parent — move it to
a color variant." This is by design — container parents carry no inventory.

### A note on rendering

Filament DB v1.35.2 fixed the parent-swatch rendering (GitHub issue #597). The
parent record now shows a composite of all its children's colors rather than a
cross-hatch when it has no color of its own. Both modes render cleanly in
modern Filament DB. Choosing `generic_container` is a **pure organizational
preference** (uniform "every color is a child" structure, count = children),
not a rendering fix.

**When to use:** You want a uniform hierarchy where every imported color is
always a variant, the parent is always a colorless container, and the record
count/structure is predictable regardless of how many colors a filament comes
in.

---

## Existing installs and re-runs

- **Existing mappings are never touched.** If you already ran the wizard with
  `promote_color` semantics (or before this setting existed), those mappings
  remain valid. Only new wizard runs are gated on a chosen mode.
- The wizard is re-runnable and idempotent: already-linked records are skipped.
  Re-running with `generic_container` after a prior `promote_color` run creates
  containers only for clusters that have not yet been imported.

---

## Container naming and the "Master" suffix

The container name follows the pattern `{vendor} {base_material} {finish} Master`:

- `base_material` is the material string with finish keywords stripped (via
  `strip_finish_words`) so that a Spoolman filament with `material = "PLA Silk"`
  produces "ELEGOO PLA Silk Master", not "ELEGOO PLA Silk Silk Master".
- The `" Master"` suffix is always appended so the container name never collides
  with its own color children (e.g. "ELEGOO PLA Silk Red"). The suffix is a
  named constant `_CONTAINER_MASTER_SUFFIX` in `api/wizard.py`.

## Container naming collision prevention

The lookup key for existing synthetic containers uses the full cluster tuple
`(vendor_norm, material_norm, finish_norm)`, not just the display name string.
Two clusters that normalize to the same display name but differ by vendor,
material, or finish are treated as distinct containers.

If the "… Master" name still collides with an existing FDB filament (e.g. you
have a record named "ELEGOO PLA Silk Master" from a prior manual import), the
Preview step will show it as a name collision with a "Fix variant mapping" link
(to return to the Variances step and adjust grouping). A 409 on execute is
caught per-record and recorded as a failure — it does not abort the rest of the
batch.

## optTags on container parents (re-runs)

When a pre-existing container is reused on re-run, the wizard computes the
shared finish tags (intersection across members) and PATCHes `optTags` onto the
container if any are missing. This brings containers created before the finish-tag
logic up to date without requiring a full reset. Already-present unrelated tags
are preserved (merge, not clobber).
