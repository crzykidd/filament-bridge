---
name: 2026-06-13-conflict-add-bulk-parity-and-filament-visibility
status: completed
created: 2026-06-13
model: opus              # PLAN first — filament display-data approach + matcher reuse
completed: 2026-06-13
result: >
  P1 (filament visibility): FilamentMapping.identity JSON blob added (Alembic migration
  b7c2e1f4a9d3); build_mapping_rows emits kind="filament" rows for spool-less mappings;
  filament_mapping_status extracted to core/filament_status.py (shared by sync.py +
  mappings.py). P2 (suggestions dropdown): GET /conflicts/{id}/filament-suggestions
  endpoint added; NewRecordAddFlow replaced bare id field with ranked suggestions
  dropdown + 24-hex manual override. SyncedRecords renders filament-only rows.
  All tests written; ruff/tsc/npm tests pending user execution (sandbox blocked Bash).
---

# Task: Conflict "Add" parity with Bulk Import + make imported filaments visible in the bridge

The Conflicts "Add filament" flow (shipped in the #2 redesign via `single_record_import` +
a bespoke modal) has two real defects. Both reduce to: **make Add behave like the Bulk
Import Wizard, and make imported records actually appear in filament-bridge.**

## Problem 1 — imported spool-less filaments are INVISIBLE in filament-bridge (the bug)

Verified live: 4 imported filaments (Spoolman filament ids 10, 14, 115, 120) have a
`FilamentMapping` (and exist in Filament DB) but **zero spools in Spoolman**, so no
`SpoolMapping` exists. `build_mapping_rows` (`backend/app/api/mappings.py`) is **spool-keyed**
(one row per `SpoolMapping`), so these filaments never appear in Synced Records. User
symptom: *"it shows up in Filament DB but doesn't show shit in filament-bridge"* — the Add
succeeds, the conflict resolves, but the record is invisible in the bridge.

This is the SAME issue from the very start of the session (Light Purple PLA). A first
attempt was reverted because **filament snapshots store only an `_mp_*` comparison
projection (no name/vendor/color)**, so filament-only rows rendered blank, and it also
surfaced the synthetic FDB-only `(Master)` containers (FilamentMappings with NULL
`spoolman_filament_id`). Fix it properly this time.

### What to do (Problem 1)
- **Synced Records must show filament-level mappings**, not just spool pairs. Emit a row for
  each `FilamentMapping` that has no child `SpoolMapping` AND has a non-NULL
  `spoolman_filament_id` (EXCLUDE the synthetic `(Master)` containers — those are FDB-only).
- **Solve the display-data problem** (this is why it failed before — settle in the plan):
  the rows need vendor · name · color. Filament snapshots don't carry them. Recommended:
  **persist the filament's display identity (vendor, name, color_hex, material) on the
  `FilamentMapping`** at creation time (wizard execute + `single_record_import` both have the
  SM/FDB filament object in hand) — mirror the conflict-identity-blob approach from commit
  1c25d73. Alternative to weigh: enrich the stored filament snapshot with display fields, or
  have `build_mapping_rows` resolve identity another way. Pick one in the plan; migration must
  degrade gracefully for existing mappings lacking the data (fall back to id, or backfill).
- **Frontend `SyncedRecords.tsx`**: render filament-only rows — null spool weights show "—",
  deep-links use the FILAMENT links only (no spool link), status = in_sync/pending at the
  filament level. (DeepLinks already null-handles spool id.) Don't crash on null spool ids.
- Status for a filament-only row: reuse the dashboard filament-status logic already added in
  `api/sync.py` (commit e14f053) for consistency.

## Problem 2 — Add "link" must reuse the Bulk Import matcher (not a raw id field)

User: *"Create new filament is fine, but we should do a lookup from Filament DB and show a
dropdown of the variants we think, then allow an override to a 24-char hex."* And: *"I thought
we were just going to use the exact same logic as bulk import."*

Today the Add "link" action is a bare 24-char text field (`Conflicts.tsx` NewRecordAddFlow,
`filamentdbId` input). It should mirror the wizard's match step.

### What to do (Problem 2)
- **Suggestions endpoint:** add an endpoint that, given the conflict's Spoolman filament,
  runs the **existing wizard matcher** (`backend/app/core/matcher.py` — fuzzy vendor+name+color
  used by the Bulk Import match step) against the live FDB filaments and returns ranked
  candidate FDB filaments (id, name, vendor, color, score, variant/parent info). Reuse the
  matcher — do NOT write a new matching algorithm. (Note: this is the FDB-filament matcher,
  distinct from the OpenTag matcher.)
- **Conflict Add "link" UI:** replace the raw id field with a **dropdown of suggested FDB
  variants** (top matches from the endpoint, with score + variant labels), PLUS a manual
  **24-char hex override** field for when the user knows the exact FDB id. "Create new" stays
  as-is.
- The execute still goes through the existing `/conflicts/{id}/import` (`filament_action=link`,
  `filamentdb_id=<chosen>`), which already drives the wizard execute path — keep that.

## Bigger-picture (confirm in plan)
The user's mental model is "Add = the Bulk Import Wizard, scoped to one record." Verify the
`single_record_import` path truly matches wizard execute behavior (variant grouping, finish
tags, multicolor, snapshots-both-sides). If there's drift from the wizard, reconcile it — one
create-path. Flag any divergence found.

## Before you start
Read `docs/wizard.md`, `docs/conflicts.md`, `docs/sync-model.md`, and the code:
`backend/app/api/mappings.py` (build_mapping_rows), `backend/app/models/mapping.py`,
`backend/app/core/single_record_import.py`, `backend/app/api/conflicts.py` (import endpoint),
`backend/app/core/matcher.py` (the FDB-filament matcher + how Step3Matches uses it via
`api/wizard.py`), `frontend/src/pages/Conflicts.tsx` (NewRecordAddFlow),
`frontend/src/pages/SyncedRecords.tsx`, `frontend/src/components/DeepLinks.tsx`. Memory:
[[filament-snapshot-projection-only]] explains the no-display-data trap.

## Working tree check
`git status --porcelain`; expect clean (HEAD is the latest get_spools fix). If dirty, list +
ask. This prompt is exempt.

## Step 0 — PLAN before coding (model=opus)
Settle: the filament display-data mechanism (store-on-FilamentMapping vs snapshot-enrich vs
other) + migration/backfill; the matcher-suggestions endpoint shape; the SyncedRecords
filament-row rendering + status; and whether single_record_import has drifted from wizard
execute. Confirm ambiguous calls with the user.

## What to do (after plan agreed)
Implement Problems 1 + 2. Tests: filament-only mapping appears in `build_mapping_rows` /
Synced Records with identity (and synthetic masters excluded); the suggestions endpoint
returns ranked FDB candidates for a known SM filament; Add-link via a suggested candidate
creates the SpoolMapping/links correctly and the record then shows in the bridge. Backend
pytest + ruff; frontend tsc + npm test.

NOTE on running tests: this dev sandbox lacks `itsdangerous`, so `test_api.py` etc. can't run
here directly. Use a throwaway venv (`python3 -m venv $TMPDIR/v && $TMPDIR/v/bin/pip install
-r requirements.txt pytest pytest-asyncio`) to run the FULL suite, or ensure your new tests
live in a module that imports cleanly. All must pass.

## When done
Update frontmatter; `git mv` to `prompts/done/`; log the display-data decision in
`docs/decisions.md`; update `docs/conflicts.md` + `docs/wizard.md`. Propose ONE commit
(`feat:`), specific paths, never `git add -A`. STOP for the user to run it. Never push.
