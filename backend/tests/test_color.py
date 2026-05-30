"""Tests for core/color.py — hex-format helpers and colorName projection."""

from app.core.color import nearest_color_name, project_colorname, to_fdb_color, to_sm_color


# ---------------------------------------------------------------------------
# to_fdb_color — FDB expects '#'-prefixed hex
# ---------------------------------------------------------------------------


class TestToFdbColor:
    def test_bare_hex_gets_hash(self):
        assert to_fdb_color("93BE2F") == "#93BE2F"

    def test_already_prefixed_unchanged(self):
        assert to_fdb_color("#93BE2F") == "#93BE2F"

    def test_none_returns_none(self):
        assert to_fdb_color(None) is None

    def test_empty_string_returns_none(self):
        assert to_fdb_color("") is None

    def test_case_preserved(self):
        assert to_fdb_color("aAbBcC") == "#aAbBcC"

    def test_multiple_hashes_collapsed(self):
        # Defensive: "##93BE2F" should still yield "#93BE2F"
        assert to_fdb_color("##93BE2F") == "#93BE2F"


# ---------------------------------------------------------------------------
# to_sm_color — Spoolman expects bare hex (no '#')
# ---------------------------------------------------------------------------


class TestToSmColor:
    def test_prefixed_hex_stripped(self):
        assert to_sm_color("#93BE2F") == "93BE2F"

    def test_bare_hex_unchanged(self):
        assert to_sm_color("93BE2F") == "93BE2F"

    def test_none_returns_none(self):
        assert to_sm_color(None) is None

    def test_empty_string_returns_none(self):
        assert to_sm_color("") is None

    def test_case_preserved(self):
        assert to_sm_color("#aAbBcC") == "aAbBcC"


# ---------------------------------------------------------------------------
# Round-trip: SM → FDB → SM must be identity (no flap)
# ---------------------------------------------------------------------------


class TestColorRoundTrip:
    def test_sm_to_fdb_to_sm(self):
        original = "93BE2F"
        fdb_form = to_fdb_color(original)
        back_to_sm = to_sm_color(fdb_form)
        assert back_to_sm == original

    def test_fdb_to_sm_to_fdb(self):
        original = "#93BE2F"
        sm_form = to_sm_color(original)
        back_to_fdb = to_fdb_color(sm_form)
        assert back_to_fdb == original


# ---------------------------------------------------------------------------
# nearest_color_name
# ---------------------------------------------------------------------------


class TestNearestColorName:
    def test_exact_red(self):
        assert nearest_color_name("ff0000") == "Red"

    def test_exact_black(self):
        assert nearest_color_name("000000") == "Black"

    def test_exact_white(self):
        assert nearest_color_name("ffffff") == "White"

    def test_exact_blue(self):
        assert nearest_color_name("0000ff") == "Blue"

    def test_exact_green(self):
        assert nearest_color_name("008000") == "Green"

    def test_with_hash_prefix(self):
        assert nearest_color_name("#ff0000") == "Red"

    def test_three_char_hex(self):
        # f00 expands to ff0000 → Red
        assert nearest_color_name("f00") == "Red"

    def test_known_filament_hex_cdde1b(self):
        # cdde1b (R=205, G=222, B=27) is a yellow-green from the live dataset
        result = nearest_color_name("cdde1b")
        assert result in {"GreenYellow", "Gold", "Khaki", "YellowGreen", "Yellow", "OliveDrab"}

    def test_known_filament_hex_68cc16(self):
        # 68cc16 (R=104, G=204, B=22) is a medium green from the live dataset
        result = nearest_color_name("68cc16")
        assert result in {"LawnGreen", "LimeGreen", "YellowGreen", "Lime", "OliveDrab"}

    def test_known_filament_hex_93be2f(self):
        # 93be2f (R=147, G=190, B=47) — primary of the example multicolor filament
        result = nearest_color_name("93be2f")
        assert result in {"YellowGreen", "GreenYellow", "OliveDrab", "LimeGreen", "LawnGreen"}

    def test_invalid_hex_returns_string(self):
        result = nearest_color_name("notahex")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# project_colorname
# ---------------------------------------------------------------------------


class TestProjectColorname:
    # --- single-color passthrough ---

    def test_single_color_none_returns_none(self):
        assert project_colorname("ff0000", None, None) is None

    def test_single_color_empty_string_returns_none(self):
        assert project_colorname("ff0000", "", None) is None

    def test_single_color_whitespace_only_returns_none(self):
        assert project_colorname("ff0000", "  ", None) is None

    # --- hex format ---

    def test_two_colors_coaxial_hex(self):
        result = project_colorname("93be2f", "cdde1b,68cc16", "coaxial", fmt="hex")
        assert result == "cdde1b/68cc16 (coextruded)"

    def test_two_colors_longitudinal_hex(self):
        result = project_colorname("ff0000", "00ff00,0000ff", "longitudinal", fmt="hex")
        assert result == "00ff00/0000ff (gradient)"

    def test_three_colors_hex(self):
        result = project_colorname("ff0000", "00ff00,0000ff,ffff00", "coaxial", fmt="hex")
        assert result == "00ff00/0000ff/ffff00 (coextruded)"

    def test_hex_format_strips_hash(self):
        result = project_colorname("ff0000", "#00ff00,#0000ff", None, fmt="hex")
        assert result == "00ff00/0000ff"

    def test_hex_format_lowercases(self):
        result = project_colorname("ff0000", "CDDE1B,68CC16", None, fmt="hex")
        assert result == "cdde1b/68cc16"

    # --- name format ---

    def test_two_colors_coaxial_name_contains_direction(self):
        result = project_colorname("93be2f", "cdde1b,68cc16", "coaxial", fmt="name")
        assert result is not None
        assert "(coextruded)" in result

    def test_two_colors_name_format_has_two_parts(self):
        result = project_colorname("93be2f", "cdde1b,68cc16", "coaxial", fmt="name")
        assert result is not None
        body = result.replace(" (coextruded)", "")
        assert len(body.split("/")) == 2

    def test_three_colors_name_format_has_three_parts(self):
        result = project_colorname("ff0000", "ff0000,00ff00,0000ff", "coaxial", fmt="name")
        assert result is not None
        body = result.replace(" (coextruded)", "")
        assert len(body.split("/")) == 3

    # --- direction vocabulary ---

    def test_coaxial_maps_to_coextruded(self):
        result = project_colorname("ff0000", "00ff00", "coaxial", fmt="hex")
        assert result == "00ff00 (coextruded)"

    def test_longitudinal_maps_to_gradient(self):
        result = project_colorname("ff0000", "00ff00", "longitudinal", fmt="hex")
        assert result == "00ff00 (gradient)"

    def test_no_direction_no_parens(self):
        result = project_colorname("ff0000", "00ff00,0000ff", None, fmt="hex")
        assert result == "00ff00/0000ff"
        assert "(" not in result

    def test_unknown_direction_passes_through(self):
        result = project_colorname("ff0000", "00ff00", "unknown_dir", fmt="hex")
        assert result is not None
        assert "unknown_dir" in result

    # --- format switch ---

    def test_format_change_produces_different_output(self):
        hex_result = project_colorname("93be2f", "cdde1b,68cc16", "coaxial", fmt="hex")
        name_result = project_colorname("93be2f", "cdde1b,68cc16", "coaxial", fmt="name")
        assert hex_result != name_result
        assert "cdde1b/68cc16" in hex_result  # type: ignore[operator]

    def test_default_format_is_name(self):
        result_default = project_colorname("ff0000", "00ff00", "coaxial")
        result_name = project_colorname("ff0000", "00ff00", "coaxial", fmt="name")
        assert result_default == result_name

    # --- primary color_hex not included in projection ---

    def test_primary_hex_not_in_projection(self):
        # color_hex is already written to FDB `color`; it must not appear in colorName
        result = project_colorname("aabbcc", "cdde1b,68cc16", None, fmt="hex")
        assert result is not None
        assert "aabbcc" not in result
