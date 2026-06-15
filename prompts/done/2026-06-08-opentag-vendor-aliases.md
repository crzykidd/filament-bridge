---
name: 2026-06-08-opentag-vendor-aliases
status: completed        # pending | completed | failed
created: 2026-06-08
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-07
result: Added opentag_vendor_aliases config + resolve_opentag_brand; Prusa → Prusament aliasing works in brand pre-filter and score_candidate vendor component; 639 tests pass.
---

# Task: Settings — Spoolman→OpenTag manufacturer (brand) name mappings

The OpenTag matcher hard-filters candidates by brand (`normalize_vendor(brandName)`), and
`normalize_vendor` treats e.g. "Prusa" vs "Prusament" as different brands — so Spoolman
filaments whose vendor name differs from OpenTag's brand name never match. Add a
user-configurable mapping in Settings (Spoolman vendor → OpenTag brand) applied to OpenTag
matching.

## What to do

### 1. Config (`backend/app/config.py` + `models/config.py` + `api/config.py` + `schemas/api.py`)
- Add `opentag_vendor_aliases` — a CSV of `spoolman_vendor=opentag_brand` pairs (e.g.
  `prusa=prusament, polyterra=polymaker`). Model it on the existing `variant_line_keywords`
  config (env default + BridgeConfig override + ConfigResponse/ConfigUpdateRequest + the
  config API read/write). Default empty.
- Add a parser producing a normalized dict `{ normalize_vendor(sm): normalize_vendor(opentag) }`
  (reuse `app.core.matcher.normalize_vendor` so casing/whitespace match). Tolerate blanks,
  missing `=`, duplicates.

### 2. Apply in OpenTag matching (`backend/app/core/opentag_match.py` + `backend/app/api/opentag.py`)
- Add a helper `resolve_opentag_brand(sm_vendor_name, aliases) -> str`:
  `key = normalize_vendor(sm_vendor_name); return aliases.get(key, key)`.
- Matches endpoint: when looking up brand candidates, use the resolved brand:
  `candidates = materials_by_brand.get(resolve_opentag_brand(sm.vendor.name, aliases), [])`.
- `score_candidate`: the vendor/brand component must also honor the alias so the matched
  candidate isn't under-scored on vendor. Pass the alias map (or the resolved SM brand) into
  `score_candidate`/`find_best_match` and compare the RESOLVED SM brand to
  `normalize_vendor(opt.brandName)`. (Exact-UUID matches don't use brand — unaffected.)
- Load `opentag_vendor_aliases` from config in the matches endpoint (parsed dict).

### 3. Settings UI (`frontend/src/pages/Settings.tsx` + types/client)
- Add a text field "Manufacturer mappings (Spoolman → OpenTag)" bound to
  `opentag_vendor_aliases`, with help text and an example placeholder (`prusa=prusament,
  polyterra=polymaker`). Model it on the existing variant-keywords field. Update
  `ConfigResponse`/`ConfigUpdateRequest` TS types + the config client.

## Verification

- `cd backend && pytest` — tests:
  - parser: `"prusa=prusament, foo = bar"` → `{"prusa":"prusament","foo":"bar"}`; blanks/no-`=`
    ignored.
  - `resolve_opentag_brand("Prusa", {"prusa":"prusament"}) == "prusament"`; unmapped →
    `normalize_vendor`.
  - matches endpoint: a Spoolman "Prusa" filament with alias `prusa=prusament` now finds
    Prusament OpenTag candidates (was no-match) and the vendor component scores as a match;
    without the alias it still doesn't match Prusament.
- `cd frontend && npx tsc --noEmit && npm run build`.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md`: Settings `opentag_vendor_aliases` maps Spoolman vendor names to
   OpenTag brand names for cleanup matching (the brand pre-filter is otherwise exact).
3. Non-interactive subagent run: when pytest + build pass, stage ONLY the files this task
   touched (incl. prompt move + docs) and commit on `dev` with one `feat:` message. Never
   `git add -A`. Never push.
