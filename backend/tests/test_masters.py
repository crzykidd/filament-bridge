"""Tests for the canonical synthetic master/container detector (GitHub #3)."""

from app.core.masters import is_master_fdb
from app.schemas.filamentdb import FDBFilament


def _fil(id="f1", name="ELEGOO PLA Red", has_variants=False):
    return FDBFilament(_id=id, name=name, hasVariants=has_variants)


def test_plain_filament_is_not_master():
    assert is_master_fdb(_fil(), marker="(Master)") is False


def test_has_variants_is_master():
    assert is_master_fdb(_fil(has_variants=True), marker="(Master)") is True


def test_marker_suffix_is_master():
    # hasVariants=False but the name carries the marker (e.g. a single-cluster container).
    fil = _fil(name="Buddy3D PLA Marble (Master)")
    assert is_master_fdb(fil, marker="(Master)") is True


def test_marker_suffix_ignored_without_marker():
    # No marker supplied (connectivity-only callers) → marker signal is inert.
    fil = _fil(name="Buddy3D PLA Marble (Master)")
    assert is_master_fdb(fil, marker=None) is False


def test_synthetic_id_is_master_even_without_other_signals():
    fil = _fil(id="synthetic1", name="Plain Name")
    assert is_master_fdb(fil, marker="(Master)", synthetic_ids={"synthetic1"}) is True


def test_marker_must_be_space_delimited_suffix():
    # A name that merely contains the marker mid-string is not a master.
    fil = _fil(name="(Master) Edition PLA")
    assert is_master_fdb(fil, marker="(Master)") is False
