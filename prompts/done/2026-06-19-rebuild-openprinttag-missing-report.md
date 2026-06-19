---
name: 2026-06-19-rebuild-openprinttag-missing-report
status: done
created: 2026-06-19
model: opus              # PLAN first; then implement
completed: 2026-06-19
result: >
  Rebuilt the completeness report as an OpenPrintTag audit. Backend
  `_compute_completeness` now lists every SUPPORTED_*_FIELDS empty field across
  material + each package + each package's container; dropped your_value/opt_value
  (sections:[{scope,fields}] replaces attributes). Removed _your_value_hint and
  OpenTagMissingAttribute. heatbreakTemperature excluded. Material vs package url
  reported at distinct levels. Frontend renders grouped sections, no hint column.
  Tests rewritten to new shape; backend pytest (1156) + ruff + frontend tsc + 94
  vitest all green. Live-verified elegoo-pla-red: package GTIN gap shown, package
  url set (not flagged), material productUrl genuinely empty (correctly listed).
  Docs updated (opentag-cleanup.md, CHANGELOG [Unreleased], decisions.md). Left
  uncommitted for orchestrator review.
---

# Task: Rebuild the "missing values" report — audit OpenPrintTag, not my spools

This tool answers ONE question: **for the records I own, what supported fields is OpenPrintTag's
master DB missing — so I can decide what to go contribute.** My spool's own data is irrelevant;
the only role of my inventory is to scope WHICH OpenPrintTag records to audit. Depends on
`2026-06-19-ingest-openprinttag-full-schema-packages-containers` (the full supported schema +
package/container data must already be in the cache).

## The contract (read carefully — this reverses the current design)

- **Scope = my matched (tagged) inventory.** For each Spoolman filament with a non-empty
  `openprinttag_uuid`, resolve its OpenPrintTag record via `by_uuid`.
- **List EVERY OpenPrintTag-supported field that is EMPTY on that record** — across **material +
  package(s) + container**. "Supported" = the canonical schema constant added by the ingest prompt.
  Empty = `v in (None, "", [])`.
- **NO spool-data comparison.** Remove the "Your value (hint)" column and any read of Spoolman
  field values for the comparison. The report shows only: the OpenPrintTag field and that it's
  missing.
- **NO applicability/N-A pre-judging.** List all supported empty fields; the USER decides which are
  worth submitting (e.g. they'll skip chamber-temp for PLA themselves). Do not hide fields by
  material type.
- **Fix the false-missing bug:** material `url` and package `url` are DISTINCT supported fields —
  report each at its own level. (Today RED shows "Product URL missing" though its package URL is
  set; post-fix, the material-url and package-url are separate line items reflecting reality.)

## What the current code does (to change) — verified

- Backend `backend/app/api/opentag.py`: `opentag_completeness` (~`:1555`) → `_compute_completeness`
  (~`:1604`): iterates tagged SM filaments (`:1618-1621`), builds per-attribute items with a
  `your_value` hint and a material-only empty-field set; stale-tag handling at `:1624-1639`. The
  `_COMPLETENESS_FIELDS` set is material-only and the item carries `your_value`.
- Frontend `frontend/src/pages/OpenTagCleanup.tsx`: `MissingValuesReport` (~`:1390`) renders an
  `Attribute | Your value (hint) | OpenPrintTag` table, `showComplete=false` default
  (`:1395`,`:1411-1413`).

## What to do (after the Step-0 plan)

### Backend (`_compute_completeness` + models)
1. For each tagged SM filament → OpenPrintTag record, compute the **empty supported fields** over:
   - **material** (full schema from the ingest prompt),
   - each **package** in `packages_by_material[material_slug]` (a record can have 1→N packages —
     report per package; and if the material has **no package at all**, that itself is a gap),
   - the package's **container** (`containers_by_slug[container_slug]`).
2. Response item shape: `{ spoolman_filament_id, brand, name, opt_slug, opt_uuid, opt_url(if any),
   missing_count, sections: [ {scope: "material" | "package:<slug>" | "container:<slug>",
   fields: [<missing supported field labels>] } ] }`. Drop `your_value` entirely.
3. Keep stale-tag handling. Keep it offloaded (`run_in_threadpool`) and respect the match cache if
   applicable.

### Frontend (`MissingValuesReport`)
4. Drop the "Your value (hint)" column. Render per record: brand · name · OPT slug (linked) ·
   total missing count; expand → grouped by section (Material / Package <size> / Container) listing
   the missing supported fields. Sort by most-missing / brand.
5. Reconsider the hide-complete toggle: a record with **zero** missing supported fields has nothing
   to contribute — fine to hide by default with a "show complete" toggle. Records WITH gaps always
   show. (The point is the to-do list of contributions.)
6. Rename the view/labels to OpenPrintTag (coordinate with the rename prompt if it lands first).

## Edge cases
- Multiple packages per material → list each (e.g. 1kg vs 5kg) with its own missing set.
- Material with no packages → surface "no package data" as a gap.
- Untagged filaments are out of scope (not matched). Stale tag (uuid not in dataset) → keep the
  distinct stale row.
- Don't reintroduce any spool-field comparison anywhere.

## Before you start
Read the ingest prompt's result (the new cache keys + supported-schema constant),
`backend/app/api/opentag.py` (`_compute_completeness`), `frontend/src/pages/OpenTagCleanup.tsx`
(`MissingValuesReport`), `docs/opentag-cleanup.md`. Verify against live data that RED
(`elegoo-pla-red`) now surfaces real package gaps (e.g. GTIN) and no false material-url gap.

## Working tree
`git status --porcelain`; build on `dev` after the ingest prompt is committed. List anything
unexpected; ask.

## Step 0 — PLAN (required: response shape + package/container traversal + hide-complete)
State the new response shape, the per-section traversal (material/packages/container), the
no-spool-data guarantee, the hide-complete behavior, and the test matrix. Confirm ambiguities.

## Tests
- A tagged record reports empty supported fields across material + package + container; NO
  `your_value` in the payload or UI.
- `elegoo-pla-red`: material-url not falsely "missing" as the only URL signal; package GTIN shows
  as missing; SKU/url/weight/diameter show as present (not listed).
- Multi-package material lists each package's gaps; no-package material flags "no package".
- Records with zero gaps hidden by default; gapped records always shown; sort works.
- `cd backend && .venv/bin/python -m pytest -q && .venv/bin/ruff check .` + `cd frontend &&
  npx tsc --noEmit && npm test` green.

## Conventions / when done
Doc updates same commit (`docs/opentag-cleanup.md` — the report's purpose/scope, `CHANGELOG.md`
`[Unreleased]`, `docs/decisions.md`). Conventional-commits `feat:`. No `Co-authored-by:`. Branch
`dev`, never `main`, never push. Update frontmatter, `git mv` to `prompts/done/`, propose ONE
commit, STOP.
