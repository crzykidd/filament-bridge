"""Master-level group defaults — shared value helpers (issue #76).

FDB masters (variant-family parents, real ``hasVariants`` parents and synthetic
``generic_container`` parents alike) carry the six shared-property fields that
``_RECONCILE_FIELD_MAP`` (``app/api/wizard.py``) already knows how to map:
tare (spool_weight), nozzle/bed temp, density, diameter, and material/type.
This module holds the pure, data-only helpers that compute a family's *default*
value for those fields from its members — used both when a container is first
created (seed the master with the family's shared defaults, see
``_execute_spoolman_to_fdb``) and when backfilling existing masters that predate
this feature (``core/masters_backfill.py``).

Kept dependency-light (only imports from ``masters.py``, never from ``wizard.py``
or ``planner.py``) so both directions can import it without a circular import.
"""

from __future__ import annotations

from collections import Counter
from typing import Any


def group_mode_defaults(values_by_field: dict[str, list[Any]]) -> dict[str, Any]:
    """Per field, return the modal (most-common) non-null value across members.

    ``values_by_field`` is ``{field_name: [member_value, ...]}`` — already-extracted
    scalars (not upstream objects), so this stays pure and trivially testable.

    A field is entirely omitted from the result when every member's value is
    ``None`` (nothing to propose). Ties are broken deterministically: the lowest
    value (by ``<``) among the tied candidates wins, so results are reproducible
    and don't depend on dict/list ordering.
    """
    result: dict[str, Any] = {}
    for field_name, values in values_by_field.items():
        non_null = [v for v in values if v is not None]
        if not non_null:
            continue
        counts = Counter(non_null)
        max_count = max(counts.values())
        candidates = [v for v, c in counts.items() if c == max_count]
        result[field_name] = min(candidates)
    return result


def resolve_family_tare(fdb_filaments: list[Any], master_filamentdb_id: str | None) -> float | None:
    """Resolve the tare (empty-reel weight) a family already knows, if any.

    Resolution order:
    1. The master's own ``spoolWeight``, when set.
    2. The mode of its variant children's own ``spoolWeight`` (via
       ``group_mode_defaults`` — children with no own value are excluded).
    3. ``None`` — the family has no known tare yet.

    ``master_filamentdb_id`` may be omitted (returns ``None``) — callers with no
    family context (a genuinely standalone create) simply have no family tare.
    """
    if not master_filamentdb_id:
        return None
    fdb_by_id = {f.id: f for f in fdb_filaments}
    master = fdb_by_id.get(master_filamentdb_id)
    if master is not None and getattr(master, "spoolWeight", None) is not None:
        return master.spoolWeight

    child_values = [
        getattr(f, "spoolWeight", None)
        for f in fdb_filaments
        if getattr(f, "parentId", None) == master_filamentdb_id
    ]
    defaults = group_mode_defaults({"spool_weight": child_values})
    return defaults.get("spool_weight")
