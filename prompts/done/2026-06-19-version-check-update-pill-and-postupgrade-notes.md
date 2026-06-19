---
name: 2026-06-19-version-check-update-pill-and-postupgrade-notes
status: done
created: 2026-06-19
model: sonnet
completed: 2026-06-19
result: All three deltas implemented, 1163 backend tests + 102 frontend tests green, ruff clean, tsc clean.
---

# Task: "Update Available" pill + daily check + post-upgrade release-notes modal

Three deltas to the existing version-update-check feature (already shipped v0.2.0 — do not
rebuild it; extend it):
1. Relabel the update pill to **"Update Available"** and make the check **daily**.
2. After the user **upgrades** (running version increased), show the **now-running** version's
   release notes **once** on next login (notes come from the GitHub release body for that
   version = the CHANGELOG/PR notes — the same single source our release process publishes).

## Verified current state (file:line)

- Backend `backend/app/api/version.py`: `GET /api/version` returns a dict (`:137-148`):
  `current, latest, update_available, release_url, release_name, release_notes, channel,
  commit, build, is_dev`. `release_notes` is the body of **`/releases/latest`** only
  (`_GITHUB_URL` `:24`, `_fetch_github` `:76-83`) — i.e. the *newer-available* release. TTL =
  6h (`:25` `_TTL_SECONDS = 6 * 3600`), **lazy-on-request** (no scheduler; `_cached_github`
  `:101-107`). Dev forces `update_available=false` (`:132-135`). There is **no** way to get the
  running version's release today.
- Frontend `frontend/src/components/Layout.tsx`: `VersionBadge` (`:119-182`); pill render
  `:167-177` (text `↑ v{info.latest}` at `:175`, title `:173`); `ReleaseNotesModal` (`:40-113`)
  shows `release_notes`/`release_name`/`release_url`; trigger `:123-140` (shows when
  `update_available && latest && lastSeen!==null && lastSeen!==latest`); dismiss writes
  `fb_last_seen_version` (`LS_KEY` `:13`, writer `:142-147`). New installs (key absent) are
  suppressed. `VersionInfo` type `frontend/src/api/types.ts:901-912`.
- Docs: `docs/version-update-check.md` documents all of the above (TTL `:44`, pill text `:78`,
  dismissal `:85-94`).

## What to do

### Delta 1 — pill label + daily cadence
- `Layout.tsx:175`: pill text `↑ v{info.latest}` → **`Update Available`** (keep the version in
  the `title` at `:173`).
- `version.py:25`: `_TTL_SECONDS` 6h → **24h** (`24 * 3600`). (Lazy-on-load is fine — "daily" =
  re-checks at most once/24h on next page load; no scheduler needed. Don't add an APScheduler
  job.)

### Delta 2 — post-upgrade release notes, once
- **Backend:** also fetch the **current** running version's release. Add a GitHub call to
  `https://api.github.com/repos/crzykidd/filament-bridge/releases/tags/v{current}` (note the
  `v` tag prefix). Add to the `/api/version` response: `current_release_notes`,
  `current_release_name`, `current_release_url` (all null on 404 — dev/untagged builds — and on
  any fetch failure; never 5xx). Cache it alongside the existing GitHub cache (same TTL).
- **Frontend (`Layout.tsx`):** add a SECOND, independent trigger + storage key
  (e.g. `fb_last_running_version`):
  - On mount: if the stored running-version exists **and differs from** `info.current`, the user
    just upgraded → show `ReleaseNotesModal` with the **current**-version fields
    (`current_release_notes`/`name`/`url`). If `current_release_notes` is null (untagged/dev),
    don't show.
  - On dismiss: write `info.current` to `fb_last_running_version`.
  - First run (key absent): set the key to `info.current` silently, **no** modal (mirror the
    existing `lastSeen!==null` suppression).
  - Reuse/generalize `ReleaseNotesModal` to accept notes/name/url props (so one component serves
    both the existing "newer available" modal and the new post-upgrade one).
  - The two flows are independent and naturally don't collide (after upgrading to latest,
    `update_available` is false, so the existing newer-available modal won't fire). If both
    could ever qualify, the **post-upgrade** modal takes precedence.
- `types.ts:901-912`: add the three `current_release_*` fields.

## Before you start / working tree
Read `version.py`, `Layout.tsx` (`VersionBadge`/`ReleaseNotesModal`), `types.ts`,
`docs/version-update-check.md`. `git status --porcelain` (build on current `dev`).

## Tests
- Backend: `/api/version` returns `current_release_*`; 404 on the current tag → nulls (mock the
  GitHub call); existing fields unchanged; TTL constant updated.
- Frontend: post-upgrade modal shows once when stored running-version ≠ current and current
  notes exist; not on first run; dismiss records current; pill reads "Update Available".
- `cd backend && .venv/bin/python -m pytest -q && .venv/bin/ruff check .` and
  `cd frontend && npx tsc --noEmit && npm test` green.

## Conventions / when done
Doc updates same commit (`docs/version-update-check.md`: TTL, pill label, the new post-upgrade
modal subsection + new response fields; `CHANGELOG.md` `[Unreleased]`). Conventional-commits
`feat:`. No `Co-authored-by:`. Branch `dev`, never `main`, never push. Update frontmatter,
`git mv` to `prompts/done/`, propose ONE commit (specific paths), present list + one-liner, STOP.
