---
name: 2026-07-02-decisions-topic-index
status: completed        # pending | completed | failed
created: 2026-07-02
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-07-02
result: 155-entry topic index prepended to decisions.md + idempotent scripts/gen-decisions-index.py; body byte-identical, 155/155 anchors resolve
---

# Task: Add a topic index to docs/decisions.md so lookups don't read 304 KB (T8)

`docs/decisions.md` is an append-only decision log — **304 KB, 4805 lines, 155 top-level
`## ` entries**. A 2026-07-02 audit flagged it as the biggest incidental token sink: CLAUDE.md
points at it 5+ times and agents Read it whole (~76k tokens) to find one entry. Add an index at
the top so a reader (human or agent) can locate the right entry and jump to it — without changing
any existing entry content.

## Before you start

- Read `prompts/startnewsession.md` (operating rules, commit conventions, test commands).
  Commit but **do not push**; conventional-commit prefix; no `Co-authored-by:` trailers.
- Skim `docs/decisions.md`: every decision is a top-level heading of the form
  `## YYYY-MM-DD — <title>[, GitHub #N]` (155 of them, newest first). Sub-points use `### `.
- The file is rendered in-app by the DocsViewer (`/docs/decisions`) via `react-markdown`, and on
  GitHub. Check whether the DocsViewer configures heading slug ids (look for `rehype-slug` in
  `frontend/src/**` / the markdown component). Note the result — it affects whether in-page
  anchor links jump in-app (they always work on GitHub).

## Working tree check

Run `git status --porcelain` first. Several audit commits are already on `dev` (that's expected).
If `docs/decisions.md`, `docs/README.md`, or anything under `scripts/` has *uncommitted* changes,
list them and ask before editing. This prompt file is exempt.

## What to do

1. **Generate a topic-grouped index** and insert it directly under the `# Decision record`
   title, before the first `## ` entry. Structure it by **topic area**, not just chronologically
   (the body is already chronological). Suggested areas — adjust to what the entries actually
   cover: Sync engine & anti-ping-pong · Weight model · Conflicts & resolution · Wizard & variant
   model · OpenTag / OpenPrintTag · Backups · Mobile & labels · Security & auth · Reconcile /
   orphans · Locations & lifecycle · Misc/infra. Each entry appears **once**, under its best-fit
   area, as:
   `- [YYYY-MM-DD — short title](#anchor) — #<issue if any>`
   Keep the short title faithful to the heading (you may trim for length).
2. **Get the anchors right.** GitHub/GFM slugs: lowercase; spaces → `-`; drop characters other
   than word chars and hyphens (so `—`, backticks, `,`, `(`, `)`, `#`, `.` are removed; e.g.
   `## 2026-06-28 — `new_filament`/`new_spool` conflicts update in place (stable id), GitHub #44`
   → `#2026-06-28--new_filamentnew_spool-conflicts-update-in-place-stable-id-github-44`). Do this
   **programmatically**, not by hand — write a small script (see step 4) that parses the headings
   and emits the slug the same way GitHub does, including the duplicate-slug `-1`/`-2` suffix rule
   if any two headings collide. **Verify every generated anchor matches a real heading** before
   finishing (a quick check: each link target, stripped of `#`, must equal a computed heading
   slug; report the count matched — it must be 155/155).
3. **Add a one-line maintenance note** at the top of the index, e.g. *"New entries: add a line to
   the matching area below (or re-run `scripts/gen-decisions-index.py`)."* so the index doesn't
   silently rot as the log grows.
4. **Add the generator to `scripts/`** (e.g. `scripts/gen-decisions-index.py`) — a small,
   dependency-free Python script that regenerates the index block from the headings (idempotent:
   running it twice produces no diff). This makes the index maintainable instead of a one-off. If
   a `scripts/` convention already exists, match it. Keep it simple and documented at the top.
5. **Do NOT alter any existing decision entry** — only prepend the index block (and add the
   script). The body must be byte-identical below the inserted index.

## Conventions to honor

- Pure Markdown; the index must render cleanly in `react-markdown` (no HTML).
- No new runtime dependency. The script is a dev tool, not imported by the app.
- If the DocsViewer lacks slug ids (step "Before you start"), still ship GitHub-valid anchors and
  note in your report that in-app jumping needs `rehype-slug` (a possible follow-up — do NOT add
  it here, that's frontend scope creep).

## Verification before you hand off

- `grep -c '^## ' docs/decisions.md` still returns **155** (no entries lost/added).
- Your index lists **155** entries, each exactly once. Report any that didn't fit an area.
- Every anchor resolves to a computed heading slug (report N/155).
- `git diff docs/decisions.md` shows ONLY the prepended index block — no edits below it.

## Reporting (you are a dispatched agent — cannot ask the user mid-run)

Do the work, run the verification, but **do NOT** create a GitHub issue, `git commit`, `git add`,
or move this prompt file. Leave the tree dirty for review. In your final message report:
(1) files changed + one-line each, (2) `git diff --stat`, (3) the anchor-match count (must be
155/155) and the entries-per-area breakdown, (4) whether the DocsViewer has slug support,
(5) proposed `docs:` commit message, (6) any non-obvious decisions for `docs/decisions.md`
(ironically) — e.g. how you bucketed cross-cutting entries. Your final message is the deliverable
I will review.
