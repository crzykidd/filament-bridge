"""Shared test fixtures for the filament-bridge test suite."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models.config import BridgeConfig, seed_defaults
from app.models.conflict import Conflict  # noqa: F401  ensure table is created
from app.models.mapping import FilamentMapping, SpoolMapping  # noqa: F401
from app.models.snapshot import Snapshot  # noqa: F401
from app.models.sync_log import SyncLog  # noqa: F401


@pytest.fixture()
def db() -> Session:
    """In-memory SQLite session with all bridge tables created and defaults seeded."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    seed_defaults(session)
    yield session
    session.close()
