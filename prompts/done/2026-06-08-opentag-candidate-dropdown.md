---
name: 2026-06-08-opentag-candidate-dropdown
status: completed
created: 2026-06-08
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-07
result: Added OpenTagCandidate model + candidates list to matches endpoint; per-filament dropdown in review UI selects candidate and resets field decisions; 3 new tests; 625 backend tests pass, frontend build clean.
---

# Task: OpenTag cleanup — pick from best + top-5 alternate matches (dropdown)

On the OpenTag Cleanup review, the user can only edit fields of the single best match. Let
them **choose a different candidate** (the matcher already computes alternates) — e.g. when
the best match's color is off, pick a closer sibling. Show the best match plus the top
alternates in a per-filament dropdown; selecting one swaps the whole per-field comparison to
that candidate.

## Current shape

`backend/app/api/opentag.py`: each `OpenTagFilamentMatch` has the BEST match's `opt_uuid/
opt_slug/opt_brand/opt_name/confidence/fields` plus `alternates: list[dict]` (raw OPTMaterial
dicts, no per-alternate fields/confidence). `find_best_match` returns
`{best, confidence, alternates}` where `alternates` drops the scores.

## What to do

### Backend
- `find_best_match` (`backend/app/core/opentag_match.py`): return alternates WITH their
  scores so each candidate can show its confidence (e.g. keep `alternates` as
  `list[dict]` but add a parallel `alternate_scores: list[float]`, or return
  `alternates: list[tuple[float, dict]]`). Keep the existing `best`/`confidence`.
- Matches endpoint: build a structured `candidates` list per filament — `candidates[0]` is
  the best, followed by up to 5 alternates. Each candidate is a new model
  `OpenTagCandidate { opt_uuid, opt_slug, opt_brand, opt_name, confidence,
  multicolor_mismatch, fields: list[OpenTagFieldRow] }`, where `fields` is built via
  `_build_field_rows(sm_fil, opt_to_spoolman_fields(candidate_material, tag_map))` for THAT
  candidate (so each carries its own Spoolman-vs-OpenTag comparison and its own slug/uuid).
  Compute `multicolor_mismatch` per candidate. Add `candidates: list[OpenTagCandidate]` to
  `OpenTagFilamentMatch`. Keep the existing top-level best fields (= candidates[0]) for
  backward-compat, or have the frontend read candidates[0] as the default.
- Exact-UUID matches: candidates = just the one (confidence 1.0); that's fine.

### Frontend (`frontend/src/pages/OpenTagCleanup.tsx` + types)
- Add `candidates` to the `OpenTagFilamentMatch` TS type (with the candidate shape).
- Per filament, track a selected-candidate index (default 0 = best). Render a **dropdown** in
  the card header listing each candidate as `"{opt_brand} · {opt_name}  ({confidence}%)"`
  with a small color swatch (from the candidate's color_hex field if present). The current
  100%/exact badge still applies to candidates[0].
- When the selected candidate changes: reset the per-field decisions for that filament to the
  selected candidate's `fields` (default OpenTag values), and use the selected candidate's
  `opt_slug`/`opt_uuid` for the apply decision (the FDB settings push) and the confirm list.
  The existing per-field edit / keep-mine / confirm / apply flow then operates on the
  selected candidate.
- The "ignore match" control stays per filament (ignores regardless of selected candidate).

## Verification

- `cd backend && pytest` — tests: the matches endpoint returns a `candidates` list (best
  first) where each candidate has its own `fields` + confidence + slug/uuid; alternates carry
  their real scores; an exact-UUID match yields a single candidate at 1.0.
- `cd frontend && npx tsc --noEmit && npm run build` — must pass.
- Reason through: a filament with a slightly-off best match shows a dropdown; selecting an
  alternate swaps the field rows (different color/name) and the apply then writes that
  candidate's values + identity.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md`: OpenTag cleanup lets the user pick from best + top-5 alternates;
   each candidate carries its own field comparison.
3. Non-interactive subagent run: when pytest + build pass, stage ONLY the files this task
   touched (incl. prompt move + docs) and commit on `dev` with one `feat:` message. Never
   `git add -A`. Never push.
