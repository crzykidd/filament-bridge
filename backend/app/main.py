"""filament-bridge FastAPI application.

Startup sequence:
  1. Config is validated at import time (app/config.py raises SystemExit on missing vars)
  2. Lifespan runs Alembic migrations and seeds default BridgeConfig rows
  3. Lifespan opens async HTTP clients for both upstream APIs
  4. ensure_extra_fields() creates the Spoolman cross-ref spool fields and the filament
     fields (filamentdb_material_tags, openprinttag_slug, openprinttag_uuid) if absent
  5. APScheduler registers an interval job (SYNC_INTERVAL_SECONDS) that reads
     auto_sync_enabled from BridgeConfig each tick — if false it is a no-op
  6. Health endpoint is available immediately at GET /api/health

Phase 4: /static is mounted when the directory exists (built image only)
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
from app.api import backup as backup_router
from app.api import config as config_router
from app.api import conflicts as conflicts_router
from app.api import debug as debug_router
from app.api import health as health_router
from app.api import mappings as mappings_router
from app.api import opentag as opentag_router
from app.api import sync as sync_router
from app.api import sync_log as sync_log_router
from app.api import wizard as wizard_router
from app.config import settings
from app.core.engine import run_sync_cycle
from app.db import SessionLocal
from app.api.config import get_config_value, prune_sync_log, set_config_value
from app.models.config import BridgeConfig, seed_defaults
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


def _migrate_sync_config(db) -> None:
    """One-time idempotent migration: derive new two-axis keys from old SoT keys.

    Maps old source-of-truth → one-way direction with manual conflict policy,
    preserving today's effective behavior post-deploy. Skips keys already present.
    Called once at startup after seed_defaults().
    """
    # Weight
    if get_config_value(db, "weight_sync_direction") is None:
        old_sot = get_config_value(db, "weight_source_of_truth", "spoolman")
        direction = "spoolman_to_filamentdb" if old_sot == "spoolman" else "filamentdb_to_spoolman"
        set_config_value(db, "weight_sync_direction", direction)
    if get_config_value(db, "weight_conflict_policy") is None:
        set_config_value(db, "weight_conflict_policy", "manual")

    # Material properties
    if get_config_value(db, "material_properties_sync_direction") is None:
        old_sot = get_config_value(db, "material_properties_source_of_truth", "filamentdb")
        direction = "spoolman_to_filamentdb" if old_sot == "spoolman" else "filamentdb_to_spoolman"
        set_config_value(db, "material_properties_sync_direction", direction)
    if get_config_value(db, "material_properties_conflict_policy") is None:
        set_config_value(db, "material_properties_conflict_policy", "manual")

    # New spool creation direction — old new_spool_source_of_truth was unenforced
    # (bidirectional in practice), so two_way preserves current behavior exactly.
    if get_config_value(db, "new_spool_sync_direction") is None:
        set_config_value(db, "new_spool_sync_direction", "two_way")

    db.commit()


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
        _migrate_sync_config(db)
        logger.info("BridgeConfig defaults seeded and sync config migrated")
    finally:
        db.close()

    app.state.spoolman = SpoolmanClient(settings.spoolman_url)
    app.state.filamentdb = FilamentDBClient(settings.filamentdb_url)

    async with app.state.spoolman, app.state.filamentdb:
        # Ensure Spoolman cross-ref extra fields exist (created once on startup)
        try:
            await app.state.spoolman.ensure_extra_fields()
        except Exception as exc:
            logger.warning("Could not ensure Spoolman extra fields: %s", exc)

        async def _sync_job() -> None:
            db = SessionLocal()
            try:
                row = db.query(BridgeConfig).filter_by(key="auto_sync_enabled").first()
                enabled = json.loads(row.value) if row else False
                if not enabled:
                    logger.debug("Auto-sync disabled — skipping cycle")
                    return
                # Prune old sync-log rows before each auto-sync tick.
                retention_row = db.query(BridgeConfig).filter_by(key="sync_log_retention_days").first()
                retention_days = int(json.loads(retention_row.value)) if retention_row else 30
                if retention_days > 0:
                    pruned = prune_sync_log(db, retention_days)
                    if pruned:
                        db.commit()
                await run_sync_cycle(db, app.state.spoolman, app.state.filamentdb, dry_run=False)
            except Exception as exc:
                logger.error("Unhandled error in sync job: %s", exc, exc_info=True)
            finally:
                db.close()

        # Determine the effective interval: DB override takes precedence over env default.
        from app.api.config import _effective_sync_interval
        db_for_interval = SessionLocal()
        try:
            initial_interval = _effective_sync_interval(db_for_interval)
        finally:
            db_for_interval.close()

        _scheduler.add_job(
            _sync_job,
            "interval",
            seconds=initial_interval,
            id="sync_cycle",
        )
        _scheduler.start()
        # Store scheduler on app.state so the config endpoint can reschedule it.
        app.state.scheduler = _scheduler
        logger.info(
            "Scheduler started — interval=%ds, auto-sync gated by BridgeConfig.auto_sync_enabled",
            initial_interval,
        )
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
app.include_router(sync_router.router, prefix="/api")
app.include_router(conflicts_router.router, prefix="/api")
app.include_router(mappings_router.router, prefix="/api")
app.include_router(config_router.router, prefix="/api")
app.include_router(wizard_router.router, prefix="/api")
app.include_router(opentag_router.router, prefix="/api")
app.include_router(backup_router.router, prefix="/api")
app.include_router(sync_log_router.router, prefix="/api")
app.include_router(debug_router.router, prefix="/api")

# Serve the React SPA from /static when the directory exists (built image only).
# Guarded so `pytest` and `uvicorn --reload` work without a frontend build.
_static_dir = Path(__file__).parent.parent.parent / "static"
if _static_dir.is_dir():
    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    _index = _static_dir / "index.html"
    _assets_dir = _static_dir / "assets"
    if _assets_dir.is_dir():
        # Hashed, immutable bundles are served directly.
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")

    # Everything else falls back to index.html so client-side (BrowserRouter)
    # routes survive a hard refresh / direct load / shared deep link. Registered
    # after the /api routers, so the API always wins; unknown /api paths still 404
    # as JSON rather than silently returning the SPA shell.
    @app.get("/{full_path:path}", include_in_schema=False)
    async def _spa_fallback(full_path: str) -> FileResponse:
        if full_path.startswith("api"):
            raise HTTPException(status_code=404)
        candidate = _static_dir / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_index)
