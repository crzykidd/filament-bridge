"""OpenTag → Spoolman matcher — pure, no I/O.

Scores OPTMaterial candidates against a SpoolmanFilament by:
  1. Material/type match (normalised, finish-stripped)
  2. Vendor/brand name match
  3. Color hex proximity
  4. Finish tag overlap

Returns best match + confidence + alternates list.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.core.material_tags import DEFAULT_MATERIAL_TAG_IDS, finish_ids_from_text, strip_finish_words
from app.core.matcher import normalize_name, normalize_vendor
from app.schemas.spoolman import SpoolmanFilament


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
    - color → color_hex
    - secondaryColors → multi_color_hexes (CSV)
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

    # Color
    color = opt.get("color")
    if color:
        result["color_hex"] = color.lstrip("#").upper()

    # Secondary colors → CSV
    secondary: list[str] = opt.get("secondaryColors") or []
    if secondary:
        result["multi_color_hexes"] = ",".join(c.lstrip("#").upper() for c in secondary)

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

    Scoring components:
    - Type/material match:  0.40 (most important)
    - Vendor/brand match:   0.30
    - Color proximity:      0.20
    - Finish tag overlap:   0.10
    """
    if tag_map is None:
        tag_map = DEFAULT_MATERIAL_TAG_IDS

    score = 0.0

    # ---- Type / material (0.40) ----
    sm_mat = _norm(strip_finish_words(sm.material, tag_map) or sm.material)
    opt_type_raw = opt.get("type") or opt.get("abbreviation") or ""
    opt_mat = _norm(strip_finish_words(opt_type_raw, tag_map) or opt_type_raw)
    if sm_mat and opt_mat:
        if sm_mat == opt_mat:
            score += 0.40
        elif sm_mat in opt_mat or opt_mat in sm_mat:
            score += 0.20

    # ---- Vendor / brand (0.30) ----
    sm_vendor = normalize_vendor(sm.vendor.name if sm.vendor else None)
    opt_brand = normalize_vendor(opt.get("brandName"))
    if sm_vendor and opt_brand:
        if sm_vendor == opt_brand:
            score += 0.30
        elif sm_vendor in opt_brand or opt_brand in sm_vendor:
            score += 0.15

    # ---- Color proximity (0.20) ----
    color_dist = _color_distance(sm.color_hex, opt.get("color"))
    # distance 0 → 0.20, distance 1 → 0.0
    score += max(0.0, 0.20 * (1.0 - color_dist / 0.5)) if color_dist <= 0.5 else 0.0

    # ---- Finish tag overlap (0.10) ----
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
        score += 0.10 * jaccard
    else:
        # Both have no finish tags → neutral match
        score += 0.05

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
