---
name: 2026-06-02-ci-checkin-workflows
status: pending          # pending | completed | failed
created: 2026-06-02
model: sonnet            # CI wiring from a pinned standard — execution
completed:
result:
---

# Task: Wire the `code-checkin-and-pr` CI (5 checks + publish matrix + retention) and `main` protection

filament-bridge adopts `code-checkin-and-pr` @ **v1.1.0** but has no CI — `.github/workflows/`
doesn't exist. The code now exists (Python backend, React frontend, Dockerfile, compose, alembic),
so the "pending first code" deferral is over. Implement the standard's required checks, the
image-publishing matrix, registry retention, and `main` branch protection. This also unblocks the
`release-prep-and-cut` first release (it needs the publish-on-`release` workflow).

## Before you start

- **Read the pinned standards:**
  - `code-checkin-and-pr` @ v1.1.0:
    `https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/code-checkin-and-pr/README.md`
    — the 5 required checks, the image-publishing matrix, registry retention rules, and `main`
    protection. (Local mirror, if present: `../homelab-configs/standards/code-checkin-and-pr/`.)
  - `release-prep-and-cut` @ v1.0.0 — confirm the `release: published` event must fire a build that
    pushes `:latest`, `:<semver>`, `:<major>`. `/release-cut` (`.claude/commands/release-cut.md`)
    names the workflows it verifies (`<MAIN_CI_WORKFLOW>` / `<PUBLISH_WORKFLOW>`) — match those names.
- Read `CLAUDE.md` (check-in operational rules), `standards.md` (the code-checkin + release-prep
  rows), `Dockerfile`, `docker-compose.yml`, `backend/requirements.txt`, `frontend/package.json`,
  and `backend/alembic/`.
- The local checks `/release-prep` already runs (mirror these in CI so prep ≡ CI):
  - `ruff check backend/`
  - `cd backend && DATABASE_URL=sqlite:///./_release_check.db alembic upgrade head && alembic current`
  - `docker compose config --quiet`

- **RESOLVE FIRST — two unknowns that block CI (ask the user):**
  1. **GitHub repo slug + registry.** The project registry lists the repo as "TBD — confirm repo,"
     so the GitHub remote and container registry (e.g. `ghcr.io/<owner>/filament-bridge`) must be
     confirmed before image push/retention can be wired. If the repo isn't on GitHub yet, wire the
     5 PR/push checks (which need no registry) and stub the publish/retention jobs with a clear TODO.
  2. **Frontend lint.** No eslint config exists; the repo type-checks via `npx tsc --noEmit`. Confirm
     whether "backend lint" should also gate the frontend (tsc typecheck, and eslint if you add a
     config) or stay backend-only per the standard's literal wording.

## Working tree check

Before editing, run `git status --porcelain` and cross-reference the files this plan adds/modifies
(`.github/workflows/*.yml`, possibly `standards.md`, `docs/decisions.md`, and `.claude/commands/`
if workflow names need syncing). If any have uncommitted changes, list them and ask. Surface
unrelated dirty files once; don't block. This prompt file is exempt.

## What to do

1. **CI checks workflow** (`.github/workflows/ci.yml`) — triggered on `pull_request` to `main` and
   on push to `dev` / `main`. Implement the 5 required jobs:
   1. **Backend lint** — `ruff check backend/` (+ frontend `tsc --noEmit`/eslint per the resolved
      decision). Consider also running `cd backend && pytest` — it's not one of the 5 but is cheap
      insurance; add it as a separate job if desired and note it.
   2. **Structured-config validation** — every checked-in YAML/JSON/TOML parses (at minimum
      `docker-compose.yml`, `.claude/settings.json`, `frontend/package.json`, `frontend/tsconfig*.json`).
   3. **DB migration check** — from an empty disposable SQLite DB, `alembic upgrade head` then assert
      `alembic current` == head (catches missing/broken revisions and unapplied autogenerates).
   4. **Compose validation** — `docker compose config --quiet`.
   5. **Image build verification (PR-only, no push)** — build every Dockerfile; do **not** push.
2. **Publish workflow** (`.github/workflows/publish.yml`) — the matrix from the standard:
   - push → `dev`: `:dev`, `:sha-<short>`
   - push → `main` (post-merge): `:latest`, `:sha-<short>`
   - PR → `main`: build only, nothing pushed (covered by job 5 above)
   - GitHub Release published (semver tag on `main`): `:latest`, `:<semver>`, `:<major>`
   Name this workflow to match what `/release-cut` expects (`<PUBLISH_WORKFLOW>`); update the
   command's placeholder if needed so cut's verification finds it.
3. **Registry retention** (`.github/workflows/retention.yml` or a job after publish): keep the 30
   most recent `:sha-*` and 15 most recent semver tags per image; never prune protected tags
   (`:latest`, `:dev`, bare-major like `:1`).
4. **`main` branch protection** — require a PR and all 5 checks green, disallow direct pushes.
   This is a GitHub repo setting (Settings → Branches, or `gh api`), not a file — document the exact
   steps (and the `gh api` command) in `docs/decisions.md` since it can't live in the repo. If `gh`
   is authenticated and the repo exists, apply it; otherwise leave the documented runbook.
5. **Sync docs in the same commit:** flip the `standards.md` code-checkin row from "not yet wired" to
   the wired state (note any deferred pieces, e.g. publish stubbed pending the repo slug), and flip
   the release-prep row's "remaining blocker" once the publish workflow exists.

## Conventions to honor

- Match the standard's tool-agnostic intent but use this repo's real stack (Python/ruff/alembic/
  pytest, Node/vite/tsc, Docker multi-stage). Keep workflows minimal and readable.
- Doc updates ship in the **same commit** as the workflows. Commit on `dev`, Conventional-Commits
  (`chore:` for CI/tooling), no `Co-authored-by:`. Never `--no-verify`. Never push to `main`.

## When done

1. Update this file's frontmatter: `status`, `completed` (date), `result`.
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/` (failure).
3. Record in `docs/decisions.md`: registry/repo-slug decision, the `main` branch-protection runbook,
   and any jobs stubbed pending the GitHub repo.
4. Propose ONE commit covering the added/modified files (incl. the prompt move). Present the file
   list + a one-line `chore:` message; ask `commit these as "<message>"? (y/n)`. On `y`, stage those
   specific paths and commit on `dev`. Never `git add -A`. Never push.
