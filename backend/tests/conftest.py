"""Shared test fixtures for the filament-bridge test suite."""

import os
import tempfile

# app.config validates required env vars at import time (and app.db creates a
# data dir). Set self-contained defaults BEFORE importing any app module so the
# whole suite runs with a bare `cd backend && pytest`.
os.environ.setdefault("FILAMENTDB_URL", "http://filamentdb.test")
os.environ.setdefault("SPOOLMAN_URL", "http://spoolman.test")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="filament-bridge-test-"))

# Prevent real HTTP calls to api.github.com during tests.  Every test that needs
# secondary-color recovery mocks fetch_secondary_colors explicitly; all others
# get an empty map so load_opentag_dataset stays fast and side-effect-free.
from unittest.mock import AsyncMock, patch as _patch  # noqa: E402

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.config import seed_defaults
from app.models.conflict import Conflict  # noqa: F401  ensure table is created
from app.models.mapping import FilamentMapping, SpoolMapping  # noqa: F401
from app.models.snapshot import Snapshot  # noqa: F401
from app.models.sync_log import SyncLog  # noqa: F401


@pytest.fixture(autouse=True)
def _no_github_tarball_fetch():
    """Stub out fetch_secondary_colors for every test.

    Tests that explicitly need the secondary-color merge behavior patch
    ``app.core.opentag_cache.fetch_secondary_colors`` themselves; all other tests
    get an empty map so ``load_opentag_dataset`` stays fast and makes no real
    network calls to api.github.com.
    """
    with _patch(
        "app.core.opentag_cache.fetch_secondary_colors",
        new=AsyncMock(return_value={}),
    ):
        yield


@pytest.fixture()
def db() -> Session:
    """In-memory SQLite session with all bridge tables created and defaults seeded."""
    # StaticPool shares ONE in-memory connection across threads — required because
    # FastAPI's TestClient runs sync route handlers in a worker thread, which would
    # otherwise get its own (empty) :memory: database.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    seed_defaults(session)
    yield session
    session.close()
