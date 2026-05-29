# Migration Guide: Spoolman → Filament DB

This document covers the end-to-end process for migrating an existing Spoolman-based filament inventory into Filament DB, preserving spool identities, current weights, and location assignments.

## Prerequisites

- Filament DB running (Docker or desktop app) with an accessible REST API
- Spoolman running with your current inventory
- PrusaSlicer with your tuned filament profiles
- Access to both APIs from your workstation

## Overview

The migration happens in phases. Filament profiles go in first (because spools reference filaments by name), then physical spool inventory, then post-import enrichment and configuration.

```
Phase 1: Filament profiles ──► Phase 2: Spool inventory ──► Phase 3: Post-import setup
  - PrusaSlicer INI import        - Spoolman export             - Printers & nozzles
  - OpenPrintTag enrichment       - Column mapping               - Calibrations
  - AI TDS extraction             - CSV import                   - Locations (verify)
                                                                 - Color variants
                                                                 - NFC tags
                                                                 - TDS links
```

---

## Phase 1: Import filament profiles

Filament records must exist before spools can be imported — the spool CSV import matches on filament name.

### 1a. Import PrusaSlicer config bundle

This captures your **custom overrides only** — not the system presets.

1. In PrusaSlicer: **File → Export → Export Config Bundle** → save as `PrusaSlicer_config_bundle.ini`
2. In Filament DB: **Import/Export → Import INI** → select the file
3. Every `[filament:Name]` section becomes a filament record with the full settings bag

**Important limitation discovered:** The PrusaSlicer config bundle only exports your 17 user presets (overrides like "ELEGOO PC @COREONE", "Hatchbox PLA MK4S MMU3", etc.). The system presets (Elegoo PLA, Elegoo Rapid PLA+, Generic PETG, Hatchbox PLA, etc. — the ones with lock icons in PrusaSlicer) do NOT get exported. They ship with PrusaSlicer itself.

This means the INI import is NOT sufficient as the primary source of filament settings. It only gives you your tweaks, not the base profiles for the ~25 materials you actually use.

**Revised strategy:** Lead with Spoolman data + OpenPrintTag enrichment for base material properties, then layer PrusaSlicer overrides on top for your custom tweaks.

### 1b. Enrich from OpenPrintTag community database (optional, recommended)

Fills in material science properties that PrusaSlicer doesn't carry.

1. In Filament DB: **Import/Export → Browse OpenPrintTag DB**
2. Filter by your vendors/materials, select matches
3. Click **Import Selected** — only null fields are filled; your PrusaSlicer-tuned settings are preserved
4. You'll pick up: Tg, HDT, shore hardness, drying specs, transmission distance (HueForge TD)

### 1c. AI TDS extraction (optional, per-filament)

For filaments where the manufacturer publishes a Technical Data Sheet:

1. Configure an AI provider API key in **Settings → AI Features** (Gemini free tier works fine)
2. On a filament detail page: **Import from TDS** → paste the TDS URL
3. Review extracted properties, save

This is best done gradually — hit the filaments you use most first, fill in the rest over time.

---

## Phase 2: Import spool inventory from Spoolman

### 2a. Export from Spoolman

Spoolman's API returns spool data as JSON. You can either:

- Use the Spoolman web UI export if available
- Hit the API directly: `GET http://your-spoolman:7912/api/v1/spool` returns all spools with nested filament and vendor data

Key fields you need from each Spoolman spool:
| Spoolman field | What it is |
|---|---|
| `id` | Your current spool identifier (the # you use on physical labels) |
| `remaining_weight` | Current weight in grams (the running balance after all usage tracking) |
| `filament.name` | Filament name — **this is the join key to Filament DB** |
| `filament.vendor.name` | Vendor name (helps disambiguate) |
| `location` | Current bin/location assignment |
| `lot_nr` | Lot number if you track it |
| `first_used` / `last_used` | Dates (for reference, not directly importable) |

### 2b. Transform to Filament DB spool CSV format

Create a CSV with these columns:

```csv
filament,vendor,totalWeight,label,lotNumber,location
eSun PETG Solid Black,eSun,842,047,LOT-2024-A,Bin 3
Prusament PLA Galaxy Black,Prusament,1050,048,,Bin 7
```

Column mapping from Spoolman → Filament DB CSV:

| Filament DB CSV column | Source | Notes |
|---|---|---|
| `filament` | Spoolman `filament.name` | **Must exactly match** a filament name already in Filament DB from Phase 1 |
| `vendor` | Spoolman `filament.vendor.name` | Disambiguates if multiple filaments share a name |
| `totalWeight` | Spoolman `remaining_weight` + `filament.spool_weight` | **CRITICAL: Filament DB totalWeight is GROSS weight (filament + reel).** Spoolman remaining_weight is net filament only. You must add the empty spool/reel weight. Use Spoolman's `filament.spool_weight` where available, default ~200g where missing. |
| `label` | Spoolman `id` (your physical label number) | Your existing spool ID — "047", "048", etc. Or start new scheme: "052026a" |
| `lotNumber` | Spoolman `lot_nr` | Optional |
| `location` | Spoolman `location` | Auto-created in Filament DB if it doesn't exist |

> **Weight model difference:** Spoolman tracks net filament weight. Filament DB tracks gross spool weight and subtracts the filament-level `spoolWeight` (empty reel tare) to compute remaining filament. If you import Spoolman's `remaining_weight` directly without adding the reel weight, every spool will appear to have ~200g less filament than it actually does.

**Name reconciliation:** This is the hardest part. Your PrusaSlicer profile names and your Spoolman filament names probably don't match exactly. Before importing the spool CSV, verify that every unique `filament` value in your CSV has a corresponding filament record in Filament DB. Options for fixing mismatches:

- Rename filaments in Filament DB's UI to match your Spoolman names
- Adjust the CSV `filament` column to match PrusaSlicer names
- Create missing filament records manually for any spools whose filament didn't come in via the PrusaSlicer bundle

### 2c. Import the spool CSV

```bash
curl -X POST http://your-filament-db:3000/api/spools/import \
  -H "Content-Type: text/csv" \
  --data-binary @spools.csv
```

Or via the web UI: **Import/Export → Import File** → select the CSV (the app routes by extension).

Response tells you what happened:
```json
{
  "imported": 106,
  "failed": 2,
  "results": [
    { "row": 2, "ok": true, "filament": "eSun PETG Solid Black" },
    { "row": 45, "ok": false, "error": "No filament named \"Mystery PLA\"" }
  ]
}
```

Fix any failures by creating the missing filament records and re-importing just those rows.

---

## Phase 3: Post-import setup in Filament DB

### 3a. Define printers and nozzles

1. **Nozzles:** Create records for each physical nozzle type you own (e.g., "Brass 0.4mm", "Hardened 0.4mm HF", "Brass 0.6mm"). Set diameter, type, high-flow, and hardened flags.
2. **Printers:** Create records for each printer (name, manufacturer, model). Install the appropriate nozzles on each printer.

This scaffolding is required for calibrations to work.

### 3b. Enter calibrations

For each filament you've calibrated, add per-printer per-nozzle calibration entries:
- Extrusion multiplier
- Pressure advance
- Max volumetric speed
- Retraction length/speed/lift
- Per-bed-type temperatures (if applicable)

If your PrusaSlicer profiles already contain these values and you only use one printer, much of this came in with the INI import. For multi-printer setups, you'll need to split the values out per printer/nozzle combination.

### 3c. Verify locations

If you included the `location` column in the spool CSV, locations were auto-created. Verify them in the Filament DB UI and optionally add:
- `kind` — "bin", "drybox", "shelf", "printer", etc.
- `humidity` — current %RH reading if you track it
- `notes` — any additional info

### 3d. Set up color variants (optional)

If you have the same filament in multiple colors (e.g., eSun PLA+ in 8 colors):
1. Pick one color as the parent (usually your most-used)
2. On each other color's filament page, set the parent via the variant picker
3. Inherited settings (temps, retraction, etc.) resolve from the parent automatically
4. Only per-color overrides need to be maintained on the variant

### 3e. Write NFC tags (ongoing)

For spools that already have OpenPrintTags: tap them on the ACR1552U reader. Filament DB matches by material/vendor/type — they should resolve to the right filament record.

For spools that need new tags (stick-on NFC-V tags for refill holders):
1. Open the filament's detail page
2. Place the tag on the reader
3. Click **Write NFC** — encodes the OpenPrintTag data (material, vendor, type, color, instance ID)

This can happen gradually as you handle each spool.

### 3f. Link TDS documents (optional, ongoing)

On each filament's detail page, paste the manufacturer's TDS URL into the TDS field. Enables inline preview and auto-suggestions for same-vendor filaments.

---

## Post-migration: new spool workflow

Once migrated, the workflow for adding new spools is:

1. New filament arrives — scan Prusament QR, import from OpenPrintTag DB, import from TDS, or create manually
2. Assign a label using your date-based scheme (e.g., "052026a")
3. Write an OpenPrintTag NFC tag to the spool or stick-on tag
4. Assign to a location (bin)
5. The spool is now trackable by NFC tap (filament identity), by label (physical lookup), and by location (where to find it)

## Post-migration: label numbering transition

Existing Spoolman spool IDs (numeric, e.g., "047", "048") stay as-is on current inventory. New spools get the date-based scheme ("052026a", "052026b"). Mixed label formats work fine — the label field is free text. Over time the old numeric labels will retire out as spools are consumed.
