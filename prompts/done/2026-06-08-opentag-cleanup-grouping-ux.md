---
name: 2026-06-08-opentag-cleanup-grouping-ux
status: completed        # pending | completed | failed
created: 2026-06-08
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-07
result: no_match_reason on backend + TS type + UI display; sort-by-SM-id; group collapse (default all collapsed) with Expand/Collapse all, header summaries; group-level ignore-all; 651 pytest + clean build
---

# Task: OpenTag cleanup — group collapse/expand + group-level ignore + sort-by-SM-id + no-match reasons

UX improvements to the OpenTag Cleanup page (`frontend/src/pages/OpenTagCleanup.tsx`) plus a
small backend addition for no-match reasons (`backend/app/api/opentag.py`).

## 1. Backend — no-match reason

- Add `no_match_reason: str | None = None` to `OpenTagFilamentMatch`.
- In the matches endpoint's no-match branch (where it appends a match with `opt_uuid=None`,
  `confidence=0`, empty fields), compute a human reason:
  - `sm_brand_key` (after `resolve_opentag_brand`) NOT in `materials_by_brand` →
    `f'Manufacturer "{sm_vendor}" not found in OpenTag (add a mapping in Settings)'`.
  - brand found but the material/family-filtered candidate list is empty →
    `f'No {sm_material or "matching"} match for {sm_vendor} in OpenTag'`.
  - candidates existed but the SM filament is multicolor with no compatible arrangement
    (`multicolor_mismatch`) → `'Spoolman is multicolor; no multicolor OpenTag match'`.
  - otherwise (candidates existed but best score below threshold) →
    `f'No confident match (best {round(best_conf*100)}%)'`.
  Set `no_match_reason` on that match. (Matched rows leave it None.)

## 2. Frontend — sort by Spoolman ID

- Add `'spoolman_id'` to the `SortBy` union + the sort `<select>` + `sortLabel`
  ("Spoolman ID (low→high)"). In `sortMatches`, sort ascending by
  `a.spoolman_filament_id - b.spoolman_filament_id`.

## 3. Frontend — group collapse/expand (default collapsed) with summaries

- Track per-group collapsed state keyed by group key (default: ALL collapsed).
- Add **"Expand all" / "Collapse all"** buttons near the group/sort controls.
- Each group header is clickable to toggle, with a ▸/▾ caret, and shows a **summary** of its
  members so matches are visible while collapsed, e.g.:
  `AMOLEN  ·  8 matched · 2 no-match · 3 tagged  (12)`
  - matched = members with a real match (`opt_uuid` non-null / `confidence > 0`)
  - no-match = `opt_uuid == null`
  - tagged = members whose Spoolman record already has an `openprinttag_uuid`
    (reuse the existing badge's `existingUuid` logic; if easily shared, factor it out).
  When collapsed, render only the header (not the member cards).

## 4. Frontend — group-level ignore

- On each group header add an **"Ignore all" / "Unignore all"** toggle that adds/removes every
  member's `spoolman_filament_id` to/from `ignoredIds` (the existing per-filament ignore set).
  Label reflects whether all members are currently ignored. Don't toggle collapse when this
  button is clicked (`stopPropagation`).

## 5. Frontend — show the no-match reason

- Add `no_match_reason?: string | null` to the `OpenTagFilamentMatch` TS type.
- In the no-match card body (currently "No confident match found — ignore or select an
  alternate below."), show `match.no_match_reason` when present (fall back to the existing
  text). Keep it readable/muted.

## Verification

- `cd backend && pytest` — tests: the matches endpoint sets `no_match_reason` correctly for
  (a) a vendor with no OpenTag brand ("Manufacturer … not found"), (b) a brand with no
  material match, (c) a low-confidence case; matched rows have `no_match_reason is None`.
- `cd frontend && npx tsc --noEmit && npm run build`.
- Reason through: page loads with all groups collapsed, each header showing
  matched/no-match/tagged counts; expand/collapse-all works; group "ignore all" toggles every
  member; sort-by-SM-id orders ascending; unmatched cards show a specific reason.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md` only if non-obvious (no-match reason taxonomy is worth a line).
3. Non-interactive subagent run: when pytest + build pass, stage ONLY the files this task
   touched (incl. prompt move + docs) and commit on `dev` with one `feat:` message. Never
   `git add -A`. Never push.
