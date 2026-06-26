"""GET/PATCH /api/mobile/* — mobile scan-and-update endpoints (phase 1).

A printed QR encodes the Filament DB filament id + spool id; scanning it lands on
the mobile page, which reads a spool's live detail (GET) and writes a scale weight
and/or a location change in one Save (PATCH). Writes go to Filament DB + Spoolman
and refresh both snapshots so the next auto-sync cycle doesn't re-detect a change.

The whole feature is gated by ``mobile_labels_enabled`` (default OFF): every route
here depends on ``_require_labels_enabled`` and returns 403 when the flag is off
(mirrors ``api/debug.py:_require_debug_mode``). Auth mirrors the rest of the app —
the router is included with the normal ``_auth_dep`` in ``main.py``; there is no
special public router.

Endpoints:
  GET   /api/mobile/spool/{fil}/{spool}  → assembled MobileSpoolDetail (404 if no mapping)
  PATCH /api/mobile/spool/{fil}/{spool}  → apply weight (per mode) and/or location, return detail
  GET   /api/mobile/locations            → sorted distinct location names (FDB + SM) for a datalist
"""

from __future__ import annotations

import logging
import re
import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.config import mobile_labels_enabled, mobile_weight_default_mode
from app.api.mappings import build_mapping_rows
from app.api.errors import api_error
from app.core.locations import ensure_fdb_location
from app.core.mobile import assemble_spool_detail, resolve_spool_mapping
from app.core.weight import DEFAULT_TARE_GRAMS
from app.core.weight_ops import apply_absolute_weight
from app.db import get_db
from app.schemas.api import MobileSpoolDetail, MobileSpoolSearchResult, MobileSpoolUpdateRequest

logger = logging.getLogger(__name__)

router = APIRouter()


def _require_labels_enabled(db: Session = Depends(get_db)) -> None:
    """Raise 403 unless mobile_labels_enabled is currently true."""
    if not mobile_labels_enabled(db):
        raise api_error(
            403,
            "mobile_labels_disabled",
            "The mobile updates & labels feature is disabled. Enable it via "
            "PUT /api/config with mobile_labels_enabled=true.",
        )


# A scanned QR id is an opaque record id (a Filament DB ObjectId in practice). It is
# constrained to this allowlist before it is ever interpolated into a redirect URL.
_QR_ID_RE = re.compile(r"\A[A-Za-z0-9_-]+\Z")


def qr_redirect_url(target: str, fil: str, spool: str, *, filamentdb_url: str) -> str:
    """Build the ``/r/{fil}/{spool}`` 302 target, validating the path ids first.

    ``fil``/``spool`` arrive straight off the URL path (a scanned QR label), so they
    are constrained to an id-shaped allowlist (``[A-Za-z0-9_-]``) before being
    interpolated into the redirect URL — anything else 404s. The allowlist excludes
    every character needed to break out of the intended destination (``/``, ``\\``,
    ``:``, ``.``, ``%``), so no protocol-relative ``//host``, absolute ``scheme:`` URL,
    or ``..`` path escape is constructible (open redirect / path injection,
    CWE-601 / CWE-22).
    """
    if not _QR_ID_RE.match(fil) or not _QR_ID_RE.match(spool):
        raise api_error(404, "not_found", "Unknown spool.")
    if target == "filamentdb":
        return f"{filamentdb_url}/filaments/{fil}"
    return f"/scan/{fil}/{spool}"


@router.get(
    "/mobile/spool/{fil}/{spool}",
    response_model=MobileSpoolDetail,
    dependencies=[Depends(_require_labels_enabled)],
)
async def get_mobile_spool(
    fil: str,
    spool: str,
    request: Request,
    db: Session = Depends(get_db),
) -> MobileSpoolDetail:
    """Return the assembled live detail for the spool identified by FDB ids."""
    detail = await assemble_spool_detail(
        db, request.app.state.spoolman, request.app.state.filamentdb,
        fdb_fil_id=fil, fdb_spool_id=spool,
    )
    if detail is None:
        raise api_error(
            404, "spool_not_mapped",
            f"No bridge mapping found for Filament DB spool {spool}.",
        )
    return detail


@router.patch(
    "/mobile/spool/{fil}/{spool}",
    response_model=MobileSpoolDetail,
    dependencies=[Depends(_require_labels_enabled)],
)
async def update_mobile_spool(
    fil: str,
    spool: str,
    payload: MobileSpoolUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> MobileSpoolDetail:
    """Apply a scale weight (gross) and/or a location change in one Save.

    Weight save mode = ``payload.weight_mode`` else the configured default. After
    any write both snapshots are refreshed (the weight_ops helpers do this) so the
    next auto-sync cycle sees no fresh change.
    """
    spoolman = request.app.state.spoolman
    filamentdb = request.app.state.filamentdb

    mapping = resolve_spool_mapping(db, spool)
    if mapping is None:
        raise api_error(
            404, "spool_not_mapped",
            f"No bridge mapping found for Filament DB spool {spool}.",
        )
    sm_spool_id = mapping.spoolman_spool_id

    # Fetch the FDB filament once for the tare + current gross.
    fdb_detail = await filamentdb.get_filament(fil)
    tare = fdb_detail.spoolWeight
    if tare is None:
        tare = DEFAULT_TARE_GRAMS
    tare = float(tare)
    fdb_spool = next((s for s in fdb_detail.spools if s.id == spool), None)
    current_gross = (
        float(fdb_spool.totalWeight)
        if fdb_spool and fdb_spool.totalWeight is not None
        else tare
    )

    cycle_id = f"mobile-{uuid.uuid4().hex[:8]}"
    did_write = False

    # --- Weight ---
    if payload.gross_grams is not None:
        mode = payload.weight_mode or mobile_weight_default_mode(db)
        net = round(max(float(payload.gross_grams) - tare, 0.0), 2)
        # Both modes converge the spool to the absolute net weight. Filament DB can
        # only RAISE totalWeight directly; LOWERING it always goes through a usage
        # entry (its only mechanism), so the mode only flavours that entry's label /
        # source — a scale "correction" vs a "usage" decrement (#28).
        if mode == "usage":
            src, label = "mobile-scale", "Mobile scale usage"
        else:  # direct_correction
            src, label = "mobile-scale-correction", "Mobile scale correction"
        await apply_absolute_weight(
            db, spoolman, filamentdb,
            sm_spool_id=sm_spool_id, fdb_fil_id=fil, fdb_spool_id=spool,
            net_w=net, tare=tare, current_fdb_gross=current_gross,
            cycle_id=cycle_id, source=src, job_label=label, old_value=current_gross,
        )
        did_write = True

    # --- Location ---
    if payload.location is not None and payload.location.strip():
        name = payload.location.strip()
        loc_id = await ensure_fdb_location(filamentdb, name)
        if loc_id:
            await filamentdb.update_spool(fil, spool, {"locationId": loc_id})
        await spoolman.update_spool(sm_spool_id, {"location": name})
        # Refresh both snapshots' location bit (anti-ping-pong).
        from app.core.engine import _merge_snapshot
        _merge_snapshot(db, "spoolman", "spool", str(sm_spool_id), {"location": name})
        _merge_snapshot(db, "filamentdb", "spool", spool, {"locationId": loc_id})
        did_write = True

    if did_write:
        db.commit()

    # Return the refreshed detail (live re-fetch).
    detail = await assemble_spool_detail(
        db, spoolman, filamentdb, fdb_fil_id=fil, fdb_spool_id=spool,
    )
    if detail is None:  # pragma: no cover - mapping existed above
        raise api_error(404, "spool_not_mapped", f"No bridge mapping found for spool {spool}.")
    return detail


@router.get(
    "/mobile/spools",
    response_model=list[MobileSpoolSearchResult],
    dependencies=[Depends(_require_labels_enabled)],
)
async def search_mobile_spools(
    q: str = Query(default="", description="Case-insensitive substring filter (name/vendor/color/spool #)."),
    db: Session = Depends(get_db),
) -> list[MobileSpoolSearchResult]:
    """Search mapped spools for the scan-page search box.

    Returns only spool rows (kind="spool") that have both FDB ids set — the same
    rows the mobile update card can handle.  Filtering is done server-side by a
    case-insensitive substring match across name, vendor, color hex, and Spoolman
    spool id.  An empty ``q`` returns all matched spools (capped at 200 to keep
    the response lightweight for homelab-scale libraries).
    """
    rows = build_mapping_rows(db)
    # Only spool rows with both FDB ids are navigable.
    selectable = [
        r for r in rows
        if r.kind == "spool" and r.filamentdb_filament_id and r.filamentdb_spool_id
    ]
    if q.strip():
        needle = q.strip().lower()
        selectable = [
            r for r in selectable
            if (r.name or "").lower().find(needle) != -1
            or (r.vendor or "").lower().find(needle) != -1
            or (r.color or "").lower().find(needle) != -1
            or str(r.spoolman_spool_id or "").find(needle) != -1
        ]
    return [
        MobileSpoolSearchResult(
            filamentdb_filament_id=r.filamentdb_filament_id,
            filamentdb_spool_id=r.filamentdb_spool_id,  # type: ignore[arg-type]
            spoolman_spool_id=r.spoolman_spool_id,  # type: ignore[arg-type]
            name=r.name,
            vendor=r.vendor,
            color=r.color,
            multi_color_hexes=r.multi_color_hexes,
            multi_color_direction=r.multi_color_direction,
        )
        for r in selectable[:200]
    ]


@router.get(
    "/mobile/locations",
    response_model=list[str],
    dependencies=[Depends(_require_labels_enabled)],
)
async def get_mobile_locations(request: Request) -> list[str]:
    """Return sorted distinct known location names (FDB locations + SM spool locations)."""
    spoolman = request.app.state.spoolman
    filamentdb = request.app.state.filamentdb

    names: set[str] = set()
    try:
        for loc in await filamentdb.get_locations():
            n = loc.get("name")
            if n:
                names.add(n)
    except Exception as exc:  # noqa: BLE001
        logger.warning("mobile/locations: could not fetch FDB locations: %s", exc)

    try:
        for sp in await spoolman.get_spools():
            if sp.location:
                names.add(sp.location)
    except Exception as exc:  # noqa: BLE001
        logger.warning("mobile/locations: could not fetch SM spools: %s", exc)

    return sorted(names)
