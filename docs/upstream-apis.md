# Upstream APIs — endpoints & data-model gotchas

Reference for the two upstream REST APIs the bridge talks to. Both are unauthenticated by
default (Filament DB can be given an optional bearer key via `FILAMENTDB_API_KEY`). The
bridge never modifies upstream source — integration is via these documented endpoints and
Spoolman's extra-field system only.

- Filament DB — Next.js/MongoDB, REST at `/api/`, **gross** weight model, MongoDB ObjectIds,
  spools embedded on filaments. [API docs](https://github.com/hyiger/filament-db/blob/main/docs/api.md)
- Spoolman — Python/FastAPI, REST at `/api/v1/`, **net** weight model, relational
  Vendor → Filament → Spool with int IDs. [API docs](https://donkie.github.io/Spoolman/)

## Filament DB endpoints the bridge uses

- `GET /api/filaments` — list all filaments with embedded spools
- `GET /api/filaments/:id` — single filament with full detail
- `POST /api/filaments` — create filament (set `parentId` for variants)
- `PUT /api/filaments/:id` — update filament properties
- `GET /api/spools/export-csv` — all active spools with labels, weights, locations
- `POST /api/spools/import` — bulk spool CSV import (columns: filament, vendor, totalWeight, label, lotNumber, location)
- `POST /api/filaments/:id/spools` — add a single spool to a filament
- `PUT /api/filaments/:id/spools/:spoolId` — update spool properties
- `POST /api/filaments/:id/spools/:spoolId/usage` — log usage `{ grams, jobLabel, source, date }`
- `POST /api/print-history` — log print job with multi-spool usage array
- `GET /api/filaments/:id/spool-check?weight=N` — check if spool has enough filament
- `GET /api/locations` — list locations (add `?stats=true` for spool counts/grams)
- `PUT /api/locations/:id` — update location properties (e.g., humidity)
- `DELETE /api/filaments/:id` — soft-delete only (sets `_deletedAt`)

## Spoolman endpoints the bridge uses

- `GET /api/v1/spool?limit=1000` — list spools (**MUST set limit**, default paginates)
- `GET /api/v1/spool/{id}` — single spool with nested filament and vendor
- `PATCH /api/v1/spool/{id}` — update spool (remaining_weight, extra fields, location, etc.)
- `POST /api/v1/spool` — create spool (requires filament_id)
- `GET /api/v1/filament` — list filaments with nested vendor
- `GET /api/v1/filament/{id}` — single filament
- `POST /api/v1/filament` — create filament
- `GET /api/v1/vendor` — list vendors
- `POST /api/v1/vendor` — create vendor
- `GET /api/v1/export/spools?fmt=csv` — CSV export (all spools, no pagination limit)
- `PUT /api/v1/spool/{id}/use` — decrement weight (used by OctoPrint/Moonraker, **NOT** by bridge)
- **Archived spools are EXCLUDED from `/api/v1/spool` by default.** Pass
  `?allow_archived=true` to include them (returns active + archived in one listing). There is
  NO `archived` filter param — an unknown `?archived=true` is silently ignored and returns the
  active-only list (this once hid archived spools from the bridge, making archived mapped
  spools look deleted).

## Filament DB data-model gotchas

- Spools are embedded subdocuments in the `spools[]` array on the filament document — there is
  no standalone spool collection or endpoint. Every spool operation goes through
  `/api/filaments/:filamentId/spools/:spoolId`.
- No spool label lookup endpoint — to find a spool by label, fetch all filaments or use the CSV
  export and filter client-side.
- Variant deletion is blocked (400) if the parent still has variants — must remove/reassign
  variants first.
- `DELETE /api/filaments/:id` is a soft-delete (sets `_deletedAt`), not permanent. Returns 400
  if the filament has variants.
- The `settings{}` bag on filaments is a passthrough for slicer-specific keys — unknown keys
  round-trip without modification. Don't touch this in sync, except via the scoped
  `merge_filament_settings()` path for the two OpenTag identity keys (see CLAUDE.md "What NOT
  to do").
- The `spoolWeight` and `netFilamentWeight` fields are on the FILAMENT, not individual spools.
  All spools of the same filament share the same tare weight.
- Spool subdocument `_id` values are stable across filament updates (Mongoose doesn't
  regenerate them on parent save).

## Spoolman data-model gotchas

- Extra fields must be created via the Spoolman API or UI BEFORE they can be written to on a
  spool/filament. The bridge checks for required extra fields on startup and warns if missing.
- `GET /api/v1/spool` paginates — the default limit may not return all spools. Always pass
  `?limit=1000` or implement pagination.
- Vendor deduplication is extremely common — the same vendor appearing with different IDs due
  to case differences ("ELEGOO" vs "Elegoo"), whitespace, or duplicate manual entries. The
  bridge matcher handles this.
- Spoolman spool has `remaining_weight` (current net) and `used_weight` (total consumed).
  OctoPrint calls `PUT /api/v1/spool/{id}/use` which decrements remaining and increments used.
- **A spool's `remaining_weight` can only be set if its filament has a `weight` (net full-spool
  weight) set** — otherwise `POST /api/v1/spool` fails with `400`. Spoolman also derives
  `used_weight = weight − remaining_weight` and refuses a negative "used", so if the filament
  `weight` is *below* a spool's actual net it **clamps** the remaining down (losing filament).
  When creating a Spoolman filament from FDB, send `weight` = **max**(FDB `netFilamentWeight`,
  largest net gross−tare across its spools) — a spool can legitimately hold more than the
  nominal (overfilled reels), so the max keeps every spool's remaining from being clamped.
- Spoolman filament has `spool_weight` (tare) which may or may not be set. Default to ~200 g if
  missing during weight conversion.
- **Spoolman reuses deleted integer ids.** Filaments/spools use a plain SQLite integer primary
  key (no `AUTOINCREMENT`), so deleting the *highest* id makes the next create reissue it. If the
  bridge ever deletes an upstream record but leaves its cross-reference mapping behind, a later
  create can be handed the reused id and collide on `UNIQUE(spoolman_filament_id)`. The
  FDB→Spoolman create path clears any stale mapping on a just-minted id before inserting the new
  one (`_execute_fdb_to_spoolman`); when cleaning up orphan Spoolman records, also drop the
  corresponding bridge mapping so it can't be resurrected onto a reused id.

## Deep links (UI requirement)

Every record in the bridge UI shows two clickable icons linking to that record in each upstream
system. Routes verified against live instances (see `docs/decisions.md`):

- Filament DB: `{FILAMENTDB_URL}/filaments/{filamentdb_id}` (plural). Filament DB has **no
  standalone spool page** — spools render under the filament page, so spool rows link to the
  parent filament URL.
- Spoolman: `{SPOOLMAN_URL}/spool/show/{spoolman_spool_id}` or
  `{SPOOLMAN_URL}/filament/show/{spoolman_filament_id}` (no hash routing).
- URLs are built from the `FILAMENTDB_URL` and `SPOOLMAN_URL` env vars. Open in new tabs.
