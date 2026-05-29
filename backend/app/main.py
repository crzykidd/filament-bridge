"""filament-bridge FastAPI application.

Startup sequence:
  1. Config is validated at import time (app/config.py raises SystemExit on missing vars)
  2. Lifespan runs Alembic migrations and seeds default BridgeConfig rows
  3. Lifespan opens async HTTP clients for both upstream APIs
  4. APScheduler is started with no jobs (auto-sync is OFF by default; Phase 3 adds the cycle)
  5. Health endpoint is available immediately at GET /api/health

Phase 5 TODO: mount /static for the React SPA
"""

import json
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from app import __version__
from app.api import health as health_router
from app.config import settings
from app.db import SessionLocal
from app.models.config import seed_defaults
from app.services.filamentdb import FilamentDBClient
from app.services.spoolman import SpoolmanClient


# ---------------------------------------------------------------------------
# Structured JSON logging
# ---------------------------------------------------------------------------


class _JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        obj: dict = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            obj["exc"] = self.formatException(record.exc_info)
        return json.dumps(obj)


def _configure_logging() -> None:
    numeric_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JSONFormatter())
    root = logging.getLogger()
    root.setLevel(numeric_level)
    root.handlers = [handler]
    # Suppress noisy low-level HTTP wire logs unless debug is explicitly requested
    if numeric_level > logging.DEBUG:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Application lifecycle
# ---------------------------------------------------------------------------

_scheduler = AsyncIOScheduler()


def _run_migrations() -> None:
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(Path(__file__).parent.parent / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{settings.data_dir}/bridge.db")
    alembic_command.upgrade(cfg, "head")


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    _configure_logging()
    logger = logging.getLogger(__name__)
    logger.info("filament-bridge %s starting", __version__)

    _run_migrations()
    logger.info("Database migrations applied — %s/bridge.db", settings.data_dir)

    db = SessionLocal()
    try:
        seed_defaults(db)
        logger.info("BridgeConfig defaults seeded")
    finally:
        db.close()

    app.state.spoolman = SpoolmanClient(settings.spoolman_url)
    app.state.filamentdb = FilamentDBClient(settings.filamentdb_url)

    async with app.state.spoolman, app.state.filamentdb:
        _scheduler.start()
        logger.info("Scheduler started — auto-sync disabled, no jobs scheduled")
        try:
            yield
        finally:
            _scheduler.shutdown(wait=False)
            logger.info("filament-bridge stopped")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="filament-bridge",
    version=__version__,
    description="Bidirectional sync service between Filament DB and Spoolman",
    lifespan=_lifespan,
)

app.include_router(health_router.router, prefix="/api")

# TODO Phase 5: mount React SPA static assets
# from fastapi.staticfiles import StaticFiles
# app.mount("/", StaticFiles(directory="static", html=True), name="static")
