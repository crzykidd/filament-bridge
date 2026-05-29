"""Tests for core/fields.py — field-mapping resolution."""

from unittest.mock import MagicMock

from app.core.fields import get_fdb_field_value, resolve_field_map, should_skip_inherited
from app.schemas.filamentdb import FDBFilamentDetail, FDBTemperatures


def _mock_settings(field_mappings="", excludes=""):
    s = MagicMock()
    if field_mappings:
        pairs = {}
        for pair in field_mappings.split(","):
            k, v = pair.split("=")
            pairs[k.strip()] = v.strip()
        s.parsed_field_mappings = pairs
    else:
        s.parsed_field_mappings = {}
    s.parsed_field_mapping_excludes = {e.strip() for e in excludes.split(",") if e.strip()}
    return s


def _fdb_detail(**kwargs):
    defaults = {
        "_id": "aaa",
        "name": "Test PLA",
        "_inherited": [],
    }
    defaults.update(kwargs)
    return FDBFilamentDetail.model_validate(defaults)


class TestResolveFieldMap:
    def test_explicit_mapping(self):
        s = _mock_settings(field_mappings="density=sm_density")
        maps = resolve_field_map(s, set(), "filamentdb")
        assert len(maps) == 1
        assert maps[0].fdb_path == "density"
        assert maps[0].sm_key == "sm_density"
        assert maps[0].direction == "fdb_to_sm"

    def test_auto_match_by_name(self):
        s = _mock_settings()
        # "density" is both a valid FDB field and in the SM extra keys
        maps = resolve_field_map(s, {"density"}, "filamentdb")
        assert any(m.fdb_path == "density" and m.sm_key == "density" for m in maps)

    def test_explicit_takes_priority_over_auto(self):
        s = _mock_settings(field_mappings="density=custom_density")
        maps = resolve_field_map(s, {"density"}, "filamentdb")
        # Only one mapping for density, and it's the explicit one
        density_maps = [m for m in maps if m.fdb_path == "density"]
        assert len(density_maps) == 1
        assert density_maps[0].sm_key == "custom_density"

    def test_excludes_filter_explicit(self):
        s = _mock_settings(field_mappings="density=sm_density", excludes="density")
        maps = resolve_field_map(s, set(), "filamentdb")
        assert not maps

    def test_excludes_filter_auto(self):
        s = _mock_settings(excludes="density")
        maps = resolve_field_map(s, {"density"}, "filamentdb")
        assert not any(m.fdb_path == "density" for m in maps)

    def test_direction_sm_to_fdb(self):
        s = _mock_settings(field_mappings="density=sm_density")
        maps = resolve_field_map(s, set(), "spoolman")
        assert maps[0].direction == "sm_to_fdb"

    def test_unknown_sm_key_not_auto_matched(self):
        s = _mock_settings()
        # "spoolman_custom" is not in FDB_SYNCABLE_FIELDS
        maps = resolve_field_map(s, {"spoolman_custom"}, "filamentdb")
        assert not any(m.sm_key == "spoolman_custom" for m in maps)


class TestGetFdbFieldValue:
    def test_scalar_field(self):
        detail = _fdb_detail(density=1.24)
        assert get_fdb_field_value(detail, "density") == 1.24

    def test_dotted_path(self):
        detail = _fdb_detail(temperatures=FDBTemperatures(nozzle=215.0))
        assert get_fdb_field_value(detail, "temperatures.nozzle") == 215.0

    def test_missing_field_returns_none(self):
        detail = _fdb_detail()
        assert get_fdb_field_value(detail, "density") is None

    def test_dotted_with_null_parent(self):
        detail = _fdb_detail(temperatures=None)
        assert get_fdb_field_value(detail, "temperatures.nozzle") is None


class TestShouldSkipInherited:
    def test_inherited_field(self):
        detail = _fdb_detail(**{"_inherited": ["density", "spoolWeight"]})
        assert should_skip_inherited(detail, "density") is True

    def test_non_inherited_field(self):
        detail = _fdb_detail(**{"_inherited": ["density"]})
        assert should_skip_inherited(detail, "color") is False

    def test_dotted_path_checks_top_level(self):
        detail = _fdb_detail(**{"_inherited": ["temperatures"]})
        assert should_skip_inherited(detail, "temperatures.nozzle") is True

    def test_empty_inherited_list(self):
        detail = _fdb_detail()
        assert should_skip_inherited(detail, "density") is False
