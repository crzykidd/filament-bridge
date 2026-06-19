---
name: 2026-06-18-opentag-inline-unmatch-rematch
status: done
created: 2026-06-18
model: opus              # PLAN first (backend un-bypass + scoped FDB settings removal); then implement
completed: 2026-06-18
result: >
  Implemented inline unmatch + change-match on the OpenTag match page. Un-bypassed
  alternates for tagged rows (exact-UUID match stays pinned at index 0; gate pipeline +
  find_best_match(top_n=10) now also run, returning [current]+alternates) via a shared
  _gated_candidates_for helper — no scorer changes. Added FilamentDBClient
  .remove_filament_settings_keys() (scoped removal exception, mirror of merge_filament_settings;
  deletes only the two OpenTag keys, idempotent). Added SpoolmanClient.get_filament(id). Added
  _clear_opentag_identity + _resolve_fdb_filament_id helpers, a clear_identity flag on
  OpenTagFilamentDecision (handled in the Apply loop → status "cleared"), and a standalone
  POST /api/openprinttag/clear/{id} endpoint. Frontend: blank "— unmatch —" dropdown option
  (sentinel idx -1, shown only for tagged rows) that stages a clear_identity decision applied
  via the existing Apply flow; ConfirmStep renders it as a single "clear OpenTag identity" row.
  openprinttag_ignore is left untouched; FDB removal is best-effort, SM blank authoritative;
  logged exception/upstream text scrubbed via core/log_safe.scrub. Docs updated
  (opentag-cleanup.md, spoolman-writes.md, CHANGELOG [Unreleased], decisions.md). All four
  checks green: backend pytest 1130 passed + ruff clean; frontend tsc clean + 84 tests passed.
  7 new backend tests added. Apply-vs-immediate = integrated into Apply (recommended choice).
---

# Task: Inline unmatch + change-match on the OpenTag match page

Let the user re-point or clear an already-applied OpenTag match directly from the match row,
via the candidate dropdown — current match preselected, the ~10 likely alternates listed, and
a blank **"— unmatch —"** option that clears the OpenTag identity. This closes the
"no way to clear/untag in-app" gap (today you must edit Spoolman extras by hand or use the
debug bulk-clear). Depends on `2026-06-18-opentag-cleanup-landing-toolbar`.

## Decisions already made with the user

- The matched-row dropdown (already shown for any candidate after the recent `>= 1` gate fix)
  becomes the single control for both **change-match** and **unmatch**:
  current selected + up to 10 alternates + a blank option whose meaning is "no match / untag".
- "Unmatch" = **clear the OpenTag identity** (blank `openprinttag_slug` + `openprinttag_uuid`
  on the Spoolman filament) **and** remove those two keys from the Filament DB `settings{}`
  bag. The FDB-side removal is an APPROVED scoped exception to the "never remove from
  `settings{}`" rule (same scope as the existing `merge_filament_settings` write path —
  see `CLAUDE.md` "What NOT to do").

## Verified facts (from investigation — don't re-derive)

- **Tagged rows currently have no alternates.** The exact-UUID bypass at
  `backend/app/api/opentag.py:576-601` sets `alternates=[]`, `candidates=[best_candidate]`, and
  `continue`s before any fuzzy scoring. So the dropdown has nothing to offer for a tagged row
  until this is un-bypassed.
- **To get alternates for a tagged row**, after pinning the exact-UUID match as `best`, run the
  same gated pipeline the untagged branch uses (`opentag.py:605-653`): `resolve_opentag_brand`
  → `materials_by_brand` → `color_profile_compatible_soft` gate → `families_gate_compatible`
  gate → `find_best_match(sm, materials, …, top_n=10, …)` (`backend/app/core/opentag_match.py:1115-1125`,
  returns `alternates` + `alternate_scores`), then build
  `structured_candidates = [best_candidate] + _build_candidate(...)` per alternate (mirror
  `opentag.py:708-710`). No scorer changes — only un-bypass the alternate computation.
- **Tagged-state resolution** is by UUID via the `by_uuid` index (`opentag.py:546-552`,
  read at `:571,576`); `openprinttag_slug` is written but never read for lookup.
- **Apply can't clear identity today**: `_build_sm_patch` skips `value is None`
  (`opentag.py:342`) and only writes non-empty slug/uuid (`:361-374`). The debug bulk-clear
  (`POST /api/debug/clear-spoolman-...` / the opentag-ids clear) already does the Spoolman-side
  blanking — reuse that logic for the SM side of a single-filament clear.
- Frontend dropdown is at `frontend/src/pages/OpenTagCleanup.tsx` (the `<select>` gated by
  `hasCandidates`, now `>= 1`); `onCandidateChange` / `onSearchSelect` plumbing already exists.

## What to do (after the Step-0 plan)

### Backend
1. **Un-bypass alternates for tagged rows** (`opentag.py:576-601`): keep the exact-UUID match
   as `best`/preselected, but also compute + return top-N alternates via the gate pipeline +
   `find_best_match`. The matched row's `candidates` becomes `[current] + alternates`.
2. **Clear-identity endpoint** — e.g. `POST /api/openprinttag/clear/{spoolman_filament_id}`:
   - PATCH the Spoolman filament `extra` to blank `openprinttag_slug` + `openprinttag_uuid`
     (reuse the debug clear logic; Spoolman PATCH, not the apply path).
   - Remove the two OpenTag keys from the FDB filament `settings{}` bag — add a scoped
     **removal** capability alongside `FilamentDBClient.merge_filament_settings()` (read-
     modify-write, delete ONLY `openprinttag_slug`/`openprinttag_uuid`, preserve all other
     keys, idempotent). This is the approved scoped exception.
   - Sanitize any logged upstream/exception text via `core/log_safe.scrub` (CWE-117).

### Frontend (`OpenTagCleanup.tsx`)
3. Add a blank **"— unmatch (no match) —"** option to the candidate `<select>` (top or bottom;
   value sentinel like `-1`/`""`). Current match stays preselected for tagged rows.
4. On selecting an **alternate** → existing re-match path (stage/apply writes the new slug/uuid).
   On selecting **blank** → unmatch: call the clear-identity endpoint and reflect the row as
   untagged. **Decide in the plan** whether blank clears immediately (with a small confirm) or
   stages an "unmatch" decision applied at the existing Apply step — recommend integrating into
   the **Apply** flow for consistency with the rest of the page (one apply action; the apply
   path calls the clear endpoint for unmatch decisions).

## Edge cases
- Untagged rows: blank option is a no-op (already no identity) — only show/clear meaningfully
  for rows that have an applied identity.
- A row whose brand has only one dataset entry (e.g. TTYT3D): dropdown = [current] + blank
  only (no alternates) — that's correct.
- Don't clear `openprinttag_ignore` as part of unmatch (separate concern) unless you justify it.

## Before you start
- Read `docs/opentag-cleanup.md`, `docs/spoolman-writes.md`, `docs/decisions.md` (the
  `merge_filament_settings` scoped-exception entry), `CLAUDE.md` "What NOT to do",
  `backend/app/api/opentag.py`, `backend/app/api/debug.py` (the existing clear), and
  `backend/app/services/filamentdb.py` (`merge_filament_settings`).

## Working tree check
`git status --porcelain`; build on the landing-toolbar change. List anything unexpected, ask.

## Step 0 — PLAN (required; backend un-bypass + scoped FDB removal + apply-vs-immediate)
State: the un-bypass approach, the clear endpoint shape, the FDB `settings{}` removal method,
the blank-option apply-vs-immediate choice, and the test matrix. Confirm ambiguities first.

## Tests
- Tagged filament's matches row returns `[current] + N alternates` (un-bypass works).
- Clear-identity endpoint blanks SM slug/uuid AND removes only those two keys from FDB
  `settings{}` (other keys preserved); idempotent on a second call.
- Selecting blank → identity cleared, row reads untagged, next match cycle re-evaluates it.
- Selecting an alternate → re-match writes the new slug/uuid.
- Backend `pytest` + `ruff check .`; frontend `npx tsc --noEmit` + `npm test`. All green.

## Conventions to honor
- Reuse the debug clear logic + `merge_filament_settings` pattern; one canonical scoped
  settings path. Doc updates ship in the SAME commit (`docs/opentag-cleanup.md`,
  `docs/spoolman-writes.md` — now clears identity, `CHANGELOG.md` `[Unreleased]`, decision in
  `docs/decisions.md`). Conventional-commits `feat:`. No `Co-authored-by:`. Branch `dev`,
  never `main`, never push.

## When done
1. Frontmatter (`status`/`completed`/`result`); `git mv` to `prompts/done/`.
2. Decision logged in `docs/decisions.md`.
3. Propose ONE commit (specific paths, never `git add -A`); present list + one-liner; STOP.
   Never push. Separate commit from the other two OpenTag prompts.
