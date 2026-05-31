"""Semantic-version parsing helpers — pure, no I/O, no third-party deps.

Used to gate features on upstream versions (e.g. structured multicolor sync
requires Filament DB >= 1.33.0).
"""

from __future__ import annotations

# Minimum Filament DB version with structured multicolor support
# (color/secondaryColors/optTags). Earlier versions lack the fields entirely.
MULTICOLOR_MIN_FDB = (1, 33, 0)


def parse_semver(version: str | None) -> tuple[int, int, int]:
    """Parse ``"1.33.0"`` (or ``"v1.33.0"``, ``"1.33.0-rc1"``, ``"1.33"``) → (1, 33, 0).

    Unparseable / missing input → (0, 0, 0). Build/pre-release suffixes are dropped.
    """
    if not version:
        return (0, 0, 0)
    core = version.strip().lstrip("vV").split("+", 1)[0].split("-", 1)[0]
    parts = (core.split(".") + ["0", "0", "0"])[:3]
    out: list[int] = []
    for p in parts:
        try:
            out.append(int(p))
        except ValueError:
            out.append(0)
    return (out[0], out[1], out[2])


def version_gte(version: str | None, target: tuple[int, int, int]) -> bool:
    """True if ``version`` is at least ``target`` (unknown/missing version → False)."""
    return parse_semver(version) >= target
