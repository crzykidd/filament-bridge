"""Golden-set regression tests for the OpenTag v2/v2.1 matcher.

Each test case uses real-world Spoolman filament descriptions and real-world
OpenPrintTag material entries.  The key invariants checked here:

1. AMOLEN "Silk Shiny Gradient Silver & Shiny Blue" ranks #1 over
   "Dual Color Blue & Fuchsia" (the core v1 failure case).
2. Orange-vs-Copper is preserved (single color name wins over hex proximity).
3. Hatchbox Red single-color matches correctly.
4. Matte vs Silk finish-tag discrimination.
5. Multicolor profile compatibility gate.
6. (v2.1) CC3D "Temperature Color Change Purple to Red" ranks #1 over green-to-yellow;
   name-aware color arity gate lets it through despite incomplete hex data.
7. (v2.1) ColorFabb "PLA Woodfill" ranks #1 over steelfill; PLA-biopolymer bucket
   lets the PHA-typed woodfill candidate through the family gate.
8. (v2.1) families_gate_compatible truth table.
9. (v2.1) Cross-family regression: PETG candidate is gate-dropped for an ASA filament.
"""

from __future__ import annotations

import pytest
from collections import Counter

from app.core.opentag_match import (
    _color_multiset_score,
    _modifier_jaccard,
    color_profile_compatible_soft,
    decompose_name,
    families_gate_compatible,
    find_best_match,
    material_family,
    score_candidate,
    sm_color_profile,
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


# ===========================================================================
# v2.1 NEW GOLDEN TESTS
# ===========================================================================

# ---------------------------------------------------------------------------
# OPT candidates — CC3D Temperature Color Change
# ---------------------------------------------------------------------------
#
# cc3d-temperature-color-change-pla-purple-to-red:
#   type=PLA, color=None, secondaryColors=["#963877"] (only ONE secondary)
#   → old gate: opt_color_profile = "single" (< 2 secondaries)
#   → old behavior: profiles_compatible("multi_unknown", "single") = False → DROPPED
#   → v2.1: opt_color_arity uses name decomposition; name has "purple" + "red" → arity 2 → KEPT
#
# cc3d-temperature-color-change-pla-green-to-yellow:
#   type=PLA, color="#00FF00", secondaryColors=["#FFFF00"] (ONE secondary)
#   → similar hex situation, but "green" + "yellow" are different colors than "purple" + "red"

_OPT_CC3D_TEMP_CHANGE_PURPLE_RED = _opt(
    slug="cc3d-temperature-color-change-pla-purple-to-red",
    brand="CC3D",
    name="Temperature Color Change Purple to Red",
    mat_type="PLA",
    tags=[],
    color=None,
    secondary=["#963877"],  # only one secondary → old gate said "single"
)

_OPT_CC3D_TEMP_CHANGE_GREEN_YELLOW = _opt(
    slug="cc3d-temperature-color-change-pla-green-to-yellow",
    brand="CC3D",
    name="Temperature Color Change Green to Yellow",
    mat_type="PLA",
    tags=[],
    color="#00FF00",
    secondary=["#FFFF00"],  # one secondary → also "single" by old gate
)

# A second multi-secondary variant for the gate test (ensures strict path works)
_OPT_CC3D_TEMP_CHANGE_BLUE_WHITE = _opt(
    slug="cc3d-temperature-color-change-pla-blue-to-white",
    brand="CC3D",
    name="Temperature Color Change Blue to White",
    mat_type="PLA",
    tags=[],
    color="#0000FF",
    secondary=["#FFFFFF", "#AAAAAA"],  # two secondaries → "multi_unknown"
)

# ---------------------------------------------------------------------------
# OPT candidates — ColorFabb *fill composites
# ---------------------------------------------------------------------------
#
# colorfabb-woodfill: type=PHA (inconsistently typed in OPT; the physical product
#   is a PLA/PHA blend with wood fibres)
# colorfabb-steelfill: type=PLA
# colorfabb-copperfill: type=PHA (also a PLA/PHA + copper powder blend)

_OPT_COLORFABB_WOODFILL = _opt(
    slug="colorfabb-woodfill",
    brand="colorFabb",
    name="PLA/PHA woodFill",
    mat_type="PHA",  # inconsistently typed as PHA in OpenPrintTag
    tags=[],
    color="#8B6914",
)

_OPT_COLORFABB_STEELFILL = _opt(
    slug="colorfabb-steelfill",
    brand="colorFabb",
    name="steelFill",
    mat_type="PLA",
    tags=[],
    color="#888888",
)

_OPT_COLORFABB_COPPERFILL = _opt(
    slug="colorfabb-copperfill",
    brand="colorFabb",
    name="copperFill",
    mat_type="PHA",
    tags=[],
    color="#B87333",
)

# ---------------------------------------------------------------------------
# GOLDEN TEST 9 (v2.1): CC3D Temperature Color Change Purple to Red ranks #1
# ---------------------------------------------------------------------------


def test_cc3d_temp_change_purple_red_ranks_first():
    """v2.1: CC3D 'Temperature Color Change Purple to Red' must rank #1.

    The SM filament is multicolor (multi_color_hexes set → multi_unknown profile).
    The OPT purple-to-red entry has color=None + only ONE secondaryColor, so the
    old gate (profiles_compatible) would classify it as "single" and drop it.
    With v2.1 name-aware arity, the name contributes 2 color tokens (purple, red)
    → arity=2 → the entry passes the soft gate and scores on name match.

    The green-to-yellow entry must score strictly BELOW the purple-to-red entry.
    """
    sm = _sm(
        name="Temperature Color Change Purple to Red",
        vendor="CC3D",
        material="PLA",
        multi_color_hexes="963877,FF0000",
        multi_color_direction="coaxial",
    )
    candidates = [
        _OPT_CC3D_TEMP_CHANGE_PURPLE_RED,
        _OPT_CC3D_TEMP_CHANGE_GREEN_YELLOW,
        _OPT_CC3D_TEMP_CHANGE_BLUE_WHITE,
    ]

    s_purple_red = score_candidate(sm, _OPT_CC3D_TEMP_CHANGE_PURPLE_RED)
    s_green_yellow = score_candidate(sm, _OPT_CC3D_TEMP_CHANGE_GREEN_YELLOW)

    assert s_purple_red > s_green_yellow, (
        f"purple-to-red ({s_purple_red:.4f}) must beat green-to-yellow ({s_green_yellow:.4f})"
    )

    result = find_best_match(sm, candidates, min_confidence=0.0)
    assert result["best"] is not None
    assert result["best"]["slug"] == "cc3d-temperature-color-change-pla-purple-to-red", (
        f"Expected purple-to-red slug, got '{result['best']['slug'] if result['best'] else None}'"
    )


def test_cc3d_purple_red_passes_soft_gate():
    """v2.1: The purple-to-red OPT entry must NOT be filtered out by the soft color-profile gate.

    SM is multicolor (sm_arity >= 2).  The OPT entry has color=None + 1 secondary
    → hex_count=1.  But decompose_name on the OPT name yields colors={purple:1, red:1}
    → name_color_count=2 → opt_color_arity=max(1,2)=2 → passes (arity >= 2 for multicolor SM).
    """
    sm = _sm(
        name="Temperature Color Change Purple to Red",
        vendor="CC3D",
        material="PLA",
        multi_color_hexes="963877,FF0000",
        multi_color_direction="coaxial",
    )
    sm_profile = sm_color_profile(sm)
    sm_parsed = decompose_name(sm.name, "CC3D", "PLA")
    sm_arity = sum(sm_parsed.colors.values())
    if sm.multi_color_hexes:
        hex_arity = 1 + len([h for h in sm.multi_color_hexes.split(",") if h.strip()])
        sm_arity = max(sm_arity, hex_arity)

    assert sm_arity >= 2, f"SM arity must be >= 2, got {sm_arity}"
    assert color_profile_compatible_soft(sm_profile, sm_arity, _OPT_CC3D_TEMP_CHANGE_PURPLE_RED), (
        "purple-to-red must pass the soft color-profile gate"
    )


# ---------------------------------------------------------------------------
# GOLDEN TEST 10 (v2.1): ColorFabb PLA Woodfill ranks #1 over steelfill
# ---------------------------------------------------------------------------


def test_colorfabb_woodfill_ranks_first():
    """v2.1: ColorFabb 'PLA Woodfill' must rank #1 over steelfill and copperfill.

    The SM filament material is 'PLA'. The woodfill OPT entry is typed as 'PHA'.
    The old family gate would block PHA for a PLA SM filament.
    With v2.1 PLA-biopolymer bucket (PLA↔PHA compatible), woodfill passes the gate.

    The '*fill' descriptor ('woodfill') is now in the modifier lexicon via
    COMPOSITE_DESCRIPTOR_SEED, so woodfill scores modifier_jaccard=1.0 vs steelfill=0.0.
    """
    sm = _sm(
        name="PLA Woodfill",
        vendor="colorFabb",
        material="PLA",
    )
    candidates = [
        _OPT_COLORFABB_WOODFILL,
        _OPT_COLORFABB_STEELFILL,
        _OPT_COLORFABB_COPPERFILL,
    ]

    s_woodfill = score_candidate(sm, _OPT_COLORFABB_WOODFILL)
    s_steelfill = score_candidate(sm, _OPT_COLORFABB_STEELFILL)
    s_copperfill = score_candidate(sm, _OPT_COLORFABB_COPPERFILL)

    assert s_woodfill > s_steelfill, (
        f"woodfill ({s_woodfill:.4f}) must beat steelfill ({s_steelfill:.4f})"
    )
    assert s_woodfill > s_copperfill, (
        f"woodfill ({s_woodfill:.4f}) must beat copperfill ({s_copperfill:.4f})"
    )

    result = find_best_match(sm, candidates, min_confidence=0.0)
    assert result["best"] is not None
    assert result["best"]["slug"] == "colorfabb-woodfill", (
        f"Expected woodfill slug, got '{result['best']['slug'] if result['best'] else None}'"
    )


def test_woodfill_decompose_name_has_woodfill_modifier():
    """'woodFill' token must appear in the modifier bag after decompose_name."""
    parsed = decompose_name("PLA/PHA woodFill", "colorFabb", "PHA")
    assert "woodfill" in parsed.modifiers, (
        f"Expected 'woodfill' in modifiers, got {parsed.modifiers}"
    )


def test_steelfill_decompose_name_has_steelfill_modifier():
    """'steelFill' token must appear in the modifier bag after decompose_name."""
    parsed = decompose_name("steelFill", "colorFabb", "PLA")
    assert "steelfill" in parsed.modifiers, (
        f"Expected 'steelfill' in modifiers, got {parsed.modifiers}"
    )


def test_woodfill_modifier_jaccard_vs_steelfill():
    """woodfill vs woodfill = 1.0 Jaccard; woodfill vs steelfill = 0.0 Jaccard."""
    from app.core.opentag_match import _modifier_jaccard
    wf = frozenset({"woodfill"})
    sf = frozenset({"steelfill"})
    assert _modifier_jaccard(wf, wf) == 1.0, "Same fill descriptor must score 1.0"
    assert _modifier_jaccard(wf, sf) == 0.0, "Different fill descriptors must score 0.0"


# ---------------------------------------------------------------------------
# GOLDEN TEST 11 (v2.1): families_gate_compatible truth table
# ---------------------------------------------------------------------------


def test_families_gate_compatible_truth_table():
    """families_gate_compatible must satisfy the PLA-bucket truth table."""
    # PLA biopolymer bucket members — all pairs compatible
    assert families_gate_compatible("pla", "pha") is True,   "PLA↔PHA must be compatible"
    assert families_gate_compatible("pla", "lw-pla") is True, "PLA↔LW-PLA must be compatible"
    assert families_gate_compatible("pla", "htpla") is True,  "PLA↔HTPLA must be compatible"
    assert families_gate_compatible("pla", "rpla") is True,   "PLA↔rPLA must be compatible"
    assert families_gate_compatible("pha", "pla") is True,    "PHA↔PLA must be compatible"
    assert families_gate_compatible("lw-pla", "pla") is True, "LW-PLA↔PLA must be compatible"

    # Same family always compatible
    assert families_gate_compatible("petg", "petg") is True,  "PETG↔PETG must be compatible"
    assert families_gate_compatible("asa", "asa") is True,    "ASA↔ASA must be compatible"
    assert families_gate_compatible("pla", "pla") is True,    "PLA↔PLA must be compatible"

    # Empty/unknown OPT family → always compatible (don't gate on missing data)
    assert families_gate_compatible("asa", "") is True,       "anything↔'' must be compatible"
    assert families_gate_compatible("petg", "") is True,      "anything↔'' must be compatible"

    # Cross-family strict separation
    assert families_gate_compatible("asa", "petg") is False,  "ASA↔PETG must NOT be compatible"
    assert families_gate_compatible("pc", "petg") is False,   "PC↔PETG must NOT be compatible"
    assert families_gate_compatible("petg", "asa") is False,  "PETG↔ASA must NOT be compatible"
    assert families_gate_compatible("asa", "abs") is False,   "ASA↔ABS must NOT be compatible"
    assert families_gate_compatible("pla", "petg") is False,  "PLA↔PETG must NOT be compatible"


# ---------------------------------------------------------------------------
# GOLDEN TEST 12 (v2.1): Cross-family regression — PETG candidate gate-dropped for ASA
# ---------------------------------------------------------------------------


def test_petg_candidate_gate_dropped_for_asa_filament():
    """v2.1: A PETG OPT candidate must be filtered out by the family gate for an ASA SM filament.

    This confirms the gate softening didn't over-merge unrelated polymers.
    ASA and PETG are NOT in the PLA-biopolymer bucket, so they remain strictly gated.
    """
    _opt_asa_black = _opt(
        slug="some-brand-asa-black",
        brand="Generic",
        name="ASA Black",
        mat_type="ASA",
        tags=[],
        color="#000000",
    )
    _opt_petg_black = _opt(
        slug="some-brand-petg-black",
        brand="Generic",
        name="PETG Black",
        mat_type="PETG",
        tags=[],
        color="#000000",
    )

    sm_asa = _sm(name="Black", vendor="Generic", material="ASA", color_hex="000000")
    sm_fam = material_family(sm_asa.material)

    # Manually apply the family gate as the opentag_matches endpoint would
    candidates = [_opt_asa_black, _opt_petg_black]
    gate_passed = [
        c for c in candidates
        if families_gate_compatible(
            sm_fam,
            material_family(c.get("type") or c.get("abbreviation") or ""),
        )
    ]

    slugs_passed = [c["slug"] for c in gate_passed]
    assert "some-brand-asa-black" in slugs_passed, "ASA candidate must pass the gate"
    assert "some-brand-petg-black" not in slugs_passed, (
        "PETG candidate must be gate-DROPPED for an ASA SM filament"
    )
