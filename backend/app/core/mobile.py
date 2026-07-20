"""Mobile scan-and-update assembly (phase 1).

Resolves a printed-QR identity (Filament DB filament id + spool id) to the bridge
``SpoolMapping``, then live-fetches both upstream records (fresher than the
snapshot-based mapping rows) and assembles the detail payload the mobile page
shows: brand, color, label number, the gross/net/tare weights, and the location.

Live fetch order:
  * ``filamentdb.get_filament(fil_id)`` → the FDB filament detail (carries the
    spool subdocs + ``spoolWeight`` tare).  The spool is picked from ``spools[]``
    by ``_id``.
  * ``spoolman.get_spool(sm_id)`` → the Spoolman spool (carries vendor/brand,
    color hex, net remaining weight, free-text location).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.api.config import mobile_weight_default_mode
from app.core.weight import DEFAULT_TARE_GRAMS
from app.models.mapping import SpoolMapping
from app.schemas.api import MobileSpoolDetail
from app.schemas.filamentdb import FDBFilamentDetail, FDBSpoolDetail
from app.services.filamentdb import FilamentDBClient
from app.services.spoolman import SpoolmanClient


def resolve_spool_mapping(db: Session, fdb_spool_id: str) -> SpoolMapping | None:
    """Return the SpoolMapping for an FDB spool subdocument id, or None."""
    return (
        db.query(SpoolMapping)
        .filter(SpoolMapping.filamentdb_spool_id == fdb_spool_id)
        .first()
    )


def _pick_spool(detail: FDBFilamentDetail, fdb_spool_id: str) -> FDBSpoolDetail | None:
    for s in detail.spools:
        if s.id == fdb_spool_id:
            return s
    return None


async def assemble_spool_detail(
    db: Session,
    spoolman: SpoolmanClient,
    filamentdb: FilamentDBClient,
    *,
    fdb_fil_id: str,
    fdb_spool_id: str,
) -> MobileSpoolDetail | None:
    """Resolve + live-assemble the mobile detail payload, or None if unmapped.

    Returns None when no SpoolMapping exists for ``fdb_spool_id`` (endpoint → 404).
    Raises on upstream fetch failure (endpoint → 502 / surfaced error).
    """
    mapping = resolve_spool_mapping(db, fdb_spool_id)
    if mapping is None:
        return None

    sm_spool_id = mapping.spoolman_spool_id

    sm_spool = await spoolman.get_spool(sm_spool_id)
    fdb_detail = await filamentdb.get_filament(fdb_fil_id)

    fdb_spool = _pick_spool(fdb_detail, fdb_spool_id)

    # Tare = FDB filament.spoolWeight (default when missing — same as the engine).
    tare = fdb_detail.spoolWeight
    if tare is None:
        tare = DEFAULT_TARE_GRAMS
    tare = float(tare)

    gross = float(fdb_spool.totalWeight) if fdb_spool and fdb_spool.totalWeight is not None else None
    net = float(sm_spool.remaining_weight) if sm_spool.remaining_weight is not None else None

    sm_fil = sm_spool.filament
    brand = sm_fil.vendor.name if sm_fil.vendor else None
    # Color name: prefer the FDB filament's colorName, then the SM filament name.
    color_name = fdb_detail.colorName or sm_fil.name
    color_hex = sm_fil.color_hex or fdb_detail.color
    material = sm_fil.material or fdb_detail.type

    _dry_temp = getattr(fdb_detail, "dryingTemperature", None)
    _dry_time = getattr(fdb_detail, "dryingTime", None)
    # Derive last-dried + count from the spool's dryCycles array (the canonical source
    # on the detail view). FDB's convenience lastDriedAt/dryCycleCount fields are
    # computed and not reliably present on GET /api/filaments/:id, so we don't read
    # them. Newest cycle date wins — matching FDB's own "last dried" semantics.
    _cycles = getattr(fdb_spool, "dryCycles", None) if fdb_spool else None
    _cycles = _cycles if isinstance(_cycles, list) else []
    _cycle_dates = [c.get("date") for c in _cycles if isinstance(c, dict) and c.get("date")]
    _last_dried = max(_cycle_dates) if _cycle_dates else None
    _dry_count = len(_cycles) if _cycles else None

    is_retired = bool(fdb_spool.retired) if fdb_spool is not None else False

    return MobileSpoolDetail(
        filamentdb_filament_id=fdb_fil_id,
        filamentdb_spool_id=fdb_spool_id,
        spoolman_spool_id=sm_spool_id,
        spoolman_filament_id=sm_fil.id,
        number=sm_spool_id,
        filamentdb_name=fdb_detail.name,
        brand=brand,
        color_name=color_name,
        color_hex=color_hex,
        material=material,
        gross=gross,
        net=net,
        tare=tare,
        location=sm_spool.location,
        weight_default_mode=mobile_weight_default_mode(db),  # type: ignore[arg-type]
        last_dried_at=str(_last_dried) if _last_dried is not None else None,
        dry_cycle_count=int(_dry_count) if _dry_count is not None else None,
        recommended_drying_temp_c=int(_dry_temp) if _dry_temp is not None else None,
        recommended_drying_time_min=int(_dry_time) if _dry_time is not None else None,
        is_retired=is_retired,
    )
