---
name: 2026-06-04-variant-keywords-config-standalone-move
status: completed
created: 2026-06-04
model: sonnet            # opus planned this; sonnet implements
completed: 2026-06-04
result: >
  Part 1: VARIANT_LINE_KEYWORDS env var + Settings runtime override fully wired.
  matcher.py extract_finish_line/sm_variant_cluster_key accept keywords param (None=legacy fallback).
  wizard.py _resolve_variant_keywords threads through both wizard_variances and wizard_variants.
  ConfigResponse/ConfigUpdateRequest + types.ts/client.ts updated. Settings.tsx editor added.
  Part 2: Standalone rows now have "Move to…" dropdown (movingStandaloneId state +
  standaloneTargetOptions + moveFromStandalone). handleSave required no changes.
  246 backend tests pass, TypeScript clean.
---

# Task: Make the variant finish-keyword lexicon a user setting + add "Move to" on Standalone rows

Two follow-ups to the shipped finish-line auto-split (commit `81950f5`):

1. **The finish/variant keyword list is hardcoded** in `matcher.py` (`_FINISH_PATTERNS`,
   regex per token: matte/silk/cf/glow/…). Real libraries have line keywords it doesn't know
   — e.g. ELEGOO **"Rapid"** is a distinct print profile but isn't in the list, so Rapid
   colors wrongly cluster with standard ones. The keyword list must be a **user-editable
   setting** (the user's words: "variant matchings separated by a `,`").
2. **Standalone filaments have no "Move to" action.** Grouped members (auto + extra) got a
   "Move to…" dropdown in `81950f5`, but a Standalone row can only be multi-selected into a
   *new* group ("Group as variants"). It should also be able to **move directly into an
   existing group**, symmetric with the in-group control.

## Before you start

- Read the `docs/decisions.md` entries for **2026-06-04 — Wizard variant-resolution
  redesign** and the per-member-actions / finish-split decision (commit `81950f5`), and
  `docs/wizard-redesign.md` (Q1). Read `CLAUDE.md` (env-var table + hard rules).
- Read the shipped code:
  - `backend/app/core/matcher.py` — `_FINISH_PATTERNS` (~L102), `extract_finish_line`
    (~L131), `sm_variant_cluster_key` (uses `extract_finish_line`). These are **pure
    functions** — they can't read the DB, so the keyword list must be passed in as a param.
  - `backend/app/api/wizard.py` — every caller of `sm_variant_cluster_key` /
    `extract_finish_line` (`wizard_variances`, the legacy `wizard_variants` SM branch, the
    existing-FDB-parent map, `_compute_variant_groups`). These resolve config → pass the
    keyword list into the matcher.
  - `backend/app/config.py` — `Settings`; note the comma-separated `field_mappings` /
    `field_mapping_excludes` precedent (the pattern to copy).
  - `backend/app/api/config.py` — `get_config_value` / `set_config_value`, `GET`/`PUT
    /config`, `ConfigResponse` / `ConfigUpdateRequest`.
  - `frontend/src/pages/Settings.tsx` — runtime-config editor.
  - `frontend/src/pages/Wizard/StepVariances.tsx` — move helpers (`buildMoveOptions`/`moveTo`
    ~L340, the in-group "Move to…" dropdowns ~L503/L680, `makeStandaloneFrom*`), and the
    Standalone render (`effectiveUngrouped.map` ~L582 with its `selectedForGrouping` checkbox
    + `createGroupFromSelected`).
  - `frontend/src/api/types.ts` + `client.ts`.

## Working tree check

Run `git status --porcelain`; cross-reference the files below. If any are dirty, list them
and ask. Surface unrelated dirty files once; don't block. This prompt is exempt.

## What to do

### Part 1 — Variant finish keywords as a user setting

1. **Env default.** Add `variant_line_keywords: str = "<seed>"` to `Settings`
   (`config.py`), comma-separated, following the `field_mappings` precedent. Seed it with the
   tokens currently in `_FINISH_PATTERNS` so behavior is preserved (silk, matte, satin,
   carbon, cf, glow, wood, marble, metal, metallic, high-speed, hs, dual, tri, rainbow,
   multicolor, …) **plus `rapid`**. Document the new env var in `CLAUDE.md`'s env table
   (same commit).
2. **Runtime override.** Resolve the effective list as
   `get_config_value(db, "variant_line_keywords", settings.variant_line_keywords)` so the UI
   can override the env default without a restart (BridgeConfig wins). Parse to a normalized
   `list[str]` (trim, lowercase, drop empties, de-dupe).
3. **Thread it into the matcher.** Change `extract_finish_line(name, material, keywords)` and
   `sm_variant_cluster_key(sm, keywords)` to take the keyword list as a parameter and match
   on whole-word, case-insensitive membership; the finish token is the matched keyword
   (lowercased). Replace the hardcoded `_FINISH_PATTERNS` with keyword-driven matching (keep
   word-boundary semantics). Update every caller in `wizard.py` to pass the resolved list.
   Keep matcher functions pure (no DB import).
4. **Expose + edit in UI.** Surface `variant_line_keywords` in `ConfigResponse` and accept it
   in `ConfigUpdateRequest`; add an editor field to `Settings.tsx` (a text input for the
   comma-separated list, with a short helper: "Words that mark a distinct variant line, e.g.
   `silk, matte, rapid`. Filaments whose names contain different keywords won't be grouped
   together."). Update `types.ts` / `client.ts`.
5. **Optional nicety (only if cheap):** an inline "edit variant keywords" link on the
   Variances step header that deep-links to Settings — the user feels the pain there. Skip if
   it complicates state; the Settings page is the required home.

### Part 2 — "Move to existing group" on Standalone rows

6. Add a **"Move to…"** control to each Standalone row (`effectiveUngrouped.map`, ~L582)
   that lists every existing group (auto + extra) and moves the filament into the chosen
   group's membership — reuse `buildMoveOptions` / `moveTo` and the auto/extra membership
   maps rather than writing a parallel path. Keep the existing multi-select "Group as
   variants" (new-group creation) intact; the two coexist (move = into existing, multi-select
   = new group).
7. After a move, the row leaves Standalone and appears under the target group with a sensible
   default (non-master) and its own tare carried over. Ensure `handleSave` already covers it
   (membership-driven) — verify nothing special is needed.

### Verify

8. `cd backend && ruff check . && pytest`. Add/adjust tests: `extract_finish_line` with a
   custom keyword list (e.g. `rapid` splits ELEGOO Rapid from standard; empty list →
   everything "standard"); config override beats env default; `sm_variant_cluster_key`
   threads the list. Frontend: `cd frontend && npm test` and `npx tsc --noEmit`.
9. If practical, drive the live flow (`verify` / running app): set keywords to include
   `rapid` in Settings, confirm ELEGOO Rapid colors split into their own group; confirm a
   Standalone filament can be moved into an existing group.

## Conventions to honor

- Copy the `field_mappings` env+config pattern; don't invent a new config mechanism. New
  schema fields get defaults (Pydantic v2) so the contract stays backward compatible.
- Keep matcher functions pure; the DB/config resolution stays in the API layer.
- Never modify/delete upstream records. Clusters/keywords remain hints; the GUI decision is
  authoritative.
- Doc updates (CLAUDE.md env table, decisions) ship in the **same commit** as code. Commit on
  `dev`, Conventional-Commits (`feat:`), no `Co-authored-by:`. Never `--no-verify`. Never
  push to `main`.

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/` (failure).
3. In `docs/decisions.md`, record: `variant_line_keywords` becomes user-configurable
   (env default + runtime override, comma-separated, default seed incl. `rapid`), and
   Standalone rows gain "Move to existing group".
4. Propose ONE commit covering the modified files (incl. the prompt move + docs). Present the
   file list + a one-line `feat:` message; ask `commit these as "<message>"? (y/n)`. On `y`,
   stage those specific paths and commit on `dev`. Never `git add -A`. Never push.
</content>
