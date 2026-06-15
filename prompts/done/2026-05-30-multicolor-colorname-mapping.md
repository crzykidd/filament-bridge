---
name: 2026-05-30-multicolor-colorname-mapping
status: completed
created: 2026-05-30
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-05-30
result: core/color.py (pure projection helper, 100-color palette, coaxial→coextruded/longitudinal→gradient vocab); wizard execute sets colorName on create + updates linked multicolor filaments; engine recomputes colorName per cycle (format-change triggers rewrite via _colorName snapshot tracking) and guards FDB→SM color field sync behind protect_multicolor; two new BridgeConfig keys + ConfigResponse/ConfigUpdateRequest fields; Settings UI format dropdown + protect checkbox with loss warning; 131 backend tests pass + frontend build clean.
---

# Task: Multicolor filament mapping — colorName projection + protect setting

Filament DB has no multicolor support; Spoolman does (`multi_color_hexes` +
`multi_color_direction`, 29/175 of the live dataset). This task projects Spoolman's
multicolor into Filament DB's single-color model **without losing data**, and protects
Spoolman's multicolor fields from being flattened by write-back sync. The full decision is
already recorded — **read `docs/decisions.md` → "2026-05-30 — Multicolor filament mapping"
first; it is the spec.** This prompt is the implementation.

## Before you start

- **Read `docs/decisions.md`** the "Multicolor filament mapping" entry (the 5 decisions),
  the weight-model entry, and the Phase 5 entry (PATCH-not-PUT, config-as-key-value rows).
- **Read `CLAUDE.md`** — the weight/cross-ref model, the Spoolman/FDB data-model gotchas,
  and the hard rules: **never touch the FDB `settings{}` bag** (the UI "Notes" field is
  `settings.filament_notes` — off-limits), never raw-overwrite, conflicts never auto-resolve.
- **Read `docs/reconcile-backlog.md` item 5** for context.
- Use the `vexp` `run_pipeline` MCP tool for code context, not grep/glob.

## Context — reproduce on the local stack

The dev stack runs via `docker-compose.dev.yml` (bridge :8090, FDB :3000 + Mongo,
Spoolman :7912); Spoolman holds the real dataset, clean snapshot at
`private_data/spoolman-livedata.db`. The 29 multicolor filaments split 18 `coaxial` / 11
`longitudinal`, with 2 or 3 colors each (e.g. Spoolman filament #2:
`color_hex=93BE2F`, `multi_color_hexes="cdde1b,68cc16"`, `multi_color_direction="coaxial"`).
We already model `multi_color_hexes` / `multi_color_direction` in `schemas/spoolman.py`.

## Working tree check

Run `git status --porcelain`. Files this touches: a new `backend/app/core/color.py` (or
extend an existing core helper), `backend/app/api/wizard.py` (execute), `backend/app/core/
engine.py` (ongoing color sync / write-back), `backend/app/api/config.py`,
`backend/app/schemas/api.py`, `backend/app/models/config.py`,
`frontend/src/pages/Settings.tsx` (+ `api/types.ts`, `api/client.ts`),
`backend/tests/*`. If any are dirty, list and ask. (`private_data/`, `backend/.env`
gitignored.) This prompt file is exempt.

## What to do

### 1. Color projection helper (pure, testable) — `core/color.py`
A pure function that builds the FDB `colorName` from Spoolman multicolor data + the format
setting. No I/O.
- Inputs: primary `color_hex`, `multi_color_hexes` (CSV, may be empty/None),
  `multi_color_direction` (`coaxial`/`longitudinal`/None), `fmt` (`"name"` | `"hex"`).
- Type vocabulary mapping: `coaxial` → `coextruded`, `longitudinal` → `gradient`.
- `hex` format: `"cdde1b/68cc16 (coextruded)"` (primary first, then the rest, joined `/`,
  type in parens). `name` format: fuzzy nearest-named-color per hex →
  `"Yellow/Green (coextruded)"`.
- **Fuzzy hex→name:** nearest-named-color over a standard palette (CSS/X11 named colors or
  a small curated table baked into the module — **no heavy dependency**; a dict of
  name→RGB + Euclidean/CIE distance is fine). Approximate by design.
- Single-color filaments (no `multi_color_hexes`): return None / leave `colorName` untouched
  — only multicolor filaments get a projection.

### 2. Wire into create + sync
- **Always** set FDB `color` = Spoolman primary `color_hex` (unchanged behavior).
- For multicolor filaments, set FDB `colorName` = the projection. Apply in **wizard execute**
  (initial create) and wherever filaments are created/updated in `core/engine.py`.
- **`colorName` is bridge-managed / derived (decision #3):** recompute it from Spoolman data
  + the *current* format whenever a multicolor filament is applied — including a path so that
  **changing the format setting and re-running sync (or a manual trigger) rewrites it**, even
  though the differ sees no Spoolman-side change. (E.g. on a sync/manual cycle, recompute
  `colorName` for known multicolor mappings and PUT if it differs from the last snapshot.)
  Strip computed fields before the FDB PUT; never touch `settings{}`.

### 3. Protect multicolor on write-back (decision #4)
In the FDB→Spoolman color path (FR-10/FR-11 / new-record + field-mapping sync), when
`protect_multicolor_color_in_spoolman` is true (default), **skip writing color fields to
Spoolman for any filament Spoolman marks multicolor** (`multi_color_hexes` non-empty),
regardless of the material-properties source-of-truth. Never null/overwrite
`multi_color_hexes` / `multi_color_direction` / `color_hex` for these. When the toggle is
off, normal color sync applies (the UI warns this can lose multicolor).

### 4. Config + Settings UI
- Add two `BridgeConfig` keys in `models/config.py::seed_defaults` and surface them in
  `ConfigResponse` / `ConfigUpdateRequest` (`schemas/api.py`): `multicolor_colorname_format`
  (`"name"` | `"hex"`, default `"name"`) and `protect_multicolor_color_in_spoolman` (bool,
  default `true`). Key-value rows — no Alembic migration.
- `frontend/src/pages/Settings.tsx`: a **format dropdown** (Name (fuzzy) / Hex) and a
  **checkbox** for protect-multicolor (default checked) with a prominent warning:
  > ⚠️ Turning this off can overwrite and lose your multicolor settings in Spoolman.
  Wire through the existing config api client + types.

## Conventions to honor
- `core/color.py` stays pure (no I/O); keep the palette/table in-module, no heavy deps.
- Delegate HTTP to existing clients; strip computed fields before FDB PUT; never touch the
  `settings{}` bag; never raw-overwrite weight; structured logs, respect `LOG_LEVEL`.
- Frontend matches the existing Settings page + typed api client patterns.

## Verification
- `cd backend && pytest` green — new tests: projection in both formats for 2- and 3-color
  filaments; coaxial→coextruded / longitudinal→gradient; fuzzy match maps known hexes to
  expected names; protect rule blocks FDB→Spoolman color write for multicolor; format change
  re-derives `colorName`.
- `cd frontend && npm run build` green; the format dropdown + protect checkbox load and
  round-trip via GET/PUT `/config`.
- **End-to-end on the local stack:** trigger a sync; confirm the 29 multicolor filaments get
  a `colorName` like `"Yellow/Green (coextruded)"`; flip the format to `hex`, re-run →
  `colorName` updates to the hex form; run an FDB→Spoolman cycle and confirm Spoolman's
  `multi_color_hexes`/`direction`/`color_hex` are unchanged with the toggle on.

## When done
1. Update frontmatter: `status`, `completed`, `result`.
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/` (failure).
3. The design decision is already in `docs/decisions.md`; add only implementation notes if
   something non-obvious changed (e.g. the palette source, the re-derivation mechanism).
4. Propose ONE commit (no `Co-authored-by:`). Suggested message:
   `feat: multicolor colorName projection + protect-multicolor setting`.
   Present the file list and ask `commit these as "<message>"? (y/n)` before staging. Stage
   specific paths only; commit on `dev`; no push.
