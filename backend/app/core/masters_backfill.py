"""Backfill screen for existing master/container defaults (issue #76).

Item 1 (``masters_defaults.group_mode_defaults`` + the ``_execute_spoolman_to_fdb``
container-create path) seeds a master's shared defaults at *creation* time. This
module covers masters that predate that feature (or were backfilled from an older
bridge version): a manual-review screen that proposes the family's mode value for
each of the six ``_RECONCILE_FIELD_MAP`` fields on every existing master — real
``hasVariants`` parents and synthetic ``generic_container`` parents alike — and
writes only what the user explicitly approves.

Write model mirrors ``core/tare.py``'s ``apply_tare``: fill-null-only (never
overwrite a value the master already holds, on EITHER side), write both the FDB
master and its live Spoolman counterpart (when one exists — a synthetic container
has none), and refresh both ``_mp_*`` snapshot baselines to the post-write agreed
value so the engine's material-scalar pass doesn't re-detect the edit as drift on
the next cycle. A synthetic master has no Spoolman side, so its SM write/snapshot
is skipped entirely; its FDB-side baseline is still refreshed for consistency
(synthetic parents never participate in the scalar sync pass, so it's inert, but
keeping the shape uniform avoids a second code path).

Variant inheritance in Filament DB means writing the master's field is enough — a
variant with no own value already inherits it, and the engine's scalar pass mirrors
that inheritance to the variant's Spoolman counterpart on the next cycle (same
reasoning as ``core/tare.py``).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.api.config import resolve_container_parent_marker
from app.api.wizard import _RECONCILE_FIELD_MAP
from app.core.engine import _log, _merge_snapshot
from app.core.masters import is_master_fdb
from app.core.masters_defaults import group_mode_defaults
from app.models.mapping import FilamentMapping
from app.services.filamentdb import FilamentDBClient
from app.services.spoolman import SpoolmanClient

logger = logging.getLogger(__name__)


def _fdb_field_value(fil: Any, fdb_key: str) -> Any:
    """Read a (possibly dotted, e.g. 'temperatures.nozzle') field off an FDB filament."""
    if "." in fdb_key:
        top, sub = fdb_key.split(".", 1)
        nested = getattr(fil, top, None)
        return getattr(nested, sub, None) if nested is not None else None
    return getattr(fil, fdb_key, None)


def _set_nested(payload: dict, fdb_key: str, value: Any) -> None:
    """Write a (possibly dotted) field into an FDB PATCH payload, read-modify-write style."""
    if "." in fdb_key:
        top, sub = fdb_key.split(".", 1)
        nested = dict(payload.get(top) or {})
        nested[sub] = value
        payload[top] = nested
    else:
        payload[fdb_key] = value


async def build_master_default_rows(
    db: Session,
    spoolman: SpoolmanClient,
    filamentdb: FilamentDBClient,
) -> list[dict]:
    """One row per master (real ``hasVariants`` parent or synthetic container).

    Per field (the six ``_RECONCILE_FIELD_MAP`` keys): the master's current FDB
    value, its current Spoolman value (when it has a live counterpart), the
    group-mode proposal computed from the master's variant children's OWN values
    (never their inherited/effective value — inheritance is exactly what we're
    trying to backfill), ``would_fill`` (current FDB value is null and a proposal
    exists), and a breakdown of which variants contributed a value — so the UI can
    show why a value won.
    """
    fdb_list = await filamentdb.get_filaments()
    sm_filaments = {f.id: f for f in await spoolman.get_filaments()}

    marker = resolve_container_parent_marker(db)
    synthetic_ids = {
        m.filamentdb_id
        for m in db.query(FilamentMapping).filter_by(is_synthetic_parent=True).all()
    }
    mapping_by_fdb_id = {m.filamentdb_id: m for m in db.query(FilamentMapping).all()}

    rows: list[dict] = []
    for fdb in fdb_list:
        if not is_master_fdb(fdb, marker, synthetic_ids):
            continue
        children = [f for f in fdb_list if getattr(f, "parentId", None) == fdb.id]
        mapping = mapping_by_fdb_id.get(fdb.id)
        sm_master_id = (
            mapping.spoolman_filament_id
            if mapping is not None and not mapping.is_synthetic_parent
            else None
        )
        sm_master = sm_filaments.get(sm_master_id) if sm_master_id is not None else None

        fields: dict[str, dict] = {}
        for canonical, (fdb_key, sm_key) in _RECONCILE_FIELD_MAP.items():
            current = _fdb_field_value(fdb, fdb_key)
            current_sm = getattr(sm_master, sm_key, None) if sm_master is not None else None
            child_values = [_fdb_field_value(c, fdb_key) for c in children]
            proposal = group_mode_defaults({canonical: child_values}).get(canonical)
            breakdown = [
                {"filamentdb_id": c.id, "name": c.name, "value": _fdb_field_value(c, fdb_key)}
                for c in children
                if _fdb_field_value(c, fdb_key) is not None
            ]
            fields[canonical] = {
                "current": current,
                "current_sm": current_sm,
                "proposal": proposal,
                "would_fill": current is None and proposal is not None,
                "breakdown": breakdown,
            }

        rows.append({
            "filamentdb_id": fdb.id,
            "name": fdb.name,
            "vendor": fdb.vendor,
            "is_synthetic": fdb.id in synthetic_ids,
            "spoolman_filament_id": sm_master_id,
            "variant_count": len(children),
            "fields": fields,
        })

    rows.sort(key=lambda r: (r["name"] or "").lower())
    return rows


async def apply_master_defaults(
    db: Session,
    *,
    filamentdb_id: str,
    fields: list[str],
    spoolman: SpoolmanClient,
    filamentdb: FilamentDBClient,
    rows_by_fdb_id: dict[str, dict],
    cycle_id: str,
) -> list[str]:
    """Fill the requested null fields on one master with its proposed mode value.

    ``rows_by_fdb_id`` is ``{filamentdb_id: row}`` from ``build_master_default_rows``
    — reused rather than recomputed, so apply can never propose a different value
    than the preview the user reviewed (preview ≡ execute, same pattern as the
    wizard planner). A requested field that is not ``would_fill`` (e.g. a stale
    request replaying a field a prior apply already filled) is silently skipped,
    not an error — only genuinely-still-null fields are ever written.

    Raises ValueError for an unknown master id. Upstream write errors propagate to
    the caller for per-row failure isolation (mirrors ``tare.py:apply_tare``).
    """
    row = rows_by_fdb_id.get(filamentdb_id)
    if row is None:
        raise ValueError(f"unknown master filamentdb_id {filamentdb_id}")

    fdb_patch: dict = {}
    sm_patch: dict = {}
    snapshot_by_key: dict[str, tuple[Any, Any]] = {}  # snap_key -> (sm_value, fdb_value)
    filled: list[str] = []

    for canonical in fields:
        field_row = row["fields"].get(canonical)
        if field_row is None or not field_row["would_fill"]:
            continue
        fdb_key, sm_key = _RECONCILE_FIELD_MAP[canonical]
        proposal = field_row["proposal"]

        _set_nested(fdb_patch, fdb_key, proposal)
        fdb_final = proposal

        # Never clobber an already-set SM value — only write when the master has a
        # live Spoolman counterpart AND its own field is also null.
        sm_final = field_row.get("current_sm")
        if row["spoolman_filament_id"] is not None and sm_final is None:
            sm_patch[sm_key] = proposal
            sm_final = proposal

        snapshot_by_key[f"_mp_{sm_key}"] = (sm_final, fdb_final)
        filled.append(canonical)

    if not filled:
        return filled

    await filamentdb.update_filament(filamentdb_id, fdb_patch)
    if sm_patch and row["spoolman_filament_id"] is not None:
        await spoolman.update_filament(row["spoolman_filament_id"], sm_patch)

    # Refresh both baselines to the post-write agreed value (anti-ping-pong) —
    # skipped on the SM side entirely for a synthetic master (no counterpart to key
    # a Spoolman-side snapshot on).
    for snap_key, (sm_v, fdb_v) in snapshot_by_key.items():
        if row["spoolman_filament_id"] is not None:
            _merge_snapshot(
                db, "spoolman", "filament", str(row["spoolman_filament_id"]), {snap_key: sm_v}
            )
        _merge_snapshot(db, "filamentdb", "filament", filamentdb_id, {snap_key: fdb_v})

    for canonical in filled:
        _, sm_key = _RECONCILE_FIELD_MAP[canonical]
        _log(
            db, cycle_id, "manual", "update", "filament",
            spoolman_id=row["spoolman_filament_id"], fdb_filament_id=filamentdb_id,
            field_name=sm_key, old_value=None, new_value=row["fields"][canonical]["proposal"],
        )

    return filled


async def apply_master_defaults_bulk(
    db: Session,
    updates: list[dict],
    spoolman: SpoolmanClient,
    filamentdb: FilamentDBClient,
) -> dict:
    """Apply a batch of master-default fills with per-row failure isolation.

    ``updates`` is a list of ``{filamentdb_id, fields}`` (``fields`` a list of
    canonical field names). Returns ``{"updated": n, "failed": [{filamentdb_id,
    error}]}``. Successful rows are committed even when others fail.
    """
    rows = await build_master_default_rows(db, spoolman, filamentdb)
    rows_by_fdb_id = {r["filamentdb_id"]: r for r in rows}
    cycle_id = f"master-defaults-{uuid.uuid4().hex[:8]}"

    updated = 0
    failed: list[dict] = []
    for u in updates:
        fdb_id = u.get("filamentdb_id")
        try:
            filled = await apply_master_defaults(
                db,
                filamentdb_id=fdb_id,
                fields=u.get("fields") or [],
                spoolman=spoolman,
                filamentdb=filamentdb,
                rows_by_fdb_id=rows_by_fdb_id,
                cycle_id=cycle_id,
            )
            db.commit()
            if filled:
                updated += 1
        except Exception as exc:  # noqa: BLE001 — isolate per-row, report below
            logger.warning("Master-defaults apply failed for %s: %s", fdb_id, exc)
            db.rollback()
            failed.append({"filamentdb_id": fdb_id, "error": str(exc)})

    return {"updated": updated, "failed": failed}
