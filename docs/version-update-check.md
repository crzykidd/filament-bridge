# Version display and update check

## Purpose

The bridge sidebar always shows the running version with a link to its GitHub release.
When a newer release exists, an "↑ vX.Y.Z" pill appears next to the version and a
one-time modal pops up with the release notes. Dev builds suppress the update nag.

## `GET /api/version`

Public endpoint (no auth required). Returns:

```json
{
  "current":        "0.1.0",
  "latest":         "0.2.0",
  "update_available": true,
  "release_url":    "https://github.com/crzykidd/filament-bridge/releases/tag/v0.2.0",
  "release_name":   "v0.2.0",
  "release_notes":  "## What's new\n...",
  "channel":        "release",
  "commit":         null,
  "build":          "v0.1.0",
  "is_dev":         false
}
```

| Field | Description |
|---|---|
| `current` | Running version from `backend/app/__init__.py:__version__` |
| `latest` | Tag name from GitHub releases (leading `v` stripped), or `null` on error |
| `update_available` | `true` when `latest > current` AND `channel == "release"` |
| `release_url` | Link to the GitHub release page |
| `release_name` | GitHub release title |
| `release_notes` | GitHub release body (markdown, treated as plain text in the UI) |
| `channel` | `"release"` (default) or `"dev"` — baked in at build time |
| `commit` | Short git SHA baked in at build time, or `null` |
| `build` | Display label: `"v0.1.0"` on release; `"v0.1.0-dev+abc1234"` on dev |
| `is_dev` | `true` when `channel != "release"` |

## GitHub check

- Backend calls `https://api.github.com/repos/crzykidd/filament-bridge/releases/latest`
  with a 3-second timeout and `User-Agent: filament-bridge`.
- Result is cached in-memory for 6 hours. On any network or parse error, the last good
  cached value is served; if no cache exists, `latest` is `null` and
  `update_available` is `false`. The endpoint never returns 5xx.
- The browser never calls GitHub directly.

## Dev / channel builds

`BRIDGE_CHANNEL` and `BRIDGE_COMMIT` are environment variables read at startup from
`backend/app/__init__.py`. They are baked into the Docker image as env vars via the
`BUILD_CHANNEL` and `GIT_COMMIT` build args (placed near the end of the Dockerfile
to avoid busting earlier cache layers).

| Channel | Version label example |
|---|---|
| `release` (default) | `v0.1.0` |
| `dev` (no SHA) | `v0.1.0-dev` |
| `dev` (with SHA) | `v0.1.0-dev+abc1234` |

To stamp the dev compose build with the current commit:

```bash
GIT_COMMIT=$(git rev-parse --short HEAD) docker compose -f docker-compose.dev.yml build
```

Dev builds force `update_available=false` even when `latest > current`, suppressing the
update nag. (`latest` is still reported for informational purposes.)

## Frontend — version badge

`Layout.tsx` renders a `VersionBadge` component that fetches `/api/version` once on
mount. It shows:
- The `build` label as a link to the current release tag (or the latest release URL
  when `update_available` is false and `release_url` is present).
- An "↑ vX.Y.Z" pill linking to `release_url` when `update_available` is true.
- A one-time release-notes modal when `update_available` is true and the `latest` version
  has not already been dismissed (per-version dismissal stored in
  `localStorage['fb_last_seen_version']`). The modal does not appear on the very first
  run (no stored value) to avoid surprising new installs.
- Markdown from `release_notes` is rendered as `<pre>` plain text — never as `innerHTML`.

## Dismissal behavior

`localStorage['fb_last_seen_version']` stores the last version the user dismissed.
- Key absent → first-ever run → modal suppressed.
- Key equals `latest` → already dismissed for this version → modal suppressed.
- Key differs from `latest` → modal shown; on close, key is updated to `latest`.

The modal can be dismissed by clicking ×, clicking the "Got it" button, clicking the
backdrop, or pressing Escape.
