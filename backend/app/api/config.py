"""GET/PUT /api/config — runtime config (FR-2 ongoing settings).

Exposes the user-tunable subset of BridgeConfig: source-of-truth per data
category and the weight sync threshold. Connection settings (URLs, field-mapping
config) stay env-var-only per CLAUDE.md and are NOT editable here.

The config-store helpers (read_config / get_config_value / set_config_value)
live here and are reused by the sync and wizard routers — BridgeConfig is the
bridge's key→JSON store, so wizard decision state is persisted here too rather
than in a dedicated table (see docs/decisions.md).
"""

from __future__ import annotations

import datetime
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.config import settings as _settings
from app.db import get_db
from app.models.config import BridgeConfig
from app.models.sync_log import SyncLog
from app.schemas.api import ConfigResponse, ConfigUpdateRequest

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Shared config-store helpers
# ---------------------------------------------------------------------------


def read_config(db: Session) -> dict[str, Any]:
    """Return all BridgeConfig keys decoded from their JSON values."""
    return {r.key: json.loads(r.value) for r in db.query(BridgeConfig).all()}


def get_config_value(db: Session, key: str, default: Any = None) -> Any:
    row = db.query(BridgeConfig).filter_by(key=key).first()
    return json.loads(row.value) if row else default


def set_config_value(db: Session, key: str, value: Any) -> None:
    """Upsert one BridgeConfig key (value is JSON-encoded)."""
    value_json = json.dumps(value)
    stmt = (
        sqlite_insert(BridgeConfig)
        .values(key=key, value=value_json)
        .on_conflict_do_update(
            index_elements=["key"],
            set_={"value": value_json, "updated_at": func.now()},
        )
    )
    db.execute(stmt)


# ---------------------------------------------------------------------------
# Sync-log prune helper
# ---------------------------------------------------------------------------

_SYNC_INTERVAL_MIN = 30  # minimum seconds the scheduler will accept


def prune_sync_log(db: Session, retention_days: int) -> int:
    """Delete SyncLog rows older than retention_days. No-op when retention_days == 0.

    Returns the number of rows deleted.
    """
    if retention_days <= 0:
        return 0
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=retention_days)
    deleted = db.query(SyncLog).filter(SyncLog.timestamp < cutoff).delete(synchronize_session=False)
    logger.info("Sync-log retention prune: deleted=%d rows older than %s", deleted, cutoff.date())
    return deleted


# ---------------------------------------------------------------------------
# Response assembly
# ---------------------------------------------------------------------------


def _effective_sync_interval(db: Session) -> int:
    """Return the active sync interval in seconds.

    The DB override (sync_interval_seconds != 0) takes precedence over the
    env-var default.
    """
    db_interval = int(get_config_value(db, "sync_interval_seconds", 0) or 0)
    if db_interval > 0:
        return max(db_interval, _SYNC_INTERVAL_MIN)
    return _settings.sync_interval_seconds


_REQUIRED_SETTINGS = ["variant_parent_mode"]


def _required_settings_unset(cfg: dict) -> list[str]:
    """Return list of required setting keys that are still in their 'unset' sentinel state."""
    unset = []
    if (cfg.get("variant_parent_mode") or "unset") == "unset":
        unset.append("variant_parent_mode")
    return unset


def _config_response(db: Session) -> ConfigResponse:
    cfg = read_config(db)
    db_interval = int(cfg.get("sync_interval_seconds") or 0)
    effective_interval = max(db_interval, _SYNC_INTERVAL_MIN) if db_interval > 0 else _settings.sync_interval_seconds

    # api_token: return the stored token value if present, else None.
    # NEVER return admin_password_hash or auth_secret.
    api_token_raw = cfg.get("api_token", None)
    api_token = api_token_raw if api_token_raw else None

    return ConfigResponse(
        sync_weight_threshold_grams=float(cfg.get("sync_weight_threshold_grams", 2.0)),
        weight_precision_decimals=int(cfg.get("weight_precision_decimals", 2)),
        auto_sync_enabled=bool(cfg.get("auto_sync_enabled", False)),
        wizard_completed=bool(cfg.get("wizard_completed", False)),
        import_direction=cfg.get("import_direction"),
        variant_line_keywords=cfg.get("variant_line_keywords", _settings.variant_line_keywords),
        opentag_vendor_aliases=cfg.get("opentag_vendor_aliases", _settings.opentag_vendor_aliases),
        weight_sync_direction=cfg.get("weight_sync_direction", "spoolman_to_filamentdb"),
        weight_conflict_policy=cfg.get("weight_conflict_policy", "manual"),
        material_properties_sync_direction=cfg.get("material_properties_sync_direction", "filamentdb_to_spoolman"),
        material_properties_conflict_policy=cfg.get("material_properties_conflict_policy", "manual"),
        new_spool_sync_direction=cfg.get("new_spool_sync_direction", "two_way"),
        new_filament_policy=cfg.get("new_filament_policy", "manual_review") or "manual_review",
        new_spool_policy=cfg.get("new_spool_policy", "manual_review") or "manual_review",
        sync_interval_seconds=effective_interval,
        sync_log_retention_days=int(cfg.get("sync_log_retention_days", 30)),
        never_import_empties=bool(cfg.get("never_import_empties", False)),
        debug_mode=bool(cfg.get("debug_mode", False)),
        variant_parent_mode=cfg.get("variant_parent_mode", "unset") or "unset",
        container_parent_marker=str(cfg.get("container_parent_marker", _settings.container_parent_marker)),
        api_token=api_token,
        api_token_enabled=bool(cfg.get("api_token_enabled", False)),
        required_settings_unset=_required_settings_unset(cfg),
    )


@router.get("/config", response_model=ConfigResponse)
def get_config(db: Session = Depends(get_db)) -> ConfigResponse:
    return _config_response(db)


@router.put("/config", response_model=ConfigResponse)
def update_config(
    payload: ConfigUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ConfigResponse:
    # Pydantic Literal/gt validators already rejected bad enum values / non-positive
    # thresholds with a 422 before we get here.
    #
    # Additional semantic constraint: newest_wins is weight-only (Spoolman has no
    # per-filament mtime, so it cannot be honest at the filament level).
    if payload.material_properties_conflict_policy == "newest_wins":
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_conflict_policy",
                "message": (
                    "newest_wins is not supported for material_properties — "
                    "Spoolman exposes no per-filament modification timestamp."
                ),
            },
        )

    updates = payload.model_dump(exclude_unset=True)

    # Extract sync_interval_seconds before persisting so we can reschedule.
    new_interval: int | None = None
    if "sync_interval_seconds" in updates and updates["sync_interval_seconds"] is not None:
        new_interval = max(int(updates["sync_interval_seconds"]), _SYNC_INTERVAL_MIN)
        updates["sync_interval_seconds"] = new_interval  # store clamped value

    for key, value in updates.items():
        if value is not None:
            set_config_value(db, key, value)
    db.commit()

    # Reschedule the interval job if the interval changed and the scheduler is
    # available on app.state (it won't be in tests that skip the full lifespan).
    if new_interval is not None:
        scheduler = getattr(getattr(request, "app", None), "state", None)
        scheduler = getattr(scheduler, "scheduler", None) if scheduler is not None else None
        if scheduler is not None:
            try:
                scheduler.reschedule_job(
                    "sync_cycle",
                    trigger="interval",
                    seconds=new_interval,
                )
                logger.info("Sync interval rescheduled to %ds", new_interval)
            except Exception as exc:
                logger.warning("Could not reschedule sync_cycle job: %s", exc)

    return _config_response(db)
