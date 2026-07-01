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
            "dataset": "abc123…",  # upstream commit SHA (falls back to count:fetched_at)
            "sm_content_hash": "<sha256 hex>",
            "config_hash": "<sha256 hex>"
        },
        "response": { ...OpenTagMatchesResponse dict... }
    }

Fingerprint notes
-----------------
* ``dataset`` is the upstream OpenPrintTag commit SHA — a stable content identity
  that changes only when the dataset actually changes.  When the SHA is unknown
  (pre-SHA cache, or a download whose SHA check failed) it falls back to the
  ``count:fetched_at`` proxy so the fingerprint is always populated.
* ``config_hash`` covers the vendor-alias CSV, the material-tag map, and the
  openprinttag extra-field names — anything that changes how a match is computed
  or where its identity is written.
* ``sm_content_hash`` is a SHA-256 hash of the Spoolman filament set (vendor
  name + filament name + material type per filament, sorted, order-independent).
  A vendor rename — same count but different name — produces a different hash
  and flips ``stale_inputs``, catching edits the old ``sm_count`` proxy missed.
  Existing caches lacking this key read as stale on first load post-upgrade and
  re-match on demand.

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


def dataset_fingerprint(
    count: int, fetched_at: str | None, commit_sha: str | None = None
) -> str:
    """Return a stable identity for the dataset.

    Prefers the upstream commit SHA (changes only on a real dataset change); falls
    back to the ``count:fetched_at`` proxy when the SHA is unknown (pre-SHA cache or
    a download whose SHA check failed).
    """
    if commit_sha:
        return f"sha:{commit_sha}"
    return f"{count}:{fetched_at or ''}"


def config_fingerprint(
    aliases_raw: str,
    tag_map: dict[str, int],
    field_names: dict[str, str],
) -> str:
    """Hash the match-affecting configuration into a stable hex digest.

    Covers the vendor-alias CSV, the material-tag keyword→id map, and the
    openprinttag extra-field names.  Order-independent for the dicts (sorted).

    SHA-256 (not for security — this is a cache-invalidation fingerprint of
    non-sensitive config; SHA-256 just keeps static analysis happy).
    """
    h = hashlib.sha256()
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
    sm_content_hash: str,
    aliases_raw: str,
    tag_map: dict[str, int],
    field_names: dict[str, str],
    dataset_commit_sha: str | None = None,
) -> dict[str, Any]:
    """Assemble the full fingerprint dict for the current inputs."""
    return {
        "dataset": dataset_fingerprint(
            dataset_count, dataset_fetched_at, dataset_commit_sha
        ),
        "sm_content_hash": sm_content_hash,
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
        or cached_fingerprint.get("sm_content_hash") != current.get("sm_content_hash")
        or cached_fingerprint.get("config_hash") != current.get("config_hash")
    )
