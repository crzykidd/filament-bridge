"""Tests for core/color.py — hex-format helpers and structured multicolor mapping."""

from app.core.color import (
    TAG_COEXTRUDED,
    TAG_GRADIENT,
    fdb_multicolor_to_sm,
    multicolor_signature,
    sm_multicolor_signature,
    sm_multicolor_to_fdb,
    to_fdb_color,
    to_sm_color,
)


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
# sm_multicolor_to_fdb
# ---------------------------------------------------------------------------


class TestSmMulticolorToFdb:
    def test_single_color_solid(self):
        mc = sm_multicolor_to_fdb("ff0000", None, None)
        assert mc == {"color": "#ff0000", "secondaryColors": [], "optTags": []}

    def test_single_hex_in_multi_is_solid(self):
        mc = sm_multicolor_to_fdb("ff0000", "ff0000", "coaxial")
        assert mc["color"] == "#ff0000"
        assert mc["secondaryColors"] == []
        assert TAG_COEXTRUDED not in mc["optTags"]

    def test_coaxial_null_primary_all_secondary(self):
        mc = sm_multicolor_to_fdb("93be2f", "cdde1b,68cc16", "coaxial")
        assert mc["color"] is None
        assert mc["secondaryColors"] == ["#cdde1b", "#68cc16"]
        assert mc["optTags"] == [TAG_COEXTRUDED]

    def test_longitudinal_primary_plus_rest(self):
        mc = sm_multicolor_to_fdb("aa0000", "aa0000,00bb00,0000cc", "longitudinal")
        assert mc["color"] == "#aa0000"
        assert mc["secondaryColors"] == ["#00bb00", "#0000cc"]
        assert mc["optTags"] == [TAG_GRADIENT]

    def test_hash_normalization(self):
        mc = sm_multicolor_to_fdb(None, "#cdde1b , #68cc16", "coaxial")
        assert mc["secondaryColors"] == ["#cdde1b", "#68cc16"]

    def test_existing_tags_preserved_and_arrangement_swapped(self):
        mc = sm_multicolor_to_fdb("ff0000", "ff0000,00ff00", "coaxial", existing_opt_tags=[5, TAG_GRADIENT])
        # unrelated tag 5 kept; gradient replaced by coextruded
        assert mc["optTags"] == [5, TAG_COEXTRUDED]

    def test_solid_clears_arrangement_tags(self):
        mc = sm_multicolor_to_fdb("ff0000", None, None, existing_opt_tags=[7, TAG_COEXTRUDED, TAG_GRADIENT])
        assert mc["optTags"] == [7]

    def test_multi_hex_unknown_direction_defensive(self):
        mc = sm_multicolor_to_fdb("ff0000", "ff0000,00ff00", None)
        assert mc["color"] == "#ff0000"
        assert mc["secondaryColors"] == ["#00ff00"]
        assert mc["optTags"] == []


# ---------------------------------------------------------------------------
# fdb_multicolor_to_sm
# ---------------------------------------------------------------------------


class TestFdbMulticolorToSm:
    def test_coextruded_synthesizes_primary(self):
        sm = fdb_multicolor_to_sm(None, ["#cdde1b", "#68cc16"], [TAG_COEXTRUDED])
        assert sm["color_hex"] == "cdde1b"
        assert sm["multi_color_hexes"] == "cdde1b,68cc16"
        assert sm["multi_color_direction"] == "coaxial"

    def test_gradient_primary_plus_rest(self):
        sm = fdb_multicolor_to_sm("#aa0000", ["#00bb00", "#0000cc"], [TAG_GRADIENT])
        assert sm["color_hex"] == "aa0000"
        assert sm["multi_color_hexes"] == "aa0000,00bb00,0000cc"
        assert sm["multi_color_direction"] == "longitudinal"

    def test_coextruded_wins_over_gradient(self):
        sm = fdb_multicolor_to_sm(None, ["#112233", "#445566"], [TAG_GRADIENT, TAG_COEXTRUDED])
        assert sm["multi_color_direction"] == "coaxial"

    def test_solid_clears_multi(self):
        sm = fdb_multicolor_to_sm("#ff0000", [], [])
        assert sm["color_hex"] == "ff0000"
        assert sm["multi_color_hexes"] is None
        assert sm["multi_color_direction"] is None


# ---------------------------------------------------------------------------
# multicolor_signature — system-agnostic, round-trip stable
# ---------------------------------------------------------------------------


class TestMulticolorSignature:
    def test_case_and_hash_invariant(self):
        a = multicolor_signature("#FF0000", ["#00FF00"], [TAG_GRADIENT])
        b = multicolor_signature("ff0000", ["00ff00"], [TAG_GRADIENT])
        assert a == b

    def test_coaxial_sm_matches_fdb_signature(self):
        # The FDB a coaxial SM filament maps to must share its signature.
        mc = sm_multicolor_to_fdb("93be2f", "cdde1b,68cc16", "coaxial")
        sm_sig = sm_multicolor_signature("93be2f", "cdde1b,68cc16", "coaxial")
        fdb_sig = multicolor_signature(mc["color"], mc["secondaryColors"], mc["optTags"])
        assert sm_sig == fdb_sig

    def test_gradient_round_trip_stable(self):
        # fdb -> sm -> signature equals the original fdb signature
        fdb_sig = multicolor_signature("#aa0000", ["#00bb00", "#0000cc"], [TAG_GRADIENT])
        sm = fdb_multicolor_to_sm("#aa0000", ["#00bb00", "#0000cc"], [TAG_GRADIENT])
        sm_sig = sm_multicolor_signature(
            sm["color_hex"], sm["multi_color_hexes"], sm["multi_color_direction"]
        )
        assert sm_sig == fdb_sig

    def test_coaxial_round_trip_stable(self):
        fdb_sig = multicolor_signature(None, ["#cdde1b", "#68cc16"], [TAG_COEXTRUDED])
        sm = fdb_multicolor_to_sm(None, ["#cdde1b", "#68cc16"], [TAG_COEXTRUDED])
        sm_sig = sm_multicolor_signature(
            sm["color_hex"], sm["multi_color_hexes"], sm["multi_color_direction"]
        )
        assert sm_sig == fdb_sig

    def test_different_arrangement_differs(self):
        coax = multicolor_signature(None, ["#aabbcc"], [TAG_COEXTRUDED])
        grad = multicolor_signature("#aabbcc", [], [TAG_GRADIENT])
        assert coax != grad
