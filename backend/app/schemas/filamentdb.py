"""Pydantic response models for the Filament DB REST API.

Two projections exist:
  - List view  (GET /api/filaments)       → FDBFilament with FDBSpool (trimmed)
  - Detail view (GET /api/filaments/:id)  → FDBFilamentDetail with FDBSpoolDetail (full)

Models are lenient (extra="allow") for forward compatibility.

Fields starting with "_" (MongoDB conventions) are mapped via Field(alias=...) and
require populate_by_name=True so callers can also address them by their Python name.

IMPORTANT: Before any PUT, strip computed/read-only fields:
  _inherited, _parent, _variants, hasVariants, inherits, __v, instanceId,
  createdAt, updatedAt, _deletedAt, settings
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FDBTemperatures(BaseModel):
    model_config = ConfigDict(extra="allow")

    nozzle: float | None = None
    nozzleFirstLayer: float | None = None
    bed: float | None = None
    bedFirstLayer: float | None = None
    nozzleRangeMin: float | None = None
    nozzleRangeMax: float | None = None
    standby: float | None = None


# ---------------------------------------------------------------------------
# Spool models
# ---------------------------------------------------------------------------


class FDBSpool(BaseModel):
    """Trimmed spool subdocument returned in the filament list view."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str = Field(alias="_id")
    label: str | None = None
    totalWeight: float | None = None
    retired: bool = False


class FDBUsageEntry(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str | None = Field(None, alias="_id")
    grams: float
    jobLabel: str | None = None
    source: str | None = None
    date: str | None = None


class FDBSpoolDetail(BaseModel):
    """Full spool subdocument returned in the filament detail view."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str = Field(alias="_id")
    label: str | None = None
    totalWeight: float | None = None
    retired: bool = False
    location: str | None = None
    lotNumber: str | None = None
    usageHistory: list[FDBUsageEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Filament models
# ---------------------------------------------------------------------------


class FDBParentRef(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str = Field(alias="_id")
    name: str


class FDBVariantRef(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str = Field(alias="_id")
    name: str
    color: str | None = None
    cost: float | None = None
    optTags: list[Any] = Field(default_factory=list)


class FDBFilament(BaseModel):
    """Trimmed filament record from GET /api/filaments (list view)."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str = Field(alias="_id")
    name: str
    vendor: str | None = None
    type: str | None = None
    color: str | None = None
    cost: float | None = None
    density: float | None = None
    temperatures: FDBTemperatures | None = None
    spoolWeight: float | None = None
    netFilamentWeight: float | None = None
    totalWeight: float | None = None
    lowStockThreshold: float | None = None
    tdsUrl: str | None = None
    parentId: str | None = None
    optTags: list[Any] = Field(default_factory=list)
    hasCalibrations: bool = False
    hasVariants: bool = False
    spools: list[FDBSpool] = Field(default_factory=list)


class FDBFilamentDetail(BaseModel):
    """Full filament record from GET /api/filaments/:id (detail view).

    Includes server-resolved variant inheritance fields and full spool detail.
    hasVariants is absent here; use variants list instead.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str = Field(alias="_id")
    name: str
    vendor: str | None = None
    type: str | None = None
    color: str | None = None
    colorName: str | None = None
    cost: float | None = None
    density: float | None = None
    diameter: float | None = None
    maxVolumetricSpeed: float | None = None
    temperatures: FDBTemperatures | None = None
    spoolWeight: float | None = None
    netFilamentWeight: float | None = None
    totalWeight: float | None = None
    lowStockThreshold: float | None = None
    dryingTemperature: float | None = None
    dryingTime: float | None = None
    transmissionDistance: float | None = None
    glassTempTransition: float | None = None
    heatDeflectionTemp: float | None = None
    shoreHardnessA: float | None = None
    shoreHardnessD: float | None = None
    minPrintSpeed: float | None = None
    maxPrintSpeed: float | None = None
    spoolType: str | None = None
    tdsUrl: str | None = None
    shrinkageXY: float | None = None
    shrinkageZ: float | None = None
    parentId: str | None = None
    optTags: list[Any] = Field(default_factory=list)
    hasCalibrations: bool = False

    # Variant/inheritance fields (read-only; strip before PUT)
    inherited_fields: list[str] = Field(default_factory=list, alias="_inherited")
    parent: FDBParentRef | None = Field(None, alias="_parent")
    variants: list[FDBVariantRef] = Field(default_factory=list, alias="_variants")

    spools: list[FDBSpoolDetail] = Field(default_factory=list)
