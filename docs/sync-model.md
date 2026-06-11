# The sync engine

How a sync cycle works, what data flows in each pass, and the invariants that keep two-way
sync stable. Code: `backend/app/core/engine.py` (cycle), `core/sync_policy.py` (resolver),
`core/differ.py` (change classification).

## One cycle, end to end

Every cycle (scheduled, or via **Sync now**):

1. **Version gate.** Both upstream versions are read. If a *known* version is below the
   minimum (Filament DB 1.33.0 / Spoolman 0.22.0), the cycle is refused — no reads beyond
   the version check, no writes. An unknown version does not block (that's a connectivity
   concern, surfaced as `degraded` health).
2. **Snapshot fetch.** All Spoolman spools + filaments and all Filament DB filaments
   (with embedded spools) are fetched. Archived Spoolman spools are excluded from sync.
3. **Mapped-pair processing.** For every `SpoolMapping`, the pair's current values are
   diffed against the last stored snapshots. First sight of a pair just stores a baseline
   (no writes). Then the weight pass and the field-mapping pass run per pair.
4. **Stale-link handling.** A mapped record missing upstream either queues a deletion
   conflict (a live, still-linked counterpart exists) or purges the bridge-local mapping
   (nothing left to protect). See [conflicts.md](conflicts.md).
5. **Filament-level passes.** Multicolor, cost, temperatures, native scalars, and finish
   tags run over filament mappings.
6. **New-spool detection.** Unmapped spools on either side are created on the other (or
   queued as a `new_spool` notice when no filament mapping exists), gated by the
   new-spool direction.
7. **OpenTag identity push.** `openprinttag_slug`/`uuid` from Spoolman extras are merged
   into the linked FDB filament's `settings{}` bag (the one approved exception to the
   "never touch settings" rule).
8. Everything is written to the sync log under one cycle ID.

A **dry run** computes the same changeset without writing or advancing snapshots, and the
Dashboard dry-run additionally plans what the wizard would do for unlinked records.

## Direction + conflict policy resolution

Every change is routed through `resolve_sync_action(sm_changed, fdb_changed, direction,
policy)`:

| Situation | one-way (source changed) | one-way (locked side changed) | two_way |
|---|---|---|---|
| One side changed | push | NOOP (drift ignored) | push to the other side |
| Both sides changed | push (source wins by definition) | — | apply the conflict policy: `manual` → queue, `spoolman_wins`/`filamentdb_wins` → push, `newest_wins` → compare timestamps (weight only; indeterminate → queue) |

Weight uses the `weight` category settings; every other pass uses `material_properties`.
New-spool creation has a direction but no policy.

## The passes

| Pass | What syncs | Notes |
|---|---|---|
| **Weight** | SM `remaining_weight` ↔ FDB spool `totalWeight` | SM→FDB decrements are logged as **usage entries** (audit trail preserved); increases update `totalWeight` directly. FDB→SM writes `remaining_weight = totalWeight − tare`. Changes below `sync_weight_threshold_grams` (default 2 g) are ignored. |
| **Field mapping** | configured/auto-matched Spoolman *extra* fields ↔ FDB fields | `FIELD_MAPPINGS` / exact-name auto-match; inherited FDB variant fields are skipped (writing them would detach the variant from its parent). |
| **Cost** | SM effective price ↔ FDB `cost` | SM side uses the first spool with a price, falling back to the filament price; FDB→SM writes the *filament* price only — never per-spool prices. |
| **Temperatures** | SM `settings_bed_temp` / `settings_extruder_temp` ↔ FDB `temperatures.bed` / `.nozzle` | FDB writes read-modify-write the `temperatures` object so sibling temps survive. |
| **Native scalars** | SM `material`/`density`/`diameter`/`spool_weight`/`weight` ↔ FDB `type`/`density`/`diameter`/`spoolWeight`/`netFilamentWeight` | SM→FDB writes are **master/variant-gated**: a value that would override an *inherited* variant field queues a master-divergence conflict instead of writing (see [conflicts.md](conflicts.md)). |
| **Multicolor** | SM `color_hex`/`multi_color_hexes`/`multi_color_direction` ↔ FDB `color`/`secondaryColors`/arrangement `optTags` | Compared via a system-agnostic signature. Requires FDB ≥ 1.33.0. The bridge never sends `color_hex` and `multi_color_hexes` in the same Spoolman PATCH (422). |
| **Finish tags** | FDB `optTags` (managed finish subset) ↔ SM extra `filamentdb_material_tags` | Managed IDs only (silk/matte/CF/…); arrangement tags (28/29) and unknown tags pass through untouched. Requires FDB ≥ 1.33.0. |
| **New spools** | spool creation in the opposite system | Carries weight (converted), cross-reference IDs, and purchase/opened provenance dates. |
| **OpenTag identity** | SM extras `openprinttag_slug`/`uuid` → FDB `settings{}` | Merge-only, idempotent, scoped to those two keys. |

## Weight model

Spoolman stores **net** filament weight; Filament DB stores **gross** (filament + empty-reel
tare, the filament-level `spoolWeight`). Conversions:

- SM → FDB: `totalWeight = remaining_weight + tare`
- FDB → SM: `remaining_weight = totalWeight − tare`

`totalWeight` already reflects logged usage — Filament DB reduces it when a usage entry is
posted — so usage history is **never** subtracted on top (doing so double-counted and caused
a runaway decrement loop; fixed 2026-06-10). When no tare is known anywhere, a 200 g default
is used and flagged.

## Snapshots and anti-ping-pong

The bridge stores one snapshot per record per side. Change detection is always
*current value vs my own side's last snapshot* — never a cross-system comparison — so the
two systems' different representations can't generate phantom changes.

Two invariants prevent feedback loops:

1. **Post-write refresh:** after any successful write, **both** sides' snapshots are set to
   the agreed post-write value. Otherwise the propagated change would look like a fresh
   change on the destination next cycle and bounce back forever.
2. **Baseline on first sight:** a pair (or a field key) seen for the first time stores a
   baseline and does nothing. Differences that existed before the bridge ever saw the pair
   are not "changes" — they surface only when one side actually moves.

Filament-level passes share one snapshot row per filament per side; each pass keeps its own
keys (`_mc_sig`, `_cost`, `_mp_<field>`, `_finish_sig`) via a merge-write so they never
clobber each other.

## Version gating

`core/version.py` defines `MIN_FDB = 1.33.0` and `MIN_SPOOLMAN = 0.22.0`. A known
below-minimum upstream hard-blocks: the trigger/dry-run endpoints and wizard execute return
`409 upstream_version_unsupported`, auto-sync can't be enabled, and scheduled cycles no-op.
The Dashboard shows the reasons. Structured multicolor and finish-tag passes additionally
gate on FDB ≥ 1.33.0 individually.
