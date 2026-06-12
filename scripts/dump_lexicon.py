#!/usr/bin/env python3
"""Dump the mined OpenTag modifier + color lexicons for human review.

Usage (from repo root):
    python scripts/dump_lexicon.py [--cache PATH] [--top-modifiers N] [--top-colors N]
    python -m scripts.dump_lexicon

The script loads the OpenTag dataset from the local cache file and runs
``mine_lexicons_with_counts`` to produce the full lexicon with frequencies.

Dataset source priority:
  1. --cache / --data-dir flag (explicit path to opentag_cache.json or its parent dir)
  2. private_data/filament-bridge/opentag_cache.json  (repo private_data)
  3. private_data/spoolman/opentag_cache.json
  4. /data/opentag_cache.json                          (Docker DATA_DIR)

If none of those are found, the script exits with an error and instructions on
how to populate the cache (e.g. run the bridge and hit /api/openprinttag/refresh).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap: add the backend directory to sys.path so we can import app.*
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


def _find_cache() -> Path | None:
    """Search for a populated opentag_cache.json in the known locations."""
    candidates = [
        _REPO_ROOT / "private_data" / "filament-bridge" / "opentag_cache.json",
        _REPO_ROOT / "private_data" / "spoolman" / "opentag_cache.json",
        Path("/data") / "opentag_cache.json",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _load_materials(cache_path: Path) -> list[dict]:
    with cache_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    mats = data.get("materials", [])
    if not mats or not all(isinstance(m, dict) for m in mats):
        print(f"ERROR: {cache_path} exists but contains no valid material dicts.", file=sys.stderr)
        sys.exit(1)
    return mats


def _fmt_count(n: int) -> str:
    return f"{n:>6}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cache", metavar="PATH",
                        help="Path to opentag_cache.json or its parent directory")
    parser.add_argument("--top-modifiers", type=int, default=100,
                        help="Number of top modifiers to show (default: 100)")
    parser.add_argument("--top-colors", type=int, default=60,
                        help="Number of top colors to show (default: 60)")
    parser.add_argument("--show-bigram-lifts", action="store_true",
                        help="Also print bigram lift diagnostics")
    args = parser.parse_args()

    # Resolve cache path
    cache_path: Path | None = None
    if args.cache:
        p = Path(args.cache)
        if p.is_dir():
            p = p / "opentag_cache.json"
        if not p.exists():
            print(f"ERROR: Cache file not found: {p}", file=sys.stderr)
            sys.exit(1)
        cache_path = p
    else:
        cache_path = _find_cache()

    if cache_path is None:
        print(
            "ERROR: No opentag_cache.json found in standard locations.\n"
            "  Populate it by:\n"
            "    1. Running the bridge (docker compose up) and hitting:\n"
            "       POST http://localhost:8090/api/openprinttag/refresh\n"
            "    2. Or passing --cache /path/to/opentag_cache.json",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Loading dataset from: {cache_path}", file=sys.stderr)
    materials = _load_materials(cache_path)
    print(f"Loaded {len(materials)} materials", file=sys.stderr)

    # Import lexicon module (after path setup)
    from app.core.opentag_lexicon import (  # noqa: PLC0415
        BIGRAM_LIFT_THRESHOLD,
        COLOR_MIN_BRANDS,
        COLOR_MIN_COUNT,
        MODIFIER_MIN_BRANDS,
        MODIFIER_MIN_COUNT,
        mine_lexicons_with_counts,
    )

    print("Mining lexicons...", file=sys.stderr)
    result = mine_lexicons_with_counts(materials)

    modifiers = result["modifiers"]
    colors = result["colors"]
    mod_counts = result["modifier_counts"]
    col_counts = result["color_counts"]

    # ---- Print thresholds ----
    print()
    print("=" * 70)
    print("LEXICON MINING THRESHOLDS")
    print("=" * 70)
    print(f"  MODIFIER_MIN_COUNT   = {MODIFIER_MIN_COUNT}")
    print(f"  MODIFIER_MIN_BRANDS  = {MODIFIER_MIN_BRANDS}")
    print(f"  BIGRAM_LIFT_THRESHOLD= {BIGRAM_LIFT_THRESHOLD}")
    print(f"  COLOR_MIN_COUNT      = {COLOR_MIN_COUNT}")
    print(f"  COLOR_MIN_BRANDS     = {COLOR_MIN_BRANDS}")
    print(f"  Dataset size         = {len(materials)} materials")

    # ---- Print top modifiers ----
    print()
    print("=" * 70)
    print(f"TOP {args.top_modifiers} MINED MODIFIERS  (sorted by frequency desc)")
    print("=" * 70)
    top_mods = sorted(modifiers, key=lambda m: (-mod_counts.get(m, 0), m))
    for i, phrase in enumerate(top_mods[:args.top_modifiers], 1):
        cnt = mod_counts.get(phrase, 0)
        flag = "  [SEED]" if cnt == 0 else ""
        print(f"  {i:>3}. {_fmt_count(cnt)}  {phrase}{flag}")

    # ---- Print all modifiers alphabetical (for completeness check) ----
    print()
    print(f"ALL MODIFIERS ({len(modifiers)} total) — alphabetical")
    print("-" * 70)
    for phrase in sorted(modifiers):
        cnt = mod_counts.get(phrase, 0)
        flag = " [SEED]" if cnt == 0 else ""
        print(f"  {_fmt_count(cnt)}  {phrase}{flag}")

    # ---- Print top colors ----
    print()
    print("=" * 70)
    print(f"TOP {args.top_colors} MINED COLORS  (sorted by frequency desc)")
    print("=" * 70)
    top_cols = sorted(colors, key=lambda c: (-col_counts.get(c, 0), c))
    for i, color in enumerate(top_cols[:args.top_colors], 1):
        cnt = col_counts.get(color, 0)
        flag = "  [SEED]" if cnt == 0 else ""
        print(f"  {i:>3}. {_fmt_count(cnt)}  {color}{flag}")

    # ---- Print all colors alphabetical ----
    print()
    print(f"ALL COLORS ({len(colors)} total) — alphabetical")
    print("-" * 70)
    for color in sorted(colors):
        cnt = col_counts.get(color, 0)
        flag = " [SEED]" if cnt == 0 else ""
        print(f"  {_fmt_count(cnt)}  {color}{flag}")

    # ---- Bigram lift diagnostics ----
    if args.show_bigram_lifts:
        lifts = result.get("_bigram_lift_examples", {})
        if lifts:
            print()
            print("=" * 70)
            print("BIGRAM LIFT DIAGNOSTICS (sample of kept bigrams)")
            print("=" * 70)
            for phrase, info in sorted(lifts.items(), key=lambda x: -x[1].get("lift", 0)):
                print(
                    f"  {phrase!r:30s}  count={info['count']:>5}  "
                    f"expected={info['expected']:>6.1f}  lift={info['lift']:>8.1f}"
                )

    # ---- Summary ----
    print()
    print("=" * 70)
    print(f"SUMMARY: {len(modifiers)} modifiers, {len(colors)} colors")
    print("=" * 70)


if __name__ == "__main__":
    main()
