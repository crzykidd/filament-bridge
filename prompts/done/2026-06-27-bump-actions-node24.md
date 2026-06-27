---
name: 2026-06-27-bump-actions-node24
status: completed        # pending | completed | failed
created: 2026-06-27
model: sonnet
completed: 2026-06-27
result: Bumped checkout v4→v5, setup-python v5→v6, setup-node v4→v5, docker/setup-buildx-action v3→v4, docker/login-action v3→v4, docker/metadata-action v5→v6, docker/build-push-action v6→v7 (all confirmed node24). github/codeql-action/{init,analyze} left at v4 (already node24). YAML validates. No node20 pins remain.
---

# Task: Bump GitHub Actions off deprecated Node.js 20 (#38)

The `v0.6.3` release build warned that several pinned actions still target Node.js 20,
which GitHub is deprecating (currently force-run on Node 24, fallback to be removed).
Bump the affected actions to the latest majors that run on Node 24 so the workflows keep
working and the deprecation annotation goes away. GitHub issue: #38.

## Before you start

- Read `standards.md` (this repo adopts `code-checkin-and-pr`): work on `dev`, never
  `main`; conventional-commit prefixes; no `Co-authored-by:`. You are already on `dev`.
- This is a CI-only change — no app code, no tests to add. The real validation is the
  next CI run after the change lands; locally you can only lint the YAML.

## Working tree check

Run `git status --porcelain`. The only file this task should touch besides the workflows
is this prompt itself. If `.github/workflows/*.yml` have unrelated uncommitted changes,
stop and ask. (At dispatch time the tree was clean.)

## What to do

1. Determine the current latest **major** version of each action below that runs on
   **Node 24** (check the action's GitHub releases / README; use WebSearch/WebFetch).
   Do NOT guess — confirm each target actually moved to Node 24 before bumping. If an
   action's latest major still uses Node 20, leave it and note that in the result.
   Actions in use (across `.github/workflows/ci.yml`, `codeql.yml`, `publish.yml`,
   `retention.yml` — grep `uses:` to find every occurrence):
   - `actions/checkout@v4`
   - `actions/setup-python@v5`
   - `actions/setup-node@v4`
   - `docker/setup-buildx-action@v3`
   - `docker/login-action@v3`
   - `docker/metadata-action@v5`
   - `docker/build-push-action@v6`
   - `github/codeql-action/init@v4` + `analyze@v4` — already Node 24; leave unless a
     newer major is the documented recommendation.
2. Update every `uses:` pin to the confirmed Node-24 major. Bump the major only — do not
   change step names, inputs, `with:` blocks, ordering, or any other behavior.
3. Sanity-check the YAML is still valid (e.g. `python -c "import yaml,glob;
   [yaml.safe_load(open(f)) for f in glob.glob('.github/workflows/*.yml')]"` using
   `backend/.venv/bin/python`, which has pyyaml). If `actionlint` happens to be
   installed, run it; if not, skip — don't install it.
4. Re-grep `uses:` and confirm no remaining pin is on a major known to use Node 20.

## Conventions to honor

- Only touch the `uses:` version pins. Keep diffs minimal and mechanical.
- `CHANGELOG.md`: this is CI tooling, not user-facing — do NOT add a changelog entry
  (the `## [Unreleased]` section is for user-facing notes). If you feel a note is
  warranted, add it under a `### Changed` line only if it would read as user-relevant;
  default is no changelog change.

## When done

1. Update this file's frontmatter: `status: completed` (or `failed`), `completed:
   2026-06-27`, and a one-line `result:` listing what bumped to what.
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/` (failure).
   Create the subdir if needed.
3. If you made any non-obvious version decision (e.g. an action you intentionally left
   on Node 20 because no Node-24 major exists), record it in `docs/decisions.md`.
4. Do NOT commit and do NOT push. Leave all changes staged-or-unstaged in the working
   tree and report back: the file-by-file version changes, your YAML-validity check
   result, and anything left on Node 20 and why. The orchestrator (Opus) will review the
   diff and commit with `Fixes #38`.
