---
name: 2026-06-18-shared-wizard-action-bar
status: done
created: 2026-06-18
model: sonnet            # mechanical-ish frontend refactor across several steps
completed: 2026-06-18
result: >
  Created WizardActionBar component; refactored all 9 wizard/OpenTag step locations.
  All 94 tests green. Docs updated. Working tree ready to commit.
---

# Task: Consistent Back/Continue on both top and bottom of every commit/step page

Multi-step and commit pages currently put the primary nav buttons top-only, bottom-only, or
both, inconsistently. Standardize: a shared action bar rendered at **both top and bottom** of
every wizard step and the OpenTag commit flow.

## Decisions already made with the user

- Extract a **shared `<WizardActionBar>` component** (Back / Next|Save + optional extra slot +
  saving/disabled state) and render it twice (top + bottom) per page — replacing the 5
  hand-rolled `const actionBar` blocks.
- **Include the OpenTag Cleanup review + confirm steps** (they're commit pages).
- **Settings is OUT of scope** — leave its single mid-page Save as-is (flat form, not a stepper).

## Verified inventory (from audit — file:line)

There is **no** shared component today; three steps copy-paste a local `const actionBar` and
render it top+bottom. Current state per page:

| Page / Step | Top | Bottom | Ref |
|---|---|---|---|
| Step1 Connectivity | **missing** | yes | `Wizard/Step1Connectivity.tsx:57-65` (`Next →`) |
| Step2 Direction | **missing** | yes | `Step2Direction.tsx:73-84` (`Back`/`Save & Next`) |
| Step3 Matches | yes | yes | `Step3Matches.tsx` actionBar `:470-489`, top `:500`, bottom `:693` (has extra `↻ Rescan`) |
| StepVariances (SM path) | yes | yes | `StepVariances.tsx` actionBar `:476-487`, top `:498`, bottom `:1135`; early empty-state Back `:467` |
| StepVariances (FDB path) | **missing** | yes | `FDBVariancesStep` (same file, `:1151+`), bottom-only `:1305-1310` |
| StepNPreview | yes | yes | `StepNPreview.tsx` actionBar `:81-90`, top `:101`, bottom `:297` |
| Step6 Execute | **missing** | yes | `Step6Execute.tsx:248-259` (`Back`/`Execute sync`); result view `:40-176` is terminal (no nav) |
| OpenTag review step | yes | **missing** | `OpenTagCleanup.tsx:2097-2104` (`Review & Confirm →` top only) |
| OpenTag confirm step | **missing** | yes | `ConfirmStep` `OpenTagCleanup.tsx:676-693` (`Back`/`Apply N writes`) |

Wizard nav plumbing (`next`/`prev`/`goTo`) is in `WizardShell` (`Wizard/index.tsx:55-62`), passed
via `ctx`; `Stepper` (`:20-48`) is a progress indicator only (not action buttons).

## What to do

1. **Create `<WizardActionBar>`** (e.g. `frontend/src/components/WizardActionBar.tsx` or under
   `Wizard/`). Props to cover all observed needs: `onBack?`, `backLabel?`, `onNext?`,
   `nextLabel?` (default "Next →"; supports "Save & Next →", "Execute sync", "Apply N writes",
   "Review & Confirm →"), `nextDisabled?`, `busy?`/`saving?`, and an `extra?` slot (for Matches'
   `↻ Rescan`). Match the existing actionBar styling so nothing visually regresses.
2. **Refactor the 3 compliant steps** (Step3 Matches, StepVariances SM path, StepNPreview) to
   use the shared component top+bottom; delete their local `actionBar` consts. Preserve the
   Rescan button via `extra`.
3. **Add the missing bars** (render top+bottom via the shared component):
   - Top added: Step1 Connectivity, Step2 Direction, Step6 Execute, `FDBVariancesStep`,
     OpenTag confirm step.
   - Bottom added: OpenTag review step.
   - Keep terminal/result views without nav (Step6 result `:40-176`, OpenTag done step).
   - Preserve each page's existing button semantics/labels and disabled/saving logic.
4. Leave Settings, the selection toolbars (`OpenTagCleanup.tsx:2194`, `Conflicts.tsx:1331`), and
   `Stepper` untouched.

## Edge cases / cautions
- `FDBVariancesStep` is a second component inside `StepVariances.tsx` — easy to miss; it needs a
  top bar. Also handle the SM-path early empty-state Back (`:467`) sensibly.
- Don't change navigation behavior — only placement/consistency. The "Save & Next" steps must
  still save before advancing; disabled/busy states preserved.
- OpenTag review/confirm live in `OpenTagCleanup.tsx` (recently restructured) — re-read current
  state before editing; the confirm step is the `ConfirmStep` sub-component.

## Before you start
- Read `Wizard/index.tsx` (shell/ctx/stepper) and every step listed above, plus the OpenTag
  review/confirm sections, as they are NOW.

## Working tree check
`git status --porcelain`; build on current `dev` (and, if landed first, the friendly-backup
change — they both touch `OpenTagCleanup.tsx`/`Settings.tsx`, so expect to run sequentially).
List anything unexpected; ask.

## Tests
- `npx tsc --noEmit` + `npm test` green (update any step tests that asserted button location).
- Spot-add/extend a test that the shared `WizardActionBar` renders Back/Next with the right
  labels + disabled state, if a sensible harness exists.

## Conventions to honor
- One shared component; no new copy-paste. Doc updates ship in the SAME commit (`docs/wizard.md`
  / `docs/opentag-cleanup.md` if they describe navigation; `CHANGELOG.md` `[Unreleased]`).
  Conventional-commits `refactor:` or `feat:`. No `Co-authored-by:`. Branch `dev`, never `main`,
  never push.

## When done
1. Frontmatter (`status`/`completed`/`result`); `git mv` to `prompts/done/`.
2. Record any non-obvious decision in `docs/decisions.md`.
3. Propose ONE commit (specific paths, never `git add -A`); present list + one-liner; STOP.
   Never push.
