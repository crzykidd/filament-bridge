"""GET /api/reconcile — read-only cross-system filament reconcile report.

Fetches all filaments from both Spoolman and Filament DB, runs the same
matcher used by the Bulk Import Wizard, and returns four buckets:
  matched         — filaments paired on both sides
  only_in_spoolman — SM filaments with no FDB counterpart
  only_in_filamentdb — FDB filaments with no SM counterpart
  ambiguous       — one SM filament with multiple FDB candidates

This endpoint is purely read-only: it writes nothing, links nothing, and
resolves nothing. Acting on a missing item is the Bulk Import Wizard's job.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.wizard import _fdb_ref, _sm_ref
from app.config import settings as _settings
from app.core.matcher import match_filaments
from app.db import get_db
from app.schemas.api import (
    AmbiguousRow,
    ReconcileMatchRow,
    ReconcileMissingRow,
    ReconcileResponse,
    ReconcileSummary,
)
from app.schemas.spoolman import decode_extra_value

router = APIRouter()


@router.get("/reconcile", response_model=ReconcileResponse)
async def get_reconcile(
    request: Request,
    db: Session = Depends(get_db),
) -> ReconcileResponse:
    """Return a read-only reconcile report comparing both upstream systems."""

    sm_filaments = await request.app.state.spoolman.get_filaments()
    fdb_filaments = await request.app.state.filamentdb.get_filaments()

    # Fetch all SM spools (active + archived) to build the cross-ref map.
    sm_spools = await request.app.state.spoolman.get_spools()

    # ---------------------------------------------------------------------------
    # Build xref map: {sm_filament_id: fdb_filament_id}
    # Mirrors the block in wizard.py:343-359 verbatim.
    # ---------------------------------------------------------------------------
    xref_by_sm_filament: dict[int, str] = {}
    fdb_id_field = _settings.spoolman_field_filamentdb_id
    for spool in sm_spools:
        # Include archived spools — a cross-ref on an archived spool still links its
        # filament to FDB.
        if spool.filament is None:
            continue
        raw = (spool.extra or {}).get(fdb_id_field)
        fdb_id = decode_extra_value(raw)
        if not fdb_id or not isinstance(fdb_id, str):
            continue
        # First non-empty cross-ref per filament wins.
        xref_by_sm_filament.setdefault(spool.filament.id, fdb_id)

    mr = match_filaments(
        sm_filaments,
        fdb_filaments,
        xref_by_sm_filament=xref_by_sm_filament or None,
    )

    # ---------------------------------------------------------------------------
    # Spool roll-ups — SM side
    # ---------------------------------------------------------------------------
    sm_spool_count: dict[int, int] = {}
    sm_spool_weight: dict[int, float | None] = {}
    for spool in sm_spools:
        if spool.filament is None:
            continue
        fid = spool.filament.id
        sm_spool_count[fid] = sm_spool_count.get(fid, 0) + 1
        if spool.remaining_weight is not None:
            prev = sm_spool_weight.get(fid)
            sm_spool_weight[fid] = (prev or 0.0) + spool.remaining_weight
        else:
            # At least one spool has no weight — keep existing sum but mark as
            # incomplete only if we have never seen a non-None weight.
            if fid not in sm_spool_weight:
                sm_spool_weight[fid] = None

    # ---------------------------------------------------------------------------
    # Spool roll-ups — FDB side (spools embedded on each filament)
    # ---------------------------------------------------------------------------
    fdb_spool_count: dict[str, int] = {}
    fdb_spool_weight: dict[str, float | None] = {}
    for fil in fdb_filaments:
        spools = fil.spools or []
        fdb_spool_count[fil.id] = len(spools)
        total: float | None = None
        for sp in spools:
            if sp.totalWeight is not None:
                total = (total or 0.0) + sp.totalWeight
        fdb_spool_weight[fil.id] = total

    # ---------------------------------------------------------------------------
    # `linked` flag: True when the pair came from xref pre-pass.
    # A pair is xref-linked iff the SM filament id appears in xref_by_sm_filament
    # AND the stored FDB id matches the paired FDB filament id.
    # ---------------------------------------------------------------------------
    def _is_linked(sm_id: int, fdb_id: str) -> bool:
        return xref_by_sm_filament.get(sm_id) == fdb_id

    # ---------------------------------------------------------------------------
    # Assemble response
    # ---------------------------------------------------------------------------
    matched_rows: list[ReconcileMatchRow] = [
        ReconcileMatchRow(
            spoolman=_sm_ref(p.spoolman_filament),
            filamentdb=_fdb_ref(p.fdb_filament),
            confidence=p.confidence,
            linked=_is_linked(p.spoolman_filament.id, p.fdb_filament.id),
            spoolman_spools=sm_spool_count.get(p.spoolman_filament.id, 0),
            filamentdb_spools=fdb_spool_count.get(p.fdb_filament.id, 0),
            spoolman_weight=sm_spool_weight.get(p.spoolman_filament.id),
            filamentdb_weight=fdb_spool_weight.get(p.fdb_filament.id),
        )
        for p in mr.matched
    ]

    only_sm_rows: list[ReconcileMissingRow] = [
        ReconcileMissingRow(
            ref=_sm_ref(sm),
            spool_count=sm_spool_count.get(sm.id, 0),
            weight_total=sm_spool_weight.get(sm.id),
        )
        for sm in mr.unmatched_spoolman
    ]

    only_fdb_rows: list[ReconcileMissingRow] = [
        ReconcileMissingRow(
            ref=_fdb_ref(fdb),
            spool_count=fdb_spool_count.get(fdb.id, 0),
            weight_total=fdb_spool_weight.get(fdb.id),
        )
        for fdb in mr.unmatched_fdb
    ]

    ambiguous_rows: list[AmbiguousRow] = [
        AmbiguousRow(spoolman=_sm_ref(sm), candidates=[_fdb_ref(f) for f in cands])
        for sm, cands in mr.ambiguous
    ]

    summary = ReconcileSummary(
        spoolman_filaments=len(sm_filaments),
        filamentdb_filaments=len(fdb_filaments),
        matched=len(matched_rows),
        only_in_spoolman=len(only_sm_rows),
        only_in_filamentdb=len(only_fdb_rows),
        ambiguous=len(ambiguous_rows),
    )

    return ReconcileResponse(
        summary=summary,
        matched=matched_rows,
        only_in_spoolman=only_sm_rows,
        only_in_filamentdb=only_fdb_rows,
        ambiguous=ambiguous_rows,
    )
