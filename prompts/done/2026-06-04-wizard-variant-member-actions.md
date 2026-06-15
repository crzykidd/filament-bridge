---
name: 2026-06-04-wizard-variant-member-actions
status: completed
created: 2026-06-04
model: sonnet            # opus planned this; sonnet implements
completed: 2026-06-04
result: >
  Part A and Part B implemented in full. matcher.py: extract_finish_line() + 3-tuple
  sm_variant_cluster_key. wizard.py: 3-tuple clusters, POST /wizard/matches/{id}/skip.
  schemas/api.py: VariancesGroupRow.finish. StepVariances.tsx: per-member Move-to/Standalone/Ignore
  actions; finish badge on group header; Ignore on standalone and extra-group rows; ignoreErr display.
  client.ts: postWizardMatchSkip. types.ts: VariancesGroupRow.finish. Tests: 29 new assertions in
  test_matcher.py (TestExtractFinishLine + TestSmVariantClusterKey) + 3 new tests in test_api.py
  (skip endpoint). 2 stale tests updated for 3-tuple. All 237 pass; tsc --noEmit clean.
  docs/decisions.md: Part A/B entry + D1 note updated. docs/wizard-redesign.md: Q1 marked resolved.
---

# Task: Variances step — per-member actions (move / standalone / ignore) + auto-split groups by finish line

Follow-up to the shipped D1–D4 redesign (commit `5fff500`). The `vendor+material` grouping
key (D1) correctly clusters same-line colors, but it **over-clusters across finish lines**:
Buddy brand "Silk <color>" ×2 + a non-silk "<color>" all land in ONE group, because Silk
vs non-Silk share the same `material` ("PLA") and the same print settings — so D2's
`suggest_exclude` (which only fires on `sm_prop_conflicts`) never flags them. The only
current escape is the cramped always-checked checkbox at `StepVariances.tsx:382` (remove →
standalone), which is undiscoverable and can't express "these two Silks are their OWN
group" or "skip this one entirely."

This task adds first-class per-member control (the user's explicit ask) **and** auto-splits
clusters by finish line so the common case needs no manual fixing. This is the deferred
**Q1 (line separation)** from `docs/wizard-redesign.md`.

## Before you start

- Read `docs/wizard-redesign.md` (Q1 is what this resolves) and the `docs/decisions.md`
  entry **"2026-06-04 — Wizard variant-resolution redesign"** (D1–D4 contract — do not
  break it). Read `CLAUDE.md` variant model + the hard rules (never auto-resolve conflicts,
  never delete, map-not-copy).
- Read the shipped code you'll extend:
  - `frontend/src/pages/Wizard/StepVariances.tsx` — the SM branch `SMVariancesStep`. Key
    state: `groupMembership`, `masters`, `attachDecision`, `extraGroupMemberships` /
    `extraMasters` / `selectedForGrouping` (manual grouping), `effectiveUngrouped`,
    `toggleMember`, `createGroupFromSelected`, `handleSave` (builds `SMVariantDecision[]`).
  - `backend/app/core/matcher.py` — `sm_variant_cluster_key` (now `(vendor, material)`),
    plus normalize helpers and the existing color-word lexicon `strip_color_and_words`.
  - `backend/app/api/wizard.py` — `wizard_variances` (builds groups/ungrouped),
    `_included_sm_ids` (the single include gate), `wizard_save_matches` /
    `wizard_match_decisions` persistence (the `link|create|skip` actions).
  - `backend/app/schemas/api.py` — `VariancesGroupRow`, `VariancesFilament`,
    `SMVariantDecision`, the match-decision request/response models.
  - `frontend/src/api/types.ts` + `client.ts`.

## Working tree check

Run `git status --porcelain` first; cross-reference the files below. If any are dirty,
list them and ask. Surface unrelated dirty files once; don't block. This prompt is exempt.

## Decisions & defaults

- **Ignore = skip via the existing match gate.** "Ignore for this import" sets that SM
  filament's `wizard_match_decisions` action to `skip`. Do NOT invent a second exclusion
  set — `_included_sm_ids` must stay the single definition of "included," so the change
  flows to variances/weights/preview/execute for free.
- **Finish lexicon is a hint, like every other cluster.** Auto-split is a *suggestion*; the
  per-member actions (Part A) remain authoritative. A filament with no recognized finish
  token belongs to the "standard" sub-group of its `vendor+material`.
- Keep the existing "master = a real filament", "clusters are hints", "conflicts surfaced
  never auto-resolved", and the D3 attach contract intact.

## What to do

### Part A — Per-member actions (P0, the explicit ask)

Replace the per-member row (`StepVariances.tsx` ~L366-417, the radio + always-`checked`
disabled checkbox) with a clear, discoverable control set per grouped filament:

1. **Master** — keep the radio (sets the parent). Unchanged semantics.
2. **Move to… ** — a small dropdown/menu letting the user move this filament into any
   *other* group (an auto group or a manual `extra` group) or a **New group** (spins up a
   fresh `extraGroupMemberships` entry with this filament as master). Implement as state
   moves between `groupMembership[idx]` / `extraGroupMemberships[idx]`; reuse the existing
   master/membership maps. Moving the current master out should promote a sensible new
   master in the source group (e.g. first remaining member; if none remain the group
   dissolves).
3. **Make standalone** — remove from the group → it joins `effectiveUngrouped` with its own
   tare (this is today's checkbox behavior, surfaced as an explicit labeled action).
4. **Ignore for this import** — drop the filament from the import. Wire this to the match
   gate: POST an update setting this filament's `wizard_match_decisions` action to `skip`
   (reuse `wizard_save_matches`, or add a minimal single-decision patch endpoint if a bulk
   rewrite is awkward), then remove it from local Variances state. After ignore it must not
   appear in any group, in Standalone, or in Preview/Execute counts.

Make the four actions visually obvious (labeled buttons or a compact kebab menu per row),
not a bare checkbox. Show the finish-line sub-group label (Part B) on each group header so
the user can see *why* things grouped the way they did.

### Part B — Auto-split clusters by finish line (P1, resolves Q1)

5. Add a **finish-token lexicon** + extractor in `matcher.py`, e.g.
   `extract_finish_line(name: str) -> str` returning a normalized finish token
   (`"silk" | "matte" | "satin" | "cf" | "glow" | "wood" | "hs" | ...`) or `""` (standard).
   Cover at least: silk, matte, satin, carbon/cf, glow(-in-the-dark), wood, marble,
   metal/metallic, high-speed/hs, dual/tri/rainbow/multicolor. Token detection is
   word-boundary, case-insensitive, on the filament name (and material if present).
6. Extend the SM variant cluster key to `(vendor, material, finish)` so a `vendor+material`
   cluster splits into one group per finish line. Buddy "Silk Red"/"Silk Blue" → one group;
   Buddy "Green" → a separate group (or standalone if alone). Keep the "singletons (size<2)
   aren't auto-groups" rule per finish sub-cluster.
7. Surface the finish on `VariancesGroupRow` (e.g. `finish: str | None`) and render it in
   the group header ("Buddy PLA — Silk"). This is a hint; Part A can still merge/move across
   finishes if the user insists.
8. Don't let auto-split change D3 attach matching incorrectly: an existing FDB parent should
   still match on the same `(vendor, material, finish)` basis so a Silk group attaches to a
   Silk parent, not the standard one. Adjust the existing-FDB-parent map keying to include
   finish.

### Verify

9. `cd backend && ruff check . && pytest`. Add tests: `extract_finish_line` token cases;
   cluster key splits Silk vs standard into separate groups; "ignore" sets the match
   decision to `skip` and removes the filament from `_included_sm_ids`; moving a master out
   of a group promotes a new master / dissolves an empty group. Frontend:
   `cd frontend && npm test` and `npx tsc --noEmit`.
10. If practical, drive the live flow (`verify` / running app) with the Buddy Silk×2 +
    non-silk case: confirm two groups auto-form, "Move to…", "Make standalone", and "Ignore"
    each behave, and Preview/Execute counts reflect ignores.

## Conventions to honor

- Reuse helpers (`normalize_vendor`/`normalize_name`, `strip_color_and_words`,
  `_included_sm_ids`, the match-decision persistence). New schema fields get defaults so the
  contract stays backward compatible (Pydantic v2).
- Never modify/delete an upstream record; "ignore" only writes a local bridge skip decision.
- Doc updates ship in the **same commit** as code. Commit on `dev`, Conventional-Commits
  (`feat:`), no `Co-authored-by:`. Never `--no-verify`. Never push to `main`.

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/` (failure).
3. In `docs/decisions.md`, record: the finish-lexicon cluster split (Q1 resolved), the
   per-member action set, and the "ignore = match-skip, single include gate" rule. Update
   the Q1 line in `docs/wizard-redesign.md` (mark resolved).
4. Propose ONE commit covering the modified files (incl. the prompt move + docs). Present the
   file list + a one-line `feat:` message; ask `commit these as "<message>"? (y/n)`. On `y`,
   stage those specific paths and commit on `dev`. Never `git add -A`. Never push.
</content>
