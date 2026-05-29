"""Request/response models for the bridge's own REST API (Phase 3).

These models are the bridge↔UI contract. Upstream-shape models stay in
schemas/filamentdb.py and schemas/spoolman.py.

Every record-bearing response carries the IDs the UI needs to build both deep
links — the UI owns URL construction from the FILAMENTDB_URL / SPOOLMAN_URL env
bases (see docs/decisions.md):
  - Filament DB filament: {FILAMENTDB_URL}/filaments/{filamentdb_filament_id}
    (spool rows link to the parent filament — no standalone FDB spool page)
  - Spoolman spool:       {SPOOLMAN_URL}/spool/show/{spoolman_spool_id}
  - Spoolman filament:    {SPOOLMAN_URL}/filament/show/{spoolman_filament_id}
"""

from __future__ import annotations

import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

SourceOfTruth = Literal["spoolman", "filamentdb"]
SyncDirection = Literal["spoolman_to_filamentdb", "filamentdb_to_spoolman"]
MappingStatus = Literal["in_sync", "pending", "conflict", "unlinked"]

# Backup envelope schema version — bump when the export shape changes.
BACKUP_SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Shared connectivity shape (built from the health probe results)
# ---------------------------------------------------------------------------


class SystemStatus(BaseModel):
    status: Literal["ok", "error"]
    url: str
    version: str | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    error: str | None = None


# ---------------------------------------------------------------------------
# Sync (FR-8 / FR-14 / FR-18 / FR-15)
# ---------------------------------------------------------------------------


class CycleResultResponse(BaseModel):
    cycle_id: str
    dry_run: bool
    created: int
    updated: int
    conflicts: int
    skipped: int
    errors: int
    preview: list[dict[str, Any]] = Field(default_factory=list)


class AutoSyncRequest(BaseModel):
    enabled: bool


class AutoSyncResponse(BaseModel):
    auto_sync_enabled: bool


class SyncStatusResponse(BaseModel):
    """Dashboard payload (FR-15)."""

    last_sync_at: datetime.datetime | None = None
    next_sync_at: datetime.datetime | None = None
    auto_sync_enabled: bool
    wizard_completed: bool
    pending_conflicts: int
    counts: dict[str, int]  # in_sync / pending / conflict / unlinked / total
    systems: dict[str, SystemStatus]


# ---------------------------------------------------------------------------
# Conflicts (FR-13 / FR-16)
# ---------------------------------------------------------------------------


class ConflictResponse(BaseModel):
    id: int
    status: Literal["open", "resolved"]
    entity_type: str
    field_name: str
    # For spool conflicts spoolman_id is the Spoolman spool id (deep-link id).
    spoolman_id: int | None = None
    filamentdb_filament_id: str | None = None
    filamentdb_spool_id: str | None = None
    spoolman_value: Any = None
    filamentdb_value: Any = None
    detected_at: datetime.datetime
    resolved_at: datetime.datetime | None = None
    resolution: str | None = None
    resolved_value: Any = None


class ConflictResolveRequest(BaseModel):
    resolution: Literal["spoolman", "filamentdb", "manual"]
    value: Any = None  # required when resolution == "manual"


class BulkResolveRequest(BaseModel):
    ids: list[int]
    resolution: Literal["spoolman", "filamentdb", "manual"]
    value: Any = None


class BulkResolveResponse(BaseModel):
    resolved: int
    skipped: list[int] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Mappings (FR-19)
# ---------------------------------------------------------------------------


class MappingRow(BaseModel):
    id: int  # SpoolMapping.id
    status: MappingStatus
    spoolman_spool_id: int
    spoolman_filament_id: int | None = None
    filamentdb_filament_id: str
    filamentdb_spool_id: str
    filamentdb_parent_id: str | None = None
    name: str | None = None
    vendor: str | None = None
    color: str | None = None
    spoolman_weight: float | None = None  # net remaining (last snapshot)
    filamentdb_weight: float | None = None  # gross total (last snapshot)
    last_synced: datetime.datetime | None = None


class MappingUpdateRequest(BaseModel):
    filamentdb_filament_id: str | None = None
    filamentdb_spool_id: str | None = None
    filamentdb_parent_id: str | None = None


# ---------------------------------------------------------------------------
# Config (FR-2 ongoing settings)
# ---------------------------------------------------------------------------


class ConfigResponse(BaseModel):
    weight_source_of_truth: SourceOfTruth
    material_properties_source_of_truth: SourceOfTruth
    new_spool_source_of_truth: SourceOfTruth
    sync_weight_threshold_grams: float
    auto_sync_enabled: bool
    wizard_completed: bool
    import_direction: SourceOfTruth | None = None


class ConfigUpdateRequest(BaseModel):
    weight_source_of_truth: SourceOfTruth | None = None
    material_properties_source_of_truth: SourceOfTruth | None = None
    new_spool_source_of_truth: SourceOfTruth | None = None
    sync_weight_threshold_grams: float | None = Field(default=None, gt=0)


# ---------------------------------------------------------------------------
# Wizard (FR-1 … FR-6)
# ---------------------------------------------------------------------------


class WizardConnectivityResponse(BaseModel):
    status: Literal["ok", "degraded", "error"]
    bridge_version: str
    blocked: bool  # True when either system is unreachable — block further steps (FR-1)
    systems: dict[str, SystemStatus]


class WizardDirectionRequest(BaseModel):
    import_direction: SourceOfTruth
    weight_source_of_truth: SourceOfTruth | None = None
    material_properties_source_of_truth: SourceOfTruth | None = None
    new_spool_source_of_truth: SourceOfTruth | None = None


class FilamentRef(BaseModel):
    """A filament summary carrying both deep-link IDs where known."""

    spoolman_filament_id: int | None = None
    filamentdb_filament_id: str | None = None
    name: str | None = None
    vendor: str | None = None
    color: str | None = None


class MatchPairRow(BaseModel):
    spoolman: FilamentRef
    filamentdb: FilamentRef
    confidence: float
    # Set when both vendor names normalize equal but the raw strings differ
    # (e.g. "ELEGOO" vs "Elegoo") — FR-4 vendor dedup hint.
    vendor_dedup_hint: str | None = None


class AmbiguousRow(BaseModel):
    spoolman: FilamentRef
    candidates: list[FilamentRef]


class WizardMatchesResponse(BaseModel):
    matched: list[MatchPairRow]
    unmatched_spoolman: list[FilamentRef]
    unmatched_filamentdb: list[FilamentRef]
    ambiguous: list[AmbiguousRow]


class MatchDecision(BaseModel):
    spoolman_filament_id: int
    action: Literal["link", "create", "skip"]
    filamentdb_id: str | None = None  # required when action == "link"


class WizardMatchesRequest(BaseModel):
    decisions: list[MatchDecision]


class WizardDecisionAck(BaseModel):
    persisted: int


class WeightPreviewRow(BaseModel):
    direction: SyncDirection
    spoolman_spool_id: int | None = None
    filamentdb_filament_id: str | None = None
    filamentdb_spool_id: str | None = None
    name: str | None = None
    net_weight: float | None = None
    gross_weight: float | None = None
    tare: float
    tare_source: Literal["spoolman", "filamentdb", "default"]
    override_tare: float | None = None  # UI sets this to override at execute (Phase 3b)


class WizardWeightsResponse(BaseModel):
    direction: SyncDirection
    rows: list[WeightPreviewRow]


class VariantGroupRow(BaseModel):
    base_name: str
    vendor: str | None = None
    suggested_parent: FilamentRef
    variants: list[FilamentRef]


class WizardVariantsResponse(BaseModel):
    groups: list[VariantGroupRow]


class VariantDecision(BaseModel):
    parent_filamentdb_id: str
    variant_filamentdb_ids: list[str]


class WizardVariantsRequest(BaseModel):
    groups: list[VariantDecision]


# ---------------------------------------------------------------------------
# Backup (FR-24 / FR-25)
# ---------------------------------------------------------------------------


class BackupExport(BaseModel):
    schema_version: int = BACKUP_SCHEMA_VERSION
    exported_at: datetime.datetime
    config: dict[str, Any]
    filament_mappings: list[dict[str, Any]]
    spool_mappings: list[dict[str, Any]]
    open_conflicts: list[dict[str, Any]]


class BackupImportResponse(BaseModel):
    schema_version: int
    config: int
    filament_mappings: int
    spool_mappings: int
    conflicts: int


# ---------------------------------------------------------------------------
# Sync log (FR-17)
# ---------------------------------------------------------------------------


class SyncLogEntry(BaseModel):
    id: int
    cycle_id: str
    timestamp: datetime.datetime
    direction: str
    action: str
    entity_type: str
    spoolman_id: int | None = None
    filamentdb_filament_id: str | None = None
    filamentdb_spool_id: str | None = None
    field_name: str | None = None
    old_value: Any = None
    new_value: Any = None
    error_message: str | None = None


class SyncLogResponse(BaseModel):
    items: list[SyncLogEntry]
    total: int
    limit: int
    offset: int
