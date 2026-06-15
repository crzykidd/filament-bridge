---
name: 2026-06-08-wizard-openprinttag-filter
status: done
created: 2026-06-08
model: sonnet
completed: 2026-06-07
result: Implemented openprinttag boolean flag on FilamentRef (backend schema + _sm_ref builder) and "OpenPrintTag-tagged only" filter toggle in Step3Matches wizard UI. 668 backend tests pass, frontend tsc + build clean.
---

# Task: Wizard match step — filter to OpenPrintTag-tagged filaments (stage your sync)

Let the user sync their inventory in stages by filtering the wizard match table to only the
Spoolman filaments that have been cleaned/stamped via OpenPrintTag (i.e. carry an
`openprinttag_uuid`). Backend flag + frontend filter.

## Backend (`backend/app/api/wizard.py`)

The wizard match SM reference (built by `_sm_ref`, returned in `wizard_matches`) should carry
whether the Spoolman filament is OpenPrintTag-tagged. Add a boolean field (e.g. `openprinttag`
or `opt_tagged`) to the SM-ref schema and set it from the SM filament's extra:
`bool(decode_extra_value(sm.extra.get(_settings.spoolman_field_openprinttag_uuid)))` (treat
empty string / None / missing as False). `_sm_ref` receives a `SpoolmanFilament`, which has
`.extra` — verify and decode via `decode_extra_value` (already imported). Update the SM-ref
Pydantic schema accordingly. This flag rides on matched / unmatched_spoolman / ambiguous rows
(any row backed by an SM filament).

## Frontend (`frontend/src/pages/Wizard/Step3Matches.tsx` + types)

- Add the new flag to the SM-ref TS type.
- Add a filter toggle — "OpenPrintTag-tagged only" — that, when on, keeps only rows whose SM
  filament has the flag true (FDB-only / `unmatched_fdb` rows have no SM side → hidden when the
  filter is on). Wire it into the existing `filtered` useMemo alongside `filterStatus`/`search`.
- Default OFF. Match the existing filter-control styling. A small count of how many are tagged
  is a nice touch if trivial.

This lets the user, e.g., run the OpenTag cleanup on a batch, then in the wizard show only those
tagged filaments and sync just that stage.

## Verification

- `cd backend && pytest` — test: `wizard_matches` SM refs expose the flag — true for a filament
  with a non-empty `openprinttag_uuid` extra, false otherwise.
- `cd frontend && npx tsc --noEmit && npm run build`.
- Reason through: enabling "OpenPrintTag-tagged only" narrows the table to cleaned filaments so
  the user can sync in stages.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. No docs/decisions entry needed unless non-obvious.
3. Non-interactive subagent run: when pytest + build pass, stage ONLY the files this task
   touched (incl. prompt move) and commit on `dev` with one `feat:` message. Use a
   pathspec-scoped commit; if git hits an index lock, wait ~5s and retry once. Never
   `git add -A`. Never push.
