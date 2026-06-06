"""Tests for core/color.py — hex-format helpers and structured multicolor mapping."""

from app.core.color import (
    TAG_COEXTRUDED,
    TAG_GRADIENT,
    apply_finish_tags,
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


# ---------------------------------------------------------------------------
# apply_finish_tags — merges finish IDs without touching arrangement or unknown tags
# ---------------------------------------------------------------------------


class TestApplyFinishTags:
    def test_adds_silk_tag(self):
        result = apply_finish_tags([], {17})
        assert result == [17]

    def test_adds_multiple_tags_sorted(self):
        result = apply_finish_tags([], {17, 16})
        assert result == [16, 17]

    def test_preserves_arrangement_tag_gradient(self):
        # TAG_GRADIENT (28) must survive — it's in ARRANGEMENT_TAGS, not MANAGED_FINISH_IDS
        result = apply_finish_tags([TAG_GRADIENT], {17})
        assert TAG_GRADIENT in result
        assert 17 in result

    def test_preserves_arrangement_tag_coextruded(self):
        result = apply_finish_tags([TAG_COEXTRUDED], {17})
        assert TAG_COEXTRUDED in result
        assert 17 in result

    def test_preserves_unknown_tag(self):
        # Unknown tag (e.g. 999) must pass through unmodified
        result = apply_finish_tags([999], {17})
        assert 999 in result
        assert 17 in result

    def test_replaces_stale_managed_finish_ids(self):
        # If 17 (silk) was previously set and we now pass {16} (matte), 17 is cleared
        result = apply_finish_tags([17], {16})
        assert 17 not in result
        assert 16 in result

    def test_clears_all_managed_finish_ids_when_empty(self):
        # Passing an empty set clears all managed finish IDs
        result = apply_finish_tags([17, 16, TAG_GRADIENT], set())
        assert 17 not in result
        assert 16 not in result
        assert TAG_GRADIENT in result  # arrangement tag preserved

    def test_none_existing_treated_as_empty(self):
        result = apply_finish_tags(None, {17})
        assert result == [17]

    def test_arrangement_and_finish_coexist(self):
        # Full real-world scenario: coextruded + silk
        result = apply_finish_tags([TAG_COEXTRUDED, TAG_GRADIENT], {17})
        assert TAG_COEXTRUDED in result
        assert TAG_GRADIENT in result
        assert 17 in result

    def test_deterministic_output_order(self):
        # Multiple calls with same args should return the same list
        a = apply_finish_tags([TAG_COEXTRUDED], {17, 16})
        b = apply_finish_tags([TAG_COEXTRUDED], {17, 16})
        assert a == b

    def test_malformed_tags_skipped(self):
        # Non-integer tags should be skipped gracefully
        result = apply_finish_tags(["bad", None, 17], {16})
        assert 17 not in result  # 17 is a managed ID → replaced
        assert 16 in result

