"""Synthetic master / container-parent detection for Filament DB filaments.

In ``generic_container`` variant-parent mode the bridge synthesises colorless
"container" / master parent filaments in Filament DB (one per cluster). They have
no Spoolman counterpart and never participate in sync, so most count/UI surfaces
must treat them separately from real filaments.

This is the single canonical detector — callers pass whichever signals they have:
  - ``synthetic_ids`` (authoritative): the set of ``FilamentMapping.filamentdb_id``
    where ``is_synthetic_parent=True``. Only available where a DB session is in hand.
  - ``hasVariants``: an FDB-observable signal (a parent with color children).
  - the configured container marker name suffix (e.g. ``" (Master)"``).
"""

from __future__ import annotations

from typing import Any


def is_master_fdb(
    fil: Any,
    marker: str | None = None,
    synthetic_ids: set[str] | None = None,
) -> bool:
    """Return True if ``fil`` (an FDBFilament) is a synthetic master/container parent.

    Detection is the union of the available signals (any one is sufficient):
    bridge-created synthetic parent, ``hasVariants``, or a name ending with the
    configured container marker. A purely FDB-observable call (``synthetic_ids``
    omitted) still catches every synthetic parent, since containers always carry
    ``hasVariants`` and/or the marker suffix.
    """
    if synthetic_ids and getattr(fil, "id", None) in synthetic_ids:
        return True
    if getattr(fil, "hasVariants", False):
        return True
    name = getattr(fil, "name", None)
    if marker and name and name.endswith(f" {marker}"):
        return True
    return False
