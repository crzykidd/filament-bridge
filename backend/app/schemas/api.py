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

# New two-axis sync model
SyncDirection2 = Literal["two_way", "spoolman_to_filamentdb", "filamentdb_to_spoolman"]
ConflictPolicy = Literal["manual", "spoolman_wins", "filamentdb_wins", "newest_wins"]

# Variant parent mode for the Bulk Import Wizard (Spoolman → FDB direction).
VariantParentMode = Literal["unset", "promote_color", "generic_container"]

# New-record handling policy for ongoing sync (not the wizard).
NewRecordPolicy = Literal["manual_review", "auto_import"]

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
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


# ---------------------------------------------------------------------------
# Sync (FR-8 / FR-14 / FR-18 / FR-15)
# ---------------------------------------------------------------------------


class SyncPreviewEntry(BaseModel):
    action: Literal["create", "update", "conflict", "skip", "matched"]
    entity_type: Literal["spool", "filament"] | None = None
    direction: Literal["spoolman_to_filamentdb", "filamentdb_to_spoolman", "conflict"] | None = None
    label: str
    field: str | None = None
    old: Any = None
    new: Any = None
    reason: str | None = None
    candidates: list[str] | None = None  # FDB filament IDs for ambiguous-match conflicts
    spoolman_id: int | None = None
    fdb_filament_id: str | None = None
    fdb_spool_id: str | None = None


class CycleResultResponse(BaseModel):
    cycle_id: str
    dry_run: bool
    created: int
    updated: int
    conflicts: int
    skipped: int
    errors: int
    preview: list[SyncPreviewEntry] = Field(default_factory=list)


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
    counts: dict[str, int]  # in_sync / pending / conflict / unlinked / total (spool counts)
    # Filament-level counts (excludes synthetic NULL-spoolman_filament_id masters).
    # Keys: in_sync / pending / conflict / total
    filament_counts: dict[str, int] = Field(default_factory=dict)
    systems: dict[str, SystemStatus]
    # True when an upstream version is below the minimum supported → sync is
    # refused. blocked_reasons holds the per-system upgrade messages.
    sync_blocked: bool = False
    sync_blocked_reasons: list[str] = []


# ---------------------------------------------------------------------------
# Conflicts (FR-13 / FR-16)
# ---------------------------------------------------------------------------


class ConflictResponse(BaseModel):
    id: int
    status: Literal["open", "resolved"]
    entity_type: str
    field_name: str
    # "cross_system" — both sides changed the same field (the standard conflict).
    # "master_divergence" — SM→FDB write would override a variant's inherited master value;
    #   requires Phase B approval before applying. Record-only in Phase A.
    conflict_type: str = "cross_system"
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
    # Identity fields sourced from the Spoolman snapshot (read-only enrichment).
    label: str | None = None
    vendor: str | None = None
    name: str | None = None
    color_hex: str | None = None
    multi_color_hexes: str | None = None
    multi_color_direction: str | None = None
    material: str | None = None


class ConflictResolveRequest(BaseModel):
    resolution: Literal["spoolman", "filamentdb", "manual"]
    value: Any = None  # required when resolution == "manual"
    # Required for master_divergence conflicts; ignored for all other conflict types.
    action: Literal["apply_all", "variant_override", "ignore"] | None = None


class DivergenceVariantEntry(BaseModel):
    fdb_id: str
    name: str | None = None
    color_hex: str | None = None
    spoolman_filament_id: int | None = None
    current_value: Any = None
    inherited: bool


class DivergenceContextResponse(BaseModel):
    """Context for a master_divergence conflict: master + full variant line."""
    master_fdb_id: str
    master_name: str | None = None
    master_current_value: Any = None
    field_name: str   # SM field name (e.g. "density", "material")
    fdb_path: str     # FDB path (e.g. "density", "type")
    variants: list[DivergenceVariantEntry] = Field(default_factory=list)


class ConflictImportRequest(BaseModel):
    """Request body for POST /api/conflicts/{conflict_id}/import.

    Scoped single-record import: imports the filament (and optionally its spool)
    referenced by a new_filament or new_spool conflict, using the existing
    wizard/planner logic.  Dry-run returns a preview without writing.
    """
    dry_run: bool = False
    # "create" → create a new filament in the target system.
    # "link"   → link to an existing filament (filamentdb_id required for SM→FDB conflicts;
    #             spoolman_filament_id not yet supported for FDB→SM conflicts — use create).
    filament_action: Literal["create", "link"] = "create"
    # For filament_action=="link" (SM→FDB): the existing FDB filament id to link to.
    filamentdb_id: str | None = None
    # Optional tare override in grams (overrides the filament's spool_weight / spoolWeight).
    tare_override: float | None = None
    # For variant grouping: if the SM filament should become a child of an existing
    # FDB filament, supply that id here (only used when filament_action=="create").
    master_filamentdb_id: str | None = None


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


class MappingDetailField(BaseModel):
    """One synced field with the last-known value on each side (for the expandable row)."""
    field: str
    label: str
    spoolman: object | None = None
    filamentdb: object | None = None


class MappingRow(BaseModel):
    id: int  # SpoolMapping.id for kind="spool"; FilamentMapping.id for kind="filament"
    status: MappingStatus
    # kind="spool"    → a normal spool pair row (spoolman_spool_id and filamentdb_spool_id are set)
    # kind="filament" → a filament-only row (no Spoolman spool; spool ids/weights are None)
    kind: Literal["spool", "filament"] = "spool"
    spoolman_spool_id: int | None = None       # None for kind="filament"
    spoolman_filament_id: int | None = None
    filamentdb_filament_id: str
    filamentdb_spool_id: str | None = None     # None for kind="filament"
    filamentdb_parent_id: str | None = None
    name: str | None = None
    vendor: str | None = None
    color: str | None = None
    spoolman_weight: float | None = None  # net remaining (last snapshot)
    filamentdb_weight: float | None = None  # gross total (last snapshot)
    last_synced: datetime.datetime | None = None
    # Enrichment fields (all default None)
    multi_color_hexes: str | None = None       # comma-separated hex list from SM filament snapshot
    multi_color_direction: str | None = None   # "longitudinal" | "coaxial" | None
    remaining_weight: float | None = None      # SM spool remaining_weight (same as spoolman_weight; named for clarity)
    is_empty: bool = False                     # True when remaining_weight <= 0
    conflict_id: int | None = None             # open Conflict.id for this spool/filament (status=="conflict" rows)
    detail: list[MappingDetailField] = []      # per-side values for the expandable row


class MappingUpdateRequest(BaseModel):
    filamentdb_filament_id: str | None = None
    filamentdb_spool_id: str | None = None
    filamentdb_parent_id: str | None = None


# ---------------------------------------------------------------------------
# Filament suggestions (conflict Add "link" UX — P2)
# ---------------------------------------------------------------------------


class FilamentSuggestion(BaseModel):
    """One candidate FDB filament for the conflict Add "link" dropdown."""

    filamentdb_id: str
    name: str | None = None
    vendor: str | None = None
    color: str | None = None
    material: str | None = None
    score: float  # 0.0–1.0; 1.0 = exact key match
    # True when this FDB filament is a master/parent (has variants or synthetic).
    is_master_container: bool = False
    # Set when this filament is a variant child: the FDB id of its parent.
    parent_id: str | None = None
    # Human-readable variant label (e.g. "Red", "Silk Blue") derived from the name.
    variant_label: str | None = None


class FilamentSuggestionsResponse(BaseModel):
    suggestions: list[FilamentSuggestion]


# ---------------------------------------------------------------------------
# Config (FR-2 ongoing settings)
# ---------------------------------------------------------------------------


class ConfigResponse(BaseModel):
    sync_weight_threshold_grams: float
    weight_precision_decimals: int
    auto_sync_enabled: bool
    wizard_completed: bool
    import_direction: SourceOfTruth | None = None
    variant_line_keywords: str | None = None
    opentag_vendor_aliases: str | None = None
    # Two-axis sync direction + conflict policy (new model)
    weight_sync_direction: SyncDirection2 = "spoolman_to_filamentdb"
    weight_conflict_policy: ConflictPolicy = "manual"
    material_properties_sync_direction: SyncDirection2 = "filamentdb_to_spoolman"
    material_properties_conflict_policy: ConflictPolicy = "manual"
    # Archive/retire lifecycle sync (mirrors SM archived ↔ FDB retired for mapped pairs).
    # newest_wins is rejected (booleans aren't timestamp-eligible) — same as material_properties.
    archive_sync_direction: SyncDirection2 = "two_way"
    archive_conflict_policy: ConflictPolicy = "manual"
    new_spool_sync_direction: SyncDirection2 = "two_way"
    # New-record handling policies
    # manual_review (default) → queue an actionable conflict; auto_import → create immediately.
    new_filament_policy: NewRecordPolicy = "manual_review"
    new_spool_policy: NewRecordPolicy = "manual_review"
    # Scheduler settings
    sync_interval_seconds: int = 120
    sync_log_retention_days: int = 30
    # Import behaviour
    never_import_empties: bool = False
    # Debug mode — exposes /api/debug/* reset endpoints when true
    debug_mode: bool = False
    # Variant parent mode for the Bulk Import Wizard (Spoolman → FDB direction).
    # "unset" means the user has not yet chosen; wizard is gated until chosen.
    variant_parent_mode: VariantParentMode = "unset"
    # Marker appended to generic-container parent names (default "(Master)").
    # Empty string = no marker (containers get no suffix).
    container_parent_marker: str = "(Master)"
    # API token settings — token value is included so Settings can display it.
    # admin_password_hash and auth_secret are NEVER included in any response.
    api_token: str | None = None
    api_token_enabled: bool = False
    # Required settings that must be configured before the bridge is usable.
    # Frontend redirects to /settings and shows a modal when this list is non-empty.
    required_settings_unset: list[str] = Field(default_factory=list)


class ConfigUpdateRequest(BaseModel):
    sync_weight_threshold_grams: float | None = Field(default=None, gt=0)
    weight_precision_decimals: int | None = Field(default=None, ge=0, le=4)
    variant_line_keywords: str | None = None
    opentag_vendor_aliases: str | None = None
    # Two-axis sync direction + conflict policy (new model)
    weight_sync_direction: SyncDirection2 | None = None
    weight_conflict_policy: ConflictPolicy | None = None
    material_properties_sync_direction: SyncDirection2 | None = None
    material_properties_conflict_policy: ConflictPolicy | None = None
    # Archive/retire lifecycle sync.
    archive_sync_direction: SyncDirection2 | None = None
    archive_conflict_policy: ConflictPolicy | None = None
    new_spool_sync_direction: SyncDirection2 | None = None
    # New-record handling policies
    new_filament_policy: NewRecordPolicy | None = None
    new_spool_policy: NewRecordPolicy | None = None
    # Scheduler settings
    sync_interval_seconds: int | None = Field(default=None, ge=30)
    sync_log_retention_days: int | None = Field(default=None, ge=0)
    # Import behaviour
    never_import_empties: bool | None = None
    # Debug mode
    debug_mode: bool | None = None
    # Variant parent mode
    variant_parent_mode: VariantParentMode | None = None
    # Container parent marker (empty string = no suffix)
    container_parent_marker: str | None = None
    # API token control (value managed via /auth/api-token/regenerate; only flag is updatable here)
    api_token_enabled: bool | None = None


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


class WizardDirectionResponse(BaseModel):
    import_direction: SourceOfTruth | None = None
    include_empty_spools: bool = False


class FilamentRef(BaseModel):
    """A filament summary carrying both deep-link IDs where known."""

    spoolman_filament_id: int | None = None
    filamentdb_filament_id: str | None = None
    name: str | None = None
    vendor: str | None = None
    color: str | None = None
    material: str | None = None
    # True when the Spoolman filament has a non-empty openprinttag_uuid extra field.
    # Always False for FDB-only refs (no SM side).
    openprinttag: bool = False
    # True when this FDB ref is a synthetic container parent (bridge-owned, no SM counterpart).
    # Used in the Matches step to show a "Master / Parent" badge instead of "Unmatched (FDB)".
    is_master_container: bool = False


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
    saved_decisions: list[MatchDecision] = Field(default_factory=list)


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


# ---------------------------------------------------------------------------
# SM-direction variant grouping (FR-6, import_direction="spoolman")
# ---------------------------------------------------------------------------


class VariantPropConflict(BaseModel):
    """A property that disagrees between a variant and its proposed master."""

    field: str
    master_value: Any = None
    member_value: Any = None


class SMVariantMemberRow(BaseModel):
    ref: FilamentRef
    is_master: bool
    conflicts: list[VariantPropConflict] = Field(default_factory=list)


class SMVariantGroupRow(BaseModel):
    base_name: str
    vendor: str | None = None
    material: str | None = None
    suggested_master: FilamentRef
    members: list[SMVariantMemberRow]


class SMVariantDecision(BaseModel):
    master_spoolman_filament_id: int
    variant_spoolman_filament_ids: list[int]
    existing_fdb_parent_id: str | None = None


class SMVariantsRequest(BaseModel):
    groups: list[SMVariantDecision]


class WizardVariantsResponse(BaseModel):
    direction: str = "filamentdb"  # "spoolman" | "filamentdb"
    sm_groups: list[SMVariantGroupRow] = Field(default_factory=list)
    fdb_groups: list[VariantGroupRow] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Variances endpoint (merged Weights + Variants step)
# ---------------------------------------------------------------------------


class VariancesFilament(BaseModel):
    """One SM filament in the merged variances view — carries group membership and comparable props."""

    ref: FilamentRef
    spool_ids: list[int] = Field(default_factory=list)
    tare: float
    tare_source: Literal["spoolman", "default"]
    is_master: bool = False
    conflicts: list[VariantPropConflict] = Field(default_factory=list)
    suggest_exclude: bool = False
    # Comparable props returned so the client can recompute conflicts live
    material: str | None = None
    density: float | None = None
    spool_weight: float | None = None
    settings_extruder_temp: int | None = None
    settings_bed_temp: int | None = None
    # Phase 1: enriched display fields
    material_type: str | None = None  # matched FDB filament's `type` field (or null if no match)
    diameter: float | None = None  # Spoolman filament diameter
    color_hex: str | None = None  # Spoolman filament color_hex (for swatch display)


class VariancesGroupRow(BaseModel):
    base_name: str
    vendor: str | None = None
    material: str | None = None
    finish: str | None = None  # Part B: finish/line token ('silk', 'matte', 'cf', …) or None (standard)
    suggested_master: FilamentRef
    members: list[VariancesFilament]
    existing_fdb_parent: FilamentRef | None = None


class VariancesResponse(BaseModel):
    direction: str
    groups: list[VariancesGroupRow] = Field(default_factory=list)
    ungrouped: list[VariancesFilament] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Phase 2 — Per-field reconciliation
# ---------------------------------------------------------------------------


class ReconciledField(BaseModel):
    """One reconciled canonical field for a variant group."""

    field: str  # canonical key: type | density | diameter | nozzle_temp | bed_temp | spool_weight
    value: Any
    source: Literal["spoolman_filament", "manual"]
    source_spoolman_filament_id: int | None = None  # set when source == "spoolman_filament"


class VariancesGroupReconcile(BaseModel):
    """Per-group reconciliation decisions (one per variant group)."""

    master_spoolman_filament_id: int
    fields: list[ReconciledField] = Field(default_factory=list)


class SMVariancesDecisionsRequest(BaseModel):
    """Extends the existing SM variants POST to include reconciliation decisions.

    This replaces (extends) the SMVariantsRequest to carry both grouping + reconcile
    decisions in a single call, persisted via the existing wizard_sm_variant_decisions
    and the new wizard_variances_reconcile BridgeConfig keys.
    """

    groups: list[SMVariantDecision] = Field(default_factory=list)
    reconcile: list[VariancesGroupReconcile] = Field(default_factory=list)


class VariantDecision(BaseModel):
    parent_filamentdb_id: str
    variant_filamentdb_ids: list[str]


class WizardVariantsRequest(BaseModel):
    groups: list[VariantDecision]


# ---------------------------------------------------------------------------
# Wizard execute (FR-7) — the initial-sync write to both upstreams
# ---------------------------------------------------------------------------


class WizardTareOverride(BaseModel):
    """A per-spool tare override from the FR-5 weight-review step.

    Weight overrides are not persisted in BridgeConfig (unlike match/variant
    decisions) — the UI collects them on the review screen and submits them with
    the execute call. Key by whichever spool id the active import direction uses.
    """

    spoolman_spool_id: int | None = None
    filamentdb_spool_id: str | None = None
    tare: float


class WizardExecuteRequest(BaseModel):
    tare_overrides: list[WizardTareOverride] = Field(default_factory=list)


class WizardExecuteRecord(BaseModel):
    """One per-record line in the FR-7 report, carrying both deep-link IDs."""

    entity_type: Literal["filament", "spool"]
    action: Literal["created", "updated", "skipped", "failed"]
    spoolman_filament_id: int | None = None
    spoolman_spool_id: int | None = None
    filamentdb_filament_id: str | None = None
    filamentdb_spool_id: str | None = None
    # Human-readable label for display in the execute result (e.g. "ELEGOO PLA Red").
    # Set to whichever name/identifier is available at the call site.
    label: str | None = None
    detail: str | None = None
    error: str | None = None


class WizardExecuteResponse(BaseModel):
    cycle_id: str
    direction: SyncDirection
    # Flat totals (existing — do not remove; frontend + tests depend on these)
    created: int
    updated: int
    skipped: int
    failed: int
    wizard_completed: bool
    records: list[WizardExecuteRecord] = Field(default_factory=list)
    # Per-type breakdown (filaments vs spools)
    created_filaments: int = 0
    created_spools: int = 0
    updated_filaments: int = 0
    updated_spools: int = 0
    skipped_filaments: int = 0
    skipped_spools: int = 0
    failed_filaments: int = 0
    failed_spools: int = 0


# ---------------------------------------------------------------------------
# Wizard preview (FR-4 foundation — read-only reconcile surface)
# ---------------------------------------------------------------------------


class NameCollisionEntry(BaseModel):
    """A filament name that would collide on import into Filament DB."""

    normalized_name: str
    sm_filament_ids: list[int]
    vs_existing: bool  # clashes with an already-existing FDB filament
    intra_batch: bool  # multiple incoming SM filaments share this normalized name
    existing_fdb_filament_id: str | None = None
    # True when this collision is on a synthetic container parent name.
    # Container collisions render an editable rename box + skip control in Preview.
    is_container_collision: bool = False
    # The cluster key string for this container collision (used to persist override).
    cluster_key: str | None = None
    # The proposed container name (before any user override).
    proposed_name: str | None = None


class EmptyActiveEntry(BaseModel):
    """A Spoolman spool that is empty (remaining ≤ 0) or archived.

    ``archived=True`` means the spool is archived in Spoolman — when imported, it will
    become a *retired* spool in Filament DB (``retired: true``). When ``never_import_empties``
    is off (the default), both empty-active and archived/empty spools are imported.
    """

    spoolman_spool_id: int
    spoolman_filament_id: int | None = None
    name: str | None = None
    archived: bool = False  # True when the spool is archived in Spoolman (imports as retired)


class DefaultTareEntry(BaseModel):
    """A planned spool create that used the 200 g default tare (no spool_weight set)."""

    spoolman_spool_id: int
    spoolman_filament_id: int | None = None
    name: str | None = None
    planned_gross: float
    default_tare_used: float


class VariantGroupPreviewEntry(BaseModel):
    """A proposed variant group among to-be-created filaments (vendor + material + base_name)."""

    base_name: str
    vendor: str | None = None
    material: str | None = None
    sm_filament_ids: list[int]


class PreviewFlagCounts(BaseModel):
    name_collision: int
    empty_active: int
    default_tare: int
    variant_group: int


class PlannedWriteField(BaseModel):
    """A field-level change in a planned write operation."""

    name: str
    old: Any  # None for creates
    new: Any


class PlannedWrite(BaseModel):
    """One planned write operation shown in the Phase-4 pre-flight summary."""

    system: Literal["filamentdb", "spoolman"]
    entity_type: Literal["filament", "spool"]
    action: Literal["create", "update"]
    target_label: str  # human-readable identifier (name + system id)
    fields: list[PlannedWriteField] = Field(default_factory=list)


class ContainerNameOverride(BaseModel):
    """A per-cluster container-name override (or skip) from the Preview rename UI.

    ``cluster_key`` is the str-representation of the cluster tuple
    (vendor_norm, material_norm, finish_norm).  The execute path looks up
    this key and replaces the generated container name with ``name_override``
    (or skips the cluster when ``skip`` is True).
    """

    cluster_key: str  # str(cluster_tuple) from sm_variant_cluster_key
    name_override: str | None = None  # new container name; None when skip=True
    skip: bool = False  # True = skip this cluster (don't create a container)


class ContainerNameOverridesRequest(BaseModel):
    overrides: list[ContainerNameOverride]


class WizardPreviewResponse(BaseModel):
    direction: SyncDirection
    plan_rows: list[WizardExecuteRecord]
    flag_counts: PreviewFlagCounts
    name_collisions: list[NameCollisionEntry]
    empty_active: list[EmptyActiveEntry]
    default_tare: list[DefaultTareEntry]
    variant_groups: list[VariantGroupPreviewEntry]
    variant_plan: list[SMVariantGroupRow] = Field(default_factory=list)
    include_empty_spools: bool = False
    # Phase 4: structured write summary for the pre-flight review
    planned_writes: list[PlannedWrite] = Field(default_factory=list)
    # Saved container-name overrides (populated from persisted wizard_container_name_overrides)
    container_name_overrides: list[ContainerNameOverride] = Field(default_factory=list)


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
    # Human-readable record name ("Vendor Name"), resolved at read time from the
    # filament/spool mapping identity. None when the record can't be resolved.
    label: str | None = None
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


class SyncLogDeleteResponse(BaseModel):
    deleted: int


# ---------------------------------------------------------------------------
# Reconcile report (read-only — no upstream writes)
# ---------------------------------------------------------------------------


class ReconcileMatchRow(BaseModel):
    """A matched pair of filaments (one SM, one FDB) with spool roll-ups."""

    spoolman: FilamentRef
    filamentdb: FilamentRef
    confidence: float
    # True when the pair came from an existing cross-ref (xref pre-pass, conf 1.0).
    # False when matched by exact normalized vendor+name+color key.
    linked: bool
    spoolman_spools: int
    filamentdb_spools: int
    spoolman_weight: float | None
    filamentdb_weight: float | None
    # Name of the FDB parent filament when this row is a variant child (parentId set);
    # None for top-level filaments.
    variant_of: str | None = None


class ReconcileMissingRow(BaseModel):
    """A filament that exists on one side only."""

    ref: FilamentRef
    spool_count: int
    weight_total: float | None


class ReconcileSummary(BaseModel):
    spoolman_filaments: int
    filamentdb_filaments: int
    matched: int
    only_in_spoolman: int
    only_in_filamentdb: int
    ambiguous: int


class ReconcileResponse(BaseModel):
    summary: ReconcileSummary
    matched: list[ReconcileMatchRow]
    only_in_spoolman: list[ReconcileMissingRow]
    only_in_filamentdb: list[ReconcileMissingRow]
    ambiguous: list[AmbiguousRow]
