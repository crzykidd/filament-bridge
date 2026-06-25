"""Standalone bulk tare-weight editor (FR-23 / issue #26).

GET  /api/tare        — list mapped filaments with current both-side tare + edit state
POST /api/tare/bulk   — set tare for a batch of filaments (writes both sides)

All tare logic lives in ``core/tare.py`` so the write path (both-sides + snapshot
refresh, anti-ping-pong) is reused, not duplicated.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.errors import api_error
from app.core import tare as tare_core
from app.core.compat import sync_compatibility_errors
from app.db import get_db

router = APIRouter()


class TareRow(BaseModel):
    filament_mapping_id: int
    spoolman_filament_id: int
    filamentdb_id: str
    name: str | None = None
    vendor: str | None = None
    role: str
    editable: bool
    spoolman_tare: float | None = None
    filamentdb_tare: float | None = None
    effective_tare: float | None = None
    is_overridden: bool = False
    parent_name: str | None = None
    status: str


class TareListResponse(BaseModel):
    rows: list[TareRow]


class TareUpdate(BaseModel):
    filament_mapping_id: int
    tare_grams: float = Field(ge=0)


class TareBulkRequest(BaseModel):
    updates: list[TareUpdate] = Field(min_length=1)


class TareFailure(BaseModel):
    filament_mapping_id: int | None = None
    error: str


class TareBulkResponse(BaseModel):
    updated: int
    failed: list[TareFailure]


@router.get("/tare", response_model=TareListResponse)
async def list_tare(request: Request, db: Session = Depends(get_db)) -> TareListResponse:
    """List every mapped filament with its current tare on both sides (FR-23)."""
    rows = await tare_core.build_tare_rows(
        db, request.app.state.spoolman, request.app.state.filamentdb
    )
    return TareListResponse(rows=[TareRow(**r) for r in rows])


@router.post("/tare/bulk", response_model=TareBulkResponse)
async def bulk_set_tare(
    body: TareBulkRequest, request: Request, db: Session = Depends(get_db)
) -> TareBulkResponse:
    """Set tare for a batch of filaments, writing both sides (FR-23).

    Hard-gated on upstream compatibility (same as the sync trigger / wizard execute),
    since it writes to both upstream systems.
    """
    blocked = await sync_compatibility_errors(
        request.app.state.spoolman, request.app.state.filamentdb
    )
    if blocked:
        raise api_error(
            409, "upstream_version_unsupported",
            "Tare editing disabled — " + "; ".join(blocked) + ".",
        )

    result = await tare_core.apply_tare_bulk(
        db,
        [u.model_dump() for u in body.updates],
        request.app.state.spoolman,
        request.app.state.filamentdb,
    )
    return TareBulkResponse(**result)
