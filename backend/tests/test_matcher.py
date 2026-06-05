"""Tests for core/matcher.py — fuzzy filament matching."""

from app.core.matcher import (
    extract_finish_line,
    match_filaments,
    normalize_color,
    normalize_name,
    normalize_vendor,
    sm_variant_cluster_key,
)
from app.schemas.filamentdb import FDBFilament
from app.schemas.spoolman import SpoolmanFilament, SpoolmanVendor


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def test_vendor_alias_elegoo():
    assert normalize_vendor("ELEGOO") == normalize_vendor("elegoo") == normalize_vendor("Elegoo")


def test_vendor_alias_polymaker():
    assert normalize_vendor("polymaker") == normalize_vendor("Polymaker")


def test_vendor_whitespace():
    assert normalize_vendor("  Hatchbox  ") == normalize_vendor("hatchbox")


def test_name_case_insensitive():
    assert normalize_name("Rapid PLA+") == normalize_name("rapid pla+")


def test_name_collapses_whitespace():
    assert normalize_name("PLA  Plus") == normalize_name("pla plus")


def test_color_strips_hash():
    assert normalize_color("#FF0000") == "ff0000"
    assert normalize_color("ff0000") == "ff0000"


# ---------------------------------------------------------------------------
# Fixtures shaped from real findings.md data
# ---------------------------------------------------------------------------


def _sm_filament(id_: int, vendor: str, name: str, color: str) -> SpoolmanFilament:
    return SpoolmanFilament(
        id=id_,
        name=name,
        vendor=SpoolmanVendor(id=1, name=vendor),
        color_hex=color,
    )


def _fdb_filament(id_: str, vendor: str, name: str, color: str) -> FDBFilament:
    return FDBFilament(
        **{"_id": id_, "name": name, "vendor": vendor, "color": color}
    )


class TestMatchFilaments:
    def test_exact_match(self):
        sm = [_sm_filament(1, "ELEGOO", "Rapid PLA+", "ff0000")]
        fdb = [_fdb_filament("aaa", "elegoo", "rapid pla+", "ff0000")]
        result = match_filaments(sm, fdb)
        assert len(result.matched) == 1
        assert result.matched[0].confidence == 1.0
        assert not result.unmatched_spoolman
        assert not result.unmatched_fdb

    def test_vendor_alias_match(self):
        sm = [_sm_filament(2, "Polymaker", "PolyLite PLA", "ffffff")]
        fdb = [_fdb_filament("bbb", "polymaker", "polylite pla", "ffffff")]
        result = match_filaments(sm, fdb)
        assert len(result.matched) == 1

    def test_unmatched_spoolman(self):
        sm = [_sm_filament(3, "SUNLU", "PLA", "000000")]
        fdb = []
        result = match_filaments(sm, fdb)
        assert len(result.unmatched_spoolman) == 1
        assert result.unmatched_spoolman[0].id == 3

    def test_unmatched_fdb(self):
        sm = []
        fdb = [_fdb_filament("ccc", "Hatchbox", "PLA", "00ff00")]
        result = match_filaments(sm, fdb)
        assert len(result.unmatched_fdb) == 1
        assert result.unmatched_fdb[0].id == "ccc"

    def test_ambiguous_two_fdb_candidates(self):
        sm = [_sm_filament(4, "ELEGOO", "PLA", "ff0000")]
        fdb = [
            _fdb_filament("d1", "elegoo", "pla", "ff0000"),
            _fdb_filament("d2", "elegoo", "pla", "ff0000"),
        ]
        result = match_filaments(sm, fdb)
        assert len(result.ambiguous) == 1
        sm_r, cands = result.ambiguous[0]
        assert sm_r.id == 4
        assert len(cands) == 2
        assert not result.unmatched_fdb  # ambiguous candidates excluded from unmatched

    def test_multiple_sm_same_key_gets_distinct_fdb(self):
        # Two SM filaments with same key should not both claim the same FDB record
        sm = [
            _sm_filament(5, "Prusa", "PLA", "0000ff"),
            _sm_filament(6, "Prusa", "PLA", "0000ff"),
        ]
        fdb = [_fdb_filament("e1", "prusa", "pla", "0000ff")]
        result = match_filaments(sm, fdb)
        # First SM gets the match; second goes to unmatched
        assert len(result.matched) == 1
        assert len(result.unmatched_spoolman) == 1

    def test_empty_inputs(self):
        result = match_filaments([], [])
        assert not result.matched
        assert not result.unmatched_spoolman
        assert not result.unmatched_fdb


# ---------------------------------------------------------------------------
# extract_finish_line
# ---------------------------------------------------------------------------


class TestExtractFinishLine:
    def test_silk(self):
        assert extract_finish_line("Buddy PLA Silk Red") == "silk"

    def test_matte(self):
        assert extract_finish_line("ELEGOO PLA Matte Black", "PLA") == "matte"

    def test_satin(self):
        assert extract_finish_line("Satin PLA Blue") == "satin"

    def test_cf_word_boundary(self):
        assert extract_finish_line("Bambu PLA-CF") == "cf"
        assert extract_finish_line("ELEGOO PLA CF Grey") == "cf"

    def test_cf_carbon_fiber(self):
        assert extract_finish_line("PLA Carbon Fiber") == "cf"

    def test_glow(self):
        assert extract_finish_line("PLA Glow in the Dark") == "glow"
        assert extract_finish_line("GITD PLA Green") == "glow"
        assert extract_finish_line("Glow Blue PLA") == "glow"

    def test_hs(self):
        assert extract_finish_line("High Speed PLA White") == "hs"
        assert extract_finish_line("PLA HS Red") == "hs"

    def test_marble(self):
        assert extract_finish_line("PLA Marble White") == "marble"

    def test_wood(self):
        assert extract_finish_line("PLA Wood Brown") == "wood"

    def test_multicolor(self):
        assert extract_finish_line("PLA Multicolor Rainbow") == "multicolor"
        assert extract_finish_line("PLA Rainbow") == "multicolor"

    def test_standard_empty(self):
        assert extract_finish_line("ELEGOO PLA Green") == ""
        assert extract_finish_line("PLA Red") == ""
        assert extract_finish_line("ABS White") == ""

    def test_material_field_contributes(self):
        assert extract_finish_line("SILK Blue", "Silk PLA") == "silk"

    def test_cf_not_false_positive_in_scaffold(self):
        # "Scaff" contains no finish token
        assert extract_finish_line("PLA Scaffolding") == ""


# ---------------------------------------------------------------------------
# sm_variant_cluster_key — finish splits clusters (Part B)
# ---------------------------------------------------------------------------


def _sm_fil(id_: int, name: str, vendor: str = "Buddy", material: str = "PLA") -> SpoolmanFilament:
    return SpoolmanFilament(
        id=id_,
        name=name,
        vendor=SpoolmanVendor(id=1, name=vendor),
        material=material,
    )


class TestExtractFinishLineKeywords:
    def test_custom_keyword_rapid(self):
        keywords = ["rapid", "silk", "matte"]
        assert extract_finish_line("ELEGOO Rapid PLA Red", keywords=keywords) == "rapid"
        assert extract_finish_line("ELEGOO PLA Red", keywords=keywords) == ""

    def test_empty_keyword_list_always_standard(self):
        assert extract_finish_line("ELEGOO PLA Silk Red", keywords=[]) == ""
        assert extract_finish_line("PLA Matte Black", keywords=[]) == ""

    def test_first_matching_keyword_wins(self):
        # "silk" before "matte" — silk should win when both appear
        assert extract_finish_line("PLA Matte Silk", keywords=["silk", "matte"]) == "silk"
        assert extract_finish_line("PLA Matte Silk", keywords=["matte", "silk"]) == "matte"

    def test_keyword_word_boundary_enforced(self):
        # "matt" must not match "matte"; "matte" must match
        assert extract_finish_line("PLA Matte Black", keywords=["matt"]) == ""
        assert extract_finish_line("PLA Matte Black", keywords=["matte"]) == "matte"

    def test_keyword_case_insensitive(self):
        assert extract_finish_line("PLA SILK Red", keywords=["silk"]) == "silk"

    def test_no_keywords_falls_back_to_default_patterns(self):
        # keywords=None → _FINISH_PATTERNS; existing behavior preserved
        assert extract_finish_line("Buddy PLA Silk Red") == "silk"
        assert extract_finish_line("ELEGOO PLA Green") == ""


class TestSmVariantClusterKey:
    def test_silk_and_standard_split(self):
        silk_red = _sm_fil(1, "PLA Silk Red")
        silk_blue = _sm_fil(2, "PLA Silk Blue")
        standard = _sm_fil(3, "PLA Green")

        key_silk = sm_variant_cluster_key(silk_red)
        key_silk2 = sm_variant_cluster_key(silk_blue)
        key_std = sm_variant_cluster_key(standard)

        assert key_silk == key_silk2, "Silk Red and Silk Blue should share a cluster key"
        assert key_silk != key_std, "Silk and standard should be in different clusters"
        assert key_silk[2] == "silk"
        assert key_std[2] == ""

    def test_same_vendor_material_different_finish(self):
        matte = _sm_fil(4, "Buddy PLA Matte Red")
        silk = _sm_fil(5, "Buddy PLA Silk Red")
        standard = _sm_fil(6, "Buddy PLA Red")

        assert sm_variant_cluster_key(matte) != sm_variant_cluster_key(silk)
        assert sm_variant_cluster_key(matte) != sm_variant_cluster_key(standard)
        assert sm_variant_cluster_key(silk) != sm_variant_cluster_key(standard)

    def test_key_is_3_tuple(self):
        sm = _sm_fil(7, "PLA Red")
        key = sm_variant_cluster_key(sm)
        assert len(key) == 3  # (vendor, material, finish)


class TestSmVariantClusterKeyKeywords:
    def test_rapid_keyword_splits_cluster(self):
        rapid_red = _sm_fil(1, "ELEGOO Rapid PLA Red", vendor="ELEGOO", material="PLA")
        standard_red = _sm_fil(2, "ELEGOO PLA Red", vendor="ELEGOO", material="PLA")
        keywords = ["rapid", "silk"]

        key_rapid = sm_variant_cluster_key(rapid_red, keywords=keywords)
        key_std = sm_variant_cluster_key(standard_red, keywords=keywords)

        assert key_rapid != key_std
        assert key_rapid[2] == "rapid"
        assert key_std[2] == ""

    def test_empty_keywords_all_standard(self):
        silk = _sm_fil(1, "PLA Silk Red")
        standard = _sm_fil(2, "PLA Red")
        # Empty keyword list → both get "" finish → same cluster
        assert sm_variant_cluster_key(silk, keywords=[])[2] == ""
        assert sm_variant_cluster_key(standard, keywords=[])[2] == ""

    def test_none_keywords_uses_default_behavior(self):
        silk = _sm_fil(1, "PLA Silk Red")
        standard = _sm_fil(2, "PLA Red")
        # keywords=None → _FINISH_PATTERNS fallback
        assert sm_variant_cluster_key(silk)[2] == "silk"
        assert sm_variant_cluster_key(standard)[2] == ""
