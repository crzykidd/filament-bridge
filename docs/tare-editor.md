# Tare Editor

The **Tare Editor** (nav: *Tare Editor*, route `/tare-editor`) is a standalone bulk editor for the
**empty-reel tare weight** of your mapped filaments. Tare is the weight of the bare spool with no
filament on it. It matters because the two systems disagree about what "weight" means:

- **Spoolman** stores **net** filament weight (`spool_weight` is the tare).
- **Filament DB** stores **gross** weight (`spoolWeight` is the tare).

The bridge converts between them with `net = gross − tare`, so a wrong or missing tare makes every
weight sync off by the reel weight. The Tare Editor lets you review and fix tare across all mapped
filaments in one place. **Tare is shared by all spools of a filament** (it lives on the filament,
not the individual spool), so you set it once per filament.

## What it shows

Filaments are grouped by **variant family** (a master and its color variants collapse under one
group header showing the variant count); standalone filaments render as plain rows. Each row shows:

| Column | Meaning |
|---|---|
| checkbox | select the row for a bulk apply |
| name | filament name (variants indented with a `└` marker) |
| vendor | the vendor |
| role | **Standalone**, **Master**, or **Variant** |
| **SM tare** | current Spoolman `spool_weight` |
| **FDB tare** | current Filament DB `spoolWeight` |
| **New tare** | editable input (grams) |
| status | **Set** (green — both sides agree), **Missing** (red — no tare set), or **Mismatch** (amber — the two sides disagree) |
| links | [deep links](upstream-apis.md#deep-links-ui-requirement) to both systems |

Two controls narrow the list: a **search** box (name or vendor, case-insensitive) and an **Only
missing / mismatched** checkbox that hides rows whose status is already *Set*.

## Editing

- **Per row** — type the new tare into the **New tare** input (grams, minimum 0, 0.1 g steps). A
  changed input highlights with a blue border until saved.
- **In bulk** — select rows with their checkboxes (or the *Select all* / per-family header
  checkbox), enter a value in the **grams** field, and click **Apply to selected** to fill every
  selected row with that value. The control shows how many rows are selected.

## Saving

Saving writes every changed row to **both upstream systems at once** — a Spoolman `spool_weight`
update *and* a Filament DB `spoolWeight` update per filament (via `POST /api/tare/bulk`, which
routes through the shared tare write path so both sides and the bridge snapshots stay consistent,
avoiding a ping-pong on the next cycle).

- On success you see **"Saved tare for N filament(s)."**; successfully-saved rows clear their edit
  and the live values refresh.
- Any failures are listed below the message and those rows stay editable (highlighted red) so you
  can retry.
- Bulk tare writes are **hard-gated on upstream compatibility** — if either upstream is below its
  [minimum supported version](sync-model.md#version-gating), the save is refused (HTTP 409) with a
  "Tare editing disabled — …" message, the same gate the sync trigger and wizard execute use.

## API

- `GET /api/tare` → `TareListResponse` — every mapped filament with both-side tare, status, and
  variant grouping.
- `POST /api/tare/bulk` — body `{ updates: [{ filament_mapping_id, tare_grams }] }` (tare ≥ 0);
  returns `{ updated, failed[] }`.

Both are auth-gated. Tare also participates in ongoing sync as one of the native scalar fields
(`spool_weight` ↔ `spoolWeight`); the Tare Editor is the deliberate bulk-correction tool for it.
