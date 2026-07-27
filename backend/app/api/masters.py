"""Master-defaults backfill screen (issue #76).

GET  /api/masters/defaults        — list every master with current vs proposed
                                     (group-mode) values for the six shared fields
POST /api/masters/defaults/apply  — fill a batch of requested (still-null) fields

All logic lives in ``core/masters_backfill.py`` so the write path (fill-null-only,
both-sides write + snapshot refresh, anti-ping-pong) is reused, not duplicated.
Nothing here writes unless the user explicitly requests a field via the apply
endpoint — this is a manual-review screen, not an automatic backfill.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.errors import api_error
from app.core import masters_backfill
from app.core.compat import sync_compatibility_errors
from app.db import get_db

router = APIRouter()


class MasterFieldRow(BaseModel):
    current: Any = None
    current_sm: Any = None
    proposal: Any = None
    would_fill: bool = False
    breakdown: list[dict] = Field(default_factory=list)


class MasterDefaultRow(BaseModel):
    filamentdb_id: str
    name: str | None = None
    vendor: str | None = None
    is_synthetic: bool = False
    spoolman_filament_id: int | None = None
    variant_count: int = 0
    fields: dict[str, MasterFieldRow]


class MasterDefaultsResponse(BaseModel):
    rows: list[MasterDefaultRow]


class MasterDefaultsUpdate(BaseModel):
    filamentdb_id: str
    fields: list[str] = Field(min_length=1)


class MasterDefaultsApplyRequest(BaseModel):
    updates: list[MasterDefaultsUpdate] = Field(min_length=1)


class MasterDefaultsFailure(BaseModel):
    filamentdb_id: str | None = None
    error: str


class MasterDefaultsApplyResponse(BaseModel):
    updated: int
    failed: list[MasterDefaultsFailure]


@router.get("/masters/defaults", response_model=MasterDefaultsResponse)
async def list_master_defaults(
    request: Request, db: Session = Depends(get_db)
) -> MasterDefaultsResponse:
    """List every master (real or synthetic) with current-vs-proposed field values."""
    rows = await masters_backfill.build_master_default_rows(
        db, request.app.state.spoolman, request.app.state.filamentdb
    )
    return MasterDefaultsResponse(rows=[MasterDefaultRow(**r) for r in rows])


@router.post("/masters/defaults/apply", response_model=MasterDefaultsApplyResponse)
async def apply_master_defaults(
    body: MasterDefaultsApplyRequest, request: Request, db: Session = Depends(get_db)
) -> MasterDefaultsApplyResponse:
    """Fill the requested still-null fields on a batch of masters (FR-76).

    Hard-gated on upstream compatibility, same as the tare editor and wizard
    execute, since a non-synthetic master's fill also writes to Spoolman.
    """
    blocked = await sync_compatibility_errors(
        request.app.state.spoolman, request.app.state.filamentdb
    )
    if blocked:
        raise api_error(
            409, "upstream_version_unsupported",
            "Master-defaults backfill disabled — " + "; ".join(blocked) + ".",
        )

    result = await masters_backfill.apply_master_defaults_bulk(
        db,
        [u.model_dump() for u in body.updates],
        request.app.state.spoolman,
        request.app.state.filamentdb,
    )
    return MasterDefaultsApplyResponse(**result)
