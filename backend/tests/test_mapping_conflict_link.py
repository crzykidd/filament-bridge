"""Regression: Synced Records rows are spool-keyed, but `new_filament` conflicts store a
*filament* id in `spoolman_id`. Filament-ids and spool-ids are separate id-spaces, so a
synced spool whose id numerically collides with a conflicted filament id must NOT be flagged
as a conflict, and "Resolve" must NOT jump to that unrelated filament conflict.
"""

from app.api.mappings import build_mapping_rows
from app.models.conflict import Conflict
from app.models.mapping import SpoolMapping


def _row(rows, spool_id):
    return next((r for r in rows if r.spoolman_spool_id == spool_id), None)


def test_spool_row_ignores_colliding_filament_conflict(db):
    # spool #5 is synced/mapped
    db.add(SpoolMapping(
        spoolman_spool_id=5,
        filamentdb_filament_id="aaaaaaaaaaaaaaaaaaaaaaa0",
        filamentdb_spool_id="aaaaaaaaaaaaaaaaaaaaaaa1",
    ))
    # a new_filament conflict for FILAMENT 5 (entity_type="filament") — numeric collision
    db.add(Conflict(
        conflict_type="new_filament", field_name="new_filament",
        entity_type="filament", spoolman_id=5,
        spoolman_value='{"vendor": "Acme", "name": "Filament Five"}',
    ))
    db.commit()

    row = _row(build_mapping_rows(db), 5)
    assert row is not None
    assert row.status != "conflict", "a filament conflict must not flag the spool row"
    assert row.conflict_id is None, "spool row must not link to a filament conflict"


def test_spool_row_still_links_real_spool_conflict(db):
    db.add(SpoolMapping(
        spoolman_spool_id=7,
        filamentdb_filament_id="bbbbbbbbbbbbbbbbbbbbbbb0",
        filamentdb_spool_id="bbbbbbbbbbbbbbbbbbbbbbb1",
    ))
    c = Conflict(
        conflict_type="cross_system", field_name="weight",
        entity_type="spool", spoolman_id=7,
    )
    db.add(c)
    db.commit()

    row = _row(build_mapping_rows(db), 7)
    assert row is not None
    assert row.status == "conflict"
    assert row.conflict_id == c.id
