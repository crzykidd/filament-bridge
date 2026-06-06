---
name: 2026-06-06-opentag-spoolman-cleanup-tool
status: completed
created: 2026-06-06
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-06
result: OpenTag cleanup tool shipped — cache, matcher, matches/apply endpoints, frontend review/confirm/apply page, Phase 5 settings-bag merge wired; 470 tests green, tsc + build pass
---

# Task: OpenTag → Spoolman cleanup tool (standalone) + push OpenTag identity into FDB

A new standalone tool that matches the user's Spoolman filaments against the OpenPrintTag
database, shows a per-field review (Spoolman value vs OpenTag value, defaulting to OpenTag,
editable), then a **full confirm page** of every write, and on the user's explicit action
writes the chosen canonical data back to Spoolman (incl. `openprinttag_slug` +
`openprinttag_uuid`). The existing sync then carries the clean data to FDB — including the
OpenTag identity keys pushed into FDB's `settings{}` bag so a bridge-cleaned filament looks
identical to an OpenTag import. Builds on the finish-tag round-trip (commit `2438dba`).

Large, multi-phase, opt-in (separate page) — must not change existing sync behavior except
the scoped settings-bag exception in Phase 5.

## Decisions (from the user)

- **Data source:** fetch from Filament DB's `GET /api/openprinttag` (FDB already downloads
  the `OpenPrintTag/openprinttag-database` tarball, denormalizes, caches 1hr). Bridge caches
  LOCALLY and re-fetches only when its copy is older than `OPENTAG_CACHE_MAX_AGE_HOURS`
  (default 24) or the user forces a refresh — on-demand, not background. Version-gate; clear
  error if the FDB endpoint is missing (direct-tarball fallback NOT built here).
- **Review:** per field, show **Spoolman value AND OpenTag value**, default the selection to
  **OpenTag**, make it an **editable input**, with **"keep mine"** (per field) and **"ignore
  match"** (whole filament).
- **Confirm page:** after review, a full pre-apply summary listing EVERY write that will hit
  Spoolman (filament → field → old → new), like the wizard Execute pre-flight. Apply only
  from there.
- **Identity:** capture and store BOTH `openprinttag_slug` (e.g. `buddy3d-pla-silk-bronze`)
  and `openprinttag_uuid` (e.g. `d22442a5-...`) as Spoolman extra fields, and push them into
  FDB so FDB shows them like an OpenTag import.
- **UI:** standalone page.

## OpenTag record shape (FDB /api/openprinttag, verified)

`OPTMaterial`: `uuid`, `slug`, `brandName`, `name`, `type`, `abbreviation`, `tags` (finish
strings, map → OpenPrintTag IDs via `backend/app/core/material_tags.py`), `color` (hex),
`secondaryColors` (hex[]), `density`, `nozzleTempMin/Max`, `bedTempMin/Max`,
`completenessScore`. (No weight/cost; diameter assumed 1.75.)

## Field mapping OpenTag → Spoolman

| OpenTag | Spoolman target | Notes |
|---|---|---|
| `type` (base) | `material` | base, e.g. "PLA" (finish → tags, per #1) |
| `tags` → IDs | `extra.filamentdb_material_tags` | reuse #1 map + extra field |
| `color` | `color_hex` | |
| `secondaryColors` | `multi_color_hexes` | |
| `density` | `density` | |
| (1.75) | `diameter` | default |
| `nozzleTempMax` | `settings_extruder_temp` | single value, default = max, editable |
| `bedTempMax` | `settings_bed_temp` | single value, default = max, editable |
| `slug` | `extra.openprinttag_slug` | new extra field |
| `uuid` | `extra.openprinttag_uuid` | new extra field |

## Phase 1 — Dataset fetch + local cache + config + extra fields

- FDB client: add `get_openprinttag()` → `GET /api/openprinttag`; parse to OPTMaterial
  dicts; gate/handle 404.
- Local cache file in `DATA_DIR` (`opentag_cache.json`) + `fetched_at`; config
  `OPENTAG_CACHE_MAX_AGE_HOURS` (default 24); loader re-fetches only when missing/stale or
  forced.
- New Spoolman filament extra fields `openprinttag_slug` + `openprinttag_uuid` (configs
  `SPOOLMAN_FIELD_OPENPRINTTAG_SLUG`/`_UUID`), registered in `ensure_extra_fields`. Update
  `docs/spoolman-writes.md`.

## Phase 2 — Matcher + matches endpoint

- `backend/app/core/opentag_match.py`: score OPTMaterial candidates per SM filament by
  vendor + type + color + finish (reuse `matcher.py` normalizers + #1 tag map); best match +
  confidence + alternates. Pure + unit-tested.
- `GET /api/opentag/matches`: load cached dataset (refetch if stale); per filament return SM
  current values, matched OPTMaterial values mapped to Spoolman fields, per-field comparison,
  confidence, alternates, + dataset metadata (fetched_at, count, stale).
- `POST /api/opentag/refresh`: force fresh fetch; return metadata.

## Phase 3 — Apply endpoint

- `POST /api/opentag/apply`: request = per-filament final chosen values per field (frontend
  sends resolved values: OpenTag default / keep-mine / edited) + `openprinttag_slug` +
  `openprinttag_uuid`. PATCH each Spoolman filament with ONLY provided fields (native +
  the three extras: `filamentdb_material_tags`, `openprinttag_slug`, `openprinttag_uuid`).
  Skip ignored filaments / keep-mine fields. Log each; non-fatal per-filament errors. This is
  the explicit user action authorizing Spoolman writes.

## Phase 5 — Push OpenTag identity into FDB's settings bag (scoped rule exception)

Goal: a bridge-cleaned filament shows `openprinttag_slug`/`openprinttag_uuid` in FDB exactly
like an OpenTag import — which FDB stores in the filament `settings{}` bag.

- **Hard-rule exception:** CLAUDE.md says "don't touch the `settings{}` bag." Relax it ONLY
  to **merge the two keys `openprinttag_slug` + `openprinttag_uuid`** into FDB's settings bag
  — never modify/remove any other settings key. Implement as a read-modify-merge (fetch
  current settings, set just those two keys, write back) so all slicer passthrough keys are
  preserved. Note `update_filament`'s `_STRIP_BEFORE_PUT` currently strips `settings` — you
  must allow these two keys through (e.g. a dedicated settings-merge path, NOT a blanket
  settings write).
- Wire it where the bridge creates/updates FDB filaments from Spoolman: the wizard planner
  create payload AND the ongoing material-properties sync (when the SM extra fields
  `openprinttag_slug`/`uuid` are present, ensure FDB's settings bag carries them). Keep it
  idempotent (don't rewrite if already equal — no flapping).
- Update `CLAUDE.md` ("don't touch settings{}") and `docs/decisions.md` to record this scoped
  exception. Update `docs/spoolman-writes.md` for the two new SM extra fields.

## Phase 4 — Standalone frontend page (review → confirm → apply)

- New page `frontend/src/pages/OpenTagCleanup.tsx` + nav entry.
- Dataset status (fetched_at/age/count) + **Refresh**; fetch `/api/opentag/matches`.
- Review: per matched filament, per-field row: field | Spoolman value | OpenTag value |
  editable input (default OpenTag) | "keep mine" toggle. Confidence badge, candidate picker
  for alternates, "Ignore match" per filament. Color swatches; finish tags as labels.
- **Confirm step:** an explicit second screen/section listing EVERY pending write to Spoolman
  (filament → field → old → new, incl. slug/uuid), with counts; only here is **Apply** shown.
  POST to `/api/opentag/apply`, then reload.
- Types/client updates in `frontend/src/api/types.ts` + `client.ts`.

## Conventions

- `code-checkin-and-pr`: `dev`, `feat:` (cohesive; multiple commits OK if cleaner), no
  `Co-authored-by:`, docs in same commit. Write Spoolman ONLY via the explicit Apply.
  Settings-bag writes limited to the two OpenTag keys (merge, never clobber). Reuse #1's map
  + extra field. Don't change other sync behavior.

## Verification

- `cd backend && pytest` — tests: cache staleness/force-refresh; FDB endpoint parse + 404
  gate; matcher (exact/ambiguous/none); matches + apply endpoints (PATCH only provided
  fields, skip ignored, stamp slug+uuid); `ensure_extra_fields` registers both new fields;
  **settings-bag merge sets only the two OpenTag keys and preserves other keys**;
  settings-merge is idempotent (no rewrite when equal).
- `cd frontend && npx tsc --noEmit && npm run build`.
- Reason through: SM "PLA Silk" Beige → matched → review (defaults OpenTag, editable) →
  confirm page lists all writes → Apply writes material/density/temps/color/tags +
  slug+uuid → sync pushes slug+uuid into FDB settings bag without disturbing other keys.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `CLAUDE.md` (settings-bag exception), `docs/decisions.md`, `docs/spoolman-writes.md`
   updated.
3. Non-interactive subagent run: when pytest + tsc + build pass, stage ONLY the files this
   task touched (incl. prompt move + docs) and commit on `dev`. Never `git add -A`. Never push.
