"""Local cache for the last computed OpenTag *match* result.

The OpenTag match computation is pure-CPU but expensive (scoring every Spoolman
filament against the brand-gated slice of the ~11k-entry OpenPrintTag dataset).
Recomputing it on every page visit is wasteful and — before the event-loop
offload landed — blocked the whole bridge.  This module persists the last
``OpenTagMatchesResponse`` payload to a JSON file in ``DATA_DIR`` (mirroring the
``opentag_cache.py`` dataset-cache pattern) so ``GET /api/openprinttag/matches``
can return it instantly and recompute only on an explicit refresh.

Cache file shape (``opentag_matches_cache.json``)::

    {
        "computed_at": "2026-06-18T12:00:00+00:00",
        "fingerprint": {
            "dataset": "1234:2026-06-18T11:00:00+00:00",  # count:fetched_at
            "sm_count": 87,
            "config_hash": "<sha1 hex>"
        },
        "response": { ...OpenTagMatchesResponse dict... }
    }

Fingerprint notes
-----------------
* ``dataset`` is ``count:fetched_at`` — a content proxy.  When the sibling
  smart-dataset-refresh work lands a stable commit-SHA identity, swap that in;
  until then count+timestamp is the documented fallback.
* ``config_hash`` covers the vendor-alias CSV, the material-tag map, and the
  openprinttag extra-field names — anything that changes how a match is computed
  or where its identity is written.
* ``sm_count`` is the Spoolman filament count — a cheap proxy for "your
  inventory changed since the last match".

When any fingerprint component differs from the live inputs the cache is still
served (so the page is instant) but ``stale_inputs`` is set so the UI can prompt
for a Refresh.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CACHE_FILENAME = "opentag_matches_cache.json"


def dataset_fingerprint(count: int, fetched_at: str | None) -> str:
    """Return a content proxy for the dataset identity (``count:fetched_at``).

    Documented fallback until a stable dataset commit-SHA is available from the
    smart-dataset-refresh work.
    """
    return f"{count}:{fetched_at or ''}"


def config_fingerprint(
    aliases_raw: str,
    tag_map: dict[str, int],
    field_names: dict[str, str],
) -> str:
    """Hash the match-affecting configuration into a stable hex digest.

    Covers the vendor-alias CSV, the material-tag keyword→id map, and the
    openprinttag extra-field names.  Order-independent for the dicts (sorted).
    """
    h = hashlib.sha1()
    h.update(b"aliases\x00")
    h.update((aliases_raw or "").encode("utf-8"))
    h.update(b"\x00tags\x00")
    for k in sorted(tag_map):
        h.update(f"{k}={tag_map[k]};".encode("utf-8"))
    h.update(b"\x00fields\x00")
    for k in sorted(field_names):
        h.update(f"{k}={field_names[k]};".encode("utf-8"))
    return h.hexdigest()


def build_fingerprint(
    *,
    dataset_count: int,
    dataset_fetched_at: str | None,
    sm_count: int,
    aliases_raw: str,
    tag_map: dict[str, int],
    field_names: dict[str, str],
) -> dict[str, Any]:
    """Assemble the full fingerprint dict for the current inputs."""
    return {
        "dataset": dataset_fingerprint(dataset_count, dataset_fetched_at),
        "sm_count": sm_count,
        "config_hash": config_fingerprint(aliases_raw, tag_map, field_names),
    }


def load_match_cache(data_dir: str) -> dict[str, Any] | None:
    """Load the raw match-cache dict from disk; None if absent/corrupt."""
    path = Path(data_dir) / _CACHE_FILENAME
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        logger.warning("opentag_match_cache: failed to read %s: %s", path, exc)
        return None
    if not isinstance(data, dict) or "response" not in data:
        return None
    return data


def save_match_cache(
    data_dir: str,
    response: dict[str, Any],
    computed_at: str,
    fingerprint: dict[str, Any],
) -> None:
    """Persist the computed match response + fingerprint to disk (best-effort)."""
    path = Path(data_dir) / _CACHE_FILENAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(
                {
                    "computed_at": computed_at,
                    "fingerprint": fingerprint,
                    "response": response,
                },
                fh,
            )
        logger.info("opentag_match_cache: saved match result to %s", path)
    except Exception:  # pragma: no cover - best-effort persistence
        logger.warning("opentag_match_cache: failed to write %s", path, exc_info=True)


def inputs_stale(cached_fingerprint: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    """True when any cached fingerprint component differs from the current inputs."""
    if not cached_fingerprint:
        return True
    return (
        cached_fingerprint.get("dataset") != current.get("dataset")
        or cached_fingerprint.get("sm_count") != current.get("sm_count")
        or cached_fingerprint.get("config_hash") != current.get("config_hash")
    )
