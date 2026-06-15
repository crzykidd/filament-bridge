"""OpenTag → Spoolman matcher — pure, no I/O.

v2 scorer (2026-06-11): structured token decomposition + mined lexicons.

Scores OPTMaterial candidates against a SpoolmanFilament by:
  1. Material/type match (normalised, finish-stripped)              × 0.15
  2. Vendor/brand name match                                        × 0.15
  3. Color multiset similarity (order-independent, count-aware)     × 0.40
  4. Modifier set Jaccard                                           × 0.15
  5. Finish tag overlap                                             ±0.10
  6. Color hex proximity                                            × 0.05
  7. Full-string similarity tie-breaker                             +0.05 max

Returns best match + confidence + alternates list.

Backward-compat shims retained
--------------------------------
``_color_name_tokens``, ``_name_similarity``, ``_base_color`` are kept as shims
for existing tests.  The new code path uses ``decompose_name`` + ``score_candidate``.

``score_candidate`` / ``find_best_match`` gain an optional ``lexicon=`` kwarg.
When ``None`` the scorer falls back to the seed-only ``BASE_COLORS``/``MODIFIER_SEED``
lexicons from ``opentag_lexicon`` (no network call needed).
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from typing import Any, NamedTuple

from app.core.color import TAG_COEXTRUDED, TAG_GRADIENT, arrangement_from_tags
from app.core.material_tags import DEFAULT_MATERIAL_TAG_IDS, finish_ids_from_text, serialize_material_tags, strip_finish_words
from app.core.matcher import normalize_vendor
from app.schemas.spoolman import SpoolmanFilament


# ---------------------------------------------------------------------------
# COLOR_SYNONYMS — true synonym reduction only (v2)
#
# LOCKED DECISION (2026-06-11 plan): drop all conflating base-color collapses
# (silver→grey, galaxy→black, cool→grey, etc.).  Reduce to ONLY genuine
# linguistic equivalences.  Marketing names and distinct shades are NOT collapsed.
#
# Only true linguistic equivalences belong here; marketing names and distinct
# shades are NOT collapsed.
# ---------------------------------------------------------------------------

#: True synonym map applied to both sides before multiset comparison.
#: Keep short — only add entries where two words are genuinely interchangeable
#: (e.g. "gray" == "grey", "violet" == "purple").
DEFAULT_COLOR_KEYWORDS: dict[str, str] = {
    # Spelling variants (genuine synonyms)
    "gray":        "grey",
    "violet":      "purple",
    "magenta":     "pink",
    "transparent": "clear",
    "navy":        "blue",
    # Legacy: keep "prusa" → empty so the brand-name token doesn't score as a color
    "prusa":       "",
}

#: Alias: ``COLOR_SYNONYMS`` is the canonical name; ``DEFAULT_COLOR_KEYWORDS``
#: is retained for import-compat with ``api/opentag.py``.
COLOR_SYNONYMS = DEFAULT_COLOR_KEYWORDS


# ---------------------------------------------------------------------------
# ParsedName — structured token bag produced by ``decompose_name``
# ---------------------------------------------------------------------------

class ParsedName(NamedTuple):
    """Structured decomposition of a filament name.

    Fields
    ------
    material_family:
        Normalised polymer family (``"pla"``, ``"petg"``, ``"tpu"``, …) or ``""``
        when not identifiable.
    finish_ids:
        Set of integer finish-tag IDs detected in the name (silk, matte, cf, …).
    modifiers:
        Frozenset of modifier tokens/phrases (``"shiny"``, ``"gradient"``,
        ``"dual color"``, …) present in the residual after brand/material/finish
        removal.
    colors:
        Counter (multiset) of color tokens.  Synonym-reduced via ``COLOR_SYNONYMS``
        **before** building the Counter so that "gray" and "grey" always compare equal.
    """
    material_family: str
    finish_ids: frozenset[int]
    modifiers: frozenset[str]
    colors: Counter  # str → int


# ---------------------------------------------------------------------------
# Lexicon helpers — build match dicts from the mined lexicon
# ---------------------------------------------------------------------------

def build_ngram_index(lexicon: dict[str, list[str]] | None) -> dict[int, set[str]]:
    """Return ``{1: set_of_unigrams, 2: set_of_bigrams, 3: set_of_trigrams}``
    keyed by n-gram length (word count).

    When ``lexicon`` is None, falls back to ``MODIFIER_SEED`` + ``BASE_COLORS``
    from ``opentag_lexicon``.
    """
    from app.core.opentag_lexicon import BASE_COLORS, COMPOSITE_DESCRIPTOR_SEED, MODIFIER_SEED
    if lexicon is None:
        modifier_list: list[str] = list(MODIFIER_SEED | COMPOSITE_DESCRIPTOR_SEED)
        color_list: list[str] = list(BASE_COLORS)
    else:
        modifier_list = lexicon.get("modifiers", [])
        color_list = lexicon.get("colors", [])

    all_terms = list(modifier_list) + list(color_list)
    index: dict[int, set[str]] = {1: set(), 2: set(), 3: set()}
    for term in all_terms:
        n = len(term.split())
        if 1 <= n <= 3:
            index[n].add(term)
    return index


# ---------------------------------------------------------------------------
# decompose_name — pure, both sides identical
# ---------------------------------------------------------------------------

def _norm(s: str | None) -> str:
    if not s:
        return ""
    return unicodedata.normalize("NFKC", s).lower().strip()


def _residual_token_list(
    name: str | None,
    vendor: str | None,
    material: str | None,
    tag_map: dict[str, int] | None = None,
) -> list[str]:
    """Return an ordered list of residual lowercase tokens from a material name,
    with vendor, material, and finish words removed.  Separator positions
    (``&``, ``/``) are preserved as ``"__SEP__"`` sentinels.

    This is the shared residual-token step used by both ``decompose_name`` and
    (via a set-shim) the legacy ``_color_name_tokens`` helper.
    """
    from app.core.opentag_lexicon import _residual_tokens as _lex_residual
    return _lex_residual(name, vendor, material, tag_map)


def decompose_name(
    name: str | None,
    vendor: str | None,
    material: str | None,
    tag_map: dict[str, int] | None = None,
    ngram_index: dict[int, set[str]] | None = None,
    color_synonyms: dict[str, str] | None = None,
) -> ParsedName:
    """Decompose a filament name into a structured ``ParsedName`` token bag.

    Algorithm
    ---------
    1. ``material_family()`` on the material field.
    2. ``finish_ids_from_text()`` on name + material.
    3. ``_residual_token_list()`` → ordered residual tokens (brand/mat/finish removed).
    4. Slide a longest-first n-gram window (tri → bi → uni) over the residual to
       classify tokens into ``modifiers`` vs ``colors``:
       - n-gram found in the modifier lexicon → modifier.
       - unigram found in the color lexicon → color.
       - unigram not found in either → silently discarded (generic noise).
       Consumed token positions are not reused.
    5. Color synonyms are applied (via ``color_synonyms``) to the color Counter
       so that "gray" and "grey" score identically.

    N-grams do NOT cross ``__SEP__`` sentinels (``&`` / ``/`` boundaries).

    Parameters
    ----------
    ngram_index:
        Pre-built ``{1: set, 2: set, 3: set}`` of known modifier/color terms.
        When None, built from seed lists (no mined lexicon).
    color_synonyms:
        Synonym reduction map (``{"gray": "grey", ...}``).  Defaults to
        ``COLOR_SYNONYMS``.
    """
    if tag_map is None:
        tag_map = DEFAULT_MATERIAL_TAG_IDS
    if color_synonyms is None:
        color_synonyms = COLOR_SYNONYMS

    # Build ngram index lazily when not pre-built
    if ngram_index is None:
        ngram_index = build_ngram_index(None)

    mat_fam = material_family(material, tag_map)
    finish_ids = frozenset(finish_ids_from_text(name or "", material or "", tag_map))

    tokens = _residual_token_list(name, vendor, material, tag_map)

    # Build color set for quick unigram lookup
    modifier_set_2: set[str] = ngram_index.get(2, set())
    modifier_set_3: set[str] = ngram_index.get(3, set())

    # Determine which unigrams are colors vs modifiers from the lexicon
    from app.core.opentag_lexicon import BASE_COLORS
    color_unigrams: set[str] = set()
    modifier_unigrams: set[str] = set()
    for term in ngram_index.get(1, set()):
        if term in BASE_COLORS:
            color_unigrams.add(term)
        else:
            modifier_unigrams.add(term)
    # Also treat any additional color lexicon entries as colors
    if "colors" in _get_raw_lexicon_ref(ngram_index):
        pass  # already handled via BASE_COLORS above

    mods: set[str] = set()
    cols: Counter = Counter()

    i = 0
    n_tok = len(tokens)
    while i < n_tok:
        if tokens[i] == "__SEP__":
            i += 1
            continue

        # Try trigram first (no sep in window)
        if i + 2 < n_tok:
            w3 = tokens[i: i + 3]
            if "__SEP__" not in w3:
                phrase3 = " ".join(w3)
                if phrase3 in modifier_set_3:
                    mods.add(phrase3)
                    i += 3
                    continue

        # Try bigram
        if i + 1 < n_tok:
            w2 = tokens[i: i + 2]
            if "__SEP__" not in w2:
                phrase2 = " ".join(w2)
                if phrase2 in modifier_set_2:
                    mods.add(phrase2)
                    i += 2
                    continue

        # Unigram
        tok = tokens[i]
        if tok in color_unigrams:
            # Apply synonym reduction before inserting into counter
            canonical = color_synonyms.get(tok, tok)
            if canonical:  # skip empty-mapped tokens (e.g. "prusa" → "")
                cols[canonical] += 1
        elif tok in modifier_unigrams:
            mods.add(tok)
        elif len(tok) >= 6 and tok.endswith("fill"):
            # Catch novel *fill composite-descriptor tokens not yet in the lexicon
            # (e.g. "rockfill", "glassfill") — treat as a modifier so they score
            # against OPT entries that carry the same token.
            mods.add(tok)
        # else: discard — generic noise not in lexicon

        i += 1

    return ParsedName(
        material_family=mat_fam,
        finish_ids=finish_ids,
        modifiers=frozenset(mods),
        colors=cols,
    )


def _get_color_set(ngram_index: dict[int, set[str]]) -> set[str]:
    """Return the set of color unigrams from the ngram index.

    The ngram_index built by ``build_ngram_index`` merges both modifiers and
    colors into the same n sets.  We recover the color subset by intersecting
    with ``BASE_COLORS``.
    """
    from app.core.opentag_lexicon import BASE_COLORS
    return ngram_index.get(1, set()) & BASE_COLORS


def _get_raw_lexicon_ref(ngram_index: dict[int, set[str]]) -> dict:
    """Thin helper to avoid circular logic — returns an empty dict here."""
    return {}


# ---------------------------------------------------------------------------
# Color-words map helpers (backward-compat shims)
# ---------------------------------------------------------------------------

# Modifier words that prefix a color token but should not block a base-color match.
# These are stripped from color names before base-color lookup.
_COLOR_MODIFIERS: frozenset[str] = frozenset({
    "light", "lite", "dark", "deep", "pastel", "bright",
    "pale", "vivid", "neon", "matte", "glossy",
})


def _base_color(tokens: set[str], color_map: dict[str, str]) -> str:
    """Reduce a set of color tokens to a single canonical base color string.

    Shim retained for backward-compat with existing tests that call this directly.
    The v2 scorer uses ``decompose_name`` → color ``Counter`` instead.
    """
    for tok in tokens:
        if tok in _COLOR_MODIFIERS:
            continue
        base = color_map.get(tok)
        if base:
            return base
    return ""


# ---------------------------------------------------------------------------
# Color-profile helpers — pure, no I/O
# ---------------------------------------------------------------------------

# Profile literals: single | coextruded | gradient | multi_unknown
_PROFILE_SINGLE = "single"
_PROFILE_COEXTRUDED = "coextruded"
_PROFILE_GRADIENT = "gradient"
_PROFILE_MULTI_UNKNOWN = "multi_unknown"


def sm_color_profile(sm: SpoolmanFilament) -> str:
    """Return the color profile of a Spoolman filament.

    ``single``         — no ``multi_color_hexes``
    ``coextruded``     — ``multi_color_direction == "coaxial"``
    ``gradient``       — ``multi_color_direction == "longitudinal"``
    ``multi_unknown``  — ``multi_color_hexes`` present but direction unknown/absent
    """
    if not sm.multi_color_hexes:
        return _PROFILE_SINGLE
    direction = sm.multi_color_direction
    if direction == "coaxial":
        return _PROFILE_COEXTRUDED
    if direction == "longitudinal":
        return _PROFILE_GRADIENT
    return _PROFILE_MULTI_UNKNOWN


def opt_color_profile(opt: dict[str, Any], tag_map: dict[str, int] | None = None) -> str:
    """Return the color profile of an OPTMaterial dict.

    ``single``         — no arrangement tag AND no ``secondaryColors``
    ``coextruded``     — tag string "coextruded" OR optTag 29 present
    ``gradient``       — tag string "gradual_color_change"/"gradient" OR optTag 28 present
    ``multi_unknown``  — ``secondaryColors`` present but no arrangement tag

    IMPORTANT: FDB's denormalized OpenTag feed leaves ``secondaryColors`` EMPTY on all
    records.  Arrangement is only signalled via the string ``tags`` array (e.g. "coextruded",
    "gradual_color_change").  Therefore we derive arrangement from tags FIRST; we only fall
    back to ``secondaryColors`` for the ``multi_unknown`` case when tags are absent.
    """
    # Build integer opt-tags list from the optTags field (integer tag IDs)
    opt_tags_int: list[int] = []
    for t in opt.get("optTags") or []:
        try:
            opt_tags_int.append(int(t))
        except (TypeError, ValueError):
            pass

    # Scan string tags for arrangement words (coextruded / gradual_color_change / gradient).
    # This is the primary signal in FDB's denormalized feed where secondaryColors is always [].
    tag_strings: list[str] = [s.lower().strip() for s in (opt.get("tags") or []) if isinstance(s, str)]
    if "coextruded" in tag_strings:
        opt_tags_int.append(TAG_COEXTRUDED)
    if "gradual_color_change" in tag_strings or "gradient" in tag_strings:
        opt_tags_int.append(TAG_GRADIENT)

    # If any arrangement tag is present, classify by it regardless of secondaryColors.
    arrangement = arrangement_from_tags(opt_tags_int)
    if arrangement == "coextruded":
        return _PROFILE_COEXTRUDED
    if arrangement == "gradient":
        return _PROFILE_GRADIENT

    # No arrangement tag — fall back to secondaryColors to distinguish single vs multi_unknown.
    # An entry with fewer than 2 distinct secondaryColors is treated as single-color even if
    # the secondaryColors list is non-empty (e.g. thermochromic / one-color OPT entries).
    secondary: list = opt.get("secondaryColors") or []
    if len(secondary) >= 2:
        return _PROFILE_MULTI_UNKNOWN
    return _PROFILE_SINGLE


def profiles_compatible(a: str, b: str) -> bool:
    """Return True when profile ``a`` (SM side) and ``b`` (OPT side) are compatible.

    Rules:
    - ``single`` matches only ``single``
    - ``coextruded`` matches only ``coextruded``
    - ``gradient`` matches only ``gradient``
    - ``multi_unknown`` (either side) matches any multicolor profile, never ``single``
    """
    if a == _PROFILE_SINGLE and b == _PROFILE_SINGLE:
        return True
    if a == _PROFILE_SINGLE or b == _PROFILE_SINGLE:
        return False  # single never matches any multicolor profile
    # Both sides are multicolor — exact or lenient (multi_unknown) match
    if a == b:
        return True
    if a == _PROFILE_MULTI_UNKNOWN or b == _PROFILE_MULTI_UNKNOWN:
        return True  # lenient: multi_unknown matches any multicolor
    return False


# ---------------------------------------------------------------------------
# Field mapping: OPTMaterial → Spoolman native fields
# ---------------------------------------------------------------------------


def opt_to_spoolman_fields(
    opt: dict[str, Any],
    tag_map: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Map an OPTMaterial dict to a Spoolman filament update payload.

    Returns a dict containing ONLY the fields that have non-None values in the
    OPTMaterial — callers may further filter by user "keep mine" choices.

    Field mapping:
    - type (base, finish-stripped) → material
    - tags (finish strings) → extra.filamentdb_material_tags (JSON list of IDs)
    - color + secondaryColors + arrangement → color_hex, multi_color_hexes,
      multi_color_direction  (reuses fdb_multicolor_to_sm for consistency;
      empty primary color is handled automatically)
    - density → density
    - 1.75 → diameter (always)
    - nozzleTempMax → settings_extruder_temp
    - bedTempMax → settings_bed_temp
    - slug → extra.openprinttag_slug
    - uuid → extra.openprinttag_uuid
    """
    if tag_map is None:
        tag_map = DEFAULT_MATERIAL_TAG_IDS

    result: dict[str, Any] = {}

    # Material (base, finish-stripped)
    raw_type = opt.get("type") or opt.get("abbreviation") or ""
    base_type = strip_finish_words(raw_type, tag_map) or raw_type
    if base_type:
        result["material"] = base_type

    # Finish tags from OPT tags array (strings like "silk", "matte", etc.)
    opt_tags_raw: list[str] = opt.get("tags") or []
    finish_ids: set[int] = set()
    for tag_str in opt_tags_raw:
        ids = finish_ids_from_text(tag_str, None, tag_map)
        finish_ids.update(ids)
    # Also scan name/type for finish hints
    finish_ids.update(finish_ids_from_text(opt.get("name", ""), raw_type, tag_map))
    result["extra.filamentdb_material_tags"] = serialize_material_tags(finish_ids)

    # Color — reuse fdb_multicolor_to_sm for consistency (handles empty primary,
    # arrangement, and single-color cases uniformly).
    opt_color = opt.get("color") or None  # treat empty string as None
    secondary: list[str] = opt.get("secondaryColors") or []

    # Build integer optTags for arrangement detection (same logic as opt_color_profile)
    opt_tags_int: list[int] = []
    for t in opt.get("optTags") or []:
        try:
            opt_tags_int.append(int(t))
        except (TypeError, ValueError):
            pass
    tag_strings_lower: list[str] = [s.lower().strip() for s in opt_tags_raw if isinstance(s, str)]
    if "coextruded" in tag_strings_lower:
        opt_tags_int.append(TAG_COEXTRUDED)
    if "gradual_color_change" in tag_strings_lower or "gradient" in tag_strings_lower:
        opt_tags_int.append(TAG_GRADIENT)

    arrangement = arrangement_from_tags(opt_tags_int)
    has_arrangement = arrangement in ("coextruded", "gradient")

    # Build the de-duplicated, order-preserving hex list: primary first, then secondaries.
    # Normalise to bare uppercase hex (no leading '#'); skip empty/falsy values.
    _seen: set[str] = set()
    all_hexes: list[str] = []
    for raw in ([opt_color] if opt_color else []) + list(secondary):
        h = raw.lstrip("#").upper() if raw else ""
        if h and h not in _seen:
            _seen.add(h)
            all_hexes.append(h)

    # Count-based color rule — Spoolman rejects a lone-hex multi_color_hexes (422).
    #
    # len >= 2 → multicolor: put all hexes in multi_color_hexes; ALWAYS set
    #            multi_color_direction (Spoolman 422s if multi_color_hexes is set without it):
    #              coextruded arrangement → "coaxial"
    #              gradient arrangement  → "longitudinal"
    #              no/unknown arrangement (multi_unknown) → "coaxial" (safe default; Spoolman
    #                only requires *a* direction — coaxial is used for thermochromic and other
    #                unclassified multicolor entries where spatial arrangement is unknown).
    #            NEVER set color_hex alongside multi_color_hexes (Spoolman 422s on both).
    # len == 1 and no arrangement tag → single-color: write color_hex only.
    # len == 1 and arrangement tag → partial multicolor data; emit NO color fields so we
    #            don't overwrite Spoolman's existing multi_color_hexes with a lone color_hex.
    # len == 0 → no color info; emit NO color fields (preserves the existing
    #            "arrangement tag but empty secondaryColors → leave Spoolman's multicolor
    #            alone" behaviour for the denormalized FDB feed path).
    if len(all_hexes) >= 2:
        result["multi_color_hexes"] = ",".join(all_hexes)
        # Always set multi_color_direction — Spoolman requires it whenever multi_color_hexes
        # is present.  Default to "coaxial" for unknown/no arrangement (multi_unknown).
        if arrangement == "gradient":
            result["multi_color_direction"] = "longitudinal"
        else:
            # coextruded → coaxial; no/unknown arrangement → coaxial (safe default)
            result["multi_color_direction"] = "coaxial"
        # color_hex intentionally NOT set — Spoolman rejects both fields together (422).
    elif len(all_hexes) == 1 and not has_arrangement:
        # Single distinct color, no arrangement tag → straightforward single-color write.
        # This is the thermochromic / one-secondary case (e.g. SM #21).
        result["color_hex"] = all_hexes[0]
    elif len(all_hexes) == 1 and has_arrangement:
        # Only one hex but the entry claims to be multicolor (arrangement tag present).
        # We lack the full hex set — emit no color fields to avoid overwriting Spoolman's
        # existing multi_color_hexes with a lone color_hex (which Spoolman would reject
        # when multi_color_hexes is already set, or would lose the multicolor data entirely).
        pass
    # else len == 0: no color info — emit nothing; Spoolman's existing values are preserved.

    # Density
    density = opt.get("density")
    if density is not None:
        result["density"] = float(density)

    # Diameter (always 1.75)
    result["diameter"] = 1.75

    # Temperatures — use max values as single-point defaults
    nozzle_max = opt.get("nozzleTempMax")
    if nozzle_max is not None:
        result["settings_extruder_temp"] = int(nozzle_max)

    bed_max = opt.get("bedTempMax")
    if bed_max is not None:
        result["settings_bed_temp"] = int(bed_max)

    # Name — reviewable field; defaults to OpenTag name
    opt_name = opt.get("name")
    if opt_name is not None:
        result["name"] = opt_name

    # Vendor/brand — reviewable field; the OpenTag brand name.
    # Callers (_build_field_rows in opentag.py) only include this row when the
    # Spoolman vendor name differs from the OpenTag brand (normalized comparison).
    # _build_sm_patch extracts it separately (vendor is a relation, not a scalar).
    opt_brand = opt.get("brandName")
    if opt_brand is not None:
        result["vendor"] = opt_brand

    # Identity fields → extra
    slug = opt.get("slug")
    if slug:
        result["extra.openprinttag_slug"] = slug

    uuid_val = opt.get("uuid")
    if uuid_val:
        result["extra.openprinttag_uuid"] = uuid_val

    return result


# ---------------------------------------------------------------------------
# Polymer-family normalisation
# ---------------------------------------------------------------------------

# Finish words that must be stripped before identifying the base polymer family.
# (We reuse ``strip_finish_words`` which covers silk, matte, cf, etc.)

#: Map of base-material token → polymer-family string.
_FAMILY_MAP: dict[str, str] = {
    "pla+":  "pla",
    "pla":   "pla",
    "petg":  "petg",
    "asa":   "asa",
    "abs":   "abs",
    "pc":    "pc",
    "tpu":   "tpu",
    "tpe":   "tpu",
    "pa":    "pa",
    "nylon": "pa",
    "pva":   "pva",
}

# Prefixes that inherit the same family (e.g. "pa-cf" → "pa", "pa6" → "pa").
_FAMILY_PREFIX_ORDER: list[tuple[str, str]] = [
    ("pla+", "pla"),
    ("pla",  "pla"),
    ("petg", "petg"),
    ("asa",  "asa"),
    ("abs",  "abs"),
    ("tpe",  "tpu"),
    ("tpu",  "tpu"),
    # PA / Nylon and all variants (PA-CF, PA6, PA12, etc.)
    ("pa",   "pa"),
    ("nylon", "pa"),
    ("pc",   "pc"),
    ("pva",  "pva"),
]


def material_family(material: str | None, tag_map: dict[str, int] | None = None) -> str:
    """Normalise ``material`` to a base polymer family string.

    Strips finish words first (so "PLA Silk" → "pla"), then matches against the
    family map / prefix list.  Returns the lower-cased stripped token when the
    material is unknown, so callers can still use it as an opaque key.  Returns
    ``""`` when ``material`` is empty / None.

    Examples::

        material_family("PLA")       → "pla"
        material_family("PLA+")      → "pla"
        material_family("PLA Silk")  → "pla"
        material_family("PETG")      → "petg"
        material_family("PETG-CF")   → "petg"
        material_family("ASA")       → "asa"
        material_family("PC")        → "pc"
        material_family("TPU")       → "tpu"
        material_family("PA-CF")     → "pa"
        material_family("Nylon")     → "pa"
        material_family("ABS+")      → "abs"
    """
    if not material:
        return ""
    # Strip finish modifiers first (silk, matte, cf, etc.)
    stripped = strip_finish_words(material, tag_map).strip().lower()
    if not stripped:
        stripped = material.strip().lower()

    # Exact lookup first.
    if stripped in _FAMILY_MAP:
        return _FAMILY_MAP[stripped]

    # Prefix lookup handles compound tokens like "petg-cf", "pa6", "pa-cf", "abs+".
    # Sort by prefix length descending so longer prefixes win (e.g. "pla+" before "pla").
    for prefix, family in _FAMILY_PREFIX_ORDER:
        if stripped.startswith(prefix) and (
            len(stripped) == len(prefix)
            or not stripped[len(prefix)].isalpha()  # separator / digit follows prefix
        ):
            return family

    # Unknown material → return as-is (normalised), so the gate is a no-op.
    return stripped


# ---------------------------------------------------------------------------
# Polymer-family gate helpers (v2.1)
# ---------------------------------------------------------------------------

#: PLA-biopolymer compatibility bucket (user-confirmed 2026-06-11).
#:
#: These polymer families are gate-compatible with each other because:
#: - PHA is a biopolymer that is often blended with PLA (e.g. ColorFabb composites
#:   labelled "PHA" or "PLA/PHA" by the brand are physically the same family).
#: - LW-PLA, HTPLA, rPLA are all PLA variants/grades.
#: - The OpenPrintTag dataset inconsistently types some PLA composites as PHA.
#:
#: Everything else (ABS, ASA, PETG, PC, PA/nylon, TPU, etc.) stays strictly
#: separate — the bucket only relaxes within the PLA biopolymer family.
#:
#: Bucket strings are exactly what ``material_family()`` emits for these inputs:
#:   "PHA"     → "pha"     (unknown → stripped, returned as-is)
#:   "LW-PLA"  → "lw-pla" (unknown → stripped, returned as-is)
#:   "HTPLA"   → "htpla"  (unknown → stripped, returned as-is; also in STOP_WORDS
#:               for the lexicon, but that does NOT affect material_family)
#:   "rPLA"    → "rpla"   (unknown → stripped, returned as-is)
#:   "PLA/PHA" → "pla"    (prefix "pla" matches before separator "/" is checked)
#:   "PLA"     → "pla"
PLA_BIOPOLYMER_BUCKET: frozenset[str] = frozenset({"pla", "pha", "pla/pha", "lw-pla", "htpla", "rpla"})


def families_gate_compatible(sm_fam: str, opt_fam: str) -> bool:
    """Return True when the SM and OPT polymer families are gate-compatible.

    Rules (v2.1):
    - If ``opt_fam`` is empty/unknown → always compatible (don't gate on missing data).
    - If they are equal → compatible.
    - If both are in ``PLA_BIOPOLYMER_BUCKET`` → compatible (PLA/PHA/LW-PLA/HTPLA/rPLA
      are mutually compatible due to dataset inconsistency + actual material overlap).
    - Otherwise → NOT compatible (ASA≠PETG, PC≠PETG, ASA≠ABS, etc.).

    Parameters
    ----------
    sm_fam:
        Polymer family of the Spoolman filament (from ``material_family()``).
    opt_fam:
        Polymer family of the OPT candidate (from ``material_family()``).
    """
    if not opt_fam or opt_fam == sm_fam:
        return True
    return sm_fam in PLA_BIOPOLYMER_BUCKET and opt_fam in PLA_BIOPOLYMER_BUCKET


# ---------------------------------------------------------------------------
# Color-profile gate helpers (v2.1)
# ---------------------------------------------------------------------------


def opt_color_arity(
    opt: dict[str, Any],
    tag_map: dict[str, int] | None = None,
    ngram_index: dict[int, set[str]] | None = None,
    color_synonyms: dict[str, str] | None = None,
) -> int:
    """Return the effective color count for an OPT material.

    Takes the maximum of:
    - Hex color count: ``(1 if color else 0) + len(non-empty secondaryColors)``
    - Name-decomposed color count: sum of the colors Counter from ``decompose_name``

    Using the max means an entry with incomplete hex data but a descriptive multi-color
    name (e.g. "Temperature Color Change Purple to Red") still registers as multicolor.
    """
    hex_count = (1 if opt.get("color") else 0) + sum(
        1 for s in (opt.get("secondaryColors") or []) if s
    )
    opt_type_raw = opt.get("type") or opt.get("abbreviation") or ""
    opt_parsed = decompose_name(
        opt.get("name"), opt.get("brandName"), opt_type_raw,
        tag_map=tag_map,
        ngram_index=ngram_index,
        color_synonyms=color_synonyms,
    )
    name_color_count = sum(opt_parsed.colors.values())
    return max(hex_count, name_color_count)


def color_profile_compatible_soft(
    sm_profile: str,
    sm_arity: int,
    opt: dict[str, Any],
    tag_map: dict[str, int] | None = None,
    ngram_index: dict[int, set[str]] | None = None,
    color_synonyms: dict[str, str] | None = None,
) -> bool:
    """Return True when the SM color profile is compatible with an OPT candidate.

    v2.1 name-aware + soft variant of the v2 ``profiles_compatible`` gate:

    - When BOTH sides have a real arrangement tag (coextruded / gradient) AND the OPT
      entry has complete hex data (hex_count >= 2) → use the strict ``profiles_compatible``
      check.  Don't relax legit single-vs-multi where data is complete.

    - Otherwise (incomplete/absent arrangement or hex data) → keep the candidate when:
        - SM is single-color (sm_arity <= 1): keep OPT entries that are also single
          (opt_arity <= 1).
        - SM is multicolor (sm_arity >= 2): keep OPT entries that are also multicolor
          (opt_arity >= 2).

    This ensures "Temperature Color Change Purple to Red" (OPT: color=None,
    secondaryColors=[], but name has 2 color tokens) reaches scoring for a multicolor
    SM filament instead of being gate-dropped as "single".

    Parameters
    ----------
    sm_profile:
        ``sm_color_profile(sm_fil)`` — ``"single"``, ``"coextruded"``,
        ``"gradient"``, or ``"multi_unknown"``.
    sm_arity:
        Effective color count for the SM side:
        ``max(name_color_count, 1 + len(multi_color_hexes.split(","))`` if present, else 0).
    opt:
        OPT candidate dict.
    tag_map, ngram_index, color_synonyms:
        Forwarded to ``opt_color_arity`` / ``decompose_name``.
    """
    opt_profile = opt_color_profile(opt, tag_map)

    # Determine whether the OPT entry has complete arrangement + hex data.
    hex_count = (1 if opt.get("color") else 0) + sum(
        1 for s in (opt.get("secondaryColors") or []) if s
    )
    opt_has_arrangement = opt_profile in (_PROFILE_COEXTRUDED, _PROFILE_GRADIENT)
    sm_has_arrangement = sm_profile in (_PROFILE_COEXTRUDED, _PROFILE_GRADIENT)

    # Strict path: both sides have explicit arrangement tags AND OPT hex data is complete.
    if sm_has_arrangement and opt_has_arrangement and hex_count >= 2:
        return profiles_compatible(sm_profile, opt_profile)

    # Soft path: use effective arity (hex + name) for compatibility.
    arity = opt_color_arity(opt, tag_map, ngram_index, color_synonyms)
    if sm_arity >= 2:
        # SM is multicolor → keep OPT candidates that are also multicolor (arity >= 2).
        return arity >= 2
    else:
        # SM is single-color → keep OPT candidates that are single-color (arity <= 1).
        return arity <= 1


# ---------------------------------------------------------------------------
# Vendor alias resolution
# ---------------------------------------------------------------------------


def resolve_opentag_brand(sm_vendor_name: str | None, aliases: dict[str, str]) -> str:
    """Map a Spoolman vendor name to its OpenTag brand name via the alias dict.

    The alias dict is keyed by ``normalize_vendor(sm_vendor)``.  If a mapping
    is found the normalized OpenTag brand is returned; otherwise the normalized
    SM vendor name is returned unchanged (so the caller can use it as a brand
    key without further transformation).

    Example::

        aliases = {"prusa": "prusament"}
        resolve_opentag_brand("Prusa", aliases)    # → "prusament"
        resolve_opentag_brand("ELEGOO", aliases)   # → "elegoo"
        resolve_opentag_brand(None, aliases)       # → ""
    """
    key = normalize_vendor(sm_vendor_name)
    return aliases.get(key, key)


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _color_name_tokens(
    name: str | None,
    vendor: str | None,
    material: str | None,
    tag_map: dict[str, int] | None = None,
) -> set[str]:
    """Extract the color-name tokens from a filament name by removing vendor,
    material, and finish words.

    SHIM — retained for backward-compat with existing tests.  The v2 scorer
    uses ``decompose_name`` instead.  This function now delegates to the shared
    ``_residual_token_list`` (same implementation as before, just factored out).

    Returns a (possibly empty) set of lowercase token strings.  An empty set
    means no distinguishable color token could be isolated.

    Examples::

        _color_name_tokens("Orange", "Hatchbox", "PETG", ...)  → {"orange"}
        _color_name_tokens("Copper PETG", "Hatchbox", "PETG", ...)  → {"copper"}
        _color_name_tokens("PLA Silk Bronze", "Buddy3D", "PLA Silk", ...)  → {"bronze"}
        _color_name_tokens("Transparent Orange", "Hatchbox", "PLA", ...)  → {"orange"}
    """
    if tag_map is None:
        tag_map = DEFAULT_MATERIAL_TAG_IDS

    tokens = _residual_token_list(name, vendor, material, tag_map)

    # Drop separator sentinels and noise tokens (same set as the old code)
    _NOISE = {"color", "dual", "tri", "multi", "multicolor", "tricolor", "dualcolor", "__SEP__"}
    return {t for t in tokens if t != "__SEP__" and len(t) > 1 and t not in _NOISE}


def _name_similarity(
    sm_tokens: set[str],
    opt_tokens: set[str],
) -> float:
    """Score color-name token overlap in [0.0, 1.0].

    SHIM — retained for backward-compat with existing tests.

    Scoring:
    - If both token sets are non-empty: Jaccard similarity with a containment
      bonus for single-token names (e.g. {"orange"} inside {"pumpkin", "orange"}).
    - If either side has no color tokens: return 0.5 (neutral — naming gap
      shouldn't nuke an otherwise-good match).
    - Disjoint non-empty sets: 0.0.
    """
    if not sm_tokens or not opt_tokens:
        # One side has no isolatable color token → neutral
        return 0.5

    inter = sm_tokens & opt_tokens
    union = sm_tokens | opt_tokens

    if not inter:
        return 0.0

    jaccard = len(inter) / len(union)

    # Containment bonus: if the smaller set is fully contained in the larger,
    # treat it as a strong partial match even when sizes differ (e.g. "orange"
    # ⊂ {"pumpkin", "orange"}).
    smaller = sm_tokens if len(sm_tokens) <= len(opt_tokens) else opt_tokens
    larger = opt_tokens if len(sm_tokens) <= len(opt_tokens) else sm_tokens
    if smaller <= larger:
        containment = len(smaller) / len(larger)
        return max(jaccard, containment)

    return jaccard


def _color_distance(hex1: str | None, hex2: str | None) -> float:
    """Simple RGB Euclidean distance normalised to [0, 1]. 0 = same, 1 = max apart."""
    def _parse(h: str | None) -> tuple[int, int, int] | None:
        if not h:
            return None
        h = h.lstrip("#")
        if len(h) != 6:
            return None
        try:
            return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        except ValueError:
            return None

    r1 = _parse(hex1)
    r2 = _parse(hex2)
    if r1 is None or r2 is None:
        return 0.5  # neutral when one is unknown
    dist = ((r1[0]-r2[0])**2 + (r1[1]-r2[1])**2 + (r1[2]-r2[2])**2) ** 0.5
    return dist / (255 * 3 ** 0.5)


def _finish_score(
    sm_finish_ids: set[int],
    opt_finish_ids: set[int],
) -> float:
    """Return a finish component in [-0.10, +0.10].

    Rules (v2 rescaled from ±0.15 to ±0.10 to match new weight budget):
    - Both empty (solid vs solid): neutral +0.05
    - Perfect match (same non-empty sets): +0.10
    - Both non-empty, partial overlap: Jaccard × 0.10
    - One solid, other has finish (clear mismatch): −0.10 penalty
    - Both non-empty but disjoint: −0.07 penalty (matte vs silk)

    A mismatch (penalty) is large enough to drop a wrong-finish candidate below a
    correct plain/solid one of the same color name.
    """
    if not sm_finish_ids and not opt_finish_ids:
        # Both plain/solid → neutral (half the max reward)
        return 0.05

    if not sm_finish_ids or not opt_finish_ids:
        # One solid, the other finished → clear mismatch penalty
        return -0.10

    union = sm_finish_ids | opt_finish_ids
    inter = sm_finish_ids & opt_finish_ids
    if not inter:
        # Both finished but different (e.g. matte vs silk) → mismatch penalty
        return -0.07

    jaccard = len(inter) / len(union)
    return 0.10 * jaccard


def _color_multiset_score(a: Counter, b: Counter) -> float:
    """Score two color Counters (multisets) in [0.0, 1.0].

    Formula:
        matched  = sum((A & B).values())   # intersection (minimum per-color)
        denom    = matched + sum((A - B).values()) + sum((B - A).values())
        score    = matched / denom         (= 1.0 iff A == B)

    When either side is empty → neutral 0.5 (naming gap, not a mismatch).
    """
    if not a or not b:
        return 0.5  # neutral: one side has no recognized color tokens

    matched = sum((a & b).values())
    extra_a = sum((a - b).values())
    extra_b = sum((b - a).values())
    denom = matched + extra_a + extra_b
    if denom == 0:
        return 0.5  # shouldn't happen (both non-empty), but defensive
    return matched / denom


def _modifier_jaccard(sm_mods: frozenset[str], opt_mods: frozenset[str]) -> float:
    """Jaccard of two modifier sets in [0.0, 1.0].

    When both sides are empty → neutral 0.5 (no modifier signal, not a mismatch).
    """
    if not sm_mods and not opt_mods:
        return 0.5  # neutral
    union = sm_mods | opt_mods
    if not union:
        return 0.5
    inter = sm_mods & opt_mods
    return len(inter) / len(union)


def _hex_score(sm_hex: str | None, opt_hex: str | None) -> float:
    """Score hex proximity in [0.0, 0.05] (max 0.05 weight)."""
    dist = _color_distance(sm_hex, opt_hex)
    # distance 0 → 0.05, distance 1 → 0.0; neutral 0.025 when unknown (dist == 0.5)
    return max(0.0, 0.05 * (1.0 - dist / 0.5)) if dist <= 0.5 else 0.0


def _string_similarity_bonus(sm_name: str, opt_name: str) -> float:
    """Full-string SequenceMatcher ratio × 0.05 (tie-breaker, max 0.05)."""
    if not sm_name or not opt_name:
        return 0.0
    ratio = SequenceMatcher(None, _norm(sm_name), _norm(opt_name)).ratio()
    return ratio * 0.05


def score_candidate(
    sm: SpoolmanFilament,
    opt: dict[str, Any],
    tag_map: dict[str, int] | None = None,
    aliases: dict[str, str] | None = None,
    color_map: dict[str, str] | None = None,
    lexicon: dict[str, list[str]] | None = None,
) -> float:
    """Score an OPTMaterial candidate against a SpoolmanFilament (v2).

    Returns a confidence in [0.0, 1.0].  Higher is better.

    Scoring components (v2 weights — sum to 1.0 for a perfect match):
    - Color multiset similarity:  0.40  ← primary discriminator within brand/material
    - Modifier set Jaccard:       0.15
    - Material family:            0.15  exact / 0.075 substring
    - Vendor/brand:               0.15  exact / 0.075 substring
    - Finish tag overlap:        ±0.10
    - Color hex proximity:        0.05
    - Full-string tie-breaker:   +0.05 max

    ``aliases`` is the parsed ``opentag_vendor_aliases`` dict for vendor resolution.
    ``color_map`` feeds COLOR_SYNONYMS overrides (synonyms-only in v2).
    ``lexicon`` is the mined modifier/color lexicon dict (``{"modifiers":..., "colors":...}``).
    When ``None``, seed-only fallback is used.
    """
    if tag_map is None:
        tag_map = DEFAULT_MATERIAL_TAG_IDS
    if aliases is None:
        aliases = {}
    if color_map is None:
        color_map = COLOR_SYNONYMS

    # Merge user synonym overrides on top of default synonyms
    effective_synonyms = dict(COLOR_SYNONYMS)
    if color_map is not COLOR_SYNONYMS:
        effective_synonyms.update(color_map)

    # Build ngram index once from the lexicon
    ngram_index = build_ngram_index(lexicon)

    score = 0.0

    # ---- Material family (0.15) ----
    sm_mat = material_family(sm.material, tag_map)
    opt_type_raw = opt.get("type") or opt.get("abbreviation") or ""
    opt_mat = material_family(opt_type_raw, tag_map)
    if sm_mat and opt_mat:
        if sm_mat == opt_mat:
            score += 0.15
        elif sm_mat in opt_mat or opt_mat in sm_mat:
            score += 0.075

    # ---- Vendor / brand (0.15) ----
    sm_vendor_name = sm.vendor.name if sm.vendor else None
    sm_vendor = resolve_opentag_brand(sm_vendor_name, aliases)
    opt_brand = normalize_vendor(opt.get("brandName"))
    if sm_vendor and opt_brand:
        if sm_vendor == opt_brand:
            score += 0.15
        elif sm_vendor in opt_brand or opt_brand in sm_vendor:
            score += 0.075

    # ---- Color multiset (0.40) ----
    # Decompose both sides using structured decomposition
    sm_parsed = decompose_name(
        sm.name, sm_vendor_name, sm.material,
        tag_map=tag_map,
        ngram_index=ngram_index,
        color_synonyms=effective_synonyms,
    )
    opt_parsed = decompose_name(
        opt.get("name"), opt.get("brandName"), opt_type_raw,
        tag_map=tag_map,
        ngram_index=ngram_index,
        color_synonyms=effective_synonyms,
    )

    color_sim = _color_multiset_score(sm_parsed.colors, opt_parsed.colors)
    score += 0.40 * color_sim

    # ---- Modifier Jaccard (0.15) ----
    mod_sim = _modifier_jaccard(sm_parsed.modifiers, opt_parsed.modifiers)
    score += 0.15 * mod_sim

    # ---- Finish component (up to +0.10, min −0.10) ----
    # Use pre-computed finish_ids from ParsedName where possible; also scan OPT tags
    sm_finish_ids = set(sm_parsed.finish_ids)
    opt_tags_raw: list[str] = opt.get("tags") or []
    opt_finish_ids: set[int] = set(opt_parsed.finish_ids)
    for ts in opt_tags_raw:
        opt_finish_ids.update(finish_ids_from_text(ts, None, tag_map))
    score += _finish_score(sm_finish_ids, opt_finish_ids)

    # ---- Color hex proximity (0.05) ----
    score += _hex_score(sm.color_hex, opt.get("color"))

    # ---- Full-string similarity tie-breaker (+0.05 max) ----
    score += _string_similarity_bonus(sm.name, opt.get("name"))

    return round(score, 4)


# ---------------------------------------------------------------------------
# Top-level match function
# ---------------------------------------------------------------------------


def find_best_match(
    sm: SpoolmanFilament,
    materials: list[dict[str, Any]],
    tag_map: dict[str, int] | None = None,
    aliases: dict[str, str] | None = None,
    *,
    top_n: int = 10,
    min_confidence: float = 0.30,
    color_map: dict[str, str] | None = None,
    lexicon: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Find the best matching OPTMaterial for a SpoolmanFilament.

    Returns::

        {
            "best": OPTMaterial dict | None,
            "confidence": float,
            "alternates": [OPTMaterial dict, ...],      # top_n excluding best
            "alternate_scores": [float, ...],           # score for each alternate
        }

    When no candidate exceeds ``min_confidence`` the best is None.
    ``alternate_scores`` always has the same length as ``alternates``.

    ``aliases`` is forwarded to ``score_candidate`` for vendor-alias resolution.
    ``color_map`` is forwarded to ``score_candidate`` for synonym overrides.
    ``lexicon`` is forwarded to ``score_candidate`` for the mined modifier/color lexicon.
    """
    if not materials:
        return {"best": None, "confidence": 0.0, "alternates": [], "alternate_scores": []}
    if aliases is None:
        aliases = {}

    # Defensive: skip any candidate that isn't a dict (guard against shape drift
    # or a malformed cache entry containing a string instead of an OPTMaterial).
    scored = [
        (score_candidate(sm, opt, tag_map, aliases, color_map, lexicon), opt)
        for opt in materials
        if isinstance(opt, dict)
    ]
    if not scored:
        return {"best": None, "confidence": 0.0, "alternates": [], "alternate_scores": []}
    scored.sort(key=lambda x: x[0], reverse=True)

    top = scored[:top_n + 1]
    best_score, best_opt = top[0]

    if best_score < min_confidence:
        alts = top[:top_n]
        return {
            "best": None,
            "confidence": best_score,
            "alternates": [o for _, o in alts],
            "alternate_scores": [s for s, _ in alts],
        }

    alts = top[1:top_n + 1]
    return {
        "best": best_opt,
        "confidence": best_score,
        "alternates": [o for _, o in alts],
        "alternate_scores": [s for s, _ in alts],
    }
