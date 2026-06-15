---
name: 2026-06-13-remove-opentag-color-keywords
status: completed
created: 2026-06-13
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-13
result: Removed opentag_color_keywords user-override plumbing (setting, env var, seed, parser, UI, config fields, tests, docs); built-in DEFAULT_COLOR_KEYWORDS retained; 1075 backend + 83 frontend tests green.
---

# Task: Remove the OpenTag "Color word mappings" user-override feature entirely

The user-facing `opentag_color_keywords` override (Settings "Color word mappings (OpenTag
matcher)" section, the `OPENTAG_COLOR_KEYWORDS` env var, and its default seed) is being
**removed**. Rationale: the v2 matcher policy (CLAUDE.md) says marketing collapses like
`galaxy=black, cool=grey` are invalid and degrade multicolor matching, yet the new-install
default still seeds exactly those and the UI still teaches them. The built-in
`DEFAULT_COLOR_KEYWORDS` / `COLOR_SYNONYMS` map already covers true synonyms, so the
override adds only downside.

**KEEP** `DEFAULT_COLOR_KEYWORDS` and its alias `COLOR_SYNONYMS` in
`core/opentag_match.py` — they are the built-in synonym map the matcher relies on. Remove
only the **user-override plumbing** (setting, env var, seed, parser, Settings UI, config
GET/PUT field, docs).

## Before you start

- Read `CLAUDE.md` (commit/doc rules: doc edits ship in the SAME commit). Skim the OpenTag
  matcher section of `docs/opentag-matching.md`.
- The complete reference inventory is below — verify with your own grep
  (`grep -rn "opentag_color_keywords\|OPENTAG_COLOR_KEYWORDS\|parse_color_keywords_config\|Color word"`),
  then remove each. Do NOT remove `DEFAULT_COLOR_KEYWORDS` / `COLOR_SYNONYMS`.

## Working tree check

`git status --porcelain` first. Tree should be clean except unrelated dotfiles. If a file
this plan touches is dirty, list it and ask. This prompt file is exempt.

## What to do — remove every reference (keep DEFAULT_COLOR_KEYWORDS)

### Backend
1. `backend/app/models/config.py` (≈34-36): delete the `"opentag_color_keywords": ...`
   seed entry and its now-orphaned comment. (No migration needed — any value already
   stored in an existing install's BridgeConfig simply becomes dead/ignored once the read
   paths below are gone. Don't write a migration.)
2. `backend/app/config.py`: delete the `opentag_color_keywords: str = ""` field (≈72) and
   the entire `parsed_opentag_color_keywords` property (≈114-125).
3. `backend/app/core/opentag_match.py`: delete `parse_color_keywords_config` (≈317) and fix
   the comment block at ≈46 that references "the opentag_color_keywords setting / env var".
   KEEP `DEFAULT_COLOR_KEYWORDS` (≈53) and `COLOR_SYNONYMS` (≈66).
4. `backend/app/api/opentag.py` — TWO blocks (the matches endpoint ≈514-534 and the search
   endpoint ≈993-1020): these load BOTH `opentag_vendor_aliases` AND
   `opentag_color_keywords`. **Keep the vendor-alias loading intact.** Remove only the
   color-keyword parts: the `parse_color_keywords_config` import, the
   `get_config_value(_db, "opentag_color_keywords", ...)` reads, the `color_kw_raw`
   fallback, and the `color_map.update(parse_color_keywords_config(...))` merge. Replace
   with `color_map = dict(DEFAULT_COLOR_KEYWORDS)` (keep importing `DEFAULT_COLOR_KEYWORDS`).
5. `backend/app/api/config.py` (≈131): remove the `opentag_color_keywords=...` kwarg from
   the config response builder.
6. `backend/app/schemas/api.py` (≈288 and ≈326): remove the `opentag_color_keywords` field
   from BOTH the config GET response model and the update request model.

### Frontend
7. `frontend/src/api/types.ts` (≈265 and ≈297): remove `opentag_color_keywords` from both
   config interfaces.
8. `frontend/src/pages/Settings.tsx`: remove the "Color word mappings" section (≈1035-1050),
   the `colorKeywords` state (≈206), its dirty-check clause (≈266), the `vcolorkw` var
   (≈319), and the `opentag_color_keywords` field in the save payload (≈509). Make sure the
   surrounding dirty-check `||` chain and save object stay syntactically valid.
9. `frontend/src/pages/Settings.test.tsx` (≈89): remove the `opentag_color_keywords` mock
   field. Fix any other Settings.test assertions that reference the removed section.

### Docs (same commit)
10. `docs/configuration.md` (≈108 and ≈146): delete both `OPENTAG_COLOR_KEYWORDS` /
    `opentag_color_keywords` rows.
11. `CLAUDE.md` (≈249 and ≈281): delete the `OPENTAG_COLOR_KEYWORDS` env-var row and the
    `opentag_color_keywords` runtime-editable row.
12. `docs/opentag-matching.md` (≈208): update the sentence that references "The
    `opentag_color_keywords` env var / setting" so it no longer mentions the removed
    override (the built-in synonym map still exists; just drop the override mention).
13. `docs/decisions.md`: ADD a new dated entry (2026-06-13) recording the removal and why
    (marketing-collapse defaults contradicted v2 policy; built-in COLOR_SYNONYMS suffices).
    Leave the older historical entries as-is (they're dated history).

### Tests
14. `backend/tests/test_api.py` (≈63) and `backend/tests/test_auth.py`: remove/adjust any
    assertion on the `opentag_color_keywords` seed or config field.
15. `backend/tests/test_opentag.py` (≈5584, 5591): remove the `parse_color_keywords_config`
    unit tests. Remove any other test asserting the override merge behavior.

## Conventions to honor

- Surgical removal; don't touch the matcher's built-in synonym map or vendor-alias plumbing.
- **Full backend suite via throwaway venv** (sandbox skips `itsdangerous` tests otherwise):
  `python3 -m venv $TMPDIR/v && $TMPDIR/v/bin/pip install -q -r backend/requirements.txt &&
  cd backend && $TMPDIR/v/bin/pytest`. Confirm `test_api`/`test_opentag` ran (not skipped).
  Then `ruff check backend/`, and in `frontend/` `npx tsc --noEmit` + `npm test`. All green.
- Grep once more at the end for `opentag_color_keywords` / `parse_color_keywords_config` /
  `OPENTAG_COLOR_KEYWORDS` / "Color word" to confirm ZERO remaining references (outside
  `prompts/` and dated `docs/decisions.md` history).

## When done

1. Update frontmatter (`status`, `completed` 2026-06-13, `result`).
2. `git mv` this file to `prompts/done/` (or `prompts/failed/`).
3. (decisions.md entry already added in step 13.)
4. Propose ONE `chore:`-prefixed commit (file list + one-liner; ask y/n). On `y`, stage
   those specific paths and commit on `dev` (never `main`, never `git add -A`, never push,
   no `Co-authored-by:`).
