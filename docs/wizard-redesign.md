# Initial-Sync Wizard — Redesign Spec

**Status: IMPLEMENTED** (2026-06-04) — D1–D4 shipped.
See `docs/decisions.md` entry "2026-06-04 — Wizard variant-resolution redesign" for the
settled contract. This file is preserved as design context; decisions.md is authoritative.

Primary direction under discussion: **Spoolman → Filament DB** (`import_direction="spoolman"`).

---

## Why we're rethinking it

A walkthrough of the live flow (clearing Matches down to two filaments — ELEGOO **Brown**
and **Beige**, both PLA) exposed that the wizard's variant model is broken in a way that
small tweaks won't fix:

- The two filaments are obviously the same vendor + material, differing only by color —
  the textbook case for a Filament DB parent/variant group — yet they land as two
  **standalone** filaments, and Preview reports **Variant groups: 0**.
- There is no UI path to group them manually (the only grouping control lives *inside* an
  auto-detected group card, and none was detected).
- The wizard never loads Filament DB's existing state, so it can only ever create fresh,
  duplicate parents — it can't attach an incoming color to a parent line that already
  exists in FDB.
- Empty/depleted spools (63 in the test library) are flagged and shoved aside with no
  control over whether they come in.

## The conceptual model (the thing the old flow got wrong)

**Color lives at the filament level in *both* systems.** You cannot have "one filament
with a Brown spool and a Beige spool" — that record can't exist in Spoolman or Filament DB.

- **Spoolman:** filament = vendor + material + **color**. Brown and Beige are, by
  definition, two filaments, each with spools.
- **Filament DB:** color also lives on the filament. The thing that represents "ELEGOO
  PLA" *as a type* is the **parent**. Brown and Beige are **color variants** — each its
  own filament record with `parentId` → parent, one level deep. Spools attach to the
  *color* filament, never to the parent.

So the correct result for "Brown + Beige as variants" is:

```
ELEGOO PLA            ← parent (the "type"); holds shared print settings
├─ Brown   (variant)  ← filament record, holds the Brown spool(s)
└─ Beige   (variant)  ← filament record, holds the Beige spool(s)
```

Two filaments + two spools is *correct*. **Variant groups: 0** is the bug — they should
be linked under a parent. The existing "master = parent (a real filament, not synthesized)"
rule from the 2026-05-31 SM-keyed master-promote decision still holds: one color becomes
the parent, the others get `parentId` stamped at create time.

---

## Decisions so far (2026-06-03)

### D1 — Grouping key is `vendor + material` (drop the base-name requirement)

Today clustering keys on `(normalize_vendor, normalize_name(material), base_name)` where
`base_name` strips a color-word lexicon (see 2026-05-31 decision). That under-clusters:
Brown and Beige share no base word, so they never group.

**New key: `(vendor, material)`.** For Spoolman, *different colors under the same
vendor+material is the definition of a variant group* — color difference is the signal,
not an obstacle. All ELEGOO PLA colors suggest as one parent line.

Open: how to keep distinct *lines* apart (PLA vs PLA Matte vs PLA Silk vs PLA-CF). These
are often the same `material` string ("PLA") with the finish/line encoded in the name. See
Q1.

### D2 — Per-member exclude, driven by the print-settings conflict signal

Grouping two colors as variants asserts **they print the same** (FDB variants inherit the
parent's print settings). A color-changing or glow-in-the-dark filament may be the same
vendor+material on paper but print differently — it should *not* inherit, and belongs as
its own standalone parent.

- We already compute `sm_prop_conflicts` (material, density, spool_weight, extruder_temp,
  bed_temp) between a group's master and each member.
- The UI suggests the vendor+material group, **pre-flags** members whose settings diverge
  from the master, and offers a per-member **"don't include → standalone"** toggle.
- Excluded members become their own parent (a flat create). This is the user's
  glow-in-the-dark / color-changing escape hatch, driven by data rather than guesswork.

This extends the existing "editable membership; clusters are hints only" rule (2026-06-03
merged-Variances decision, point 5) — the new part is *pre-flagging* the likely-exclude
members instead of presenting every member as an equal default-in.

### D3 — Load Filament DB's existing state and resolve incoming colors against it

The wizard loads the FDB filament/variant tree once. Every incoming Spoolman color
resolves to one of three outcomes:

| Outcome | Condition | Action |
|---|---|---|
| **Link** | exact color already exists in FDB | link / update (this is what Matches does) |
| **Attach** | the parent *line* exists in FDB, this color doesn't | add as a **new variant** under the existing parent |
| **Create** | no match at all | create parent (or promote a master) + variant |

The key gap today: Variances only clusters the *incoming* Spoolman filaments among
themselves. It must instead show **existing FDB parents as attach targets** — "ELEGOO
Beige → add as a variant under your existing *ELEGOO PLA* parent" is a different, safer
action than "create a brand-new ELEGOO PLA parent." Matching (color identity) and variant
attachment (parent structure) are the same resolution problem and both need the FDB
picture.

### D4 — "Include empty/depleted spools" toggle, applied globally up front

An empty spool is still attached to a filament/color that may be worth importing, so the
toggle separates the color from the inventory record:

- **off** → still import the filament/color definitions; skip creating the empty spool
  *records* (no zero-weight clutter).
- **on** → bring the empty spool records in too.

Applied globally so all downstream counts respect it (fixes the confusing "63 empty active
spools" number). Placement (Direction step vs a small pre-filter) is Q3.

---

## Open questions

- **Q1 — Line separation within a vendor+material.** ✅ **Resolved (2026-06-04).**
  `extract_finish_line()` in `matcher.py` parses a finish/line token (silk, matte, satin, cf,
  glow, hs, marble, wood, metallic, multicolor/rainbow) from the filament name using word-boundary
  regexes. `sm_variant_cluster_key` extended to 3-tuple `(vendor, material, finish)`. FDB parent
  map keying updated to match. Groups show a violet finish badge. D2 `suggest_exclude` survives
  as a second-line guard for unlexiconed finishes. See `docs/decisions.md` "Part A/B" entry.
- **Q2 — Where attachment is decided.** Does "attach to existing FDB parent" (D3) surface
  on Matches, on Variances, or a merged resolution view? Leaning: Matches = color identity,
  Variances = parent/grouping incl. existing-parent attach targets.
- **Q3 — Empty-spool toggle placement** (Direction step vs dedicated pre-filter).
- **Q4 — Matches step formatting/clarity** (deferred polish — noted, not yet specified).
- **Q5 — Direction step source-of-truth** actually changing downstream behavior is
  untested; confirm it does what the UI implies.

## Proposed target flow (sketch — refine next session)

1. **Connectivity** — unchanged (works well).
2. **Direction** — direction + source-of-truth; possibly host the empty-spool toggle (Q3).
3. **Matches** — color-level identity resolution (Link vs Create), formatting cleanup (Q4).
4. **Variances** — vendor+material variant grouping with: pre-flagged per-member exclude
   (D2), existing-FDB-parent attach targets (D3), one tare per group/standalone (unchanged).
5. **Preview** — counts that reflect the real tree (parent lines, variants, spools) and
   honor the empty-spool toggle; flagged items surfaced read-only.
6. **Execute** — unchanged contract.

## Touch points (for when we build)

- `backend/app/core/matcher.py` — `sm_variant_cluster_key` (D1), `sm_prop_conflicts` (D2).
- `backend/app/api/wizard.py` — `wizard_variances` (D1/D2/D3), needs to load FDB filaments
  + variant tree (D3); `_included_sm_ids` / empty-spool filtering (D4).
- `frontend/src/pages/Wizard/StepVariances.tsx` — manual grouping + per-member exclude +
  attach-target UI.
- Existing related decisions: 2026-05-31 (SM-keyed master-promote), 2026-06-03 (merged
  Variances step). This spec extends both; it does not contradict the master=real-filament
  or clusters-are-hints rules.
</content>
</invoke>
