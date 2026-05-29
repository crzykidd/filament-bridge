# filament-bridge

Bidirectional sync between [Filament DB](https://github.com/hyiger/filament-db) and [Spoolman](https://github.com/Donkie/Spoolman) for 3D printing filament management.

## Why?

Filament DB and Spoolman are both excellent tools that solve different parts of the filament management problem:

- **Filament DB** excels at material profile management — deep slicer integration (PrusaSlicer, OrcaSlicer, Bambu Studio), per-printer/nozzle calibration storage, material science properties, NFC tag support, and AI-powered data sheet import.
- **Spoolman** excels at print-side inventory tracking — native OctoPrint and Moonraker/Klipper integration, real-time spool weight decrement during prints, Home Assistant integration, and broad ecosystem support.

Neither can do what the other does well. filament-bridge keeps them in sync so you can use both without manual data entry.

## What it does

- **Bidirectional sync** — spool weights, material properties, and inventory changes flow between Filament DB and Spoolman automatically
- **Guided initial sync** — walks you through importing existing data from either direction, with conflict resolution and validation before enabling auto-sync
- **Usage tracking** — when OctoPrint decrements a spool weight in Spoolman, the sync service creates a proper usage log entry in Filament DB with source, timestamp, and job label
- **Field mapping** — Spoolman extra fields map to Filament DB's richer property set (density, temperatures, TDS URL, etc.), either by name match or explicit configuration
- **Cross-reference IDs** — each system stores a reference to its counterpart (Filament DB spool ID in Spoolman extra fields, Spoolman spool ID in Filament DB's label field)
- **Variant awareness** — understands Filament DB's parent/variant model and tracks relationships via Spoolman extra fields
- **Conflict detection** — when both sides change between sync cycles, conflicts are queued for manual resolution with optional Discord notifications
- **Weight model translation** — handles the conversion between Spoolman's net weight tracking and Filament DB's gross weight (filament + reel) model

## Architecture

```
┌─────────────┐                    ┌──────────────────┐                    ┌──────────────┐
│  OctoPrint   │◄──────────────────►│                  │◄──────────────────►│  Filament DB  │
│  Moonraker   │   Spoolman API     │  filament-bridge │  Filament DB API   │  (Next.js)    │
│  Klipper     │                    │                  │                    │               │
└──────┬───────┘                    │  - Sync engine   │                    └───────────────┘
       │                            │  - Conflict queue │                           │
       ▼                            │  - Field mapping  │                           ▼
┌─────────────┐                    │  - Web UI         │                    ┌───────────────┐
│  Spoolman    │◄──────────────────►│                  │                    │  PrusaSlicer   │
│              │   Spoolman API     └──────────────────┘                    │  OrcaSlicer    │
└─────────────┘                                                            │  Bambu Studio  │
                                                                           └───────────────┘
```

Both Spoolman and Filament DB continue to function independently. filament-bridge is the glue that keeps them in sync. If the bridge goes down, both systems keep working — you just lose sync until it's back up.

## Quick start

```yaml
# docker-compose.yml
services:
  filament-bridge:
    image: ghcr.io/yourname/filament-bridge:latest
    container_name: filament-bridge
    restart: unless-stopped
    environment:
      FILAMENTDB_URL: http://filament-db:3000
      SPOOLMAN_URL: http://spoolman:7912
      SYNC_INTERVAL_SECONDS: 120
      # See docs/configuration.md for all options
    ports:
      - "8090:8090"
```

On first run, navigate to `http://localhost:8090` to run the guided initial sync.

## Configuration

All configuration is via environment variables. The service will not start if required variables are missing.

| Variable | Required | Default | Description |
|---|---|---|---|
| `FILAMENTDB_URL` | Yes | — | Base URL of your Filament DB instance |
| `SPOOLMAN_URL` | Yes | — | Base URL of your Spoolman instance |
| `SYNC_INTERVAL_SECONDS` | No | `120` | Seconds between auto-sync cycles (when enabled) |
| `SPOOLMAN_FIELD_FILAMENTDB_ID` | No | `filamentdb_id` | Spoolman extra field name for the Filament DB filament ID |
| `SPOOLMAN_FIELD_FILAMENTDB_PARENT_ID` | No | `filamentdb_parent_id` | Spoolman extra field name for the Filament DB parent filament ID (variant tracking) |
| `SPOOLMAN_FIELD_FILAMENTDB_SPOOL_ID` | No | `filamentdb_spool_id` | Spoolman extra field name for the Filament DB spool subdocument ID |
| `FILAMENTDB_SPOOLMAN_ID_FIELD` | No | `label` | Filament DB spool field to store the Spoolman spool ID |
| `FIELD_MAPPINGS` | No | — | Comma-separated `filamentdb_field=spoolman_extra_field` pairs |
| `FIELD_MAPPING_EXCLUDES` | No | — | Comma-separated field names to exclude from auto-matching |
| `DISCORD_WEBHOOK_URL` | No | — | Discord webhook for conflict notifications |
| `LOG_LEVEL` | No | `info` | Logging level (debug, info, warn, error) |

## Sync phases

### Phase 1: Initial sync (manual, guided)

On first run the web UI walks you through:

1. **Connect** — verify connectivity to both Filament DB and Spoolman APIs
2. **Choose direction** — "Import from Spoolman" or "Import from Filament DB" sets which side is the initial source of truth
3. **Review mapping** — the service reads both databases, auto-matches records by vendor + name + color, and shows: matched pairs, unmatched records, and ambiguous matches
4. **Resolve conflicts** — manually match or skip ambiguous records, clean up vendor name deduplication, assign variant parents
5. **Weight conversion** — review the spool tare weight adjustments (Spoolman net → Filament DB gross)
6. **Write cross-references** — the service writes linking IDs to both systems (Spoolman extra fields, Filament DB spool labels)
7. **Confirm** — review the full sync plan before committing

### Phase 2: Validation dry run

Before enabling auto-sync:

1. The service runs a simulated sync cycle
2. Shows what would change: spool weight updates, field syncs, new records, potential conflicts
3. User reviews and approves
4. User explicitly enables auto-sync

### Phase 3: Continuous sync (automated)

Once enabled, runs on the configured interval:

1. Poll both databases for changes since last sync
2. Apply non-conflicting changes automatically (weight decrements, field updates, new spool registrations)
3. Queue conflicting changes for manual resolution
4. Send Discord notification on conflicts
5. Log all sync actions for audit trail

## How sync works

### Source of truth

The user defines which system is authoritative for each data category during initial sync setup. Recommended defaults:

- **Spool weight**: Spoolman (because OctoPrint/Moonraker update it in real-time)
- **Material properties**: Filament DB (richer data model, slicer integration)
- **Spool inventory**: User's choice (where do you add new spools?)

### Weight model translation

Spoolman tracks **net filament weight** (remaining_weight excludes the reel). Filament DB tracks **gross spool weight** (totalWeight includes the reel, then subtracts the filament-level spoolWeight tare to display remaining filament).

When syncing a weight decrement from Spoolman:
- Spoolman reports: remaining_weight decreased by 50g
- Bridge calls: `POST /api/filaments/:id/spools/:spoolId/usage` with `{ grams: 50, jobLabel: "spoolman sync", source: "spoolman" }`

When syncing a weight from Filament DB to Spoolman:
- Filament DB shows: totalWeight 1220g, spoolWeight 220g → 1000g net
- Bridge writes: Spoolman remaining_weight = 1000g

### Variant tracking

Filament DB uses parent/variant inheritance (one parent filament with shared settings, color variants underneath). Spoolman has one filament per color with no hierarchy.

The bridge tracks this via Spoolman extra fields:
- `filamentdb_id` — direct link to the Filament DB color variant filament
- `filamentdb_parent_id` — link to the Filament DB parent filament (shared across all colors of the same material)

When a new Spoolman filament is created and its vendor+material matches an existing Filament DB parent, the bridge can suggest creating it as a variant.

### Conflict resolution

A conflict occurs when both sides change the same field between sync cycles. Conflicts are queued (not silently resolved) and the user must choose which value to keep. The conflict queue shows:

- Which record and field are in conflict
- The value on each side
- Timestamps of both changes
- A button to pick either value or enter a manual resolution

## Status

Design phase — see [docs/prd.md](docs/prd.md) for detailed requirements.

## Contributing

Contributions welcome! Please open an issue to discuss before submitting PRs for new features.

## License

MIT
