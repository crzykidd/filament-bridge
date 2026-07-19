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
   (with embedded spools) are fetched. The archived-spool filter is **split by purpose**:
   *new-spool detection* uses the active-only set (so an unmapped archived spool is never
   auto-imported — the wizard import gate is preserved), while *mapped-pair diffing* uses
   the active + archived set (so a mapped spool that flips to archived still reaches the
   differ and its lifecycle state can be mirrored).
3. **Stale-filament-mapping GC.** Any `FilamentMapping` whose Spoolman filament is no longer
   in the fetched set is purged (with the filament's now-defunct spool mappings). Spoolman
   reuses deleted integer ids (SQLite rowid, no `AUTOINCREMENT`), so a mapping kept past its
   filament's deletion could later be silently re-pointed at an unrelated filament that reuses
   the freed id — this drops it before that can happen. Bridge-local only; runs only after a
   successful upstream fetch (a partial fetch never triggers a purge). See
   [upstream-apis.md](upstream-apis.md) (Spoolman id reuse) and decisions.md 2026-07-19 (#70).
4. **Mapped-pair processing.** For every `SpoolMapping`, the pair's current values are
   diffed against the last stored snapshots. First sight of a pair just stores a baseline
   (no writes). Then the weight pass, the **lifecycle (archive/retire) pass** (after
   weight — see below), the **location pass**, and the field-mapping pass run per pair.
5. **Stale-link handling.** A mapped record missing upstream either queues a deletion
   conflict (a live, still-linked counterpart exists) or purges the bridge-local mapping
   (nothing left to protect). See [conflicts.md](conflicts.md).
6. **Filament-level passes.** Multicolor, cost, temperatures, native scalars, and finish
   tags run over filament mappings.
7. **New-record detection.** The engine detects unmapped filaments and spools on both sides
   and handles them according to the two-tier new-record policy (see below).
8. **OpenTag identity push.** `openprinttag_slug`/`uuid` from Spoolman extras are merged
   into the linked FDB filament's `settings{}` bag (the one approved exception to the
   "never touch settings" rule).
9. Everything is written to the sync log under one cycle ID.

A **dry run** computes the same changeset without writing or advancing snapshots, and the
Dashboard dry-run additionally plans what the wizard would do for unlinked records.

## Direction + conflict policy resolution

Every change is routed through `resolve_sync_action(sm_changed, fdb_changed, direction,
policy)`:

| Situation | one-way (source changed) | one-way (locked side changed) | two_way |
|---|---|---|---|
| One side changed | push | NOOP (drift ignored) | push to the other side |
| Both sides changed | push (source wins by definition) | — | apply the conflict policy: `manual` → queue, `spoolman_wins`/`filamentdb_wins` → push, `newest_wins` → compare timestamps (weight only; indeterminate → queue) |

Weight uses the `weight` category settings; the lifecycle pass uses the `archive_sync`
category; the location pass uses the `location_sync` category; every other pass uses
`material_properties`. New-spool creation has a direction but no policy.

### Why the lifecycle pass runs after the weight pass

A spool is usually archived/retired right as it hits ~0 g, so the depletion (final weight
decrement) and the lifecycle flip often arrive in the **same** cycle. The weight pass must
settle first: it propagates the final decrement, logs the FDB usage-log audit entry
(`POST …/usage`, `source:"spoolman"`), and refreshes both snapshots — *before* the lifecycle
pass mirrors the archive/retire bit. Mirror first and the far side would land
retired/archived carrying a stale (too-high) weight with its final usage entry lost. (A
spool already dead on both sides from a prior cycle NOOPs the weight pass naturally, since
its snapshots already converged — no special skip is needed.) After any lifecycle push the
engine refreshes **both** snapshots' lifecycle bits to the converged value, the same
anti-ping-pong invariant the weight pass follows; a both-sides-flip-to-same-state case
writes nothing but still refreshes both snapshots so it doesn't re-fire next cycle.

## The passes

| Pass | What syncs | Notes |
|---|---|---|
| **Weight** | SM `remaining_weight` ↔ FDB spool `totalWeight` | SM→FDB decrements are logged as **usage entries** (audit trail preserved); increases update `totalWeight` directly. FDB→SM writes `remaining_weight = totalWeight − tare`. Changes below `sync_weight_threshold_grams` (default 2 g) are ignored. |
| **Lifecycle (archive/retire)** | SM spool `archived` ↔ FDB spool `retired` | Boolean mirror for **mapped pairs only**, runs **after** the weight pass. A one-sided flip (either direction, archive or un-archive) is a clean push; both sides flipping to the *same* state converges silently; only a both-sides-flip-to-*opposite*-states divergence queues a `cross_system` conflict with `field_name="lifecycle"`. Uses the `archive_sync` category (`archive_sync_direction` / `archive_conflict_policy`); `newest_wins` is not applicable to a boolean. |
| **Location** | SM spool `location` (free-text name) ↔ FDB spool `locationId` (resolved to its **name**) | Compared **by name** for **mapped pairs only**. Spoolman stores the location as a string; Filament DB references a location by id, so the bridge resolves `locationId` → name (one `GET /api/locations` per cycle) to diff and **finds-or-creates** the matching FDB location on a SM→FDB push (`core/locations.py:ensure_fdb_location`). A one-sided change is a clean push; both sides changing to the *same* name converges silently; both changing to *different* names queues a `cross_system` conflict with `field_name="location"`. Uses the `location_sync` category (`location_sync_direction` / `location_sync_conflict_policy`); `newest_wins` is not applicable (a name has no timestamp). Independent of weight — no ordering requirement. |
| **Field mapping** | configured/auto-matched Spoolman *extra* fields ↔ FDB fields | `FIELD_MAPPINGS` / exact-name auto-match; inherited FDB variant fields are skipped (writing them would detach the variant from its parent). |
| **Cost** | SM effective price ↔ FDB `cost` | SM side uses the first spool with a price, falling back to the filament price; FDB→SM writes the *filament* price only — never per-spool prices. |
| **Temperatures** | SM `settings_bed_temp` / `settings_extruder_temp` ↔ FDB `temperatures.bed` / `.nozzle` | FDB writes read-modify-write the `temperatures` object so sibling temps survive. |
| **Native scalars** | SM `material`/`density`/`diameter`/`spool_weight`/`weight` ↔ FDB `type`/`density`/`diameter`/`spoolWeight`/`netFilamentWeight` | SM→FDB writes are **master/variant-gated**: a value that would override an *inherited* variant field queues a master-divergence conflict instead of writing (see [conflicts.md](conflicts.md)). |
| **Multicolor** | SM `color_hex`/`multi_color_hexes`/`multi_color_direction` ↔ FDB `color`/`secondaryColors`/arrangement `optTags` | Compared via a system-agnostic signature. Requires FDB ≥ 1.33.0. The bridge never sends `color_hex` and `multi_color_hexes` in the same Spoolman PATCH (422). |
| **Finish tags** | FDB `optTags` (managed finish subset) ↔ SM extra `filamentdb_material_tags` | Managed IDs only (silk/matte/CF/…); arrangement tags (28/29) and unknown tags pass through untouched. Requires FDB ≥ 1.33.0. |
| **New spools** | spool creation in the opposite system | Carries weight (converted), cross-reference IDs, and purchase/opened provenance dates. |
| **Orphan re-adoption** | a Spoolman spool that has a live FDB cross-reference (`filamentdb_spool_id`) but **no bridge `SpoolMapping`** | Runs inside the new-SM-spool handling (`engine.py:_reconcile_orphan_spool`). Instead of silently skipping such an *orphan* (which had made it invisible to Synced Records / Mobile forever), the engine **recreates the missing mapping** when the target FDB spool is unclaimed — so pre-existing orphans (e.g. after a bridge-state reset that clears mappings while upstream cross-refs survive) auto-heal each cycle, logged as a `link`. If the target FDB spool is already mapped to a *different* SM spool (collision), it is **not** adopted — it falls through to normal new-spool handling (a visible `new_spool` conflict or its own FDB spool). A stale cross-ref (target spool gone) also falls through, and the re-import overwrites the dangling id. See decisions.md 2026-06-28 (#48). |
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

## New-record hierarchy (filament → spool)

A **filament is a container**. Sync flows top-down: a spool can only be created in the
target system once its filament exists and is mapped. This gives two independent policy
tiers:

### Filament tier (`new_filament_policy`)

When the engine detects an unmapped filament (Spoolman or Filament DB side):

- **`manual_review`** (default): queues a `new_filament` conflict. Actionable — the
  Conflicts page "Add" button calls `POST /api/conflicts/{id}/import` to create the
  filament and write the mapping without leaving the page.
- **`auto_import`**: immediately creates the filament on the other side using the same
  code path as the Bulk Import Wizard (`app/core/single_record_import.py`), writes the
  `FilamentMapping` and cross-reference IDs, then snapshots both sides to prevent ping-pong
  (see anti-ping-pong below). **Exception:** if `variant_parent_mode` is `unset` and the
  filament appears to belong to a variant cluster, the engine falls back to `manual_review`
  — auto-grouping without a chosen parent mode would produce an uncorrectable hierarchy.

### Spool tier (`new_spool_policy`)

After the filament is mapped, the engine handles each new spool:

- **`manual_review`** (default): queues a `new_spool` conflict.
- **`auto_import`**: creates the spool immediately on the other side.

A spool whose filament is **not yet mapped** is always held regardless of `new_spool_policy`
— the filament must be resolved first. The engine queues a `new_filament` conflict for the
filament and does not touch the spool until the filament is mapped.

Both policies default to `manual_review` — new records never appear silently without a
conflict entry in the queue.

### Anti-ping-pong after auto-create

After any auto-create, the engine refreshes **both** sides' snapshots to the agreed
post-create state. Without this, the newly created record would look like a fresh change
on the destination side next cycle and be re-queued. This is the same FR-11 post-write
refresh invariant that applies to all other write passes. Covered by
`test_auto_import_no_pingpong`.

## Version gating

`core/version.py` defines `MIN_FDB = 1.33.0` and `MIN_SPOOLMAN = 0.22.0`. A known
below-minimum upstream hard-blocks: the trigger/dry-run endpoints and wizard execute return
`409 upstream_version_unsupported`, auto-sync can't be enabled, and scheduled cycles no-op.
The Dashboard shows the reasons. Structured multicolor and finish-tag passes additionally
gate on FDB ≥ 1.33.0 individually.
