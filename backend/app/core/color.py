"""Multicolor colorName projection — pure helper, no I/O.

Maps Spoolman multicolor fields (multi_color_hexes + multi_color_direction) to a
human-readable FDB colorName string.  For single-color filaments (multi_color_hexes
absent / empty) the functions return None so callers leave colorName untouched.
"""

from __future__ import annotations

import math

# Curated palette: name → (R, G, B).  Exact CSS/X11 coordinates.
# Kept small (no external dependency) — approximate matching by design.
_PALETTE: dict[str, tuple[int, int, int]] = {
    "AliceBlue": (240, 248, 255),
    "AntiqueWhite": (250, 235, 215),
    "Aquamarine": (127, 255, 212),
    "Beige": (245, 245, 220),
    "Black": (0, 0, 0),
    "Blue": (0, 0, 255),
    "BlueViolet": (138, 43, 226),
    "Brown": (165, 42, 42),
    "Chocolate": (210, 105, 30),
    "Coral": (255, 127, 80),
    "CornflowerBlue": (100, 149, 237),
    "Crimson": (220, 20, 60),
    "Cyan": (0, 255, 255),
    "DarkBlue": (0, 0, 139),
    "DarkCyan": (0, 139, 139),
    "DarkGray": (169, 169, 169),
    "DarkGreen": (0, 100, 0),
    "DarkMagenta": (139, 0, 139),
    "DarkOrange": (255, 140, 0),
    "DarkRed": (139, 0, 0),
    "DarkSlateBlue": (72, 61, 139),
    "DarkViolet": (148, 0, 211),
    "DeepPink": (255, 20, 147),
    "DeepSkyBlue": (0, 191, 255),
    "DimGray": (105, 105, 105),
    "DodgerBlue": (30, 144, 255),
    "FireBrick": (178, 34, 34),
    "ForestGreen": (34, 139, 34),
    "Fuchsia": (255, 0, 255),
    "Gold": (255, 215, 0),
    "GoldenRod": (218, 165, 32),
    "Gray": (128, 128, 128),
    "Green": (0, 128, 0),
    "GreenYellow": (173, 255, 47),
    "HotPink": (255, 105, 180),
    "Indigo": (75, 0, 130),
    "Ivory": (255, 255, 240),
    "Khaki": (240, 230, 140),
    "LawnGreen": (124, 252, 0),
    "LightBlue": (173, 216, 230),
    "LightCoral": (240, 128, 128),
    "LightCyan": (224, 255, 255),
    "LightGray": (211, 211, 211),
    "LightGreen": (144, 238, 144),
    "LightPink": (255, 182, 193),
    "LightSkyBlue": (135, 206, 250),
    "Lime": (0, 255, 0),
    "LimeGreen": (50, 205, 50),
    "Magenta": (255, 0, 255),
    "Maroon": (128, 0, 0),
    "MediumBlue": (0, 0, 205),
    "MediumOrchid": (186, 85, 211),
    "MediumPurple": (147, 112, 219),
    "MediumSeaGreen": (60, 179, 113),
    "MediumSlateBlue": (123, 104, 238),
    "MediumSpringGreen": (0, 250, 154),
    "MediumTurquoise": (72, 209, 204),
    "MidnightBlue": (25, 25, 112),
    "MistyRose": (255, 228, 225),
    "Moccasin": (255, 228, 181),
    "Navy": (0, 0, 128),
    "Olive": (128, 128, 0),
    "OliveDrab": (107, 142, 35),
    "Orange": (255, 165, 0),
    "OrangeRed": (255, 69, 0),
    "Orchid": (218, 112, 214),
    "PaleGreen": (152, 251, 152),
    "PaleTurquoise": (175, 238, 238),
    "PaleVioletRed": (219, 112, 147),
    "Peru": (205, 133, 63),
    "Pink": (255, 192, 203),
    "Plum": (221, 160, 221),
    "PowderBlue": (176, 224, 230),
    "Purple": (128, 0, 128),
    "Red": (255, 0, 0),
    "RoyalBlue": (65, 105, 225),
    "SaddleBrown": (139, 69, 19),
    "Salmon": (250, 128, 114),
    "SandyBrown": (244, 164, 96),
    "SeaGreen": (46, 139, 87),
    "Silver": (192, 192, 192),
    "SkyBlue": (135, 206, 235),
    "SlateBlue": (106, 90, 205),
    "SlateGray": (112, 128, 144),
    "Snow": (255, 250, 250),
    "SpringGreen": (0, 255, 127),
    "SteelBlue": (70, 130, 180),
    "Tan": (210, 180, 140),
    "Teal": (0, 128, 128),
    "Thistle": (216, 191, 216),
    "Tomato": (255, 99, 71),
    "Turquoise": (64, 224, 208),
    "Violet": (238, 130, 238),
    "Wheat": (245, 222, 179),
    "White": (255, 255, 255),
    "WhiteSmoke": (245, 245, 245),
    "Yellow": (255, 255, 0),
    "YellowGreen": (154, 205, 50),
}

# Spoolman direction values → human-readable type labels
_TYPE_VOCAB: dict[str, str] = {
    "coaxial": "coextruded",
    "longitudinal": "gradient",
}


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int] | None:
    h = hex_str.lstrip("#").lower()
    if len(h) == 3:
        h = h[0] * 2 + h[1] * 2 + h[2] * 2
    if len(h) != 6:
        return None
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return None


def nearest_color_name(hex_str: str) -> str:
    """Return the nearest named color for a hex string (Euclidean RGB distance)."""
    rgb = _hex_to_rgb(hex_str)
    if rgb is None:
        return hex_str.lstrip("#").lower()
    r, g, b = rgb
    best_name = hex_str
    best_dist = float("inf")
    for name, (pr, pg, pb) in _PALETTE.items():
        dist = math.sqrt((r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2)
        if dist < best_dist:
            best_dist = dist
            best_name = name
    return best_name


def project_colorname(
    color_hex: str | None,
    multi_color_hexes: str | None,
    multi_color_direction: str | None,
    fmt: str = "name",
) -> str | None:
    """Build the FDB colorName projection from Spoolman multicolor fields.

    Returns None for single-color filaments (multi_color_hexes absent/empty)
    so callers leave colorName untouched.

    The primary color_hex is already written to FDB's ``color`` field; this
    projection is derived from ``multi_color_hexes`` only.

    Args:
        color_hex: Primary Spoolman hex (unused in projection; kept for API symmetry).
        multi_color_hexes: Comma-separated hex values from Spoolman API.
        multi_color_direction: "coaxial" | "longitudinal" | None.
        fmt: "name" (fuzzy nearest-named-color) or "hex" (raw lowercase hex values).
    """
    if not multi_color_hexes:
        return None
    hexes = [h.strip() for h in multi_color_hexes.split(",") if h.strip()]
    if not hexes:
        return None

    direction_label = _TYPE_VOCAB.get(multi_color_direction or "", multi_color_direction or "") if multi_color_direction else ""

    if fmt == "hex":
        colors_str = "/".join(h.lstrip("#").lower() for h in hexes)
    else:
        colors_str = "/".join(nearest_color_name(h) for h in hexes)

    if direction_label:
        return f"{colors_str} ({direction_label})"
    return colors_str
