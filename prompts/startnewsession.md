# Start-new-session prompt — filament-bridge

Paste/point me at this file at the start of a fresh session. It's a standing
onboarding brief (not a task — don't move it to `done/`). It restates the project and
the operating rules so a new session is productive even if conversation memory was
cleared.

## What this project is

**filament-bridge** is a bidirectional sync service between
[Filament DB](https://github.com/hyiger/filament-db) (Next.js/MongoDB, gross weight
model, MongoDB ObjectIds, spools embedded on filaments) and
[Spoolman](https://github.com/Donkie/Spoolman) (Python/FastAPI, net weight model,
relational Vendor→Filament→Spool with int IDs, extra-field system). It runs as a Docker
sidecar, polls both REST APIs, diffs against stored snapshots, applies non-conflicting
changes, and queues conflicts for manual resolution. **No upstream modifications** — only
documented REST APIs + Spoolman extra fields. Conflicts are never auto-resolved.

- **Stack:** Backend Python 3.12 / FastAPI, httpx, SQLAlchemy + SQLite, APScheduler,
  Pydantic v2. Frontend React 18 / TypeScript, Vite, Tailwind, React Router. Single
  Docker image (Node builds React → FastAPI serves it), single port 8090, SQLite in a
  mounted volume.
- **Cross-references:** Spoolman extra fields (`filamentdb_id`, `filamentdb_parent_id`,
  `filamentdb_spool_id`) link to FDB; FDB spool `label` stores the Spoolman spool id.
- **Variant model:** FDB has parent/variant inheritance (`parentId`, one level deep);
  Spoolman is flat one-filament-per-colour. The bridge tracks the parent via
  `filamentdb_parent_id`.

## Read first (in this order)

1. **`CLAUDE.md`** — the authoritative quick-reference (architecture decisions, env vars,
   runtime settings, weight/lifecycle/location sync rules, "what NOT to do").
2. **`docs/prd.md`** — full functional requirements (FR-numbers).
3. **`standards.md`** — the homelab standards this repo implements + pinned versions.
4. **`docs/decisions.md`** — the "why" log; check before re-deriving a design.
5. **`docs/backlog.md`** — the prioritised issue queue (GitHub issues are the source of
   truth; this file is the agreed order).

## Operating rules (honor these by default)

**Scope / what to work on**
- **Only work the bug(s)/issue(s) the user explicitly names.** Never fan out to the
  backlog, pick up other open issues, or add "while I'm here" fixes on your own. Offer
  others as a one-liner at most, then wait.
- For substantial *named* implementation work, prefer **dispatching to a Sonnet
  subagent** (Agent tool, `model: sonnet`, `isolation: "worktree"` when parallel); Opus
  orchestrates, reviews the diff, and integrates. Don't dispatch unnamed work.

**Git / check-in (the `code-checkin-and-pr` standard)**
- **Commit, but do not push** without explicit OK — even to `dev`. *Exception:*
  invoking `/release-prep` or `/release-cut` authorizes that command's own push.
- **Never push to `main`** (protected). Changes land via a `dev → main` PR with all
  required checks green. Day-to-day work is on `dev` (or a short branch off it).
- **Conventional-commit prefixes** (`feat:`/`fix:`/`chore:`/`docs:`). **No
  `Co-authored-by:` trailers.** **Docs ship in the same commit as the code** they
  describe. Never bypass hooks (`--no-verify` etc.).
- Branch-protection required checks use **bare names** (`Lint`, `Test`, …), not
  `CI / Lint`.

**Issue tracking / auto-close**
- For a bug reported **in chat with no GitHub issue**, `gh issue create` one, then end
  the fix commit body with `Fixes #N` so it auto-closes on release.
- In the **release PR body**, add one closing keyword **per issue** (`Fixes #22`,
  `fixes #26`, `fixes #31`) — keywords do NOT distribute across a list, and a squash
  merge discards commit trailers, so the PR body is the reliable closer.
- For an already-closed issue lacking a version note, add a "Fixed in vX.Y.Z" comment.

**Testing (run before committing)**
- Backend: `cd backend && .venv/bin/python -m pytest` (the venv python; bare `python`
  isn't on PATH). Lint: `.venv/bin/python -m ruff check backend/`.
- Frontend: `cd frontend && npx vitest run` and `npx tsc --noEmit`.

**Releases (the `release-prep-and-cut` standard)**
- Version is stored **bare** in `backend/app/__init__.py` (`__version__`) and mirrored to
  the README badge + What's New + `CHANGELOG.md`. The `v` prefix is added in exactly one
  place: the git tag / GitHub release (done by `/release-cut`).
- `CHANGELOG.md` `## [Unreleased]` is the single source of release notes; the release PR
  body and the GitHub release body reuse the same section verbatim.
- Flow: `/release-prep <version>` (bump + roll changelog + sync docs + one
  `chore(release):` commit + push dev + open PR) → human merges + CI green + `:latest`
  published → `/release-cut <version>` (tag + GitHub release, which triggers the
  production image build). Never re-tag; pick the next version instead.

**Other standards**
- `repo-sandbox-permissions` (repo-wide): in-repo reads/edits/writes/bash run sandboxed;
  widen `allowedDomains`/`allowWrite` rather than adding `Bash(...)` allow rules.
- `handoff-prompt-workflow`: scoped tasks live in `prompts/` (from `TEMPLATE.md`),
  completed → `prompts/done/`; log non-obvious decisions in `docs/decisions.md`.

## Current state (update as it moves)

- Latest release: **v0.6.2** (modal-portal fix #33, Tare Editor variants-editable +
  variant grouping #34). Earlier: v0.6.1 (Tare Editor, mobile collapsible sidebar, logo +
  favicons, sync-log retention #22, OpenPrintTag phantom-update #31).
- Open backlog (see `docs/backlog.md`): wizard UX (#13 require tare entry, #14
  partial-success + Failure Report), backup-status UI (#20), Discord webhooks (#24),
  print-history enrichment decision (#25), and a batch of docs/PRD-sync issues
  (#15–#19, #23).

## How to start a session

1. Read the docs above.
2. Ask me (the user) which bug/issue to work — then work only that.
3. Make the change with tests + docs in the same commit; run the test commands; **stop
   and ask before pushing.**
