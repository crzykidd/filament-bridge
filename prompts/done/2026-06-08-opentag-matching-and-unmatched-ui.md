---
name: 2026-06-08-opentag-matching-and-unmatched-ui
status: completed        # pending | completed | failed
created: 2026-06-08
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-08
result: Fixed VOXEL-pla brand gate (normalize_vendor hyphen→space), added color-words map + score rebalancing (jet/galaxy → black; 756 tests pass), enriched unmatched UI (deep link, material, no-manufacturer badge, reason)
---

# Task: Fix OpenTag Cleanup matching gaps + improve the unmatched section

Three independent problems surfaced testing OpenTag Cleanup against live data. Root causes were
traced in an Opus session on 2026-06-08 with real Spoolman + OpenTag data — trust the diagnoses,
verify line numbers haven't drifted.

## Background — the real failing cases

1. **VOXEL-pla → 0% (brand-gate bug).** Spoolman vendor `"VOXEL-pla"` should match OpenTag brand
   `"Voxel PLA"` (slug `voxel-pla`), but lands in "unmatched" with 0% and reason
   `'Manufacturer "VOXEL-pla" not found in OpenTag'`. Cause: `normalize_vendor()`
   (`backend/app/core/matcher.py:28-33`) lowercases + collapses whitespace but does NOT normalize
   hyphens. So `"VOXEL-pla"` → `"voxel-pla"` while `"Voxel PLA"` → `"voxel pla"` — different keys.
   The brand index in `backend/app/api/opentag.py:445-456` (keyed by `normalize_vendor(brandName)`)
   and the lookup at `opentag.py:500-503` then find ZERO candidates, so scoring never runs.

2. **Spoolman #3 "PLA Jet Black" → should match `prusament-pla-prusa-galaxy-black` (color scorer).**
   Brand matches (Prusament). NOT a coverage gap — the material exists
   (`data/materials/prusament/prusament-pla-prusa-galaxy-black.yaml`, name "PLA Prusa Galaxy Black",
   type PLA, `#4b4545`). It fails because the color name "Jet Black" vs "Galaxy Black" shares the
   base color "black" but differs in modifier, and the hex (`#222F2E` vs `#4b4545`) is only
   moderately close — so the weighted color score is too low and it drops below the 30% unmatched
   threshold. The scorer is weighted-sum (no hard color gate): see `score_candidate()` in
   `backend/app/core/opentag_match.py:549-624` (type 0.20, brand 0.20, color-name 0.30,
   finish ±0.15, hex 0.10).

3. **Unmatched section is sparse.** `frontend/src/pages/OpenTagCleanup.tsx:1146-1159` shows only
   `{name} ({vendor}) — {pct}%`. The `OpenTagFilamentMatch` model
   (`backend/app/api/opentag.py:82-105`) already carries `spoolman_filament_id`,
   `spoolman_material`, `spoolman_color_hex`, and a computed `no_match_reason` — all unused here.

## Working tree note

Repo root has pre-existing untracked dotfiles (`.bashrc`, `.gitconfig`, `.idea`, `.mcp.json`,
`.claude/*`, …) — IGNORE; never stage them. Run `git status --porcelain` first.

---

## A — Brand-gate fix (VOXEL-pla)

In `core/matcher.py:normalize_vendor()`, treat hyphens/underscores as spaces BEFORE the existing
whitespace collapse, so `"VOXEL-pla"` and `"Voxel PLA"` both normalize to `"voxel pla"`.
Minimal change: `n = re.sub(r"[-_]+", " ", n)` before `n = re.sub(r"\s+", " ", n)`.

- `normalize_vendor` is SHARED (variant clustering, vendor dedup, OpenTag brand gate). Treating a
  hyphen like a space is correct for vendor names generally, but run the FULL backend suite and
  confirm no regressions in vendor-dedup / variant-cluster tests. If any test encodes the old
  hyphen behavior intentionally, surface it rather than blindly changing the test.
- Defensive bonus: in the brand pre-filter (`opentag.py` ~500), also try matching against the
  OpenTag brand SLUG (already hyphen-shaped, e.g. `voxel-pla`) in addition to the normalized brand
  name, so future brand/slug shape mismatches degrade gracefully.
- Tests: SM vendor `"VOXEL-pla"` matches OpenTag brand `"Voxel PLA"` and yields the
  `voxel-pla-*` candidates (non-empty, non-zero confidence). Add to the OpenTag matcher tests.

---

## B — Color-words list + color scoring (#3)

Goal: Spoolman "PLA Jet Black" surfaces `prusament-pla-prusa-galaxy-black` as a candidate with
confidence above the 30% threshold (ideally best or near-best), because both are "black".

1. **Add a configurable color-words MAP** (not a flat list) mirroring `opentag_vendor_aliases`:
   a new runtime-editable `opentag_color_keywords` setting — env `OPENTAG_COLOR_KEYWORDS`
   (CSV of `keyword=base_color` pairs), `BridgeConfig` override, Settings UI field. It maps any
   color word to a canonical base color so the matcher can reduce both names to a comparable base.
   The map must handle three kinds of entry, all in the DEFAULT seed and all user-extendable:
   - **Base colors → themselves:** `black=black`, `white=white`, `grey=grey`, `gray=grey`,
     `silver=grey`, `red=red`, `blue=blue`, `green=green`, `yellow=yellow`, `orange=orange`,
     `purple=purple`, `pink=pink`, `brown=brown`, `gold=gold`, `natural=natural`, `clear=clear`, …
   - **Modifiers that prefix a color** (`lite`/`light`, `dark`, `deep`, `pastel`): treat as
     modifiers — they should NOT block a base-color match (strip/ignore them, or keep them as a
     weak secondary signal). "Light Grey" and "Grey" should both reduce to base `grey`.
   - **Brand/marketing names → a base color:** e.g. `cool=grey`, `galaxy=black`. These are
     vendor marketing words ("Galaxy Cool" used for grey, "Galaxy Black" for black). Seed a few
     common ones and let users add their own — this is exactly why it's user-editable.
   Keep the seed in a constant in `core/opentag_match.py` so it's testable. Prefer this NEW map over
   overloading `matcher._SM_COLOR_WORDS` (which mixes finishes + drives variant clustering).
2. **Use it in the color scorer** (`opentag_match.py` color-name component, ~L589-624): reduce BOTH
   the Spoolman color/name and the OpenTag color name to their base color via the map, then compare
   base colors. If they match (both → "black"/"grey"), award strong color credit even when the
   surrounding modifier/marketing words differ ("jet" / "galaxy" / "prusa" / "cool"). A modifier or
   marketing mismatch must not zero out a correct base-color match.
3. **Lean on hex as the PRIMARY color signal — marketing names are unreliable.** Increase the
   influence of hex proximity (currently only 0.10) when both hexes are present; the hex is ground
   truth ("Jet Black" #222F2E and "Galaxy Black" #4b4545 are both clearly dark) while names like
   "Galaxy"/"Cool" are brand fluff. The base-color map is the secondary aid (and the fallback when a
   hex is missing). Keep changes proportionate — don't regress existing well-matched cases.
4. Tests: the #3 case (SM "PLA Jet Black" #222F2E + Prusament → galaxy-black candidate above
   threshold), plus a couple of base-color-match-with-different-modifier unit tests on the scorer.

This is the nuanced item — you have latitude on the exact scoring math, but the acceptance bar is:
VOXEL cases and #3 stop being 0%/unmatched, and no previously-correct match regresses (run the
existing OpenTag matcher tests).

---

## C — Improve the unmatched section UI

In `frontend/src/pages/OpenTagCleanup.tsx` (~L1146-1159), enrich each unmatched row using data the
backend already returns:

- **Spoolman deep link:** render `<DeepLinks spoolmanFilamentId={m.spoolman_filament_id} />` (the
  component is already imported and used on matched cards ~L288) so the SM id links to the spool's
  filament page.
- **Material:** show `m.spoolman_material`.
- **No-manufacturer error:** when `m.spoolman_vendor` is missing/empty, show a red "No manufacturer"
  error badge — a missing vendor is a primary cause of no-match and should read as an error.
- **Reason:** surface the existing `m.no_match_reason` (e.g. the "Manufacturer X not found" text)
  so the user understands WHY it's unmatched.
- Keep grey text readable (`text-gray-600`/`-700`, consistent with the prior darken pass).

Confirm `spoolman_material` and `no_match_reason` are present on the frontend `OpenTagFilamentMatch`
type (`frontend/src/api/types.ts`); add the fields if the type is missing them.

---

## Conventions / tests / done

- Backend tests: `cd backend && python3 -m pytest` (use `python3`, not `python`). Add the tests
  above; report the summary line. Frontend: `cd frontend && npm run build`; report result.
- Update `CHANGELOG.md` `[Unreleased]`, the env-var table in `CLAUDE.md` for `OPENTAG_COLOR_KEYWORDS`,
  and the runtime-settings docs. Docs ship in the same commit as code.
- Commit prefixes: `fix:` for the brand-gate + color-scoring bugs, `feat:` for the color-words
  setting + unmatched-UI enrichment. No `Co-authored-by:`. Branch `dev`, never `main`, never push.
- When done: update this file's frontmatter (completed) + `git mv` to `prompts/done/`; record
  non-obvious decisions in `docs/decisions.md`. DO NOT `git commit` — leave changes in the working
  tree and report back: file list, proposed commit message(s) (suggest splitting A+B backend fix /
  color-words feat / C UI), backend test results, frontend build result, and anything deferred.
