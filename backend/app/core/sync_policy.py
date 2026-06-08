"""Per-category sync direction and conflict policy resolver.

Two independent axes per data category (weight | material_properties):

  direction: two_way | spoolman_to_filamentdb | filamentdb_to_spoolman
  policy:    manual | spoolman_wins | filamentdb_wins | newest_wins
             (newest_wins is weight-only; material_properties rejects it at the API layer)

Call ``resolve_sync_action`` with the diff result and category settings.  The
caller is responsible for executing the returned ``SyncAction`` using its own
existing write mechanics — this module is pure (no I/O, no DB access).
"""

from __future__ import annotations

import datetime
from enum import Enum


class SyncAction(str, Enum):
    PUSH_SM_TO_FDB = "push_sm_to_fdb"
    PUSH_FDB_TO_SM = "push_fdb_to_sm"
    QUEUE_CONFLICT = "queue_conflict"
    NOOP = "noop"


def resolve_sync_action(
    *,
    sm_changed: bool,
    fdb_changed: bool,
    direction: str,
    policy: str,
    sm_ts: datetime.datetime | None = None,
    fdb_ts: datetime.datetime | None = None,
) -> SyncAction:
    """Decide what the engine should do for a single category on one pair.

    Parameters
    ----------
    sm_changed:  Spoolman side changed since the last snapshot.
    fdb_changed: Filament DB side changed since the last snapshot.
    direction:   "two_way" | "spoolman_to_filamentdb" | "filamentdb_to_spoolman"
    policy:      "manual" | "spoolman_wins" | "filamentdb_wins" | "newest_wins"
                 (only consulted when direction=="two_way" AND both sides changed)
    sm_ts:       Spoolman source timestamp (already nulled out if not after captured_at).
    fdb_ts:      Filament DB source timestamp (same nulling rule).

    Returns
    -------
    SyncAction
    """
    # Nothing to do.
    if not sm_changed and not fdb_changed:
        return SyncAction.NOOP

    # One-way modes: only the source side propagates; locked destination drift is NOOP.
    if direction == "spoolman_to_filamentdb":
        return SyncAction.PUSH_SM_TO_FDB if sm_changed else SyncAction.NOOP
    if direction == "filamentdb_to_spoolman":
        return SyncAction.PUSH_FDB_TO_SM if fdb_changed else SyncAction.NOOP

    # two_way — lone change always propagates.
    if sm_changed and not fdb_changed:
        return SyncAction.PUSH_SM_TO_FDB
    if fdb_changed and not sm_changed:
        return SyncAction.PUSH_FDB_TO_SM

    # Both sides changed — apply conflict policy.
    if policy == "spoolman_wins":
        return SyncAction.PUSH_SM_TO_FDB
    if policy == "filamentdb_wins":
        return SyncAction.PUSH_FDB_TO_SM
    if policy == "newest_wins":
        # Both timestamps must be present and unequal for a deterministic winner.
        if sm_ts is not None and fdb_ts is not None and sm_ts != fdb_ts:
            return SyncAction.PUSH_SM_TO_FDB if sm_ts > fdb_ts else SyncAction.PUSH_FDB_TO_SM
        return SyncAction.QUEUE_CONFLICT  # missing / equal / indeterminate → manual
    # manual (default)
    return SyncAction.QUEUE_CONFLICT
