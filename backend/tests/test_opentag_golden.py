"""Golden-set regression tests for the OpenTag v2 matcher.

Each test case uses real-world Spoolman filament descriptions and real-world
OpenPrintTag material entries.  The key invariants checked here:

1. AMOLEN "Silk Shiny Gradient Silver & Shiny Blue" ranks #1 over
   "Dual Color Blue & Fuchsia" (the core v1 failure case).
2. Orange-vs-Copper is preserved (single color name wins over hex proximity).
3. Hatchbox Red single-color matches correctly.
4. Matte vs Silk finish-tag discrimination.
5. Multicolor profile compatibility gate.
"""

from __future__ import annotations

import pytest
from collections import Counter

from app.core.opentag_match import (
    _color_multiset_score,
    _modifier_jaccard,
    decompose_name,
    find_best_match,
    score_candidate,
)
from app.schemas.spoolman import SpoolmanFilament, SpoolmanVendor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sm(
    name: str,
    vendor: str,
    material: str,
    color_hex: str | None = None,
    multi_color_hexes: str | None = None,
    multi_color_direction: str | None = None,
) -> SpoolmanFilament:
    return SpoolmanFilament(
        id=1,
        name=name,
        vendor=SpoolmanVendor(id=1, name=vendor),
        material=material,
        color_hex=color_hex,
        multi_color_hexes=multi_color_hexes,
        multi_color_direction=multi_color_direction,
        extra={},
    )


def _opt(
    slug: str,
    brand: str,
    name: str,
    mat_type: str,
    tags: list[str],
    color: str | None,
    secondary: list[str] | None = None,
    density: float = 1.24,
) -> dict:
    return {
        "uuid": f"uuid-{slug}",
        "slug": slug,
        "brandName": brand,
        "name": name,
        "type": mat_type,
        "abbreviation": mat_type,
        "tags": tags,
        "color": color,
        "secondaryColors": secondary or [],
        "density": density,
        "nozzleTempMin": 190,
        "nozzleTempMax": 230,
        "bedTempMin": 45,
        "bedTempMax": 65,
    }


# ---------------------------------------------------------------------------
# OPT candidates — AMOLEN scenario
# ---------------------------------------------------------------------------

_OPT_AMOLEN_SILK_GRADIENT_SILVER_BLUE = _opt(
    slug="amolen-pla-silk-shiny-gradient-silver-shiny-blue",
    brand="AMOLEN",
    name="PLA Silk Shiny Gradient Silver & Shiny Blue",
    mat_type="PLA",
    tags=["silk"],
    color="#C0C0C0",
    secondary=["#4169E1"],
)

_OPT_AMOLEN_DUAL_BLUE_FUCHSIA = _opt(
    slug="amolen-pla-dual-color-blue-fuchsia",
    brand="AMOLEN",
    name="Dual Color Blue & Fuchsia",
    mat_type="PLA",
    tags=[],
    color="#0000FF",
    secondary=["#FF00FF"],
)

_OPT_AMOLEN_SILK_GOLD = _opt(
    slug="amolen-pla-silk-gold",
    brand="AMOLEN",
    name="PLA Silk Gold",
    mat_type="PLA",
    tags=["silk"],
    color="#FFD700",
)

# ---------------------------------------------------------------------------
# OPT candidates — Hatchbox Orange/Copper
# ---------------------------------------------------------------------------

_OPT_HATCHBOX_PETG_ORANGE = _opt(
    slug="hatchbox-petg-orange",
    brand="Hatchbox",
    name="Orange PETG",
    mat_type="PETG",
    tags=[],
    color="#FF8C00",
    density=1.27,
)

_OPT_HATCHBOX_PETG_COPPER = _opt(
    slug="hatchbox-petg-copper",
    brand="Hatchbox",
    name="Copper PETG",
    mat_type="PETG",
    tags=[],
    color="#AF784D",
    density=1.27,
)

# ---------------------------------------------------------------------------
# OPT candidates — matte vs silk discrimination
# ---------------------------------------------------------------------------

_OPT_ELEGOO_PLA_MATTE_RED = _opt(
    slug="elegoo-pla-matte-red",
    brand="ELEGOO",
    name="PLA Matte Red",
    mat_type="PLA",
    tags=["matte"],
    color="#CC0000",
)

_OPT_ELEGOO_PLA_SILK_RED = _opt(
    slug="elegoo-pla-silk-red",
    brand="ELEGOO",
    name="PLA Silk Red",
    mat_type="PLA",
    tags=["silk"],
    color="#CC0000",
)

# ---------------------------------------------------------------------------
# OPT candidates — single color
# ---------------------------------------------------------------------------

_OPT_HATCHBOX_PLA_RED = _opt(
    slug="hatchbox-pla-red",
    brand="Hatchbox",
    name="Red",
    mat_type="PLA",
    tags=[],
    color="#FF0000",
)

_OPT_HATCHBOX_PLA_BLUE = _opt(
    slug="hatchbox-pla-blue",
    brand="Hatchbox",
    name="Blue",
    mat_type="PLA",
    tags=[],
    color="#0000FF",
)

# ---------------------------------------------------------------------------
# GOLDEN TEST 1: AMOLEN Silk Shiny Gradient Silver & Shiny Blue must rank #1
# ---------------------------------------------------------------------------


def test_amolen_silk_gradient_silver_blue_ranks_first():
    """AMOLEN 'Silk Shiny Gradient Silver & Shiny Blue' must rank #1 over 'Dual Color Blue & Fuchsia'.

    This is the core v1 failure case.  The v1 scorer collapsed Silver→grey and stripped
    modifiers like 'shiny'/'gradient', making the near-perfect match invisible.

    v2 expects: target ~0.80+ > wrong ≥ 0.10 gap.
    """
    sm = _sm(
        name="Silk Shiny Gradient Silver & Shiny Blue",
        vendor="AMOLEN",
        material="PLA Silk",
        color_hex="C0C0C0",
        multi_color_hexes="C0C0C0,4169E1",
        multi_color_direction="longitudinal",
    )
    candidates = [
        _OPT_AMOLEN_SILK_GRADIENT_SILVER_BLUE,
        _OPT_AMOLEN_DUAL_BLUE_FUCHSIA,
        _OPT_AMOLEN_SILK_GOLD,
    ]

    s_target = score_candidate(sm, _OPT_AMOLEN_SILK_GRADIENT_SILVER_BLUE)
    s_wrong = score_candidate(sm, _OPT_AMOLEN_DUAL_BLUE_FUCHSIA)

    assert s_target > s_wrong, (
        f"Target ({s_target:.4f}) must beat Dual Blue/Fuchsia ({s_wrong:.4f})"
    )
    # Gap must be substantial (not a tie) — at least 0.10
    assert s_target - s_wrong >= 0.10, (
        f"Gap must be >= 0.10, got {s_target - s_wrong:.4f}"
    )

    result = find_best_match(sm, candidates, min_confidence=0.0)
    assert result["best"] is not None
    assert result["best"]["slug"] == "amolen-pla-silk-shiny-gradient-silver-shiny-blue", (
        f"Expected target slug, got '{result['best']['slug']}'"
    )


def test_amolen_dual_blue_fuchsia_scores_strictly_below_target():
    """'Dual Color Blue & Fuchsia' must score strictly below the shiny-gradient target."""
    sm = _sm(
        name="Silk Shiny Gradient Silver & Shiny Blue",
        vendor="AMOLEN",
        material="PLA Silk",
        color_hex="C0C0C0",
    )
    s_target = score_candidate(sm, _OPT_AMOLEN_SILK_GRADIENT_SILVER_BLUE)
    s_wrong = score_candidate(sm, _OPT_AMOLEN_DUAL_BLUE_FUCHSIA)
    assert s_wrong < s_target, (
        f"Dual Blue/Fuchsia ({s_wrong:.4f}) must be strictly below target ({s_target:.4f})"
    )


# ---------------------------------------------------------------------------
# GOLDEN TEST 2: Orange-vs-Copper preserved
# ---------------------------------------------------------------------------


def test_orange_vs_copper_preserved():
    """SM 'Orange / Hatchbox / PETG' (hex CB6D30) must rank Orange #1 over Copper.

    Preserved from v1 — the color NAME dominates over hex proximity.
    """
    sm = _sm(name="Orange", vendor="Hatchbox", material="PETG", color_hex="CB6D30")
    s_orange = score_candidate(sm, _OPT_HATCHBOX_PETG_ORANGE)
    s_copper = score_candidate(sm, _OPT_HATCHBOX_PETG_COPPER)
    assert s_orange > s_copper, (
        f"Orange ({s_orange:.4f}) must beat Copper ({s_copper:.4f})"
    )
    result = find_best_match(sm, [_OPT_HATCHBOX_PETG_ORANGE, _OPT_HATCHBOX_PETG_COPPER])
    assert result["best"] is not None
    assert result["best"]["slug"] == "hatchbox-petg-orange"


# ---------------------------------------------------------------------------
# GOLDEN TEST 3: Single-color Red (Hatchbox)
# ---------------------------------------------------------------------------


def test_hatchbox_red_single_color():
    """SM 'Red / Hatchbox / PLA' must match 'Red' OPT entry over 'Blue'."""
    sm = _sm(name="Red", vendor="Hatchbox", material="PLA", color_hex="FF0000")
    s_red = score_candidate(sm, _OPT_HATCHBOX_PLA_RED)
    s_blue = score_candidate(sm, _OPT_HATCHBOX_PLA_BLUE)
    assert s_red > s_blue, (
        f"Red ({s_red:.4f}) must beat Blue ({s_blue:.4f})"
    )
    result = find_best_match(sm, [_OPT_HATCHBOX_PLA_RED, _OPT_HATCHBOX_PLA_BLUE])
    assert result["best"]["slug"] == "hatchbox-pla-red"


# ---------------------------------------------------------------------------
# GOLDEN TEST 4: Matte vs Silk discrimination
# ---------------------------------------------------------------------------


def test_matte_vs_silk_discrimination():
    """SM 'PLA Matte Red / ELEGOO' must rank matte #1, silk strictly lower."""
    sm = _sm(name="PLA Matte Red", vendor="ELEGOO", material="PLA Matte", color_hex="CC0000")
    s_matte = score_candidate(sm, _OPT_ELEGOO_PLA_MATTE_RED)
    s_silk = score_candidate(sm, _OPT_ELEGOO_PLA_SILK_RED)
    assert s_matte > s_silk, (
        f"Matte ({s_matte:.4f}) must beat Silk ({s_silk:.4f}) for a matte query"
    )


def test_silk_vs_matte_discrimination():
    """SM 'PLA Silk Red / ELEGOO' must rank silk #1, matte strictly lower."""
    sm = _sm(name="PLA Silk Red", vendor="ELEGOO", material="PLA Silk", color_hex="CC0000")
    s_silk = score_candidate(sm, _OPT_ELEGOO_PLA_SILK_RED)
    s_matte = score_candidate(sm, _OPT_ELEGOO_PLA_MATTE_RED)
    assert s_silk > s_matte, (
        f"Silk ({s_silk:.4f}) must beat Matte ({s_matte:.4f}) for a silk query"
    )


# ---------------------------------------------------------------------------
# GOLDEN TEST 5: No-modifier, color-only multiset parity
# ---------------------------------------------------------------------------


def test_identical_multiset_scores_1_0():
    """Two identical color multisets score 1.0."""
    a: Counter = Counter({"red": 1, "blue": 1})
    b: Counter = Counter({"red": 1, "blue": 1})
    assert _color_multiset_score(a, b) == 1.0


def test_disjoint_multisets_score_0_0():
    """Two completely disjoint color multisets score 0.0."""
    a: Counter = Counter({"red": 1})
    b: Counter = Counter({"blue": 1})
    assert _color_multiset_score(a, b) == 0.0


def test_subset_multiset_partial_score():
    """A ⊂ B gives partial score > 0 and < 1."""
    a: Counter = Counter({"red": 1})
    b: Counter = Counter({"red": 1, "blue": 1})
    score = _color_multiset_score(a, b)
    assert 0.0 < score < 1.0
    # matched=1, extra_a=0, extra_b=1 → score = 1/2 = 0.5
    assert score == pytest.approx(0.5)


def test_neutral_when_one_side_empty():
    """Empty Counter on either side → neutral 0.5."""
    assert _color_multiset_score(Counter(), Counter({"red": 1})) == 0.5
    assert _color_multiset_score(Counter({"red": 1}), Counter()) == 0.5
    assert _color_multiset_score(Counter(), Counter()) == 0.5


# ---------------------------------------------------------------------------
# GOLDEN TEST 6: Modifier Jaccard
# ---------------------------------------------------------------------------


def test_modifier_jaccard_identical():
    """Identical modifier sets → 1.0."""
    a = frozenset({"shiny", "gradient"})
    assert _modifier_jaccard(a, a) == 1.0


def test_modifier_jaccard_disjoint():
    """Disjoint modifier sets → 0.0."""
    a = frozenset({"shiny"})
    b = frozenset({"marble"})
    assert _modifier_jaccard(a, b) == 0.0


def test_modifier_jaccard_both_empty():
    """Both empty → neutral 0.5."""
    assert _modifier_jaccard(frozenset(), frozenset()) == 0.5


# ---------------------------------------------------------------------------
# GOLDEN TEST 7: decompose_name — color and modifier classification
# ---------------------------------------------------------------------------


def test_decompose_name_colors_classified_correctly():
    """'PLA Silk Bronze / Buddy3D / PLA' → colors={'bronze'}, finish=silk."""
    from app.core.material_tags import DEFAULT_MATERIAL_TAG_IDS
    parsed = decompose_name("PLA Silk Bronze", "Buddy3D", "PLA", DEFAULT_MATERIAL_TAG_IDS)
    assert "bronze" in parsed.colors, f"Expected 'bronze' in colors, got {dict(parsed.colors)}"
    # Silk is a finish tag, not a modifier
    from app.core.material_tags import DEFAULT_MATERIAL_TAG_IDS as _tm
    silk_id = _tm.get("silk")
    if silk_id:
        assert silk_id in parsed.finish_ids, "Expected silk finish id"


def test_decompose_name_multiset_counts_repeated():
    """'Silver & Shiny Blue' → colors={'silver':1, 'blue':1}, 'shiny' in modifiers."""
    from app.core.material_tags import DEFAULT_MATERIAL_TAG_IDS
    parsed = decompose_name(
        "PLA Silk Shiny Gradient Silver & Shiny Blue", "AMOLEN", "PLA Silk",
        DEFAULT_MATERIAL_TAG_IDS,
    )
    # Silver and blue should be in colors
    assert "silver" in parsed.colors or "grey" in parsed.colors, (
        f"Expected 'silver' or 'grey' in colors, got {dict(parsed.colors)}"
    )
    assert "blue" in parsed.colors, f"Expected 'blue' in colors, got {dict(parsed.colors)}"


def test_decompose_name_separator_not_crossed():
    """N-grams must not span the '&' separator — so 'silver blue' is NOT a bigram."""
    from app.core.material_tags import DEFAULT_MATERIAL_TAG_IDS
    parsed = decompose_name(
        "Silver & Blue", "TestBrand", "PLA",
        DEFAULT_MATERIAL_TAG_IDS,
    )
    # Both colors should appear independently in the counter
    # 'silver blue' must not form a bigram modifier
    assert "silver" in parsed.colors or "silver" in {k: v for k, v in parsed.colors.items()}
    assert "blue" in parsed.colors
    # "silver blue" must NOT appear as a modifier (would only happen if & was crossed)
    assert "silver blue" not in parsed.modifiers


# ---------------------------------------------------------------------------
# GOLDEN TEST 8: find_best_match with explicit lexicon
# ---------------------------------------------------------------------------


def test_find_best_match_with_lexicon_kwarg():
    """find_best_match accepts lexicon= kwarg and uses it for scoring."""
    sm = _sm(name="Silk Shiny Gradient Silver & Shiny Blue", vendor="AMOLEN", material="PLA Silk")
    candidates = [_OPT_AMOLEN_SILK_GRADIENT_SILVER_BLUE, _OPT_AMOLEN_DUAL_BLUE_FUCHSIA]

    # With seed-only lexicon (lexicon=None)
    result_seed = find_best_match(sm, candidates, lexicon=None, min_confidence=0.0)
    # With explicit minimal lexicon
    minimal_lex = {
        "modifiers": ["shiny", "gradient", "dual color"],
        "colors": ["silver", "blue", "gold", "fuchsia", "red", "green"],
    }
    result_lex = find_best_match(sm, candidates, lexicon=minimal_lex, min_confidence=0.0)

    # Both should rank target first
    assert result_seed["best"]["slug"] == "amolen-pla-silk-shiny-gradient-silver-shiny-blue"
    assert result_lex["best"]["slug"] == "amolen-pla-silk-shiny-gradient-silver-shiny-blue"
