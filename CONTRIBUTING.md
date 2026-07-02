# Contributing to filament-bridge

Thanks for your interest in improving filament-bridge. This guide covers the essentials for
humans; `CLAUDE.md` and `standards.md` carry the same rules in the form coding agents consume.

## Getting set up

The bridge is a Python/FastAPI backend + React/TypeScript frontend, served as a single Docker
container. To run it locally against your own Filament DB and Spoolman:

```bash
# Backend (port 8090)
cd backend && pip install -r requirements.txt
FILAMENTDB_URL=http://localhost:3000 SPOOLMAN_URL=http://localhost:7912 \
  uvicorn app.main:app --reload --port 8090

# Frontend (Vite dev server proxies /api to the backend)
cd frontend && npm install && npm run dev
```

`docker-compose.dev.yml` brings up a full local stack (bridge + Spoolman + Filament DB + Mongo) if
you'd rather not run the upstreams yourself. See [docs/getting-started.md](docs/getting-started.md).

## Before you open a PR

Run the checks locally — CI runs the same ones:

```bash
cd backend && python -m pytest && python -m ruff check .
cd frontend && npx vitest run && npx tsc --noEmit
```

## Branching & commits

- **Work on `dev`** (or a short-lived branch off `dev`). `main` is protected — all changes land via
  a **`dev` → `main` pull request** once every required check is green. Never push to `main`.
- **Conventional-commit prefixes are required:** `feat:` (user-facing feature), `fix:` (bug fix),
  `chore:` (tooling/deps/maintenance), `docs:` (docs only).
- **Docs ship in the same commit as the code they describe** — not as a follow-up.
- **Every `feat:`/`fix:` adds a `## [Unreleased]` entry to [`CHANGELOG.md`](CHANGELOG.md)** in the
  same commit. `CHANGELOG.md` is the single source of release notes.
- Don't add `Co-authored-by:` trailers, and don't bypass git hooks (`--no-verify` etc.) — if a hook
  fails, fix the underlying issue.
- If your change resolves a tracked issue, reference it (`Fixes #N`) in the commit body **and** the
  PR description (a squash merge keeps the PR body, so that's what auto-closes the issue).

## Issues

GitHub issues are the source of truth for planned work; [`docs/backlog.md`](docs/backlog.md) is the
agreed ordering. If you hit a bug that has no issue, please file one before (or alongside) the fix.

## Where things live

- `backend/app/api/` — FastAPI routers · `backend/app/core/` — sync engine + logic ·
  `frontend/src/pages/` — one file per screen.
- [`docs/`](docs/README.md) — user + reference docs (start at the index).
- [`docs/decisions.md`](docs/decisions.md) — the "why" log (topic-indexed at the top). Check it
  before re-deriving a design, and record non-obvious decisions there.
- The engineering standards this repo follows are pinned in [`standards.md`](standards.md).

## Security

Please do **not** file security issues as public GitHub issues — see [SECURITY.md](SECURITY.md) for
private reporting.

## License

By contributing, you agree that your contributions are licensed under the project's
[MIT License](LICENSE).
