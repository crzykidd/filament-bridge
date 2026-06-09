---
name: 2026-06-08-wizard-opentag-fixes-batch
status: completed
created: 2026-06-08
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-08
result: P0 double-Silk + Master suffix + optTags-on-reuse; P1 resilient-409 + collision UI; P2 reprocess button, SM deeplink, 10 candidates, darker grey, top action bars, variances sort, vendor in spool rows, Settings pinned
---

# Task: Bulk Import Wizard + OpenTag Cleanup fixes batch (post-import-testing)

A batch of fixes found while testing the generic-container import against a live Filament DB.
Two are data-corrupting bugs (P0); one is a real UX gap around name collisions (P1); the rest
are UX polish (P2). Root causes and file/line pointers below were established in an Opus session
on 2026-06-08 — trust them but verify line numbers haven't drifted.

## Background — key facts you must know

- **Filament DB filament `name` is GLOBALLY UNIQUE** (a partial-unique-on-non-deleted Mongo index
  on `name`, NOT scoped by vendor). `POST /api/filaments` returns **409** via
  `handleDuplicateKeyError` on any active-name collision. This is the source of the import
  "bombing out on the second filament."
- **The name drives variant grouping.** `core/matcher.py:sm_variant_cluster_key` returns
  `(vendor, material, finish)`, all parsed from the Spoolman name via `extract_finish_line` /
  color-word detection. Messy names → wrong clusters → wrong container names → collisions. So
  fixing names and re-scanning is central to the workflow, and collisions frequently mean a
  variant was mis-grouped.
- The wizard ALREADY computes name collisions at preview: `data.name_collisions`
  (`NameCollisionEntry` in `frontend/src/api/types.ts` ~L458–464: `normalized_name`,
  `sm_filament_ids[]`, `vs_existing`, `intra_batch`, `existing_fdb_filament_id`). They are shown
  read-only in `StepNPreview.tsx` (~L103–136) and the per-record opt-out (`TriCheckbox` → action
  `skip`) already exists in `Step3Matches.tsx` (`MemberRow`, ~L149–277, decisions keyed by
  `spoolman_filament_id`). The gap is UX + execution resilience, not detection.

## Working tree check

Run `git status --porcelain` first. The repo root has pre-existing untracked dotfiles
(`.bashrc`, `.gitconfig`, `.idea`, `.mcp.json`, `.claude/*`, etc.) — IGNORE them, never stage
them. If any of the source files below are already dirty, list them and ask before editing.

---

## P0 — Generic container naming + Silk finish-tag bugs (backend)

Both in `backend/app/api/wizard.py`, generic-container path.

### P0.1 — Double finish word in the container name (e.g. "TTYT3d PLA Silk Silk")
`_container_display_name()` (~L153–178) composes `vendor + material + finish` but uses the RAW
`rep.material` (which already contains "Silk", e.g. material = "PLA Silk") and then ALSO appends
the extracted finish line → "PLA Silk Silk".
**Fix:** strip the finish words from the material before composing, using the existing helper
`strip_finish_words(material, tag_map)` from `core/material_tags.py` (planner.py already does this:
`base_type = strip_finish_words(material, tag_map)`). `_settings.parsed_material_tag_ids` is the
tag map; `_settings` is module-global in wizard.py. Result: "TTYT3d" + "PLA" + "Silk" =
"TTYT3d PLA Silk".

### P0.2 — Append a "Master" marker to the container name (decided)
After the clean `vendor + material + finish` name is built, append a marker so the container
never collides with its own color children. **Default marker: " Master"** → "TTYT3d PLA Silk
Master". (The collision feature in P1 lets the user override this per-cluster when it still
collides.) Keep the marker as a single named constant so it's easy to change. The children keep
their normal color names ("TTYT3d PLA Silk Red", …).

### P0.3 — Apply finish tags (optTags) when REUSING an existing container, not just on create
The create-new branch sets `container_payload["optTags"]` from the shared finish IDs. The
idempotent **reuse branch** (`if existing_fdb_parent_id:` ~L982–996) re-registers the mapping but
NEVER patches optTags — so containers created before the tag logic (or on any re-run) stay
untagged. **Fix:** in the reuse branch, compute the shared finish IDs the same way
(`set.intersection` of `finish_ids_from_text(m.name, m.material, tag_map)` across members) and, if
non-empty and the existing container is missing them, PATCH via
`await filamentdb.update_filament(container_fdb_id, {"optTags": sorted(shared_ids)})`
(method exists; it strips computed fields and PUTs `/api/filaments/:id`). Wrap in try/except +
log; don't abort the batch on failure. Fetch the existing container's current optTags (it's in
`fdb_by_id` / via the client) and merge rather than clobber if it already has unrelated tags.

Tests: extend `backend/tests/test_variant_parent_mode.py` — assert the container name is
"ELEGOO PLA Silk Master" (no double Silk) and that a re-run patches optTags onto a pre-existing
untagged container.

---

## P1 — Name-collision handling (backend + frontend)

Goal: collisions never silently 409 the batch; the user can resolve them by renaming the
container OR by going back to fix the variant grouping.

### P1.1 — Resilient execution (backend, non-negotiable)
In `_execute_spoolman_to_fdb`, wrap each `create_filament` (container AND child) so a 409 (httpx
`HTTPStatusError` with `response.status_code == 409`) is caught per-record: skip that record,
record a clear error on the result (e.g. `res.add(..., "error", detail="name collision: <name>")`)
and continue the batch. One colliding record must not fail all the others. Add a test.

### P1.2 — Surface collisions actionably at preview (frontend)
In `StepNPreview.tsx` the collision section (~L103–136) is read-only. Make each collision row
actionable:
- For a **container-name collision** (the synthesized "… Master" name already exists, or two
  clusters produced the same container name): show an **editable text field** pre-filled with the
  proposed container name so the user can disambiguate (e.g. append a diameter or free text →
  "TTYT3d PLA Silk Master 1.75"). Offer a one-click suggestion that appends the cluster's
  diameter when available. The chosen name must flow into execute (see P1.3).
- Provide a **"Fix variant mapping"** link/button on each collision that routes back to the
  Variances step (`StepVariances`) — collisions are often a mis-grouped variant.
- Keep the existing per-record **skip** opt-out (`Step3Matches` TriCheckbox) as the fallback, and
  show the collision warning near it.
Per the decision: do NOT silently auto-skip; warn clearly and let the user rename / refit / skip.

### P1.3 — Carry user-chosen container names into execute (backend + frontend)
The wizard needs to persist a per-cluster container-name override (keyed by cluster identity)
from the preview UI through to `_execute_spoolman_to_fdb`, which uses it instead of the generated
"… Master" name. Store it in the wizard decisions/config the same way other wizard decisions are
persisted (see how `wizard_match_decisions` / variant decisions are stored & read in
`api/wizard.py` and `core/planner.py`). Re-check uniqueness against FDB for the overridden name in
the preview response so the user gets immediate feedback.

This (P1.2/P1.3) is the most involved item — if scope forces a cut, the MUST-HAVES are P1.1
(resilient execute) + the editable container-name field + the "fix variant mapping" link. The
auto-diameter suggestion is nice-to-have.

---

## P2 — OpenTag Cleanup page (`frontend/src/pages/OpenTagCleanup.tsx`)

### P2.1 — "Reprocess records" button (re-scan Spoolman without refreshing the dataset)
Next to "Refresh dataset" (~L954–961, calls `handleRefresh` → `runLoad(false)` →
`/api/openprinttag/refresh`), add a sibling **"Reprocess records"** button that re-scans Spoolman
and recomputes matches against the CURRENT OpenTag dataset (no dataset re-download). This is for
iterating on Spoolman name cleanup. The matches fetch (`getOpenTagMatches` in `api/client.ts`
~L205, backend `GET` in `api/opentag.py`) already recomputes from Spoolman — wire the button to
re-invoke that path (a lighter reload than refresh). Confirm the matches endpoint does NOT force a
dataset re-fetch; if it does, add a query flag to skip it.

### P2.2 — Make the Spoolman filament id a clickable deep link
Replace the plain `<span className="text-xs text-gray-400">SM #{match.spoolman_filament_id}</span>`
(~L287) with the existing `<DeepLinks spoolmanFilamentId={match.spoolman_filament_id} />`
component (already imported ~L16; resolves the Spoolman base URL via `DeepLinkContext` →
`/api/health`; link format `${spoolmanUrl}/filament/show/{id}`, opens new tab).

### P2.3 — Show ~10 candidate matches instead of 5
Backend caps alternates at 5 when building `structured_candidates` (`api/opentag.py` ~L582–585;
the `alternates`/`alternate_scores` come from `core/opentag_match.py` — find the slice/top-N there
and raise to ~10). The dropdown render (~L299–314) shows `match.candidates` as-is, so raising the
backend cap is sufficient.

### P2.4 — Darken hard-to-read grey text
Across this page (and apply the same pass to other pages where the lightest greys are used for
real content, not just decoration): bump `text-gray-400` → `text-gray-600` (or `-700` for primary
content) and `text-gray-300` → `text-gray-500`. Known spots in OpenTagCleanup: ~L102, 287, 329,
347, 625, 631, 1140. Leave genuinely decorative elements (e.g. faint dividers) alone.

---

## P2 — Wizard UX

### P2.5 — Primary action button at BOTH top and bottom of each long step
Wizard steps are long. The primary action (Back / Rescan / Save & Next / Execute) currently lives
only at the bottom of each step (`Step3Matches` ~L644–661, `StepVariances` ~L1066–1075,
`StepNPreview` ~L256–263, plus `Step1/2/6`). Add the same primary action at the TOP of each step
too. Prefer a single shared footer/action component (or a small `<StepActions>` rendered at top
and bottom) over duplicating JSX per step. A sticky top action bar is acceptable if cleaner.

### P2.6 — Sort control on the Variances step (`StepVariances.tsx`)
Add a sort control (segmented buttons or dropdown) above the group/standalone sections
(~L480, ~L859, ~L975) to sort by **vendor/brand (A→Z)** or **material (A→Z)** (default: current
order). Apply consistently to the auto-groups, standalone, and manual-group sections.

### P2.7 — Show manufacturer/vendor in the planned-writes "spools" section
In `StepNPreview.tsx` `PlannedWritesList` (~L272–321), the spool planned-writes omit the
manufacturer, making it hard to tell what's being written. Add vendor/manufacturer to the display.
Check whether `PlannedWrite` (`api/types.ts` ~L501–507) / the backend response (`api/wizard.py`
planned-writes builder + `schemas/api.py` `PlannedWrite`) already carries vendor in `target_label`;
if not, add a `vendor`/`manufacturer` field to the backend `PlannedWrite` schema and populate it,
then render it on the spool rows.

---

## P2 — Navigation (`frontend/src/components/Layout.tsx`)

### P2.8 — Pin Settings to the bottom of the sidebar (decided)
Currently `NAV_ITEMS` (~L6–14) lists Settings 5th. Remove Settings from the main list and render
it pinned at the BOTTOM of the sidebar, visually separated (e.g. main nav in a `flex-1` block,
Settings in a bottom block with a top border). Final order: Dashboard, Synced Records, Conflicts,
Sync Log, Bulk Import Wizard, OpenTag Cleanup, ──, Settings.

---

## Conventions to honor

- Match existing component/structure/naming. Reuse `DeepLinks`, `strip_finish_words`,
  `finish_ids_from_text`, existing wizard decision-persistence patterns — don't reinvent.
- Backend tests alongside `backend/tests/test_variant_parent_mode.py` and `test_api.py`; run
  `cd backend && pytest` (use `python3 -m pytest` — `python` is not on PATH) and report results.
- Frontend: run `cd frontend && npm run build` and report. Keep TS types consistent.
- Docs ship in the SAME commit as code: update `CHANGELOG.md` `[Unreleased]`, and
  `docs/variant-parent-mode.md` for the "Master" naming + collision behavior.
- Commit prefixes: `fix:` for P0/P1 bug behavior, `feat:` for new UX (reprocess button, sort,
  collision rename UI, settings reposition). No `Co-authored-by:`. Branch `dev`, never `main`,
  never push.

## When done

1. Update this file's frontmatter (`status`, `completed`, `result`); `git mv` it into
   `prompts/done/` (or `prompts/failed/`).
2. Record non-obvious decisions in `docs/decisions.md` (Master naming, collision-rename flow,
   resilient-execute on 409).
3. DO NOT run `git commit` — leave all changes in the working tree and report back: the file
   list, proposed commit message(s) (you may propose splitting into a few focused commits:
   e.g. P0 Silk, P1 collisions, P2 UX), backend test results, and frontend build result. The
   human approves commits.
