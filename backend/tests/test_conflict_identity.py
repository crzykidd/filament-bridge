"""Tests for _conflict_identity including multi_color_hexes / multi_color_direction.

Verifies:
- multi_color_hexes + multi_color_direction are included from the spool snapshot
  filament data (present when set, None when absent).
- ConflictResponse schema includes both new fields and they round-trip correctly.
"""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.config import seed_defaults
from app.models.conflict import Conflict
from app.models.snapshot import Snapshot
from app.api.conflicts import _conflict_identity, _to_response
from app.schemas.api import ConflictResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    seed_defaults(session)
    return session


def _add_spool_snapshot(db, spool_id: int, filament_data: dict):
    """Insert a Spoolman spool snapshot whose nested filament carries filament_data."""
    snap = {"filament": filament_data}
    db.add(
        Snapshot(
            source="spoolman",
            entity_type="spool",
            entity_id=str(spool_id),
            data=json.dumps(snap),
        )
    )
    db.flush()


def _make_conflict(db, spoolman_id: int = 1) -> Conflict:
    c = Conflict(
        entity_type="spool",
        field_name="weight",
        spoolman_id=spoolman_id,
        filamentdb_filament_id="fil-1",
        filamentdb_spool_id="spool-1",
        spoolman_value=json.dumps(800.0),
        filamentdb_value=json.dumps(900.0),
    )
    db.add(c)
    db.flush()
    return c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_conflict_identity_includes_multi_color_hexes_and_direction():
    """When the snapshot filament has multi_color_hexes + multi_color_direction,
    _conflict_identity returns them."""
    db = _make_db()
    c = _make_conflict(db, spoolman_id=1)
    _add_spool_snapshot(db, 1, {
        "name": "PLA Silk Rainbow",
        "vendor": {"name": "ELEGOO"},
        "color_hex": None,
        "multi_color_hexes": "FF0000,00FF00,0000FF",
        "multi_color_direction": "longitudinal",
        "material": "PLA",
    })

    identity = _conflict_identity(db, c)

    assert identity["multi_color_hexes"] == "FF0000,00FF00,0000FF"
    assert identity["multi_color_direction"] == "longitudinal"
    assert identity["color_hex"] is None
    assert identity["label"] == "ELEGOO PLA Silk Rainbow"


def test_conflict_identity_multi_color_none_when_absent():
    """When the snapshot filament has no multicolor fields, they come back None."""
    db = _make_db()
    c = _make_conflict(db, spoolman_id=2)
    _add_spool_snapshot(db, 2, {
        "name": "PLA",
        "vendor": {"name": "Bambu"},
        "color_hex": "FF5733",
        "material": "PLA",
    })

    identity = _conflict_identity(db, c)

    assert identity["multi_color_hexes"] is None
    assert identity["multi_color_direction"] is None
    assert identity["color_hex"] == "FF5733"


def test_conflict_identity_coaxial_direction():
    """multi_color_direction='coaxial' is preserved as-is."""
    db = _make_db()
    c = _make_conflict(db, spoolman_id=3)
    _add_spool_snapshot(db, 3, {
        "name": "Dual Color PLA",
        "vendor": {"name": "Polymaker"},
        "multi_color_hexes": "AABBCC,DDEEFF",
        "multi_color_direction": "coaxial",
        "material": "PLA",
    })

    identity = _conflict_identity(db, c)

    assert identity["multi_color_direction"] == "coaxial"
    assert identity["multi_color_hexes"] == "AABBCC,DDEEFF"


def test_to_response_includes_multi_color_fields_in_schema():
    """_to_response returns a ConflictResponse that carries multi_color_hexes
    and multi_color_direction fields (schema round-trip)."""
    db = _make_db()
    c = _make_conflict(db, spoolman_id=4)
    _add_spool_snapshot(db, 4, {
        "name": "Silk Rainbow",
        "vendor": {"name": "Bambu"},
        "multi_color_hexes": "FF0000,FFFF00",
        "multi_color_direction": "longitudinal",
        "material": "PLA",
    })

    response = _to_response(c, db)

    assert isinstance(response, ConflictResponse)
    assert response.multi_color_hexes == "FF0000,FFFF00"
    assert response.multi_color_direction == "longitudinal"
    # Verify the Pydantic model has these as proper declared fields (not extras)
    assert "multi_color_hexes" in ConflictResponse.model_fields
    assert "multi_color_direction" in ConflictResponse.model_fields


def test_to_response_multi_color_none_when_absent():
    """_to_response returns None for multi_color fields when snapshot lacks them."""
    db = _make_db()
    c = _make_conflict(db, spoolman_id=5)
    _add_spool_snapshot(db, 5, {
        "name": "Standard PLA",
        "vendor": {"name": "SUNLU"},
        "color_hex": "FFFFFF",
        "material": "PLA",
    })

    response = _to_response(c, db)

    assert response.multi_color_hexes is None
    assert response.multi_color_direction is None
    assert response.color_hex == "FFFFFF"


def test_conflict_response_schema_has_multi_color_fields():
    """ConflictResponse Pydantic model declares both new fields with None defaults."""
    fields = ConflictResponse.model_fields
    assert "multi_color_hexes" in fields
    assert "multi_color_direction" in fields
    # Both default to None
    assert fields["multi_color_hexes"].default is None
    assert fields["multi_color_direction"].default is None
