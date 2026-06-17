---
name: 2026-06-17-fix-synced-records-fdb-color
status: completed
created: 2026-06-17
model: opus              # one judgment call (staleness handling); then implement
completed: 2026-06-17
result: >
  Root cause refined against live data: the bug was solid filaments, not multicolor — the
  multicolor pass skips solids before writing _mc_color, so solid colors never captured for
  display. Fixed by capturing a representative display hex (new color.py:fdb_representative_hex)
  for EVERY mapped filament early in _sync_multicolor (not-dry-run), normalized to SM
  convention at the read site so matched colors read as matched. 2 engine tests + 6 color
  helper tests; 1 stale assertion updated. 1110 backend pass, ruff clean. Self-heals next cycle.
---

# Task: Fix Synced Records not showing the Filament DB color (GitHub issue #2)

In the Synced Records expandable detail, the Filament DB side shows "—" for color on most
synced filaments while Spoolman shows a real hex — so in-sync records look out of sync. The
UI cell and the `/api/mappings` detail payload already exist; the stored value is wrong.

## Verified root cause (proven against the live services — do not re-litigate)

**The primary bug is that purely-solid filaments never get a display color captured at all.**
The detail's FDB color reads the FDB filament snapshot key `_mc_color`
(`backend/app/api/mappings.py:99-101`: `filamentdb=fdb_fil.get("_mc_color")`). That key is
written in exactly one place — the multicolor pass `_sync_multicolor` — which **`continue`s on
purely-solid filaments before storing anything**:

- `backend/app/core/engine.py:813-816` —
  `if not (sm_is_mc or fdb_is_mc): continue  # purely solid — the generic color field sync handles it`
  The solid color IS synced elsewhere (generic `color` field path), but `_mc_color` is never
  written, so the Synced Records detail shows "—" for every solid filament.

**Live proof (the exact filament in the issue screenshot):** FDB "ELEGOO PLA Beige"
(`6a3207c3dc06747477904ff5`) is **single-color**: `color="#DAC7A0"`, `secondaryColors=[]`,
`optTags=[]`, `hasVariants=false` — and it matches Spoolman filament 111 ("PLA Beige",
`color_hex=DAC7A0`). Its bridge snapshot has `_cost`, `_finish_sig`, and all `_mp_*` keys but
**no `_mc_color` / `_mc_sig`** → renders "—" despite a perfectly good, in-sync color. Snapshot
stats: of 37 FDB filament snapshots, `_mc_color` is set in 8, `None` in 4, **MISSING in 25** —
the 25 are the solids the multicolor pass skips.

**Secondary issue (multicolor):** even when the multicolor pass DID write `_mc_color`, it
stored only the bare `color` field, which is `null` for coextruded/gradient filaments (real
hexes live in `secondaryColors[]`) → those also showed "—".

There is **no** missing UI cell and **no** payload-shape bug — `SyncedRecords.tsx:44-62`
(`DetailGrid`) renders both sides; `fmtDetailValue` (`:38-41`) shows null/'' as "—". The fix is
backend-side: capture a representative display hex for **every** mapped filament (solid AND
multicolor), not just the ones the multicolor-sync logic processes.

## The fix (semantics to implement — confirm staleness choice in the plan)

1. **Capture a representative display hex for EVERY mapped filament — solid and multicolor.**
   Add the capture early in `_sync_multicolor`'s loop (before the solid-skip `continue`), so
   solids get `_mc_color` too; the multicolor path refines it from the variant-resolved
   detail. Use a new helper `core/color.py:fdb_representative_hex(color, secondary_colors,
   opt_tags)` (built on `fdb_multicolor_to_sm`) that returns one display hex: single → `color`;
   gradient → primary; coextruded → first secondary; colorless container → `None`. Gate the
   capture on `not dry_run`.
2. **Normalize the `#` prefix so a matched color reads as matched.** FDB uses `#AEB8C1`,
   Spoolman uses `AEB8C1` (no `#`). Apply the existing normalization (`to_sm_color()` /
   `to_fdb_color()` in `color.py`) consistently for the detail comparison so a truly in-sync
   single color doesn't display as different. Decide whether to normalize at capture time
   (store `#`-prefixed, the FDB convention) or at the read site in `mappings.py` — state the
   choice; be consistent with how the Spoolman side stores `color_hex`.
3. **Staleness — the 25 missing-key snapshots (JUDGMENT CALL, decide in the plan):**
   - **Option A (self-heal, simplest):** capture fix only; rely on the next sync cycle's
     multicolor pass to rewrite `_mc_color` correctly for all non-gated filaments. Acceptable
     if the multicolor pass runs every cycle and rewrites the key.
   - **Option B (immediate, more robust UX):** add a read-side fallback in
     `mappings.py:_build_detail` that derives the FDB color when `_mc_color` is absent/None —
     BUT only viable if the FDB *filament* snapshot already carries `secondaryColors`/`optTags`
     (verify — it likely stores only the sig keys). If it doesn't, Option B needs the snapshot
     to start carrying the structured color, which widens scope.
   - Recommend A unless you confirm the snapshot carries the structured fields cheaply.
     Whichever you pick, say so and why.

## Edge cases to honor

- **Coextruded/coaxial** (optTag 29, `color=null`, ≥2 secondaries) → first secondary hex is
  the representative.
- **Gradient/longitudinal** (optTag 28) → `color` (primary) is the representative.
- **Single color** → already works; just apply `#` normalization (item 2).
- **Genuinely colorless** (Master/container parents: `color=null`, no secondaries) → stays
  `None`/"—". That is correct, not a bug — do not synthesize a color.
- **Version-gated (FDB < 1.33.0)** → `_mc_color` never written; "—" is acceptable. Note it.

## Before you start

- Read `CLAUDE.md` (color model, FDB/Spoolman data-model gotchas), `docs/spoolman-writes.md`,
  `docs/sync-model.md`, and `backend/app/core/color.py` in full (the conversion helpers).
- Compare against the running services if useful: FDB `http://localhost:3000/api/filaments`,
  Spoolman `http://localhost:7912/api/v1/filament`, bridge state in
  `docker exec filament-bridge-filament-bridge-1 sh -c "sqlite3 /data/bridge.db '<query>'"`.

## Working tree check

Run `git status --porcelain`; cross-reference the files this touches. If any are dirty, list
them and ask before touching. This prompt file is exempt. (Expect a clean tree — the prior
archive/retire commit already landed.)

## Step 0 — PLAN (short; required because of the item-3 judgment call)

State: the exact `_mc_color` derivation, the `#`-normalization location, the chosen staleness
option (A or B with justification), and the test matrix. Confirm anything ambiguous before
implementing.

## What to do (after the plan)

1. Fix the `_mc_color` capture in `engine.py` to derive a representative hex via
   `fdb_multicolor_to_sm`, with `#` normalization.
2. (If Option B chosen) add the read-side fallback in `mappings.py`.
3. Tests:
   - Multicolor FDB filament (color=null + secondaryColors) → `_mc_color` stored as a
     non-null representative hex (coextruded → first secondary; gradient → primary).
   - Single-color FDB filament → `_mc_color` set, and a matched single color reads as matched
     across the `#`-prefix normalization.
   - Colorless container parent → `_mc_color` stays None (no synthesized color).
   - If Option B: a snapshot with `_mc_color` absent still yields the FDB color in the
     `/api/mappings` detail.
   - Backend `pytest` + `ruff check .`; if any FE change, `npx tsc --noEmit` + `npm test`.

## Conventions to honor

- Reuse `color.py` helpers — do not reimplement hex/multicolor parsing.
- Doc updates ship in the SAME commit: if behavior/notes change, update `docs/spoolman-writes.md`
  / `docs/sync-model.md` as needed and add a `CHANGELOG.md` entry under `[Unreleased]`. Record
  any non-obvious decision in `docs/decisions.md`.
- Conventional-commits: `fix:` (FDB color showed "—" for multicolor synced records). No
  `Co-authored-by:`. Branch `dev`, never `main`, never push.

## When done

1. Update this file's frontmatter (`status`, `completed`, `result`).
2. `git mv` to `prompts/done/` (or `prompts/failed/`).
3. Record any non-obvious decision in `docs/decisions.md`.
4. Propose ONE commit (stage specific paths, never `git add -A`); present file list + a
   one-line message and STOP for the user. Never push. This is a SEPARATE commit from issue #3.
