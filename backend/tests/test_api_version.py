"""Tests for app/api/version.py — semver helpers and /api/version endpoint behavior."""

from __future__ import annotations

from unittest.mock import patch


from app import __version__ as APP_VERSION
from app.api.version import _is_newer, _parse_semver


# ---------------------------------------------------------------------------
# _parse_semver
# ---------------------------------------------------------------------------


class TestParseSemver:
    def test_basic(self):
        assert _parse_semver("1.2.3") == (1, 2, 3)

    def test_v_prefix(self):
        assert _parse_semver("v1.2.3") == (1, 2, 3)

    def test_two_part(self):
        assert _parse_semver("1.2") == (1, 2)

    def test_prerelease_suffix_dropped(self):
        assert _parse_semver("1.2.3-rc1") == (1, 2, 3)

    def test_build_suffix_dropped(self):
        assert _parse_semver("1.2.3+build5") == (1, 2, 3)

    def test_garbage(self):
        assert _parse_semver("not-a-version") is None

    def test_empty(self):
        assert _parse_semver("") is None


# ---------------------------------------------------------------------------
# _is_newer
# ---------------------------------------------------------------------------


class TestIsNewer:
    def test_newer_patch(self):
        assert _is_newer("0.1.1", "0.1.0") is True

    def test_newer_minor(self):
        assert _is_newer("0.2.0", "0.1.9") is True

    def test_newer_major(self):
        assert _is_newer("1.0.0", "0.9.9") is True

    def test_equal(self):
        assert _is_newer("0.1.0", "0.1.0") is False

    def test_older(self):
        assert _is_newer("0.0.9", "0.1.0") is False

    def test_unparseable_latest(self):
        assert _is_newer("not-a-version", "0.1.0") is False

    def test_unparseable_current(self):
        assert _is_newer("0.2.0", "not-a-version") is False

    def test_v_prefix_tolerated(self):
        assert _is_newer("v0.2.0", "v0.1.0") is True


# ---------------------------------------------------------------------------
# GET /api/version endpoint
# ---------------------------------------------------------------------------


def _make_client():
    """Build a minimal TestClient for the version router only."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.version import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


class TestVersionEndpoint:
    def test_returns_current_version(self):
        """Endpoint must include current version even when GitHub fetch fails."""
        with patch("app.api.version._fetch_github", side_effect=OSError("no network")):
            client = _make_client()
            resp = client.get("/api/version")
        assert resp.status_code == 200
        data = resp.json()
        assert data["current"] == APP_VERSION
        assert data["update_available"] is False
        assert data["latest"] is None

    def test_no_raise_on_network_error(self):
        """Endpoint must return 200 (never 500) when GitHub is unreachable."""
        import urllib.error

        with patch(
            "app.api.version._fetch_github",
            side_effect=urllib.error.URLError("unreachable"),
        ):
            client = _make_client()
            resp = client.get("/api/version")
        assert resp.status_code == 200

    def test_update_available_when_newer(self):
        """update_available=True when a newer release exists and channel is release."""
        gh_data = {
            "latest": "0.2.0",
            "release_url": "https://github.com/crzykidd/filament-bridge/releases/tag/v0.2.0",
            "release_name": "v0.2.0",
            "release_notes": "Some notes",
        }
        import app.api.version as version_mod

        with (
            patch.object(version_mod, "__channel__", "release"),
            patch.object(version_mod, "__version__", "0.1.0"),
            patch("app.api.version._fetch_github", return_value=gh_data),
            patch.dict("app.api.version._cache", {}, clear=True),
        ):
            client = _make_client()
            resp = client.get("/api/version")
        assert resp.status_code == 200
        data = resp.json()
        assert data["update_available"] is True
        assert data["latest"] == "0.2.0"

    def test_update_suppressed_on_dev(self):
        """update_available=False even with a newer release when channel is dev."""
        gh_data = {
            "latest": "9.9.9",
            "release_url": "https://example.com/releases/tag/v9.9.9",
            "release_name": "v9.9.9",
            "release_notes": "notes",
        }
        import app.api.version as version_mod

        with (
            patch.object(version_mod, "__channel__", "dev"),
            patch.object(version_mod, "__version__", "0.1.0"),
            patch("app.api.version._fetch_github", return_value=gh_data),
            patch.dict("app.api.version._cache", {}, clear=True),
        ):
            client = _make_client()
            resp = client.get("/api/version")
        assert resp.status_code == 200
        data = resp.json()
        assert data["update_available"] is False
        assert data["is_dev"] is True

    def test_build_label_release(self):
        """Build label is 'v{version}' on the release channel."""
        import app.api.version as version_mod

        with (
            patch.object(version_mod, "__channel__", "release"),
            patch.object(version_mod, "__version__", "0.1.0"),
            patch.object(version_mod, "__commit__", None),
            patch("app.api.version._fetch_github", side_effect=OSError("no network")),
            patch.dict("app.api.version._cache", {}, clear=True),
        ):
            client = _make_client()
            resp = client.get("/api/version")
        assert resp.json()["build"] == "v0.1.0"

    def test_build_label_dev_with_commit(self):
        """Build label includes channel suffix and short SHA on dev."""
        import app.api.version as version_mod

        with (
            patch.object(version_mod, "__channel__", "dev"),
            patch.object(version_mod, "__version__", "0.1.0"),
            patch.object(version_mod, "__commit__", "abc1234"),
            patch("app.api.version._fetch_github", side_effect=OSError("no network")),
            patch.dict("app.api.version._cache", {}, clear=True),
        ):
            client = _make_client()
            resp = client.get("/api/version")
        assert resp.json()["build"] == "v0.1.0-dev+abc1234"
