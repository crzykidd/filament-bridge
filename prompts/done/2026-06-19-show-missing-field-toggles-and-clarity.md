---
name: 2026-06-19-show-missing-field-toggles-and-clarity
status: done
created: 2026-06-19
model: sonnet
completed: 2026-06-19
result: >
  Backend: added AuditedField/AuditedFieldGroup Pydantic models and audited_fields block to
  OpenTagCompletenessResponse (opentag.py). Frontend: added AuditedField/AuditedFieldGroup types
  (api/types.ts), FieldToggleChips component + localStorage persistence + client-side filter
  (OpenTagCleanup.tsx). Copy updated: intro, toolbar title, idle help. Docs updated:
  opentag-cleanup.md toolbar bullet + report section + controls. CHANGELOG [Unreleased] entry
  added. Test added: test_completeness_audited_fields_in_response.
---

# Task: Show missing values — per-field toggle chips (localStorage) + clearer purpose copy

Two improvements to the OpenPrintTag "Show missing values" completeness report (already built
as an audit; this extends it):
1. **Per-field include/exclude toggle chips** at the top, covering EVERY audited field, persisted
   per-browser in localStorage — so the user controls which fields count (replaces any
   tool-side "applicability" guessing — *they* decide chamber-temp is irrelevant, etc.).
2. **Clearer intro copy** framing it as an optional tool to find which of *your* filaments most
   need contributions at OpenPrintTag.

## Verified current state (file:line)

- Backend `backend/app/api/opentag.py`: `GET /api/openprinttag/completeness` →
  `_compute_completeness`. The canonical audited-field lists are the module constants
  `SUPPORTED_MATERIAL_FIELDS` / `SUPPORTED_PACKAGE_FIELDS` / `SUPPORTED_CONTAINER_FIELDS` in
  `backend/app/core/opentag_cache.py` (each `(cache_key, label)`); the report excludes
  `heatbreakTemperature` (`_REPORT_EXCLUDED_MATERIAL_KEYS`) and treats `secondaryColors` as
  conditional (multicolor only). Response items carry `sections:[{scope, fields:[labels]}]`.
- Frontend `frontend/src/pages/OpenTagCleanup.tsx`: `MissingValuesReport` — intro heading/body
  `:1453-1466`, toolbar button label `:1968` + title `:1966`, inline help `:2041`. Existing
  controls: most-missing/brand sort + hide-complete toggle.
- Docs: `docs/opentag-cleanup.md` toolbar bullet `:26-28`, report section `:193-248`.

## What to do

### A. Backend — expose the canonical audited-field list
- Add an `audited_fields` block to the completeness response: the full set of checked fields the
  report uses, grouped by scope, as `{scope: [{key, label}]}` — derived from the same
  `SUPPORTED_*_FIELDS` constants minus the report's exclusions (drop `heatbreakTemperature`;
  include `secondaryColors` but mark it conditional so the UI can label it). This is the source
  the UI renders chips from, so chips appear for EVERY audited field even when no record currently
  misses it. (Reuse the constants; don't hardcode a second list.)

### B. Frontend — toggle chips + localStorage filter (`MissingValuesReport`)
- Render a chip per audited field at the top, grouped by **Material / Package / Container**, using
  `audited_fields`. Default: all included. Click a chip to **exclude** it (visually muted/struck);
  click again to include.
- Persist the excluded-field set in **localStorage** (e.g. key `fb_opt_missing_excluded_fields`,
  storing field `key`s), per browser.
- **Apply client-side:** drop excluded fields from each record's `sections`, recompute
  `missing_count` from the remaining fields, and re-apply the hide-complete behavior (a record
  whose remaining count is 0 is hidden unless "Show complete" is on). Sorting (most-missing)
  uses the recomputed counts. No server round-trip — purely browser-local.
- Keep it usable: a "Reset" (clear all exclusions) affordance; show how many fields are excluded.

### C. Copy — clearer purpose
- Reword the report intro (`OpenTagCleanup.tsx:1453-1466`), the toolbar button title
  (`:1966`), and the inline help (`:2041`) to frame it as: *an optional tool to find which of the
  filaments in your library most need data contributed to OpenPrintTag* — emphasizing it audits
  OpenPrintTag (not your spools) and is for deciding what to go submit.
- Match the docs: `docs/opentag-cleanup.md` toolbar bullet (`:26-28`) and report section intro
  (`:193-201`), and document the new per-field toggle filter.

## Edge cases
- Chips must list ALL audited fields (material + package + container), not only currently-missing
  ones — that's why the backend `audited_fields` list is needed.
- `secondaryColors` chip: when excluded, never counted; when included, still only counts for
  multicolor records (keep the existing conditional rule).
- Excluding every field → all records show 0 → empty report (fine; user did that).
- localStorage absent/corrupt → default to all-included.

## Before you start / working tree
Read `_compute_completeness` + the `SUPPORTED_*_FIELDS` constants, `MissingValuesReport`, and the
report section of `docs/opentag-cleanup.md`. `git status --porcelain` (build on current `dev`).

## Tests
- Backend: response includes `audited_fields` grouped by scope with all supported labels (minus
  heatbreak); existing item shape unchanged.
- Frontend: chips render for all audited fields; excluding a field removes it from records +
  recomputes counts + can hide a now-complete record; exclusions persist across reload
  (localStorage); reset clears them.
- `cd backend && .venv/bin/python -m pytest -q && .venv/bin/ruff check .` and
  `cd frontend && npx tsc --noEmit && npm test` green.

## Conventions / when done
Doc updates same commit (`docs/opentag-cleanup.md`; `CHANGELOG.md` `[Unreleased]`).
Conventional-commits `feat:`. No `Co-authored-by:`. Branch `dev`, never `main`, never push.
Update frontmatter, `git mv` to `prompts/done/`, propose ONE commit (specific paths), present
list + one-liner, STOP.
