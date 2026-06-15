---
name: 2026-06-08-docs-changelog-decisions
status: done
created: 2026-06-08
model: sonnet
completed: 2026-06-08
result: Added 8 Added/4 Changed/6 Fixed CHANGELOG entries and 7 decision records; pathspec-scoped docs: commit.
---

# Task: Bring CHANGELOG [Unreleased] + docs/decisions.md current with today's work

Documentation-only. Touch ONLY `CHANGELOG.md` and `docs/decisions.md` (+ prompt move). ONE
`docs:` commit. A parallel agent edits README/configuration and CLAUDE.md/prd — do NOT touch those.

## A. CHANGELOG.md — add to `[Unreleased]` (keep under [Unreleased], don't roll to a version)

Add these (verify each isn't already present; merge into the existing Added/Changed/Fixed lists,
collapse duplicates):

Added: pre-write backup safeguard dialog gating Wizard Execute / OpenTag Apply / Enable
auto-sync (one-click Spoolman backup + one-click Filament DB backup via `GET /api/snapshot` to
`DATA_DIR/backups/`); OpenTag secondary-colors recovery from the raw OpenPrintTag tarball +
multicolor-mismatch badge; Scheduler & Logs settings (runtime sync interval + sync-log
retention + Sync Log windows view & clear-log); Bulk Import Wizard (re-runnable rename) +
"Never import empties" setting; Debug mode + reset tools (clear Spoolman FDB refs; reset bridge
local state); browser-local timestamps; Synced Records hide-empty + multicolor swatch +
conflict deep-link + empty-state; wizard OPT badge + tagged-only / hide-matched / hide-tagged
filters.

Changed: Conflicts page rework (collapsible rows, sort, expand-all, resolve clarity, multicolor
color); ongoing source-of-truth removed from the wizard (Settings owns sync direction +
conflict policy); standard `docker-compose.yml` is bridge-only (full stack → `docker-compose.dev.yml`);
container runs non-root 1000:1000 via entrypoint chown+gosu (PUID/PGID).

Fixed: `multi_color_direction` always sent with `multi_color_hexes` (completes the multicolor
422 trio); new_spool conflict dedup + auto-resolve on map; wizard pre-matches by `filamentdb_id`
cross-reference; readonly-DB crash on a root-owned volume (entrypoint self-heals); OpenTag
color-name tokenization (Green/Purple); all backend ruff lint errors (74→0).

(A complete draft is in the session audit — adapt freely, but verify against
`git log --since="2026-06-07 00:00" --oneline`.)

## B. docs/decisions.md — add the missing decisions

decisions.md is mostly complete; add SHORT entries (1-2 lines each) for these that are missing
(check first — don't duplicate):
- Browser-local timestamp rendering (`frontend/src/utils/datetime.ts`; naive-UTC strings get a
  `Z` appended before `toLocaleString`). (`d22cad8`)
- Conflicts page rework + `ColorDisplay` component + `_conflict_identity` returning
  multi_color fields; new_spool conflicts labelled "Dismiss". (`eb9af66`)
- Sync-log windows (`?windows=N` = most recent N cycle_ids) + `DELETE /sync-log`. (`7b0361e`)
- Synced Records enrichment (MappingRow gains multi_color/remaining_weight/is_empty/conflict_id;
  hide-empty + conflict deep-link). (`a870950`)
- Wizard OpenPrintTag flag/filter/badge (FilamentRef.openprinttag from the SM openprinttag_uuid
  extra). (`db8a4c6`, `4b5db3f`)
- OPT stamped badge (grey in-sync / orange drifted) on OpenTag Cleanup cards. (`7eb5e98`)
- PLA+/grade modeling: base polymer type + grade-in-name per OpenTag spec; deliberately NO
  material guard preserving the literal "PLA+" (matcher still maps PLA/PLA+ → pla for matching).

## Verification

- No code touched. `git diff --stat` shows only CHANGELOG.md + docs/decisions.md (+ prompt move).

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. Pathspec-scoped commit of ONLY those two files + prompt move, `docs:` message. Retry once on
   index lock. Never `git add -A`. Never push.
