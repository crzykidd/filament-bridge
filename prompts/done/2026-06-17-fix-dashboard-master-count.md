---
name: 2026-06-17-fix-dashboard-master-count
status: completed
created: 2026-06-17
model: opus              # product-judgment on count semantics; then implement
completed: 2026-06-17
result: >
  User clarified the ask: 49=spools / 38=filaments is correct fan-out, not a masters bug —
  fix is presentational. Added a single shared detector core/masters.is_master_fdb (reused by
  wizard, reconcile, and filamentdb.health), broke out "filaments + masters" on the Connected
  systems FDB line (self-gating; only when masters>0), moved the marker resolver to api/config,
  and added Dashboard help text clarifying spools and filaments are counted independently.
  6 detector tests + 2 health-breakout tests; 1118 backend pass, ruff clean, tsc clean, 84 FE pass.
---

# Task: Account for synthetic master/container filaments in Dashboard counts (GitHub issue #3)

The Dashboard shows "In Sync = 49" near "Filament DB = 38" and the mismatch reads as broken
sync. The reporter suspected the `generic_container` master/container filaments. They're
partly right: the 49-vs-38 itself is legitimate, but synthetic masters DO cause a real,
separate count inconsistency that should be fixed, and the Dashboard should stop inviting the
false comparison.

## Verified findings (proven against the live services — do not re-litigate)

Both reported numbers are individually correct; they count different entities:

- **"In Sync = 49"** (Spools section) = `SpoolMapping`s with `in_sync` status —
  `backend/app/api/sync.py:126-129`, status logic `backend/app/api/mappings.py:148-160`.
- **"Total = 38"** (Filaments section) = real `FilamentMapping`s (synthetic masters already
  excluded) — `backend/app/api/sync.py:131-151` (filter `spoolman_filament_id IS NOT NULL` at
  `:143-147`), per-row status in `backend/app/core/filament_status.py:21-48`.
- 49 spools live on 38 filaments (6 filaments own >1 spool; 49 − 38 = 11). **The 49-vs-38 gap
  is normal spool-per-filament fan-out, NOT masters.** Do not try to force these two to match —
  that would be wrong.

**The real inconsistency (this is the fix the reporter asked for):** the
**Connected systems → filamentdb "filaments" tile** shows the RAW FDB total **including the 13
synthetic `(Master)` containers**, while every other FDB-filament surface excludes them:

- Over-counting site: `backend/app/services/filamentdb.py:289-294` (`health()` returns
  `len(filaments)`) → surfaced by `backend/app/api/health.py:72-94` (`counts["filaments"]`) →
  rendered at `frontend/src/pages/Dashboard.tsx:369-371`.
- Live data (this dev instance, `variant_parent_mode = "generic_container"`): FDB
  `GET /api/filaments` = **50** filaments, of which **13** are masters (`hasVariants=True`
  or name ends with the `(Master)` marker) → **37 real** FDB filaments. The bridge has **13**
  `FilamentMapping.is_synthetic_parent=1` rows and **38** real filament mappings.

**Master detection is duplicated in three places that must stay aligned:**
- `backend/app/api/sync.py:143-147` — excludes via `spoolman_filament_id IS NOT NULL`
- `backend/app/api/reconcile.py:79-92` — `_is_master` (synthetic ∪ hasVariants ∪ marker)
- `backend/app/api/wizard.py:364-405` — `_is_master_fdb` (same three signals)

The health/filamentdb count is the ONLY FDB-filament surface that does not apply this
exclusion.

## The fix (user-confirmed direction — presentational, no count is "wrong")

The user clarified the real ask after seeing the numbers: **row 1 is Spools, row 2 is
Filaments** — the 49-vs-38 is correct, it just needs to *read* as two independent things, and
the Filament DB connected-systems line should **break out "filaments + master filaments"** (not
silently drop the masters) when the dedicated-master setting is in play.

1. **Shared master detector** `core/masters.py:is_master_fdb(fil, marker=None, synthetic_ids=None)`
   — pure function on an `FDBFilament`: `True` if `id in synthetic_ids` (authoritative, when
   provided) OR `hasVariants` OR name ends with `" {marker}"`. No DB access inside. Refactor
   `wizard.py:_is_master_fdb` and `reconcile.py:_is_master` to call it (pass their synthetic-id
   set + marker) so the copies can't drift. (Keep `sync.py`'s SQL-level mapping exclusion.)
2. **Break out masters on the Connected systems → Filament DB line.** `filamentdb.py:health()`
   gains a `container_marker` param and returns `master_filament_count` (count via
   `is_master_fdb(f, marker)` over the raw FDB list — `hasVariants`/marker cover every synthetic
   parent). `health.py:_check_filamentdb` resolves the marker and, **when masters > 0**, reports
   counts as `{"filaments": total − masters, "masters": masters, "spools": …}` (so the line
   reads "filaments: 37  masters: 13  spools: 49"); when 0, it stays `{"filaments": total, …}`.
   This is **self-gating** — `promote_color`/`unset` have no masters, so no breakout appears; do
   NOT branch on `variant_parent_mode`. Resolve the marker via a request-scoped `db`
   (`health` route gains `db: Session = Depends(get_db)`) so tests using the overridden session
   work; keep `info.get("master_filament_count", 0)` so existing health mocks stay green.
3. **Sharpen the Spools vs Filaments separation** (`frontend/src/pages/Dashboard.tsx`). The
   connected-systems renderer already prints each count generically, so the new `masters` key
   appears automatically. Add clarity so green-but-unequal row totals don't trigger a hunt:
   a HelpTip on the "Spools" header (it has none today) noting spools are counted independently
   and a filament can hold several; reinforce the existing Filaments HelpTip. Keep it tasteful
   microcopy — no layout overhaul required.

## Investigate (cheap) — the off-by-one

37 non-master FDB filaments vs 38 real filament mappings. Likely one real mapping whose FDB
filament snapshot is absent, or one master that is genuinely paired to a Spoolman filament.
Spend a little time confirming which; if it's a quick data explanation, note it in the
decision log. Do NOT let it block the count-consistency fix.

## Before you start

- Read `CLAUDE.md` (variant/parent model, generic_container), `docs/variant-parent-mode.md`,
  `docs/sync-model.md`, and the three existing master-detection sites above.
- Compare against the running services: FDB `http://localhost:3000/api/filaments`, bridge
  state via `docker exec filament-bridge-filament-bridge-1 sh -c "sqlite3 /data/bridge.db
  '<query>'"`. Current live mode is `generic_container` with 13 masters — ideal for verifying.

## Working tree check

Run `git status --porcelain`; cross-reference the files this touches. If any are dirty, list
them and ask before touching. This prompt file is exempt.

## Step 0 — PLAN (short; required because of the count-semantics judgment)

State: the shared detector's location + signals, exactly which count site(s) change and the
chosen presentation (bare real count vs annotated), whether you refactor the other two
detectors, the Dashboard label change, and the test matrix. Confirm anything ambiguous first.

## What to do (after the plan)

1. Add the shared `is_master_fdb` detector; apply it to exclude masters from the
   connected-systems FDB filament count (self-gating).
2. Add the Dashboard label/HelpTip clarity for Spools vs Filaments.
3. (Optional) refactor `reconcile.py` / `wizard.py` to the shared detector.
4. Tests:
   - `generic_container` with N masters → connected-systems FDB filament count excludes the N
     masters; matches the real-filament total.
   - `promote_color` / `unset` (no masters) → count unchanged (no-op).
   - Marker-suffix-only master (no `hasVariants`) and `hasVariants`-only master both detected.
   - Frontend renders the clarified labels.
   - Backend `pytest` + `ruff check .`; frontend `npx tsc --noEmit` + `npm test`.

## Conventions to honor

- One canonical master detector — do not add a fourth divergent copy.
- Doc updates ship in the SAME commit: update `docs/variant-parent-mode.md` /
  `docs/sync-model.md` if count semantics are documented there; add a `CHANGELOG.md` entry
  under `[Unreleased]`; record the count-semantics decision in `docs/decisions.md`.
- Conventional-commits: `fix:` (connected-systems FDB count included synthetic masters). No
  `Co-authored-by:`. Branch `dev`, never `main`, never push.

## When done

1. Update this file's frontmatter (`status`, `completed`, `result`).
2. `git mv` to `prompts/done/` (or `prompts/failed/`).
3. Record the count-semantics decision in `docs/decisions.md`.
4. Propose ONE commit (stage specific paths, never `git add -A`); present file list + a
   one-line message and STOP for the user. Never push. This is a SEPARATE commit from issue #2.
