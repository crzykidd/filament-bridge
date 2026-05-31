"""Tests for core/version.py — semver parsing and the multicolor version gate."""

from app.core.version import MULTICOLOR_MIN_FDB, parse_semver, version_gte


class TestParseSemver:
    def test_basic(self):
        assert parse_semver("1.33.0") == (1, 33, 0)

    def test_v_prefix(self):
        assert parse_semver("v1.33.0") == (1, 33, 0)

    def test_prerelease_suffix_dropped(self):
        assert parse_semver("1.33.0-rc1") == (1, 33, 0)

    def test_build_suffix_dropped(self):
        assert parse_semver("1.33.0+build5") == (1, 33, 0)

    def test_two_part(self):
        assert parse_semver("1.33") == (1, 33, 0)

    def test_none(self):
        assert parse_semver(None) == (0, 0, 0)

    def test_garbage(self):
        assert parse_semver("not-a-version") == (0, 0, 0)


class TestVersionGte:
    def test_exact_min_passes(self):
        assert version_gte("1.33.0", MULTICOLOR_MIN_FDB) is True

    def test_newer_passes(self):
        assert version_gte("1.33.1", MULTICOLOR_MIN_FDB) is True
        assert version_gte("2.0.0", MULTICOLOR_MIN_FDB) is True

    def test_older_fails(self):
        assert version_gte("1.32.9", MULTICOLOR_MIN_FDB) is False
        assert version_gte("1.32.0", MULTICOLOR_MIN_FDB) is False

    def test_none_fails(self):
        assert version_gte(None, MULTICOLOR_MIN_FDB) is False
