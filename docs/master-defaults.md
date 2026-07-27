# Master Defaults

The **Master Defaults** screen (nav: *Master Defaults*, route `/master-defaults`) is a manual
review-and-fill tool for six shared-property fields on **master/container filaments** — tare
(empty-reel weight), nozzle temp, bed temp, density, diameter, and material — that predate the
[master-seeding feature](decisions.md) (issue #76) or were otherwise created without them.

## Background

A "master" is a variant-family parent: either a real Filament DB filament with `hasVariants: true`
(the [`promote_color`](variant-parent-mode.md) mode) or a bridge-owned synthetic **container**
parent (`generic_container` mode, no Spoolman counterpart). Filament DB's parent/variant
inheritance means a variant with no own value for one of these six fields inherits the master's —
so a master with a blank tare or temp leaves every variant that hasn't been explicitly overridden
without one either, and the wizard's merge/reconcile flows keep re-asking for values the family
already collectively knows.

Newly-created masters (via the wizard or a Conflicts "Add") are seeded automatically with the
**mode** (most-common value) across the cluster at creation time — see
[`CHANGELOG.md`](../CHANGELOG.md) for the release that shipped it. This screen is the backfill for
everything created **before** that: it never writes automatically, and a value the master already
holds is **never** overwritten.

## What it shows

One card per master (real or synthetic), each with a badge (**Master** / **Synthetic container**),
vendor, and variant count. Within a card, one row per field that is **fillable** — the master's own
value is null AND its variant children agree on a value (the modal/majority value, deterministic
lowest-value tie-break). Each row shows the field label, the proposed value, and how many variants
(and which ones) contributed to it. A master with nothing fillable collapses to a single "Nothing
to fill" line; toggle **Only masters with something to fill** off to see it anyway.

A field the family doesn't actually agree on (every variant has a different value, or none has a
value at all) is never proposed — the row-builder omits it, it never shows as fillable.

## Applying

Tick the fields you want to fill (per row, or the master-level checkbox to select every fillable
field for that master) and click **Apply N fields**. Nothing is written until you do. On success,
successfully-applied masters clear their selection and the list refreshes; any failures are listed
with their error and the master stays selectable to retry.

Write semantics mirror the [Tare Editor](tare-editor.md)'s `apply_tare`:

- **Fill-null-only** — a field is only ever written when the master's own value is null; an
  already-set value (on either the Filament DB or, for a real master, the paired Spoolman side) is
  never overwritten.
- **Both sides, when there is a Spoolman side** — a real (`promote_color`) master has a live
  Spoolman filament and gets written on both sides, like any other material-property field. A
  synthetic container has no Spoolman counterpart, so only the Filament DB side is written.
- **Snapshot refresh** — after a write, both sides' `_mp_<field>` sync baselines are refreshed to
  the post-write agreed value (the same anti-ping-pong pattern used everywhere else propagation
  happens — see [sync-model.md](sync-model.md#snapshots-and-anti-ping-pong)), so the next sync
  cycle doesn't re-detect the fill as drift.
- **Variant inheritance does the rest** — writing the master's field is enough; a variant with no
  own value already inherits it in Filament DB, and the engine's material-scalar pass mirrors that
  inheritance to the variant's Spoolman counterpart on the next cycle.
- **Hard-gated on upstream compatibility** — like the Tare Editor and wizard execute, applying is
  refused (HTTP 409) when either upstream is below its
  [minimum supported version](sync-model.md#version-gating).

## API

- `GET /api/masters/defaults` → one row per master: `filamentdb_id`, `name`, `vendor`,
  `is_synthetic`, `spoolman_filament_id` (null for a synthetic container), `variant_count`, and
  `fields` — a map of the six canonical field keys (`spool_weight`, `nozzle_temp`, `bed_temp`,
  `density`, `diameter`, `type`) to `{ current, current_sm, proposal, would_fill, breakdown[] }`.
- `POST /api/masters/defaults/apply` — body `{ updates: [{ filamentdb_id, fields: [...] }] }`;
  returns `{ updated, failed[] }`. A field in the request that is no longer `would_fill` (e.g. a
  stale retry after a prior apply already filled it) is silently skipped, not an error.

Both are auth-gated.
