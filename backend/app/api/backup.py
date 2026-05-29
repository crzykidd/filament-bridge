"""Backup export/import — FR-24 / FR-25.

Exports/restores the bridge's OWN state only: mappings, config, and open
conflicts. It is NOT a copy of Filament DB or Spoolman data (CLAUDE.md). The
envelope is versioned (schema_version) for forward compatibility, and import is
idempotent — re-importing the same dump makes no further changes.
"""

from __future__ import annotations

import datetime
import json

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.config import read_config, set_config_value
from app.api.errors import api_error
from app.db import get_db
from app.models.conflict import Conflict
from app.models.mapping import FilamentMapping, SpoolMapping
from app.schemas.api import (
    BACKUP_SCHEMA_VERSION,
    BackupExport,
    BackupImportResponse,
)

router = APIRouter()


def _decode(raw: str | None):
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


@router.get("/backup/export", response_model=BackupExport)
def export_backup(db: Session = Depends(get_db)) -> BackupExport:
    filament_mappings = [
        {
            "id": m.id,
            "spoolman_filament_id": m.spoolman_filament_id,
            "filamentdb_id": m.filamentdb_id,
            "filamentdb_parent_id": m.filamentdb_parent_id,
        }
        for m in db.query(FilamentMapping).all()
    ]
    spool_mappings = [
        {
            "id": m.id,
            "spoolman_spool_id": m.spoolman_spool_id,
            "filamentdb_filament_id": m.filamentdb_filament_id,
            "filamentdb_spool_id": m.filamentdb_spool_id,
            "filament_mapping_id": m.filament_mapping_id,
        }
        for m in db.query(SpoolMapping).all()
    ]
    open_conflicts = [
        {
            "entity_type": c.entity_type,
            "spoolman_id": c.spoolman_id,
            "filamentdb_filament_id": c.filamentdb_filament_id,
            "filamentdb_spool_id": c.filamentdb_spool_id,
            "field_name": c.field_name,
            "spoolman_value": _decode(c.spoolman_value),
            "filamentdb_value": _decode(c.filamentdb_value),
        }
        for c in db.query(Conflict).filter(Conflict.resolved_at.is_(None)).all()
    ]
    return BackupExport(
        schema_version=BACKUP_SCHEMA_VERSION,
        exported_at=datetime.datetime.now(datetime.timezone.utc),
        config=read_config(db),
        filament_mappings=filament_mappings,
        spool_mappings=spool_mappings,
        open_conflicts=open_conflicts,
    )


@router.post("/backup/import", response_model=BackupImportResponse)
def import_backup(payload: BackupExport, db: Session = Depends(get_db)) -> BackupImportResponse:
    if payload.schema_version != BACKUP_SCHEMA_VERSION:
        raise api_error(
            400,
            "unsupported_schema_version",
            f"Backup schema_version {payload.schema_version} is not supported "
            f"(expected {BACKUP_SCHEMA_VERSION}).",
        )

    config_count = 0
    for key, value in payload.config.items():
        set_config_value(db, key, value)
        config_count += 1

    # Filament mappings — upsert by the unique business key (spoolman_filament_id).
    fil_count = 0
    for fm in payload.filament_mappings:
        existing = (
            db.query(FilamentMapping)
            .filter_by(spoolman_filament_id=fm["spoolman_filament_id"])
            .first()
        )
        if existing is not None:
            existing.filamentdb_id = fm["filamentdb_id"]
            existing.filamentdb_parent_id = fm.get("filamentdb_parent_id")
        else:
            db.add(
                FilamentMapping(
                    id=fm.get("id"),
                    spoolman_filament_id=fm["spoolman_filament_id"],
                    filamentdb_id=fm["filamentdb_id"],
                    filamentdb_parent_id=fm.get("filamentdb_parent_id"),
                )
            )
        fil_count += 1

    # Spool mappings — upsert by the unique business key (spoolman_spool_id).
    spool_count = 0
    for sm in payload.spool_mappings:
        existing = (
            db.query(SpoolMapping)
            .filter_by(spoolman_spool_id=sm["spoolman_spool_id"])
            .first()
        )
        if existing is not None:
            existing.filamentdb_filament_id = sm["filamentdb_filament_id"]
            existing.filamentdb_spool_id = sm["filamentdb_spool_id"]
            existing.filament_mapping_id = sm.get("filament_mapping_id")
        else:
            db.add(
                SpoolMapping(
                    id=sm.get("id"),
                    spoolman_spool_id=sm["spoolman_spool_id"],
                    filamentdb_filament_id=sm["filamentdb_filament_id"],
                    filamentdb_spool_id=sm["filamentdb_spool_id"],
                    filament_mapping_id=sm.get("filament_mapping_id"),
                )
            )
        spool_count += 1

    # Open conflicts — insert only if an equivalent open conflict is absent
    # (natural key: entity_type + field_name + the two spool/filament ids).
    conflict_count = 0
    for c in payload.open_conflicts:
        exists = (
            db.query(Conflict)
            .filter(
                Conflict.resolved_at.is_(None),
                Conflict.entity_type == c["entity_type"],
                Conflict.field_name == c["field_name"],
                Conflict.spoolman_id == c.get("spoolman_id"),
                Conflict.filamentdb_spool_id == c.get("filamentdb_spool_id"),
            )
            .first()
        )
        if exists is not None:
            continue
        sm_val = c.get("spoolman_value")
        fdb_val = c.get("filamentdb_value")
        db.add(
            Conflict(
                entity_type=c["entity_type"],
                spoolman_id=c.get("spoolman_id"),
                filamentdb_filament_id=c.get("filamentdb_filament_id"),
                filamentdb_spool_id=c.get("filamentdb_spool_id"),
                field_name=c["field_name"],
                spoolman_value=json.dumps(sm_val) if sm_val is not None else None,
                filamentdb_value=json.dumps(fdb_val) if fdb_val is not None else None,
            )
        )
        conflict_count += 1

    db.commit()
    return BackupImportResponse(
        schema_version=payload.schema_version,
        config=config_count,
        filament_mappings=fil_count,
        spool_mappings=spool_count,
        conflicts=conflict_count,
    )
