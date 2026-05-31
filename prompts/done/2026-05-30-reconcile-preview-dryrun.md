---
name: 2026-05-30-reconcile-preview-dryrun
status: completed        # pending | completed | failed
created: 2026-05-30
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-05-31
result: Read-only wizard preview shipped — backend planner/endpoint/flags + tests were already in place; added the frontend preview step (StepNPreview), types, and client. E2E on clean FDB matched backlog (empty_active=63, default_tare=79) with zero writes.
---

# Task: Initial-sync reconcile PREVIEW (dry-run) — FR-4 foundation

Build a single consolidated, **read-only** preview of the initial Spoolman→FDB import: what
would be created, plus every reconcile issue that needs a human decision. This is the
"start with a clean Filament DB and see the preview" step, and it is the data layer the
FR-4 reconcile **decision** UI (a later prompt) will sit on. **This prompt builds the
preview and surfacing only — it makes NO decisions and writes NOTHING to either upstream.**

## Scope guardrails (read first)

- **No writes.** The preview must not call any FDB/Spoolman mutating endpoint. Read-only.
- **No decision UI, no auto-resolution.** Surface the issues; do not let the user resolve
  them yet, and never silently pick a resolution (hard project rule). Decisions are the
  next phase.
- **Reuse execute's planning, don't fork it.** The plan the preview shows MUST match what
  `wizard_execute` would actually do. Factor the shared payload/weight/matcher logic so the
  two cannot drift (see step 1).

## Before you start

- **Read `CLAUDE.md`** (weight model, FDB/Spoolman gotchas, hard rules) and
  **`docs/reconcile-backlog.md`** items **1–4** — they ARE the spec for the four flag types.
  Item 5 (multicolor) already shipped; reflect its `colorName` projection in the preview but
  don't re-solve it.
- Use the `vexp` `run_pipeline` MCP tool for code context, not grep/glob.
- Study the existing pieces you will reuse:
  - `backend/app/api/wizard.py` — `_fdb_filament_payload_from_sm` (create payload, now
    multicolor-aware), `_execute_spoolman_to_fdb` (the write path to mirror as a dry plan),
    the FR-5 weights endpoint (`wizard_weights`) and FR-6 variants (`wizard_variants`,
    `_strip_color`).
  - `backend/app/core/matcher.py` — `normalize_name` / `normalize_vendor` / `normalize_color`
    (use these for collision + variant-group keys; don't reinvent normalization).
  - `backend/app/schemas/api.py` — `WizardExecuteRecord` / `WizardExecuteResponse` shapes to
    model the preview response after (carry both deep-link IDs on every row).
  - Frontend `frontend/src/pages/Wizard/Step6Execute.tsx` + `index.tsx` for the step pattern,
    and `frontend/src/api/*` for the typed client + types.

## Working tree check

Run `git status --porcelain`. Files this likely touches: `backend/app/api/wizard.py` (new
preview endpoint + extracted planner), `backend/app/schemas/api.py` (preview response
models), a new `frontend/src/pages/Wizard/StepNPreview.tsx` + `Wizard/index.tsx`,
`frontend/src/api/types.ts` + `client.ts`, and `backend/tests/*`. If any are dirty, list and
ask. `private_data/`, `backend/.env` are gitignored. This prompt file is exempt.

## What to do

### 1. Extract a pure-ish planner from execute (no writes)
Refactor the Spoolman→FDB planning currently inlined in `_execute_spoolman_to_fdb` so the
decision of *what would happen per filament/spool* (target FDB payload, weight conversion,
tare source, match vs create) is computed by a function that does **no I/O writes** and
returns plan rows. `wizard_execute` then consumes the plan and performs the writes; the new
preview endpoint consumes the same plan and only reports. This is what keeps preview ≡
execute. Reads (fetching current FDB/Spoolman state) are fine.

### 2. Preview endpoint — `GET /api/wizard/preview` (read-only)
Returns a structured report computed from the planner against the **current** FDB +
Spoolman state and the persisted wizard decisions/config (direction, tare overrides,
weight precision, multicolor format). Include:
- **Plan summary:** counts of filaments/spools that would be `created` vs `matched`
  (linked to an existing FDB record), with per-record rows carrying both deep-link IDs and
  the planned action — reuse the `WizardExecuteRecord` shape.
- **Reconcile flags**, one list per type (from `docs/reconcile-backlog.md` 1–4):
  1. **`name_collision`** — incoming FDB filament name (after `normalize_name`) clashes with
     (a) an existing FDB filament OR (b) **another incoming filament in the same batch**
     (FDB enforces unique names, so 10× "Black" self-collide). Each entry: the colliding
     name, the SM filament(s) involved, and whether the clash is vs-existing or intra-batch.
     This is the highest-value flag — it's what makes a clean import fail today.
  2. **`empty_active`** — Spoolman spool `remaining_weight == 0` and **not** archived.
  3. **`default_tare`** — SM filament has no `spool_weight`; the 200 g default was substituted,
     so the planned gross weight is a guess. Include the computed gross and the default used.
  4. **`variant_group`** — group the **to-be-created** filaments by vendor + material with
     color stripped (reuse `_strip_color` + normalization). FR-6 only groups *matched* records
     and returns nothing on an empty FDB; this fills that gap for fresh imports. Report the
     proposed groups (no `parentId` is written here — that's a decision for the next phase).
- Each flag entry must carry the IDs needed for deep links and for the future decision UI.
- **Counts per flag type** at the top so the UI can show "43 name collisions, 63 empty-active,
  79 default-tare, N variant groups" at a glance.

### 3. Read-only preview UI (new wizard step before Execute)
- Add a preview step in `frontend/src/pages/Wizard/` (e.g. `StepNPreview.tsx`) wired into
  `Wizard/index.tsx`, placed **before** the Execute step. It shows the plan summary and the
  four flag groups (collapsible sections with counts). Read-only: no buttons that mutate.
- Surface a clear, non-blocking notice that flagged items will need decisions in a later
  release (so a user doesn't think the preview is broken when collisions appear).
- Use the existing typed api client + types; match the existing wizard step styling.

## Conventions to honor
- Read-only; delegate HTTP to existing service clients; never write to upstreams from preview.
- Reuse `matcher` normalization and existing weight-conversion logic — no parallel copies.
- Structured logs, respect `LOG_LEVEL`. Never touch the FDB `settings{}` bag.
- Frontend matches existing wizard step + typed-client patterns.

## Verification
- `cd backend && pytest` green — new tests: planner produces create-vs-match rows without
  writing (assert no mutating client calls, e.g. via a mock that fails on POST/PUT/PATCH);
  name-collision detects both vs-existing and intra-batch dupes; empty_active flags
  `remaining_weight==0 && !archived` and NOT archived-and-empty; default_tare flags
  missing `spool_weight` and reports the 200 g substitution; variant_group groups by
  vendor+material with color stripped on a fresh (empty-FDB) import.
- `cd frontend && npm run build` green; the preview step loads, shows counts, and renders the
  four flag sections.
- **End-to-end on the local stack** (`docker-compose.dev.yml`; re-seed
  `private_data/spoolman-livedata.db`; **clean/empty FDB**): hit `GET /api/wizard/preview`
  and confirm the live numbers land near the backlog's first run — ~43 name collisions, ~63
  empty-active, ~79 default-tare, plus variant groups — and that NOTHING was written to FDB
  or Spoolman (verify both are unchanged after the call).

## When done
1. Update frontmatter: `status`, `completed`, `result`.
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/` (failure).
3. Record any non-obvious calls in `docs/decisions.md` (e.g. where the planner was extracted,
   the exact collision key, the variant-group key). Note in `docs/reconcile-backlog.md` that
   items 1–4 are now **surfaced (preview)** but not yet **resolvable** (decision UI pending).
4. Propose ONE commit (no `Co-authored-by:`). Suggested message:
   `feat: initial-sync reconcile preview (dry-run) surfacing collisions, empties, tare, variants`.
   Present the file list and ask `commit these as "<message>"? (y/n)` before staging. Stage
   specific paths only; commit on `dev`; no push.
