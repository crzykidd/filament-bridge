"""Field-mapping resolution (FR-11).

Resolves the effective FDB-field ↔ Spoolman-extra-field map from settings,
layering explicit mappings over exact-name auto-matches and honouring excludes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.config import Settings
    from app.schemas.filamentdb import FDBFilamentDetail

# Fields on an FDBFilamentDetail that the bridge is allowed to sync
_FDB_SCALAR_FIELDS: frozenset[str] = frozenset({
    "name", "color", "vendor", "type", "cost", "density", "diameter",
    "maxVolumetricSpeed", "spoolWeight", "netFilamentWeight", "dryingTemperature",
    "dryingTime", "transmissionDistance", "glassTempTransition", "heatDeflectionTemp",
    "shoreHardnessA", "shoreHardnessD", "minPrintSpeed", "maxPrintSpeed", "spoolType",
    "tdsUrl", "shrinkageXY", "shrinkageZ",
})

_FDB_DOTTED_FIELDS: frozenset[str] = frozenset({
    "temperatures.nozzle", "temperatures.nozzleFirstLayer", "temperatures.bed",
    "temperatures.bedFirstLayer", "temperatures.nozzleRangeMin", "temperatures.nozzleRangeMax",
    "temperatures.standby",
})

FDB_SYNCABLE_FIELDS: frozenset[str] = _FDB_SCALAR_FIELDS | _FDB_DOTTED_FIELDS


@dataclass
class FieldMapping:
    fdb_path: str    # dotted FDB field path, e.g. "temperatures.nozzle"
    sm_key: str      # Spoolman extra-field key
    direction: str   # "fdb_to_sm" | "sm_to_fdb"


def resolve_field_map(
    settings: "Settings",
    spoolman_extra_keys: set[str],
    material_props_sot: str,
) -> list[FieldMapping]:
    """Build the effective FDB↔Spoolman field mapping list.

    Priority order:
      1. Explicit pairs from settings.parsed_field_mappings
      2. Auto-matched: Spoolman extra key name == FDB field name exactly
    Excludes (from settings.parsed_field_mapping_excludes) filter both layers.
    """
    direction = "fdb_to_sm" if material_props_sot == "filamentdb" else "sm_to_fdb"
    excludes = settings.parsed_field_mapping_excludes
    explicit = settings.parsed_field_mappings  # {fdb_path: sm_key}

    mappings: list[FieldMapping] = []
    covered_fdb: set[str] = set()

    for fdb_path, sm_key in explicit.items():
        if fdb_path in excludes or sm_key in excludes:
            continue
        mappings.append(FieldMapping(fdb_path=fdb_path, sm_key=sm_key, direction=direction))
        covered_fdb.add(fdb_path)

    for sm_key in sorted(spoolman_extra_keys):
        if sm_key in excludes or sm_key not in FDB_SYNCABLE_FIELDS:
            continue
        if sm_key not in covered_fdb:
            mappings.append(FieldMapping(fdb_path=sm_key, sm_key=sm_key, direction=direction))

    return mappings


def get_fdb_field_value(filament: "FDBFilamentDetail", path: str) -> Any:
    """Read a (possibly dotted) field from an FDB filament detail object."""
    obj: Any = filament
    for part in path.split("."):
        if obj is None:
            return None
        obj = getattr(obj, part, None) if hasattr(obj, part) else (
            obj.get(part) if isinstance(obj, dict) else None
        )
    return obj


def should_skip_inherited(filament: "FDBFilamentDetail", fdb_path: str) -> bool:
    """True if the top-level field is inherited from a parent variant.

    Writing an inherited field would override the parent's value and break
    variant inheritance — skip and log instead (decisions-log rule).
    """
    top = fdb_path.split(".")[0]
    return top in filament.inherited_fields
