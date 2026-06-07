"""OpenTag → Spoolman matcher — pure, no I/O.

Scores OPTMaterial candidates against a SpoolmanFilament by:
  1. Material/type match (normalised, finish-stripped)
  2. Vendor/brand name match
  3. Color name similarity  ← key within-brand/material discriminator
  4. Color hex proximity
  5. Finish tag overlap

Returns best match + confidence + alternates list.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.core.color import TAG_COEXTRUDED, TAG_GRADIENT, arrangement_from_tags, fdb_multicolor_to_sm
from app.core.material_tags import DEFAULT_MATERIAL_TAG_IDS, finish_ids_from_text, strip_finish_words
from app.core.matcher import normalize_name, normalize_vendor
from app.schemas.spoolman import SpoolmanFilament


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

    ``single``         — no ``secondaryColors``
    ``coextruded``     — optTag 29 present (or tag string "coextruded")
    ``gradient``       — optTag 28 present (or tag string "gradual_color_change")
    ``multi_unknown``  — ``secondaryColors`` present but no arrangement tag
    """
    secondary: list = opt.get("secondaryColors") or []
    if not secondary:
        return _PROFILE_SINGLE

    # Build integer opt-tags list from the optTags field (integer tag IDs)
    opt_tags_int: list[int] = []
    for t in opt.get("optTags") or []:
        try:
            opt_tags_int.append(int(t))
        except (TypeError, ValueError):
            pass

    # Also scan string tags for arrangement words (coextruded / gradual_color_change)
    # by mapping them to the integer tag IDs understood by arrangement_from_tags.
    tag_strings: list[str] = [s.lower().strip() for s in (opt.get("tags") or []) if isinstance(s, str)]
    if "coextruded" in tag_strings:
        opt_tags_int.append(TAG_COEXTRUDED)
    if "gradual_color_change" in tag_strings or "gradient" in tag_strings:
        opt_tags_int.append(TAG_GRADIENT)

    arrangement = arrangement_from_tags(opt_tags_int)
    if arrangement == "coextruded":
        return _PROFILE_COEXTRUDED
    if arrangement == "gradient":
        return _PROFILE_GRADIENT
    return _PROFILE_MULTI_UNKNOWN


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
    result["extra.filamentdb_material_tags"] = sorted(finish_ids)

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

    if secondary:
        # Multicolor: delegate to fdb_multicolor_to_sm for coextruded/gradient so SM↔FDB
        # stays consistent (handles empty primary for coextruded, builds correct hex CSV).
        # For multi_unknown (secondaries present but no arrangement tag), fdb_multicolor_to_sm
        # would drop the secondaries (solid fallback), so we handle that case directly.
        arrangement = arrangement_from_tags(opt_tags_int)
        if arrangement in ("coextruded", "gradient"):
            sm_color = fdb_multicolor_to_sm(opt_color, secondary, opt_tags_int)
            if sm_color["color_hex"] is not None:
                result["color_hex"] = sm_color["color_hex"].upper()
            if sm_color["multi_color_hexes"] is not None:
                result["multi_color_hexes"] = sm_color["multi_color_hexes"].upper()
            if sm_color["multi_color_direction"] is not None:
                result["multi_color_direction"] = sm_color["multi_color_direction"]
        else:
            # multi_unknown: preserve primary + secondary hexes; no direction
            if opt_color:
                result["color_hex"] = opt_color.lstrip("#").upper()
            all_hexes = []
            if opt_color:
                all_hexes.append(opt_color.lstrip("#").upper())
            all_hexes.extend(c.lstrip("#").upper() for c in secondary if c)
            if all_hexes:
                result["multi_color_hexes"] = ",".join(all_hexes)
    else:
        # Single-color: map primary color directly
        if opt_color:
            result["color_hex"] = opt_color.lstrip("#").upper()

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

    # Identity fields → extra
    slug = opt.get("slug")
    if slug:
        result["extra.openprinttag_slug"] = slug

    uuid_val = opt.get("uuid")
    if uuid_val:
        result["extra.openprinttag_uuid"] = uuid_val

    return result


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _norm(s: str | None) -> str:
    if not s:
        return ""
    return unicodedata.normalize("NFKC", s).lower().strip()


def _color_name_tokens(
    name: str | None,
    vendor: str | None,
    material: str | None,
    tag_map: dict[str, int] | None = None,
) -> set[str]:
    """Extract the color-name tokens from a filament name by removing vendor,
    material, and finish words.

    Returns a (possibly empty) set of lowercase token strings.  An empty set
    means no distinguishable color token could be isolated.

    Examples::

        _color_name_tokens("Orange", "Hatchbox", "PETG", ...)  → {"orange"}
        _color_name_tokens("Copper PETG", "Hatchbox", "PETG", ...)  → {"copper"}
        _color_name_tokens("PLA Silk Bronze", "Buddy3D", "PLA Silk", ...)  → {"bronze"}
    """
    if tag_map is None:
        tag_map = DEFAULT_MATERIAL_TAG_IDS

    text = _norm(name)
    if not text:
        return set()

    # Remove vendor tokens
    vendor_norm = _norm(vendor)
    for tok in vendor_norm.split():
        # Whole-word removal
        text = re.sub(r'\b' + re.escape(tok) + r'\b', ' ', text)

    # Remove material tokens (base material, finish-stripped)
    mat_norm = _norm(material)
    base_mat = _norm(strip_finish_words(mat_norm, tag_map) or mat_norm)
    for tok in base_mat.split():
        text = re.sub(r'\b' + re.escape(tok) + r'\b', ' ', text)

    # Remove full material string tokens (catches e.g. "petg" in "Copper PETG")
    for tok in mat_norm.split():
        text = re.sub(r'\b' + re.escape(tok) + r'\b', ' ', text)

    # Remove finish words
    for keyword in sorted(tag_map.keys(), key=len, reverse=True):
        text = re.sub(r'\b' + re.escape(keyword) + r'\b', ' ', text, flags=re.IGNORECASE)

    # Tokenize what remains
    tokens = {t for t in text.split() if len(t) > 1}
    return tokens


def _name_similarity(
    sm_tokens: set[str],
    opt_tokens: set[str],
) -> float:
    """Score color-name token overlap in [0.0, 1.0].

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


def score_candidate(
    sm: SpoolmanFilament,
    opt: dict[str, Any],
    tag_map: dict[str, int] | None = None,
) -> float:
    """Score an OPTMaterial candidate against a SpoolmanFilament.

    Returns a confidence in [0.0, 1.0].  Higher is better.

    Scoring components (sum ≈ 1.0):
    - Type/material match:   0.25 exact / 0.125 substring
    - Vendor/brand match:    0.25 exact / 0.125 substring
    - Color name similarity: 0.35  ← key within-brand/material discriminator
    - Color hex proximity:   0.10
    - Finish tag overlap:    0.05
    """
    if tag_map is None:
        tag_map = DEFAULT_MATERIAL_TAG_IDS

    score = 0.0

    # ---- Type / material (0.25) ----
    sm_mat = _norm(strip_finish_words(sm.material, tag_map) or sm.material)
    opt_type_raw = opt.get("type") or opt.get("abbreviation") or ""
    opt_mat = _norm(strip_finish_words(opt_type_raw, tag_map) or opt_type_raw)
    if sm_mat and opt_mat:
        if sm_mat == opt_mat:
            score += 0.25
        elif sm_mat in opt_mat or opt_mat in sm_mat:
            score += 0.125

    # ---- Vendor / brand (0.25) ----
    sm_vendor_name = sm.vendor.name if sm.vendor else None
    sm_vendor = normalize_vendor(sm_vendor_name)
    opt_brand = normalize_vendor(opt.get("brandName"))
    if sm_vendor and opt_brand:
        if sm_vendor == opt_brand:
            score += 0.25
        elif sm_vendor in opt_brand or opt_brand in sm_vendor:
            score += 0.125

    # ---- Color name similarity (0.35) ----
    sm_color_tokens = _color_name_tokens(sm.name, sm_vendor_name, sm.material, tag_map)
    opt_color_tokens = _color_name_tokens(
        opt.get("name"), opt.get("brandName"), opt_type_raw, tag_map
    )
    name_sim = _name_similarity(sm_color_tokens, opt_color_tokens)
    score += 0.35 * name_sim

    # ---- Color hex proximity (0.10) ----
    color_dist = _color_distance(sm.color_hex, opt.get("color"))
    # distance 0 → 0.10, distance 1 → 0.0
    score += max(0.0, 0.10 * (1.0 - color_dist / 0.5)) if color_dist <= 0.5 else 0.0

    # ---- Finish tag overlap (0.05) ----
    sm_finish_ids = finish_ids_from_text(sm.name, sm.material, tag_map)
    opt_tags_raw: list[str] = opt.get("tags") or []
    opt_finish_ids: set[int] = set()
    for ts in opt_tags_raw:
        opt_finish_ids.update(finish_ids_from_text(ts, None, tag_map))
    opt_finish_ids.update(finish_ids_from_text(opt.get("name", ""), opt_type_raw, tag_map))
    if sm_finish_ids or opt_finish_ids:
        union = sm_finish_ids | opt_finish_ids
        inter = sm_finish_ids & opt_finish_ids
        jaccard = len(inter) / len(union) if union else 1.0
        score += 0.05 * jaccard
    else:
        # Both have no finish tags → neutral match
        score += 0.025

    return round(score, 4)


# ---------------------------------------------------------------------------
# Top-level match function
# ---------------------------------------------------------------------------


def find_best_match(
    sm: SpoolmanFilament,
    materials: list[dict[str, Any]],
    tag_map: dict[str, int] | None = None,
    *,
    top_n: int = 5,
    min_confidence: float = 0.30,
) -> dict[str, Any]:
    """Find the best matching OPTMaterial for a SpoolmanFilament.

    Returns::

        {
            "best": OPTMaterial dict | None,
            "confidence": float,
            "alternates": [OPTMaterial dict, ...],   # top_n excluding best
        }

    When no candidate exceeds ``min_confidence`` the best is None.
    """
    if not materials:
        return {"best": None, "confidence": 0.0, "alternates": []}

    # Defensive: skip any candidate that isn't a dict (guard against shape drift
    # or a malformed cache entry containing a string instead of an OPTMaterial).
    scored = [
        (score_candidate(sm, opt, tag_map), opt)
        for opt in materials
        if isinstance(opt, dict)
    ]
    if not scored:
        return {"best": None, "confidence": 0.0, "alternates": []}
    scored.sort(key=lambda x: x[0], reverse=True)

    top = scored[:top_n + 1]
    best_score, best_opt = top[0]

    if best_score < min_confidence:
        return {
            "best": None,
            "confidence": best_score,
            "alternates": [o for _, o in top[:top_n]],
        }

    alternates = [o for _, o in top[1:top_n + 1]]
    return {
        "best": best_opt,
        "confidence": best_score,
        "alternates": alternates,
    }
