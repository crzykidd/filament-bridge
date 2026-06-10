"""GET /api/version — current version, channel, commit, and GitHub update check.

Public endpoint (no auth required): current version / channel / commit are not
sensitive, and the badge must be visible even if the session has expired.
Caches the GitHub releases API response in-memory for 6 hours; degrades
gracefully on any network or parse error.
"""

import logging
import time
import urllib.error
import urllib.request
from json import JSONDecodeError
from json import loads as json_loads
from typing import Any

from fastapi import APIRouter

from app import __channel__, __commit__, __version__

router = APIRouter()
logger = logging.getLogger(__name__)

_GITHUB_URL = "https://api.github.com/repos/crzykidd/filament-bridge/releases/latest"
_TTL_SECONDS = 6 * 3600  # 6 hours

# Module-level cache: {"result": {...}, "fetched_at": float}
_cache: dict[str, Any] = {}


def _parse_semver(v: str) -> tuple[int, ...] | None:
    """Parse a dotted numeric version string, tolerating a leading 'v'.

    Returns a tuple of ints (major, minor, patch) or None if unparseable.
    """
    v = v.strip().lstrip("v")
    # Drop pre-release / build suffixes (e.g. "1.2.3-rc1+build5")
    for sep in ("-", "+"):
        v = v.split(sep)[0]
    parts = v.split(".")
    try:
        result = tuple(int(p) for p in parts if p)
        return result if result else None
    except ValueError:
        return None


def _is_newer(latest: str, current: str) -> bool:
    """Return True if latest > current. False if either is unparseable."""
    lv = _parse_semver(latest)
    cv = _parse_semver(current)
    if lv is None or cv is None:
        return False
    # Pad to equal length for comparison
    length = max(len(lv), len(cv))
    lv_padded = lv + (0,) * (length - len(lv))
    cv_padded = cv + (0,) * (length - len(cv))
    return lv_padded > cv_padded


def _fetch_github() -> dict[str, Any]:
    """Call the GitHub releases API and return parsed fields.

    On any network/parse error, raises an exception — callers handle it.
    """
    req = urllib.request.Request(
        _GITHUB_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "filament-bridge",
        },
    )
    with urllib.request.urlopen(req, timeout=3) as resp:
        body = json_loads(resp.read().decode())

    tag_name: str = body.get("tag_name", "")
    latest = tag_name.lstrip("v")
    return {
        "latest": latest or None,
        "release_url": body.get("html_url"),
        "release_name": body.get("name"),
        "release_notes": body.get("body"),
    }


def _refresh_cache() -> None:
    """Attempt to refresh the in-memory cache from GitHub.

    On failure, logs a warning and leaves the existing cache entry intact
    (so a stale-but-good value continues to be served).
    """
    try:
        data = _fetch_github()
        _cache["result"] = data
        _cache["fetched_at"] = time.monotonic()
        logger.debug("GitHub release check succeeded: latest=%s", data.get("latest"))
    except (urllib.error.URLError, TimeoutError, JSONDecodeError, KeyError, OSError) as exc:
        logger.warning("GitHub release check failed: %s", exc)


def _cached_github() -> dict[str, Any]:
    """Return the cached GitHub result, refreshing if stale or absent."""
    now = time.monotonic()
    fetched_at = _cache.get("fetched_at")
    if fetched_at is None or (now - fetched_at) > _TTL_SECONDS:
        _refresh_cache()
    return _cache.get("result") or {}


def _build_label(current: str) -> str:
    """Compute the display version label (includes leading 'v').

    release channel → ``v0.1.0``
    dev channel     → ``v0.1.0-dev`` or ``v0.1.0-dev+8e32bb1`` when a commit is baked in.
    """
    if __channel__ == "release":
        return f"v{current}"
    suffix = f"-{__channel__}"
    if __commit__:
        suffix += f"+{__commit__}"
    return f"v{current}{suffix}"


@router.get("/version")
async def get_version() -> dict:
    current = __version__
    is_dev = __channel__ != "release"
    build = _build_label(current)

    gh = _cached_github()
    latest = gh.get("latest")
    update_available = _is_newer(latest, current) if latest else False
    if is_dev:
        # Dev builds are typically ahead of the latest release; suppress the nag.
        update_available = False

    return {
        "current": current,
        "latest": latest,
        "update_available": update_available,
        "release_url": gh.get("release_url"),
        "release_name": gh.get("release_name"),
        "release_notes": gh.get("release_notes"),
        "channel": __channel__,
        "commit": __commit__,
        "build": build,
        "is_dev": is_dev,
    }
