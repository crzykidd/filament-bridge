---
name: 2026-06-22-changelog-archive-summary-rule
status: completed        # pending | completed | failed
created: 2026-06-22
model: opus              # research/planning + multi-repo standard edit
completed: 2026-06-22
result: Standard bumped to v1.1.0 (summarize-on-archive, minor/major-only, archive all closed minors); re-adopted in filament-bridge (standards.md + release-prep.md Step 3); decision logged. Executed in-session at maintainer request.
---

# Task: Revise the changelog archive rule (summarize-on-archive), in the standard then here

Change how `release-prep` archives the changelog: instead of moving the full previous-minor
detail out of `CHANGELOG.md` (leaving nothing behind), keep a **condensed summary** of each
archived version in the active changelog and move the **full detail** into the per-minor
archive file. The change is made first in the source standard
(`homelab-configs/standards/release-prep-and-cut`), then re-adopted in this repo.

## Why

A reader of the active `CHANGELOG.md` should get the **current version in full detail** plus a
**one-line-per-major-item summary** of older versions, with a link to read the full archived
section if they want more. Today archiving moves the whole series out and leaves only an index
link — you lose the at-a-glance history. (Decision origin: maintainer, 2026-06-22, during the
0.5.0 release where archiving was deliberately skipped pending this rule change.)

## Before you start

- Read the source standard: `/home/manderse/projects/homelab-configs/standards/release-prep-and-cut/README.md`
  (esp. "Per-minor changelog archive trigger", and Step 6 of "`/release-prep` — required steps")
  and the shipped template `release-prep.md` (Step 3 archive) in the same dir.
- Read this repo's adopted skill: `.claude/commands/release-prep.md` (Step 3 — the archive step)
  and `standards.md` (the pinned-version row for `release-prep-and-cut`).
- **Honor the homelab-standards-tagging convention** (see memory `[[homelab-standards-tagging]]`):
  editing a standard requires bumping that standard's own version and pushing its namespaced git
  tag. This is a standard change → at least a minor bump of the standard (new behavior).
- `homelab-configs` is an additional working directory (`/home/manderse/projects/homelab-configs`).
  Writes there are a separate repo with its own branch/commit rules — confirm before committing
  in it.
- Standing rule: **commit only, never push** (even `dev`) without explicit OK. See `[[ask-before-push]]`.

## Working tree check

Before editing, run `git status --porcelain` in BOTH repos and cross-reference the files below.
If any have uncommitted changes, list them and ask before touching.

## The new archive rule (the spec to implement)

1. **Trigger** — archiving fires ONLY on a new **minor** (`0.x.0`) or **major** (`x.0.0`) bump,
   never on a patch (`0.x.Y`). (Today's standard already says "new minor"; make it explicitly
   "minor or major", since a major also closes the prior minor series.)

2. **On archive, summarize — don't just move-and-link:**
   - Move the **full detailed entries** of each closed minor series into the per-minor archive
     file `docs/CHANGELOG-<minor>.x.md` (e.g. `docs/CHANGELOG-0.5.x.md`), full content preserved,
     newest-first, matching Keep-a-Changelog format.
   - In the **active `CHANGELOG.md`**, replace each moved version's full section with a condensed
     **summary block**:
     - Heading: `## [0.x.0] Summary` (one per archived version).
     - Body: **1 bullet per *major* feature or fix.** Use judgment to **drop small/trivial
       items** (typo fixes, copy tweaks, minor internal cleanups); keep user-visible features
       and significant fixes. Each summary version ends with a link to its full section in the
       archive file (anchored deep link, e.g. `…/docs/CHANGELOG-0.5.x.md#050--2026-06-22`).
   - Net result: active `CHANGELOG.md` = `[Unreleased]` + **current** minor series (full detail)
     + **older** minors as summary blocks (major-item bullets + archive links). Archive files
     hold the full detail.

## What to do

1. **Edit the source standard** (`homelab-configs/standards/release-prep-and-cut`):
   - Update the "Per-minor changelog archive trigger" section (README) and Step 6 of the required
     steps to describe the summarize-on-archive behavior above; make the trigger explicitly
     "minor or major".
   - Update the template `release-prep.md` Step 3 to match (this is what downstream repos copy).
   - Add concrete guidance for the summarization judgment ("major feature/fix" vs "drop small")
     and the summary-block format (heading + bullets + archive deep-link).
   - Bump the standard's version + tag per `[[homelab-standards-tagging]]`; note the new version.
2. **Re-adopt here** (filament-bridge):
   - Update `.claude/commands/release-prep.md` Step 3 to the new behavior (resolve placeholders;
     archive dir is `docs/`, archive files `docs/CHANGELOG-<minor>.x.md`).
   - Bump the pinned version in `standards.md`'s `release-prep-and-cut` row to the new standard
     version, with a one-line note of what changed.
3. **Decide + document the first-archive scope (OPEN QUESTION — ask the maintainer):**
   `CHANGELOG.md` currently still holds the full `0.3.x`, `0.4.x`, AND `0.5.x` series (archiving
   was skipped for 0.4.0 and 0.5.0). When the next minor (`0.6.0`) finally triggers archiving,
   does it archive **only the immediately-prior minor (0.5.x)**, or **all closed minors
   (0.3.x + 0.4.x + 0.5.x)** at once? Confirm with the maintainer; record the answer in
   `docs/decisions.md`. (Recommendation: archive all closed minors so the backlog clears in one
   pass and the rule self-heals.)

## Conventions to honor

- This repo adopts `code-checkin-and-pr`: work on `dev`, never `main`; conventional-commit
  prefixes (`docs:` fits a standard/skill text change); no `Co-authored-by:`.
- Doc/skill updates ship in the same commit as the behavior they describe.
- The version is stored bare; the `v` prefix is only on git tags.

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/`.
3. Record the archive-rule change + the first-archive-scope decision in `docs/decisions.md`.
4. Propose commits per the template (one per repo touched). Present file lists + one-line
   messages; ask before committing. Never `git add -A`. Never push without explicit OK.
