# Reconcile-phase backlog

Data-model mismatches surfaced by the first live end-to-end sync run (223 Spoolman spools
/ 175 filaments, 2026-05-30). These are genuine user-visible problems but belong in the
FR-4 match/reconcile UI — they cannot be silently resolved by the bridge. Each item is a
deferred handoff; none are built in Phase 5.

**Status as of 2026-05-31:** Items 1–4 are **surfaced (preview)** in
`GET /api/wizard/preview` (FR-4 foundation). Decision UI (FR-4 full) is pending. The
Dashboard dry-run (`POST /api/sync/dry-run`) now uses the same planner and correctly
reports create/update/conflict/skipped for ALL records regardless of bridge state.

## 1. Filament name uniqueness collisions (43 × 409)

Filament DB enforces a **unique filament name**; Spoolman allows duplicates across
vendors or materials (10 × "Black", 8 × "White", 7 × "Orange", etc.). 43 of 175
Spoolman filaments collide on import.

**Reconcile choice per collision:** rename the incoming filament (e.g. qualify with
vendor or material: "ELEGOO Black PLA") / merge into the existing FDB record / skip.
This is the single largest reconcile item.

## 2. Empty-but-active spools (63)

`remaining_weight == 0`, fully consumed, **not archived** in Spoolman. The bridge cannot
decide whether these should be imported.

**Reconcile choice per spool (or bulk):** import as empty / skip / treat as archived
(Spoolman supports an `archived` flag; the bridge could patch it on the user's behalf
after confirmation).

## 3. Default-tare spools (79)

No `spool_weight` set on the Spoolman filament → bridge substitutes the 200 g default,
so part of the imported gross weight is a guess.

FR-5 already supports per-spool/filament tare override. The reconcile UI should **flag**
default-tare rows and allow the user to confirm/correct the tare before execute so the
imported gross weights are accurate.

## 4. Variant grouping on fresh import

FR-6 variant grouping only analyses *matched* (pre-existing) FDB filaments, so it
returns zero groups when the target FDB database is empty. Decide whether to also group
the *to-be-created* filaments during initial import, keyed by vendor + material with
color stripped — this would let the bridge set `parentId` at create time rather than
requiring a second reconcile pass.

## 5. Multicolor filaments (29) — SPECCED, not deferred

Filament DB is single-color; 29/175 Spoolman filaments are multicolor
(`multi_color_hexes` + `coaxial`/`longitudinal`). Unlike items 1–4 this one is **already
decided and has its own handoff prompt** — see the "Multicolor filament mapping" entry in
`docs/decisions.md` and `prompts/2026-05-30-multicolor-colorname-mapping.md`. Summary: keep
Spoolman authoritative, project primary `color_hex` → FDB `color` + a configurable
`colorName` string, and protect Spoolman's multicolor fields from being overwritten on
write-back. Listed here so the issue inventory from the first live run stays complete.
