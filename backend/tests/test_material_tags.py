"""Tests for core/material_tags.py — OpenPrintTag finish-ID helpers."""


from app.core.material_tags import (
    DEFAULT_MATERIAL_TAG_IDS,
    MANAGED_FINISH_IDS,
    finish_ids_from_text,
    parse_material_tag_ids_config,
    parse_material_tags,
    serialize_material_tags,
    strip_finish_words,
)
from app.schemas.spoolman import encode_extra_value


# ---------------------------------------------------------------------------
# Seed map sanity checks
# ---------------------------------------------------------------------------


class TestSeedMap:
    def test_silk_is_17(self):
        assert DEFAULT_MATERIAL_TAG_IDS["silk"] == 17

    def test_matte_is_16(self):
        assert DEFAULT_MATERIAL_TAG_IDS["matte"] == 16

    def test_high_speed_is_71(self):
        assert DEFAULT_MATERIAL_TAG_IDS["high-speed"] == 71

    def test_hs_alias_is_71(self):
        assert DEFAULT_MATERIAL_TAG_IDS["hs"] == 71

    def test_rapid_alias_is_71(self):
        assert DEFAULT_MATERIAL_TAG_IDS["rapid"] == 71

    def test_carbon_is_31(self):
        assert DEFAULT_MATERIAL_TAG_IDS["carbon"] == 31

    def test_cf_alias_is_31(self):
        assert DEFAULT_MATERIAL_TAG_IDS["cf"] == 31

    def test_glow_is_24(self):
        assert DEFAULT_MATERIAL_TAG_IDS["glow"] == 24

    def test_all_managed_ids_in_map(self):
        # Every seed value must be in MANAGED_FINISH_IDS
        for _kw, tag_id in DEFAULT_MATERIAL_TAG_IDS.items():
            assert tag_id in MANAGED_FINISH_IDS, f"seed id {tag_id} not in MANAGED_FINISH_IDS"


# ---------------------------------------------------------------------------
# serialize_material_tags
# ---------------------------------------------------------------------------


class TestSerializeMaterialTags:
    def test_single_id(self):
        assert serialize_material_tags([17]) == "17"

    def test_two_ids_sorted(self):
        # Input unsorted — output must be sorted
        assert serialize_material_tags([28, 17]) == "17,28"

    def test_canonical_example(self):
        assert serialize_material_tags([17, 28]) == "17,28"

    def test_empty_returns_empty_string(self):
        assert serialize_material_tags([]) == ""

    def test_deduplicates(self):
        assert serialize_material_tags([17, 17, 28]) == "17,28"

    def test_frozenset_input(self):
        result = serialize_material_tags(frozenset({17, 28}))
        assert result == "17,28"


# ---------------------------------------------------------------------------
# parse_material_tags
# ---------------------------------------------------------------------------


class TestParseMaterialTags:
    def test_csv_single(self):
        assert parse_material_tags("17") == [17]

    def test_csv_two(self):
        assert parse_material_tags("17,28") == [17, 28]

    def test_csv_unsorted_returned_sorted(self):
        assert parse_material_tags("28,17") == [17, 28]

    def test_empty_string_returns_empty_list(self):
        assert parse_material_tags("") == []

    def test_none_returns_empty_list(self):
        assert parse_material_tags(None) == []

    def test_legacy_json_array_string(self):
        # Pre-fix Spoolman rejected these on write, but any stored value round-trips
        assert parse_material_tags("[17]") == [17]

    def test_legacy_json_array_multiple(self):
        assert parse_material_tags("[17, 28]") == [17, 28]

    def test_real_list_input(self):
        # Already-decoded list (e.g. from decode_extra_value on a legacy entry)
        assert parse_material_tags([17]) == [17]

    def test_real_list_multiple(self):
        assert parse_material_tags([28, 17]) == [17, 28]

    def test_deduplicates_csv(self):
        assert parse_material_tags("17,17,28") == [17, 28]

    def test_round_trip(self):
        ids = [17, 28]
        serialized = serialize_material_tags(ids)
        assert parse_material_tags(serialized) == ids

    def test_unknown_type_returns_empty(self):
        assert parse_material_tags(12345) == []


# ---------------------------------------------------------------------------
# parse_material_tag_ids_config
# ---------------------------------------------------------------------------


class TestParseConfig:
    def test_basic_parse(self):
        result = parse_material_tag_ids_config("silk=17,matte=16")
        assert result == {"silk": 17, "matte": 16}

    def test_empty_string_returns_empty(self):
        result = parse_material_tag_ids_config("")
        assert result == {}

    def test_whitespace_tolerant(self):
        result = parse_material_tag_ids_config(" silk = 17 , matte = 16 ")
        assert result == {"silk": 17, "matte": 16}

    def test_malformed_pair_skipped(self):
        result = parse_material_tag_ids_config("silk=17,not-valid,matte=16")
        assert result == {"silk": 17, "matte": 16}

    def test_non_integer_id_skipped(self):
        result = parse_material_tag_ids_config("silk=abc,matte=16")
        assert result == {"matte": 16}

    def test_keyword_lowercased(self):
        result = parse_material_tag_ids_config("SILK=17")
        assert "silk" in result
        assert result["silk"] == 17

    def test_override_replaces_seed_entirely(self):
        # An override with only one keyword should produce exactly that keyword.
        result = parse_material_tag_ids_config("custom=99")
        assert result == {"custom": 99}
        assert "silk" not in result  # seed not merged in


# ---------------------------------------------------------------------------
# finish_ids_from_text
# ---------------------------------------------------------------------------


class TestFinishIdsFromText:
    def test_silk_in_name(self):
        ids = finish_ids_from_text("PLA Silk Red", None)
        assert 17 in ids

    def test_matte_in_name(self):
        ids = finish_ids_from_text("PLA Matte", None)
        assert 16 in ids

    def test_silk_in_material(self):
        ids = finish_ids_from_text("Red", "PLA Silk")
        assert 17 in ids

    def test_multi_tag_both_keywords(self):
        # A name that would match both "silk" and "matte" should return both IDs.
        ids = finish_ids_from_text("PLA Silk Matte Fusion", None)
        assert 17 in ids  # silk
        assert 16 in ids  # matte

    def test_no_keywords_returns_empty(self):
        ids = finish_ids_from_text("PLA Standard Red", None)
        assert len(ids) == 0

    def test_none_name_and_material(self):
        ids = finish_ids_from_text(None, None)
        assert ids == set()

    def test_case_insensitive(self):
        ids = finish_ids_from_text("PLA SILK", None)
        assert 17 in ids

    def test_word_boundary_no_false_positive(self):
        # "silky" should not match "silk" keyword (word boundary).
        ids = finish_ids_from_text("Silky PLA", None)
        assert 17 not in ids

    def test_custom_map_overrides_defaults(self):
        custom_map = {"shiny": 99}
        ids = finish_ids_from_text("PLA Shiny", None, custom_map)
        assert 99 in ids
        # "silk" no longer in map — should not match.
        ids2 = finish_ids_from_text("PLA Silk", None, custom_map)
        assert 17 not in ids2

    def test_cf_keyword_maps_to_31(self):
        ids = finish_ids_from_text("PLA-CF", None)
        assert 31 in ids

    def test_carbon_keyword_maps_to_31(self):
        ids = finish_ids_from_text("Carbon Fiber PLA", None)
        assert 31 in ids

    def test_high_speed_hyphenated(self):
        ids = finish_ids_from_text("PLA High-Speed", None)
        assert 71 in ids

    def test_hs_abbreviation(self):
        ids = finish_ids_from_text("PETG HS", None)
        assert 71 in ids

    def test_rapid_maps_to_71(self):
        ids = finish_ids_from_text("PLA Rapid", None)
        assert 71 in ids

    def test_returns_set_of_ints(self):
        ids = finish_ids_from_text("PLA Silk", None)
        assert isinstance(ids, set)
        assert all(isinstance(i, int) for i in ids)


# ---------------------------------------------------------------------------
# strip_finish_words
# ---------------------------------------------------------------------------


class TestStripFinishWords:
    def test_strips_silk_from_pla_silk(self):
        result = strip_finish_words("PLA Silk")
        assert result == "PLA"

    def test_strips_matte_from_pla_matte(self):
        result = strip_finish_words("PLA Matte")
        assert result == "PLA"

    def test_keeps_pla_unchanged(self):
        result = strip_finish_words("PLA")
        assert result == "PLA"

    def test_keeps_petg_unchanged(self):
        result = strip_finish_words("PETG")
        assert result == "PETG"

    def test_keeps_pla_plus_unchanged(self):
        # "PLA+" must not be altered by finish stripping
        result = strip_finish_words("PLA+")
        assert result == "PLA+"

    def test_strips_cf_suffix(self):
        # "PETG-CF" → "PETG"
        result = strip_finish_words("PETG-CF")
        # cf is in the map; should be stripped
        assert "cf" not in result.lower()

    def test_none_returns_empty(self):
        result = strip_finish_words(None)
        assert result == ""

    def test_empty_string_returns_empty(self):
        result = strip_finish_words("")
        assert result == ""

    def test_strips_high_speed(self):
        result = strip_finish_words("ABS High-Speed")
        assert "high-speed" not in result.lower()
        assert "abs" in result.lower()

    def test_case_insensitive_stripping(self):
        result = strip_finish_words("PLA SILK")
        assert "silk" not in result.lower()

    def test_custom_map(self):
        custom = {"special": 99}
        result = strip_finish_words("PLA Special Edition", custom)
        assert "special" not in result.lower()
        assert "pla" in result.lower()

    def test_no_match_returns_original(self):
        result = strip_finish_words("PETG Standard")
        assert "petg" in result.lower()

    def test_pla_silk_flap_safety(self):
        # The core flap-safety property: strip_finish_words("PLA Silk") == "PLA"
        # so "PLA Silk" (SM) vs "PLA" (FDB type) do not cause a perpetual diff.
        assert strip_finish_words("PLA Silk") == "PLA"


# ---------------------------------------------------------------------------
# Wire-format contract: serialize_material_tags + encode_extra_value
# Spoolman text extras must be JSON-quoted CSV strings, NOT JSON arrays.
# Regression guard for the wizard Pass-2.6 bug where encode_extra_value was
# called directly on a Python list → "[17]" wire value → Spoolman 400.
# ---------------------------------------------------------------------------


class TestWireFormat:
    def test_single_id_wire_format(self):
        # encode_extra_value(serialize_material_tags([17])) → '"17"' (JSON-quoted CSV)
        # NOT encode_extra_value([17])               → '"[17]"' or '[17]'
        wire = encode_extra_value(serialize_material_tags([17]))
        assert wire == '"17"'

    def test_two_ids_wire_format(self):
        wire = encode_extra_value(serialize_material_tags([17, 28]))
        assert wire == '"17,28"'

    def test_bare_list_encoding_is_wrong(self):
        # Confirm the old (broken) path produces the wrong format.
        wrong = encode_extra_value([17])
        assert wrong == "[17]"  # JSON array — NOT what Spoolman text fields expect

    def test_wire_not_json_array(self):
        # The correct wire value must not start with '['.
        wire = encode_extra_value(serialize_material_tags([16, 17]))
        decoded_outer = __import__("json").loads(wire)
        assert isinstance(decoded_outer, str), "outer JSON must decode to a string, not a list"
        assert "," in decoded_outer or decoded_outer.isdigit()  # CSV form
