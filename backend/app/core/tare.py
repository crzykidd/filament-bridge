"""Standalone bulk tare-weight (spool-weight) editing (FR-23 / issue #26).

Tare is a *filament-level* field — Filament DB ``spoolWeight`` ↔ Spoolman
``spool_weight`` — already synced bidirectionally by the engine's material-property
scalar pass (``_sync_material_scalars`` under the ``material_properties`` category,
baseline key ``_mp_spool_weight``). This module is the read/write backing for the
standalone Tare Editor, which lets the user fix tare for many *already-mapped*
filaments outside the wizard.

Write model: a tare edit is an authoritative user choice, so we write **both sides
directly** and refresh **both** ``_mp_spool_weight`` snapshots in the same
transaction — the same anti-ping-pong pattern the engine's ``_store`` closure uses —
so the next sync cycle doesn't re-detect the edit as a one-sided change. We do NOT
defer to the configured ``material_properties`` direction/policy (that governs passive
drift, not a deliberate edit).

Variant handling (issue #26 decision — "edit parent + standalone only"): variant
filaments inherit tare from their parent in Filament DB, so they are surfaced
read-only with their effective (resolved) value; only standalone and master/parent
filaments are editable. Editing a master propagates to its inheriting variants
through FDB inheritance, and the engine's scalar pass mirrors that to the variants'
Spoolman counterparts on the next cycle.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.engine import _get_snapshot, _log, _merge_snapshot
from app.models.mapping import FilamentMapping
from app.services.filamentdb import FilamentDBClient
from app.services.spoolman import SpoolmanClient

logger = logging.getLogger(__name__)

# Baseline snapshot key the engine's material-scalar pass uses for spool_weight
# (``f"_mp_{sm_field}"``). Reused here so a bulk edit refreshes the SAME baseline.
TARE_SNAP_KEY = "_mp_spool_weight"

# Defensive upper bound — an empty reel tare above this is almost certainly a typo
# (grams, not kg). Keeps a fat-fingered "10000000" from poisoning every spool.
MAX_TARE_GRAMS = 100_000.0


def _round2(v: Any) -> float | None:
    """Coerce to a 2-dp float, or None when absent/unparseable (mirrors _norm_float2)."""
    if v is None:
        return None
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def _role(fdb: Any, has_variants: bool) -> str:
    """Classify an FDB filament: 'variant' (inherits), 'master' (has variants), 'standalone'."""
    if getattr(fdb, "parentId", None):
        return "variant"
    if has_variants:
        return "master"
    return "standalone"


async def build_tare_rows(
    db: Session,
    spoolman: SpoolmanClient,
    filamentdb: FilamentDBClient,
) -> list[dict]:
    """List every mapped filament pair with its current both-side tare and edit state.

    Uses the list projections (one call each) rather than per-filament detail fetches.
    Variant tare is resolved client-side from the parent's stored value, since the
    list view does not resolve inheritance.
    """
    sm_filaments = {f.id: f for f in await spoolman.get_filaments()}
    fdb_list = await filamentdb.get_filaments()
    fdb_by_id = {f.id: f for f in fdb_list}

    rows: list[dict] = []
    for m in db.query(FilamentMapping).all():
        # Skip synthetic container parents (no real Spoolman side) and any
        # half-linked rows — exactly as build_mapping_rows does.
        if m.is_synthetic_parent or m.spoolman_filament_id is None:
            continue
        fdb = fdb_by_id.get(m.filamentdb_id)
        sm = sm_filaments.get(m.spoolman_filament_id)
        if fdb is None or sm is None:
            continue  # upstream record gone — out of scope for tare editing

        has_variants = bool(getattr(fdb, "hasVariants", False))
        role = _role(fdb, has_variants)
        parent_id = getattr(fdb, "parentId", None) or None

        sm_tare = _round2(getattr(sm, "spool_weight", None))
        fdb_stored = _round2(getattr(fdb, "spoolWeight", None))

        # Effective FDB tare: a variant with no own value inherits the parent's.
        effective = fdb_stored
        parent_name = None
        if role == "variant" and parent_id:
            parent = fdb_by_id.get(parent_id)
            if parent is not None:
                parent_name = parent.name
                if effective is None:
                    effective = _round2(getattr(parent, "spoolWeight", None))

        if effective is None:
            status = "missing"
        elif sm_tare is not None and sm_tare != effective:
            status = "mismatch"
        else:
            status = "set"

        # Group key clusters a variant family together: variants group under their
        # FDB parent id; masters/standalone group under their own id (so a master
        # and its variants share one key). group_name labels the cluster.
        group_key = parent_id or m.filamentdb_id
        group_name = parent_name if (role == "variant" and parent_name) else (sm.name or fdb.name)

        rows.append({
            "filament_mapping_id": m.id,
            "spoolman_filament_id": m.spoolman_filament_id,
            "filamentdb_id": m.filamentdb_id,
            "name": sm.name or fdb.name,
            "vendor": (getattr(sm.vendor, "name", None) if getattr(sm, "vendor", None) else None) or fdb.vendor,
            "role": role,
            # Every mapped filament is editable: each has both an FDB and a Spoolman
            # record, so apply_tare can write both sides directly. Editing a variant
            # writes an explicit (override) tare on it — that is exactly the point of
            # this tool, and writing both sides + refreshing snapshots keeps the engine
            # from re-detecting it as drift.
            "editable": True,
            "spoolman_tare": sm_tare,
            "filamentdb_tare": fdb_stored,
            "effective_tare": effective,
            "is_overridden": role == "variant" and fdb_stored is not None,
            "parent_id": parent_id,
            "parent_name": parent_name,
            "group_key": group_key,
            "group_name": group_name,
            "status": status,
        })

    # Sort so families cluster together (by group name, then role with the master
    # first, then member name) — the frontend renders in this order.
    _role_rank = {"master": 0, "standalone": 0, "variant": 1}
    rows.sort(key=lambda r: (
        (r["group_name"] or "").lower(),
        r["group_key"],
        _role_rank.get(r["role"], 2),
        (r["name"] or "").lower(),
        r["filament_mapping_id"],
    ))
    return rows


async def apply_tare(
    db: Session,
    *,
    filament_mapping_id: int,
    tare_grams: float,
    spoolman: SpoolmanClient,
    filamentdb: FilamentDBClient,
    fdb_by_id: dict[str, Any],
    cycle_id: str,
) -> None:
    """Write one filament's tare to BOTH sides and refresh both snapshots.

    Works for any mapped filament — standalone, master, or variant. Editing a
    variant writes an explicit (override) tare on it; writing both sides and
    refreshing both snapshots keeps the engine from re-detecting it as drift.

    Raises ValueError on a bad target (unknown/synthetic mapping or a missing
    upstream record). Upstream write errors propagate to the caller for per-row
    failure isolation.
    """
    m = db.query(FilamentMapping).filter_by(id=filament_mapping_id).first()
    if m is None or m.is_synthetic_parent or m.spoolman_filament_id is None:
        raise ValueError("unknown or non-editable filament mapping")

    fdb = fdb_by_id.get(m.filamentdb_id)
    if fdb is None:
        raise ValueError("Filament DB record not found")

    tare = _round2(tare_grams)
    if tare is None or tare < 0 or tare > MAX_TARE_GRAMS:
        raise ValueError(f"tare must be between 0 and {MAX_TARE_GRAMS:.0f} g")

    sm_snap = _get_snapshot(db, "spoolman", "filament", str(m.spoolman_filament_id)) or {}
    old = sm_snap.get(TARE_SNAP_KEY)

    # Authoritative write to both systems.
    await filamentdb.update_filament(m.filamentdb_id, {"spoolWeight": tare})
    await spoolman.update_filament(m.spoolman_filament_id, {"spool_weight": tare})

    # Refresh both baselines to the agreed value (anti-ping-pong).
    _merge_snapshot(db, "spoolman", "filament", str(m.spoolman_filament_id), {TARE_SNAP_KEY: tare})
    _merge_snapshot(db, "filamentdb", "filament", m.filamentdb_id, {TARE_SNAP_KEY: tare})

    _log(
        db, cycle_id, "manual", "update", "filament",
        spoolman_id=m.spoolman_filament_id, fdb_filament_id=m.filamentdb_id,
        field_name="spool_weight", old_value=old, new_value=tare,
    )


async def apply_tare_bulk(
    db: Session,
    updates: list[dict],
    spoolman: SpoolmanClient,
    filamentdb: FilamentDBClient,
) -> dict:
    """Apply a batch of tare edits with per-row failure isolation.

    ``updates`` is a list of ``{filament_mapping_id, tare_grams}``. Returns
    ``{"updated": n, "failed": [{filament_mapping_id, error}]}``. Successful rows are
    committed even when others fail.
    """
    fdb_by_id = {f.id: f for f in await filamentdb.get_filaments()}
    cycle_id = f"tare-edit-{uuid.uuid4().hex[:8]}"

    updated = 0
    failed: list[dict] = []
    for u in updates:
        mid = u.get("filament_mapping_id")
        try:
            await apply_tare(
                db,
                filament_mapping_id=int(mid),
                tare_grams=u.get("tare_grams"),
                spoolman=spoolman,
                filamentdb=filamentdb,
                fdb_by_id=fdb_by_id,
                cycle_id=cycle_id,
            )
            # Commit per row so a later failure's rollback can't discard earlier
            # successes (they share one session) — true per-row isolation.
            db.commit()
            updated += 1
        except Exception as exc:  # noqa: BLE001 — isolate per-row, report below
            logger.warning("Tare edit failed for mapping %s: %s", mid, exc)
            db.rollback()
            failed.append({"filament_mapping_id": mid, "error": str(exc)})

    return {"updated": updated, "failed": failed}
