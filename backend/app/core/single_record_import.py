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


class TareRequiredError(Exception):
    """Raised when a FDB→Spoolman single-record import needs a tare it doesn't have.

    Spoolman's weight model is net, so importing a filament's spool requires the
    empty-reel (tare) weight. When the FDB filament has no ``spoolWeight`` and the
    caller supplies no ``tare_override``, the import cannot proceed — the conflict
    endpoint maps this to a 422 so the UI can require the tare (rather than a 502
    that silently leaves an orphan Spoolman filament).
    """


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
    dry_run: bool = False,
) -> "Any":  # returns _ExecResult from wizard
    """Import a single Spoolman filament (and its spools) into Filament DB.

    Calls the wizard's _execute_spoolman_to_fdb scoped to one SM filament.
    Returns the _ExecResult accumulator. When ``dry_run`` is set, no upstream
    writes are performed (the preview counts still reflect what a real run would do).

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
        dry_run=dry_run,
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
    require_tare: bool = False,
    precision: int = 2,
    dry_run: bool = False,
) -> "Any":  # returns _ExecResult from wizard
    """Import a single FDB filament (and its spools) into Spoolman.

    Calls the wizard's _execute_fdb_to_spoolman scoped to one FDB filament.
    Returns the _ExecResult accumulator. When ``dry_run`` is set, no upstream
    writes are performed (the preview counts still reflect what a real run would do).

    ``tare_override`` supplies the empty-reel (tare) weight for the filament's
    spools when the FDB filament has none. When it fills a MISSING ``spoolWeight``
    it is also **written back to the FDB filament** (outside dry_run) so the source
    record is fixed and future imports/auto-sync of its other spools just work.

    ``require_tare`` (the conflict-endpoint path) raises ``TareRequiredError`` when
    the filament has an unmapped spool to import but no resolvable tare (no
    ``spoolWeight`` and no ``tare_override``) — so the caller can return a 422 and
    require the tare, instead of creating a filament and then failing its spool.
    The engine auto-import path leaves ``require_tare=False`` (unchanged behavior).
    """
    from app.api.config import resolve_container_parent_marker
    from app.api.wizard import (
        _ExecResult,
        _execute_fdb_to_spoolman,
    )
    from app.core.masters import is_master_fdb
    from app.models.mapping import FilamentMapping, SpoolMapping

    direction = "filamentdb_to_spoolman"
    res = _ExecResult(cycle_id=cycle_id, direction=direction)

    sm_filaments_all = await spoolman.get_filaments()
    fdb_filaments_all = await filamentdb.get_filaments()

    fdb_fil = next((f for f in fdb_filaments_all if f.id == fdb_filament_id), None)
    if fdb_fil is None:
        raise ValueError(f"FDB filament {fdb_filament_id} not found")

    fdb_filaments = [fdb_fil]

    # ---- Tare resolution + write-back ----
    # Spoolman's weight model is net, so importing a spool needs the empty-reel
    # (tare) weight. When the FDB filament has none, require a supplied override
    # (conflict path) rather than creating a filament whose spool then fails.
    _mapped_fdb_spool_ids = {m.filamentdb_spool_id for m in db.query(SpoolMapping).all()}
    _has_unmapped_spool = any(s.id not in _mapped_fdb_spool_ids for s in fdb_fil.spools)
    if fdb_fil.spoolWeight is None and _has_unmapped_spool:
        if tare_override is None:
            if require_tare:
                raise TareRequiredError(
                    "This Filament DB filament has no empty-reel (tare) weight; "
                    "enter it to import the spool into Spoolman."
                )
        else:
            # Fill the missing tare: in-memory so the SM filament create computes a
            # correct weight/spool_weight, and on the FDB source (outside dry_run) so
            # it is fixed permanently.
            fdb_fil.spoolWeight = tare_override
            if not dry_run:
                try:
                    await filamentdb.update_filament(
                        fdb_fil.id, {"spoolWeight": tare_override}
                    )
                except Exception as exc:  # non-fatal: import still proceeds with the override
                    logger.warning(
                        "single_record_import %s: could not write tare back to FDB "
                        "filament %s: %s", cycle_id, fdb_fil.id, exc,
                    )

    # Synthetic/container parents (masters) never sync directly to Spoolman — a
    # master carries no material/density/diameter and Spoolman is flat (one filament
    # per colour). Exclude it so the create path skips it instead of writing a junk
    # parent filament (its variants sync on their own).
    _marker = resolve_container_parent_marker(db)
    _synth_fdb_ids = {
        m.filamentdb_id
        for m in db.query(FilamentMapping).filter_by(is_synthetic_parent=True).all()
    }
    master_fdb_ids = {f.id for f in fdb_filaments if is_master_fdb(f, _marker, _synth_fdb_ids)}

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
        master_fdb_ids=master_fdb_ids,
        precision=precision,
        dry_run=dry_run,
    )
    return res
