# Decision record

## 2026-06-07 — OpenTag review: exact-UUID match, existing identity display, reviewable name

### Exact-UUID match (confidence 1.0)

`GET /api/openprinttag/matches` now builds a `by_uuid` index over the full materials list.
Before fuzzy scoring, if the SM filament's `extra.openprinttag_uuid` (decoded) exists in
that index, the corresponding material is returned directly with `confidence = 1.0`,
bypassing brand-filter and all fuzzy scoring. This covers SM filaments that were already
tagged by a prior cleanup run — they are immediately re-identified without re-scoring.

### Review shows existing OpenTag identity

`_build_field_rows` in `backend/app/api/opentag.py` now **includes** `extra.openprinttag_slug`
and `extra.openprinttag_uuid` as review rows (previously excluded, commit 48c05d6 was reversed).
Each row's `spoolman_value` is the SM filament's current decoded extra value — blank/`None` when
unset, showing the existing identity when already set.  The removal of the frontend's explicit
slug/uuid push in `OpenTagCleanup.tsx` (`~274-275`) prevents duplicates: the rows are now
the single source, and `_build_sm_patch` deduplicates via the `if key not in native["extra"]`
guard for anything that also comes through `decision.openprinttag_slug/uuid`.

### Reviewable name field (default OpenTag)

`opt_to_spoolman_fields` in `backend/app/core/opentag_match.py` now includes
`result["name"] = opt.get("name")` — the OpenTag material name is offered as the
Spoolman filament name.  The `name` row flows through the generic field-rows path: default =
OpenTag value, keep-mine toggle supported, `_build_sm_patch` writes it as a native Spoolman
field when not kept.  `spoolman_value` for the `name` row is set to `sm_fil.name` by
`_current_spoolman_value` (native attribute lookup).

## 2026-06-07 — filamentdb_material_tags stored as CSV string in Spoolman text extra field

Spoolman's text extra fields accept a JSON-quoted string value (e.g. `"17,28"` on the wire
becomes `'"17,28"'` in the PATCH body). They do NOT accept a JSON array (`"[17]"` → 400 Bad
Request). The bridge was passing a Python list through `encode_extra_value` which does
`json.dumps(value)` — so `[17]` became `"[17]"`, a JSON array, causing every PATCH to
`filamentdb_material_tags` to 400. The field has therefore never persisted any values.

**Fix:**

- `serialize_material_tags(ids)` in `backend/app/core/material_tags.py` converts an iterable
  of ints to a sorted comma-separated string (`"17"`, `"17,28"`, `""`).
- `parse_material_tags(raw)` in the same module parses back to `list[int]`, tolerating the new
  CSV string form, an empty string, the legacy JSON-array string (`"[17]"`), and a real Python
  list (all backward-compatible).
- The two write sites now call `encode_extra_value(serialize_material_tags(ids))`:
  - `opt_to_spoolman_fields` in `backend/app/core/opentag_match.py` (OpenTag apply path)
  - FDB→SM finish-tag write in `backend/app/core/engine.py` `_sync_finish_tags`
- The read site (`_sm_finish_ids_from_filament` in engine.py) now uses `parse_material_tags`
  after `decode_extra_value` instead of the old `isinstance(decoded, list)` branch.
- The apply error handler in `backend/app/api/opentag.py` now logs `exc.response.text` when
  available so future 4xx errors show Spoolman's detail message.

The snapshot signature (`",".join(str(i) for i in sorted(ids))`) was already CSV — now the
stored value matches it, so the round-trip is stable (no flapping).

## 2026-06-07 — OpenTag apply no longer writes multi_color_direction when secondaryColors is empty

`opt_to_spoolman_fields` in `backend/app/core/opentag_match.py` previously set
`multi_color_direction` ("coaxial" or "longitudinal") in the branch where an arrangement
tag is present but `secondaryColors` is empty (always the case in FDB's denormalized feed).
Spoolman rejects a PATCH with `multi_color_direction` but no `multi_color_hexes` → 422,
causing the entire filament apply to fail for multicolor filaments (e.g. SM #86 Silk Gradient).

The fix removes the `multi_color_direction` assignment from that branch entirely.  When OpenTag
carries no `secondaryColors`, neither `multi_color_direction` nor `multi_color_hexes` is
emitted — Spoolman's existing arrangement data is left untouched.  The `if secondary:` branch
(which sets both fields together when real secondary colors are present) is unchanged.

This is correct because the SM filament already has the right multicolor hexes + direction
(that's how the match was found in the first place via `sm_color_profile` reading
`sm.multi_color_direction`).  The apply has nothing new to add for those fields when OPT
provides no secondary colors.

## 2026-06-07 — OpenTag apply self-creates required extra fields; ensure_extra_fields is per-section resilient

### Root cause

The OpenTag apply endpoint (`POST /api/openprinttag/apply`) was 422-ing on every filament
because the Spoolman filament extra fields `openprinttag_slug` and `openprinttag_uuid` were
never created. `ensure_extra_fields` creates these at startup but is wrapped in a swallow-all
`try/except` in `main.py`, so a transient/partial failure at startup left them missing
silently — with no log entry visible to the user.

### Fix 1: apply self-heals (`backend/app/api/opentag.py`)

`opentag_apply` now calls `await sm.ensure_extra_fields()` once before the decision loop.
`ensure_extra_fields` is idempotent (only POSTs fields not yet defined), so calling it on
every apply is safe and cheap. A failure in this call returns a clear 502
`opentag_field_setup_failed` error with a descriptive message, rather than letting the first
PATCH attempt fail with a 422 for each filament.

### Fix 2: per-section isolation in ensure_extra_fields (`backend/app/services/spoolman.py`)

The spool field section and the filament field section now each wrap their
`get_field_definitions(...)` call (previously un-try'd) in independent try/except blocks.
A failure in the spool section logs a warning and continues to the filament section; a
failure in the filament section does not block the spool section. This means a transient
Spoolman error against one entity type cannot silently leave the other type's fields
uncreated.

The per-field creation `except` was broadened from `httpx.HTTPStatusError` only to
`(httpx.HTTPStatusError, httpx.RequestError)`, so transient connection/timeout errors
on individual field POSTs are logged and skipped rather than bubbling up and aborting
the remaining fields.

### Fix 3: main.py docstring tidied

The startup comment (step 4) previously said "the three cross-ref fields". It now
accurately lists the full set: cross-ref spool fields +
`filamentdb_material_tags` / `openprinttag_slug` / `openprinttag_uuid`.

All field creation stays via the Spoolman REST API (`POST /api/v1/field/{entity}/{key}`),
never touching the DB directly.

## 2026-06-06 — OpenTag matcher: arrangement-from-tags, polymer-family gate, finish-aware scoring

Three systematic failures found via a real-data audit (bridge matcher run over live Spoolman DB
+ the 12,501-record OpenTag cache) were fixed in `backend/app/core/opentag_match.py` and
`backend/app/api/opentag.py`:

### 1. Arrangement derived from tags, not secondaryColors (critical)

FDB's denormalized OpenTag feed leaves `secondaryColors` **empty on all 12,501 records**.
Arrangement is only present in the string `tags` array (e.g. `"coextruded"`,
`"gradual_color_change"`).  `opt_color_profile` previously checked `secondaryColors` first
— when empty it returned `"single"`, so every multicolor SM filament got 0 candidates.

**Fix:** `opt_color_profile` now checks the `tags`/`optTags` arrangement FIRST (via
`arrangement_from_tags`), regardless of `secondaryColors`.  Only falls back to
`secondaryColors` for the `multi_unknown` case (secondaries present, no arrangement tag).

**Apply-side guard:** `opt_to_spoolman_fields` no longer writes `multi_color_hexes` when
the OPT entry has empty `secondaryColors` (which is always in the real feed) — Spoolman's
existing multicolor hex data is preserved.  `multi_color_direction` is still set from the
arrangement tag.

### 2. Polymer-family hard gate in the matches endpoint

`material_family(material)` normalises a material string to a base polymer family:
`PLA/PLA+` → `pla`; `PETG` → `petg`; `ASA` → `asa`; `ABS` → `abs`; `PC` → `pc`;
`TPU/TPE` → `tpu`; `PA/Nylon/PA-CF/PA6` → `pa`; `PVA` → `pva`; unknown → passthrough.
Strips finish words first so `"PLA Silk"` → `"pla"`.

In `GET /api/openprinttag/matches`, after the brand + color-profile filters, candidates are
further filtered to the same `material_family` as the SM filament.  An empty/unknown SM
material bypasses the gate (all candidates scored).  This kills PC→ASA, ASA→PETG.
PLA↔PLA+ remain matchable (same family).

### 3. Finish-aware scoring with finish-word stripping

**Rebalanced weights** (old → new):

| Component | Old | New |
|---|---|---|
| Type/material (exact) | 0.25 | 0.20 |
| Vendor/brand (exact) | 0.25 | 0.20 |
| Color-name similarity | 0.35 | 0.30 |
| Finish component | +0.05 reward only | +0.075 neutral / +0.15 reward / −0.10/−0.15 penalty |
| Color hex proximity | 0.10 | 0.10 |

**Finish-word stripping:** `_color_name_tokens` already removed finish words; these were
already included in the `tag_map` iteration (silk, matte, transparent, etc.).  This means
`"Transparent Orange"` → `{orange}` and `"Silk Bronze"` → `{bronze}` BEFORE the name-
similarity comparison — finish mismatch is handled entirely by the finish component.

**`_finish_score(sm_ids, opt_ids)` returns:**
- both empty (solid vs solid): `+0.075` (neutral)
- perfect finish match: `+0.15`
- partial overlap: `jaccard × 0.15`
- one solid, one finished (clear mismatch): `−0.15`
- both finished but disjoint (matte vs silk): `−0.10`

This drops a wrong-finish candidate (Transparent Orange, Silk White) below the correct
plain/solid one when the SM filament has no finish tags.

Verified by 562 passing tests including 24 new tests covering: tag-based profile with empty
secondaryColors; coaxial SM matches coextruded OPT (the real-data path); apply-side guard
preserves multi_color_hexes; polymer-family gate (PC≠ASA, ASA≠PETG, PLA=PLA+); finish
scoring (solid vs silk, solid vs transparent, matte vs silk, finish-word stripping).

## 2026-06-06 — OpenTag matching hard-filters by color profile; apply sets multi_color_direction + handles empty primary

The OpenTag matcher was arrangement-blind — a multicolor Spoolman filament (coaxial/longitudinal)
could wrongly match a solid OpenTag product, or the wrong arrangement.

**Phase 1 — Color-profile pre-filter in `GET /api/openprinttag/matches`:**

Three pure helpers added to `backend/app/core/opentag_match.py`:

- `sm_color_profile(sm)` — `single` (no `multi_color_hexes`), `coextruded` (`coaxial`),
  `gradient` (`longitudinal`), or `multi_unknown` (hexes present, direction absent).
- `opt_color_profile(opt, tag_map)` — `single` (no `secondaryColors`), `coextruded` (optTag 29
  or string tag "coextruded"), `gradient` (optTag 28 or "gradual_color_change"), `multi_unknown`.
  Reads both the integer `optTags` array and the string `tags` array for arrangement detection,
  reusing `color.arrangement_from_tags`.
- `profiles_compatible(a, b)` — hard rules: `single↔single` only; `coextruded↔coextruded` only;
  `gradient↔gradient` only; `multi_unknown` (either side) matches any multicolor but never `single`.

In `opentag_matches` (`backend/app/api/opentag.py`), after the brand pre-filter, candidates are
further filtered to those whose profile is compatible with the SM filament's profile. `find_best_match`
remains pure — receives the already-filtered list.

**Phase 2 — Complete `opt_to_spoolman_fields` multicolor mapping:**

- When the matched OPT entry is coextruded (optTag 29) or gradient (optTag 28), delegates to
  `fdb_multicolor_to_sm(opt_color, secondary, opt_tags_int)` so the OPT→SM mapping is consistent
  with the FDB→SM sync direction. This sets `multi_color_direction` (`"coaxial"` or `"longitudinal"`),
  `multi_color_hexes`, and `color_hex`.
- Empty primary `color` (common for coextruded) is handled automatically: `fdb_multicolor_to_sm`
  synthesises `color_hex` from the first secondary for coextruded filaments.
- For `multi_unknown` (secondaries present, no arrangement tag), the hexes are preserved in
  `multi_color_hexes` but no direction is set.
- Single-color OPT entries are unchanged (primary `color` → `color_hex`, no multi fields).

Verified by 538 passing tests including 44 new tests for profile detection (both sides, incl.
empty-primary dual-color), profile compatibility rules, `opt_to_spoolman_fields` multicolor output,
and endpoint integration (coaxial SM matches only coextruded; single never matches multicolor;
longitudinal matches gradient).

## 2026-06-06 — OpenTag matcher: color NAME is the key within-brand/material discriminator; hex demoted

`score_candidate` in `backend/app/core/opentag_match.py` previously ignored the color
name entirely — it scored brand (0.30) + material (0.40) + hex-proximity (0.20) +
finish (0.10). Within a brand+material, all color variants received the same 0.70
baseline and the tiebreaker was RGB distance, which is unreliable (e.g. CB6D30 "Orange"
is closer in RGB to AF784D "Copper" than to some true-orange hex).

**Fix:** rebalanced weights and added a color-name similarity component:

| Component | Old weight | New weight |
|---|---|---|
| material/type (exact) | 0.40 | 0.25 |
| vendor/brand (exact) | 0.30 | 0.25 |
| **color-name similarity** | — | **0.35** |
| color hex proximity | 0.20 | 0.10 |
| finish tag overlap | 0.10 | 0.05 |

Two new pure helpers:
- `_color_name_tokens(name, vendor, material, tag_map)` — strips vendor tokens, material
  tokens (base + full), and finish keywords from the name string; returns the remaining
  lowercase token set (the isolatable color name).
- `_name_similarity(sm_tokens, opt_tokens)` — Jaccard similarity with a containment bonus
  for single-token colors; returns 0.5 (neutral) when either side has no color token so
  naming gaps don't nuke an otherwise-good match; returns 0.0 when both sides have tokens
  and they're disjoint.

With these changes, "Orange / Hatchbox / PETG" scores the OpenTag Orange candidate strictly
higher than the Copper candidate of the same brand+material, even when the Orange hex is
RGB-closer to Copper. Verified by `test_orange_vs_copper_bug_orange_scores_higher` and
`test_find_best_match_returns_orange_not_copper`.

## 2026-06-06 — OpenTag cleanup: instant dataset banner + staged fetch/match progress

Added `GET /api/openprinttag/status` — a side-effect-free endpoint that reads local
cache metadata via `opentag_cache.get_cache_metadata()` without calling FDB. Returns
`{ exists, fetched_at, count, stale, max_age_hours }`. New `OpenTagCacheStatus` Pydantic
model; matching `OpenTagCacheStatus` TypeScript interface + `getOpenTagStatus` client fn.

The `OpenTagCleanup.tsx` page now has two-phase startup:

1. **Instant banner** — `getOpenTagStatus()` fires on mount and populates the dataset
   banner (count + relative age + stale chip) immediately, before any slow work starts.
   While the status call is in-flight the banner reads "Checking dataset cache…".

2. **Staged loading messages** — once the status resolves, a `runLoad(skipRefresh)` call
   begins. A spinner + `statusMsg` string is shown prominently during work:
   - Cold run (cache missing or stale): "Fetching the OpenTag dataset from Filament
     DB… (first load downloads ≈11k records — up to a minute)" while `POST /refresh`
     runs, then "Matching your Spoolman filaments…" while `GET /matches` runs.
   - Warm run (cache fresh): skips the fetch stage entirely, shows only
     "Matching your Spoolman filaments…".
   - Refresh button always forces cold run.

The existing review → confirm → apply flow is unchanged.

## 2026-06-06 — OpenTag matching pre-filters candidates by normalized brand for performance; progress logged

`GET /api/openprinttag/matches` was hanging because `find_best_match` scored all ~11k
OpenTag materials for every Spoolman filament — hundreds × 11k scoring ops per request.

**Fix:** in `opentag_matches` (`backend/app/api/opentag.py`), a `materials_by_brand`
index is built once from the full dataset, keyed by `normalize_vendor(m.get("brandName"))`.
For each SM filament, only its brand's candidates are passed to `find_best_match`.
A SM vendor with no matching OpenTag brand gets an empty candidates list → no-match (correct;
brand is a strong signal). `find_best_match` is unchanged in signature and behavior.

**Progress logging added** before and after the scoring loop:
- Before: `opentag matches: scoring N filaments against M materials across B brands`
- After: `opentag matches: X matched, Y no-match`

These were absent, which is why the user saw "no log entries" during the long hang.

## 2026-06-06 — FDB /api/openprinttag returns OPTDatabase wrapper; bridge extracts .materials; cache self-heals malformed data

### Root cause

`GET /api/openprinttag` on Filament DB returns an **OPTDatabase wrapper object**, not a bare
list of OPTMaterial dicts:

```json
{ "brands": [...], "materials": [...], "cachedAt": "...", "totalFFF": N, "totalSLA": N }
```

The bridge's `get_openprinttag()` was doing `return resp.json()` and treating the whole dict
as the materials list. Downstream code iterated the 5 dict *keys* (strings `"brands"`,
`"materials"`, etc.) — hence "saved 5 materials" in the log and
`AttributeError: 'str' object has no attribute 'get'` in `score_candidate` when a key string
was passed as an OPTMaterial.

### Fix

**`FilamentDBClient.get_openprinttag()`** now extracts the nested `materials` array:

```python
data = resp.json()
if isinstance(data, dict):
    return data.get("materials", []) or []
return data  # already a list (defensive)
```

`brandName` is already present on each OPTMaterial dict, so the separate `brands` list is
not needed by the bridge.

**`load_opentag_dataset()` in `opentag_cache.py`** self-heals a malformed cache: if the
stored `materials` list is not a non-empty list of dicts (e.g. contains string keys from the
old bug), the loader treats the cache as stale and re-fetches — no manual Refresh required.

**`find_best_match()` in `opentag_match.py`** defensively filters out any non-dict candidate
before scoring, so a single bad entry cannot 500 the whole matches endpoint.

## 2026-06-06 — OpenTag cleanup API renamed to /openprinttag/*; 120 s fetch timeout; structured fetch errors

### Route rename: /opentag/* → /openprinttag/*

The bridge's OpenTag cleanup routes were at `/api/opentag/matches`, `/api/opentag/refresh`,
and `/api/opentag/apply`. The token `opentag` (without "print") collides with the "Qubit
OpenTag" web-analytics product, which EasyList and uBlock filter lists block at the network
layer. Chrome reported `net::ERR_BLOCKED_BY_CLIENT` for every request, while the bridge log
showed nothing (the requests never reached the backend).

The routes are now at `/api/openprinttag/matches|refresh|apply`. The string `openprinttag`
does not contain the blocked `opentag` substring, and FDB already exposes
`/api/openprinttag` through the same ad blocker without issues. The client-side SPA route
`/opentag-cleanup` is unchanged (browser navigation is not a network request and isn't
blocked). Function and type names in the codebase are unchanged.

### 120 s per-request timeout for get_openprinttag()

`FilamentDBClient.get_openprinttag()` now passes `timeout=httpx.Timeout(120.0)` to the
HTTP GET. The global client timeout stays at 15 s for all other endpoints. The cold fetch
downloads FDB's ~3 MB gzip tarball and extracts it on the server, which takes 20–60 s.

### Structured fetch errors (504/502) with logger.error

`opentag_refresh` and `opentag_matches` now catch `httpx.TimeoutException`,
`httpx.HTTPStatusError`, and `httpx.RequestError` from `load_opentag_dataset` and raise
`api_error(...)` responses with stable codes:

- `httpx.TimeoutException` → 504 `opentag_fetch_timeout`
- FDB 404 `HTTPStatusError` → 502 `opentag_unavailable` (FDB too old)
- other HTTP/request errors → 502 `opentag_fetch_failed`

Each failure branch calls `logger.error(...)`. The frontend renders the backend `message`
field in a visible error box, and shows a descriptive loading message during the long cold
fetch (noting 20–60 s is expected).

## 2026-06-06 — OpenTag cleanup tool + scoped FDB settings-bag exception

### OpenTag cleanup tool

New standalone tool (`/opentag-cleanup` page, `GET /api/openprinttag/matches`,
`POST /api/openprinttag/refresh`, `POST /api/openprinttag/apply`) that:

1. Fetches the OpenPrintTag dataset from FDB's `GET /api/openprinttag`, caches it
   locally in `DATA_DIR/opentag_cache.json` with a configurable 24-hour staleness
   threshold (`OPENTAG_CACHE_MAX_AGE_HOURS`).
2. Scores each Spoolman filament against the cached OPTMaterial list using a
   weighted scoring function (type/material 40%, vendor/brand 30%, color proximity
   20%, finish-tag overlap 10%).
3. Shows a per-field review UI with Spoolman value vs OpenTag value (default OpenTag,
   editable, per-field "keep mine"). "Ignore match" dismisses a whole filament.
4. Shows a full confirm screen listing every write before any action is taken.
5. On Apply, PATCHes each Spoolman filament with only the non-keep_mine fields
   (including `openprinttag_slug` + `openprinttag_uuid` as extra fields), then calls
   `merge_filament_settings()` on the linked FDB filament to carry the two identity
   keys into FDB's `settings{}` bag.

Reuses `#1`'s finish-tag map (`filamentdb_material_tags`) and `material_tags.py`.
Does not change any existing sync or wizard behavior.

### Scoped FDB settings{} bag exception (Phase 5)

**Rule relaxed:** CLAUDE.md prohibits touching FDB's `settings{}` bag (slicer passthrough).

**Exception granted (2026-06-06):** `FilamentDBClient.merge_filament_settings()` in
`backend/app/services/filamentdb.py` is the only approved path. It ONLY merges the
two keys `openprinttag_slug` and `openprinttag_uuid` — never reads, removes, or
modifies any other key.

**Implementation:** read-modify-write — fetch current filament detail, read existing
`settings` bag (default empty dict), check if both keys are already equal (idempotent,
no HTTP PUT if equal), merge only those two keys, write back. The `_STRIP_BEFORE_PUT`
stripping is bypassed for this path because `settings` is in that strip set — the
merged `settings` bag is re-attached to the PUT payload after stripping.

**Wire points:**
- `backend/app/api/opentag.py` → `POST /api/openprinttag/apply` calls it after writing
  each SM filament when `fdb_filament_id` is provided.
- `backend/app/core/engine.py` → `_sync_opentag_identity()` is called once per live
  sync cycle (not dry-run) to ensure any SM filament with slug/uuid extras has them
  mirrored into FDB. Non-fatal per pair.
- `backend/app/api/wizard.py` → Pass 2.7 in `_execute_spoolman_to_fdb` pushes slug/uuid
  from newly-created FDB filaments' SM counterparts on wizard execute.

**Not wired for FDB→SM direction** (FDB's settings bag is not read by the bridge for
other purposes; the SM side is the authoritative source for these identity keys).

## 2026-06-06 — Name-collision detection is vendor-aware

`_compute_name_collisions` in `backend/app/api/wizard.py` now keys both the
`existing` FDB filament map and the `incoming` create-plan map on
`(normalize_vendor(vendor), normalize_name(name))` instead of `normalize_name(name)`
alone.

**Why non-obvious:** the original name-only key caused false-positive collision flags
when two vendors happen to sell a filament with the same name (e.g. "Beige" from
ELEGOO and "Beige" from Bambu Lab). The bridge's own matcher already keys on
vendor+name+color, so the collision check should be at least as precise. Same
vendor+name still flags correctly (genuine potential duplicate); different vendors
with the same name do not.

## 2026-06-06 — Conflict cards carry snapshot-derived identity

Each conflict card now shows a compact identity header (color swatch, label,
material chip, hex chip, SM spool id, FDB filament id, FDB spool id) so the
user can identify the record at a glance without following deep-link icons.

**Where the data comes from:** `_conflict_identity(db, c)` in
`backend/app/api/conflicts.py` loads the Spoolman snapshot for the conflicting
entity — the **spool** snapshot (`source="spoolman", entity_type="spool"`) for
spool conflicts, the **filament** snapshot for filament conflicts — and extracts
`filament.name`, `filament.vendor.name`, `filament.color_hex`, `filament.material`
(spool path) or the top-level equivalents (filament path). The composed label is
`"{vendor} {name}".strip()` falling back to `"SM #{spoolman_id}"` when the
snapshot is absent.

**Read-only enrichment only:** the `_conflict_identity` helper performs no writes
and does not participate in conflict detection or resolution logic. The five new
fields (`label`, `vendor`, `name`, `color_hex`, `material`) are nullable on
`ConflictResponse` — existing consumers that don't need them are unaffected.

## 2026-06-06 — FDB create_spool returns the filament doc; extract spool _id by label match

`POST /api/filaments/:id/spools` returns the **filament document** (with its embedded
`spools[]` array), not the new spool subdocument. The bridge was reading `raw["_id"]`
directly, which is the **filament** id — so every `SpoolMapping.filamentdb_spool_id`
was set to the filament id instead of the spool id. This caused every per-spool lookup
(deletion detection, weight sync, field sync) to fail with "Record deleted upstream"
because the filament id was never found in `fdb_spool_index` (keyed by real spool ids).

**Fix:** `extract_created_spool_id(resp, *, label_field, label_value)` in
`backend/app/services/filamentdb.py` finds the just-created spool inside `resp["spools"]`
by matching `label_field` (the `FILAMENTDB_SPOOLMAN_ID_FIELD`, default `"label"`) against
`label_value` (the Spoolman spool id stored on create). Falls back to the last entry in
`spools[]` if no label match; handles a bare-spool response defensively. Applied at both
call sites: `wizard.py` (`_execute_spoolman_to_fdb`) and `engine.py`
(`_handle_new_sm_spool`).

**Pre-fix mappings are corrupt** — every `spool_mappings` row written before this fix has
`filamentdb_spool_id == filamentdb_filament_id`. The user should clear these rows and
re-run the wizard import to produce correct mappings. Any open `__record_deleted__`
deletion conflicts for those spools are stale artifacts and can be dismissed.

## 2026-06-06 — Stale cross-ref no longer skips spool creation; spoolWeight from resolved tare

### Bug A: stale filamentdb_spool_id cross-ref blocked spool creation

When Filament DB is wiped or a spool is deleted, Spoolman spools still carry the old
`filamentdb_spool_id` extra pointing at a now-deleted FDB spool. Previously, the planner
(`_plan_spoolman_to_fdb` Phase C) and the ongoing engine new-spool detection both treated
any non-empty cross-ref as "already linked" and skipped creating the FDB spool — leaving
filaments with no spools after re-import.

**Fix:** a cross-ref only causes a skip when the referenced FDB spool id actually exists
in the current FDB dataset (`existing_fdb_spool_ids` in the planner; `fdb_spool_index` in
the engine). A stale xref falls through to create, and the write-back overwrites the stale
id automatically. A live SpoolMapping row still always skips (unchanged).

The `plan_dry_run` step-4 filter is updated to also remove engine-generated `new_spool`
conflicts for cross-ref orphans (previously they were not cleaned up in the stale-xref path
because the stale-xref check in the engine used to skip before reaching
`_handle_new_sm_spool`).

### Bug B: FDB filament spoolWeight was written from raw sm.spool_weight (often NULL)

The wizard computes a resolved tare per filament (user override → spool spool_weight →
filament spool_weight → 200 g default) and uses it to compute spool `totalWeight`. But
`_fdb_filament_payload_from_sm` wrote `spoolWeight` from raw `sm.spool_weight`, which is
NULL for many Spoolman filaments. Result: FDB got the correct `totalWeight` but
`spoolWeight=null`, so the % bar math was wrong (gross - 0 = full rather than gross - tare).

**Fix:** thread the resolved tare into `_fdb_filament_payload_from_sm` via a new
`resolved_tare` parameter. Phase A of `_plan_spoolman_to_fdb` computes
`_resolve_filament_tare(sm_fil, fil_spools, tare_by_sm_spool)` (same resolution chain as
the Phase C gross computation) and passes it through. `spoolWeight` is now always set to
the resolved tare (guaranteed ≥ 200 g), not the raw Spoolman field.

## 2026-06-06 — Import now sets FDB netFilamentWeight from Spoolman filament weight

When the wizard imports a Spoolman filament into Filament DB, `_fdb_filament_payload_from_sm`
now sets `netFilamentWeight` (the full spool capacity) on the create payload so that Filament
DB can compute and render the spool fill % bar immediately after import.

Resolution order: use `SpoolmanFilament.weight` when set; fall back to the `initial_weight`
of the first spool (sorted by id, mirroring `resolve_effective_cost`) that has a non-null
value; omit the field entirely if neither is available (Filament DB continues to show "—",
no fabricated value). `spoolWeight`, `totalWeight`, `planned_gross`, and all weight math are
unchanged — this is a purely additive create-payload field.

Because FDB already logs Spoolman weight decrements as usage entries (FR-9), the % bar will
track downward automatically as usage accrues once `netFilamentWeight` is set — no
ongoing-sync change is needed. Backfilling `netFilamentWeight` on filaments imported before
this fix is a possible follow-up, not implemented here.

## 2026-06-06 — Dry-run preview lists in-sync pairs as "matched — no updates"

Spool pairs that are already in sync produced no preview entry, making the dry-run
invisible for synced data. Each such pair now emits a `{"action": "matched", "reason":
"in sync — no updates", ...}` entry in the dry-run preview — spool-pair scoped (weight
and field-mapping passes only; filament-level multicolor/cost passes emit their own
separate rows and are unaffected).

**Dry-run only.** The `_preview_len_before_pair` sentinel tracks whether any preview
entry was appended during the weight + field passes for the pair iteration. If the
preview length is unchanged at the end of the pair block and `dry_run=True`, a single
"matched" entry is appended. Real (non-dry-run) cycles never emit it.

**First-baseline pairs are excluded.** Pairs without prior snapshots fall into the
existing `skip` (baseline) path and `continue` before reaching the matched block —
correct behavior preserved.

**Frontend:** `SyncPreviewEntry.action` gains `"matched"`. The Dashboard dry-run
summary includes a muted "Matched — no updates (N)" section with a "Show/Hide" toggle
(default shown), and the counts bar shows a "Matched: N" figure when N > 0.

## 2026-06-06 — New-spool direction enforced; wizard writes new keys; old source-of-truth removed

### New-spool creation is now a real enforced direction (default two_way)

`new_spool_sync_direction` replaces the dead `new_spool_source_of_truth` config key.
The old key was read from the DB but never checked — all new-spool detection paths
always ran bidirectionally. The new key is enforced in `core/engine.py`'s new-spool
detection block:

- `two_way` (default) → both `_handle_new_sm_spool` (SM→FDB) and `_handle_new_fdb_spool`
  (FDB→SM) run — identical to pre-deploy behavior.
- `spoolman_to_filamentdb` → only SM→FDB creation runs (new SM spools get an FDB spool;
  new FDB spools are NOT created in Spoolman).
- `filamentdb_to_spoolman` → only FDB→SM creation runs.

The startup migration (`_migrate_sync_config`) sets `two_way` if the key is absent,
preserving current behavior for existing deployments.

### Wizard direction step now configures ongoing sync

The `POST /api/wizard/direction` handler previously wrote old `*_source_of_truth` keys
which the engine no longer read — so onboarding configuration had no effect on
ongoing sync. The handler now translates the wizard's binary per-category choice
(`spoolman` / `filamentdb`) into the new direction + conflict policy keys:

- `weight_source_of_truth=spoolman` → `weight_sync_direction=spoolman_to_filamentdb` +
  `weight_conflict_policy=manual`
- `weight_source_of_truth=filamentdb` → `weight_sync_direction=filamentdb_to_spoolman` +
  `weight_conflict_policy=manual`
- Same mapping for `material_properties_*` and `new_spool_*` categories.

The wizard's frontend payload (`WizardDirectionRequest`) is unchanged — the UI still
presents the binary per-category choice. A richer wizard UI with full
direction+policy selection is a later nicety.

### Old source-of-truth fields removed from the config surface

`weight_source_of_truth`, `material_properties_source_of_truth`, and
`new_spool_source_of_truth` are no longer present in `ConfigResponse`,
`ConfigUpdateRequest`, or the frontend `types.ts` / `Settings.tsx`. The keys remain
readable in `_DEFAULTS` and `_migrate_sync_config` for backward-compatible migration
reads only.

The Settings UI "New spools" row is replaced with a `DirectionSelect` (Two-way /
Spoolman → Filament DB / Filament DB → Spoolman) bound to `new_spool_sync_direction`.

## 2026-06-06 — Per-category sync direction + conflict policy (two-axis model)

### Replaced "source of truth" with two independent per-category axes

Each data category (`weight`, `material_properties`) now has two settings:

- **Write direction**: `two_way` | `spoolman_to_filamentdb` | `filamentdb_to_spoolman`
- **Conflict policy**: `manual` | `spoolman_wins` | `filamentdb_wins` | `newest_wins`
  (weight only for `newest_wins`; material_properties rejects it with HTTP 422)

### Two-way: lone change always propagates

In `two_way` mode, a lone change on either side always propagates to the other — no SoT
gating. The conflict policy is consulted ONLY when both sides changed since the last
snapshot. This enables true bidirectional sync without forcing a manual conflict review for
every single change.

### One-way modes never queue conflicts

In `spoolman_to_filamentdb` or `filamentdb_to_spoolman` mode, the locked destination's
drift is a NOOP — never queued as a conflict. The source side wins on the next cycle that
sources a change. This preserves backward-compatible behavior for users who relied on the
old SoT (one-way) semantics.

### newest_wins is weight-only

Spoolman exposes no per-filament modification timestamp (only `last_used`/`registered` at
the spool level). It cannot be used honestly for material_properties conflicts. The API
rejects `material_properties_conflict_policy=newest_wins` with HTTP 422. For weight,
`newest_wins` is anchored to the snapshot's `captured_at` (bridge last-sync time) — a
side's timestamp is only counted if it is strictly after that anchor, preventing stale
clocks from winning. When both timestamps are missing, equal, or indeterminate, the policy
falls back to `QUEUE_CONFLICT`. This is best-effort and clock-skew-prone; frequent syncing
is the reliable mitigation.

### Multicolor now follows material_properties direction

Before this change, multicolor/color sync was hardcoded two-way. After this change it
follows `material_properties_sync_direction`. The migration default is
`filamentdb_to_spoolman` (mirroring the old `material_properties_source_of_truth=filamentdb`
default). This is a deliberate, documented behavior change: multicolor changes that
previously propagated from Spoolman automatically will be NOOP under the default one-way
config until the user opts into two-way.

### Conflict dedup added

Without a dedup check, a both-changed pair would re-queue a new conflict row every sync
cycle (because the snapshot is not advanced on conflict). A new `_has_open_conflict` helper
checks for an existing OPEN conflict with the same `(entity_type, field_name, spoolman_id,
fdb_spool_id)` tuple before queuing. If one exists, the new conflict is skipped.

### Migration preserves pre-deploy behavior

`_migrate_sync_config(db)` in `app/main.py` runs once at startup after `seed_defaults`.
It reads the old `weight_source_of_truth` and `material_properties_source_of_truth` keys
and maps them to one-way direction + manual policy (behavior-identical). The function is
idempotent — if the new keys already exist it skips them. Fresh installs get the same
defaults as today's.

## 2026-06-06 — Filament cost sync: spool-price-first, filament fallback; matprop SoT; snapshot merge

### Effective Spoolman cost resolved spool-first

`resolve_effective_cost(filament_price, spools)` in `backend/app/core/fields.py` returns the
price of the first spool (by id) with a non-null `price`; if no spool has a price, it falls
back to the filament-level `price`. This is the canonical cost value used throughout the
bridge — in the wizard import and in ongoing sync.

### Wizard import: FDB filament create payload includes cost

`_fdb_filament_payload_from_sm` in `backend/app/core/planner.py` now accepts an
`effective_cost` keyword argument. `_plan_spoolman_to_fdb` resolves the cost for each
`create` action using the active (non-archived) spools for that filament and passes it to
the payload builder. The resulting `cost` field appears in the FDB filament create payload
and is visible in the Phase-4 planned-writes preview.

### FDB→SM write-back targets the Spoolman FILAMENT price

Because FDB cost is filament-level, the FDB→SM write direction updates
`spoolman.update_filament(sm_fil_id, {"price": fdb_cost_now})` — the Spoolman **filament**
price. Per-spool Spoolman prices are the user's actual purchase prices and must never be
overwritten by a filament-level value.

### Cost follows material_properties_source_of_truth

`_sync_cost` in `backend/app/core/engine.py` iterates `filament_mappings` each cycle,
computes effective SM cost (spool-first) and FDB cost, then:
- Neither side has cost → skip
- First sight (both snapshots have no `_cost` key) → store baseline, no write
- One side changed and SoT favours that side → apply the write
- Both changed and disagree → queue a `cost` conflict (never auto-resolve)
- Both changed into agreement → refresh baseline

SoT semantics mirror `resolve_field_map` / `_apply_field_changes` exactly — no new behavior.

### Filament snapshots now merge keys (_mc_sig + _cost coexist)

The multicolor and cost passes both store filament-level snapshots. Previously `_sync_multicolor`'s
inner `_store()` called `_upsert_snapshot` directly with only `{"_mc_sig": ...}`, replacing
the entire row on each write. A new `_merge_snapshot` helper (reads existing data, updates
the one key, writes back) is used by **both** passes. This means `_mc_sig` and `_cost`
coexist in the shared filament snapshot row and neither pass clobbers the other's key.
Regression test: `test_cost_and_multicolor_snapshots_coexist`.

## 2026-06-05 — Tare excluded from variant-prop conflicts; conflict badges name specific fields

### Tare (`spool_weight`) excluded from `sm_prop_conflicts`

`sm_prop_conflicts` in `backend/app/core/matcher.py` no longer checks `spool_weight`.
Previously, two filaments that were identical in every material property but had different
empty-reel tare values (e.g. ELEGOO PLA Beige tare 160 g vs Black tare 154 g) would yield
a non-empty conflict list, which set `suggest_exclude=True` on the non-master member and
pushed it to the ungrouped/standalone section — preventing auto-grouping.

This was self-contradictory: the wizard already unifies tare per variant group (the banner
"All variants in this group will use the master's empty-reel tare" makes this explicit) and
tare is a physical/estimated reel weight, not a property that distinguishes a product line.
Removing `spool_weight` from the check means a tare-only difference no longer flags a member
for exclusion or standalone suggestion.

The fix propagates to all three call sites automatically (both `wizard.py` at ~375 and ~535,
and `planner.py` at ~188). The `CONFLICT_FIELD_TO_CANONICAL` map and `computeConflicts`
mirror function in `StepVariances.tsx` were updated in parallel. Regression tests added:
`test_sm_prop_conflicts_tare_only_diff_returns_empty`, `test_sm_prop_conflicts_real_diff_still_detected`,
and `test_wizard_variances_tare_only_diff_does_not_suggest_exclude`.

### Conflict badges name specific differing fields

The standalone badge in `StepVariances.tsx` previously read "suggested standalone (prop conflict)"
for any filament with `suggest_exclude=True`. It now reads:

> suggested standalone — {field labels} differ

where the field labels are derived from a `CONFLICT_FIELD_LABELS` map that translates raw SM
field names to friendly display names (e.g. `settings_extruder_temp` → "nozzle temp",
`material` → "material/type"). Labels are deduped and joined with ", ". Example:
"suggested standalone — diameter, nozzle temp differ". If `conflicts` is empty but
`suggest_exclude` is true (shouldn't occur post-fix, but as a fallback), it reads
"suggested standalone".

The same `CONFLICT_FIELD_LABELS` map is used in the in-group "Conflicts with master:" box
so field names read consistently across both locations.

## 2026-06-05 — Reconcile canonical-key contract + editable master temps

### Canonical-key contract between frontend and backend

`ReconciledField.field` in the frontend MUST use canonical keys matching
`_RECONCILE_FIELD_MAP` in `backend/app/api/wizard.py`. The frontend constant
`CONFLICT_FIELD_TO_CANONICAL` (in `StepVariances.tsx`) maps raw Spoolman field
names to their canonical equivalents:

| Raw SM / conflict field | Canonical key |
|---|---|
| `material` | `type` |
| `settings_extruder_temp` | `nozzle_temp` |
| `settings_bed_temp` | `bed_temp` |
| `density`, `diameter`, `spool_weight` | (same) |

The state map `reconcileByGroup[groupIdx]` is also keyed by canonical names.
Raw field names are used only for display labels. `material_type` is excluded
from the reconcile set entirely — it is derived/display-only and not in the
canonical map; its mismatch chip is still shown but no reconcile option is offered.

**Why this was broken:** the original code emitted raw SM names
(`settings_extruder_temp`, `material`) as `ReconciledField.field`. The backend
`_RECONCILE_FIELD_MAP` checks `if canonical_key not in _RECONCILE_FIELD_MAP: continue`,
so temp and type reconcile decisions were silently dropped. Only `density`, `diameter`,
and `spool_weight` happened to have the same raw and canonical names, so those worked.

A regression test `test_wizard_execute_reconcile_nozzle_temp_overlays_fdb_and_patches_spoolman`
was added to `backend/tests/test_api.py` to lock this contract.

### Editable master temps

On the master member row in `StepVariances.tsx` (SM direction, auto groups only),
the read-only temps chip is replaced with two compact number inputs (nozzle and bed),
styled within the same orange chip. Editing upserts `nozzle_temp` / `bed_temp`
canonical reconcile entries with `source: 'manual'` into `reconcileByGroup[groupIdx]`,
which then flow to the FDB parent payload (via `temperatures.nozzle` / `temperatures.bed`)
and the Spoolman write-back PATCH (`settings_extruder_temp` / `settings_bed_temp`) via
the existing `handleSave` → POST → execute path — no backend changes.

Clearing an input removes the override key from the map (no null persisted).
Non-master rows retain the read-only chip.

Possible follow-ups (not in scope): editable type/diameter/density on master row;
editable temps on standalone rows; live conflict-badge update when master temp is overridden.

## 2026-06-05 — Variances type/diameter/temps display

Every variant-group member row and standalone filament row in `StepVariances.tsx` now
always renders three property chips: **type** (blue, from `filData.material` — SM's native
`material` field), **diameter** (gray, `{N} mm` or `⌀ —` when null), and **temps**
(orange, `{nozzle}° / {bed}°`, shown only when at least one temp is non-null).

The old `material_type`-only chip (green, prefixed "FDB:") was the primary type indicator
but it's only populated for `link` decisions — null in fresh imports. The fix: primary type
= `material` (always present from SM); `material_type` is now a secondary amber mismatch
chip shown only when it differs from `material`. All three fields (`diameter`,
`settings_extruder_temp`, `settings_bed_temp`) were already populated by the
`GET /wizard/variances` backend endpoint via the SM filament list fetch — no backend change
was needed.

## 2026-06-05 — Conflicts page: client-side type filter

`classifyConflict` derives a `ConflictType` bucket purely from `field_name` and `spoolman_id`
fields already present on `ConflictResponse` — no API or schema changes. `new_spool` direction
is disambiguated by `spoolman_id != null` (Spoolman-only spool) vs null (FDB-only spool), per
the engine's existing behavior. The filter bar appears only when two or more types are present,
so a single-type list is never cluttered with an unnecessary UI element.

## 2026-06-05 — Upstream deletion detection → conflict queue

### Design

When a mapped record disappears from an upstream fetch, the bridge now queues a
`Conflict` row with `field_name = "__record_deleted__"` (sentinel constant
`DELETION_FIELD` in `app/models/conflict.py`) instead of logging a skip/error and
continuing. This keeps the "conflicts are never auto-resolved" hard rule and gives the
user an explicit UI action to take.

**Archived vs deleted (Spoolman side):** `sm_all_ids` (set of all spool ids returned
by Spoolman, including archived ones) is built each cycle. An id absent from
`sm_all_ids` is gone entirely → deletion conflict. An id present but not in the
active (non-archived) dict → skip as before. This preserves the existing archived-spool
skip behavior.

**Dedup:** `_queue_deletion_conflict` checks for an existing open conflict with the
same sentinel `field_name`, `spoolman_id`, and `filamentdb_spool_id` before inserting.
This prevents a new conflict row from accumulating every cycle until the user resolves.

**Value encoding:** the surviving side's value carries
`{"exists": true, "deleted_side": "<spoolman|filamentdb>"}`. The deleted side is
`null`. The frontend keys off `deleted_side` to render a human-readable explanation
instead of a raw value diff.

**Dashboard / Synced Records:** `build_mapping_rows` already flips a row to
`status="conflict"` when any open conflict references its spool ids. No changes to
`mappings.py` were needed — queueing the deletion conflict is sufficient.

### Resolution cleanup

When `resolve_conflict` or `bulk_resolve` marks a `DELETION_FIELD` conflict as
resolved, `_cleanup_orphaned_mapping` deletes the `SpoolMapping` row and both `Snapshot`
rows for that pair from bridge-local SQLite. This is bridge-local state only — no
upstream writes. The mapping disappears from Synced Records and the Dashboard count
corrects itself on the next page load.

**Upstream re-create is Phase 2.** If the user wants to restore the deleted upstream
record and re-link it, that is a separate future workflow. The conflict router never
writes to Spoolman or Filament DB (existing hard rule; see "resolve = record, apply
next cycle" philosophy above).

## 2026-06-04 — variant_line_keywords user setting + Standalone "Move to existing group"

### variant_line_keywords — user-configurable finish/line keyword lexicon

`matcher.py`'s `extract_finish_line` and `sm_variant_cluster_key` now accept an optional
`keywords: list[str]` parameter. When provided, each keyword is matched whole-word
case-insensitively (`\bkeyword\b`); the first match becomes the finish token. When `keywords`
is `None`, the original `_FINISH_PATTERNS` regex lexicon is used (backward-compatible fallback
for tests and any non-wizard caller).

**Resolution:** env var `VARIANT_LINE_KEYWORDS` (comma-separated) seeds the default with the
same tokens as `_FINISH_PATTERNS` plus `rapid`. At runtime, `get_config_value(db, "variant_line_keywords", settings.variant_line_keywords)` lets the UI override the env default without a restart. `wizard_variances` and `wizard_variants` both call `_resolve_variant_keywords(db)` and pass the result to every `sm_variant_cluster_key` / `extract_finish_line` call. The matcher functions remain pure (no DB import). `ConfigResponse` / `ConfigUpdateRequest` expose `variant_line_keywords`; `Settings.tsx` adds an editor text field.

### Standalone rows gain "Move to existing group"

The Standalone section in `StepVariances.tsx` previously only offered multi-select "Group as
variants" (new group only). Each standalone row now also shows a **"Move to…"** dropdown
(via `movingStandaloneId` state + `moveFromStandalone` / `standaloneTargetOptions` helpers)
listing all existing non-empty auto/extra groups plus "New group". After a move the row
disappears from Standalone and joins the target group; `handleSave` is driven by membership
state so no special handling is needed.

## 2026-06-04 — Wizard per-member actions + finish-line auto-split (Part A/B)

Extends the 2026-06-04 D1–D4 redesign. Source of truth for D1–D4 remains that entry;
this section records the Part A (per-member actions) and Part B (finish-line split) additions.

### Part A — Per-member labeled actions replace the checkbox

`StepVariances.tsx` grouped-filament rows now show three labeled buttons per member instead of
a bare always-checked disabled checkbox:

- **Move to…** — dropdown listing all other auto/extra groups and "New group"; removes from source,
  adds to target (with master promotion if the moving member was master).
- **Standalone** — removes from group; member appears in the standalone list with its own tare.
- **Ignore** — calls `POST /wizard/matches/{sm_filament_id}/skip`, which sets `action: "skip"` in
  `wizard_match_decisions`, then removes from the group. Uses `_included_sm_ids()` as the single gate,
  so the change flows to variances/weights/preview/execute for free. No second exclusion set.

The `Ignore` button is also present on standalone filament rows and extra-group (manually grouped) rows.
Master radio button is unchanged. Groups dissolved to 0 members are hidden (no empty card).

`ignoreErr` is surfaced as a red text line above the Save/Back row.

### Part B — Finish-line auto-split extends D1 grouping key to 3-tuple

**Q1 resolved.** `sm_variant_cluster_key` in `matcher.py` now returns a 3-tuple
`(normalize_vendor, normalize_name(material), finish)` where `finish` is the output of
`extract_finish_line(name, material)`.

`extract_finish_line` uses a word-boundary-aware regex lexicon (ordered most-specific first):
`glow-in-the-dark / GITD`, `carbon fiber / CF`, `rainbow / multicolor`, `high-speed / HS`,
`metallic`, `marble`, `wood`, `matte`, `satin`, `silk`. Returns `""` for standard/unrecognized.

Effect: `ELEGOO PLA Red` and `ELEGOO PLA Silk Red` now get different cluster keys (`""` vs `"silk"`),
so they land in separate variant groups — preventing Silk from inheriting PLA print settings via the
parent. D2's `suggest_exclude` signal survives as a second-line safeguard for finish tokens not in the
lexicon. The lexicon is a closed set; user-driven move/standalone actions are the escape hatch.

FDB parent map keying in `wizard_variances` updated to 3-tuple `(vendor_norm, material_norm, finish_norm)`
so existing Silk FDB parents match Silk SM groups (not standard PLA parents).

`VariancesGroupRow` gains `finish: str | None` (shown in the group header as a violet pill).
Frontend `VariancesGroupRow` interface updated to match.

## 2026-06-04 — Wizard variant-resolution redesign: D1 grouping key, D2 suggest-exclude, D3 FDB-parent attach, D4 empty-spool toggle

Implements `docs/wizard-redesign.md` decisions D1–D4 in full. Source of truth is that spec;
this entry records the settled contract. See the "Part A/B" entry above for the Q1 resolution
(finish-line split) and per-member action redesign that followed.

### D1 — Grouping key is `(vendor, material)` — drop base_name (initial pass)

`sm_variant_cluster_key` in `matcher.py` returned a 2-tuple `(normalize_vendor, normalize_name(material))`.
The old 3-tuple included `base_name = strip_color_and_words(name, color_hex)`, which caused filaments
whose name IS a color word (e.g. "Brown", "Beige") to produce different base_names and never cluster.

All callers updated to unpack 2-tuples; extended to 3-tuples by Part B above.
Group display `base_name` is now `normalize_name("{vendor} {material}")` — consistent across all paths.

**Q1 simplification (initial pass, since superseded):** finish/line tokens (PLA Matte / Silk / PLA-CF)
were NOT parsed out in this pass. Q1 is now resolved by the Part B finish-line split above.

### D2 — Per-member exclude, pre-flagged by `sm_prop_conflicts`

`VariancesFilament` gains `suggest_exclude: bool = False`. Set to `True` for non-master members where
`sm_prop_conflicts(master, member)` returns ≥1 mismatch (density, extruder_temp, bed_temp, etc.).
Conflicts are still surfaced, never auto-resolved. The flag is a *hint* only — the user remains in
control via the membership checkboxes in `StepVariances.tsx`.

Pre-suggested-excluded members start unchecked in the initial `groupMembership` state (frontend).

Standalones also gain checkbox select + "Group as variants" action: select 2+ standalone filaments
and click the button to create an editable extra group (pick master via radio). This is the only
path to manually group filaments that the auto-clustering didn't detect.

### D3 — Load FDB state; resolve each incoming color as Attach / Create

`wizard_variances` now also loads `filamentdb.get_filaments()` and builds a
`(vendor_norm, material_norm) → FilamentRef` map of existing FDB parent lines (filaments with
`hasVariants=True` or with children pointing to them via `parentId`).

`VariancesGroupRow` gains `existing_fdb_parent: FilamentRef | None`. When set, the frontend offers
a per-group choice: **Attach to existing FDB parent** (default) vs **Create new parent**.

`SMVariantDecision` gains `existing_fdb_parent_id: str | None = None`. Semantics:
- **None** → SM-keyed master-promote (unchanged behavior: master becomes the FDB parent).
- **set** → ALL members (including the "master") are created with `parentId = existing_fdb_parent_id`;
  no new parent is created. The existing FDB parent is **never modified or deleted** — only `parentId`
  is written on newly-created variants.

New helper `_build_attach_parent_for_sm(decisions) → {sm_id: existing_fdb_parent_id}` in `wizard.py`.
In `_execute_spoolman_to_fdb` Pass 1: attach-group masters get `parentId` injected into the create
payload; `master_map[master_sm_id]` is set to `existing_fdb_parent_id` (not the newly-created FDB id),
so Pass 2 variants correctly receive `parentId = existing_fdb_parent_id`.

### D4 — "Include empty / depleted spools" toggle

Config key `wizard_include_empty_spools` (bool, default `False`) persisted via `get/set_config_value`.
"Empty" is defined as `not archived AND remaining_weight == 0.0` — same predicate as `_compute_empty_active`.

Applied in three places:
1. `wizard_variances` `spool_ids_per_filament`: empty spools omitted from `spool_ids` when toggle=False.
2. `_plan_spoolman_to_fdb` Phase C: `include_empty_spools: bool = True` parameter; when False, skips
   spool plan items for zero-weight spools. The filament/color plan item is still created (toggle only
   controls the *inventory record*, not the color definition).
3. `wizard_preview` / `wizard_execute` both pass the toggle to the planner.

New `GET /wizard/direction` endpoint returns `{import_direction, include_empty_spools}`.
`POST /wizard/direction` extended with `include_empty_spools: bool | None` (optional, backward-compatible).

Frontend Step 2 (`Step2Direction.tsx`): "Include empty / depleted spools" checkbox, default unchecked.
`StepNPreview.tsx` `EmptyActiveEntry` panel: badge turns blue (informational) when toggle=False with copy
"skipped by setting"; amber when toggle=True ("will be imported").

## 2026-06-03 — CI workflows, registry, and main branch protection

### Registry / repo slug

GitHub remote is `crzykidd/filament-bridge`; container registry is
`ghcr.io/crzykidd/filament-bridge`. Image authentication uses `GITHUB_TOKEN` with
`packages: write` permission — no additional secrets needed.

### Migration check command

`alembic env.py` reads the DB path from `settings.data_dir` (env var `DATA_DIR`), NOT from
a `DATABASE_URL` env var. The two required env vars `FILAMENTDB_URL`/`SPOOLMAN_URL` must
also be set for `Settings()` to initialise, even though their values are irrelevant for
schema-only migration checks. Correct CI command:

```
FILAMENTDB_URL=http://localhost SPOOLMAN_URL=http://localhost DATA_DIR=/tmp/alembic-check \
  alembic upgrade head
```

### CI check names (used in branch protection)

Workflow `CI` → jobs named exactly as follows (branch protection contexts =
`CI / <job-name>`):

| Context | Trigger |
|---|---|
| `CI / Lint` | push + PR |
| `CI / Config validation` | push + PR |
| `CI / Migration check` | push + PR |
| `CI / Compose validation` | push + PR |
| `CI / Image build` | PR only |

`CI / Test` (pytest) is a bonus job — NOT a required check.

### main branch protection

Applied via `gh api` (see command below). Required: PR + all 5 checks green, no direct
pushes, no force-pushes. `required_approving_review_count: 0` (single-developer repo).
`strict: false` (branch need not be current with main before merge).

**Verify check names after first CI run.** GitHub registers check contexts only after
they've executed. If the names above don't match what appears in
Settings → Branches → main protection, update them there or re-run the command below.

```bash
gh api -X PUT /repos/crzykidd/filament-bridge/branches/main/protection \
  --input - << 'EOF'
{
  "required_status_checks": {
    "strict": false,
    "contexts": [
      "CI / Lint",
      "CI / Config validation",
      "CI / Migration check",
      "CI / Compose validation",
      "CI / Image build"
    ]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "required_approving_review_count": 0,
    "dismiss_stale_reviews": false
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
EOF
```

## 2026-06-03 — Wizard: merged Variances step, downstream filtering, master-tare rule

Two coupled problems fixed together:

1. **Downstream steps now filter to the chosen-to-sync set.** An SM filament is *included*
   iff its `wizard_match_decisions` action is `link` or `create`. `skip` and no-decision are
   excluded everywhere: `wizard_weights`, `wizard_variants`, and the new `wizard_variances`
   endpoint. Helper `_included_sm_ids(db)` is the single definition; all three endpoints call
   it. Before this change, the Weights and Variants steps re-fetched and showed the entire
   Spoolman library, forcing users to deal with filaments they had already decided to skip.

2. **Weights + Variants merged into one "Variances" step.** Wizard order is now 6 steps:
   Connectivity → Direction → Matches → **Variances** → Preview → Execute.
   `Step4Weights.tsx` and `Step5Variants.tsx` are deleted; `StepVariances.tsx` replaces them.
   The FDB import direction reuses the old `GET /wizard/variants` and `GET /wizard/weights`
   endpoints directly from within `FDBVariancesStep`; no backend changes for that direction.

3. **Tare is per filament/group, not per spool.** Filament DB stores one `spoolWeight` per
   filament (not per spool). The new `GET /wizard/variances` endpoint returns one tare per
   SM filament (from the filament-level `spool_weight`; default 200 g). The UI shows one
   editable tare input per variant group (the master's) and one per standalone filament. On
   save, the frontend expands these to per-spool `WizardTareOverride[]` entries covering every
   spool of every filament in each group. The execute contract (`WizardExecuteRequest.
   tare_overrides`) is unchanged — tare overrides still ride in the request body.

4. **Master-tare-wins with a visible warning.** All variants in a group share the master's
   tare. A banner on the UI makes this explicit: "All variants in this group will use the
   master's empty-reel tare: N g." This is the only correct model given FDB's single-tare
   per-filament constraint.

5. **Editable variant membership; clusters are hints only.** The user can un-check a member
   to remove it from a group (it becomes standalone with its own tare), or click "+ Add
   member" to pull any other included-but-ungrouped SM filament into the group. The saved
   `SMVariantDecision[]` (in `wizard_sm_variant_decisions`) is authoritative; the API's
   suggested groupings are hints only. Groups reduced to master-only are treated as flat
   (no `SMVariantDecision` entry emitted).

6. **Conflicts recompute live.** `VariancesFilament` carries comparable props
   (material/density/spool_weight/temps). When the user changes the master radio button,
   the frontend recomputes conflicts via `computeConflicts()` — a pure function that
   mirrors `sm_prop_conflicts` from `backend/app/core/matcher.py` — without a round-trip.

7. **Step3Matches row separator fix.** Group-body `divide-gray-50` changed to
   `divide-gray-100` so member row dividers are visible on white backgrounds.

## 2026-06-01 — De-adopted the vexp-context-engine standard (sunset homelab-wide)

vexp is being removed across the homelab; the `vexp-context-engine` standard is deprecated and
rewritten as a removal guide at **v3.0.0**. filament-bridge was its first adopter (fully wired at
v2.1.0); all wiring is stripped here:

- Deleted the `.claude/hooks/vexp-guard.sh` PreToolUse guard hook.
- Removed the `mcp__vexp__*` entries from `permissions.allow` and the `hooks` block from
  `.claude/settings.json`. **The `sandbox` block (repo-sandbox-permissions, repo-wide) and the
  `Read/Edit/Write(**)` allows live in the same file and were preserved intact** — JSON re-validated.
- Removed the "Context search (operational rules)" section from `CLAUDE.md`.
- Dropped the vexp `.gitignore` block; untracked `.vexpignore`, `.vexp/.gitignore`,
  `.vexp/.gitattributes`; deleted the `.vexp/` runtime dir and the gitignored auto-generated
  `.claude/CLAUDE.md`.
- Flipped the `standards.md` vexp row to de-adopted/sunset (v3.0.0 guide) and dropped the vexp
  reference from the `repo-sandbox-permissions` row note.

**Not done from this repo:** host daemon teardown is the Ansible `devworkstation` role's opt-in
`--tags vexp_teardown`. A still-running daemon transiently recreated the (now-untracked) `.vexp/`
runtime dir during this change; it clears when the daemon is stopped by the teardown. No
`CHANGELOG.md` exists yet (pending first release), so this record stands in for the changelog note.

## 2026-06-01 — Match-review v2: one unified table, Group-By Status default

Replaced the four fixed status tables (v1) with a single unified table that has a toolbar for Group By, Sort By + direction, global search, Status filter, and per-column filter inputs (Name, Material). Collapsible groups with tri-state checkboxes and right-aligned aggregates.

1. **Group-By Status is the default**, reproducing the v1 four-section feel (Matched / Ambiguous / Unmatched-SM / Unmatched-FDB) while allowing the user to pivot to Material or Brand grouping. Status also appears as a column and filter.
2. **No backend changes.** All fields needed by the new columns (name, vendor, material, color, confidence, vendorDedup, candidates) were already present on `FilamentRef` / `MatchPairRow` / `AmbiguousRow`. Spool-count aggregates would require fetching spools in `wizard_matches`; omitted as optional per the prompt.
3. **All v1 decision logic preserved unchanged**: tri-state checkboxes, Rescan + decision pruning, `saved_decisions` rehydration, ambiguous candidate picker, `bulkSet` per-status action mapping. `unmatched_fdb` rows remain informational (no checkboxes) regardless of grouping.
4. **Status breakdown pills** appear in group headers when Group-By is Material or Brand, showing counts per status within that group. Amber ⚠ badge flags groups with unresolved ambiguous rows.

## 2026-05-31 — FDB location semantics: locationId (ObjectId reference), pre-creation required

Verified against the live FDB instance while implementing spool location seeding (SM→FDB wizard
execute path).

1. **FDB spools use `locationId`, not a bare `location` string.** `POST /api/filaments/:id/spools`
   with `"location": "name"` silently ignores the key. The correct field is `"locationId"` holding
   a 24-char MongoDB ObjectId referencing the `locations` collection. The bridge schema
   `FDBSpoolDetail.location` was wrong and has been corrected to `locationId`.

2. **Locations must be pre-created via `POST /api/locations`.** FDB does not auto-create a location
   from a name. The wizard seed fetches `GET /api/locations` once per run to build a `name→id`
   cache, then creates missing locations on-demand per spool. A `create_location` failure is
   per-record (that spool fails; the run continues) — consistent with the existing NFR-4
   per-record isolation pattern.

3. **Scope of this change.** Only the SM→FDB initial-seed path (wizard execute). Ongoing-sync
   location updates (engine diff) and the FDB→SM direction are out of scope — follow-up work.

## 2026-05-31 — Match-review redesign: grouped tables, checkboxes, rescan

FR-3/FR-4 match-review step rebuilt from a flat list into four independent grouped/sortable tables.

1. **Status is the top-level grouping — four tables stay separate.** Match status (Matched /
   Ambiguous / Unmatched-SM / Unmatched-FDB) dictates what action is even possible per row,
   so it's the outer split. Subgrouping (Material or Brand/vendor) happens *inside* each table
   via a single shared dimension control.

2. **Checkbox → action mapping (per table).**
   - Matched: checked = `link` (to the auto-matched FDB filament), unchecked = `skip`.
   - Unmatched-SM: checked = `create`, unchecked = `skip`. Both default to the "include" action.
   - Ambiguous: row checkbox only active once a candidate is chosen via the Link picker;
     toggles between the chosen `link` (preserving `filamentdb_id`) and `skip`. The `filamentdb_id`
     is preserved in the decision even when `action="skip"` so re-checking restores the link
     without re-picking.
   - Unmatched-FDB: informational only — groupable/sortable, no checkboxes.
   - Subgroup-header checkbox is tri-state (checked/unchecked/indeterminate); table-level checkbox
     covers all rows in the section.

3. **Rescan keeps choices.** `GET /wizard/matches` now accepts a `db` dependency and returns
   `saved_decisions: list[MatchDecision]` (echoing `wizard_match_decisions` from BridgeConfig).
   On first load the UI hydrates `decisions` state from `saved_decisions`. On rescan
   (`reload()`), existing choices are kept and pruned to the SM ids still present in the new
   response — keyed by `spoolman_filament_id`.

4. **`material` added to `FilamentRef`.** `_sm_ref` sets `material=sm.material` (Spoolman
   `SpoolmanFilament.material`); `_fdb_ref` sets `material=fdb.type` (FDB `FDBFilament.type`).
   Used for the Material subgroup dimension in the UI.

## 2026-05-31 — Wizard preview (FR-4 foundation): reconcile-flag keys + read-only UI step

`GET /api/wizard/preview` reuses the same `_plan_spoolman_to_fdb` planner as
`wizard_execute` (so preview ≡ execute), then derives four reconcile-flag lists from the
plan via pure helpers in `backend/app/api/wizard.py`. The non-obvious grouping keys:

1. **`name_collision`** (`_compute_name_collisions`): key is `normalize_name(payload.name)`
   over the *create* plan items. A group flags `vs_existing` when the normalized name is
   also a key in the existing-FDB map, and `intra_batch` when ≥2 incoming creates share the
   key. One entry per distinct normalized name (not per filament) — so the count is groups,
   while the backlog's "43" counted the colliding *filaments*.
2. **`empty_active`** (`_compute_empty_active`): straight over `sm_spools` —
   `not archived AND (remaining_weight or 0) == 0`. Independent of the plan.
3. **`default_tare`** (`_compute_default_tare`): create spool items where
   `tare_source == "default"` (planner substituted the 200 g default because no
   `spool_weight` was set); reports the planned gross and the default used.
4. **`variant_group`** (`_compute_variant_groups`): key is
   `(normalize_vendor(vendor), _strip_color(name, color_hex), normalize_name(material))`
   over create items, groups of ≥2. Fills FR-6's gap (which only groups *matched* records
   and returns nothing on an empty FDB) for fresh imports. No `parentId` is written — the
   proposed groups are surfaced for the future decision UI only.

**UI:** new read-only `frontend/src/pages/Wizard/StepNPreview.tsx`, wired into the stepper
*before* Execute. Shows the plan summary + flag counts and four collapsible flag sections,
with a non-blocking notice that flagged items need decisions in a later release. No mutating
controls.

**E2E (clean FDB, reseeded `spoolman-livedata.db`, 175 fil / 223 spools):** preview returned
`empty_active=63`, `default_tare=79` (exact backlog match), `name_collision=17` groups /
60 colliding filaments, `variant_group=1`; FDB stayed empty and Spoolman unchanged (no
cross-ref extras written) — confirming the read-only guarantee.

## 2026-05-30 — Dashboard dry-run: SyncPreviewEntry shape and skip coverage

Decisions made while implementing FR-14 per-category detail (created/updated/conflicts/skipped).

1. **Typed `SyncPreviewEntry` Pydantic model** (option b). The WIP wizard-preview changes in
   `schemas/api.py` are purely additive (new model classes at the bottom); `CycleResultResponse`
   was untouched, so adding `SyncPreviewEntry` + changing the one-line `preview` type was safe
   and additive. Frontend gets full TypeScript inference with no extra effort.

2. **Preview entry shape** — all 11 fields present on every entry, with `None` for N/A.
   Consistent shape avoids runtime `?.` chains in the frontend and makes the Pydantic model
   validator simple. `old`/`new` on weight conflicts hold SM `remaining_weight` and FDB
   `totalWeight` respectively (labeled in `reason`).

3. **`sm_skipped_fields` set in `_apply_field_changes`** — introduced to prevent the SM→FDB
   dry-run second-pass from emitting duplicate update entries for inherited-skipped fields.
   Local to the function, dry-run only. The live-sync path is unchanged.

4. **Skip entries for archived and first-baseline paths** were previously silent (incremented
   `result.skipped` but produced no preview entry). Now each emits a `skip` entry with a
   `reason`, so the "Skipped (n)" section in the UI is actually populated.

5. **Label degradation rule** — `_preview_label()` builds "VENDOR NAME COLOR (SM #id) / FDB name"
   when all data is present; degrades gracefully to just FDB name, just SM id, or "unknown" if
   parts are missing (e.g. archived spool where sm_spool object is None).

## 2026-05-30 — Multicolor filament mapping (Spoolman ↔ Filament DB)

Spoolman models multicolor (`multi_color_hexes` CSV + `multi_color_direction` =
`coaxial`/`longitudinal`; 29/175 of the live set). Filament DB has **no multicolor
support** — one `color` hex + a `colorName` string. Note: FDB's UI "Notes" field is
actually `settings.filament_notes` inside the **off-limits slicer-passthrough bag**, so we
never write there. Decisions:

1. **Spoolman is authoritative for color; the bridge's own DB is canonical.** FDB can't hold
   multicolor and has no structured extension field, so nothing is stored in FDB beyond a
   display projection. No data loss — Spoolman + the bridge snapshot retain the full set.
2. **FDB gets primary `color_hex` → `color`, plus a human projection in `colorName`** (a
   real top-level field, never `notes`/`settings`). Format is a config choice
   (`multicolor_colorname_format`): `name` (default — fuzzy nearest-named-color over a
   standard palette, e.g. `"Yellow/Green (coextruded)"`) or `hex`
   (`"cdde1b/68cc16 (coextruded)"`). Type vocabulary is friendly: `coaxial`→**coextruded**,
   `longitudinal`→**gradient**.
3. **`colorName` is a bridge-managed derived field** — recomputed from Spoolman data + the
   current format on each apply for multicolor filaments, so changing the format setting and
   re-running sync rewrites it (the differ won't see a Spoolman-side change). The fuzzy name
   match is approximate by design; switching to `hex` is the escape hatch.
4. **Protect multicolor on write-back.** New setting `protect_multicolor_color_in_spoolman`
   (default **true**): ongoing FDB→Spoolman sync never writes color fields for filaments
   Spoolman marks multicolor, regardless of the material-properties source-of-truth, so
   `multi_color_hexes`/`direction`/`color_hex` can't be flattened. Disabling it carries a UI
   loss-warning.
5. **Forward path:** an upstream feature request was filed for native FDB multicolor. If it
   lands, replace the `colorName` projection with a real field mapping and push correctly —
   no data-model rework, since Spoolman + the bridge already hold the truth.

## 2026-05-31 — Structured multicolor sync supersedes the colorName projection

Filament DB **v1.33.0** (closing [hyiger/filament-db#477](https://github.com/hyiger/filament-db/issues/477))
shipped native structured multicolor, so the "forward path" above has landed. The interim
`colorName`-text projection (decisions 2–4 of the 2026-05-30 entry) is **removed entirely**
— pre-first-release, so no migration. Replacement decisions:

1. **Structured field mapping, both directions.** FDB `color` (nullable) + `secondaryColors[]`
   + arrangement in `optTags` (tag **29 = coextruded**, **28 = gradient**, coextruded wins)
   ↔ Spoolman `color_hex` + `multi_color_hexes` + `multi_color_direction`. Helpers live in
   `core/color.py` (`sm_multicolor_to_fdb`, `fdb_multicolor_to_sm`). coaxial → FDB `color`=null
   & all hexes in `secondaryColors`; longitudinal → `color`=primary, rest secondary. optTag
   writes preserve unrelated tags.
2. **Bidirectional, mirroring the field-diff model.** Multicolor is a filament-level property,
   so `engine._sync_multicolor` runs over filament mappings with a system-agnostic
   `multicolor_signature` stored as filament-level snapshots. One-sided change → directional
   write; both sides changed & disagree → queued conflict (`field_name="multicolor"`), never
   auto-resolved. SoT is not consulted for one-sided changes (consistent with field sync).
   The generic `color` field-map sync is skipped for multicolor filaments (the structured path
   owns it), which replaces the old `protect_multicolor` setting.
3. **Version-gated.** FDB has no version endpoint; we read `GET /api/openapi` → `info.version`
   (`FilamentDBClient.get_version`, cached, refreshed per health probe). `core/version.py`
   gates on `>= 1.33.0` (`MULTICOLOR_MIN_FDB`). On older FDB, multicolor sync is skipped and
   `/api/health` (+ sync status) surface an "upgrade to 1.33.0" warning; single-color `color`
   sync is unaffected.
4. **Removed config** — `multicolor_colorname_format` and `protect_multicolor_color_in_spoolman`
   (defaults, schemas, API, and Settings UI controls) are gone.

## 2026-05-30 — Phase 5 sync fixes (PATCH, weight precision, material default, wizard gating)

Four concrete bugs exposed by the first live end-to-end run (223 Spoolman spools):

1. **`PATCH /api/v1/spool/{id}`, not `PUT`.** Spoolman v0.23.1 returns 405 on `PUT` for
   spool updates; `PATCH` returns 200. This affected both the wizard cross-ref write-back
   and the FR-10 ongoing weight sync (both go through `update_spool`). `CLAUDE.md`
   endpoint list corrected accordingly.

2. **Configurable weight precision (default 2 decimal places).** Without rounding,
   Spoolman's full-precision floats flowed straight through (e.g. `739.4936014320408`).
   `precision` is now a keyword arg on both `spoolman_to_fdb_gross` / `fdb_to_spoolman_net`
   (default 2), threaded from the `weight_precision_decimals` config key (range 0–4).
   Safe from sync churn: the maximum rounding delta at precision 2 is 0.005 g, far below
   the `sync_weight_threshold_grams` default of 2 g.

3. **Missing `material` defaults to `"Unknown"`.** Spoolman allows `material: null`;
   Filament DB requires the `type` field and returns 400 without it. When material is
   absent, the bridge substitutes `"Unknown"`, logs a warning naming the Spoolman filament
   id, and continues. Silent invention was rejected — the warning makes the substitution
   auditable.

4. **`wizard_completed` only flips on zero failures.** Previously the flag was set
   unconditionally after any non-fatal run, so a run with 211 failures still reported
   completion. Now `wizard_completed` is only set `true` when `failed == 0`. Users can
   re-run after fixing issues; idempotency already skips already-linked records so reruns
   are safe.

Architecture / approach decisions for filament-bridge, newest at top. One entry per
non-obvious call: a change of approach, a rejected alternative, or a workaround. Keep
entries short — the *why*, not a tutorial. Part of the
[handoff-prompt-workflow](https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/handoff-prompt-workflow/README.md)
standard (see `standards.md`).

## 2026-05-30 — Make docker-compose deployable + SPA route fallback

Bringing the stack up locally surfaced four problems; all fixed.

1. **Upstream images live on GHCR, not Docker Hub.** `docker-compose.yml` referenced
   `hyiger/filament-db` and `donkie/spoolman` (both nonexistent on Docker Hub →
   `pull access denied`). Correct refs: `ghcr.io/hyiger/filament-db:latest`,
   `ghcr.io/donkie/spoolman:latest`.
2. **Spoolman listens on 8000 internally.** The compose mapped `7912:7912` but Spoolman
   binds 8000 by default, so nothing answered on 7912. Set `SPOOLMAN_PORT: "7912"` so the
   host mapping *and* the in-network `http://spoolman:7912` (used by the bridge service)
   both resolve. The whole project assumes Spoolman on 7912.
3. **Filament DB needs MongoDB.** It's a Next.js app that 500s on every API call without
   `MONGODB_URI`. Added a `mongo:7` service + `MONGODB_URI: mongodb://mongo:27017/filamentdb`,
   and dropped the meaningless `filamentdb-data:/data` volume (its state lives in Mongo).
4. **SPA route fallback.** Phase 4 served the build with `StaticFiles(html=True)`, which
   only serves `index.html` at the root — every client route (`/conflicts`, `/wizard`, …)
   404'd on hard refresh / direct load / shared link, since the app uses `BrowserRouter`.
   Replaced with: mount `/assets` for hashed bundles, plus a catch-all `GET /{full_path:path}`
   that returns the matching file if it exists else `index.html`. Guarded to still 404
   unknown `/api/*` paths (as JSON) rather than swallowing them into the SPA shell. Whole
   block stays behind `if _static_dir.is_dir()`, so pytest / `uvicorn --reload` are
   unaffected (no `/static` dir in dev).

**`docker-compose.dev.yml`** (tracked): same services with data bind-mounted under the
gitignored `./private_data/` instead of named volumes — lets you seed/inspect data from
the host. Safe to track because no real data is ever committed.

**Deep-link base caveat (known, not fixed):** the UI builds deep links from the URLs the
bridge reports (`systems[*].url`), which in compose are docker-internal names
(`http://filament-db:3000`). Browsers can't resolve those, so deep-link icons don't click
through in a localhost-only compose run. In a real LAN deployment the upstream URLs resolve
from both the bridge and the browser, so they work; for local poking, run the bridge in
host dev mode (uvicorn + `backend/.env` → `localhost:3000`/`7912`).

## 2026-05-29 — Phase 4 Web UI: SPA scaffold, static mount, deep-link bases, hooks

Key decisions taken while building the React SPA.

1. **`frontend/dist` → `static/` in the Docker image; mount guarded by `is_dir()`.**
   The Vite build writes to `frontend/dist`; the Dockerfile copies it to `/app/static/`
   in the runtime image. `main.py` resolves `Path(__file__).parent.parent.parent / "static"`
   and only calls `app.mount` when the directory exists — so `pytest` and local
   `uvicorn --reload` (no frontend build) pass without error. `html=True` on
   `StaticFiles` provides the SPA fallback for client-side routes.

2. **Deep-link bases come from `/api/health` `systems[*].url`, not env vars.**
   The backend already returns the configured `FILAMENTDB_URL` / `SPOOLMAN_URL` in the
   health response. `DeepLinkContext` fetches `/health` once on mount and provides the
   bases to all `DeepLinks` components. This means the UI never needs its own copy of the
   env vars and stays correct even if the backend is pointed at non-default URLs.

3. **Plain `fetch` + hooks, no react-query.**
   Two hooks — `useApi` (one-shot, re-runs on dep change) and `usePoll` (interval
   auto-refresh for the dashboard). Avoids a heavy dependency for a simple internal tool;
   adding react-query later is straightforward if the data requirements grow.

4. **Tare overrides are held in WizardShell state, not in a URL or context file.**
   The FR-5 weight-review step collects per-spool tare overrides and passes them into the
   `WizardShell` component's `tareOverrides` state. Step 6 submits them in the execute
   body. This matches the backend contract (the server does not persist tare overrides
   between calls) and keeps the wizard self-contained.

5. **Wizard step navigation is driven by the stepper index + React Router.**
   `WizardShell` owns the current step index and calls `navigate('/wizard/<path>')` on
   `next()`/`prev()`. Steps are plain route components with no shared session storage —
   each re-fetches its data from the API when mounted. This is correct for a wizard that
   is run once; it avoids stale cached state if the user navigates back and re-fetches.

## 2026-05-29 — Phase 3b wizard execute (FR-7): create order, idempotency, snapshot seed, fatal vs per-record

Decisions taken while building `POST /api/wizard/execute` — the initial bulk
write to both upstreams.

1. **Create order = filaments → variants → spools, in three passes.** Phase A
   resolves every source filament to a target filament id (link to an existing
   one, or `create_filament`). Phase B applies the FR-6 variant groupings
   (`update_filament` with `parentId`) as a *second pass* rather than setting
   `parentId` at create time: the variant decisions are keyed by FDB filament id,
   and a just-created filament has no id at decision time — so a variant decision
   can only reference a pre-existing (linked) filament. By the time Phase B runs,
   every referenced filament exists, so "parents before children" is satisfied
   for free. Phase C creates the `FilamentMapping`/`SpoolMapping` rows and seeds
   the spools. The parent id is resolved before spool seeding so the
   `filamentdb_parent_id` cross-ref and the `FilamentMapping.filamentdb_parent_id`
   column are written in one shot.

   **Superseded for the `spoolman` direction (2026-05-31, see below):** the
   FDB-keyed two-pass rationale only ever held because variant decisions were
   keyed by FDB filament id. That breaks in a greenfield FDB (no ids to key on),
   so the `_execute_spoolman_to_fdb` path now keys decisions by *Spoolman*
   filament id and injects `parentId` at create time (Pass 2), not via a
   post-hoc `update_filament`. The two-pass `update_filament(parentId)` approach
   survives only for the `filamentdb` direction (`_execute_fdb_to_spoolman`).

2. **Idempotency is keyed on the bridge's own mapping tables *and* the upstream
   cross-ref field.** Before creating, we skip if a `FilamentMapping`/`SpoolMapping`
   row exists (the normal re-run case) *or* if the Spoolman spool already carries a
   `filamentdb_spool_id` extra value (a prior run wrote upstream but its DB
   transaction rolled back — the commit is at the very end). This makes a re-run
   after a partial failure a no-op rather than a duplicator. Nothing upstream is
   ever deleted to "clean up" a partial run (CLAUDE.md hard rule); the re-run
   reconciles.

3. **Fatal vs per-record failure governs the `wizard_completed` flip.** A failure
   to *read* both systems is fatal — we write an error `SyncLog`, do **not** flip
   `wizard_completed`, and return `502 upstream_fetch_failed` (nothing was
   written). A single record's API error is isolated (NFR-4): it becomes a
   `failed` report entry + an `error` `SyncLog` and the run continues; the flag
   still flips, since the user can re-run to reconcile. There are no conflicts to
   queue here — the wizard is the user explicitly choosing the initial state
   (conflicts are an ongoing-sync concept, FR-13).

4. **Seed weights are SET on create, never logged as usage.** New target spools
   get their converted gross/net weight set directly on `create_spool`. Usage
   entries (`log_usage`) are reserved for ongoing decrements (FR-9); emitting them
   for the seed import would invent a fake consumption history.

5. **Snapshots are seeded post-write (best-effort).** Each freshly-linked pair
   gets both snapshot rows written using the engine's own
   `_sm_snapshot_dict`/`_fdb_snapshot_dict`/`_upsert_snapshot` helpers, so cycle 1
   of auto-sync diffs against a correct baseline instead of treating every record
   as first-seen. A snapshot-write error is swallowed (the engine baselines a
   first-seen pair anyway) so it can never fail the import.

6. **Tare overrides ride in the execute request body, not BridgeConfig.** Unlike
   match/variant decisions, the FR-5 per-spool tare overrides are *not* persisted
   in Phase 3 (there is no `POST /wizard/weights`). The UI collects them on the
   review screen and submits them with the execute call
   (`WizardExecuteRequest.tare_overrides`, keyed by whichever spool id the active
   direction uses). Absent an override, tare falls back to the spool's, then the
   filament's, `spool_weight`, then the 200 g default.

7. **Direction-model asymmetry (documented limitation).** The persisted
   `MatchDecision` is Spoolman-keyed (`link`/`create`/`skip` per Spoolman
   filament). It cleanly drives the `import_direction="spoolman"` path. For
   `import_direction="filamentdb"` the same link decisions still pair both ids,
   but FDB filaments with no link decision are created in Spoolman with no
   per-record skip granularity (the FR-4 "skip this unmatched record" choice for
   an FDB-only filament isn't representable in the Spoolman-keyed model). Accepted
   for now; revisit if the FDB-import direction needs per-record skips.

## 2026-05-29 — Phase 3 API: error envelope, conflict-resolve semantics, wizard state, backup format

Five decisions taken while building the bridge API layer (Phase 3):

1. **Error envelope.** Handled errors return `{"detail": {"code": <machine
   code>, "message": <human message>}}` via a single `api/errors.py:api_error()`
   helper. `code` is a stable string the UI branches on (e.g. `wizard_incomplete`,
   `manual_value_required`, `mapping_not_found`); `message` is for display.
   FastAPI's own validation (Pydantic `Literal`/`gt`) still returns its native
   422 shape — we don't wrap those.

2. **Conflict resolution = record now, apply on a later cycle.** `POST
   /conflicts/{id}/resolve` writes `resolution`/`resolved_value`/`resolved_at`
   on the row and drops it from the open queue, but performs **no upstream
   write** (honours the no-auto-resolve hard rule and keeps sync logic in
   `core/`). `resolved_value` is the chosen side's value (spoolman/filamentdb)
   or the supplied `manual` value. ⚠️ Engine gap: `core/engine` does not yet
   read resolved conflicts to push the chosen value upstream (and currently
   re-queues an unresolved weight conflict every cycle). Wiring the engine to
   consume resolutions is a Phase 2 follow-up — tracked, not done here.

3. **Wizard decision state lives in `BridgeConfig`, not a new table.** The
   wizard's direction (`import_direction`), match decisions
   (`wizard_match_decisions`), and variant groupings (`wizard_variant_decisions`)
   are persisted as JSON values in the existing key→JSON `BridgeConfig` store.
   Chosen over a dedicated `wizard_state` table to avoid an Alembic migration for
   transient setup data; Phase 3b reads these keys to execute (FR-7) and flips
   `wizard_completed`. The source-of-truth choices reuse the existing
   `*_source_of_truth` keys directly.

4. **Backup format.** `GET /backup/export` emits a versioned envelope
   (`schema_version = 1`) containing **bridge state only** — config, filament
   mappings, spool mappings, and *open* conflicts — never a copy of upstream
   data (CLAUDE.md). `POST /backup/import` is idempotent: mappings upsert by
   their unique business key (`spoolman_filament_id` / `spoolman_spool_id`)
   preserving ids so spool→filament FKs survive a clean restore; conflicts insert
   only when no equivalent open conflict exists (natural key: entity_type +
   field_name + the two ids). A mismatched `schema_version` is a 400.

5. **Mapping status enum (the `/mappings` + dashboard contract).** Precedence:
   `conflict` (an open Conflict references the spool) > `unlinked` (spool mapping
   has no parent filament mapping) > `pending` (a side has no snapshot yet) >
   `in_sync` (both snapshots present, no open conflict). Per-side weights and the
   name/vendor/color display fields come from the last **snapshots** (the
   Spoolman-side snapshot carries the filament detail; the FDB spool snapshot is
   trimmed), so the endpoint needs no live upstream fetch.

Test-harness note: the in-memory SQLite fixtures use `StaticPool` (one shared
connection) because FastAPI's `TestClient` runs sync handlers in a worker thread,
which would otherwise see its own empty `:memory:` database. `tests/conftest.py`
also `setdefault`s the required env vars so `cd backend && pytest` is
self-contained.

## 2026-05-29 — Async-job / sync-DB bridging approach (Option A — inline)

`run_sync_cycle` is a single `async def` that `await`s client I/O and calls
synchronous SQLAlchemy code inline — no thread, no second sync httpx client.
SQLite latency is microseconds; the only real bottleneck is the HTTP calls to
Spoolman and Filament DB. The brief loop stall is harmless for a single-container
homelab service. Rejected Option B (offload DB to `asyncio.to_thread` with a sync
httpx client) because it would split stack traces across the event loop and a worker
thread, surface errors a step removed from their cause, and require a parallel sync
`httpx.Client` purely to make the thread viable. Only revisit if a much larger
inventory (≫ 1000 spools) makes a cycle long enough to visibly stall the event loop.

## 2026-05-29 — Spoolman extra-field conflict-key definition (Phase 2)

The conflict `field_name` for a weight disagreement is `"weight"` (not
`"remaining_weight"` or `"totalWeight"`) so the resolution UI can display a
single unified weight conflict rather than two system-specific column names.
Field-mapping conflicts use the FDB dotted path (e.g. `"temperatures.nozzle"`)
as the key, which is the canonical name in the bridge's field-map config.

## 2026-05-28 — Canonical build-phase numbering (closes the skipped Phase 2)

The handoff prompts grew a numbering gap: Phase 0 (backend foundation) and Phase 1
(SQLite persistence) shipped, but the prompts then forward-referenced "Phase 3 (sync
engine)" and "Phase 4 (wizard API)" — there was never a Phase 2. The Phase 0 prompt only
mentioned Phase 2 in passing ("clients ... Phase 2 leans on this"). To keep the sequence
contiguous, the remaining work is renumbered to close the gap. This table is the single
source of truth for build-phase numbers; product-facing phases in `README.md` (guided
sync → dry run → auto-sync) and the migration-guide phases are separate schemes and are
unaffected.

| Build phase | Scope | Status |
|---|---|---|
| Phase 0 | Backend foundation — FastAPI skeleton, health (FR-1), upstream clients | ✅ done |
| Phase 1 | SQLite persistence — models, Alembic, config seed | ✅ done |
| Phase 2 | Continuous sync engine — snapshot/diff/match/apply/conflict/log (FR-8…FR-14) | next |
| Phase 3 | Bridge API layer — wizard read/decision endpoints (FR-1…FR-6) + sync/conflict/mappings/config/backup/log routers | planned |
| Phase 3b | Wizard execute (FR-7) — the initial-sync write to both upstreams; carved out for risk/isolation | planned |
| Phase 4 | Frontend SPA + `/static` mount (FR-15…FR-19) | planned |

The forward-references in the two completed prompts under `prompts/done/` were corrected
to match (sync engine 3→2, wizard 4→3, SPA 5→4).

## 2026-05-28 — Synchronous SQLAlchemy (not async) for the persistence layer

Used `create_engine` / `Session` rather than `create_async_engine` / `AsyncSession`.
SQLite latency is microseconds — the only real bottleneck is the HTTP calls to Spoolman
and Filament DB. Async SQLAlchemy + Alembic autogenerate also requires a sync
compatibility shim that adds complexity for zero practical gain. FastAPI runs sync
`Depends` handlers in a threadpool automatically, so sync DB sessions in route handlers
are safe without any extra wrapper.

## 2026-05-28 — Deep-link routes (corrects PRD NFR-7 / CLAUDE.md)

Verified against the live crzynet instances. The spec's guessed patterns were wrong:
- Filament DB filament: `{FILAMENTDB_URL}/filaments/{id}` — **plural**, not `/filament/{id}`.
- Spoolman spool: `{SPOOLMAN_URL}/spool/show/{id}` and filament `/filament/show/{id}` —
  **no hash routing** (newer Spoolman dropped `/#/`).
- Filament DB has **no standalone spool page** — spools render under the filament page.
  So bridge spool rows link to the parent filament page, not a per-spool URL.

## 2026-05-28 — Filament DB variant inheritance: read detail, strip computed fields

`GET /api/filaments/:id` resolves parent→variant inheritance server-side: the variant
response merges inherited values and names which ones in `_inherited[]` (plus `_parent`,
and `_variants[]` on the parent). The trimmed list view (`GET /api/filaments`) is for
enumeration only. Two rules for the bridge: (1) writing a material prop onto a variant
whose field is in `_inherited[]` overrides inheritance — check `_inherited[]` and
skip/flag instead of blindly writing; (2) strip computed/Mongoose fields before any PUT
(`_inherited`, `_parent`, `_variants`, `hasVariants`, `inherits`, `settings`, `__v`,
`instanceId`, `createdAt`, `updatedAt`, `_deletedAt`). Note `inherits` (a PrusaSlicer
preset name) is unrelated to the `parentId` variant tree — do not conflate.

## 2026-05-28 — Spoolman extra fields: create on startup, JSON-decode values

`GET /api/v1/field/spool` returns `[]` on the live instance — none of the bridge's
cross-ref fields exist. The bridge creates `filamentdb_id`, `filamentdb_parent_id`,
`filamentdb_spool_id` via `POST /api/v1/field/{entity_type}/{key}` on startup (chosen
over requiring manual UI setup — keeps deployment env-var-only). Spoolman stores text
extra-field values JSON-double-quoted (`"\"https://...\""`), so the bridge must
`json.loads()` them on read and `json.dumps()` on write, never use raw.

## 2026-05-28 — Sync engine defaults for the three design open questions

Defaults chosen now, revisitable later: (OQ#1) sync a weight change only when the delta
≥ a configurable threshold (default ~2g) to avoid rounding churn between net/gross
models. (OQ#6) full-snapshot diff each cycle — `GET /api/v1/spool?limit=1000` returns
all 223 spools fast enough; add incremental fetch only if a larger inventory demands it.
Note: `limit=1000` includes archived (active+archived both returned 223), so filter
`archived == false` client-side for the active set. (OQ#7) accept the aggregate weight
delta when multiple printers decrement one spool between cycles; per-printer attribution
is out of scope — documented, not silently dropped.

## 2026-05-28 — Docker base images: node:22-alpine (build) + python:3.12-slim-bookworm (runtime)

Multi-stage Dockerfile uses `node:22-alpine` for the React build stage (throw-away, never
ships) and `python:3.12-slim-bookworm` for the final runtime stage. Slim was chosen over
distroless/Chainguard because the service is still under active development — no shell
means no `exec`-based debugging, which is painful for a homelab sync tool. Revisit
distroless (`gcr.io/distroless/python3-debian12`) once the app is stable.

## 2026-05-31 — Unified dry-run: shared planner, auto-decisions, orphan bucket

**Shared planner location:** `_plan_spoolman_to_fdb`, `_SyncPlan`, `_FilamentPlanItem`,
`_SpoolPlanItem`, and `_fdb_filament_payload_from_sm` were extracted from
`backend/app/api/wizard.py` into `backend/app/core/planner.py`. Both `wizard_execute`
(FR-7) and `plan_dry_run` (FR-14) import from there — the same planner code means
preview ≡ execute by construction.

**Matcher → decisions mapping for the dry-run:**
`match_filaments(unlinked_sm, unlinked_fdb)` is called in `core/dryrun.py::plan_dry_run`
and its results are converted to `decisions_by_sm` before the planner runs:
- `matched` (1:1 confidence) → `{action: "link", filamentdb_id: <fdb.id>}` → planner
  emits `update` (filament_link) preview entries.
- `unmatched_spoolman` → `{action: "create"}` → planner emits `create` entries.
- `ambiguous` (multiple FDB candidates) → NOT auto-picked; emitted directly as
  `conflict` with `candidates: [<fdb_ids>]`. The planner never sees ambiguous SM
  filaments (they're excluded from `decisions_by_sm`).

**Cross-ref orphan bucket:** SM spools that already carry the `filamentdb_spool_id`
extra field but have no `SpoolMapping` row (the "167" from the live dataset) are now
bucketed as `update` with `reason: "re-link from existing cross-ref"`. The engine's
previous silent `continue` at the xref guard is preserved for live sync — only the
dry-run re-classifies them. Confirmed with user 2026-05-31.

**False-conflict removal:** `run_sync_cycle(dry_run=True)` buckets SM spools with no
`FilamentMapping` as `conflict(new_spool)` — this is correct for steady-state but wrong
for the initial-state dry-run. `plan_dry_run` filters those entries out (criterion:
`action==conflict, entity_type==spool, field==new_spool, fdb_filament_id==None`) before
adding the planner's reclassified entries.

## 2026-05-28 — Canonical version file is `backend/app/__init__.py`

For the `release-prep-and-cut` standard, the bare version lives in
`backend/app/__init__.py` (`__version__ = "X.Y.Z"`). Chosen over `pyproject.toml`
(the backend uses `requirements.txt`, not pyproject) and a root `VERSION` file (the
FastAPI app would have to parse it at runtime, whereas `__version__` is a native
import that also feeds the in-app version display). The file doesn't exist yet — it's
created when the backend lands.

## 2026-05-31 — Spoolman→FDB variant grouping: SM-keyed master-promote

The initial-sync wizard can now collapse a set of flat Spoolman filaments
(e.g. "ELEGOO PLA Red/Blue/…") into one FDB parent + variants *before* the
write, for the `import_direction="spoolman"` greenfield flow.

**Master = parent (a real filament, not a synthesized one).** Each SM filament
still maps 1:1 to an FDB filament; grouping only orders master-before-variants
and stamps `parentId` on the non-masters. The master is a normal filament with
its own color and spools. The user picks the master (radio) and prunes members
(checkbox); a group reduced to master-only dissolves to flat creates.

**SM-keyed persistence — new `wizard_sm_variant_decisions` key.** Decisions are
keyed by Spoolman filament id (`{master_spoolman_filament_id,
variant_spoolman_filament_ids[]}`), not FDB id, because a greenfield FDB has no
ids to key on. The legacy FDB-keyed `wizard_variant_decisions` +
`VariantDecision` + `_execute_fdb_to_spoolman` path is untouched; the two keys
coexist, one per direction. This corrects the earlier Phase-B rationale (above),
which documented the FDB-keyed two-pass `update_filament(parentId)` as
intentional — it was a workaround for FDB-keyed decisions and does not apply to
the spoolman direction, which injects `parentId` at create time.

**Clustering strips a color-word lexicon, not just the hex.** `_strip_color`
only removed a hex code, which under-clustered real names like "ELEGOO PLA Red".
Clustering now keys on `(normalize_vendor, normalize_name(material), base_name)`
where `base_name` strips both the hex and a known color-word lexicon
(red/blue/black/white/grey/green/…). Clusters are **hints only** — the GUI is
authoritative. Suggested master heuristic: most spools, tie-break shortest name.
Singletons (cluster of 1) are excluded.

**Shared properties are flagged, never auto-resolved.** `sm_prop_conflicts`
compares material/density/spool_weight/extruder_temp/bed_temp between master and
each member; mismatches surface as inline warnings in the preview
(`variant_plan`). The bridge never auto-picks a value (CLAUDE.md hard rule). A
group whose master has a `skip` match-decision is rejected at save; a variant
whose master failed to resolve at execute time emits a `failed` report entry
(no orphan `parentId`).

**Un-grouping after a successful run is out of scope.** The wizard builds the
tree before the first write only; reorganizing an already-synced parent/variant
tree is a separate, later concern.

## 2026-06-05 — Variances detail enrichment, per-field reconciliation, execute write-back, pre-flight summary

### Phase 1: Variances enriched display fields

`VariancesFilament` gained three new fields: `material_type` (the FDB `type` field from
the matched filament — only populated for `link` decisions, `None` for `create`), `diameter`
(SM filament diameter), and `color_hex` (SM filament color, for the color swatch). These
are populated in `wizard_variances` by building a `sm_to_fdb_type` map from `wizard_match_decisions`
and using the link's FDB filament's `type`. The `diameter` conflict check was also added to
`sm_prop_conflicts` in `matcher.py` (missing it was a bug) and the diameter field was added
to `_fdb_filament_payload_from_sm` in `planner.py` (another pre-existing omission).

### Phase 2: Per-group reconcile decisions

New schemas `ReconciledField` / `VariancesGroupReconcile` / `SMVariancesDecisionsRequest`
extend the existing `POST /wizard/variants/sm` endpoint to accept an optional `reconcile`
list (backwards-compatible — defaults to empty). Reconcile decisions are persisted under the
new `wizard_variances_reconcile` BridgeConfig key. An absent/empty `reconcile` payload leaves
any previously stored decisions untouched (non-destructive update).

### Phase 3: Execute write-back

`_execute_spoolman_to_fdb` gained:
- **Pass 2.5** (between variant creates and spool seeding): for each SM filament whose group
  has reconcile decisions, `_compute_sm_reconcile_patch` diffs canonical vs current SM values
  and calls `spoolman.update_filament`. Empty patch = no call. Errors are non-fatal (log and
  continue, per NFR-4). This pass runs only when `_reconcile_by_master` is non-empty.
- **FDB create overlay**: for master/ungrouped `create` items, `_overlay_reconcile_on_fdb_payload`
  is applied before `filamentdb.create_filament`. Nested keys (`temperatures.nozzle`) are handled
  via dot-notation splitting. Variants inherit from the FDB parent and are never overlaid separately.

**Canonical field map** (`_RECONCILE_FIELD_MAP`):
| canonical key | FDB payload key | Spoolman field |
|---|---|---|
| `type` | `type` | `material` |
| `density` | `density` | `density` |
| `diameter` | `diameter` | `diameter` |
| `nozzle_temp` | `temperatures.nozzle` | `settings_extruder_temp` |
| `bed_temp` | `temperatures.bed` | `settings_bed_temp` |
| `spool_weight` | `spoolWeight` | `spool_weight` |

Color fields are never written via the reconcile path. FDB `settings{}` is never touched.

### Phase 4: Pre-flight planned-writes summary

`_compute_planned_writes(plan, sm_filaments, reconcile_by_master)` is a pure helper that
produces `list[PlannedWrite]` covering: FDB filament creates (with reconcile overlay), FDB
spool creates, and Spoolman write-back PATCHes. It calls the exact same sub-functions as
execute, so `preview ≡ execute` by construction. `WizardPreviewResponse` gained `planned_writes`.
The frontend `StepNPreview.tsx` shows the section only for SM direction when the list is
non-empty, with All / Filament DB / Spoolman filter chips.

## 2026-06-06 — OpenPrintTag finish-tag model adopted; `filamentdb_material_tags` Spoolman extra field

### FDB finish model: base type + numeric tag IDs in optTags

Filament DB (≥ 1.33.0) models material finishes as numeric OpenPrintTag IDs in the
`optTags` array rather than as part of the material name string. For example, "PLA Silk"
in Spoolman maps to FDB `type="PLA"` + `optTags=[17]` (silk tag ID). This is the same
`optTags` field used by the multicolor path, but finishes use different IDs.

### New config-overridable keyword↔ID seed map

`DEFAULT_MATERIAL_TAG_IDS` in `backend/app/core/material_tags.py` seeds the full mapping:
`silk=17, matte=16, glitter=23, sparkle=23, glow=24, carbon=31, cf=31, glass=34, wood=41,
metal=46, metallic=46, translucent=19, transparent=20, high-speed=71, hs=71, rapid=71,
recycled=60`. Override or extend via the `MATERIAL_TAG_IDS` env var as
`keyword=id,keyword=id,...` pairs; an override replaces the entire seed (no merge).

`MANAGED_FINISH_IDS = frozenset({16,17,19,20,23,24,31,34,41,46,60,71})` defines the IDs
the bridge owns. IDs outside this set (including arrangement tags 28/29) pass through
`apply_finish_tags` untouched.

### New Spoolman filament-level extra field: `filamentdb_material_tags`

`ensure_extra_fields()` now also registers a filament-level extra field
(key `filamentdb_material_tags`, overridable via `SPOOLMAN_FIELD_FILAMENTDB_MATERIAL_TAGS`).
This stores the finish-tag IDs structurally as a JSON list of ints (e.g. `[17]`), allowing
round-trip sync without re-parsing text names each cycle.

Resolution order in `_sm_finish_ids_from_filament`: read the extra field first (structural,
trusted if set); fall back to `finish_ids_from_text(name, material)` for Spoolman filaments
that have not yet had the extra field populated.

### Flap-safety: finish-stripped type comparison in the differ

`differ.py` strips finish keywords from the Spoolman `material` value before comparing it
with the FDB `type` field. This prevents "PLA Silk" (SM) ↔ "PLA" (FDB) from appearing as
a perpetual type mismatch and flip-flopping each cycle. `strip_finish_words("PLA Silk")`
returns `"PLA"`. The generic field-mapping diff is unchanged; only the
`material` → `type` pair gets the stripped comparison.

### Arrangement tags (28/29) never touched by finish-tag code

`apply_finish_tags` and `_fdb_finish_ids` both respect `ARRANGEMENT_TAGS = {28, 29}`:
arrangement tags pass through untouched. Finish-tag code never reads or writes them.
The multicolor path retains exclusive ownership of tags 28/29.

### `_finish_sig` coexists with `_mc_sig` and `_cost` via `_merge_snapshot`

Ongoing sync stores the finish-tag state as `_finish_sig` (sorted comma-joined IDs string)
in the shared filament snapshot row. Like `_mc_sig` and `_cost`, it uses `_merge_snapshot`
(reads existing dict, updates one key, writes back), so all three keys coexist and no pass
clobbers another.

### Version gate: Filament DB ≥ 1.33.0 required (same as multicolor)

`_sync_finish_tags` is gated on `finish_tags_supported` (reuses `multicolor_supported`),
since `optTags` shipped in FDB 1.33.0. On older FDB versions the pass is a no-op.

### Wizard import: Pass 2.6 writes finish-tag extra field back to Spoolman

During SM→FDB import, `_fdb_filament_payload_from_sm` writes the parsed finish IDs as the
sentinel key `_sm_finish_ids` in the payload dict. After FDB filament creation (passes 1 and
2), a new **Pass 2.6** iterates the collected `_finish_ids_by_sm` dict and PATCHes each SM
filament's `extra.filamentdb_material_tags` so the extra field is populated from first import.
