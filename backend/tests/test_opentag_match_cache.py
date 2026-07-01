"""Tests for opentag_match_cache — content-aware fingerprint and staleness detection."""

from __future__ import annotations

from app.core.opentag_match_cache import build_fingerprint, inputs_stale
from app.schemas.spoolman import SpoolmanFilament, SpoolmanVendor

from app.api.opentag import _build_sm_content_hash


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fil(name: str, vendor: str | None = None, material: str | None = None) -> SpoolmanFilament:
    return SpoolmanFilament(
        id=1,
        name=name,
        vendor=SpoolmanVendor(id=1, name=vendor) if vendor else None,
        material=material,
        color_hex=None,
        extra={},
    )


_CONFIG = dict(aliases_raw="", tag_map={}, field_names={"uuid": "x", "ignore": "y"})


# ---------------------------------------------------------------------------
# _build_sm_content_hash
# ---------------------------------------------------------------------------


def test_content_hash_same_set_stable():
    """Same filament set always produces the same hash."""
    filaments = [
        _fil("PLA Red", vendor="ELEGOO", material="PLA"),
        _fil("PLA Blue", vendor="ELEGOO", material="PLA"),
    ]
    h1 = _build_sm_content_hash(filaments)
    h2 = _build_sm_content_hash(filaments)
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_content_hash_order_independent():
    """Order of filaments does not matter — hash is order-independent."""
    a = _fil("PLA Red", vendor="ELEGOO")
    b = _fil("PLA Blue", vendor="ELEGOO")
    assert _build_sm_content_hash([a, b]) == _build_sm_content_hash([b, a])


def test_content_hash_vendor_rename_changes_hash():
    """A vendor rename (count unchanged) produces a different hash."""
    before = [_fil("PLA Red", vendor="elegoo"), _fil("PLA Blue", vendor="elegoo")]
    after = [_fil("PLA Red", vendor="ELEGOO"), _fil("PLA Blue", vendor="ELEGOO")]
    assert _build_sm_content_hash(before) != _build_sm_content_hash(after)


def test_content_hash_name_rename_changes_hash():
    """A filament name change (count unchanged) produces a different hash."""
    before = [_fil("PLA Red", vendor="ELEGOO")]
    after = [_fil("PLA Red Silk", vendor="ELEGOO")]
    assert _build_sm_content_hash(before) != _build_sm_content_hash(after)


def test_content_hash_no_vendor():
    """Filaments without a vendor hash without error."""
    filaments = [_fil("PLA Red", vendor=None)]
    h = _build_sm_content_hash(filaments)
    assert len(h) == 64


def test_content_hash_empty_list():
    """Empty filament list produces a consistent hash."""
    h1 = _build_sm_content_hash([])
    h2 = _build_sm_content_hash([])
    assert h1 == h2


# ---------------------------------------------------------------------------
# build_fingerprint + inputs_stale
# ---------------------------------------------------------------------------


def test_inputs_stale_same_hash_not_stale():
    """Same fingerprint components → not stale."""
    filaments = [_fil("PLA Red", vendor="ELEGOO", material="PLA")]
    h = _build_sm_content_hash(filaments)
    fp = build_fingerprint(
        dataset_count=100,
        dataset_fetched_at="2026-01-01T00:00:00Z",
        dataset_commit_sha="abc123",
        sm_content_hash=h,
        **_CONFIG,
    )
    assert inputs_stale(fp, fp) is False


def test_inputs_stale_vendor_rename_detected():
    """A vendor rename (count unchanged) flips stale_inputs to True."""
    before = [_fil("PLA Red", vendor="elegoo"), _fil("PETG", vendor="elegoo")]
    after = [_fil("PLA Red", vendor="ELEGOO"), _fil("PETG", vendor="ELEGOO")]
    h_before = _build_sm_content_hash(before)
    h_after = _build_sm_content_hash(after)

    fp_cached = build_fingerprint(
        dataset_count=2,
        dataset_fetched_at="2026-01-01T00:00:00Z",
        dataset_commit_sha="abc123",
        sm_content_hash=h_before,
        **_CONFIG,
    )
    fp_current = build_fingerprint(
        dataset_count=2,
        dataset_fetched_at="2026-01-01T00:00:00Z",
        dataset_commit_sha="abc123",
        sm_content_hash=h_after,
        **_CONFIG,
    )

    assert inputs_stale(fp_cached, fp_current) is True


def test_inputs_stale_none_cached_always_stale():
    """No cached fingerprint → always stale."""
    fp = build_fingerprint(
        dataset_count=5,
        dataset_fetched_at=None,
        sm_content_hash="x",
        **_CONFIG,
    )
    assert inputs_stale(None, fp) is True


def test_inputs_stale_old_cache_missing_sm_content_hash():
    """Old cache with sm_count key (not sm_content_hash) is treated as stale."""
    old_fp = {"dataset": "sha:abc123", "sm_count": 3, "config_hash": "xxx"}
    filaments = [_fil("PLA Red", vendor="ELEGOO")]
    current_fp = build_fingerprint(
        dataset_count=100,
        dataset_fetched_at="2026-01-01T00:00:00Z",
        dataset_commit_sha="abc123",
        sm_content_hash=_build_sm_content_hash(filaments),
        **_CONFIG,
    )
    assert inputs_stale(old_fp, current_fp) is True
