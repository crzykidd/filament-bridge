"""Shared single-record import helper (FR-new-record-handling).

Wraps the wizard's _execute_spoolman_to_fdb / _execute_fdb_to_spoolman for
a SINGLE filament, so the ongoing engine auto-import paths and the
POST /api/conflicts/{id}/import endpoint share exactly one create-path.

The wizard endpoint behavior is byte-identical: this is a thin scoping
wrapper (single-element filament list), not a refactor of the execute bodies.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


async def import_single_sm_filament(
    db: Session,
    cycle_id: str,
    spoolman: Any,
    filamentdb: Any,
    sm_filament_id: int,
    *,
    filament_action: str = "create",        # "create" | "link"
    filamentdb_id: str | None = None,       # for "link": existing FDB filament id
    tare_override: float | None = None,     # optional tare override for all spools
    master_filamentdb_id: str | None = None, # if set, created filament becomes a variant child
    variant_parent_mode: str = "promote_color",
    variant_keywords: list[str] | None = None,
    container_parent_marker: str = "(Master)",
    precision: int = 2,
    include_empty_spools: bool = True,
) -> "Any":  # returns _ExecResult from wizard
    """Import a single Spoolman filament (and its spools) into Filament DB.

    Calls the wizard's _execute_spoolman_to_fdb scoped to one SM filament.
    Returns the _ExecResult accumulator.

    Raises on any unrecoverable setup failure (upstream fetch, unknown filament).
    Per-record write failures are captured in the _ExecResult (action="failed").
    """
    # Import here to avoid circular imports (wizard imports from engine).
    from app.api.wizard import (
        _ExecResult,
        _execute_spoolman_to_fdb,
    )

    direction = "spoolman_to_filamentdb"
    res = _ExecResult(cycle_id=cycle_id, direction=direction)

    # Fetch upstream state scoped to what we need.
    sm_filaments_all = await spoolman.get_filaments()
    sm_spools_all = await spoolman.get_spools()
    fdb_filaments_all = await filamentdb.get_filaments()

    # Scope to the single SM filament.
    sm_fil = next((f for f in sm_filaments_all if f.id == sm_filament_id), None)
    if sm_fil is None:
        raise ValueError(f"Spoolman filament {sm_filament_id} not found")

    sm_filaments = [sm_fil]
    sm_spools = [s for s in sm_spools_all if s.filament and s.filament.id == sm_filament_id]

    # Build decisions dict for the single filament.
    if filament_action == "link" and filamentdb_id:
        decisions_by_sm = {
            sm_filament_id: {
                "spoolman_filament_id": sm_filament_id,
                "action": "link",
                "filamentdb_id": filamentdb_id,
            }
        }
    else:
        decisions_by_sm = {
            sm_filament_id: {
                "spoolman_filament_id": sm_filament_id,
                "action": "create",
                "filamentdb_id": None,
            }
        }

    # master_of_sm: empty (no wizard-level variant grouping for single-record import).
    master_of_sm: dict[int, int] = {}
    # attach_parent_for_sm: if caller supplies master_filamentdb_id, this filament becomes a child.
    attach_parent_for_sm: dict[int, str] = {}
    if master_filamentdb_id:
        attach_parent_for_sm[sm_filament_id] = master_filamentdb_id

    # tare_by_sm_spool: apply tare_override to all spools of this filament if supplied.
    tare_by_sm_spool: dict[int, float] = {}
    if tare_override is not None:
        for s in sm_spools:
            tare_by_sm_spool[s.id] = tare_override

    await _execute_spoolman_to_fdb(
        db, res, spoolman, filamentdb,
        sm_filaments, sm_spools, fdb_filaments_all,
        decisions_by_sm, master_of_sm, attach_parent_for_sm, tare_by_sm_spool,
        reconcile_by_master=None,
        precision=precision,
        include_empty_spools=include_empty_spools,
        variant_parent_mode=variant_parent_mode,
        variant_keywords=variant_keywords,
        container_parent_marker=container_parent_marker,
        container_name_overrides=None,
    )
    return res


async def import_single_fdb_filament(
    db: Session,
    cycle_id: str,
    spoolman: Any,
    filamentdb: Any,
    fdb_filament_id: str,
    *,
    spoolman_filament_id: int | None = None,  # for "link": existing SM filament id
    tare_override: float | None = None,
    precision: int = 2,
) -> "Any":  # returns _ExecResult from wizard
    """Import a single FDB filament (and its spools) into Spoolman.

    Calls the wizard's _execute_fdb_to_spoolman scoped to one FDB filament.
    Returns the _ExecResult accumulator.
    """
    from app.api.wizard import (
        _ExecResult,
        _execute_fdb_to_spoolman,
    )

    direction = "filamentdb_to_spoolman"
    res = _ExecResult(cycle_id=cycle_id, direction=direction)

    sm_filaments_all = await spoolman.get_filaments()
    fdb_filaments_all = await filamentdb.get_filaments()

    fdb_fil = next((f for f in fdb_filaments_all if f.id == fdb_filament_id), None)
    if fdb_fil is None:
        raise ValueError(f"FDB filament {fdb_filament_id} not found")

    fdb_filaments = [fdb_fil]

    # Build decisions dict: if caller supplies spoolman_filament_id → "link".
    if spoolman_filament_id is not None:
        decisions_by_sm = {
            spoolman_filament_id: {
                "spoolman_filament_id": spoolman_filament_id,
                "action": "link",
                "filamentdb_id": fdb_filament_id,
            }
        }
    else:
        decisions_by_sm = {}

    parent_of_fdb: dict[str, str] = {}
    tare_by_fdb_spool: dict[str, float] = {}
    if tare_override is not None:
        for spool in fdb_fil.spools:
            tare_by_fdb_spool[spool.id] = tare_override

    await _execute_fdb_to_spoolman(
        db, res, spoolman, filamentdb,
        sm_filaments_all, fdb_filaments,
        decisions_by_sm, parent_of_fdb, tare_by_fdb_spool,
        precision=precision,
    )
    return res
