"""Filament DB location resolution (found-or-create).

Filament DB spools reference a location by ``locationId``; Spoolman stores the
location as a free-text string on the spool. To mirror a Spoolman location name
onto an FDB spool we must resolve (or create) the matching FDB location and use
its id.

``ensure_fdb_location`` is the shared helper for that lookup-or-create step. It is
used by the mobile update path and is the extracted form of the inline block the
Bulk Import Wizard uses when seeding spools (``api/wizard.py``).

An optional ``cache`` dict (name → FDB location id) lets a caller resolve many
names in a loop with a single up-front ``get_locations()`` prefetch (the wizard
pattern). When no cache is supplied the helper does its own single fetch.
"""

from __future__ import annotations

from app.services.filamentdb import FilamentDBClient


async def ensure_fdb_location(
    filamentdb: FilamentDBClient,
    name: str,
    cache: dict[str, str] | None = None,
    *,
    dry_run: bool = False,
) -> str | None:
    """Return the FDB location id for ``name``, creating the location if absent.

    Returns ``None`` for an empty/blank ``name`` (nothing to resolve).

    When ``cache`` is provided it is consulted first and updated in place so a
    subsequent call for the same name needs no upstream request. When it is not
    provided the helper fetches the current locations once to look for a match.

    When ``dry_run`` is set and the name is not already known (no cache hit / no
    match among the fetched locations), no location is created — a sentinel id
    (``"dry-run-location"``) is returned instead so a preview never performs the
    upstream write.

    Raises on upstream failure (the caller decides how to degrade).
    """
    if not name or not name.strip():
        return None

    if cache is not None and name in cache:
        return cache[name]

    if cache is None:
        # Build a one-shot lookup for this single resolution.
        cache = {}
        for loc in await filamentdb.get_locations():
            loc_name = loc.get("name")
            loc_id = loc.get("_id")
            if loc_name and loc_id:
                cache[loc_name] = loc_id
        if name in cache:
            return cache[name]

    if dry_run:
        sentinel = "dry-run-location"
        cache[name] = sentinel
        return sentinel

    created = await filamentdb.create_location(name)
    loc_id = created["_id"]
    cache[name] = loc_id
    return loc_id
