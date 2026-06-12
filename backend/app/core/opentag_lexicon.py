"""OpenTag lexicon mining — pure, deterministic, no I/O.

Mines a modifier and color lexicon from the OpenPrintTag material dataset by:
  1. Computing residual tokens per material (brand + material + finish words removed).
  2. Subtracting known base colors (seed list).
  3. Extracting uni/bi/tri-grams that do NOT cross ``&`` or ``/`` separators.
  4. Applying frequency thresholds and a bigram-lift rule to promote genuine phrases.
  5. Subtracting tokens covered by a longer already-kept n-gram.
  6. Unconditionally merging a hand-curated MODIFIER_SEED list.
  7. Returning deterministically sorted lists (longest-first, then alpha).

The result is ``{"modifiers": [...], "colors": [...]}`` where each entry is a
lowercase string (possibly multi-word, e.g. "dual color", "color change").

The mined data is stored alongside the cache (``opentag_cache.json``) under the
``lexicon`` key and versioned via ``lexicon_version``.  When the version is
missing or stale, ``mine_lexicons`` is called in-place without a network re-fetch.

Design notes
------------
* N-grams do NOT cross ``&`` or ``/`` separators — those mark color-conjunction
  boundaries in OpenPrintTag names (e.g. "Silver & Blue") so "silver blue" must
  NOT be promoted as a bigram phrase.
* Bigram-lift rule: a bigram ``(A, B)`` is only kept as a phrase when
  ``freq(AB) / (freq(A) * freq(B) / N)`` exceeds BIGRAM_LIFT_THRESHOLD.  This
  means "dual color" (near-always co-occurring) is kept as a unit while
  "shiny gradient" (each token appears with many other partners) is NOT — each of
  those is kept as a separate unigram modifier instead.
* Trigrams bypass the lift rule — they are kept purely by MODIFIER_MIN_COUNT and
  MODIFIER_MIN_BRANDS because three-token co-occurrence is already sufficiently
  specific.
* After keep/discard decisions the subtract-covered-by-longer step ensures that
  once "dual color" is kept as a bigram the standalone "dual" and "color" unigrams
  are removed from the modifier set (they would be spurious noise).
* MODIFIER_SEED items are always present regardless of frequency — they capture
  rare-but-important modifiers that may not appear in 5+ materials.
* Colors use stricter thresholds (COLOR_MIN_COUNT, COLOR_MIN_BRANDS) because the
  color lexicon must be clean: a noisy color entry causes a false multiset match.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Any

from app.core.material_tags import DEFAULT_MATERIAL_TAG_IDS, strip_finish_words
from app.core.matcher import normalize_vendor

# ---------------------------------------------------------------------------
# Thresholds (module-level constants — tune during the pause review)
# ---------------------------------------------------------------------------

#: Minimum number of materials a modifier token/phrase must appear in to be kept.
MODIFIER_MIN_COUNT: int = 5

#: Minimum number of distinct brands a modifier must appear across to be kept.
#: Guards against brand-specific terminology being promoted.
MODIFIER_MIN_BRANDS: int = 2

#: Bigram lift threshold.  A bigram is kept as a phrase only when
#: ``freq(AB) / (freq(A) * freq(B) / N)`` exceeds this value.
#: Lower = more permissive (keeps more phrases); higher = stricter.
#: "dual color" has lift ~20+; "shiny gradient" ~1–3.
BIGRAM_LIFT_THRESHOLD: float = 8.0

#: Minimum number of materials a COLOR token must appear in.
COLOR_MIN_COUNT: int = 8

#: Minimum number of distinct brands a color token must appear across.
COLOR_MIN_BRANDS: int = 3

#: Version tag for the lexicon stored in the cache.  Increment whenever the
#: mining algorithm changes in a way that would produce a different lexicon.
#: v2: extended BASE_COLORS seed (color-leak fix + gfN/rfid/htpla/rpla/rpetg/esd stop-list)
LEXICON_VERSION: int = 2

# ---------------------------------------------------------------------------
# Seed lists — always included regardless of frequency
# ---------------------------------------------------------------------------
# Stop words — never promoted to modifiers or colors
# ---------------------------------------------------------------------------

#: Tokens that must never appear in the modifier or color lexicons.
#: These are generic English function words, material abbreviations that slip
#: through the type-strip step, numeric noise, and other unavoidable residual
#: noise from the dataset.
STOP_WORDS: frozenset[str] = frozenset({
    # English function / stop words
    "the", "and", "of", "in", "to", "for", "by", "with", "on", "at",
    "it", "as", "an", "or", "is", "be", "do", "go", "no", "so",
    "co",  # e.g. "Co." in company names
    # Generic filament/product words that don't discriminate anything
    "filament", "spool", "brand", "color", "colour",
    # Material abbreviations that appear in names even after material-field strip
    "ps", "gf", "pa", "pbt",
    # Glass-fiber / compound grade codes — gf10, gf15, gf25, gf30, gfN, etc.
    # The bare "gf" prefix is already above; these multi-char variants also appear
    # as standalone tokens when the name includes "GF10" etc.
    "gf10", "gf15", "gf20", "gf25", "gf30", "gf35", "gf40",
    # Shore-hardness / flexometer suffixes (95A, 98A, 85A, 90A, etc.)
    "95a", "98a", "85a", "90a", "82a", "60a", "87a", "60d", "30d", "40d", "92a", "96a",
    "9085", "1010", "66", "150", "870", "850",
    # RAL color code prefix — "ral" is a code system, not a color name
    "ral",
    # Polymer / compound abbreviations that are material subtypes
    "nylon", "flex", "tough", "impact", "pet",
    # Polymer/grade codes that slip through the material-field strip
    # htpla = high-temp PLA variant, rpla/rpetg = recycled, esd = ESD-safe grade
    # rfid = RFID-tagged product, paht = high-temperature PA variant
    "htpla", "rpla", "rpetg", "esd", "rfid",
    # Misc noise tokens — these come from n-gram fragments or line-name codes
    "re", "v0", "v2", "v3",
    "fast", "hyper", "speed", "high", "change", "dark", "light",
    # Abbreviations for material grades that appear as standalone tokens in names
    "fr", "lw", "ht",
    # Truly generic words that aren't useful as discriminators
    "hf",
    # Shore hardness scale words — these appear in hardness specs, not color/modifier names
    "hardness", "shore",
    # Temperature/reactivity fragments that appear as lone tokens from n-gram splits
    "reactive", "temp", "temperature", "retardant",
    # Standalone fiber word — left after stripping "carbon"/"glass" finish tags
    "fiber", "fibre",
    # Color-adjacent fragments that are NOT standalone color names
    "medium", "multi",
    # These appear in color names but are never standalone color identities
    "triple", "polar", "starry",
    # Polymer sub-type shorthand
    "abs",
    # Color-modifier adjectives: these only appear as qualifiers of a color, not as standalone colors.
    # "burnt orange", "deep red", "hot pink", "gun gray", etc. — the modifier is in the modifier list.
    "burnt", "deep", "fire", "cold", "flame", "military", "hot", "gun",
    # Material words that end up in color residual
    "iron", "steel", "engine",
    # Generic product-line words that slip through as "colors"
    "magic", "candy", "crystal",
    # Generic quality/modifier words
    "hi", "tone",
    # Material abbreviation
    "paht",
    # Location/adjective words that only appear as qualifiers of a color name
    "earth", "stealth",
    # "Banana Yellow", "Sunny Orange", "Sunshine Yellow" — modifiers, not standalone colors
    "banana", "sunny", "sunshine",
    # "Space Gray/Grey" — brand/Apple marketing, not a standalone color word
    "space",
})

# ---------------------------------------------------------------------------

#: Hand-curated modifier seeds.  These are unconditionally unioned into the
#: mined modifier set so that rare-but-important terms are never missed.
#: Multi-word entries (e.g. "dual color") are stored as plain strings here;
#: the matcher splits them back into n-grams for matching.
MODIFIER_SEED: frozenset[str] = frozenset({
    # Multi-color descriptors
    "dual color",
    "triple color",
    "tri color",
    "multicolor",
    "multi color",
    "bi color",
    "dual",
    "tri",
    # Surface / finish modifiers (that aren't tracked as finish-tag IDs)
    "shiny",
    "glossy",
    "gradient",
    "galaxy",
    "sparkle",
    "glitter",
    "glow",
    "marble",
    "rainbow",
    "neon",
    "luminous",
    "fluorescent",
    "uv",
    "holographic",
    "iridescent",
    # Change / reactive
    "color change",
    "colour change",
    "temperature change",
    "uv change",
    "thermochromic",
    "photochromic",
    # Texture / brand-line qualifiers
    "basic",
    "standard",
    "premium",
    "pro",
    "plus",
    "lite",
    "ultra",
    "max",
    "s series",
    "s-series",
    "hs",
    # Structural / fill modifiers that DON'T have finish-tag IDs
    "toughened",
    "reinforced",
    "blended",
    "filled",
    # Special optical
    "translucent",
    "transparent",
    # Pearl / metallic (distinct from the metallic finish tag — these appear in COLOR names)
    "pearl",
    "metallic",
    "chrome",
    "mirror",
    "satin",
    "pastel",
    "silk",
})

#: Base color seed — canonical color names that seed the COLOR lexicon.
#: The miner subtracts these BEFORE looking for new color words in the residual,
#: AND checks each residual unigram against this set BEFORE filing it under modifiers.
#: Any token that appears here is classified as a COLOR — not a modifier — regardless
#: of how many brands it appears in.
#:
#: Design note (color-leak fix, 2026-06-11):
#: Several real color names like "turquoise", "fuchsia", "emerald", "graphite",
#: "golden", "rosa" were being mined as modifiers because they appeared in fewer
#: than COLOR_MIN_BRANDS brands. Adding them here guarantees they are treated as
#: colors during decomposition and are subtracted from modifier candidates.
BASE_COLORS: frozenset[str] = frozenset({
    # Primary / achromatic
    "black", "white", "grey", "gray",
    # Metallic / neutral
    "silver", "gold", "bronze", "copper", "champagne",
    # Reds
    "red", "crimson", "scarlet", "ruby", "maroon", "burgundy", "wine",
    "cherry", "rose", "pink", "magenta", "fuchsia", "coral", "salmon",
    # Oranges / yellows
    "orange", "amber", "peach", "yellow", "golden", "lime",
    # Greens
    "green", "olive", "mint", "forest", "emerald", "jade", "grass",
    "army",  # "army green" is common in names
    # Blues
    "blue", "navy", "indigo", "cobalt", "sapphire", "sky", "azure",
    "ocean", "royal",  # "royal blue"
    "electric",  # "electric blue" in many names
    "ice",  # "ice blue" / "ice white" — distinct color family in OPT
    # Purples
    "purple", "violet", "lavender", "lilac", "plum", "mauve",
    # Browns / tans
    "brown", "beige", "tan", "khaki", "chocolate",
    # Whites / lights
    "ivory", "cream",
    # pearl: intentionally NOT here — it is tracked via finish-tag IDs (modifier),
    # not as a standalone color identity. Keeping pearl in MODIFIER_SEED is correct.
    # Others
    "natural", "clear", "transparent",
    "cyan", "teal", "aqua",
    "charcoal", "ash", "graphite",
    # Marketing color names that appear consistently as color identities
    "turquoise",  # distinct shade between blue and green
    "rosa",       # "rosa" = pink in Spanish/Italian; used in OPT as a color name
    "midnight",   # "midnight black / midnight blue" — color family
    "apple",      # "apple green" — consistent color identity across brands
    # Standard CSS / web color names that are used as filament color names
    "aquamarine", "bisque", "blueviolet", "cadetblue", "chartreuse",
    "cornflower", "darkgreen", "darkred", "deeppink", "dodgerblue",
    "firebrick", "forestgreen", "fuchsia", "goldenrod", "honeydew",
    "hotpink", "indianred", "khaki", "lightblue", "lightgreen",
    "lightsalmon", "limegreen", "mediumblue", "mediumorchid",
    "mediumpurple", "mediumseagreen", "mediumslateblue",
    "mediumspringgreen", "mediumturquoise", "mediumvioletred",
    "mintcream", "mistyrose", "moccasin", "navajowhite", "oldlace",
    "olivedrab", "orangered", "orchid", "palegreen", "paleturquoise",
    "palevioletred", "papayawhip", "peru", "powderblue", "rosybrown",
    "royalblue", "saddlebrown", "sandybrown", "seagreen", "seashell",
    "sienna", "skyblue", "slateblue", "slategray", "slategrey",
    "springgreen", "steelblue", "tomato", "turquoise", "wheat",
    "whitesmoke", "yellowgreen",
})

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _norm(s: str | None) -> str:
    """Normalise a string: NFKC unicode, lower, strip."""
    if not s:
        return ""
    return unicodedata.normalize("NFKC", s).lower().strip()


def _residual_tokens(
    name: str | None,
    vendor: str | None,
    material: str | None,
    tag_map: dict[str, int] | None = None,
) -> list[str]:
    """Return an ordered list of residual lowercase tokens from a material name,
    with vendor, material, and finish words removed.

    The order is preserved so that n-gram extraction can respect word adjacency
    and separator boundaries (``&``, ``/``).  Separator positions are represented
    by inserting a sentinel token ``"__SEP__"`` into the list so that n-gram
    extraction knows NOT to form n-grams across those positions.

    ``_color_name_tokens`` (the old set-based API) is preserved as a shim:

        def _color_name_tokens(...) -> set[str]:
            return set(_residual_tokens(...))
    """
    if tag_map is None:
        tag_map = DEFAULT_MATERIAL_TAG_IDS

    text = _norm(name)
    if not text:
        return []

    # Remove vendor tokens (whole-word)
    vendor_norm = _norm(vendor)
    for tok in vendor_norm.split():
        text = re.sub(r"\b" + re.escape(tok) + r"\b", " ", text)

    # Remove material tokens (base, finish-stripped)
    mat_norm = _norm(material)
    base_mat = _norm(strip_finish_words(mat_norm, tag_map) or mat_norm)
    for tok in base_mat.split():
        text = re.sub(r"\b" + re.escape(tok) + r"\b", " ", text)
    for tok in mat_norm.split():
        text = re.sub(r"\b" + re.escape(tok) + r"\b", " ", text)

    # Remove finish words (silk, matte, cf, etc.)
    for keyword in sorted(tag_map.keys(), key=len, reverse=True):
        text = re.sub(r"\b" + re.escape(keyword) + r"\b", " ", text, flags=re.IGNORECASE)

    # Replace ``&`` and ``/`` with a special sentinel string so we can split on
    # them later while preserving the information that a separator occurred here.
    text = re.sub(r"[&/]", " __SEP__ ", text)

    # Tokenize: split on any non-alphanumeric run except for the sentinel.
    # We first protect the sentinel, then split.
    raw = re.split(r"[^a-z0-9_]+", text.lower())

    # Drop empty tokens but keep ``__sep__``; also drop single-character tokens
    # (they are noise — "a", "x", etc.) unless they are the separator.
    # Also drop purely numeric tokens (e.g. "1000", "200") and tokens that
    # look like Shore-hardness codes (all digits + optional trailing letter,
    # e.g. "95a", "90a", "93a") — these are material-grade qualifiers, not
    # color or modifier names.  We use a simple heuristic: if the token is
    # entirely digits OR matches /^\d+[a-z]?$/, drop it.
    tokens: list[str] = []
    for tok in raw:
        if tok == "__sep__":
            tokens.append("__SEP__")
        elif len(tok) > 1:
            # Drop purely numeric tokens
            if tok.isdigit():
                continue
            # Drop Shore-hardness / numeric-grade codes: digits optionally
            # followed by a single letter (e.g. "95a", "93a", "60d").
            if re.match(r"^\d+[a-z]?$", tok):
                continue
            tokens.append(tok)

    return tokens


def _extract_ngrams(
    tokens: list[str],
    n: int,
) -> list[tuple[str, ...]]:
    """Extract all n-grams from ``tokens`` that do NOT cross a ``__SEP__`` sentinel.

    Returns a list of n-tuples of plain (non-sentinel) tokens.
    """
    result: list[tuple[str, ...]] = []
    for i in range(len(tokens) - n + 1):
        window = tokens[i : i + n]
        # Skip any window that contains a separator sentinel
        if "__SEP__" in window:
            continue
        result.append(tuple(window))
    return result


def _brands_for_ngram(
    ngram: tuple[str, ...],
    ngram_brand_map: dict[tuple[str, ...], set[str]],
) -> int:
    return len(ngram_brand_map.get(ngram, set()))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def mine_lexicons(
    materials: list[dict[str, Any]],
    tag_map: dict[str, int] | None = None,
) -> dict[str, list[str]]:
    """Mine a modifier and color lexicon from a list of OPTMaterial dicts.

    Parameters
    ----------
    materials:
        The list of OPTMaterial dicts as returned by ``load_opentag_dataset``.
    tag_map:
        Finish-keyword → tag-ID map.  Defaults to ``DEFAULT_MATERIAL_TAG_IDS``.

    Returns
    -------
    dict with keys:
        ``"modifiers"``: sorted list of modifier strings (longest-first then alpha).
        ``"colors"``:    sorted list of color strings (longest-first then alpha).

    The lists are deterministic given the same input (no random seed, no
    time-dependent ordering).
    """
    if tag_map is None:
        tag_map = DEFAULT_MATERIAL_TAG_IDS

    N = len(materials)  # total material count — used in lift calculation

    # ------------------------------------------------------------------
    # Step 1: compute residual token sequences per material
    # ------------------------------------------------------------------
    # We track both per-material token lists (for n-gram extraction) and
    # per-material brand (for brand-diversity counting).
    residuals: list[tuple[list[str], str]] = []  # (tokens, brand_slug_norm)
    for mat in materials:
        name = mat.get("name")
        vendor = mat.get("brandName")
        material = mat.get("type") or mat.get("abbreviation")
        brand_key = normalize_vendor(vendor)  # normalised for diversity counting
        toks = _residual_tokens(name, vendor, material, tag_map)
        residuals.append((toks, brand_key))

    # ------------------------------------------------------------------
    # Step 2: count unigrams, bigrams, trigrams (global counts + brand sets)
    # ------------------------------------------------------------------
    unigram_count: Counter[str] = Counter()
    unigram_brands: dict[str, set[str]] = {}

    bigram_count: Counter[tuple[str, str]] = Counter()
    bigram_brands: dict[tuple[str, str], set[str]] = {}

    trigram_count: Counter[tuple[str, str, str]] = Counter()
    trigram_brands: dict[tuple[str, str, str], set[str]] = {}

    for tokens, brand in residuals:
        seen_uni: set[str] = set()
        seen_bi: set[tuple[str, str]] = set()
        seen_tri: set[tuple[str, str, str]] = set()

        # Unigrams (non-separator tokens only)
        for tok in tokens:
            if tok == "__SEP__":
                continue
            unigram_count[tok] += 1
            if tok not in unigram_brands:
                unigram_brands[tok] = set()
            if tok not in seen_uni:
                unigram_brands[tok].add(brand)
                seen_uni.add(tok)

        # Bigrams
        for bg in _extract_ngrams(tokens, 2):
            t = (bg[0], bg[1])
            bigram_count[t] += 1
            if t not in bigram_brands:
                bigram_brands[t] = set()
            if t not in seen_bi:
                bigram_brands[t].add(brand)
                seen_bi.add(t)

        # Trigrams
        for tg in _extract_ngrams(tokens, 3):
            t = (tg[0], tg[1], tg[2])
            trigram_count[t] += 1
            if t not in trigram_brands:
                trigram_brands[t] = set()
            if t not in seen_tri:
                trigram_brands[t].add(brand)
                seen_tri.add(t)

    # ------------------------------------------------------------------
    # Step 3: select kept n-grams
    # ------------------------------------------------------------------
    # --- Trigrams: kept purely by count + brand diversity ---
    kept_trigrams: set[tuple[str, str, str]] = set()
    for tg, cnt in trigram_count.items():
        if cnt >= MODIFIER_MIN_COUNT and len(trigram_brands.get(tg, set())) >= MODIFIER_MIN_BRANDS:
            kept_trigrams.add(tg)

    # --- Bigrams: kept by count + brand diversity AND lift rule ---
    kept_bigrams: set[tuple[str, str]] = set()
    for bg, cnt in bigram_count.items():
        if cnt < MODIFIER_MIN_COUNT:
            continue
        if len(bigram_brands.get(bg, set())) < MODIFIER_MIN_BRANDS:
            continue
        # Bigram-lift rule: require that the bigram co-occurs far more often
        # than would be expected if the two tokens were independent.
        #   lift = freq(AB) / (freq(A) * freq(B) / N)
        fa = unigram_count.get(bg[0], 0)
        fb = unigram_count.get(bg[1], 0)
        if fa > 0 and fb > 0:
            expected = (fa * fb) / N
            lift = cnt / expected if expected > 0 else float("inf")
        else:
            lift = float("inf")  # can't compute — keep if passes count test
        if lift >= BIGRAM_LIFT_THRESHOLD:
            kept_bigrams.add(bg)

    # --- Unigrams: kept by count + brand diversity + not in STOP_WORDS ---
    kept_unigrams: set[str] = set()
    for tok, cnt in unigram_count.items():
        if tok in STOP_WORDS:
            continue
        if cnt >= MODIFIER_MIN_COUNT and len(unigram_brands.get(tok, set())) >= MODIFIER_MIN_BRANDS:
            kept_unigrams.add(tok)

    # ------------------------------------------------------------------
    # Step 4: subtract tokens covered by a longer kept n-gram
    # The idea: if "dual color" is kept as a bigram, suppress "dual" and
    # "color" from the unigram set (they become noise once the phrase is kept).
    # Similarly, if a trigram "a b c" is kept, suppress its sub-bigrams "a b"
    # and "b c" from the bigram set, and "a", "b", "c" from unigrams.
    # ------------------------------------------------------------------
    covered_unigrams: set[str] = set()
    covered_bigrams: set[tuple[str, str]] = set()

    for tg in kept_trigrams:
        # Trigram covers its two sub-bigrams and all three unigrams
        covered_bigrams.add((tg[0], tg[1]))
        covered_bigrams.add((tg[1], tg[2]))
        covered_unigrams.update(tg)

    for bg in kept_bigrams:
        # Bigram covers both component unigrams
        covered_unigrams.update(bg)

    # Apply coverage suppression
    kept_bigrams -= covered_bigrams
    kept_unigrams -= covered_unigrams

    # ------------------------------------------------------------------
    # Step 5: split into modifier candidates vs color candidates
    # Tokens that are in BASE_COLORS seed are filed under colors; everything
    # else is a modifier candidate.
    # ------------------------------------------------------------------
    mined_modifiers: set[str] = set()
    mined_colors: set[str] = set()

    # Unigrams
    for tok in kept_unigrams:
        if tok in BASE_COLORS:
            mined_colors.add(tok)
        else:
            mined_modifiers.add(tok)

    # Bigrams → always modifiers (multi-word phrases are never base colors)
    for bg in kept_bigrams:
        mined_modifiers.add(" ".join(bg))

    # Trigrams → always modifiers
    for tg in kept_trigrams:
        mined_modifiers.add(" ".join(tg))

    # ------------------------------------------------------------------
    # Step 6: color mining — apply stricter thresholds to the unigram color set
    # and optionally promote new color names not already in BASE_COLORS.
    # New colors are those unigrams that:
    #   (a) are NOT in BASE_COLORS (those are already included automatically)
    #   (b) are NOT already claimed as modifiers
    #   (c) pass COLOR_MIN_COUNT and COLOR_MIN_BRANDS (stricter thresholds)
    #
    # This gives us marketing color names that appear consistently across
    # multiple brands and many materials — genuine color identity words like
    # "cobalt", "jade", "turquoise", etc.
    # ------------------------------------------------------------------
    # Recompute color candidates from ALL unigrams that pass the color thresholds
    # (not just those left after coverage subtraction — coverage subtraction is
    # for modifiers only; color names stay atomic).
    additional_colors: set[str] = set()
    for tok, cnt in unigram_count.items():
        if tok in BASE_COLORS:
            continue  # already seeded
        if tok in STOP_WORDS:
            continue  # stop words never become colors
        if tok in mined_modifiers:
            continue  # already claimed as a modifier
        if tok in MODIFIER_SEED:
            continue  # modifier seed takes priority
        if cnt >= COLOR_MIN_COUNT and len(unigram_brands.get(tok, set())) >= COLOR_MIN_BRANDS:
            additional_colors.add(tok)

    mined_colors.update(additional_colors)

    # ------------------------------------------------------------------
    # Step 7: seed merge — unconditionally add MODIFIER_SEED
    # Also remove:
    #   (a) any STOP_WORDS that leaked into mined_modifiers or MODIFIER_SEED
    #   (b) any BASE_COLORS tokens — colors must never appear in the modifier set
    #       (e.g. "army", "electric", "grass" are color names, not modifiers;
    #       they only ended up in MODIFIER_SEED by mistake or because they appeared
    #       in fewer brands than COLOR_MIN_BRANDS before the extended color seed was added).
    # ------------------------------------------------------------------
    all_modifiers = (mined_modifiers | MODIFIER_SEED) - STOP_WORDS - BASE_COLORS

    # Add BASE_COLORS to the color lexicon (they are always valid)
    all_colors = mined_colors | BASE_COLORS

    # ------------------------------------------------------------------
    # Step 8: deterministic sort — longest-first, then alphabetical
    # ------------------------------------------------------------------
    def _sort_key(s: str) -> tuple[int, str]:
        return (-len(s.split()), s)

    sorted_modifiers = sorted(all_modifiers, key=_sort_key)
    sorted_colors = sorted(all_colors, key=_sort_key)

    return {"modifiers": sorted_modifiers, "colors": sorted_colors}


def mine_lexicons_with_counts(
    materials: list[dict[str, Any]],
    tag_map: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Mine lexicons AND return frequency counts for the dump/review script.

    Returns a dict::

        {
            "modifiers": [...],
            "colors":    [...],
            "modifier_counts": {phrase: count, ...},
            "color_counts":    {token: count, ...},
        }

    Counts for multi-word modifiers are the n-gram occurrence count.
    Seed-only items that weren't mined have count 0.
    BASE_COLORS always-included items also have count 0 in the count dict
    (they are guaranteed by the seed, not by mining).
    """
    if tag_map is None:
        tag_map = DEFAULT_MATERIAL_TAG_IDS

    N = len(materials)

    # Rebuild residuals (same as mine_lexicons)
    residuals: list[tuple[list[str], str]] = []
    for mat in materials:
        name = mat.get("name")
        vendor = mat.get("brandName")
        material = mat.get("type") or mat.get("abbreviation")
        brand_key = normalize_vendor(vendor)
        toks = _residual_tokens(name, vendor, material, tag_map)
        residuals.append((toks, brand_key))

    # Count everything
    unigram_count: Counter[str] = Counter()
    unigram_brands: dict[str, set[str]] = {}
    bigram_count: Counter[tuple[str, str]] = Counter()
    bigram_brands: dict[tuple[str, str], set[str]] = {}
    trigram_count: Counter[tuple[str, str, str]] = Counter()
    trigram_brands: dict[tuple[str, str, str], set[str]] = {}

    for tokens, brand in residuals:
        seen_uni: set[str] = set()
        seen_bi: set[tuple[str, str]] = set()
        seen_tri: set[tuple[str, str, str]] = set()

        for tok in tokens:
            if tok == "__SEP__":
                continue
            unigram_count[tok] += 1
            if tok not in unigram_brands:
                unigram_brands[tok] = set()
            if tok not in seen_uni:
                unigram_brands[tok].add(brand)
                seen_uni.add(tok)

        for bg in _extract_ngrams(tokens, 2):
            t = (bg[0], bg[1])
            bigram_count[t] += 1
            if t not in bigram_brands:
                bigram_brands[t] = set()
            if t not in seen_bi:
                bigram_brands[t].add(brand)
                seen_bi.add(t)

        for tg in _extract_ngrams(tokens, 3):
            t = (tg[0], tg[1], tg[2])
            trigram_count[t] += 1
            if t not in trigram_brands:
                trigram_brands[t] = set()
            if t not in seen_tri:
                trigram_brands[t].add(brand)
                seen_tri.add(t)

    # Select kept n-grams (identical logic to mine_lexicons)
    kept_trigrams: set[tuple[str, str, str]] = set()
    for tg, cnt in trigram_count.items():
        if cnt >= MODIFIER_MIN_COUNT and len(trigram_brands.get(tg, set())) >= MODIFIER_MIN_BRANDS:
            kept_trigrams.add(tg)

    kept_bigrams: set[tuple[str, str]] = set()
    for bg, cnt in bigram_count.items():
        if cnt < MODIFIER_MIN_COUNT:
            continue
        if len(bigram_brands.get(bg, set())) < MODIFIER_MIN_BRANDS:
            continue
        fa = unigram_count.get(bg[0], 0)
        fb = unigram_count.get(bg[1], 0)
        if fa > 0 and fb > 0:
            expected = (fa * fb) / N
            lift = cnt / expected if expected > 0 else float("inf")
        else:
            lift = float("inf")
        if lift >= BIGRAM_LIFT_THRESHOLD:
            kept_bigrams.add(bg)

    kept_unigrams: set[str] = set()
    for tok, cnt in unigram_count.items():
        if tok in STOP_WORDS:
            continue
        if cnt >= MODIFIER_MIN_COUNT and len(unigram_brands.get(tok, set())) >= MODIFIER_MIN_BRANDS:
            kept_unigrams.add(tok)

    # Coverage subtraction
    covered_unigrams: set[str] = set()
    covered_bigrams: set[tuple[str, str]] = set()
    for tg in kept_trigrams:
        covered_bigrams.add((tg[0], tg[1]))
        covered_bigrams.add((tg[1], tg[2]))
        covered_unigrams.update(tg)
    for bg in kept_bigrams:
        covered_unigrams.update(bg)
    kept_bigrams -= covered_bigrams
    kept_unigrams -= covered_unigrams

    # Split modifiers vs colors
    mined_modifiers: set[str] = set()
    mined_colors: set[str] = set()
    for tok in kept_unigrams:
        if tok in BASE_COLORS:
            mined_colors.add(tok)
        else:
            mined_modifiers.add(tok)
    for bg in kept_bigrams:
        mined_modifiers.add(" ".join(bg))
    for tg in kept_trigrams:
        mined_modifiers.add(" ".join(tg))

    # Additional color mining
    for tok, cnt in unigram_count.items():
        if tok in BASE_COLORS:
            continue
        if tok in STOP_WORDS:
            continue
        if tok in mined_modifiers:
            continue
        if tok in MODIFIER_SEED:
            continue
        if cnt >= COLOR_MIN_COUNT and len(unigram_brands.get(tok, set())) >= COLOR_MIN_BRANDS:
            mined_colors.add(tok)

    all_modifiers = (mined_modifiers | MODIFIER_SEED) - STOP_WORDS - BASE_COLORS
    all_colors = mined_colors | BASE_COLORS

    def _sort_key(s: str) -> tuple[int, str]:
        return (-len(s.split()), s)

    sorted_modifiers = sorted(all_modifiers, key=_sort_key)
    sorted_colors = sorted(all_colors, key=_sort_key)

    # Build count dicts — look up the raw n-gram frequency for each phrase
    modifier_counts: dict[str, int] = {}
    for phrase in sorted_modifiers:
        words = tuple(phrase.split())
        if len(words) == 1:
            modifier_counts[phrase] = unigram_count.get(phrase, 0)
        elif len(words) == 2:
            modifier_counts[phrase] = bigram_count.get(words, 0)  # type: ignore[arg-type]
        elif len(words) == 3:
            modifier_counts[phrase] = trigram_count.get(words, 0)  # type: ignore[arg-type]
        else:
            modifier_counts[phrase] = 0

    color_counts: dict[str, int] = {}
    for color in sorted_colors:
        color_counts[color] = unigram_count.get(color, 0)

    return {
        "modifiers": sorted_modifiers,
        "colors": sorted_colors,
        "modifier_counts": modifier_counts,
        "color_counts": color_counts,
        # Extra debug info
        "_bigram_lift_examples": {
            " ".join(bg): {
                "count": bigram_count[bg],
                "fa": unigram_count.get(bg[0], 0),
                "fb": unigram_count.get(bg[1], 0),
                "expected": round((unigram_count.get(bg[0], 0) * unigram_count.get(bg[1], 0)) / N, 2) if N else 0,
                "lift": round(bigram_count[bg] / max(1e-9, (unigram_count.get(bg[0], 0) * unigram_count.get(bg[1], 0)) / N), 1) if N else 0,
            }
            for bg in list(kept_bigrams)[:30]  # sample
        },
    }
