---
name: 2026-06-10-variant-naming-collision-fix
status: done
created: 2026-06-10
model: sonnet
completed: 2026-06-10
result: Implemented. Added _filament_base_name/_patch_fdb_name helpers in planner.py; Phase B patches variant names, Phase B.5 patches standalone names; wizard.py _container_display_name refactored to share the helper; variant_keywords threaded through; 9 new tests, 872 total green.
---

# Task: Name created FDB filaments/variants with vendor + material + color (fix name collisions)

## Problem (production)

When the Bulk Import Wizard creates a Filament DB filament, the planner copies the **raw
Spoolman filament name** verbatim: `backend/app/core/planner.py:152` → `"name": sm.name`.
Spoolman filaments are often named with just the **color** ("Light Blue", "Beige", "Pink").
So two different lines (e.g. Hatchbox PLA *Light Blue* and another vendor/material's *Light
Blue*) both try to create an FDB filament literally named **"Light Blue"** → Filament DB
returns a 409 name collision → the wizard records it as a per-record failure and the record
silently doesn't get created. This is the root of the user's "imports fail out / don't get
created" reports.

Master/container records are already named well — `_container_display_name`
(`backend/app/api/wizard.py:176-217`) builds `"{Vendor} {Material}{finish} {marker}"`, e.g.
**"Hatchbox PLA (Master)"**. Only the **variants / standalone created filaments** use the bare
color name.

## Goal (from the user)

Created FDB filament names must include **manufacturer + material**, not just the color, so
they're unique:

- **Variant** name = the master's **base name** (vendor + material + finish, i.e. exactly what
  `_container_display_name` builds **without** the marker) **+ the color**.
  e.g. master "Hatchbox PLA (Master)" → variant **"Hatchbox PLA Light Blue"**.
- **Standalone / non-variant created filament** (and any item NOT matched to a standardized
  source): build the name from **vendor + material + color/Spoolman name** so manufacturer and
  material are present — never a bare color.
- The master/container marker (`container_parent_marker`, default `"(Master)"`) stays **only on
  the master/container**, not on variants.

This makes "Light Blue" under Hatchbox vs another vendor become "Hatchbox PLA Light Blue" vs
"<Other> <Material> Light Blue" → no collision.

## Before you start

- Read `CLAUDE.md` and these specifically:
  - `backend/app/api/wizard.py:176-217` `_container_display_name` — the canonical base-name
    builder (vendor + material/finish + optional marker). **Reuse its base-name logic** so
    variant names stay consistent with their master. Factor out a shared
    `_filament_base_name(vendor, material/type, finish_kw)` helper if cleaner, used by both the
    container naming and the new variant naming, so they can never drift.
  - `backend/app/core/planner.py:108-192` `_fdb_filament_payload_from_sm` (the `"name": sm.name`
    site) and `_plan_spoolman_to_fdb` Phase A/B (lines 195-289). Note: the master↔variant
    relationship (`master_of_sm` / `variant_master_sm_id`) is known in the planner (Phase B),
    and the cluster/base name is derived from vendor+material+finish — the same inputs
    `_container_display_name` uses.
  - `backend/app/core/matcher.py` — `sm_variant_cluster_key` / finish extraction, so the
    variant's base name uses the SAME normalized vendor/material/finish as its cluster.
- `git status --porcelain` first; tree should be clean apart from an uncommitted `README.md`
  and queued prompt files (leave those alone). Stay within `planner.py`, `wizard.py` (naming
  helper only), `matcher.py` (if you extract a shared helper). Do NOT touch engine/debug/mappings.
- Standards: `code-checkin-and-pr`.

## What to do

1. **Variant naming.** When a created FDB filament is a variant (has a master in
   `master_of_sm`), set its payload `name` to `"{base_name} {color}"` where:
   - `base_name` = vendor + material + finish (the master's base, **no marker**), produced by the
     shared helper.
   - `color` = the variant's color label — the Spoolman filament name (`sm.name`), which is the
     per-color label in this model.
   - **Dedup guard:** if `sm.name` already begins with / contains the base name (some Spoolman
     setups store the full name), don't double it — fall back to `sm.name` or strip the
     duplicate prefix. Aim for a clean single occurrence of vendor+material.
   Because the payload is built in Phase A but the master relationship is annotated in Phase B,
   compute/patch the variant name where the master context is available (e.g. set the name in
   Phase B after `variant_master_sm_id` is known, or pass the master base name into the payload
   builder). Keep preview and execute consistent — both go through the planner, so set it there.

2. **Standalone created filaments.** For a created filament with no master, ensure the name
   includes vendor + material. If the Spoolman name already contains them, keep it; otherwise
   construct `"{base_name} {color}"` the same way. Items matched to a standardized source keep
   their standardized name (don't override an explicit standardized/linked name).

3. **Master/container naming** — unchanged. Confirm the variant base name matches its master's
   base (so "Hatchbox PLA (Master)" pairs with "Hatchbox PLA Light Blue").

4. **Name-collision preview** — the wizard already computes name collisions
   (`_compute_name_collisions`, wizard.py ~1693). With vendor+material+color names, the earlier
   collisions should disappear; make sure the collision computation runs against the NEW
   constructed names (not the bare `sm.name`), so the preview's "Name collisions" count reflects
   reality.

## Tests (`backend/.venv/bin/python -m pytest`)

- Two SM filaments with the same color ("Light Blue") under different vendors/materials → planned
  FDB names are distinct ("Hatchbox PLA Light Blue" vs "<Other> <Mat> Light Blue"), no collision.
- A variant's planned name = its master's base name + color, and shares the base with the master
  container name (minus marker).
- Dedup guard: `sm.name` already = "Hatchbox PLA Light Blue" → name not doubled.
- Standalone created filament gets vendor+material in the name.
- A linked/standardized name is not overridden.
- Full suite green.

## When done

1. Update frontmatter; `git mv` this file to `prompts/done/`.
2. Record the naming rule in `docs/decisions.md` (variant = master base + color; vendor+material
   always present; marker only on master).
3. **Do NOT commit or push.** Leave changes in the working tree; report file-by-file summary +
   exact pytest counts + a couple of example before/after names.

## Tooling
- Backend venv `backend/.venv/bin/python`. `bwrap: Can't mkdir .../private_data/...` → retry that
  command with `dangerouslyDisableSandbox: true`.
