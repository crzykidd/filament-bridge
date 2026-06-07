---
name: 2026-06-07-opentag-review-uuid-name-existing
status: completed        # pending | completed | failed
created: 2026-06-07
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-07
result: UUID exact-match at 1.0, slug/uuid/name as field rows with existing SM value, frontend push removed; 605 tests pass
---

# Task: OpenTag cleanup — UUID exact-match, show existing identity, reviewable name

Three improvements to the OpenTag cleanup review/match (backend matches endpoint +
`opt_to_spoolman_fields` + frontend `OpenTagCleanup.tsx`):

1. **Exact UUID match → 100%.** If a Spoolman filament already has an `openprinttag_uuid`
   extra value (from a prior cleanup) that matches an OpenTag material's `uuid`, return that
   material as the match at confidence **1.0**, bypassing fuzzy scoring.
2. **Show the existing OpenTag identity in the review.** Surface the SM filament's CURRENT
   `openprinttag_slug`/`openprinttag_uuid` as review rows (old = existing value, blank if
   unset; new = OpenTag value), written once (no duplicate).
3. **Reviewable name, default OpenTag.** Add a `name` row (Spoolman name vs OpenTag name),
   defaulting to the OpenTag name, with the keep-mine toggle like other fields. The apply
   writes the name when not kept.

## Background

- Matches endpoint: `GET /api/openprinttag/matches` reads `sm.get_filaments()` (each
  `SpoolmanFilament` has `.extra: dict`). It builds per-filament `fields` via `_build_field_rows`
  from `opt_to_spoolman_fields(best)`, and sets `opt_slug`/`opt_uuid` from the match.
- A PRIOR fix (commit 48c05d6) EXCLUDED `openprinttag_slug`/`uuid` from `_build_field_rows`
  to avoid a duplicate, because the frontend also pushes them explicitly
  (`OpenTagCleanup.tsx` ~274-275). This task REVERSES that approach: put them back as rows
  (now carrying the existing SM value) AND remove the frontend's explicit push — that fixes
  the duplicate AND shows the existing id.

## What to do

### Backend
- **UUID index + exact match** (matches endpoint): build `by_uuid = {m["uuid"]: m for m in
  materials if m.get("uuid")}`. For each SM filament, decode its existing
  `openprinttag_uuid` extra (`decode_extra_value(sm_fil.extra.get(<uuid_field>))`). If it's
  set and present in `by_uuid`, use that material as `best` with `confidence = 1.0` and skip
  the brand/profile/family fuzzy path. (Optional: same for `openprinttag_slug` via a
  `by_slug` index as a fallback when uuid is absent.)
- **opt_to_spoolman_fields** (`backend/app/core/opentag_match.py`): add `result["name"] =
  opt.get("name")` (OpenTag name → SM name). Keep `extra.openprinttag_slug`/`uuid` in the
  output (they already are).
- **_build_field_rows**: STOP excluding `openprinttag_slug`/`uuid` — include them as rows,
  and set each row's `spoolman_value` to the filament's CURRENT decoded extra value (blank/None
  when unset). For the `name` row, `spoolman_value` = `sm_fil.name`. (Generally: a row's
  `spoolman_value` should read the live SM value — native attr for native fields, decoded
  `extra[key]` for extra fields — so "old" reflects reality, not always "—".)

### Frontend (`frontend/src/pages/OpenTagCleanup.tsx`)
- REMOVE the explicit `extra.openprinttag_slug`/`uuid` push in the confirm-write list
  (~274-275) — they now come from `match.fields` (shown once, with the real old value).
- Keep setting `decision.openprinttag_slug`/`uuid` (top-level, from `m.opt_slug`/`opt_uuid`)
  so the FDB settings-bag push still works; `_build_sm_patch` already dedupes the SM extra.
- The new `name` row flows through the generic field handling (default = OpenTag value,
  keep-mine supported). No special-casing needed.
- Nice-to-have: when a match is exact-by-uuid (confidence 1.0), show a small "exact (UUID)"
  badge. Skip if it complicates things.

### Apply
- `_build_sm_patch` already handles native fields (so `name` writes when not keep_mine) and
  dedupes the slug/uuid extra. Verify a `name` change produces `native["name"]`, and that
  slug/uuid still write exactly once.

## Verification

- `cd backend && pytest` — tests:
  - matches: a SM filament whose `extra.openprinttag_uuid` matches a material → match is that
    material with confidence 1.0 (no fuzzy); a filament without it → fuzzy as before.
  - `_build_field_rows`: includes `name`, `extra.openprinttag_slug`, `extra.openprinttag_uuid`
    rows; their `spoolman_value` reflects the filament's existing values (blank when unset);
    no row is duplicated.
  - `opt_to_spoolman_fields` includes `name`.
  - apply: writes `name` (native) when not keep_mine; slug/uuid written exactly once.
- `cd frontend && npx tsc --noEmit && npm run build` — must pass; confirm the slug/uuid no
  longer appear twice and the existing value shows as "old".

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md`: exact-UUID match (1.0); review shows existing openprinttag identity;
   name is a reviewable field (default OpenTag); slug/uuid sourced from field rows (reverses
   48c05d6's exclusion, dedup now via removing the frontend push).
3. Non-interactive subagent run: when pytest + build pass, stage ONLY the files this task
   touched (incl. prompt move + docs) and commit on `dev` with one `feat:` message. Never
   `git add -A`. Never push.
