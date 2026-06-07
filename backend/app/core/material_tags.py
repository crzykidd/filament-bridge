"""OpenPrintTag material-finish mapping — pure, no I/O.

Filament DB follows the OpenPrintTag model: ``type`` is the BASE material (e.g. "PLA")
and finishes like Silk / Matte / Carbon Fiber are numeric OpenPrintTag IDs stored in the
``optTags`` array.  The bridge tracks these finish IDs on the Spoolman side via a dedicated
filament-level extra field (``filamentdb_material_tags``, config-overridable).

Seed map (keyword → OpenPrintTag ID), overridable via ``MATERIAL_TAG_IDS`` env var
(CSV ``keyword=id`` pairs, same format as ``field_mappings``):

  silk=17, matte=16, glitter=23, sparkle=23, glow=24, carbon=31, cf=31,
  glass=34, wood=41, metal=46, metallic=46, translucent=19, transparent=20,
  high-speed=71, hs=71, rapid=71, recycled=60

Arrangement tags (gradient=28, coextruded=29) are owned by ``color.py`` and are
NEVER modified by this module.
"""

from __future__ import annotations

import json
import re
from typing import Iterable

# ---------------------------------------------------------------------------
# The managed finish-ID set — IDs the bridge actively manages here.
# Arrangement tags (28, 29) stay with the multicolor path.
# ---------------------------------------------------------------------------

#: All OpenPrintTag IDs that the bridge manages as "finish" tags.
MANAGED_FINISH_IDS: frozenset[int] = frozenset({
    16,   # matte
    17,   # silk
    19,   # translucent
    20,   # transparent
    23,   # glitter / sparkle
    24,   # glow in the dark
    31,   # carbon fiber
    34,   # glass fiber
    41,   # wood fill
    46,   # metal fill / metallic
    60,   # recycled
    71,   # high speed
})

# ---------------------------------------------------------------------------
# Seed keyword → OpenPrintTag ID map
# ---------------------------------------------------------------------------

#: Default keyword → finish-tag ID map.  Overridable via ``MATERIAL_TAG_IDS`` config.
DEFAULT_MATERIAL_TAG_IDS: dict[str, int] = {
    "silk":        17,
    "matte":       16,
    "glitter":     23,
    "sparkle":     23,
    "glow":        24,
    "carbon":      31,
    "cf":          31,
    "glass":       34,
    "wood":        41,
    "metal":       46,
    "metallic":    46,
    "translucent": 19,
    "transparent": 20,
    "high-speed":  71,
    "hs":          71,
    "rapid":       71,
    "recycled":    60,
}


# ---------------------------------------------------------------------------
# Serialization helpers for Spoolman extra-field storage
# ---------------------------------------------------------------------------


def serialize_material_tags(ids: Iterable[int]) -> str:
    """Serialize finish-tag IDs to a comma-separated string for Spoolman text fields.

    Spoolman text extra fields accept a JSON string value (``"17,28"``), NOT a JSON
    array (``"[17, 28]"`` → 400 Bad Request).  This function produces the correct
    CSV string form that ``encode_extra_value`` will then JSON-quote for the wire.

    Examples::

        serialize_material_tags([17, 28]) → "17,28"
        serialize_material_tags([28, 17]) → "17,28"   # sorted
        serialize_material_tags([17])     → "17"
        serialize_material_tags([])       → ""
    """
    sorted_ids = sorted(set(ids))
    return ",".join(str(i) for i in sorted_ids)


def parse_material_tags(raw: object) -> list[int]:
    """Parse a material-tags value read from a Spoolman extra field back to a list of ints.

    Tolerant / backward-compatible:
    - New CSV string form: ``"17,28"``   → ``[17, 28]``
    - Empty string:         ``""``       → ``[]``
    - Legacy JSON-array string: ``"[17]"`` → ``[17]``   (pre-fix Spoolman had this fail on write
      but any value that did get stored as a JSON-decoded list is also accepted)
    - A real Python list (already decoded upstream): ``[17]`` → ``[17]``
    - None or unknown types → ``[]``

    Returns a sorted list of unique ints (only values that are parseable as int are kept).
    """
    if raw is None:
        return []
    # If it's already a list (decoded upstream), iterate directly.
    if isinstance(raw, list):
        result: list[int] = []
        for v in raw:
            try:
                result.append(int(v))
            except (TypeError, ValueError):
                pass
        return sorted(set(result))
    if not isinstance(raw, str):
        return []
    text = raw.strip()
    if not text:
        return []
    # Try legacy JSON-array form first: "[17]" or "[17, 28]"
    if text.startswith("["):
        try:
            decoded = json.loads(text)
            if isinstance(decoded, list):
                result = []
                for v in decoded:
                    try:
                        result.append(int(v))
                    except (TypeError, ValueError):
                        pass
                return sorted(set(result))
        except (json.JSONDecodeError, TypeError):
            pass
    # New CSV form: "17" or "17,28"
    result = []
    for part in text.split(","):
        part = part.strip()
        if part:
            try:
                result.append(int(part))
            except ValueError:
                pass
    return sorted(set(result))


def parse_material_tag_ids_config(raw: str) -> dict[str, int]:
    """Parse a ``MATERIAL_TAG_IDS`` override string (``keyword=id,...``) into a dict.

    Values must be integers; malformed pairs are silently skipped.  Returns an empty
    dict for an empty / whitespace-only string, which callers should interpret as
    "use the seed defaults" (not as "suppress all tags").
    """
    result: dict[str, int] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            continue
        keyword, _, id_str = pair.partition("=")
        keyword = keyword.strip().lower()
        id_str = id_str.strip()
        if not keyword:
            continue
        try:
            result[keyword] = int(id_str)
        except ValueError:
            continue
    return result


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------


def finish_ids_from_text(
    name: str | None,
    material: str | None,
    tag_map: dict[str, int] | None = None,
) -> set[int]:
    """Extract ALL finish tag IDs whose keyword appears in ``name`` or ``material``.

    Matching is whole-word case-insensitive.  Returns a (possibly empty) set of
    OpenPrintTag IDs from ``MANAGED_FINISH_IDS``.

    ``tag_map`` defaults to ``DEFAULT_MATERIAL_TAG_IDS`` when None.
    """
    if tag_map is None:
        tag_map = DEFAULT_MATERIAL_TAG_IDS
    text = ((name or "") + " " + (material or "")).strip()
    if not text:
        return set()
    ids: set[int] = set()
    for keyword, tag_id in tag_map.items():
        # Escape the keyword so hyphens in e.g. "high-speed" match literally.
        pattern = r"\b" + re.escape(keyword) + r"\b"
        if re.search(pattern, text, re.IGNORECASE):
            ids.add(tag_id)
    return ids


def strip_finish_words(
    material: str | None,
    tag_map: dict[str, int] | None = None,
) -> str:
    """Return ``material`` with recognised finish keywords removed and whitespace normalized.

    Never removes core material tokens — only finish keywords from the map.
    Handles hyphenated keywords (e.g. "high-speed") by matching them as a single
    token with an optional word boundary.

    ``tag_map`` defaults to ``DEFAULT_MATERIAL_TAG_IDS`` when None.

    Examples::

        strip_finish_words("PLA Silk")         → "PLA"
        strip_finish_words("PLA Matte")        → "PLA"
        strip_finish_words("PETG-CF")          → "PETG"  (cf keyword matches)
        strip_finish_words("PLA+")             → "PLA+"  (no match → unchanged)
        strip_finish_words("ABS High-Speed")   → "ABS"
    """
    if not material:
        return ""
    if tag_map is None:
        tag_map = DEFAULT_MATERIAL_TAG_IDS

    text = material
    # Sort keywords longest-first so overlapping patterns (e.g. "high-speed" before
    # "speed") are processed in a safe order.
    for keyword in sorted(tag_map.keys(), key=len, reverse=True):
        # Build a word-boundary-aware pattern; allow optional surrounding
        # separators (space, hyphen) as connectors.
        pattern = r"(?:^|[\s\-])?" + re.escape(keyword) + r"(?:[\s\-]|$)?"
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)

    # Collapse extra whitespace and strip.
    stripped = re.sub(r"\s+", " ", text).strip()
    # Fallback: if stripping left us with nothing, return the original.
    return stripped or material.strip()
