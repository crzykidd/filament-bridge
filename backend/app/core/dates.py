"""Date helpers for translating Spoolman timestamps to Filament DB date fields.

Filament DB's spool ``purchaseDate`` / ``openedDate`` are date-only (OpenAPI
``format: date``), whereas Spoolman ``registered`` / ``first_used`` are full ISO
datetimes. These helpers carry a spool's "age" across when the bridge creates a
spool in Filament DB so users don't lose provenance moving from Spoolman.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def to_date_only(value: str | None) -> str | None:
    """Convert a Spoolman ISO datetime string to a ``YYYY-MM-DD`` date for Filament DB.

    Returns ``None`` for falsy input. Tolerates a trailing ``Z`` (which
    ``datetime.fromisoformat`` rejects before Python 3.11) and falls back to the
    leading 10 characters when the value isn't fully parseable but looks date-like.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except (ValueError, TypeError, AttributeError):
        return value[:10] if isinstance(value, str) and len(value) >= 10 else None


def spool_provenance_dates(sm_spool: Any) -> dict[str, str]:
    """Map a Spoolman spool's age fields to Filament DB spool date fields.

    - ``registered`` → ``purchaseDate`` (date the spool entered inventory ≈ purchase)
    - ``first_used`` → ``openedDate``   (date the spool was first used)

    Only includes a key when its source value is present and parseable. Intended to
    be merged into the spool-creation payload so the "age" of a roll is preserved
    when it moves into Filament DB.
    """
    out: dict[str, str] = {}
    purchase = to_date_only(getattr(sm_spool, "registered", None))
    if purchase:
        out["purchaseDate"] = purchase
    opened = to_date_only(getattr(sm_spool, "first_used", None))
    if opened:
        out["openedDate"] = opened
    return out
