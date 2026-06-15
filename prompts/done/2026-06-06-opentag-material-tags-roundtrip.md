---
name: 2026-06-06-opentag-material-tags-roundtrip
status: completed
created: 2026-06-06
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-06
result: "Adopted FDB OpenPrintTag finish model: type=base material + numeric IDs in optTags; new filamentdb_material_tags SM extra field; flap-safe differ; _finish_sig snapshot coexists with _mc_sig/_cost; 444 tests pass."
---

# Task: OpenPrintTag material-tag (finish) round-trip — type=base material + finish tag in optTags

Filament DB follows the OpenPrintTag model: `type` is the base material ("PLA") and finishes
like Silk/Matte/Glow are numeric **OpenPrintTag IDs** in the `optTags` array (FDB renders
them as badges; e.g. SILK). The bridge today bakes the finish into the `type`/material
string ("PLA Silk") and uses finish keywords ONLY for variant clustering — it never writes
the finish tag. Make the bridge adopt the OpenPrintTag model with a clean round-trip.

This is a large, core change (reshapes `type` handling, adds a Spoolman extra field). Do it
in phases; run backend tests after each.

## Decisions (from the user)

- Track the finish on the Spoolman side in a **dedicated extra field** (not by mangling the
  material string) — "should we add a field to track this? yes".
- Seed the keyword↔OpenPrintTag-ID map from the spec and make it **config-overridable**
  (the user can't read FDB's numeric ids from the UI; the bridge already uses OpenPrintTag
  28/29 so the enum applies). Verify `silk=17`/`matte=16` against live FDB when possible.
- Round-trip both directions, governed by the existing `material_properties` direction +
  conflict policy.

## OpenPrintTag IDs (from the spec — data/tags_enum.yaml) seeding the map

silk=17, matte=16, glitter=23 (FDB "Sparkle"), glow_in_the_dark=24, contains_carbon_fiber=31
(FDB "Carbon Fiber"), contains_glass_fiber=34 (FDB "Glass Fiber"), contains_wood=41 (FDB
"Wood Fill"), contains_metal=46 (FDB "Metal Fill"), translucent=19, transparent=20,
high_speed=71 (FDB "High Speed"), recycled=60. Arrangement gradient=28 / coextruded=29 stay
owned by the existing multicolor path — do NOT manage them here. Leave ambiguous FDB labels
(Flexible / Color Changing / Biodegradable / Food Safe) and `satin`/`marble` out of the
seed unless a clean single ID exists.

## Bridge keyword → seed ID (config-overridable)

silk→17, matte→16, glitter→23, sparkle→23, glow→24, carbon→31, cf→31, glass→34, wood→41,
metal→46, metallic→46, translucent→19, transparent→20, high-speed→71, hs→71, rapid→71,
recycled→60.

## Before you start

- Read `CLAUDE.md`, `docs/spoolman-writes.md`, `docs/decisions.md`. Re-verify line numbers.
- Relevant existing code: `backend/app/core/color.py` (`sm_multicolor_to_fdb`,
  `_clear_arrangement_tags`/`_set_arrangement_tag`, `ARRANGEMENT_TAGS={28,29}`) — the
  optTags-preserving pattern to extend; `backend/app/core/matcher.py`
  (`extract_finish_line`, `_FINISH_PATTERNS`, `sm_variant_cluster_key`,
  `parsed_variant_line_keywords`); `backend/app/core/planner.py`
  (`_fdb_filament_payload_from_sm`); `backend/app/core/engine.py` (multicolor & cost
  filament-level passes — model the finish pass on these); `backend/app/services/spoolman.py`
  (`_REQUIRED_SPOOL_FIELDS`, `ensure_extra_fields`); `backend/app/config.py` (extra-field
  key names + new map config).

## Phase 1 — Map + extractor + Spoolman extra field

1. **Tag map** (`backend/app/core/` — e.g. a `material_tags.py`): a `MATERIAL_TAG_IDS`
   dict (keyword→id) seeded as above, **overridable** via a new config var
   (`MATERIAL_TAG_IDS`, CSV `keyword=id` pairs, parsed like `field_mappings`). Provide
   `finish_ids_from_text(name, material, keywords, map) -> set[int]` (extract ALL matching
   keywords → IDs, not just the first), and `strip_finish_words(material, keywords) -> str`
   (return base material with recognized finish words removed; never strip the core
   material like "PLA"/"PETG"/"PLA+"). Pure + unit-tested.
2. **Spoolman extra field**: add a filament-level extra field, default key
   `filamentdb_material_tags` (config var `SPOOLMAN_FIELD_FILAMENTDB_MATERIAL_TAGS`), and
   register it in `ensure_extra_fields` (Spoolman filament field:
   `POST /api/v1/field/filament/{key}`). It stores a JSON list of OpenPrintTag finish IDs.
   Update `docs/spoolman-writes.md`.

## Phase 2 — Write on import (SM→FDB), and the optTags helper

1. Extend `color.py` (or new helper) so finish IDs can be merged into `optTags` WITHOUT
   touching arrangement tags (28/29) or unknown tags: `apply_finish_tags(existing_opt_tags,
   finish_ids) -> list[int]` = (existing minus the managed finish-ID set) + finish_ids,
   preserving arrangement + unknown tags.
2. `planner._fdb_filament_payload_from_sm`: set `payload["type"] = strip_finish_words(...)`
   (base material) and `payload["optTags"] = apply_finish_tags(<arrangement from multicolor>,
   finish_ids_from_text(...))`. Keep the multicolor arrangement logic intact (merge, don't
   overwrite). Also stage the finish IDs to write into the new SM filament extra field on
   execute (so the SM side is structural going forward).

## Phase 3 — Ongoing bidirectional finish sync + flap-safe type compare

1. **Finish-stripped type/material comparison**: wherever the generic field sync compares
   FDB `type` ↔ SM `material`, compare the **finish-stripped base** on the SM side (so
   "PLA Silk" ⟺ FDB type "PLA" don't flap). The finish itself syncs separately (below).
2. **Finish pass** (model on the multicolor/cost filament-level passes in `engine.py`):
   per filament mapping, compute SM finish IDs (from the SM extra field, falling back to
   parsing material/name) and FDB finish IDs (the managed subset of `optTags`); route
   through `resolve_sync_action` with the `material_properties` direction+policy
   (both-changed → conflict `field_name="material_tags"`, deduped). PUSH_SM_TO_FDB →
   `update_filament(optTags=apply_finish_tags(...))`; PUSH_FDB_TO_SM →
   `update_filament(SM, {extra:{material_tags_field: encode_extra_value(json ids)}})`.
   Baseline-on-first-sight + merge the filament snapshot key (coexist with `_mc_sig`/`_cost`
   via the existing `_merge_snapshot`).

## Phase 4 — UI (optional, low-cost)

Show the finish tags as chips on Variances rows and/or Synced Records (map IDs back to
labels). Skip if it adds risk; note as follow-up.

## Conventions

- `code-checkin-and-pr`: `dev`, ONE `feat:` commit, no `Co-authored-by:`, docs in same
  commit. Never auto-resolve conflicts (policy-driven only). Don't touch arrangement tags
  here. Default behavior must not regress existing multicolor/cost/weight sync.

## Verification

- `cd backend && pytest` — tests: map parse/override; `finish_ids_from_text` (multi-tag,
  none); `strip_finish_words` (keeps PLA/PETG/PLA+); `apply_finish_tags` preserves 28/29 +
  unknown tags and replaces only managed finish ids; import sets type=base + finish optTags;
  finish-stripped type compare doesn't flap ("PLA Silk" vs "PLA"+17); finish pass both
  directions + conflict + snapshot coexistence; `ensure_extra_fields` registers the filament
  field.
- `cd frontend && npx tsc --noEmit && npm run build` if Phase 4 touched.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md` + `docs/spoolman-writes.md`: OpenPrintTag finish model, the new
   `filamentdb_material_tags` filament extra field, finish-stripped type comparison, the
   config-overridable map.
3. Non-interactive subagent run: when pytest (+ any build) passes, stage ONLY the files this
   task touched (incl. prompt move + docs) and commit on `dev` with one `feat:` message.
   Never `git add -A`. Never push.
