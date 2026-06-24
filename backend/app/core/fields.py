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


# ---------------------------------------------------------------------------
# OpenPrintTag material-setting extra fields (Spoolman extra ↔ FDB first-class)
# ---------------------------------------------------------------------------
# These seven standardized OpenPrintTag material settings have no native Spoolman
# field but a writable Filament DB counterpart.  They are stored as TYPED Spoolman
# filament extra fields (integer/float), populated from OPT via the cleanup-tool
# Apply flow, and synced to/from FDB by the material-properties sync pass.
#
# Each entry: (config attribute on Settings, default key, Spoolman field_type,
#             OPT source key, FDB target path, label).  The config attribute lets
# a deployment override the extra-field key via SPOOLMAN_FIELD_* env vars
# (resolved at runtime, like every other extra-field key).
#
# All values pass through unit-for-unit — OpenPrintTag and Filament DB agree on
# units for every field, including dryingTime, which is in MINUTES on both sides.


@dataclass(frozen=True)
class OpenTagExtraField:
    config_attr: str   # attribute name on Settings holding the (overridable) key
    default_key: str   # default Spoolman extra-field key
    field_type: str    # Spoolman field_type: "integer" | "float"
    opt_key: str       # key on the OPTMaterial dict
    fdb_path: str      # dotted FDB filament field path (in FDB_SYNCABLE_FIELDS)
    label: str         # human label / sync-log + snapshot field name


#: The seven OpenPrintTag material-setting extra fields.  Order is stable.
OPENTAG_EXTRA_FIELDS: tuple[OpenTagExtraField, ...] = (
    OpenTagExtraField(
        "spoolman_field_openprinttag_nozzle_temp_min",
        "openprinttag_nozzle_temp_min", "integer",
        "nozzleTempMin", "temperatures.nozzleRangeMin", "opt_nozzle_temp_min",
    ),
    OpenTagExtraField(
        "spoolman_field_openprinttag_nozzle_temp_max",
        "openprinttag_nozzle_temp_max", "integer",
        "nozzleTempMax", "temperatures.nozzleRangeMax", "opt_nozzle_temp_max",
    ),
    OpenTagExtraField(
        "spoolman_field_openprinttag_drying_temp",
        "openprinttag_drying_temp", "integer",
        "dryingTemp", "dryingTemperature", "opt_drying_temp",
    ),
    OpenTagExtraField(
        "spoolman_field_openprinttag_drying_time",
        "openprinttag_drying_time", "integer",
        "dryingTime", "dryingTime", "opt_drying_time",
    ),
    OpenTagExtraField(
        "spoolman_field_openprinttag_hardness_shore_a",
        "openprinttag_hardness_shore_a", "float",
        "hardnessShoreA", "shoreHardnessA", "opt_hardness_shore_a",
    ),
    OpenTagExtraField(
        "spoolman_field_openprinttag_hardness_shore_d",
        "openprinttag_hardness_shore_d", "float",
        "hardnessShoreD", "shoreHardnessD", "opt_hardness_shore_d",
    ),
    OpenTagExtraField(
        "spoolman_field_openprinttag_transmission_distance",
        "openprinttag_transmission_distance", "float",
        "transmissionDistance", "transmissionDistance", "opt_transmission_distance",
    ),
)

# Every FDB target for the OPT extra fields must be in the writable allow-list.
assert all(f.fdb_path in FDB_SYNCABLE_FIELDS for f in OPENTAG_EXTRA_FIELDS)


@dataclass
class FieldMapping:
    fdb_path: str    # dotted FDB field path, e.g. "temperatures.nozzle"
    sm_key: str      # Spoolman extra-field key
    direction: str   # "fdb_to_sm" | "sm_to_fdb"


def resolve_field_map(
    settings: "Settings",
    spoolman_extra_keys: set[str],
    material_props_sot: str = "filamentdb",
) -> list[FieldMapping]:
    """Build the effective FDB↔Spoolman field mapping list.

    Priority order:
      1. Explicit pairs from settings.parsed_field_mappings
      2. Auto-matched: Spoolman extra key name == FDB field name exactly
    Excludes (from settings.parsed_field_mapping_excludes) filter both layers.

    The ``material_props_sot`` parameter is accepted for backward compatibility
    but the direction on each mapping is no longer consulted by the engine —
    direction decisions are routed through ``resolve_sync_action`` instead.
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


def resolve_effective_cost(filament_price: float | None, spools: list) -> float | None:
    """Return the effective cost for a Spoolman filament (spool price first, filament fallback).

    Uses the price of the first spool (by id) that has a non-null price.
    Falls back to the filament-level price if no spool has a price set.
    Tolerates empty spool lists.
    """
    for s in sorted(spools, key=lambda s: s.id):
        if s.price is not None:
            return s.price
    return filament_price
