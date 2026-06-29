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
    config_attr: str        # attribute name on Settings holding the (overridable) key
    default_key: str        # default Spoolman extra-field key
    field_type: str         # Spoolman field_type: "integer" | "float"
    opt_key: str            # key on the OPTMaterial dict
    label: str              # human label / sync-log + snapshot field name
    fdb_path: str | None = None  # dotted FDB field path (None = Spoolman-only, no FDB sync)


#: The fifteen OpenPrintTag material-setting extra fields.  Order is stable.
#: Entries with fdb_path are synced bidirectionally with Filament DB by
#: _sync_opentag_material_fields.  Entries without fdb_path are Spoolman-only:
#: populated by the Apply flow, never read or written to FDB.
OPENTAG_EXTRA_FIELDS: tuple[OpenTagExtraField, ...] = (
    OpenTagExtraField(
        "spoolman_field_openprinttag_nozzle_temp_min",
        "openprinttag_nozzle_temp_min", "integer",
        "nozzleTempMin", "opt_nozzle_temp_min",
        fdb_path="temperatures.nozzleRangeMin",
    ),
    OpenTagExtraField(
        "spoolman_field_openprinttag_nozzle_temp_max",
        "openprinttag_nozzle_temp_max", "integer",
        "nozzleTempMax", "opt_nozzle_temp_max",
        fdb_path="temperatures.nozzleRangeMax",
    ),
    OpenTagExtraField(
        "spoolman_field_openprinttag_drying_temp",
        "openprinttag_drying_temp", "integer",
        "dryingTemp", "opt_drying_temp",
        fdb_path="dryingTemperature",
    ),
    OpenTagExtraField(
        "spoolman_field_openprinttag_drying_time",
        "openprinttag_drying_time", "integer",
        "dryingTime", "opt_drying_time",
        fdb_path="dryingTime",
    ),
    OpenTagExtraField(
        "spoolman_field_openprinttag_hardness_shore_a",
        "openprinttag_hardness_shore_a", "float",
        "hardnessShoreA", "opt_hardness_shore_a",
        fdb_path="shoreHardnessA",
    ),
    OpenTagExtraField(
        "spoolman_field_openprinttag_hardness_shore_d",
        "openprinttag_hardness_shore_d", "float",
        "hardnessShoreD", "opt_hardness_shore_d",
        fdb_path="shoreHardnessD",
    ),
    OpenTagExtraField(
        "spoolman_field_openprinttag_transmission_distance",
        "openprinttag_transmission_distance", "float",
        "transmissionDistance", "opt_transmission_distance",
        fdb_path="transmissionDistance",
    ),
    # --- Bed temperature ---
    # bed_temp_min: Spoolman-only (FDB has no bed range, only a single bed temp)
    OpenTagExtraField(
        "spoolman_field_openprinttag_bed_temp_min",
        "openprinttag_bed_temp_min", "integer",
        "bedTempMin", "opt_bed_temp_min",
    ),
    # bed_temp_max: Spoolman-only.  FDB's single temperatures.bed is ALREADY synced
    # to/from Spoolman's native settings_bed_temp by MATERIAL_PROP_TEMP_PAIRS (engine.py,
    # "this pass owns them").  Adding temperatures.bed here too would make two Spoolman
    # fields (settings_bed_temp + this extra) fight over the same FDB field → ping-pong.
    # So this extra is Spoolman-side tracking only; bed temp still reaches FDB via the
    # native settings_bed_temp channel (OPT Apply populates settings_bed_temp from bedTempMax).
    OpenTagExtraField(
        "spoolman_field_openprinttag_bed_temp_max",
        "openprinttag_bed_temp_max", "integer",
        "bedTempMax", "opt_bed_temp_max",
    ),
    # --- Chamber temperature (all Spoolman-only — FDB has no chamber field) ---
    OpenTagExtraField(
        "spoolman_field_openprinttag_chamber_temp_min",
        "openprinttag_chamber_temp_min", "integer",
        "chamberTempMin", "opt_chamber_temp_min",
    ),
    OpenTagExtraField(
        "spoolman_field_openprinttag_chamber_temp_max",
        "openprinttag_chamber_temp_max", "integer",
        "chamberTempMax", "opt_chamber_temp_max",
    ),
    OpenTagExtraField(
        "spoolman_field_openprinttag_chamber_temp",
        "openprinttag_chamber_temp", "integer",
        "chamberTemp", "opt_chamber_temp",
    ),
    # --- Other Spoolman-only fields ---
    OpenTagExtraField(
        "spoolman_field_openprinttag_preheat_temp",
        "openprinttag_preheat_temp", "integer",
        "preheatTemp", "opt_preheat_temp",
    ),
    OpenTagExtraField(
        "spoolman_field_openprinttag_nozzle_diameter_min",
        "openprinttag_nozzle_diameter_min", "float",
        "nozzleDiameterMin", "opt_nozzle_diameter_min",
    ),
    OpenTagExtraField(
        "spoolman_field_openprinttag_cure_wavelength",
        "openprinttag_cure_wavelength", "integer",
        "cureWavelength", "opt_cure_wavelength",
    ),
)

# FDB targets for entries that have them must be in the writable allow-list.
assert all(
    f.fdb_path in FDB_SYNCABLE_FIELDS
    for f in OPENTAG_EXTRA_FIELDS
    if f.fdb_path is not None
)


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
