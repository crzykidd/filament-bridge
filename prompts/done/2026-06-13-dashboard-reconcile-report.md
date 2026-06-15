---
name: 2026-06-13-dashboard-reconcile-report
status: completed
created: 2026-06-13
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-13
result: Added read-only Reconcile page (backend router + schemas, frontend page/nav/route, 8 tests) — matched/only-SM/only-FDB/ambiguous buckets with spool roll-ups and linked flag
---

# Task: Reconcile report — compare both systems, show matches + what's missing on each side

Add a read-only **Reconcile** feature: a dedicated page (entry point on the Dashboard)
that fetches *everything* in Filament DB and *everything* in Spoolman, matches them at
the filament level, and reports three buckets — matched pairs, only-in-Spoolman, and
only-in-Filament-DB — plus ambiguous (one SM filament, multiple FDB candidates). It is a
pure report: it writes nothing, links nothing, resolves nothing. Acting on a missing item
stays the Bulk Import Wizard's job.

This is essentially a read-only twin of the wizard's `/api/wizard/matches` step
(`backend/app/api/wizard.py:338`), enriched with per-filament spool roll-ups.

## Before you start

- Read `CLAUDE.md` (esp. "What NOT to do" — no upstream writes, no auto-linking) and the
  matcher/wizard sections below.
- Read these to copy their patterns exactly:
  - `backend/app/api/wizard.py:338-410` — `wizard_matches`: how it builds the
    `xref_by_sm_filament` map from SM spool `filamentdb_id` extra fields, calls
    `match_filaments(...)`, and the `_sm_ref` / `_fdb_ref` helpers (`wizard.py:172-192`).
  - `backend/app/core/matcher.py:210-279` — `match_filaments()` returns a `MatchResult`
    with `.matched` (list[MatchedPair: spoolman_filament, fdb_filament, confidence]),
    `.unmatched_spoolman`, `.unmatched_fdb`, `.ambiguous` (list of (SM, [FDB candidates])).
    A "match" = existing cross-ref (xref pre-pass, conf 1.0) **or** exact normalized
    vendor+name+color (conf 1.0). **Use this as-is — do not modify the matcher.**
  - `backend/app/api/mappings.py` — the `build_mapping_rows` / `GET /api/mappings`
    router-registration and `Depends(get_db)` pattern.
  - `backend/app/services/spoolman.py` (`get_spools`, `get_filaments`) and
    `backend/app/services/filamentdb.py` (`get_filaments` — FDB filaments embed their
    spools in `.spools`).
  - `frontend/src/pages/SyncedRecords.tsx` — table + `DeepLinks` usage to model the page
    on; `frontend/src/api/client.ts` + `types.ts` for the fetch-wrapper + type pattern;
    `frontend/src/components/Layout.tsx:217` (NAV_ITEMS) and `frontend/src/App.tsx:27`
    (routes).

- **Scope cut (decided):** NO fuzzy near-miss / suggestion pass. Missing items are listed
  plainly with no "possible match" hints. Only the matcher's existing cross-ref +
  exact-key matching is used. Do not add any new scoring/similarity logic.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files this
plan touches. If any have uncommitted changes, list them and ask before touching. Surface
unrelated dirty files once as awareness; don't block. This prompt file is exempt.

## What to do

### Backend

1. **New schemas** in `backend/app/schemas/api.py` (reuse the existing `FilamentRef` and
   `AmbiguousRow` — do not duplicate them):
   - `ReconcileMatchRow`: `spoolman: FilamentRef`, `filamentdb: FilamentRef`,
     `confidence: float`, `linked: bool` (True when the pair came from an existing
     cross-ref rather than a name match), `spoolman_spools: int`,
     `filamentdb_spools: int`, `spoolman_weight: float | None`,
     `filamentdb_weight: float | None`.
   - `ReconcileMissingRow`: `ref: FilamentRef`, `spool_count: int`,
     `weight_total: float | None`.
   - `ReconcileSummary`: `spoolman_filaments: int`, `filamentdb_filaments: int`,
     `matched: int`, `only_in_spoolman: int`, `only_in_filamentdb: int`,
     `ambiguous: int`.
   - `ReconcileResponse`: `summary: ReconcileSummary`,
     `matched: list[ReconcileMatchRow]`, `only_in_spoolman: list[ReconcileMissingRow]`,
     `only_in_filamentdb: list[ReconcileMissingRow]`, `ambiguous: list[AmbiguousRow]`.

2. **New router** `backend/app/api/reconcile.py` — `GET /api/reconcile` →
   `ReconcileResponse`. Async, `request: Request` + `db: Session = Depends(get_db)` like
   `wizard_matches`. Logic:
   - Fetch `sm_filaments`, `sm_spools` (all, incl. archived), `fdb_filaments` via
     `request.app.state.spoolman` / `.filamentdb`.
   - Build `xref_by_sm_filament` by copying the block at `wizard.py:343-359` verbatim
     (SM spool `filamentdb_id` extra field via `decode_extra_value`, first non-empty per
     filament wins, include archived spools).
   - `mr = match_filaments(sm_filaments, fdb_filaments, xref_by_sm_filament=xref_by_sm_filament or None)`.
   - **Spool roll-ups:**
     - SM: group `sm_spools` by `spool.filament.id` → count + Σ`remaining_weight`
       (skip `None` weights in the sum; if all None, weight is `None`).
     - FDB: each filament's embedded `.spools` → count + Σ`totalWeight` (same None
       handling). Exclude retired/soft-deleted FDB spools if the embedded shape exposes
       that (check the `FDBFilament.spools` schema — match whatever
       `get_filaments()` already returns; do not invent filtering it doesn't support).
   - **`linked` flag:** a matched pair is `linked=True` iff its SM filament id is a key in
     `xref_by_sm_filament` that resolved to the paired FDB id (i.e. it came from the xref
     pre-pass, not the fuzzy key pass). Compute this from the xref map + the pair's ids.
   - Build the response: map matched pairs through `_sm_ref`/`_fdb_ref` (import them from
     `app.api.wizard`, or lift them into a shared module if cleaner — your call, but
     prefer importing to avoid drift), attach roll-up counts/weights; map
     `unmatched_spoolman`/`unmatched_fdb` to `ReconcileMissingRow`; map `ambiguous` to
     `AmbiguousRow` exactly like `wizard.py:396-399`. Fill `summary` counts.

3. **Register** the router in `backend/app/main.py` next to the other protected routers,
   with `prefix="/api"` and the `Depends(require_auth)` dependency (match how
   `mappings`/`sync` are registered — copy the exact idiom used there).

### Frontend

4. `frontend/src/api/types.ts` — add TS interfaces mirroring the new schemas
   (`ReconcileResponse`, `ReconcileMatchRow`, `ReconcileMissingRow`, `ReconcileSummary`;
   reuse the existing `FilamentRef`/`AmbiguousRow` types if present, else add them).
   `frontend/src/api/client.ts` — `export const getReconcile = () => request<ReconcileResponse>('/reconcile')`.

5. **New page** `frontend/src/pages/Reconcile.tsx`:
   - On-demand fetch via `useApi(getReconcile)` — **not** `usePoll` (a full read of both
     systems is heavy). Provide a visible **Refresh** button wired to `reload()`.
   - Summary header showing the counts (e.g. "42 matched · 3 only in Spoolman · 5 only in
     Filament DB · 1 ambiguous", plus total filament counts each side).
   - Four sections: **Matched**, **Only in Spoolman**, **Only in Filament DB**,
     **Ambiguous**. Each row uses `DeepLinks` (`frontend/src/components/DeepLinks.tsx`) to
     both systems where the ids exist; show vendor / name / color, spool count + weight,
     and for matched rows a small "linked" vs "name match" indicator driven by `linked`.
   - Empty/loading/error states like SyncedRecords. Dark-mode classes consistent with the
     rest of the app.

6. **Route** in `frontend/src/App.tsx` — add `<Route path="reconcile" element={<Reconcile />} />`.

7. **Nav** in `frontend/src/components/Layout.tsx` NAV_ITEMS — add
   `{ to: '/reconcile', label: 'Reconcile', exact: false }` (place after Synced Records).

8. **Dashboard entry point** in `frontend/src/pages/Dashboard.tsx` — add a "Reconcile"
   button/card linking to `/reconcile` (use the existing button/card styles on that page;
   a `Link`/`NavLink` to `/reconcile` is fine). This satisfies "on the dashboard we need a
   reconcile option."

### Tests

9. `backend/tests/test_reconcile.py` — model fixtures on `backend/tests/test_matcher.py`.
   Cover: a clean match by name, a cross-ref match (assert `linked=True`), an
   only-in-Spoolman filament, an only-in-FDB filament, an ambiguous case, and spool
   roll-up counts/weights (incl. a `None`-weight spool). Assert the summary counts.
   If an API-style test (httpx client against the app) fits the existing patterns in
   `test_api.py`, prefer that for the endpoint; otherwise unit-test the builder function.

## Conventions to honor

- No upstream writes, no mapping writes, no auto-linking — read-only report. (CLAUDE.md
  hard rules.)
- Do not modify `matcher.py`. Reuse `match_filaments`, `_sm_ref`, `_fdb_ref`,
  `FilamentRef`, `AmbiguousRow`.
- Match surrounding code style; keep the new router thin (fetch → match → assemble).
- **Run the full backend suite via a throwaway venv** (the sandbox lacks `itsdangerous`,
  so `test_api`/`auth`/`debug` silently skip otherwise and you'll ship false-green):
  create `$TMPDIR/v`, `pip install -r backend/requirements.txt`, run `pytest` from
  `backend/`. Also run `ruff check backend/` and, in `frontend/`, `npx tsc --noEmit` +
  `npm test`. All must be green before proposing the commit.
- Add a `docs/` note only if a doc already enumerates pages/endpoints that would now be
  stale (e.g. a features list); ship it in the same commit if so. Don't author a whole new
  doc unless it's warranted.

## When done

1. Update this file's frontmatter: `status`, `completed` (2026-06-13), `result` (one line).
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/` (failure).
3. Record any non-obvious decisions in `docs/decisions.md` (e.g. read-only/on-demand
   choice, the `linked` semantics).
4. Propose ONE commit covering the files this session modified (including the prompt move).
   Present the file list + a one-line `feat:`-prefixed message; ask
   `commit these as "<message>"? (y/n)`. On `y`, stage those specific paths and commit on
   `dev` (never `main`, never `git add -A`, never push, no `Co-authored-by:`).
