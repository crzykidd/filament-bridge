# Spoolman writes reference

Every field filament-bridge writes to Spoolman, and when. The bridge interacts with
Spoolman in two contexts: **structural setup** (custom fields it registers) and **data
writes** (the one-time wizard import, and ongoing auto-sync cycles). The bridge only ever
uses documented Spoolman REST APIs; it never deletes Spoolman records.

## Custom extra fields the bridge registers

Created once at startup (`ensure_extra_fields()`). Key names are overridable via env vars.

**Spool-level extras** (`SPOOLMAN_FIELD_FILAMENTDB_ID`, `SPOOLMAN_FIELD_FILAMENTDB_PARENT_ID`,
`SPOOLMAN_FIELD_FILAMENTDB_SPOOL_ID`):

| Field key | Type | Purpose |
|---|---|---|
| `filamentdb_id` | text | FDB filament ID (cross-reference link) |
| `filamentdb_parent_id` | text | FDB variant parent ID |
| `filamentdb_spool_id` | text | FDB spool subdocument ID |

**Filament-level extras** (`SPOOLMAN_FIELD_FILAMENTDB_MATERIAL_TAGS` env var, default
`filamentdb_material_tags`; OpenTag identity fields `SPOOLMAN_FIELD_OPENPRINTTAG_SLUG`
/ `SPOOLMAN_FIELD_OPENPRINTTAG_UUID`, defaults `openprinttag_slug` / `openprinttag_uuid`):

| Field key | Type | Purpose |
|---|---|---|
| `filamentdb_material_tags` | text | OpenPrintTag finish IDs as a CSV string (e.g. `17` for silk, `16,17`), JSON-quoted on the wire like all text extras |
| `openprinttag_slug` | text | OpenPrintTag material slug (e.g. `buddy3d-pla-silk-bronze`) — written by the OpenTag cleanup tool Apply action |
| `openprinttag_uuid` | text | OpenPrintTag material UUID — written by the OpenTag cleanup tool Apply action |
| `openprinttag_ignore` | text | `"1"` when the user has suppressed future update alerts for this filament via the Updates Review view; empty string = not ignored |

All extras are stored JSON-encoded (`encode_extra_value`). Everything below writes native
Spoolman fields or these extras.

## Ongoing auto-sync writes (per cycle, change-driven)

These are **Filament DB → Spoolman** writes. Each fires only when the category's
configured **sync direction + conflict policy** routes the change to Spoolman (two-way
lone change, one-way FDB→SM, or an FDB-winning conflict policy). See
[the sync direction/conflict model](decisions.md).

| Entity | Field(s) | Trigger |
|---|---|---|
| Spool | `remaining_weight` (net; converted from FDB gross via `fdb_to_spoolman_net`) | Weight sync resolves FDB→SM for the pair |
| Filament | `color_hex`, `multi_color_hexes`, `multi_color_direction` | Multicolor sync resolves FDB→SM (Filament DB ≥ 1.33.0) |
| Filament | `price` | Cost sync resolves FDB→SM (filament price only — never per-spool price) |
| Filament | `settings_bed_temp` | Temperature sync resolves FDB→SM (from FDB `temperatures.bed`) |
| Filament | `settings_extruder_temp` | Temperature sync resolves FDB→SM (from FDB `temperatures.nozzle`) |
| Filament | `material` | Native-scalar sync (FR-11 Phase A) resolves FDB→SM (`type` → `material` name remap) |
| Filament | `density` | Native-scalar sync resolves FDB→SM |
| Filament | `diameter` | Native-scalar sync resolves FDB→SM |
| Filament | `spool_weight` | Native-scalar sync resolves FDB→SM (from FDB `spoolWeight`) |
| Filament | `weight` | Native-scalar sync resolves FDB→SM (from FDB `netFilamentWeight`) |
| Filament | `extra.filamentdb_material_tags` | Finish-tag sync resolves FDB→SM (Filament DB ≥ 1.33.0); CSV of OpenPrintTag IDs from FDB `optTags` |
| Spool | `extra.{mapped field}` | Generic field-mapping sync (FR-11) resolves FDB→SM; arbitrary mapped FDB fields stored as spool extras |

New-spool creation during a cycle (gated by `new_spool_sync_direction`):

| Entity | Op | Field(s) | Trigger |
|---|---|---|---|
| Spool | create | `filament_id`, `remaining_weight`, + the 3 cross-ref extras | A new FDB spool has no Spoolman counterpart |
| Spool | update | the 3 cross-ref extras | After creating an FDB spool from a new SM spool — links it back |

## Wizard initial-import writes (one-time, on Execute)

**Filament DB → Spoolman import direction:**

| Entity | Op | Field(s) |
|---|---|---|
| Vendor | create | `name` (deduplicated by normalized name) |
| Filament | create | `name`, `material`, `color_hex`, `density`, `spool_weight`, `vendor_id` |
| Spool | create | `filament_id`, `remaining_weight`, + 3 cross-ref extras |

**Spoolman → Filament DB import direction:**

| Entity | Op | Field(s) | Trigger |
|---|---|---|---|
| Spool | update | 3 cross-ref extras | After creating the FDB spool — links it back |
| Filament | update | `extra.filamentdb_material_tags` | Pass 2.6 — writes parsed finish-tag IDs (from SM name/material text) back so SM's extra field matches FDB's `optTags` |
| Filament | update | `material`, `density`, `diameter`, `settings_extruder_temp`, `settings_bed_temp`, `spool_weight` | Variances **reconcile write-back** — only fields the user corrected, and only where the value differs from current Spoolman |

For FDB spool creates: when the source SM spool is **archived**, the bridge sets `retired: true`
on the FDB spool payload so the archived state is preserved at import. Only the spool is
marked retired — the filament record is always created as a normal, non-retired filament.
`archived`/`retired` is set once at import and is NOT a synced field in ongoing auto-sync.

## Conflict-resolution writes (on-demand, human-approved)

Resolving a **master_divergence** conflict (`POST /api/conflicts/{id}/resolve` with an
`action`) is the one conflict type that writes upstream — the chosen action is the
authorisation (see `docs/conflicts.md`):

| Action | Entity | Op | Field(s) |
|---|---|---|---|
| `apply_all` | Filament | update | The diverged native field (`material`, `density`, `diameter`, `spool_weight`, `weight`, `settings_bed_temp`, `settings_extruder_temp`) on **every mapped Spoolman filament in the variant line** |
| `variant_override` / `ignore` | — | — | No Spoolman writes (FDB-only / no-op respectively) |

All other conflict types are record-only — resolving them performs no Spoolman writes.

## OpenTag cleanup tool writes (on-demand, on Apply)

`POST /api/openprinttag/apply` — the explicit user action that authorises these writes.
Only the fields the user confirmed (not marked "keep mine") are written.

| Entity | Op | Field(s) | Trigger |
|---|---|---|---|
| Filament | update | `name` | User confirmed the reviewable name field (defaults to the OpenTag material name) |
| Filament | update | `vendor` → `vendor_id` | User confirmed the Manufacturer field; the Manufacturer row surfaces whenever SM vendor and OpenTag brand differ by any visible character (including case-only). Resolved via find-or-create (`_ensure_vendor`): exact trimmed name match against existing vendors; creates a new vendor if no exact match. Re-points THIS filament only — existing vendor never renamed, other filaments never touched. A case-only diff intentionally creates a near-duplicate vendor (accepted trade-off). **This is the only OpenTag path that may CREATE a new Spoolman vendor.** |
| Filament | update | `material`, `color_hex`, `density`, `diameter`, `settings_extruder_temp`, `settings_bed_temp`, `multi_color_hexes`, `multi_color_direction` (any subset) | User confirmed in the review/confirm UI |
| Filament | update | `extra.filamentdb_material_tags` | User confirmed; JSON list of finish IDs from the OPTMaterial tags |
| Filament | update | `extra.openprinttag_slug`, `extra.openprinttag_uuid` | Always written for non-ignored filaments with a match |

After each SM write the apply endpoint also calls `FilamentDBClient.merge_filament_settings()`
to push `openprinttag_slug`/`openprinttag_uuid` into the linked FDB filament's `settings{}`
bag (scoped exception — see `docs/decisions.md`).

## What the bridge never writes to Spoolman

`location`, `lot_nr`, `archived`, `comment`, and **per-spool `price`** (cost write-back
targets the filament price only). The bridge never deletes Spoolman records.

**The bridge never sets both `color_hex` and `multi_color_hexes` on the same Spoolman
filament in a single PATCH.** Spoolman returns 422 if both are present simultaneously.
Multicolor writes use `multi_color_hexes` + `multi_color_direction` only; single-color
writes use `color_hex` only. This applies to both the ongoing sync passes and the OpenTag
apply endpoint.

## Notes

- **Weight is always net-converted** on the way in (`fdb_to_spoolman_net`), since FDB
  stores gross (filament + reel tare) and Spoolman stores net (filament only).
- **`spoolWeight` on FDB filament creates uses the wizard-resolved tare**, not raw
  `sm.spool_weight` (which is often NULL). The resolved tare follows the same chain
  used to compute the spool gross weight: user tare override → spool `spool_weight` →
  filament `spool_weight` → 200 g default. This ensures `spoolWeight` matches the tare
  actually used for `totalWeight`, so Filament DB's % bar is accurate from first import.
- The Variances reconcile write-back is the only place the bridge *corrects existing*
  Spoolman filament data; all ongoing-sync writes are change-driven.
- Cross-reference extras are always JSON-encoded via `encode_extra_value` / decoded via
  `decode_extra_value` — never written raw.
- **Stale cross-refs do not block spool creation.** A `filamentdb_spool_id` extra on a
  Spoolman spool only skips spool creation if that FDB spool id actually exists in the
  current FDB dataset. If the referenced spool is gone (DB wipe, deletion), the spool
  is treated as a new create and the stale cross-ref is overwritten on success.
