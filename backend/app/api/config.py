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


def resolve_container_parent_marker(db: Session) -> str:
    """Return the effective container_parent_marker from BridgeConfig (or env default).

    An explicitly-stored empty string is honored (means "no marker suffix"); only a
    missing key falls back to the env/start-up default.
    """
    raw = get_config_value(db, "container_parent_marker", None)
    if raw is None:
        return _settings.container_parent_marker
    return str(raw)


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


def _resolve_bool(db: Session, key: str, env_default: bool) -> bool:
    """Return a boolean config value: DB override wins, else the env start-up default."""
    val = get_config_value(db, key, None)
    if val is None:
        return env_default
    return bool(val)


class _EffectiveBackupConfig:
    """Resolved scheduled-backup config (DB override wins over env), passed to the job.

    Mirrors the env→DB precedence used for ``sync_interval_seconds``.
    """

    def __init__(self, db: Session) -> None:
        self.backup_schedule_enabled = _resolve_bool(
            db, "backup_schedule_enabled", _settings.backup_schedule_enabled
        )
        self.backup_bridge_state_enabled = _resolve_bool(
            db, "backup_bridge_state_enabled", _settings.backup_bridge_state_enabled
        )
        self.backup_filamentdb_enabled = _resolve_bool(
            db, "backup_filamentdb_enabled", _settings.backup_filamentdb_enabled
        )
        retention = get_config_value(db, "backup_retention_days", None)
        self.backup_retention_days = (
            int(retention) if retention is not None else _settings.backup_retention_days
        )
        self.data_dir = _settings.data_dir


def effective_backup_config(db: Session) -> _EffectiveBackupConfig:
    """Public accessor for the resolved scheduled-backup config."""
    return _EffectiveBackupConfig(db)


def effective_backup_hour_utc(db: Session) -> int:
    """Return the active backup hour (0..23): DB override wins over the env default."""
    val = get_config_value(db, "backup_hour_utc", None)
    if val is None:
        return _settings.backup_hour_utc
    return int(val)


def mobile_labels_enabled(db: Session) -> bool:
    """Return whether the mobile-updates & labels feature is enabled (DB wins, else env)."""
    return _resolve_bool(db, "mobile_labels_enabled", _settings.mobile_labels_enabled)


def mobile_session_days(db: Session) -> int:
    """Return the mobile scan-flow session lifetime in days (DB wins, else env).

    0  → the scan flow is public (no app password); the rest of the app stays gated.
    >= 1 → the scan flow requires the normal login, and the fb_session cookie lives
    this many days. Never negative (the API rejects < 0 on write).
    """
    val = get_config_value(db, "mobile_session_days", None)
    if val is None:
        return int(_settings.mobile_session_days)
    return int(val)


def mobile_redirect_target(db: Session) -> str:
    """Return the configured /r/ redirect target ("bridge" | "filamentdb")."""
    val = get_config_value(db, "mobile_redirect_target", None)
    if val is None:
        return _settings.mobile_redirect_target
    return str(val)


def mobile_weight_default_mode(db: Session) -> str:
    """Return the default mobile weight-save mode ("direct_correction" | "usage")."""
    val = get_config_value(db, "mobile_weight_default_mode", None)
    if val is None:
        return _settings.mobile_weight_default_mode
    return str(val)


def bridge_public_url(db: Session) -> str:
    """Return the configured external bridge base URL (empty = derive from request)."""
    val = get_config_value(db, "bridge_public_url", None)
    if val is None:
        return _settings.bridge_public_url
    return str(val)


def labelforge_url(db: Session) -> str:
    """Return the configured LabelForge base URL (empty = not configured)."""
    val = get_config_value(db, "labelforge_url", None)
    if val is None:
        return _settings.labelforge_url
    return str(val)


def labelforge_token(db: Session) -> str:
    """Return the configured LabelForge API token (empty = no auth header)."""
    val = get_config_value(db, "labelforge_token", None)
    if val is None:
        return _settings.labelforge_token
    return str(val)


def labelforge_template(db: Session) -> str:
    """Return the configured LabelForge template name (empty = not configured)."""
    val = get_config_value(db, "labelforge_template", None)
    if val is None:
        return _settings.labelforge_template
    return str(val)


def labelforge_fields(db: Session) -> str:
    """Return the configured CSV of label field names to send (empty = none)."""
    val = get_config_value(db, "labelforge_fields", None)
    if val is None:
        return _settings.labelforge_fields
    return str(val)


def labelforge_label_media(db: Session) -> str:
    """Return the configured optional label-media hint (empty = template default)."""
    val = get_config_value(db, "labelforge_label_media", None)
    if val is None:
        return _settings.labelforge_label_media
    return str(val)


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
        archive_sync_direction=cfg.get("archive_sync_direction", "two_way"),
        archive_conflict_policy=cfg.get("archive_conflict_policy", "manual"),
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
        backup_schedule_enabled=(
            bool(cfg["backup_schedule_enabled"])
            if "backup_schedule_enabled" in cfg
            else _settings.backup_schedule_enabled
        ),
        backup_bridge_state_enabled=(
            bool(cfg["backup_bridge_state_enabled"])
            if "backup_bridge_state_enabled" in cfg
            else _settings.backup_bridge_state_enabled
        ),
        backup_filamentdb_enabled=(
            bool(cfg["backup_filamentdb_enabled"])
            if "backup_filamentdb_enabled" in cfg
            else _settings.backup_filamentdb_enabled
        ),
        backup_retention_days=int(
            cfg.get("backup_retention_days", _settings.backup_retention_days)
        ),
        backup_hour_utc=int(cfg.get("backup_hour_utc", _settings.backup_hour_utc)),
        mobile_labels_enabled=(
            bool(cfg["mobile_labels_enabled"])
            if "mobile_labels_enabled" in cfg
            else _settings.mobile_labels_enabled
        ),
        mobile_session_days=int(cfg.get("mobile_session_days", _settings.mobile_session_days)),
        bridge_public_url=str(cfg.get("bridge_public_url", _settings.bridge_public_url)),
        mobile_redirect_target=cfg.get("mobile_redirect_target", _settings.mobile_redirect_target),
        mobile_weight_default_mode=cfg.get(
            "mobile_weight_default_mode", _settings.mobile_weight_default_mode
        ),
        labelforge_url=str(cfg.get("labelforge_url", _settings.labelforge_url)),
        labelforge_token=str(cfg.get("labelforge_token", _settings.labelforge_token)),
        labelforge_template=str(cfg.get("labelforge_template", _settings.labelforge_template)),
        labelforge_fields=str(cfg.get("labelforge_fields", _settings.labelforge_fields)),
        labelforge_label_media=str(
            cfg.get("labelforge_label_media", _settings.labelforge_label_media)
        ),
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

    # newest_wins is also meaningless for archive/retire — the state is a boolean,
    # not a timestamped value, so there is no "newer" side to pick.
    if payload.archive_conflict_policy == "newest_wins":
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_conflict_policy",
                "message": (
                    "newest_wins is not supported for archive_sync — archive/retire "
                    "is a boolean state with no comparable timestamp."
                ),
            },
        )

    # Validate scheduled-backup numeric ranges with the project's error envelope.
    if payload.backup_hour_utc is not None and not (0 <= payload.backup_hour_utc <= 23):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_backup_hour",
                "message": "backup_hour_utc must be between 0 and 23 (UTC hour of day).",
            },
        )
    if payload.backup_retention_days is not None and payload.backup_retention_days < 1:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_backup_retention",
                "message": "backup_retention_days must be at least 1.",
            },
        )

    # Mobile scan-flow session lifetime — must be >= 0 (0 = public scan flow).
    if payload.mobile_session_days is not None and payload.mobile_session_days < 0:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_mobile_session_days",
                "message": "mobile_session_days must be 0 or greater (0 = public scan flow).",
            },
        )

    updates = payload.model_dump(exclude_unset=True)

    # Note whether the backup schedule (hour or master-enable) changed so we can
    # reschedule the nightly_backup cron after persisting.
    backup_schedule_changed = (
        "backup_hour_utc" in updates or "backup_schedule_enabled" in updates
    )

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

    # Reschedule the nightly_backup cron when the hour or master-enable changed.
    # The job itself re-reads backup_schedule_enabled and early-returns when off,
    # so changing the hour while disabled still keeps the next fire time correct.
    if backup_schedule_changed:
        scheduler = getattr(getattr(request, "app", None), "state", None)
        scheduler = getattr(scheduler, "scheduler", None) if scheduler is not None else None
        if scheduler is not None:
            try:
                from apscheduler.triggers.cron import CronTrigger

                hour = effective_backup_hour_utc(db)
                scheduler.reschedule_job(
                    "nightly_backup",
                    trigger=CronTrigger(hour=hour, minute=0),
                )
                logger.info("Nightly backup rescheduled to %02d:00 UTC", hour)
            except Exception as exc:
                logger.warning("Could not reschedule nightly_backup job: %s", exc)

    return _config_response(db)
