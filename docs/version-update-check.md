# Version display and update check

## Purpose

The bridge sidebar always shows the running version with a link to its GitHub release.
When a newer release exists, an "Update Available" pill appears next to the version and a
one-time modal pops up with the release notes. After an upgrade, the running version's own
release notes are shown once on the next page load. Dev builds suppress both nags.

## `GET /api/version`

Public endpoint (no auth required). Returns:

```json
{
  "current":        "0.2.0",
  "latest":         "0.3.0",
  "update_available": true,
  "release_url":    "https://github.com/crzykidd/filament-bridge/releases/tag/v0.3.0",
  "release_name":   "v0.3.0",
  "release_notes":  "## What's new\n...",
  "current_release_url":   "https://github.com/crzykidd/filament-bridge/releases/tag/v0.2.0",
  "current_release_name":  "v0.2.0",
  "current_release_notes": "## What's new in 0.2.0\n...",
  "channel":        "release",
  "commit":         null,
  "build":          "v0.2.0",
  "is_dev":         false
}
```

| Field | Description |
|---|---|
| `current` | Running version from `backend/app/__init__.py:__version__` |
| `latest` | Tag name from GitHub releases (leading `v` stripped), or `null` on error |
| `update_available` | `true` when `latest > current` AND `channel == "release"` |
| `release_url` | Link to the latest GitHub release page |
| `release_name` | Latest GitHub release title |
| `release_notes` | Latest GitHub release body (markdown, treated as plain text in the UI) |
| `current_release_url` | Link to the **running** version's GitHub release, or `null` on 404/dev/error |
| `current_release_name` | **Running** version's GitHub release title, or `null` |
| `current_release_notes` | **Running** version's GitHub release body, or `null` |
| `channel` | `"release"` (default) or `"dev"` — baked in at build time |
| `commit` | Short git SHA baked in at build time, or `null` |
| `build` | Display label: `"v0.2.0"` on release; `"v0.2.0-dev+abc1234"` on dev |
| `is_dev` | `true` when `channel != "release"` |

## GitHub checks

- Backend calls `https://api.github.com/repos/crzykidd/filament-bridge/releases/latest`
  (for the update-available nag) and
  `https://api.github.com/repos/crzykidd/filament-bridge/releases/tags/v{current}`
  (for the running version's release notes), each with a 3-second timeout and
  `User-Agent: filament-bridge`.
- Both results are cached in-memory for **24 hours**. On any network or parse error, the
  last good cached value is served; if no cache exists, fields default to `null`. The
  endpoint never returns 5xx.
- The tag endpoint returns `null` fields (not an error) on 404 — this is the expected
  result for dev/untagged builds.
- The browser never calls GitHub directly.
- Both caches share the same 24-hour TTL. The check is lazy-on-request (re-checks at most
  once per 24 hours on the next page load); there is no background scheduler job.

## Dev / channel builds

`BRIDGE_CHANNEL` and `BRIDGE_COMMIT` are environment variables read at startup from
`backend/app/__init__.py`. They are baked into the Docker image as env vars via the
`BUILD_CHANNEL` and `GIT_COMMIT` build args (placed near the end of the Dockerfile
to avoid busting earlier cache layers).

| Channel | Version label example |
|---|---|
| `release` (default) | `v0.2.0` |
| `dev` (no SHA) | `v0.2.0-dev` |
| `dev` (with SHA) | `v0.2.0-dev+abc1234` |

To stamp the dev compose build with the current commit:

```bash
GIT_COMMIT=$(git rev-parse --short HEAD) docker compose -f docker-compose.dev.yml build
```

Dev builds force `update_available=false` even when `latest > current`, suppressing the
update nag. (`latest` is still reported for informational purposes.) The current-version
tag fetch is also skipped for dev builds (`current_release_*` fields are always `null`).

## Frontend — version badge

`Layout.tsx` renders a `VersionBadge` component that fetches `/api/version` once on
mount. It shows:
- The `build` label as a link to the current release tag (or the latest release URL
  when `update_available` is false and `release_url` is present).
- An **"Update Available"** pill linking to `release_url` when `update_available` is true.
  The full version number is in the pill's `title` attribute for hover-tooltip access.
- A one-time release-notes modal when `update_available` is true and the `latest` version
  has not already been dismissed (per-version dismissal stored in
  `localStorage['fb_last_seen_version']`). The modal does not appear on the very first
  run (no stored value) to avoid surprising new installs.
- Markdown from `release_notes` is rendered as `<pre>` plain text — never as `innerHTML`.

## Post-upgrade release notes (one-time modal)

After the user upgrades to a new version, the **running version's** own release notes
are shown once on the next page load, then suppressed.

**Trigger logic** (runs on mount, independently of the "update available" flow):

1. Read `localStorage['fb_last_running_version']`.
2. If the key is **absent** (first ever run): write `info.current` silently — no modal.
3. If the stored value **differs** from `info.current` AND `current_release_notes` is not
   null: show the post-upgrade modal. On dismiss, write `info.current` to the key.
4. If the stored value equals `info.current`: nothing to do.

The post-upgrade modal shows `current_release_name` / `current_release_notes` /
`current_release_url` from the API. If `current_release_notes` is null (dev/untagged
build, or network failure), the modal is suppressed silently.

**Precedence:** when both flows could fire simultaneously (e.g. just upgraded to a version
that is not yet the latest), the post-upgrade modal takes precedence. The two flows use
different localStorage keys and naturally don't collide after the latest is reached
(`update_available` becomes false, so the update-available modal won't fire).

## "Update available" dismissal behavior

`localStorage['fb_last_seen_version']` stores the last version the user dismissed.
- Key absent → first-ever run → modal suppressed.
- Key equals `latest` → already dismissed for this version → modal suppressed.
- Key differs from `latest` → modal shown; on close, key is updated to `latest`.

Both modals can be dismissed by clicking ×, clicking the "Got it" button, clicking the
backdrop, or pressing Escape.
