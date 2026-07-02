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

import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Depends, FastAPI, Request

from app import __version__
from app.api import auth as auth_router
from app.api import backup as backup_router
from app.api import config as config_router
from app.api import conflicts as conflicts_router
from app.api import debug as debug_router
from app.api import health as health_router
from app.api import labels as labels_router
from app.api import version as version_router
from app.api import mappings as mappings_router
from app.api import mobile as mobile_router
from app.api import reconcile as reconcile_router
from app.api import opentag as opentag_router
from app.api import sync as sync_router
from app.api import sync_log as sync_log_router
from app.api import tare as tare_router
from app.api import wizard as wizard_router
from app.api.auth import mobile_auth, require_auth
from app.config import settings
from app.core.engine import run_sync_cycle
from app.db import SessionLocal, get_db
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

    # New-record handling policies — backfill manual_review for existing installs.
    # manual_review is the safe default: no behavior change for users who upgrade
    # (new spools on mapped filaments now queue instead of auto-creating — intended).
    if get_config_value(db, "new_filament_policy") is None:
        set_config_value(db, "new_filament_policy", "manual_review")
    if get_config_value(db, "new_spool_policy") is None:
        set_config_value(db, "new_spool_policy", "manual_review")

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
    app.state.filamentdb = FilamentDBClient(settings.filamentdb_url, settings.filamentdb_api_key)

    # Background task reference held so we can cancel it cleanly on shutdown.
    _dump_task: asyncio.Task | None = None

    async with app.state.spoolman, app.state.filamentdb:
        # Ensure Spoolman cross-ref extra fields exist (created once on startup)
        try:
            await app.state.spoolman.ensure_extra_fields()
        except Exception as exc:
            logger.warning("Could not ensure Spoolman extra fields: %s", exc)

        # Optional debug: write a startup state dump of both upstream systems.
        if settings.debug_startup_dump:
            from app.core.state_dump import write_startup_dump
            _dump_task = asyncio.create_task(
                write_startup_dump(
                    app.state.spoolman,
                    app.state.filamentdb,
                    settings.data_dir,
                    settings,
                )
            )
            logger.info("state_dump: startup dump scheduled (DEBUG_STARTUP_DUMP=true)")

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

        async def _backup_job() -> None:
            """Nightly scheduled backup (issue #5).

            Re-reads the live config each fire, early-returns when the master
            switch is off (mirrors _sync_job's gating), then writes whichever
            backups are enabled and prunes old files. Any failure is logged, never
            raised, so a bad backup can't crash the scheduler.

            Records the last-run summary in BridgeConfig["backup_last_run"] for
            observability (issue #20): success writes the artifact paths + pruned
            list; failure writes the error string. Both paths stamp a UTC ISO at-time.
            """
            import datetime as _dt

            from app.api.config import effective_backup_config, prune_sync_log_now
            from app.core.backup_job import run_scheduled_backup

            db = SessionLocal()
            try:
                # Prune the sync log daily, independent of both auto-sync and the
                # backup master switch, so retention always applies (#22).
                prune_sync_log_now(db)
                cfg = effective_backup_config(db)
                if not cfg.backup_schedule_enabled:
                    logger.debug("Scheduled backups disabled — skipping nightly run")
                    return
                result = await run_scheduled_backup(db, app.state.filamentdb, settings=cfg)
                _now_utc = _dt.datetime.now(_dt.timezone.utc).isoformat()
                set_config_value(db, "backup_last_run", {
                    "at": _now_utc,
                    "ok": True,
                    "bridge_state": result.get("bridge_state"),
                    "filamentdb": result.get("filamentdb"),
                    "pruned": result.get("pruned", []),
                })
                db.commit()
            except Exception as exc:
                logger.error("Unhandled error in backup job: %s", exc, exc_info=True)
                try:
                    import datetime as _dt2
                    _now_utc = _dt2.datetime.now(_dt2.timezone.utc).isoformat()
                    set_config_value(db, "backup_last_run", {
                        "at": _now_utc,
                        "ok": False,
                        "error": str(exc),
                    })
                    db.commit()
                except Exception:  # noqa: BLE001
                    pass
            finally:
                db.close()

        # Determine the effective interval: DB override takes precedence over env default.
        from app.api.config import _effective_sync_interval, effective_backup_hour_utc
        db_for_interval = SessionLocal()
        try:
            initial_interval = _effective_sync_interval(db_for_interval)
            initial_backup_hour = effective_backup_hour_utc(db_for_interval)
        finally:
            db_for_interval.close()

        _scheduler.add_job(
            _sync_job,
            "interval",
            seconds=initial_interval,
            id="sync_cycle",
        )

        from apscheduler.triggers.cron import CronTrigger

        _scheduler.add_job(
            _backup_job,
            CronTrigger(hour=initial_backup_hour, minute=0),
            id="nightly_backup",
        )
        _scheduler.start()
        # Store scheduler on app.state so the config endpoint can reschedule it.
        app.state.scheduler = _scheduler
        logger.info(
            "Scheduler started — interval=%ds, auto-sync gated by BridgeConfig.auto_sync_enabled; "
            "nightly backup at %02d:00 UTC (gated by backup_schedule_enabled)",
            initial_interval,
            initial_backup_hour,
        )

        # One-shot prune at startup so stale backups clear even if the nightly
        # hour hasn't been reached yet. Cheap and failure-tolerant.
        try:
            from app.api.config import effective_backup_config
            from app.core.backup_job import backups_dir, prune_backups

            _prune_db = SessionLocal()
            try:
                _bcfg = effective_backup_config(_prune_db)
            finally:
                _prune_db.close()
            prune_backups(backups_dir(_bcfg.data_dir), _bcfg.backup_retention_days)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Startup backup prune failed: %s", exc)

        # One-shot sync-log prune at startup so retention applies even for users
        # who never enable auto-sync (whose tick is the only other prune) (#22).
        try:
            from app.api.config import prune_sync_log_now

            _slog_db = SessionLocal()
            try:
                prune_sync_log_now(_slog_db)
            finally:
                _slog_db.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Startup sync-log prune failed: %s", exc)
        try:
            yield
        finally:
            _scheduler.shutdown(wait=False)
            # Cancel and await the startup dump task if it hasn't finished yet.
            if _dump_task is not None and not _dump_task.done():
                _dump_task.cancel()
                try:
                    await _dump_task
                except (asyncio.CancelledError, Exception):
                    pass
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


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    """Add defensive security headers to every response.

    setdefault() never overwrites a header a route already set explicitly.
    CSP is deferred: a strict policy for the Vite/React SPA + react-markdown
    docs viewer needs care and risks breaking the app; configure at the proxy.
    HSTS is deferred: harmful on plain-http LAN deployments; set at the TLS
    terminator.
    """
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


# Public: health + auth + version endpoints (no require_auth dependency)
app.include_router(health_router.router, prefix="/api")
app.include_router(auth_router.router, prefix="/api")
app.include_router(version_router.router, prefix="/api")

# Protected: all remaining API routers require authentication (global require_auth).
_auth_dep = [Depends(require_auth)]
app.include_router(sync_router.router, prefix="/api", dependencies=_auth_dep)
app.include_router(conflicts_router.router, prefix="/api", dependencies=_auth_dep)
app.include_router(mappings_router.router, prefix="/api", dependencies=_auth_dep)
app.include_router(reconcile_router.router, prefix="/api", dependencies=_auth_dep)
app.include_router(config_router.router, prefix="/api", dependencies=_auth_dep)
app.include_router(wizard_router.router, prefix="/api", dependencies=_auth_dep)
app.include_router(opentag_router.router, prefix="/api", dependencies=_auth_dep)
app.include_router(backup_router.router, prefix="/api", dependencies=_auth_dep)
app.include_router(sync_log_router.router, prefix="/api", dependencies=_auth_dep)
app.include_router(tare_router.router, prefix="/api", dependencies=_auth_dep)
app.include_router(debug_router.router, prefix="/api", dependencies=_auth_dep)

# Conditional auth: the mobile + labels routers (and the /r/ redirect below) carry
# `mobile_auth` INSTEAD of the global `require_auth`. mobile_auth bypasses auth ONLY
# when mobile_session_days == 0 (public scan flow) and otherwise enforces the exact
# same check as require_auth. These are the ONLY three surfaces that become
# conditionally public — every other router above keeps require_auth unchanged. The
# `_require_labels_enabled` 403 feature gate still runs on each mobile/label route.
_mobile_auth_dep = [Depends(mobile_auth)]
app.include_router(mobile_router.router, prefix="/api", dependencies=_mobile_auth_dep)
app.include_router(labels_router.router, prefix="/api", dependencies=_mobile_auth_dep)


# QR redirect — the indirection point. The printed QR encodes /r/{fil}/{spool};
# this 302s to the configured target so the destination can change later without
# reprinting. Registered BEFORE the SPA catch-all below or index.html swallows it.
# It is outside /api, so it carries its own auth + feature-gate dependencies. Auth is
# the conditional mobile_auth (public when mobile_session_days == 0), matching the
# /api/mobile + /api/labels routers — a cold phone scan lands here first.
@app.get("/r/{fil}/{spool}", include_in_schema=False, dependencies=_mobile_auth_dep)
async def _qr_redirect(fil: str, spool: str, db=Depends(get_db)):
    from fastapi.responses import RedirectResponse

    from app.api.config import mobile_redirect_target
    from app.api.mobile import _require_labels_enabled, qr_redirect_url

    _require_labels_enabled(db)  # 403 when the feature is off

    target = mobile_redirect_target(db)
    # qr_redirect_url validates fil/spool against an id allowlist before building the
    # target, closing the open-redirect / path-injection vector (CWE-601 / CWE-22).
    url = qr_redirect_url(target, fil, spool, filamentdb_url=settings.filamentdb_url)
    return RedirectResponse(url, status_code=302)

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
    _static_root = os.path.realpath(str(_static_dir))

    @app.get("/{full_path:path}", include_in_schema=False)
    async def _spa_fallback(full_path: str) -> FileResponse:
        if full_path.startswith("api"):
            raise HTTPException(status_code=404)
        # Normalise, then require the result to stay under the static root so a
        # crafted path (e.g. "../../etc/passwd") can't escape the served dir.
        candidate = os.path.realpath(os.path.join(_static_root, full_path))
        if (
            full_path
            and (candidate == _static_root or candidate.startswith(_static_root + os.sep))
            and os.path.isfile(candidate)
        ):
            return FileResponse(candidate)
        return FileResponse(_index)
