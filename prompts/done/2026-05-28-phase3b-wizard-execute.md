---
name: 2026-05-28-phase3b-wizard-execute
status: completed        # pending | completed | failed
created: 2026-05-28
model: opus              # opus = research/planning, sonnet = coding
completed: 2026-05-29    # filled when the work is done
result: Added POST /api/wizard/execute (FR-7) — direction-aware initial-sync write to both upstreams with cross-ref linking, weight conversion, mappings, snapshot seeding, idempotent re-runs, per-record isolation, and the wizard_completed flip. 7 new tests; suite green (85).
---

# Task: Phase 3b — Wizard execute (FR-7, the initial-sync write)

Add the one endpoint Phase 3 left out: `POST /api/wizard/execute`. It takes the decisions
the user made through the wizard (direction, confirmed matches, weight overrides, variant
groupings — all already persisted in Phase 3) and **performs the initial write to both
upstream systems**: writes cross-reference IDs, creates missing records, applies weight
conversions, records the bridge mappings, logs everything, and flips
`wizard_completed=true`.

This is the riskiest write path in the project — it mutates both live systems in bulk on
first run — so it gets its own prompt and `opus`. This implements **FR-7**.

## Before you start

- **Phase 2 and Phase 3 must both be merged.** This endpoint orchestrates the Phase 2
  client write methods (`create_filament`, `create_spool`, `log_usage`, `update_*`,
  `ensure_extra_fields`) and `core/weight`, and slots into the `api/wizard.py` router
  Phase 3 built. Read those signatures first; do not reimplement them.
- **Read `docs/prd.md` FR-7** and the FR-3…FR-6 wizard steps that feed it (the persisted
  decisions are this endpoint's input).
- **Read `docs/decisions.md`** — variant inheritance + strip-computed-fields-before-PUT,
  the Spoolman extra-field JSON-quoting quirk, weight conversion math, and the deep-link /
  cross-ref-ID model. All decided; honor them.
- **Read `CLAUDE.md`** — the cross-reference ID storage section, the weight-decrement-as-
  usage rule, and the hard rules (never delete upstream, never raw weight overwrite, never
  touch the FDB `settings{}` bag).
- Use the `vexp` `run_pipeline` MCP tool for code context, not grep/glob.

## Working tree check

Before editing, run `git status --porcelain` and cross-reference the files this touches
(`backend/app/api/wizard.py`, possibly `backend/app/schemas/api.py`,
`backend/tests/`). If any are dirty, list them and ask. Surface unrelated dirty files
once; don't block. This prompt file is exempt.

## What to do

### 1. `POST /api/wizard/execute` in `api/wizard.py`

Drive the initial sync from the persisted wizard decisions. Order matters — create
parents before variants, filaments before their spools:

1. **Vendors / filaments first.** For each confirmed create-in-target filament, create it
   (FDB: `create_filament`, set `parentId` for variants and create parents before
   children; Spoolman: `create_vendor` if needed → `create_filament`). For matched pairs,
   no create — just proceed to linking.
2. **Cross-reference IDs.** Write `filamentdb_id` / `filamentdb_parent_id` /
   `filamentdb_spool_id` to Spoolman extra fields (via the client's JSON-encoding helper —
   never raw), and the Spoolman spool ID into the configured FDB spool label field. Call
   `ensure_extra_fields()` first if not already guaranteed.
3. **Spools + weight conversion.** Create missing spools (`create_spool`) applying the
   per-spool/per-filament tare overrides from the wizard via `core/weight`. For the
   initial set, weights are *set on create*, not decremented — do NOT emit usage entries
   for the seed import (usage logging is for ongoing decrements, FR-9).
4. **Bridge mappings.** Insert `FilamentMapping` / `SpoolMapping` rows linking both sides.
5. **Audit + snapshot.** Write a `SyncLog` row per action (`cycle_id` = a wizard-execute
   UUID, `action` = create/update/skip/error). Seed the `Snapshot` table with the
   post-execute state so the first auto-sync cycle diffs against a correct baseline (no
   spurious changes on cycle 1).
6. **Flip the flag.** Set `BridgeConfig.wizard_completed = true` only after a successful
   run (or after a run with no fatal errors — see idempotency below).
7. **Report.** Return `{created, updated, skipped, failed}` with per-record detail and
   deep-link IDs, matching the FR-7 report shape.

### 2. Safety: idempotency, partial failure, re-run

- **Idempotent / resumable.** The wizard may be re-run after a partial failure. Before
  creating, check for an existing mapping / existing cross-ref ID and skip-with-link
  instead of duplicating. A second execute on an already-linked record is a no-op, not a
  duplicate.
- **Per-record isolation (NFR-4).** One record's API error becomes a `failed` entry +
  `SyncLog` `action="error"` and the run continues — never abort the whole import on a
  single bad record.
- **Never delete** anything upstream to "clean up" a partial run. Leave it; the re-run
  reconciles.
- **No conflicts here** — the wizard is the user explicitly choosing the initial state, so
  there's nothing to queue. (Conflicts are an ongoing-sync concept, FR-13.)

### 3. Tests

Extend `backend/tests/` with faked upstream clients (no live network):
- A clean execute creates the expected records, writes cross-ref IDs on both sides, and
  inserts the mapping rows.
- Seed weights are *set*, not logged as usage.
- A re-run after a simulated partial failure creates no duplicates (idempotency).
- A single record's client error yields a `failed` entry and the rest still import.
- `wizard_completed` flips to true only on a non-fatal run.
- `cd backend && pytest` passes.

## Conventions to honor

- Delegate writes to the Phase 2 client methods + `core/weight`; this endpoint
  orchestrates order, linking, logging, and reporting — it doesn't reimplement conversions
  or HTTP.
- Cross-ref values through the client JSON helper; strip computed fields before any FDB
  PUT; don't touch the `settings{}` bag.
- Seed import sets weights directly; usage entries are for ongoing decrements only.
- `func.now()` timestamps, UTC; structured JSON logs; respect `LOG_LEVEL`.

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/` (failure).
3. Record non-obvious decisions in `docs/decisions.md` (e.g. the create-order rule, the
   idempotency/skip-if-linked strategy, the snapshot-seeding choice).
4. Propose ONE commit (no `Co-authored-by:`). Suggested message:
   `feat: Phase 3b — wizard execute (initial-sync write to both upstreams)`.
   Files: `api/wizard.py`, `schemas/api.py` (if touched), `tests/*`, `docs/decisions.md`,
   the prompt move. Present the file list and ask `commit these as "<message>"? (y/n)`
   before staging. Stage specific paths only; commit on `dev`; no push.
