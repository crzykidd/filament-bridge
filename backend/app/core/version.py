"""Semantic-version parsing helpers — pure, no I/O, no third-party deps.

Used to gate features on upstream versions (e.g. structured multicolor sync
requires Filament DB >= 1.33.0).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Minimum supported upstream versions
# ---------------------------------------------------------------------------
# A *known* below-minimum upstream hard-gates sync: the trigger/dry-run
# endpoints, wizard execute, and scheduled auto-sync all refuse with a
# 409/blocking message.  An *unknown* (unreadable) version does NOT block —
# that is a connectivity concern surfaced as health ``degraded``.
#
# Filament DB 1.33.0 — structured multicolor (color/secondaryColors/optTags),
#   finish-tag (optTags) sync, and the temperature fields the two-way
#   material-property passes read/write. Older FDB lacks these entirely.
# Spoolman 0.22.0 — structured multi-color (multi_color_hexes / multi_color_direction)
#   plus the stable extra-fields system the bridge stores cross-reference IDs in.
MIN_FDB = (1, 33, 0)
MIN_SPOOLMAN = (0, 22, 0)

# Minimum FDB version with structured multicolor support — same floor as MIN_FDB
# today; kept as its own name where the engine gates the multicolor passes.
MULTICOLOR_MIN_FDB = MIN_FDB


def format_version(target: tuple[int, int, int]) -> str:
    """Render a version tuple for user-facing messages: (1, 33, 0) → ``"1.33.0"``."""
    return ".".join(str(p) for p in target)


def incompatibilities(fdb_version: str | None, spoolman_version: str | None) -> list[str]:
    """Return a blocking message per upstream whose KNOWN version is below its
    minimum (empty list = OK to sync).

    A ``None``/unknown version is NOT treated as incompatible — that means we
    couldn't read it (a connectivity issue, surfaced separately as health
    ``degraded``), not that it's old.  We only hard-block when we positively
    know the version is too old.
    """
    msgs: list[str] = []
    if isinstance(fdb_version, str) and fdb_version and not version_gte(fdb_version, MIN_FDB):
        msgs.append(
            f"Filament DB {fdb_version} is below the minimum supported version "
            f"{format_version(MIN_FDB)} — upgrade Filament DB to use sync"
        )
    if isinstance(spoolman_version, str) and spoolman_version and not version_gte(spoolman_version, MIN_SPOOLMAN):
        msgs.append(
            f"Spoolman {spoolman_version} is below the minimum supported version "
            f"{format_version(MIN_SPOOLMAN)} — upgrade Spoolman to use sync"
        )
    return msgs


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
