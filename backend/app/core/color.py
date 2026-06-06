"""Color helpers — pure, no I/O.

``to_fdb_color`` / ``to_sm_color`` normalise the hex-color representation at the
boundary between systems (FDB expects a leading ``#``; Spoolman stores bare hex).

``sm_multicolor_to_fdb`` / ``fdb_multicolor_to_sm`` translate between Spoolman's
multicolor shape (``color_hex`` + ``multi_color_hexes`` CSV + ``multi_color_direction``)
and Filament DB's structured shape (``color`` + ``secondaryColors[]`` + arrangement
encoded in ``optTags`` — tag 29 = coextruded, tag 28 = gradient).  ``multicolor_signature``
produces a system-agnostic canonical string so the sync engine can detect which side
changed between cycles.
"""

from __future__ import annotations

from app.core.material_tags import MANAGED_FINISH_IDS

# OpenPrintTag arrangement tag IDs surfaced by Filament DB in ``optTags``.
# coextruded (29) takes precedence over gradient (28) when both are present.
TAG_GRADIENT = 28
TAG_COEXTRUDED = 29
ARRANGEMENT_TAGS = frozenset({TAG_GRADIENT, TAG_COEXTRUDED})


def to_fdb_color(value: str | None) -> str | None:
    """Ensure exactly one leading '#' for a Filament DB color value.

    ``"93BE2F"`` → ``"#93BE2F"``, ``"#93BE2F"`` → ``"#93BE2F"``.
    None / empty → None.  Case is preserved; only the '#' is the contract.
    """
    if not value:
        return None
    stripped = value.lstrip("#")
    return f"#{stripped}" if stripped else None


def to_sm_color(value: str | None) -> str | None:
    """Strip leading '#' for a Spoolman color_hex value.

    ``"#93BE2F"`` → ``"93BE2F"``, ``"93BE2F"`` → ``"93BE2F"``.
    None / empty → None.
    """
    if not value:
        return None
    stripped = value.lstrip("#")
    return stripped if stripped else None


def _clear_arrangement_tags(tags: list | None) -> list[int]:
    """Return ``tags`` (coerced to int) with both arrangement tags removed, order preserved."""
    out: list[int] = []
    for t in tags or []:
        try:
            ti = int(t)
        except (TypeError, ValueError):
            continue
        if ti not in ARRANGEMENT_TAGS:
            out.append(ti)
    return out


def _set_arrangement_tag(tags: list | None, tag: int) -> list[int]:
    """Return ``tags`` with any arrangement tag replaced by ``tag`` (appended last)."""
    base = _clear_arrangement_tags(tags)
    base.append(tag)
    return base


def _split_hexes(multi_color_hexes: str | None) -> list[str]:
    """Parse a Spoolman ``multi_color_hexes`` CSV into normalised ``#RRGGBB`` values."""
    if not multi_color_hexes:
        return []
    return [c for c in (to_fdb_color(h.strip()) for h in multi_color_hexes.split(",")) if c]


def sm_multicolor_to_fdb(
    color_hex: str | None,
    multi_color_hexes: str | None,
    multi_color_direction: str | None,
    existing_opt_tags: list | None = None,
) -> dict:
    """Map Spoolman multicolor fields onto Filament DB's structured shape.

    Returns ``{"color", "secondaryColors", "optTags"}`` always populated:
      - coaxial      → color=None,        secondaryColors=all hexes,  optTag 29
      - longitudinal → color=first hex,   secondaryColors=rest,       optTag 28
      - solid/single → color=primary hex, secondaryColors=[],         arrangement tags cleared

    ``existing_opt_tags`` is merged so unrelated tags (and variant inheritance)
    survive the write; pass ``None`` at create time.
    """
    hexes = _split_hexes(multi_color_hexes)

    if len(hexes) <= 1:
        return {
            "color": to_fdb_color(color_hex),
            "secondaryColors": [],
            "optTags": _clear_arrangement_tags(existing_opt_tags),
        }

    if multi_color_direction == "coaxial":
        return {
            "color": None,
            "secondaryColors": hexes,
            "optTags": _set_arrangement_tag(existing_opt_tags, TAG_COEXTRUDED),
        }
    if multi_color_direction == "longitudinal":
        return {
            "color": hexes[0],
            "secondaryColors": hexes[1:],
            "optTags": _set_arrangement_tag(existing_opt_tags, TAG_GRADIENT),
        }
    # Multiple hexes but unknown/absent direction — be defensive: treat as solid
    # primary + extras, no arrangement tag.
    return {
        "color": hexes[0],
        "secondaryColors": hexes[1:],
        "optTags": _clear_arrangement_tags(existing_opt_tags),
    }


def arrangement_from_tags(opt_tags: list | None) -> str:
    """Derive arrangement ("coextruded"|"gradient"|"solid") from optTags.

    Coextruded (tag 29) wins over gradient (tag 28) when both are present.
    """
    ints = {int(t) for t in (opt_tags or []) if _is_int(t)}
    if TAG_COEXTRUDED in ints:
        return "coextruded"
    if TAG_GRADIENT in ints:
        return "gradient"
    return "solid"


def _is_int(value) -> bool:
    try:
        int(value)
        return True
    except (TypeError, ValueError):
        return False


def fdb_multicolor_to_sm(
    color: str | None,
    secondary_colors: list | None,
    opt_tags: list | None,
) -> dict:
    """Map Filament DB structured color fields onto Spoolman's shape.

    Returns ``{"color_hex", "multi_color_hexes", "multi_color_direction"}``.
    Spoolman has no null-primary concept, so for coextruded filaments the primary
    ``color_hex`` is synthesised from the first secondary color.
    """
    sec = [c for c in (to_sm_color(c) for c in (secondary_colors or [])) if c]
    arrangement = arrangement_from_tags(opt_tags)

    if arrangement == "coextruded":
        return {
            "color_hex": sec[0] if sec else None,
            "multi_color_hexes": ",".join(sec) if sec else None,
            "multi_color_direction": "coaxial",
        }
    if arrangement == "gradient":
        primary = to_sm_color(color)
        all_hexes = ([primary] if primary else []) + sec
        return {
            "color_hex": primary,
            "multi_color_hexes": ",".join(all_hexes) if all_hexes else None,
            "multi_color_direction": "longitudinal",
        }
    return {
        "color_hex": to_sm_color(color),
        "multi_color_hexes": None,
        "multi_color_direction": None,
    }


def multicolor_signature(
    color: str | None,
    secondary_colors: list | None,
    opt_tags: list | None,
) -> str:
    """Canonical, system-agnostic signature of a filament's color state.

    Two filaments yield the same signature iff they represent the same multicolor
    state, regardless of which system produced them.  Used to diff snapshots.
    """
    arrangement = arrangement_from_tags(opt_tags)
    norm_color = (to_sm_color(color) or "").lower()
    norm_sec = ",".join((to_sm_color(c) or "").lower() for c in (secondary_colors or []))
    return f"{arrangement}|{norm_color}|{norm_sec}"


def apply_finish_tags(
    existing_opt_tags: list | None,
    finish_ids: set[int],
) -> list[int]:
    """Merge finish tag IDs into ``optTags`` without touching arrangement or unknown tags.

    Algorithm:
    1. Coerce all existing tags to int (skip malformed).
    2. Remove every tag in ``MANAGED_FINISH_IDS`` (the full managed set, not just the
       incoming ones — this clears stale finish tags from the previous cycle).
    3. Append all IDs in ``finish_ids`` (sorted for deterministic output).
    4. Arrangement tags (28/29) and any other unknown tags pass through untouched.

    Returns a new list; the input is not mutated.
    """
    base: list[int] = []
    for t in existing_opt_tags or []:
        try:
            ti = int(t)
        except (TypeError, ValueError):
            continue
        if ti not in MANAGED_FINISH_IDS:
            base.append(ti)
    base.extend(sorted(finish_ids))
    return base


def sm_multicolor_signature(
    color_hex: str | None,
    multi_color_hexes: str | None,
    multi_color_direction: str | None,
) -> str:
    """Signature for a Spoolman filament — routed through the FDB mapping so both
    sides of a synced pair produce identical signatures (prevents round-trip flapping)."""
    fdb = sm_multicolor_to_fdb(color_hex, multi_color_hexes, multi_color_direction)
    return multicolor_signature(fdb["color"], fdb["secondaryColors"], fdb["optTags"])
