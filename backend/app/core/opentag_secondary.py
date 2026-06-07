"""Recover ``secondary_colors`` from the OpenPrintTag raw GitHub tarball.

FDB's ``/api/openprinttag`` feed leaves ``secondaryColors`` EMPTY on all records
because FDB's parser reads flat ``secondary_color_0..4`` keys while the OpenTag
YAML schema stores them in a ``secondary_colors`` ARRAY.

This module fetches the raw tarball directly from GitHub, parses each
``data/materials/**/*.yaml`` for ``uuid`` + ``secondary_colors[].color_rgba``,
and returns a lookup map ``{ uuid: [hexes], ... }`` (and by ``slug`` as a fallback).

Usage::

    secondary_map = await fetch_secondary_colors()
    # secondary_map["ccf32809-fbef-527a-8487-ccb75ceafab6"] == ["000000", "98282F", "DDB95D"]

Pass an optional ``http`` argument (``httpx.AsyncClient``) for testing — the client must
support absolute URLs (no ``base_url``).  When ``http`` is ``None``, a fresh client is
created and closed internally.
"""

from __future__ import annotations

import io
import logging
import tarfile
from typing import Any

import httpx
import yaml

logger = logging.getLogger(__name__)

_TARBALL_URL = (
    "https://api.github.com/repos/OpenPrintTag/openprinttag-database/tarball/main"
)
_FETCH_TIMEOUT = httpx.Timeout(120.0)


def _rgba_to_hex(rgba: str | None) -> str | None:
    """Convert ``#RRGGBBAA`` (or ``#RRGGBB``) to bare uppercase ``RRGGBB``.

    Strips the leading ``#``, drops the trailing alpha pair if present, upper-cases.
    Returns ``None`` for falsy or too-short input.

    Examples::

        _rgba_to_hex('#000000ff') -> '000000'
        _rgba_to_hex('#98282fff') -> '98282F'
        _rgba_to_hex('#ddb95dff') -> 'DDB95D'
        _rgba_to_hex('#AABBCC')   -> 'AABBCC'
    """
    if not rgba:
        return None
    stripped = rgba.lstrip("#")
    if len(stripped) < 6:
        return None
    return stripped[:6].upper()


async def fetch_secondary_colors(
    http: httpx.AsyncClient | None = None,
) -> dict[str, list[str]]:
    """Fetch the OpenPrintTag raw tarball and return a map of ``uuid → [hex, ...]``.

    Also builds a ``slug → [hex, ...]`` fallback map, merged into the same dict
    under the slug key so callers can use a single lookup.

    ``http`` must be an ``httpx.AsyncClient`` that supports absolute URLs (no
    ``base_url``).  When ``None``, a fresh client is created and closed internally.

    Errors (network failure, bad tarball, YAML parse errors on individual files)
    are non-fatal: the function logs a warning and returns ``{}`` so the caller
    can degrade gracefully to the FDB feed.
    """
    return await _fetch_secondary_colors_impl(http)


async def _fetch_secondary_colors_impl(
    http: httpx.AsyncClient | None,
) -> dict[str, list[str]]:
    own_client = http is None
    client: httpx.AsyncClient = http if http is not None else httpx.AsyncClient()
    try:
        try:
            resp = await client.get(
                _TARBALL_URL, timeout=_FETCH_TIMEOUT, follow_redirects=True
            )
            resp.raise_for_status()
            raw_bytes = resp.content
        except Exception as exc:
            logger.warning(
                "opentag_secondary: failed to fetch raw tarball from GitHub: %s", exc
            )
            return {}
    finally:
        if own_client:
            await client.aclose()

    result: dict[str, list[str]] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(raw_bytes), mode="r:gz") as tf:
            for member in tf.getmembers():
                name = member.name
                if "/data/materials/" not in name or not name.endswith(".yaml"):
                    continue
                fobj = tf.extractfile(member)
                if fobj is None:
                    continue
                try:
                    doc: Any = yaml.safe_load(fobj.read())
                except Exception as exc:
                    logger.debug(
                        "opentag_secondary: YAML parse error in %s: %s", name, exc
                    )
                    continue
                if not isinstance(doc, dict):
                    continue
                secondary_colors: list[Any] = doc.get("secondary_colors") or []
                if not secondary_colors:
                    continue
                hexes = [
                    h
                    for h in (
                        _rgba_to_hex(c.get("color_rgba") if isinstance(c, dict) else None)
                        for c in secondary_colors
                    )
                    if h
                ]
                if not hexes:
                    continue
                uuid_val: str | None = doc.get("uuid")
                slug_val: str | None = doc.get("slug")
                if uuid_val:
                    result[uuid_val] = hexes
                if slug_val:
                    result[slug_val] = hexes
    except Exception as exc:
        logger.warning(
            "opentag_secondary: failed to parse raw tarball: %s", exc
        )
        return {}

    n = len(result)
    logger.info(
        "opentag_secondary: recovered secondary_colors for %d materials (uuid+slug keys)", n
    )
    return result
