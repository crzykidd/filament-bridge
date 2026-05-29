"""Fuzzy filament matcher — pure over input lists, no network I/O.

The wizard and the sync engine (FR-12 new-record detection) both call this.
"""

import re
import unicodedata
from dataclasses import dataclass, field

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
