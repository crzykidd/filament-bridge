"""Root-cause guard for Spoolman filament-id reuse.

Spoolman stores filaments with a plain SQLite integer PK (no AUTOINCREMENT), so a
deleted top id is reissued on the next create. If the bridge keeps a FilamentMapping
after its Spoolman filament is deleted (e.g. a manual orphan-cleanup), that row can
later be silently re-pointed at an unrelated filament that reuses the freed id. The
sync cycle now drops such mappings the cycle their Spoolman filament disappears.
"""

from __future__ import annotations

from app.core.engine import _purge_stale_filament_mappings
from app.models.mapping import FilamentMapping, SpoolMapping
from app.models.snapshot import Snapshot


def _live(*ids: int) -> dict[int, object]:
    """A live-Spoolman-filaments lookup keyed by id (values unused by the GC)."""
    return {i: object() for i in ids}


def test_purges_mapping_whose_sm_filament_is_gone(db):
    """Spoolman filament deleted → its FilamentMapping (and spool mapping) is purged."""
    fm = FilamentMapping(spoolman_filament_id=179, filamentdb_id="fdbX")
    db.add(fm)
    db.flush()
    db.add(SpoolMapping(spoolman_spool_id=500, filamentdb_filament_id="fdbX",
                        filamentdb_spool_id="s1", filament_mapping_id=fm.id))
    # Snapshots that should be cleaned up with the mapping.
    db.add(Snapshot(source="spoolman", entity_type="filament", entity_id="179", data="{}"))
    db.add(Snapshot(source="filamentdb", entity_type="filament", entity_id="fdbX", data="{}"))
    db.commit()

    fil_maps = db.query(FilamentMapping).all()
    spool_maps = db.query(SpoolMapping).all()

    purged = _purge_stale_filament_mappings(db, "c", _live(1, 2), fil_maps, spool_maps)
    db.flush()

    assert purged == 1
    assert db.query(FilamentMapping).count() == 0
    assert db.query(SpoolMapping).count() == 0  # dependent spool mapping went too
    assert db.query(Snapshot).count() == 0
    # In-place list mutation so the rest of the cycle skips the purged rows.
    assert fil_maps == [] and spool_maps == []


def test_keeps_mapping_whose_sm_filament_is_live(db):
    """A mapping whose Spoolman filament still exists is never touched."""
    fm = FilamentMapping(spoolman_filament_id=42, filamentdb_id="fdbA")
    db.add(fm)
    db.commit()

    fil_maps = db.query(FilamentMapping).all()
    purged = _purge_stale_filament_mappings(db, "c", _live(42), fil_maps, [])

    assert purged == 0
    assert db.query(FilamentMapping).count() == 1
    assert len(fil_maps) == 1


def test_ignores_synthetic_parent_with_null_sm_id(db):
    """Synthetic container parents (spoolman_filament_id=NULL) are never purged."""
    db.add(FilamentMapping(spoolman_filament_id=None, filamentdb_id="master",
                           is_synthetic_parent=True))
    db.commit()

    fil_maps = db.query(FilamentMapping).all()
    purged = _purge_stale_filament_mappings(db, "c", _live(1), fil_maps, [])

    assert purged == 0
    assert db.query(FilamentMapping).count() == 1
