---
name: 2026-06-09-master-marker-parent-badge-collision-rename
status: completed
created: 2026-06-09
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-09
result: Configurable (Master) marker, Master/Parent badge, editable collision rename/skip — all four items shipped; 760 backend tests pass, frontend build clean.
---

# Task: Master marker config + parent badge + editable collision rename

Four related fixes to the generic-container wizard flow, found testing the Master containers.
Decisions are made — implement all four. Planned in an Opus session 2026-06-09; file/line
pointers were verified then (re-confirm if drifted).

## Working tree note
Repo root has pre-existing untracked dotfiles (`.bashrc`, `.gitconfig`, `.idea`, `.mcp.json`,
`.claude/*`, …) — IGNORE; never stage them. Run `git status --porcelain` first.

---

## 1 + 5 — Configurable container marker (default `(Master)`)

Today `backend/app/api/wizard.py:166` hardcodes `_CONTAINER_MASTER_SUFFIX = " Master"`, appended in
`_container_display_name()` (~L203) so containers are e.g. "ELEGOO PLA Master".

Change both the format and make it user-configurable:

- **New runtime setting `container_parent_marker`** (string). DEFAULT = `"(Master)"` (parentheses
  visually separate it — that's the point of #1). Empty string = NO marker. Wire it the same way as
  other BridgeConfig settings: env `CONTAINER_PARENT_MARKER`, `BridgeConfig` override, `_DEFAULTS`,
  `ConfigResponse`/`ConfigUpdateRequest` schemas, `_config_response()`, frontend `api/types.ts`.
- `_container_display_name()` appends `" " + marker` only when marker is non-empty, so
  "ELEGOO PLA" + "(Master)" → "ELEGOO PLA (Master)"; empty marker → "ELEGOO PLA". Read the marker
  from the DB config (the execute path already loads config; pass it through like
  `variant_parent_mode` is).
- **Settings UI (`frontend/src/pages/Settings.tsx`), inside the Variant parent mode section, shown
  only when `generic_container` is selected:**
  - A checkbox "Append a marker to container parent names" — checked when the marker is non-empty.
  - When checked, a text box for the marker, defaulting to `(Master)`. Unchecking clears the marker
    (containers get no suffix).
  - Short helper text: the marker keeps container names from colliding with their color variants;
    on a name collision you can still rename or skip per-record at Preview (see item 4).
- Note in the implementation: changing the marker means existing containers created under the old
  marker won't be found by the idempotent lookup and a re-run would try to create the new name —
  that's acceptable (collision handling in item 4 + resilient 409 already cover it). Mention it in
  the decisions log; don't try to migrate old names.

Tests: update the existing container-name assertions in
`backend/tests/test_variant_parent_mode.py` to expect `(Master)`; add a test that an empty marker
yields no suffix.

---

## 2 — Show synthetic container parents as "Master / Parent", not "Unmatched (FDB)"

In the wizard Match step, FDB filaments with no Spoolman match render as **"Unmatched (FDB)"**
(`frontend/src/pages/Wizard/Step3Matches.tsx`: `RowStatus` includes `unmatched_fdb`, labels ~L32-33,
rows built ~L342). The synthetic container parents (e.g. "ELEGOO PLA Master") are bridge-owned and
have no Spoolman counterpart BY DESIGN, so showing them as "Unmatched (FDB)" is misleading (see the
attached screenshot in the conversation — four "… Master" rows all flagged Unmatched (FDB)).

- **Backend:** when building the unmatched-FDB list (`_fdb_ref` / `unmatched_filamentdb` in
  `backend/app/api/wizard.py` ~L321; the matcher already knows parents — see ~L585
  `if f.id in _parent_ids or f.hasVariants`), add a flag to the FDB ref indicating the row is a
  master/parent container. Detect via: a `FilamentMapping` with `is_synthetic_parent=True` for that
  `filamentdb_id`, OR `hasVariants` true (a parent), OR the name ending in the configured marker.
  Prefer the `is_synthetic_parent` mapping as the authoritative signal, with `hasVariants` as a
  fallback for parents the bridge didn't create.
- **Frontend:** add a new status (e.g. `master_fdb`) or an `isMaster` flag on the row; render a
  distinct badge "Master Filament" (or "Parent") with its own (non-alarming) styling instead of the
  blue "Unmatched (FDB)" pill. These rows are informational — they should NOT count toward any
  "unmatched needs action" totals and should not offer skip/link actions that imply they're
  orphans. Keep them visible (the user wants to see them) but clearly labeled as parents.

---

## 4 — Editable rename (or skip) on name collision at Preview

This is the previously-deferred P1.3. At Preview, `name_collisions` are already computed
(`NameCollisionEntry`: `normalized_name`, `sm_filament_ids[]`, `vs_existing`, `intra_batch`,
`existing_fdb_filament_id`) and shown read-only with a "Fix variant mapping" link in
`frontend/src/pages/Wizard/StepNPreview.tsx`. Make collisions resolvable inline:

- For a **container-name collision** (the proposed "… (Master)" name already exists in FDB, or two
  clusters produced the same container name), render an **editable text box** pre-filled with the
  proposed container name so the user can disambiguate (e.g. "ELEGOO PLA (Master) 1.75"), PLUS a
  **Skip this record** control. Keep the existing "Fix variant mapping" link too.
- The chosen container-name override (or skip) must persist into execute. Add a per-cluster
  container-name override to the wizard decisions/config (mirror how `variant_parent_mode` /
  container lookups are persisted and read in `api/wizard.py`), and have `_execute_spoolman_to_fdb`
  use the override instead of the generated name. Re-check the overridden name's uniqueness against
  FDB in the preview response so the user gets immediate feedback (still-colliding → keep warning).
- This rename/skip path must work **regardless of the marker setting** (item 1/5): if the user
  turned the marker OFF and a bare "ELEGOO PLA" collides, the same editable-name / skip UI appears.
- Resilient execute (409 → skip+log, never abort the batch) already exists — keep it as the
  backstop for any collision that slips through.

Tests: a container-name collision yields an editable override that flows to execute and is used;
skip on a collision omits that record; empty marker + collision still surfaces the rename/skip UI.

---

## Conventions / tests / done

- Backend tests: `cd backend && python3 -m pytest` (use `python3`). Frontend:
  `cd frontend && npm run build`. Report both.
- Update `CHANGELOG.md` `[Unreleased]`, `CLAUDE.md` (env-var + runtime-settings tables for
  `container_parent_marker` / `CONTAINER_PARENT_MARKER`), and `docs/variant-parent-mode.md`
  (the `(Master)` marker + configurability + collision rename). Docs in the same commit as code.
- Commit prefixes: `fix:` for the marker format + parent-badge + collision behavior, `feat:` for the
  marker setting + editable-rename UI. No `Co-authored-by:`. Branch `dev`, never `main`, never push.
- When done: frontmatter → completed; `git mv` to `prompts/done/`; record decisions in
  `docs/decisions.md`. DO NOT `git commit` — leave changes in the working tree and report back:
  file list, proposed commit message(s), backend test results, frontend build result, and anything
  deferred/uncertain. (The orchestrator will verify and commit.)
