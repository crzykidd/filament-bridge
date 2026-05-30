"""Diff classifier — pure-ish, no persistence.

Takes current entities + snapshot dicts, returns structured changesets.
The engine calls this and then does all persistence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.core.matcher import normalize_color
from app.core.weight import weight_changed

if TYPE_CHECKING:
    from app.core.fields import FieldMapping
    from app.schemas.filamentdb import FDBSpool
    from app.schemas.spoolman import SpoolmanSpool


@dataclass
class FieldChange:
    field_name: str
    old_value: Any
    new_value: Any


@dataclass
class SpoolPairChangeset:
    """Change classification for a single mapped (SM spool, FDB spool) pair."""

    spoolman_spool_id: int
    fdb_filament_id: str
    fdb_spool_id: str
    has_prior_snapshot: bool

    # Weight
    sm_weight_change: FieldChange | None = None   # SM remaining_weight changed
    fdb_weight_change: FieldChange | None = None  # FDB totalWeight changed
    weight_conflict: bool = False                 # both sides changed

    # Field mappings (FR-11)
    sm_field_changes: list[FieldChange] = field(default_factory=list)
    fdb_field_changes: list[FieldChange] = field(default_factory=list)
    field_conflicts: list[str] = field(default_factory=list)  # fdb_path names


def diff_spool_pair(
    sm_spool: "SpoolmanSpool",
    fdb_spool: "FDBSpool",
    fdb_filament_id: str,
    sm_snapshot: dict | None,
    fdb_snapshot: dict | None,
    threshold: float,
    field_maps: list["FieldMapping"] | None = None,
    sm_extra_decoded: dict | None = None,   # {sm_key: decoded Python value}
    fdb_field_values: dict | None = None,   # {fdb_path: Python value}
) -> SpoolPairChangeset:
    """Classify changes for one spool pair against its last snapshots.

    Returns a changeset with has_prior_snapshot=False when either snapshot is
    missing (first time we see the pair — engine will just store a baseline).
    """
    has_prior = sm_snapshot is not None and fdb_snapshot is not None
    cs = SpoolPairChangeset(
        spoolman_spool_id=sm_spool.id,
        fdb_filament_id=fdb_filament_id,
        fdb_spool_id=fdb_spool.id,
        has_prior_snapshot=has_prior,
    )
    if not has_prior:
        return cs

    # ---- Weight diff ----
    sm_w_now = sm_spool.remaining_weight
    sm_w_snap = sm_snapshot.get("remaining_weight")
    fdb_w_now = fdb_spool.totalWeight
    fdb_w_snap = fdb_snapshot.get("totalWeight")

    sm_wc = weight_changed(sm_w_snap, sm_w_now, threshold)
    fdb_wc = weight_changed(fdb_w_snap, fdb_w_now, threshold)

    if sm_wc:
        cs.sm_weight_change = FieldChange("remaining_weight", sm_w_snap, sm_w_now)
    if fdb_wc:
        cs.fdb_weight_change = FieldChange("totalWeight", fdb_w_snap, fdb_w_now)
    if sm_wc and fdb_wc:
        cs.weight_conflict = True

    # ---- Field mapping diff ----
    if field_maps and sm_extra_decoded is not None and fdb_field_values is not None:
        sm_extra_snap: dict = sm_snapshot.get("_extra_decoded", {})
        fdb_fields_snap: dict = fdb_snapshot.get("_field_values", {})

        for fm in field_maps:
            sm_now = sm_extra_decoded.get(fm.sm_key)
            sm_then = sm_extra_snap.get(fm.sm_key)
            fdb_now = fdb_field_values.get(fm.fdb_path)
            fdb_then = fdb_fields_snap.get(fm.fdb_path)

            # Normalise color representation before comparing so bare-vs-# differences
            # don't generate spurious change events and cause perpetual flapping.
            if fm.fdb_path == "color":
                sm_now = normalize_color(sm_now)
                sm_then = normalize_color(sm_then)
                fdb_now = normalize_color(fdb_now)
                fdb_then = normalize_color(fdb_then)

            sm_fc = sm_then != sm_now
            fdb_fc = fdb_then != fdb_now

            if sm_fc and fdb_fc:
                cs.field_conflicts.append(fm.fdb_path)
            elif sm_fc:
                cs.sm_field_changes.append(FieldChange(fm.fdb_path, sm_then, sm_now))
            elif fdb_fc:
                cs.fdb_field_changes.append(FieldChange(fm.fdb_path, fdb_then, fdb_now))

    return cs
