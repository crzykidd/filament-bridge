---
name: 2026-05-31-spool-location-sm-to-fdb
status: completed
created: 2026-05-31
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-05-31
result: SM→FDB spool seed now carries location via locationId (FDB uses ObjectId ref, not string; pre-creation required)
---

# Task: Carry Spoolman spool `location` into Filament DB on seed

When the initial-sync wizard seeds Filament DB spools from Spoolman (the `spoolman` import
direction), the Spoolman spool's `location` is dropped — the FDB create payload only sets
`totalWeight` + the cross-ref id. Include the location so FDB spools land in the right place.
This unblocks (later) grouping the match review by location; that UI work is a **separate**
prompt (`2026-05-31-matches-table-grouping.md`) and is out of scope here.

Scope is the **initial seed via wizard execute, SM→FDB only.** Ongoing-sync location updates
(engine diff) and the FDB→SM direction are out of scope — note them as follow-ups, don't build.

## Before you start

- Read `CLAUDE.md` — the Filament DB endpoints section (`POST /api/filaments/:id/spools`,
  `GET /api/locations`, `PUT /api/locations/:id`, CSV import columns incl. `location`) and the
  "what NOT to do" rules. Read `docs/decisions.md`.
- Read the code you will change:
  - `backend/app/api/wizard.py` — the SM→FDB spool-seed payload at **L640-643** inside
    `_execute_spoolman_to_fdb` (Pass 3):
    ```python
    raw = await filamentdb.create_spool(fdb_id, {
        "totalWeight": spool_item.planned_gross,
        fdb_field_name: str(spool_item.sm_spool.id),
    })
    ```
    `spool_item.sm_spool` is a `SpoolmanSpool`; `spool_item.sm_spool.location` is the source value.
  - `backend/app/services/filamentdb.py` — `create_spool(filament_id, payload)` (L136) posts the
    payload through verbatim, so no client change is needed beyond adding the key.
  - `backend/app/schemas/spoolman.py` — `SpoolmanSpool.location` (L79, `str | None`).
  - `backend/app/schemas/filamentdb.py` — `FDBSpoolDetail.location` (L69) confirms FDB spools have
    a location field.
  - `backend/app/core/planner.py` — `_SpoolPlanItem` (L43). Add a `location` only if the
    dry-run/preview needs to display it (see step 3); the executor can read `sm_spool.location`
    directly.

- **VERIFY FIRST — FDB location semantics (open question, resolve before coding):** Filament DB
  models locations as first-class entities (`GET /api/locations`). Confirm against the live FDB
  instance / `docs/api.md` whether `POST /api/filaments/:id/spools` accepts a bare `location`
  string and **auto-creates** the location by name, or whether the location must already exist
  (analogous to Spoolman extra fields needing pre-creation). Record the answer in
  `docs/decisions.md`. If FDB requires pre-existing locations, the seed must first ensure the
  location exists (`GET /api/locations` → create/`PUT` if missing) before referencing it — design
  that in; do **not** silently drop spools whose location doesn't exist.

## Working tree check

Before any edits, run `git status --porcelain` and cross-reference the files this plan modifies
(`backend/app/api/wizard.py`, possibly `backend/app/core/planner.py`,
`backend/tests/test_api.py`, `docs/decisions.md`). If any have uncommitted changes, list them and
ask before touching. Surface unrelated dirty files once as awareness; don't block. This prompt
file is exempt.

## What to do

1. **Add `location` to the FDB spool-create payload** (`backend/app/api/wizard.py`, L640-643):
   include `"location": spool_item.sm_spool.location` when it is non-empty. Omit the key when the
   SM spool has no location (don't send `null`/empty — match the existing
   drop-None-keys convention in `_fdb_filament_payload_from_sm`).

2. **Handle FDB location pre-creation if required** (per the VERIFY step). If FDB auto-creates,
   nothing more is needed. If not, ensure-exists before the spool create, fetching the location
   list once per run and caching it (don't re-`GET /api/locations` per spool). Keep per-record
   isolation: a location-ensure failure becomes the spool's `failed` report entry, not a run abort.

3. **Preview parity (only if a spool preview surfaces location).** If the dry-run/preview
   (`wizard_preview` / `core/dryrun.py`) shows spool rows, add `location` to `_SpoolPlanItem` and
   the preview row so preview ≡ execute. If no preview surfaces spool location today, skip this and
   say so — don't invent UI.

## Tests (`backend/tests/test_api.py`)

4. Cover: a Spoolman spool with a `location` seeds an FDB spool whose `create_spool` payload
   includes that `location`; a spool with no location omits the key (no `null`); per-record
   isolation preserved (one spool's location/seed failure doesn't abort the others); idempotent
   re-run is still a no-op. Mirror the existing `test_wizard_execute_*` patterns. If step 2 adds
   location pre-creation, test the ensure-exists path too.

## Conventions to honor

- Match surrounding style; keep the executor per-record isolation + idempotency (NFR-4). Never
  delete upstream records. Weight handling unchanged — this only adds a location key.
- Doc updates ship in the **same commit** as the code. Commit on `dev`, Conventional-Commits
  (`feat:`), no `Co-authored-by:`. Never `--no-verify`. Never push.
- Run `cd backend && pytest` before proposing the commit.

## When done

1. Update this file's frontmatter: `status`, `completed` (date), `result` (one line).
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/` (failure).
3. Record in `docs/decisions.md`: the FDB location semantics you verified (auto-create vs
   pre-create), and that SM→FDB seed now carries spool location (ongoing-sync + FDB→SM are
   follow-ups).
4. Propose ONE commit covering the modified files (incl. the prompt move). Present the file list +
   a one-line `feat:` message; ask `commit these as "<message>"? (y/n)`. On `y`, stage those
   specific paths and commit on `dev`. Never `git add -A`. Never push.
</content>
