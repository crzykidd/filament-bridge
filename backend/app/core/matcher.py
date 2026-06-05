"""Fuzzy filament matcher — pure over input lists, no network I/O.

The wizard and the sync engine (FR-12 new-record detection) both call this.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from app.schemas.filamentdb import FDBFilament
from app.schemas.spoolman import SpoolmanFilament

# Canonical lowercase form for known vendor aliases so e.g. "ELEGOO" == "elegoo"
_VENDOR_CANONICAL: dict[str, str] = {
    "elegoo": "elegoo",
    "prusament": "prusament",
    "prusa": "prusa",
    "hatchbox": "hatchbox",
    "polymaker": "polymaker",
    "overture": "overture",
    "sunlu": "sunlu",
    "eryone": "eryone",
    "buddy3d": "buddy3d",
}


def normalize_vendor(name: str | None) -> str:
    if not name:
        return ""
    n = unicodedata.normalize("NFKC", name).lower().strip()
    n = re.sub(r"\s+", " ", n)
    return _VENDOR_CANONICAL.get(n, n)


def normalize_name(name: str | None) -> str:
    if not name:
        return ""
    n = unicodedata.normalize("NFKC", name).lower().strip()
    return re.sub(r"\s+", " ", n)


def normalize_color(color: str | None) -> str:
    if not color:
        return ""
    return color.lower().strip().lstrip("#")


def _key(vendor: str | None, name: str | None, color: str | None) -> tuple[str, str, str]:
    return (normalize_vendor(vendor), normalize_name(name), normalize_color(color))


@dataclass
class MatchedPair:
    spoolman_filament: SpoolmanFilament
    fdb_filament: FDBFilament
    confidence: float  # 1.0 = exact key match


@dataclass
class MatchResult:
    matched: list[MatchedPair] = field(default_factory=list)
    unmatched_spoolman: list[SpoolmanFilament] = field(default_factory=list)
    unmatched_fdb: list[FDBFilament] = field(default_factory=list)
    # (SM filament, list of ambiguous FDB candidates)
    ambiguous: list[tuple[SpoolmanFilament, list[FDBFilament]]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# SM variant-grouping helpers (FR-6 SM direction)
# ---------------------------------------------------------------------------

_SM_COLOR_WORDS: frozenset[str] = frozenset({
    "red", "blue", "black", "white", "grey", "gray", "green", "yellow",
    "orange", "purple", "pink", "silver", "gold", "transparent", "natural",
    "brown", "cyan", "magenta", "beige", "navy", "teal", "violet", "bronze",
    "copper", "clear",
})


def strip_color_and_words(name: str, color_hex: str | None) -> str:
    """Strip hex code and color-word lexicon from a filament name, then normalize.

    Used for SM variant clustering so "PLA Red" and "PLA Blue" share a base name.
    Falls back to the normalized original name when stripping leaves it empty.
    """
    base = name
    if color_hex:
        for v in (color_hex, color_hex.lstrip("#")):
            base = base.replace(v, "").replace(v.lower(), "").replace(v.upper(), "")
    tokens = base.split()
    filtered = [t for t in tokens if normalize_name(t) not in _SM_COLOR_WORDS]
    result = normalize_name(" ".join(filtered))
    return result or normalize_name(name)


# ---------------------------------------------------------------------------
# Finish-line extractor (Part B — Q1 resolution)
# ---------------------------------------------------------------------------

# Ordered by specificity — longer/more-specific patterns first within a token.
_FINISH_PATTERNS: list[tuple[str, list[re.Pattern[str]]]] = [
    ("glow", [
        re.compile(r"glow[\s\-]in[\s\-]the[\s\-]dark", re.IGNORECASE),
        re.compile(r"\bgitd\b", re.IGNORECASE),
        re.compile(r"\bglow\b", re.IGNORECASE),
    ]),
    ("cf", [
        re.compile(r"carbon[\s\-]?fib(?:er|re)", re.IGNORECASE),
        re.compile(r"\bcf\b", re.IGNORECASE),
    ]),
    ("multicolor", [
        re.compile(r"multi[\s\-]?color", re.IGNORECASE),
        re.compile(r"tri[\s\-]?color", re.IGNORECASE),
        re.compile(r"\brainbow\b", re.IGNORECASE),
        re.compile(r"dual[\s\-]?color", re.IGNORECASE),
    ]),
    ("hs", [
        re.compile(r"high[\s\-]speed", re.IGNORECASE),
        re.compile(r"\bhs\b", re.IGNORECASE),
    ]),
    ("metallic", [re.compile(r"\bmetallic\b", re.IGNORECASE)]),
    ("marble",   [re.compile(r"\bmarble\b",   re.IGNORECASE)]),
    ("wood",     [re.compile(r"\bwood\b",     re.IGNORECASE)]),
    ("matte",    [re.compile(r"\bmatte\b",    re.IGNORECASE)]),
    ("satin",    [re.compile(r"\bsatin\b",    re.IGNORECASE)]),
    ("silk",     [re.compile(r"\bsilk\b",     re.IGNORECASE)]),
]


def extract_finish_line(name: str, material: str | None = None) -> str:
    """Extract the finish/line token from a filament name (and optional material).

    Returns a normalized token ('silk', 'matte', 'cf', 'glow', …) or '' (standard).
    Detection is word-boundary-aware, case-insensitive, on name + material concatenated.
    """
    text = (name or "") + " " + (material or "")
    for token, patterns in _FINISH_PATTERNS:
        for pat in patterns:
            if pat.search(text):
                return token
    return ""


def sm_variant_cluster_key(sm: SpoolmanFilament) -> tuple[str, str, str]:
    """Return (vendor, material, finish) for SM variant group clustering.

    Different colors under the same vendor+material+finish are the variant-group
    signal. The finish token (e.g. 'silk', 'matte', 'cf') is parsed from the
    filament name so "PLA Silk Red" and plain "PLA Red" cluster into separate
    groups even when Spoolman records the same `material` string for both.
    This resolves Q1 from docs/wizard-redesign.md.
    """
    vendor = normalize_vendor(sm.vendor.name if sm.vendor else None)
    material = normalize_name(sm.material or "")
    finish = extract_finish_line(sm.name or "", sm.material)
    return (vendor, material, finish)


def sm_prop_conflicts(master: SpoolmanFilament, member: SpoolmanFilament) -> list[dict[str, Any]]:
    """Compare shared filament properties; return [{field, master_value, member_value}] for each mismatch.

    Both-None is not a conflict. One-None vs non-None is a conflict.
    """
    conflicts: list[dict[str, Any]] = []
    checks = [
        ("material", master.material, member.material),
        ("density", master.density, member.density),
        ("spool_weight", master.spool_weight, member.spool_weight),
        ("settings_extruder_temp", master.settings_extruder_temp, member.settings_extruder_temp),
        ("settings_bed_temp", master.settings_bed_temp, member.settings_bed_temp),
    ]
    for field_name, mv, memv in checks:
        if mv is None and memv is None:
            continue
        if mv != memv:
            conflicts.append({"field": field_name, "master_value": mv, "member_value": memv})
    return conflicts


def match_filaments(
    spoolman_filaments: list[SpoolmanFilament],
    fdb_filaments: list[FDBFilament],
) -> MatchResult:
    """Match Spoolman filaments to FDB filaments by vendor+name+color.

    Returns three buckets:
      matched    — 1-to-1 high-confidence pairs
      ambiguous  — SM record with multiple FDB candidates (user must pick)
      unmatched_* — records that found no counterpart
    """
    result = MatchResult()

    fdb_index: dict[tuple, list[FDBFilament]] = {}
    for fdb in fdb_filaments:
        k = _key(fdb.vendor, fdb.name, fdb.color)
        fdb_index.setdefault(k, []).append(fdb)

    matched_fdb_ids: set[str] = set()

    for sm in spoolman_filaments:
        vendor = sm.vendor.name if sm.vendor else None
        k = _key(vendor, sm.name, sm.color_hex)
        candidates = [f for f in fdb_index.get(k, []) if f.id not in matched_fdb_ids]

        if not candidates:
            result.unmatched_spoolman.append(sm)
        elif len(candidates) == 1:
            matched_fdb_ids.add(candidates[0].id)
            result.matched.append(MatchedPair(sm, candidates[0], confidence=1.0))
        else:
            result.ambiguous.append((sm, candidates))

    ambiguous_fdb_ids = {f.id for _, cands in result.ambiguous for f in cands}
    for fdb in fdb_filaments:
        if fdb.id not in matched_fdb_ids and fdb.id not in ambiguous_fdb_ids:
            result.unmatched_fdb.append(fdb)

    return result
