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

import json
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.config import settings as _settings
from app.db import get_db
from app.models.config import BridgeConfig
from app.schemas.api import ConfigResponse, ConfigUpdateRequest

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
# Response assembly
# ---------------------------------------------------------------------------


def _config_response(db: Session) -> ConfigResponse:
    cfg = read_config(db)
    return ConfigResponse(
        weight_source_of_truth=cfg.get("weight_source_of_truth", "spoolman"),
        material_properties_source_of_truth=cfg.get("material_properties_source_of_truth", "filamentdb"),
        new_spool_source_of_truth=cfg.get("new_spool_source_of_truth", "spoolman"),
        sync_weight_threshold_grams=float(cfg.get("sync_weight_threshold_grams", 2.0)),
        weight_precision_decimals=int(cfg.get("weight_precision_decimals", 2)),
        auto_sync_enabled=bool(cfg.get("auto_sync_enabled", False)),
        wizard_completed=bool(cfg.get("wizard_completed", False)),
        import_direction=cfg.get("import_direction"),
        variant_line_keywords=cfg.get("variant_line_keywords", _settings.variant_line_keywords),
    )


@router.get("/config", response_model=ConfigResponse)
def get_config(db: Session = Depends(get_db)) -> ConfigResponse:
    return _config_response(db)


@router.put("/config", response_model=ConfigResponse)
def update_config(payload: ConfigUpdateRequest, db: Session = Depends(get_db)) -> ConfigResponse:
    # Pydantic Literal/gt validators already rejected bad enum values / non-positive
    # thresholds with a 422 before we get here.
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            set_config_value(db, key, value)
    db.commit()
    return _config_response(db)
