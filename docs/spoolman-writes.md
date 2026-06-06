# Spoolman writes reference

Every field filament-bridge writes to Spoolman, and when. The bridge interacts with
Spoolman in two contexts: **structural setup** (custom fields it registers) and **data
writes** (the one-time wizard import, and ongoing auto-sync cycles). The bridge only ever
uses documented Spoolman REST APIs; it never deletes Spoolman records.

## Custom extra fields the bridge registers

Created once at startup (`ensure_extra_fields()`), on the **spool** entity. Key names are
overridable via env vars (`SPOOLMAN_FIELD_FILAMENTDB_ID`,
`SPOOLMAN_FIELD_FILAMENTDB_PARENT_ID`, `SPOOLMAN_FIELD_FILAMENTDB_SPOOL_ID`):

| Field key | Type | Purpose |
|---|---|---|
| `filamentdb_id` | text | FDB filament ID (cross-reference link) |
| `filamentdb_parent_id` | text | FDB variant parent ID |
| `filamentdb_spool_id` | text | FDB spool subdocument ID |

These three extras are the only additions to Spoolman's schema. They are stored
JSON-encoded (`encode_extra_value`). Everything below writes native Spoolman fields or
these extras.

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
| Filament | update | `material`, `density`, `diameter`, `settings_extruder_temp`, `settings_bed_temp`, `spool_weight` | Variances **reconcile write-back** — only fields the user corrected, and only where the value differs from current Spoolman |

## What the bridge never writes to Spoolman

`location`, `lot_nr`, `archived`, `comment`, and **per-spool `price`** (cost write-back
targets the filament price only). The bridge never deletes Spoolman records.

## Notes

- **Weight is always net-converted** on the way in (`fdb_to_spoolman_net`), since FDB
  stores gross (filament + reel tare) and Spoolman stores net (filament only).
- The Variances reconcile write-back is the only place the bridge *corrects existing*
  Spoolman filament data; all ongoing-sync writes are change-driven.
- Cross-reference extras are always JSON-encoded via `encode_extra_value` / decoded via
  `decode_extra_value` — never written raw.
