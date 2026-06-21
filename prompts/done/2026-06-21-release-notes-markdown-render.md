---
name: 2026-06-21-release-notes-markdown-render
status: completed
created: 2026-06-21
model: sonnet            # small, well-scoped frontend change
completed: 2026-06-21
result: Replaced <pre> with ReactMarkdown+remarkGfm in ReleaseNotesModal; tsc clean, 107 tests pass.
---

# Task: Render the in-app release notes as Markdown (fix funny wrapping)

The post-upgrade / update-available release-notes modal renders the GitHub release body
(our `CHANGELOG.md` section) inside a `<pre className="whitespace-pre-wrap">`, so the
source-level hard wraps (~95-col mid-sentence newlines + 2-space list-continuation
indents) are shown literally and the text wraps oddly. The notes are Markdown — render
them as Markdown so single newlines collapse to spaces and the text reflows to the panel.

## Before you start

- Read `frontend/src/pages/DocsViewer.tsx` — it already renders Markdown with
  `react-markdown` + `remark-gfm` and a `mdComponents` map. Match that approach.
- The change is in `frontend/src/components/Layout.tsx` → `ReleaseNotesModal`
  (around the `<pre className="whitespace-pre-wrap ...">{releaseNotes}</pre>` block).
- Both modal cases (`release_notes` for update-available and `current_release_notes`
  for post-upgrade) flow through the SAME component, so one change covers both.

## Working tree check

Run `git status --porcelain` first. NOTE: this session has in-progress unpushed work on
`dev` (sync-log + OPT-badge features) and a locally-modified `docker-compose.dev.yml`
(the user's host URLs — do NOT touch or stage it). Only touch the files this task needs.

## What to do

1. In `ReleaseNotesModal` (Layout.tsx), replace the `<pre className="whitespace-pre-wrap …">`
   that renders `releaseNotes` with a `<ReactMarkdown remarkPlugins={[remarkGfm]}>` block.
   - Import `ReactMarkdown` from `react-markdown` and `remarkGfm` from `remark-gfm`.
   - Provide a small `components` map for readable in-modal styling (paragraphs with
     spacing, `ul`/`li` as a bulleted list, `strong`, `a` opening in a new tab,
     `code`/`h3` if present). You may lift a trimmed subset from DocsViewer's
     `mdComponents`; keep it scoped to what release notes actually use.
   - Keep the surrounding modal scroll container / max-height.
2. Do NOT add `remark-breaks` — single newlines must stay soft breaks (collapse to a
   space). Adding it would reproduce the bug.
3. Confirm the modal still renders when `releaseNotes` is null/empty (guard stays).

## Conventions to honor

- `react-markdown` (^10) + `remark-gfm` (^4) are already in `package.json` — no new deps.
- react-markdown sanitizes by default (no raw HTML); keep it that way — release bodies
  come from GitHub and must render safely.
- Match the app's existing dark-mode Tailwind classes used elsewhere in the modal.
- Add a `CHANGELOG.md` entry under `## [Unreleased]` → `### Fixed` (user-facing):
  in-app release notes now render as Markdown instead of preformatted text, fixing the
  odd wrapping.

## Verify

- `cd frontend && npx tsc --noEmit` is clean.
- `cd frontend && npx vitest run` passes (107+ tests). Add/adjust a test only if a
  Layout/release-notes test exists; otherwise a manual render check is fine.

## When done

1. Update this file's frontmatter (`status`, `completed`, `result`).
2. `git mv` this file into `prompts/done/`.
3. Record any non-obvious decision in `docs/decisions.md` (likely none — straightforward).
4. Do NOT commit. Leave the changes for the orchestrator to review and commit on `dev`
   (the session owner handles commits/pushes per the user's standing rule).
