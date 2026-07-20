"""Conflict queue — FR-13 / FR-16.

Conflicts are NEVER auto-resolved (hard rule). These endpoints let a human record
a resolution choice; the chosen value is stored on the Conflict row and the
conflict leaves the open queue.

For `master_divergence` conflicts the endpoint additionally writes upstream
when the human chooses an action (apply_all / variant_override / ignore) — this
is human-approved resolution, not silent auto-apply.  All other conflict types
remain record-only (no upstream writes).

POST /api/conflicts/{conflict_id}/import is the scoped single-record import
endpoint for new_filament and new_spool conflicts — it powers the "Add" button
in the Conflicts UI (prompt #2).  It uses the shared single-record import helper
in app/core/single_record_import.py so the import logic is not duplicated.
"""

from __future__ import annotations

import datetime
import json
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.config import get_config_value
from app.api.errors import api_error
from app.core.log_safe import scrub as _scrub
from app.db import get_db
from app.models.conflict import DELETION_FIELD, Conflict
from app.models.mapping import SpoolMapping
from app.models.snapshot import Snapshot
from app.schemas.api import (
    BulkResolveRequest,
    BulkResolveResponse,
    ConflictImportRequest,
    ConflictResolveRequest,
    ConflictResponse,
    DivergenceContextResponse,
    DivergenceVariantEntry,
    FilamentSuggestion,
    FilamentSuggestionsResponse,
    WizardExecuteResponse,
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


def _identity_from_blob(blob_raw: str | None) -> dict | None:
    """Parse a JSON identity blob stored in spoolman_value / filamentdb_value.

    Returns a dict with vendor/name/color_hex/material keys if the blob is a
    valid JSON object (new-format rows written by the upsert helper).  Returns
    None for plain-string legacy values so callers can fall back gracefully.
    """
    if blob_raw is None:
        return None
    try:
        parsed = json.loads(blob_raw)
        if isinstance(parsed, dict) and "name" in parsed:
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def _conflict_identity(db: Session, c: Conflict) -> dict:
    """Load identifying fields for a conflict row.

    Priority order:
    1. Spoolman snapshot (most authoritative — has full nested filament data).
    2. JSON identity blob stored in spoolman_value / filamentdb_value at queue time
       (present for new_filament / new_spool conflicts where no snapshot exists yet).
    3. Id-based label fallback.

    Returns a dict with label/vendor/name/color_hex/multi_color_hexes/
    multi_color_direction/material.
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

    # --- Attempt 1: Spoolman snapshot (only when spoolman_id is set) ---
    if c.spoolman_id is not None:
        if c.entity_type == "spool":
            snap_row = (
                db.query(Snapshot)
                .filter_by(source="spoolman", entity_type="spool", entity_id=str(c.spoolman_id))
                .first()
            )
            if snap_row is not None:
                snap = json.loads(snap_row.data)
                filament = snap.get("filament") or {}
                vendor_obj = filament.get("vendor") if isinstance(filament.get("vendor"), dict) else {}
                vendor_name = (vendor_obj or {}).get("name")
                name = filament.get("name")
                color_hex = filament.get("color_hex")
                multi_color_hexes = filament.get("multi_color_hexes")
                multi_color_direction = filament.get("multi_color_direction")
                material = filament.get("material")
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
        else:
            # entity_type == "filament"
            snap_row = (
                db.query(Snapshot)
                .filter_by(source="spoolman", entity_type="filament", entity_id=str(c.spoolman_id))
                .first()
            )
            if snap_row is not None:
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

    # --- Attempt 2: JSON identity blob (new_filament / new_spool rows) ---
    blob = _identity_from_blob(c.spoolman_value) or _identity_from_blob(c.filamentdb_value)
    if blob is not None:
        vendor_name = blob.get("vendor")
        name = blob.get("name")
        color_hex = blob.get("color_hex")
        material = blob.get("material")
        parts = [p for p in (vendor_name, name) if p]
        # Build id suffix for the label
        if c.spoolman_id is not None:
            id_suffix = f"(SM #{c.spoolman_id})"
        elif c.filamentdb_filament_id is not None:
            id_suffix = f"(FDB {c.filamentdb_filament_id[:8]}…)"
        else:
            id_suffix = ""
        label_parts = [p for p in (" ".join(parts).strip(), id_suffix) if p]
        label = " ".join(label_parts) or id_suffix or "Unknown"
        return {
            "label": label,
            "vendor": vendor_name,
            "name": name,
            "color_hex": color_hex,
            "multi_color_hexes": None,
            "multi_color_direction": None,
            "material": material,
        }

    # --- Attempt 3: Id-based fallback ---
    if c.spoolman_id is not None:
        return {**_empty, "label": f"SM #{c.spoolman_id}"}
    if c.filamentdb_filament_id is not None:
        return {**_empty, "label": f"FDB {c.filamentdb_filament_id[:8]}…"}
    return _empty


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
                "apply_master_divergence failed for conflict %s: %s",
                _scrub(conflict_id),
                _scrub(exc),
            )
            raise api_error(
                502, "upstream_write_failed",
                f"Upstream write failed; conflict not resolved. Detail: {exc}"
            )
        db.commit()
        db.refresh(c)
        return _to_response(c, db)

    if payload.resolution == "manual" and payload.value is None:
        raise api_error(422, "manual_value_required", "A manual resolution requires a value")

    # cross_system conflicts (except orphaned-deletion markers) CONVERGE on resolve:
    # the chosen value is written to BOTH systems and both snapshots are refreshed so
    # the conflict does not re-queue next cycle (GitHub #21). This is human-approved
    # reconciliation, not silent auto-apply. Deletion-marker conflicts have nothing to
    # write upstream and keep their record-only + mapping-cleanup behavior below.
    if conflict_type == "cross_system" and c.field_name != DELETION_FIELD:
        from app.core.conflict_apply import (
            UnsupportedConflictField,
            apply_cross_system_conflict,
        )
        spoolman = request.app.state.spoolman
        filamentdb = request.app.state.filamentdb
        try:
            await apply_cross_system_conflict(
                c, payload.resolution, payload.value, db, spoolman, filamentdb
            )
        except UnsupportedConflictField as exc:
            import logging
            logging.getLogger(__name__).warning(
                "Unsupported cross_system field for apply, conflict %s: %s",
                _scrub(conflict_id),
                _scrub(exc),
            )
            raise api_error(
                422, "unsupported_conflict_field",
                f"This conflict cannot be applied automatically: {exc}",
            )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error(
                "apply_cross_system_conflict failed for conflict %s: %s",
                _scrub(conflict_id),
                _scrub(exc),
            )
            raise api_error(
                502, "upstream_write_failed",
                f"Upstream write failed; conflict not resolved. Detail: {exc}"
            )
        db.commit()
        db.refresh(c)
        return _to_response(c, db)

    # Deletion markers + any other non-cross_system type: record-only resolution.
    c.resolution = payload.resolution
    c.resolved_value = json.dumps(_resolved_value(c, payload.resolution, payload.value))
    c.resolved_at = datetime.datetime.now(datetime.timezone.utc)
    if c.field_name == DELETION_FIELD:
        _cleanup_orphaned_mapping(db, c)
    db.commit()
    db.refresh(c)
    return _to_response(c, db)


@router.post("/conflicts/{conflict_id}/import", response_model=WizardExecuteResponse)
async def import_conflict_record(
    conflict_id: int,
    payload: ConflictImportRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> WizardExecuteResponse:
    """Scoped single-record import for new_filament / new_spool conflicts.

    Powers the "Add" button in the Conflicts UI (prompt #2).  Uses the same
    wizard/planner execute path as the Bulk Import Wizard — no create logic is
    duplicated.

    - dry_run=True returns a preview without writing anything.
    - On zero-failure execute: marks the conflict resolved (resolution="imported")
      and resolves any paired new_filament conflict.
    - On upstream failure: returns 502 and leaves the conflict open.

    Accepted for conflict types: new_filament, new_spool.
    """
    from app.core.compat import sync_compatibility_errors
    from app.core.single_record_import import (
        TareRequiredError,
        import_single_fdb_filament,
        import_single_sm_filament,
    )
    from app.api.wizard import (
        _resolve_container_parent_marker,
        _resolve_variant_keywords,
        _resolve_variant_parent_mode,
    )

    c = db.query(Conflict).filter_by(id=conflict_id).first()
    if c is None:
        raise api_error(404, "conflict_not_found", f"No conflict with id {conflict_id}")
    if c.resolved_at is not None:
        raise api_error(409, "already_resolved", f"Conflict {conflict_id} is already resolved")

    allowed_types = ("new_filament", "new_spool")
    if c.field_name not in allowed_types:
        raise api_error(
            400, "import_not_supported",
            f"Conflict {conflict_id} has field_name '{c.field_name}'; "
            f"import is only supported for: {', '.join(allowed_types)}",
        )

    spoolman = request.app.state.spoolman
    filamentdb = request.app.state.filamentdb

    # Version gate.
    blocked = await sync_compatibility_errors(spoolman, filamentdb)
    if blocked:
        raise api_error(
            409, "upstream_version_unsupported",
            "Sync disabled — " + "; ".join(blocked) + ".",
        )

    cycle_id = str(uuid.uuid4())
    precision = int(get_config_value(db, "weight_precision_decimals", 2))

    # Determine direction from the conflict ids.
    is_sm_to_fdb = c.spoolman_id is not None  # spoolman_id set → SM→FDB
    is_fdb_to_sm = not is_sm_to_fdb and c.filamentdb_filament_id is not None

    if not is_sm_to_fdb and not is_fdb_to_sm:
        raise api_error(400, "ambiguous_direction",
                        "Cannot determine import direction from conflict ids")

    sm_filament_id: int | None = None  # set in SM→FDB branch; used for paired-conflict cleanup

    try:
        if is_sm_to_fdb:
            # For new_spool conflicts the spoolman_id is the SPOOL id; we need
            # the FILAMENT id from the spool's filament attribute.
            sm_id = c.spoolman_id
            # Resolve to filament id: for new_filament conflicts spoolman_id IS
            # the filament id; for new_spool we must look it up from Spoolman.
            if c.field_name == "new_filament":
                sm_filament_id = sm_id
            else:
                # new_spool: resolve filament id from the live spool.
                try:
                    sm_spools_live = await spoolman.get_spools()
                    sm_spool_live = next((s for s in sm_spools_live if s.id == sm_id), None)
                    if sm_spool_live is None or sm_spool_live.filament is None:
                        raise api_error(
                            404, "spool_not_found",
                            f"Spoolman spool {sm_id} not found or has no filament",
                        )
                    sm_filament_id = sm_spool_live.filament.id
                except HTTPException:
                    raise
                except Exception as exc:
                    raise api_error(502, "upstream_fetch_failed",
                                    f"Could not resolve Spoolman spool to filament: {exc}")

            variant_parent_mode = _resolve_variant_parent_mode(db)
            variant_keywords = _resolve_variant_keywords(db)
            container_marker = _resolve_container_parent_marker(db)

            import_res = await import_single_sm_filament(
                db, cycle_id, spoolman, filamentdb,
                sm_filament_id,
                filament_action=payload.filament_action,
                filamentdb_id=payload.filamentdb_id,
                tare_override=payload.tare_override,
                master_filamentdb_id=payload.master_filamentdb_id,
                variant_parent_mode=variant_parent_mode if variant_parent_mode != "unset" else "promote_color",
                variant_keywords=variant_keywords,
                container_parent_marker=container_marker,
                precision=precision,
            )
            direction = "spoolman_to_filamentdb"
        else:
            fdb_fil_id = c.filamentdb_filament_id
            import_res = await import_single_fdb_filament(
                db, cycle_id, spoolman, filamentdb,
                fdb_fil_id,
                tare_override=payload.tare_override,
                require_tare=True,
                precision=precision,
                dry_run=payload.dry_run,
            )
            direction = "filamentdb_to_spoolman"
    except HTTPException:
        raise
    except TareRequiredError as exc:
        raise api_error(422, "tare_required", str(exc))
    except Exception as exc:
        import logging as _logging
        _logging.getLogger(__name__).error(
            "import_conflict_record %s: upstream error: %s", _scrub(conflict_id), _scrub(exc)
        )
        raise api_error(
            502, "upstream_write_failed",
            f"Import failed; conflict left open. Detail: {exc}",
        )

    if payload.dry_run:
        # Dry run: don't commit or resolve — just return the preview counts.
        db.rollback()
        _type_action_counts: dict[tuple[str, str], int] = {}
        for _r in import_res.records:
            _key = (_r.entity_type, _r.action)
            _type_action_counts[_key] = _type_action_counts.get(_key, 0) + 1
        return WizardExecuteResponse(
            cycle_id=cycle_id,
            direction=direction,
            created=import_res.created,
            updated=import_res.updated,
            skipped=import_res.skipped,
            failed=import_res.failed,
            wizard_completed=False,
            records=import_res.records,
            created_filaments=_type_action_counts.get(("filament", "created"), 0),
            created_spools=_type_action_counts.get(("spool", "created"), 0),
            updated_filaments=_type_action_counts.get(("filament", "updated"), 0),
            updated_spools=_type_action_counts.get(("spool", "updated"), 0),
            skipped_filaments=_type_action_counts.get(("filament", "skipped"), 0),
            skipped_spools=_type_action_counts.get(("spool", "skipped"), 0),
            failed_filaments=_type_action_counts.get(("filament", "failed"), 0),
            failed_spools=_type_action_counts.get(("spool", "failed"), 0),
        )

    if import_res.failed > 0:
        # Partial failure — commit what succeeded but leave conflict open.
        db.commit()
        raise api_error(
            502, "partial_import_failure",
            f"Import had {import_res.failed} failure(s); conflict left open. "
            "Check the records field for details.",
        )

    # Success: resolve this conflict and any paired new_filament conflict.
    _now = datetime.datetime.now(datetime.timezone.utc)
    c.resolution = "imported"
    c.resolved_value = json.dumps({"cycle_id": cycle_id})
    c.resolved_at = _now

    # Resolve paired new_filament conflict if this is a new_spool import.
    if c.field_name == "new_spool" and is_sm_to_fdb:
        paired = (
            db.query(Conflict)
            .filter(
                Conflict.resolved_at.is_(None),
                Conflict.entity_type == "filament",
                Conflict.field_name == "new_filament",
                Conflict.spoolman_id == sm_filament_id,  # type: ignore[possibly-undefined]
            )
            .first()
        )
        if paired is not None:
            paired.resolution = "imported"
            paired.resolved_value = json.dumps({"cycle_id": cycle_id})
            paired.resolved_at = _now
    elif c.field_name == "new_spool" and is_fdb_to_sm:
        paired_fdb = (
            db.query(Conflict)
            .filter(
                Conflict.resolved_at.is_(None),
                Conflict.entity_type == "filament",
                Conflict.field_name == "new_filament",
                Conflict.filamentdb_filament_id == c.filamentdb_filament_id,
            )
            .first()
        )
        if paired_fdb is not None:
            paired_fdb.resolution = "imported"
            paired_fdb.resolved_value = json.dumps({"cycle_id": cycle_id})
            paired_fdb.resolved_at = _now

    db.commit()

    _type_action_counts2: dict[tuple[str, str], int] = {}
    for _r in import_res.records:
        _key = (_r.entity_type, _r.action)
        _type_action_counts2[_key] = _type_action_counts2.get(_key, 0) + 1

    return WizardExecuteResponse(
        cycle_id=cycle_id,
        direction=direction,
        created=import_res.created,
        updated=import_res.updated,
        skipped=import_res.skipped,
        failed=import_res.failed,
        wizard_completed=False,
        records=import_res.records,
        created_filaments=_type_action_counts2.get(("filament", "created"), 0),
        created_spools=_type_action_counts2.get(("spool", "created"), 0),
        updated_filaments=_type_action_counts2.get(("filament", "updated"), 0),
        updated_spools=_type_action_counts2.get(("spool", "updated"), 0),
        skipped_filaments=_type_action_counts2.get(("filament", "skipped"), 0),
        skipped_spools=_type_action_counts2.get(("spool", "skipped"), 0),
        failed_filaments=_type_action_counts2.get(("filament", "failed"), 0),
        failed_spools=_type_action_counts2.get(("spool", "failed"), 0),
    )


@router.get("/conflicts/{conflict_id}/filament-suggestions", response_model=FilamentSuggestionsResponse)
async def get_filament_suggestions(
    conflict_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> FilamentSuggestionsResponse:
    """Return ranked FDB filament suggestions for the conflict Add "link" dropdown.

    Only valid for SM→FDB conflicts (spoolman_id set) with field_name in
    (new_filament, new_spool).

    Matching strategy (plan §5):
      1. Exact-key match via match_filaments (vendor+name+color normalised).
         Matched/ambiguous items get score 1.0.
      2. Fuzzy fallback (if step 1 yields nothing): rank ALL FDB filaments by a
         composite score built from the matcher's own normalizers:
           - vendor exact:  +0.5
           - base-name match: +0.3 (strip_color_and_words vs normalize_name)
           - color closeness: +0.2 (hex prefix similarity after normalize_color)
         Top ~8 results are returned, all with score < 1.0.
    """
    from app.core.matcher import (
        match_filaments,
        normalize_color,
        normalize_vendor,
        strip_color_and_words,
    )

    c = db.query(Conflict).filter_by(id=conflict_id).first()
    if c is None:
        raise api_error(404, "conflict_not_found", f"No conflict with id {conflict_id}")

    allowed_types = ("new_filament", "new_spool")
    if c.field_name not in allowed_types:
        raise api_error(
            400, "import_not_supported",
            f"Conflict {conflict_id} has field_name '{c.field_name}'; "
            f"filament suggestions only available for: {', '.join(allowed_types)}",
        )

    if c.spoolman_id is None:
        raise api_error(
            400, "fdb_to_sm_unsupported",
            "Filament suggestions are only available for Spoolman→Filament DB conflicts.",
        )

    spoolman = request.app.state.spoolman
    filamentdb = request.app.state.filamentdb

    # Resolve SM filament id from the conflict.
    if c.field_name == "new_filament":
        sm_filament_id = c.spoolman_id
    else:
        # new_spool: resolve filament id from the live spool.
        try:
            sm_spools_live = await spoolman.get_spools()
            sm_spool_live = next((s for s in sm_spools_live if s.id == c.spoolman_id), None)
            if sm_spool_live is None or sm_spool_live.filament is None:
                raise api_error(
                    404, "spool_not_found",
                    f"Spoolman spool {c.spoolman_id} not found or has no filament",
                )
            sm_filament_id = sm_spool_live.filament.id
        except HTTPException:
            raise
        except Exception as exc:
            raise api_error(502, "upstream_fetch_failed",
                            f"Could not resolve Spoolman spool to filament: {exc}")

    try:
        sm_filaments_all = await spoolman.get_filaments()
        fdb_filaments_all = await filamentdb.get_filaments()
    except Exception as exc:
        raise api_error(502, "upstream_fetch_failed", f"Could not fetch upstream data: {exc}")

    sm_fil = next((f for f in sm_filaments_all if f.id == sm_filament_id), None)
    if sm_fil is None:
        raise api_error(404, "filament_not_found",
                        f"Spoolman filament {sm_filament_id} not found")

    # ---- Detect master/synthetic containers ----
    from app.models.mapping import FilamentMapping as _FilamentMapping
    from app.api.wizard import _resolve_container_parent_marker

    synth_fdb_ids: set[str] = {
        m.filamentdb_id
        for m in db.query(_FilamentMapping).filter_by(is_synthetic_parent=True).all()
    }
    marker = _resolve_container_parent_marker(db)

    def _is_master(fdb) -> bool:
        if fdb.id in synth_fdb_ids:
            return True
        if getattr(fdb, "hasVariants", False):
            return True
        if marker and fdb.name and fdb.name.endswith(f" {marker}"):
            return True
        return False

    # ---- Step 1: exact-key match via match_filaments ----
    mr = match_filaments([sm_fil], fdb_filaments_all)

    suggestions: list[FilamentSuggestion] = []

    if mr.matched or mr.ambiguous:
        # Exact / ambiguous results all score 1.0.
        for pair in mr.matched:
            fdb = pair.fdb_filament
            suggestions.append(FilamentSuggestion(
                filamentdb_id=fdb.id,
                name=fdb.name,
                vendor=fdb.vendor,
                color=fdb.color,
                material=fdb.type,
                score=1.0,
                is_master_container=_is_master(fdb),
                parent_id=getattr(fdb, "parentId", None),
                variant_label=fdb.name,
            ))
        for _sm, cands in mr.ambiguous:
            for fdb in cands:
                suggestions.append(FilamentSuggestion(
                    filamentdb_id=fdb.id,
                    name=fdb.name,
                    vendor=fdb.vendor,
                    color=fdb.color,
                    material=fdb.type,
                    score=1.0,
                    is_master_container=_is_master(fdb),
                    parent_id=getattr(fdb, "parentId", None),
                    variant_label=fdb.name,
                ))
    else:
        # ---- Step 2: fuzzy fallback ----
        # Build score from existing normalizer functions only (no new algorithm).
        sm_vendor_norm = normalize_vendor(sm_fil.vendor.name if sm_fil.vendor else None)
        sm_base = strip_color_and_words(sm_fil.name or "", sm_fil.color_hex)
        sm_color_norm = normalize_color(sm_fil.color_hex)

        scored: list[tuple[float, object]] = []
        for fdb in fdb_filaments_all:
            score = 0.0
            fdb_vendor_norm = normalize_vendor(fdb.vendor)
            fdb_base = strip_color_and_words(fdb.name or "", fdb.color)
            fdb_color_norm = normalize_color(fdb.color)

            if sm_vendor_norm and fdb_vendor_norm and sm_vendor_norm == fdb_vendor_norm:
                score += 0.5
            if sm_base and fdb_base and sm_base == fdb_base:
                score += 0.3
            # Color closeness: prefix match on normalized hex (first 6 chars).
            if sm_color_norm and fdb_color_norm:
                sm_c6 = sm_color_norm[:6]
                fdb_c6 = fdb_color_norm[:6]
                if sm_c6 and fdb_c6 and sm_c6 == fdb_c6:
                    score += 0.2
                elif sm_color_norm[:3] == fdb_color_norm[:3]:
                    score += 0.1

            if score > 0:
                scored.append((score, fdb))

        scored.sort(key=lambda t: t[0], reverse=True)
        for score, fdb in scored[:8]:
            suggestions.append(FilamentSuggestion(
                filamentdb_id=fdb.id,
                name=fdb.name,
                vendor=fdb.vendor,
                color=fdb.color,
                material=fdb.type,
                score=score,
                is_master_container=_is_master(fdb),
                parent_id=getattr(fdb, "parentId", None),
                variant_label=fdb.name,
            ))

    # Sort by score descending then name.
    suggestions.sort(key=lambda s: (-s.score, s.name or ""))
    return FilamentSuggestionsResponse(suggestions=suggestions)


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
async def bulk_resolve(
    payload: BulkResolveRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> BulkResolveResponse:
    if payload.resolution == "manual" and payload.value is None:
        raise api_error(422, "manual_value_required", "A manual resolution requires a value")

    from app.core.conflict_apply import apply_cross_system_conflict
    import logging

    spoolman = request.app.state.spoolman
    filamentdb = request.app.state.filamentdb
    now = datetime.datetime.now(datetime.timezone.utc)
    resolved = 0
    skipped: list[int] = []
    failed: list[int] = []
    # Commit per conflict so one upstream-write failure isolates to that conflict
    # (failure-isolation), leaving already-converged conflicts committed.
    for cid in payload.ids:
        c = db.query(Conflict).filter_by(id=cid).first()
        if c is None or c.resolved_at is not None:
            skipped.append(cid)
            continue
        conflict_type = getattr(c, "conflict_type", "cross_system") or "cross_system"
        try:
            if conflict_type == "cross_system" and c.field_name != DELETION_FIELD:
                # Converge: write the chosen value to BOTH systems + refresh snapshots
                # (same path as the per-row resolve endpoint, #21).
                await apply_cross_system_conflict(
                    c, payload.resolution, payload.value, db, spoolman, filamentdb
                )
            else:
                # Deletion markers + master_divergence + others: record-only resolution
                # (unchanged — master_divergence needs a per-row action; nothing to
                # write upstream for a deletion marker).
                c.resolution = payload.resolution
                c.resolved_value = json.dumps(_resolved_value(c, payload.resolution, payload.value))
                c.resolved_at = now
                if c.field_name == DELETION_FIELD:
                    _cleanup_orphaned_mapping(db, c)
            db.commit()
            resolved += 1
        except Exception as exc:  # noqa: BLE001
            # Upstream write failed or field unsupported → isolate to this conflict,
            # leave it open, keep going. (Partial upstream writes have the same
            # inherent risk as the per-row resolve path.)
            db.rollback()
            failed.append(cid)
            logging.getLogger(__name__).warning(
                "bulk-resolve: conflict %s not converged (left open): %s",
                _scrub(cid), _scrub(exc),
            )
    return BulkResolveResponse(resolved=resolved, skipped=skipped, failed=failed)
