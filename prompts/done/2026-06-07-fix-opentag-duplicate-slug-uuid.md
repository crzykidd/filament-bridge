---
name: 2026-06-07-fix-opentag-duplicate-slug-uuid
status: completed        # pending | completed | failed
created: 2026-06-07
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-07
result: Filtered slug/uuid from _build_field_rows; confirm page now shows each extra field once; 573 pytest + frontend build green
---

# Task: OpenTag confirm page shows duplicate openprinttag_slug/uuid writes

The OpenTag Cleanup "Confirm writes" page lists `extra.openprinttag_slug` and
`extra.openprinttag_uuid` TWICE per filament, and inflates the write count (e.g. "8 writes"
when it should be 6).

Cause (double source):
1. The matches endpoint's `_build_field_rows` (`backend/app/api/opentag.py` ~151) builds the
   per-field comparison rows from `opt_to_spoolman_fields(best)`, which INCLUDES
   `extra.openprinttag_slug` + `extra.openprinttag_uuid`. So `match.fields` contains them.
2. The frontend confirm-list (`frontend/src/pages/OpenTagCleanup.tsx` ~274-275) ALSO pushes
   `extra.openprinttag_slug`/`uuid` explicitly from `match.opt_slug`/`opt_uuid`.

→ shown twice. (The apply's `_build_sm_patch` dedupes the actual SM PATCH, so it's a
display/count bug, not a data corruption — but it's confusing and the count is wrong.)

## What to do

The slug/uuid are identity stamps surfaced via the match's `opt_slug`/`opt_uuid` (and the
frontend writes them once + the apply sets them via `decision.openprinttag_slug/uuid`). They
are NOT user-editable comparison rows, so they should not appear in `match.fields`.

In `_build_field_rows` (matches endpoint), **skip the `openprinttag_slug` and
`openprinttag_uuid` extra keys** when building rows from `opt_to_spoolman_fields` (skip
`field == f"extra.{_settings.spoolman_field_openprinttag_slug}"` and the uuid equivalent).
Leave `extra.filamentdb_material_tags` and all native fields as rows.

This makes `match.fields` = {material, filamentdb_material_tags, density, diameter, …}
without slug/uuid; the frontend's single explicit push then surfaces slug/uuid exactly once,
and the count is correct. Confirm the apply still WRITES slug/uuid (it does — via the
top-level `decision.openprinttag_slug/uuid`, unchanged).

(Do NOT change `opt_to_spoolman_fields` itself — other call sites/tests use its full output;
just filter at the field-rows layer. Alternatively filter in the frontend instead, but the
backend field-rows filter is the cleaner single fix — pick one, not both.)

## Verification

- `cd backend && pytest` — test: the matches endpoint's per-filament `fields` does NOT
  contain `extra.openprinttag_slug` or `extra.openprinttag_uuid`, but `opt_slug`/`opt_uuid`
  are still populated on the match; native + material_tags rows remain.
- `cd frontend && npx tsc --noEmit && npm run build`.
- Reason through the screenshot (SM #86): confirm now shows 6 writes (material,
  filamentdb_material_tags, density, diameter, openprinttag_slug, openprinttag_uuid) — each
  once — and the apply still persists slug + uuid.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md` only if non-obvious.
3. Non-interactive subagent run: when pytest (+ build) pass, stage ONLY the files this task
   touched (incl. prompt move) and commit on `dev` with one `fix:` message. Never
   `git add -A`. Never push.
