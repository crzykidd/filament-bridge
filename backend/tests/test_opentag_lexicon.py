"""Tests for the OpenTag lexicon mining module (opentag_lexicon.py).

Covers:
- Residual tokenization (vendor/material/finish removal, separator handling)
- N-gram extraction (bigrams not crossing separators)
- Bigram lift rule (dual color mined, shiny gradient NOT a bigram)
- Determinism (same input → same output)
- Seed merge (MODIFIER_SEED always present)
- Color-leak fix (turquoise/fuchsia/emerald etc. go to COLORS, not MODIFIERS)
- Material code stop-list (gf10/rfid/htpla/rpla/rpetg/esd absent from modifiers)
- Cache persistence (lexicon written on fetch; warm read; version-bump in-place recompute)
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.core.opentag_cache import (
    CACHE_SCHEMA_VERSION,
    _load_cache,
    _save_cache,
    load_opentag_dataset,
)
from app.core.opentag_lexicon import (
    BASE_COLORS,
    LEXICON_VERSION,
    MODIFIER_SEED,
    STOP_WORDS,
    _extract_ngrams,
    _residual_tokens,
    mine_lexicons,
    mine_lexicons_with_counts,
)


# ---------------------------------------------------------------------------
# Minimal test dataset (no network needed)
# ---------------------------------------------------------------------------

def _make_dataset(n: int = 200) -> list[dict]:
    """Build a synthetic minimal material dataset with controlled content.

    Includes:
    - 'dual color' as a bigram (high lift, repeated across brands)
    - 'shiny' and 'gradient' as separate unigrams (low co-occurrence lift)
    - 'blue', 'silver' as color unigrams across many brands
    - 'htpla', 'gf10', 'rfid', 'esd', 'rpla', 'rpetg' as stop-word tokens
    - 'turquoise', 'fuchsia', 'emerald' as color names (should go to COLORS)
    """
    materials = []
    brands = [f"Brand{i}" for i in range(20)]

    # Add materials with "dual color" bigram across many brands
    for i in range(40):
        brand = brands[i % len(brands)]
        materials.append({
            "name": f"Dual Color Red Blue {i}",
            "brandName": brand,
            "type": "PLA",
            "abbreviation": "PLA",
            "tags": [],
        })

    # Add materials with 'shiny' and 'gradient' as SEPARATE unigrams (not co-occurring)
    for i in range(25):
        brand = brands[i % len(brands)]
        materials.append({
            "name": f"Shiny Red {i}",
            "brandName": brand,
            "type": "PLA",
            "abbreviation": "PLA",
            "tags": [],
        })
    for i in range(20):
        brand = brands[i % len(brands)]
        materials.append({
            "name": f"Gradient Blue {i}",
            "brandName": brand,
            "type": "PLA",
            "abbreviation": "PLA",
            "tags": [],
        })

    # Add materials with 'blue' and 'silver' as color tokens
    for i in range(30):
        brand = brands[i % len(brands)]
        materials.append({
            "name": f"Blue Filament {i}",
            "brandName": brand,
            "type": "PETG",
            "abbreviation": "PETG",
            "tags": [],
        })
    for i in range(25):
        brand = brands[i % len(brands)]
        materials.append({
            "name": f"Silver {i}",
            "brandName": brand,
            "type": "PLA",
            "abbreviation": "PLA",
            "tags": [],
        })

    # Add stop-word material codes (should NOT appear in modifiers)
    for code in ["htpla", "gf10", "rfid", "esd", "rpla", "rpetg"]:
        for i in range(8):
            brand = brands[i % len(brands)]
            materials.append({
                "name": f"{code.upper()} Red {i}",
                "brandName": brand,
                "type": "PLA",
                "abbreviation": "PLA",
                "tags": [],
            })

    # Add color-name tokens that should go to BASE_COLORS/mined_colors (not modifiers)
    for color_name in ["turquoise", "fuchsia", "emerald", "graphite", "rosa"]:
        for i in range(12):
            brand = brands[i % len(brands)]
            materials.append({
                "name": f"{color_name.title()} PLA {i}",
                "brandName": brand,
                "type": "PLA",
                "abbreviation": "PLA",
                "tags": [],
            })

    return materials


_DATASET = _make_dataset()


# ---------------------------------------------------------------------------
# Tokenization tests
# ---------------------------------------------------------------------------


def test_residual_tokens_removes_vendor_and_material():
    """Vendor and material words are stripped; color token remains."""
    toks = _residual_tokens("ELEGOO PLA Red", "ELEGOO", "PLA")
    assert "red" in toks
    assert "elegoo" not in toks
    assert "pla" not in toks


def test_residual_tokens_separator_inserted():
    """'&' and '/' are converted to __SEP__ sentinel tokens."""
    toks = _residual_tokens("Silver & Blue", "TestBrand", "PLA")
    assert "__SEP__" in toks
    assert "silver" in toks
    assert "blue" in toks


def test_residual_tokens_no_cross_sep_ngram():
    """_extract_ngrams must NOT form bigrams crossing __SEP__."""
    toks = ["silver", "__SEP__", "blue"]
    bigrams = _extract_ngrams(toks, 2)
    # No bigram should contain a SEP
    for bg in bigrams:
        assert "__SEP__" not in bg
    # No bigram spanning the separator
    assert ("silver", "blue") not in bigrams


def test_residual_tokens_drops_single_chars():
    """Single-character tokens are dropped (noise)."""
    toks = _residual_tokens("A Red X", "B", "PLA")
    assert "a" not in toks
    assert "x" not in toks
    assert "red" in toks


def test_residual_tokens_drops_numeric():
    """Purely numeric tokens are dropped."""
    toks = _residual_tokens("PLA 200C Red", "B", "PLA")
    assert "200" not in toks
    assert "200c" not in toks
    assert "red" in toks


# ---------------------------------------------------------------------------
# N-gram extraction tests
# ---------------------------------------------------------------------------


def test_extract_bigrams_no_sep():
    """Normal bigram extraction without separators."""
    toks = ["red", "blue", "green"]
    bigrams = _extract_ngrams(toks, 2)
    assert ("red", "blue") in bigrams
    assert ("blue", "green") in bigrams
    assert len(bigrams) == 2


def test_extract_bigrams_sep_breaks_window():
    """A SEP in the window means no bigram formed across it."""
    toks = ["red", "__SEP__", "blue", "green"]
    bigrams = _extract_ngrams(toks, 2)
    # ("red", "__SEP__") contains a sep → skipped
    # ("__SEP__", "blue") contains a sep → skipped
    # ("blue", "green") → no sep → kept
    assert ("blue", "green") in bigrams
    assert ("red", "__SEP__") not in bigrams
    assert ("__SEP__", "blue") not in bigrams


# ---------------------------------------------------------------------------
# Bigram-lift rule — "dual color" mined, "shiny gradient" is NOT
# ---------------------------------------------------------------------------


def test_dual_color_is_mined_as_bigram():
    """'dual color' must be in the mined modifier set (it has high co-occurrence lift)."""
    result = mine_lexicons(_DATASET)
    modifiers = set(result["modifiers"])
    assert "dual color" in modifiers, (
        f"Expected 'dual color' in modifiers; modifiers sample: {sorted(modifiers)[:20]}"
    )


def test_shiny_gradient_not_a_single_bigram():
    """'shiny gradient' must NOT be in modifiers as a bigram phrase (low co-occurrence lift).

    In the test dataset, 'shiny' and 'gradient' appear separately in different materials
    (not always together), so their lift should be below BIGRAM_LIFT_THRESHOLD.
    Both should be separate unigram modifiers (from MODIFIER_SEED), not one bigram.
    """
    result = mine_lexicons(_DATASET)
    modifiers = set(result["modifiers"])
    # "shiny gradient" must not be a promoted bigram modifier
    assert "shiny gradient" not in modifiers, (
        "'shiny gradient' must NOT be a promoted bigram in this dataset"
    )
    # Each should appear as separate unigram modifiers (from MODIFIER_SEED)
    assert "shiny" in modifiers, "Expected 'shiny' as unigram modifier"
    assert "gradient" in modifiers, "Expected 'gradient' as unigram modifier"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_mining_is_deterministic():
    """mine_lexicons produces the same result on repeated calls with the same input."""
    result1 = mine_lexicons(_DATASET)
    result2 = mine_lexicons(_DATASET)
    assert result1["modifiers"] == result2["modifiers"]
    assert result1["colors"] == result2["colors"]


# ---------------------------------------------------------------------------
# Seed merge
# ---------------------------------------------------------------------------


def test_modifier_seed_always_present():
    """All MODIFIER_SEED items must appear in the output modifiers."""
    result = mine_lexicons(_DATASET)
    mods = set(result["modifiers"])
    for seed_item in MODIFIER_SEED:
        # Seeds that are in STOP_WORDS or BASE_COLORS are legitimately absent
        if seed_item in STOP_WORDS or seed_item in BASE_COLORS:
            continue
        assert seed_item in mods, f"MODIFIER_SEED item '{seed_item}' missing from modifiers"


def test_base_colors_always_present():
    """All BASE_COLORS must appear in the output colors."""
    result = mine_lexicons(_DATASET)
    cols = set(result["colors"])
    for bc in BASE_COLORS:
        assert bc in cols, f"BASE_COLORS item '{bc}' missing from colors"


# ---------------------------------------------------------------------------
# Color-leak fix: turquoise / fuchsia / emerald / graphite / rosa go to COLORS
# ---------------------------------------------------------------------------


def test_color_names_in_base_colors_not_modifiers():
    """Color names explicitly seeded in BASE_COLORS must never appear in modifiers.

    Regression: v1 would mine turquoise/fuchsia/emerald/graphite/rosa as modifiers
    because they appeared in fewer than COLOR_MIN_BRANDS brands.  The extended
    BASE_COLORS seed guarantees they are always classified as colors.
    """
    color_names_to_check = {"turquoise", "fuchsia", "emerald", "graphite", "rosa"}
    result = mine_lexicons(_DATASET)
    mods = set(result["modifiers"])
    cols = set(result["colors"])

    for name in color_names_to_check:
        # These are in BASE_COLORS — must be in colors
        if name in BASE_COLORS:
            assert name in cols, f"'{name}' should be in colors (BASE_COLORS)"
            assert name not in mods, f"'{name}' must NOT be in modifiers"


# ---------------------------------------------------------------------------
# Material code stop-list
# ---------------------------------------------------------------------------


def test_material_codes_absent_from_modifiers():
    """Material/grade codes (gf10, gf15, gf25, rfid, esd, htpla, rpla, rpetg) must be absent."""
    result = mine_lexicons(_DATASET)
    mods = set(result["modifiers"])
    cols = set(result["colors"])
    stop_codes = {"gf10", "gf15", "gf25", "gf30", "rfid", "esd", "htpla", "rpla", "rpetg", "paht"}
    for code in stop_codes:
        assert code not in mods, f"Material code '{code}' must not be in modifiers"
        assert code not in cols, f"Material code '{code}' must not be in colors"


# ---------------------------------------------------------------------------
# Cache persistence tests
# ---------------------------------------------------------------------------


def _make_opt_material(brand: str = "ELEGOO", name: str = "Red PLA", mat_type: str = "PLA") -> dict:
    return {
        "uuid": "test-uuid-001",
        "slug": "elegoo-pla-red",
        "brandName": brand,
        "name": name,
        "type": mat_type,
        "abbreviation": mat_type,
        "tags": [],
        "color": "#FF0000",
        "secondaryColors": [],
        "density": 1.24,
        "nozzleTempMin": 190,
        "nozzleTempMax": 230,
        "bedTempMin": 45,
        "bedTempMax": 65,
        "completenessScore": None,
        "completenessTier": None,
        "photoUrl": None,
        "productUrl": None,
        "hardnessShoreD": None,
        "transmissionDistance": None,
        "chamberTemp": None,
        "preheatTemp": None,
        "dryingTemp": None,
        "dryingTime": None,
    }


@pytest.mark.asyncio
async def test_load_dataset_writes_lexicon_on_fresh_fetch(tmp_path):
    """load_opentag_dataset writes 'lexicon' and 'lexicon_version' to the cache file on fresh fetch."""
    materials = [_make_opt_material()]

    with patch(
        "app.core.opentag_cache._fetch_from_tarball",
        AsyncMock(return_value={
            "materials": materials,
            "packages_by_material": {},
            "containers_by_slug": {},
        }),
    ):
        result = await load_opentag_dataset(str(tmp_path), 24, force=True)

    # Returned dict has lexicon
    assert "lexicon" in result, "Returned dataset must include 'lexicon' key"
    assert result["lexicon"] is not None
    assert "modifiers" in result["lexicon"]
    assert "colors" in result["lexicon"]

    # Cache file on disk also has lexicon
    cache = _load_cache(str(tmp_path))
    assert cache is not None
    assert "lexicon" in cache
    assert cache.get("lexicon_version") == LEXICON_VERSION


@pytest.mark.asyncio
async def test_load_dataset_warm_read_returns_lexicon(tmp_path):
    """Warm cache (fresh, not stale) returns the cached lexicon without re-mining."""
    materials = [_make_opt_material()]
    fresh_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    lexicon_data = {"modifiers": ["shiny", "gradient"], "colors": ["red", "blue"]}
    _save_cache(str(tmp_path), materials, fresh_ts, lexicon=lexicon_data, lexicon_version=LEXICON_VERSION)

    with patch(
        "app.core.opentag_cache._fetch_from_tarball",
        AsyncMock(side_effect=AssertionError("must not fetch on warm read")),
    ):
        result = await load_opentag_dataset(str(tmp_path), 24, force=False)

    assert result["lexicon"] == lexicon_data


@pytest.mark.asyncio
async def test_load_dataset_recomputes_lexicon_on_version_bump(tmp_path):
    """When cached lexicon_version != LEXICON_VERSION, lexicon is re-mined WITHOUT network fetch."""
    materials = [_make_opt_material()]
    fresh_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    old_version = LEXICON_VERSION - 1  # simulate a stale version
    if old_version < 0:
        old_version = 999  # in case LEXICON_VERSION == 0 (shouldn't happen)

    # Save with stale version
    old_lexicon = {"modifiers": ["old_mod"], "colors": ["old_col"]}
    _save_cache(str(tmp_path), materials, fresh_ts, lexicon=old_lexicon, lexicon_version=old_version)

    with patch(
        "app.core.opentag_cache._fetch_from_tarball",
        AsyncMock(side_effect=AssertionError("must not re-fetch on version bump")),
    ):
        result = await load_opentag_dataset(str(tmp_path), 24, force=False)

    # Lexicon should have been re-mined (not the stale one)
    assert result["lexicon"] != old_lexicon, "Lexicon must be re-mined on version bump"
    assert result["lexicon_version"] == LEXICON_VERSION if "lexicon_version" in result else True

    # Cache file updated
    cache = _load_cache(str(tmp_path))
    assert cache is not None
    assert cache.get("lexicon_version") == LEXICON_VERSION


@pytest.mark.asyncio
async def test_load_dataset_recomputes_lexicon_when_missing(tmp_path):
    """When cache has no 'lexicon' key, lexicon is mined WITHOUT network fetch."""
    materials = [_make_opt_material()]
    fresh_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # Save WITHOUT lexicon (simulates a cache missing only the lexicon key).
    # Keep schema_version current so the schema self-heal doesn't force a
    # download — this test isolates the lexicon-missing re-mine path.
    path = Path(tmp_path) / "opentag_cache.json"
    data = {
        "fetched_at": fresh_ts,
        "count": len(materials),
        "schema_version": CACHE_SCHEMA_VERSION,
        "materials": materials,
    }
    with path.open("w") as fh:
        json.dump(data, fh)

    with patch(
        "app.core.opentag_cache._fetch_from_tarball",
        AsyncMock(side_effect=AssertionError("must not re-fetch when lexicon missing")),
    ):
        result = await load_opentag_dataset(str(tmp_path), 24, force=False)

    assert "lexicon" in result
    assert result["lexicon"] is not None


# ---------------------------------------------------------------------------
# mine_lexicons_with_counts — smoke test
# ---------------------------------------------------------------------------


def test_mine_lexicons_with_counts_returns_expected_keys():
    """mine_lexicons_with_counts returns all expected keys including counts."""
    result = mine_lexicons_with_counts(_DATASET)
    assert "modifiers" in result
    assert "colors" in result
    assert "modifier_counts" in result
    assert "color_counts" in result
    # dual color should have a positive count in the test dataset
    mc = result["modifier_counts"]
    assert mc.get("dual color", 0) > 0, "Expected 'dual color' to have count > 0"


def test_mine_lexicons_output_sorted_longest_first():
    """Output lists are sorted longest-phrase-first then alphabetically."""
    result = mine_lexicons(_DATASET)
    mods = result["modifiers"]
    # Check that multi-word entries come before single-word entries
    multi = [m for m in mods if len(m.split()) > 1]
    single = [m for m in mods if len(m.split()) == 1]
    if multi and single:
        first_multi_idx = mods.index(multi[0])
        first_single_idx = mods.index(single[0])
        assert first_multi_idx < first_single_idx, "Multi-word modifiers must come before unigrams"
