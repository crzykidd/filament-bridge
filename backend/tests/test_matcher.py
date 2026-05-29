"""Tests for core/matcher.py — fuzzy filament matching."""

from app.core.matcher import match_filaments, normalize_color, normalize_name, normalize_vendor
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
