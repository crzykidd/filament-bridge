"""Tests for the master-level group-default helpers (issue #76)."""

from app.core.masters_defaults import group_mode_defaults, resolve_family_tare
from app.schemas.filamentdb import FDBFilament


def _fil(id, spool_weight=None, parent_id=None):
    return FDBFilament(_id=id, name=f"fil-{id}", spoolWeight=spool_weight, parentId=parent_id)


# ---------------------------------------------------------------------------
# group_mode_defaults
# ---------------------------------------------------------------------------


def test_group_mode_defaults_picks_majority_value():
    result = group_mode_defaults({"spool_weight": [200.0, 200.0, 250.0]})
    assert result == {"spool_weight": 200.0}


def test_group_mode_defaults_tie_break_lowest_wins():
    # 200 and 250 each appear twice — deterministic tie-break picks the lower.
    result = group_mode_defaults({"spool_weight": [200.0, 250.0, 200.0, 250.0]})
    assert result == {"spool_weight": 200.0}


def test_group_mode_defaults_skips_field_when_all_null():
    result = group_mode_defaults({"density": [None, None]})
    assert "density" not in result


def test_group_mode_defaults_ignores_nulls_among_present_values():
    result = group_mode_defaults({"diameter": [None, 1.75, 1.75, None]})
    assert result == {"diameter": 1.75}


def test_group_mode_defaults_multiple_fields_independent():
    result = group_mode_defaults({
        "spool_weight": [200.0, 200.0],
        "type": ["PLA", "PETG", "PLA"],
        "density": [None, None],
    })
    assert result == {"spool_weight": 200.0, "type": "PLA"}


def test_group_mode_defaults_empty_input():
    assert group_mode_defaults({}) == {}


# ---------------------------------------------------------------------------
# resolve_family_tare
# ---------------------------------------------------------------------------


def test_resolve_family_tare_none_when_no_master_id():
    fdb_filaments = [_fil("m1", spool_weight=200.0)]
    assert resolve_family_tare(fdb_filaments, None) is None


def test_resolve_family_tare_uses_masters_own_value():
    master = _fil("m1", spool_weight=154.0)
    child = _fil("c1", spool_weight=200.0, parent_id="m1")
    assert resolve_family_tare([master, child], "m1") == 154.0


def test_resolve_family_tare_falls_back_to_variant_mode():
    master = _fil("m1", spool_weight=None)
    children = [
        _fil("c1", spool_weight=200.0, parent_id="m1"),
        _fil("c2", spool_weight=200.0, parent_id="m1"),
        _fil("c3", spool_weight=250.0, parent_id="m1"),
    ]
    assert resolve_family_tare([master, *children], "m1") == 200.0


def test_resolve_family_tare_none_when_master_and_children_unknown():
    master = _fil("m1", spool_weight=None)
    child = _fil("c1", spool_weight=None, parent_id="m1")
    assert resolve_family_tare([master, child], "m1") is None


def test_resolve_family_tare_none_when_master_not_found():
    # master id supplied but not present among fdb_filaments (e.g. synthetic
    # container race / stale caller data) — no crash, just no known tare.
    assert resolve_family_tare([], "missing-id") is None


def test_resolve_family_tare_ignores_unrelated_children():
    master = _fil("m1", spool_weight=None)
    unrelated_child = _fil("c1", spool_weight=999.0, parent_id="other-master")
    assert resolve_family_tare([master, unrelated_child], "m1") is None
