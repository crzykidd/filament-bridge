---
name: 2026-06-09-version-check-and-release-notes
status: completed
created: 2026-06-09
model: sonnet
completed: 2026-06-09
result: Backend GET /api/version (public, cached 6h GitHub check, dev-channel suppression, build label), __channel__/__commit__ in __init__.py, version.py API router, 21 backend tests (21/21 pass, 804 total), VersionInfo type + getVersionInfo client, VersionBadge + ReleaseNotesModal in Layout.tsx, Dockerfile build args, docker-compose.dev.yml dev channel wiring, docs/version-update-check.md, CHANGELOG, CLAUDE.md env vars, decisions.md ADR.
---

# Task: Version display, GitHub update check, dev marker, post-upgrade release-notes popup

Plumb version awareness into filament-bridge, mirroring the proven LabelForge implementation at
`~/projects/labelforge` (`backend/labelforge/routes/version.py`, `bootstrap.py`,
`docs/features/version-update-check.md`, and the two done prompts
`prompts/done/2026-06-07-version-badge-and-update-check.md` +
`2026-06-07-dev-build-version-marker.md`). READ THOSE for the exact shape, then adapt to this repo.
No release exists yet — that's fine, plumb it so it works once we cut one.

## Working tree note
Ignore the pre-existing untracked dotfiles and the unrelated `docker-compose.dev.yml` change; never
stage them. Run `git status --porcelain` first. NOTE: a sibling auth prompt may have already landed
on `dev` — build on top of it; don't undo it.

## Backend

- **Version source:** current version is `backend/app/__init__.py:__version__ = "0.1.0"`. Add
  channel/commit markers like LabelForge: read env `BRIDGE_CHANNEL` (default `"release"`) and
  `BRIDGE_COMMIT` (default empty) — expose as `__channel__` / `__commit__` (in `app/__init__.py` or
  a small bootstrap module). When channel is `dev`, the displayed version gets a `-dev` suffix (and
  short commit if present).
- **`GET /api/version` route** (`backend/app/api/version.py`, mounted under `/api` in `main.py`):
  returns `{ current, channel, commit, latest, update_available, release_url, release_name,
  release_notes }`. Mirror LabelForge's `version.py`: hit
  `https://api.github.com/repos/<owner>/<repo>/releases/latest` (use the bridge's repo — confirm the
  GitHub owner/repo; the project README/remote will have it), cache in-memory ~6h, fail gracefully
  (return current-only on network/parse error, never raise). `update_available` =
  semver(latest) > semver(current) AND channel == release. Reuse LabelForge's `_parse_semver` /
  `_is_newer` logic. 3s timeout, `User-Agent: filament-bridge` header.
- If the auth prompt has landed: `/api/version` should be reachable to an authenticated user; decide
  whether it's in the public set (current version is not sensitive — public is fine, like health) or
  behind auth. Prefer PUBLIC for `current/channel/commit` but it's acceptable to keep the whole
  route behind auth. Pick one; note it.

## Frontend

- **Version badge** in the sidebar/footer (`Layout.tsx`) showing the current version (with `-dev`
  marker when channel=dev). When `update_available`, show an "update available → vX.Y.Z" affordance
  linking to `release_url` (new tab).
- **Post-upgrade release-notes popup:** store the last-seen version in `localStorage`
  (e.g. `fb_last_seen_version`). On load, if the current running version is NEWER than the stored
  last-seen value (and a stored value existed — don't pop on first-ever run), show a modal rendering
  this release's notes (`release_name` + `release_notes`, markdown) with a link to the full release.
  Dismiss updates `fb_last_seen_version` to current. (LabelForge's done prompt describes this UX —
  follow it.) Render the markdown safely (the repo already renders markdown somewhere, or use a tiny
  safe renderer — no raw HTML injection).
- A small `frontend/src/version.ts` constant is fine if LabelForge uses one, but prefer reading the
  current version from `/api/version` so the frontend and backend never drift.

## Conventions / tests / done

- Backend tests (`python3 -m pytest`): `_parse_semver` / `_is_newer` units; `/api/version` returns
  current-only and does not raise when the GitHub fetch is mocked to fail; `update_available` logic.
- Frontend: `npm run build`; report result.
- Update `CHANGELOG.md` `[Unreleased]`, `CLAUDE.md` (new env `BRIDGE_CHANNEL` / `BRIDGE_COMMIT`), and
  a short `docs/version-update-check.md` (mirror LabelForge's doc). Consider noting in the Dockerfile
  build how `BRIDGE_COMMIT`/`BRIDGE_CHANNEL` would be passed (build args) — optional, low priority.
- Commit prefix `feat:`. No `Co-authored-by:`. Branch `dev`, never `main`, never push.
- When done: frontmatter → completed; `git mv` to `prompts/done/`; decisions in `docs/decisions.md`.
  DO NOT `git commit` — report back file list, proposed commit message, test + build results.
