"""Conflict queue — FR-13 / FR-16.

Conflicts are NEVER auto-resolved (hard rule). These endpoints let a human record
a resolution choice; the chosen value is stored on the Conflict row and the
conflict leaves the open queue.

For `master_divergence` conflicts the endpoint additionally writes upstream
when the human chooses an action (apply_all / variant_override / ignore) — this
is human-approved resolution, not silent auto-apply.  All other conflict types
remain record-only (no upstream writes).
"""

from __future__ import annotations

import datetime
import json
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.errors import api_error
from app.db import get_db
from app.models.conflict import DELETION_FIELD, Conflict
from app.models.mapping import SpoolMapping
from app.models.snapshot import Snapshot
from app.schemas.api import (
    BulkResolveRequest,
    BulkResolveResponse,
    ConflictResolveRequest,
    ConflictResponse,
    DivergenceContextResponse,
    DivergenceVariantEntry,
)

router = APIRouter()


def _cleanup_orphaned_mapping(db: Session, c: Conflict) -> None:
    """Delete bridge-local SpoolMapping + Snapshots for a resolved deletion conflict."""
    mapping = (
        db.query(SpoolMapping)
        .filter(
            SpoolMapping.spoolman_spool_id == c.spoolman_id,
            SpoolMapping.filamentdb_spool_id == c.filamentdb_spool_id,
        )
        .first()
    )
    if mapping is None:
        return
    if c.spoolman_id is not None:
        db.query(Snapshot).filter_by(
            source="spoolman", entity_type="spool", entity_id=str(c.spoolman_id)
        ).delete()
    if c.filamentdb_spool_id is not None:
        db.query(Snapshot).filter_by(
            source="filamentdb", entity_type="spool", entity_id=c.filamentdb_spool_id
        ).delete()
    db.delete(mapping)


def _decode(raw: str | None):
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


def _conflict_identity(db: Session, c: Conflict) -> dict:
    """Load identifying fields from the Spoolman snapshot for a conflict.

    For spool conflicts: reads the spool snapshot whose nested filament carries
    name/vendor/color_hex/material.
    For filament conflicts: reads the filament snapshot directly.

    Returns a dict with label/vendor/name/color_hex/material.
    Tolerates a missing snapshot: returns an id-based label with null fields.
    """
    _empty = {
        "label": None,
        "vendor": None,
        "name": None,
        "color_hex": None,
        "multi_color_hexes": None,
        "multi_color_direction": None,
        "material": None,
    }

    if c.spoolman_id is None:
        return _empty

    if c.entity_type == "spool":
        snap_row = (
            db.query(Snapshot)
            .filter_by(source="spoolman", entity_type="spool", entity_id=str(c.spoolman_id))
            .first()
        )
        if snap_row is None:
            return {**_empty, "label": f"SM #{c.spoolman_id}"}
        snap = json.loads(snap_row.data)
        filament = snap.get("filament") or {}
        vendor_obj = filament.get("vendor") if isinstance(filament.get("vendor"), dict) else {}
        vendor_name = (vendor_obj or {}).get("name")
        name = filament.get("name")
        color_hex = filament.get("color_hex")
        multi_color_hexes = filament.get("multi_color_hexes")
        multi_color_direction = filament.get("multi_color_direction")
        material = filament.get("material")
    else:
        # entity_type == "filament"
        snap_row = (
            db.query(Snapshot)
            .filter_by(source="spoolman", entity_type="filament", entity_id=str(c.spoolman_id))
            .first()
        )
        if snap_row is None:
            return {**_empty, "label": f"SM #{c.spoolman_id}"}
        snap = json.loads(snap_row.data)
        vendor_obj = snap.get("vendor") if isinstance(snap.get("vendor"), dict) else {}
        vendor_name = (vendor_obj or {}).get("name")
        name = snap.get("name")
        color_hex = snap.get("color_hex")
        multi_color_hexes = snap.get("multi_color_hexes")
        multi_color_direction = snap.get("multi_color_direction")
        material = snap.get("material")

    parts = [p for p in (vendor_name, name) if p]
    label = " ".join(parts).strip() or f"SM #{c.spoolman_id}"
    return {
        "label": label,
        "vendor": vendor_name,
        "name": name,
        "color_hex": color_hex,
        "multi_color_hexes": multi_color_hexes,
        "multi_color_direction": multi_color_direction,
        "material": material,
    }


def _to_response(c: Conflict, db: Session | None = None) -> ConflictResponse:
    identity = _conflict_identity(db, c) if db is not None else {
        "label": None, "vendor": None, "name": None,
        "color_hex": None, "multi_color_hexes": None, "multi_color_direction": None,
        "material": None,
    }
    return ConflictResponse(
        id=c.id,
        status="resolved" if c.resolved_at is not None else "open",
        entity_type=c.entity_type,
        field_name=c.field_name,
        conflict_type=getattr(c, "conflict_type", "cross_system") or "cross_system",
        spoolman_id=c.spoolman_id,
        filamentdb_filament_id=c.filamentdb_filament_id,
        filamentdb_spool_id=c.filamentdb_spool_id,
        spoolman_value=_decode(c.spoolman_value),
        filamentdb_value=_decode(c.filamentdb_value),
        detected_at=c.detected_at,
        resolved_at=c.resolved_at,
        resolution=c.resolution,
        resolved_value=_decode(c.resolved_value),
        **identity,
    )


def _resolved_value(c: Conflict, resolution: str, manual_value) -> object:
    """Pick the value to record for a resolution. Never auto-applies the other side."""
    if resolution == "spoolman":
        return _decode(c.spoolman_value)
    if resolution == "filamentdb":
        return _decode(c.filamentdb_value)
    return manual_value  # "manual"


@router.get("/conflicts", response_model=list[ConflictResponse])
def list_conflicts(
    db: Session = Depends(get_db),
    status: Literal["open", "resolved"] = Query(default="open"),
) -> list[ConflictResponse]:
    q = db.query(Conflict)
    if status == "open":
        q = q.filter(Conflict.resolved_at.is_(None))
    else:
        q = q.filter(Conflict.resolved_at.isnot(None))
    rows = q.order_by(Conflict.detected_at.desc(), Conflict.id.desc()).all()
    return [_to_response(c, db) for c in rows]


@router.post("/conflicts/{conflict_id}/resolve", response_model=ConflictResponse)
async def resolve_conflict(
    conflict_id: int,
    payload: ConflictResolveRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ConflictResponse:
    c = db.query(Conflict).filter_by(id=conflict_id).first()
    if c is None:
        raise api_error(404, "conflict_not_found", f"No conflict with id {conflict_id}")
    if c.resolved_at is not None:
        raise api_error(409, "already_resolved", f"Conflict {conflict_id} is already resolved")

    conflict_type = getattr(c, "conflict_type", "cross_system") or "cross_system"

    if conflict_type == "master_divergence":
        # For master_divergence conflicts the `action` field is required.
        if payload.action is None:
            raise api_error(
                422, "action_required",
                "master_divergence conflicts require an action: apply_all, variant_override, or ignore"
            )
        # Perform upstream writes via conflict_apply.
        from app.core.conflict_apply import apply_master_divergence
        spoolman = request.app.state.spoolman
        filamentdb = request.app.state.filamentdb
        try:
            await apply_master_divergence(c, payload.action, db, spoolman, filamentdb)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error(
                "apply_master_divergence failed for conflict %d: %s", conflict_id, exc
            )
            raise api_error(
                502, "upstream_write_failed",
                f"Upstream write failed; conflict not resolved. Detail: {exc}"
            )
        db.commit()
        db.refresh(c)
        return _to_response(c, db)

    # All other conflict types: record-only resolution (no upstream writes).
    if payload.resolution == "manual" and payload.value is None:
        raise api_error(422, "manual_value_required", "A manual resolution requires a value")

    c.resolution = payload.resolution
    c.resolved_value = json.dumps(_resolved_value(c, payload.resolution, payload.value))
    c.resolved_at = datetime.datetime.now(datetime.timezone.utc)
    if c.field_name == DELETION_FIELD:
        _cleanup_orphaned_mapping(db, c)
    db.commit()
    db.refresh(c)
    return _to_response(c, db)


@router.get("/conflicts/{conflict_id}/divergence-context", response_model=DivergenceContextResponse)
async def get_divergence_context(
    conflict_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> DivergenceContextResponse:
    """Return master + variant line context for a master_divergence conflict.

    Only valid for conflicts with conflict_type == 'master_divergence'.
    Fetches live data from Filament DB to show current values.
    """
    c = db.query(Conflict).filter_by(id=conflict_id).first()
    if c is None:
        raise api_error(404, "conflict_not_found", f"No conflict with id {conflict_id}")
    conflict_type = getattr(c, "conflict_type", "cross_system") or "cross_system"
    if conflict_type != "master_divergence":
        raise api_error(
            400, "not_master_divergence",
            f"Conflict {conflict_id} is type '{conflict_type}', not 'master_divergence'"
        )

    from app.core.conflict_apply import build_divergence_context
    filamentdb = request.app.state.filamentdb
    try:
        ctx = await build_divergence_context(c, db, filamentdb)
    except Exception as exc:
        raise api_error(502, "upstream_fetch_failed", f"Could not fetch divergence context: {exc}")

    return DivergenceContextResponse(
        master_fdb_id=ctx["master_fdb_id"],
        master_name=ctx.get("master_name"),
        master_current_value=ctx.get("master_current_value"),
        field_name=ctx["field_name"],
        fdb_path=ctx["fdb_path"],
        variants=[
            DivergenceVariantEntry(
                fdb_id=v["fdb_id"],
                name=v.get("name"),
                color_hex=v.get("color_hex"),
                spoolman_filament_id=v.get("spoolman_filament_id"),
                current_value=v.get("current_value"),
                inherited=v.get("inherited", True),
            )
            for v in ctx.get("variants", [])
        ],
    )


@router.post("/conflicts/bulk-resolve", response_model=BulkResolveResponse)
def bulk_resolve(payload: BulkResolveRequest, db: Session = Depends(get_db)) -> BulkResolveResponse:
    if payload.resolution == "manual" and payload.value is None:
        raise api_error(422, "manual_value_required", "A manual resolution requires a value")

    now = datetime.datetime.now(datetime.timezone.utc)
    resolved = 0
    skipped: list[int] = []
    for cid in payload.ids:
        c = db.query(Conflict).filter_by(id=cid).first()
        if c is None or c.resolved_at is not None:
            skipped.append(cid)
            continue
        c.resolution = payload.resolution
        c.resolved_value = json.dumps(_resolved_value(c, payload.resolution, payload.value))
        c.resolved_at = now
        if c.field_name == DELETION_FIELD:
            _cleanup_orphaned_mapping(db, c)
        resolved += 1
    db.commit()
    return BulkResolveResponse(resolved=resolved, skipped=skipped)
