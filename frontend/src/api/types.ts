// Mirrors backend/app/schemas/api.py and backend/app/api/health.py exactly.
// If a field shape conflicts, the backend wins — fix here, never change the API.

export type SourceOfTruth = 'spoolman' | 'filamentdb'
export type SyncDirection = 'spoolman_to_filamentdb' | 'filamentdb_to_spoolman'
export type MappingStatus = 'in_sync' | 'pending' | 'conflict' | 'unlinked'

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

export interface SystemHealth {
  status: 'ok' | 'error'
  url: string
  version: string | null
  counts: Record<string, number>
  warnings: string[]
  error: string | null
}

export interface HealthResponse {
  status: 'ok' | 'degraded' | 'error'
  bridge_version: string
  systems: Record<string, SystemHealth>
}

// ---------------------------------------------------------------------------
// Shared connectivity shape (wizard + sync status)
// ---------------------------------------------------------------------------

export interface SystemStatus {
  status: 'ok' | 'error'
  url: string
  version: string | null
  counts: Record<string, number>
  warnings: string[]
  error: string | null
}

// ---------------------------------------------------------------------------
// Sync
// ---------------------------------------------------------------------------

export interface SyncPreviewEntry {
  action: 'create' | 'update' | 'conflict' | 'skip'
  entity_type: 'spool' | 'filament' | null
  direction: SyncDirection | null
  label: string
  field: string | null
  old: unknown
  new: unknown
  reason: string | null
  candidates: string[] | null
  spoolman_id: number | null
  fdb_filament_id: string | null
  fdb_spool_id: string | null
}

export interface CycleResultResponse {
  cycle_id: string
  dry_run: boolean
  created: number
  updated: number
  conflicts: number
  skipped: number
  errors: number
  preview: SyncPreviewEntry[]
}

export interface AutoSyncRequest {
  enabled: boolean
}

export interface AutoSyncResponse {
  auto_sync_enabled: boolean
}

export interface SyncStatusResponse {
  last_sync_at: string | null
  next_sync_at: string | null
  auto_sync_enabled: boolean
  wizard_completed: boolean
  pending_conflicts: number
  counts: Record<string, number>
  systems: Record<string, SystemStatus>
}

// ---------------------------------------------------------------------------
// Conflicts
// ---------------------------------------------------------------------------

export interface ConflictResponse {
  id: number
  status: 'open' | 'resolved'
  entity_type: string
  field_name: string
  spoolman_id: number | null
  filamentdb_filament_id: string | null
  filamentdb_spool_id: string | null
  spoolman_value: unknown
  filamentdb_value: unknown
  detected_at: string
  resolved_at: string | null
  resolution: string | null
  resolved_value: unknown
}

export interface ConflictResolveRequest {
  resolution: 'spoolman' | 'filamentdb' | 'manual'
  value?: unknown
}

export interface BulkResolveRequest {
  ids: number[]
  resolution: 'spoolman' | 'filamentdb' | 'manual'
  value?: unknown
}

export interface BulkResolveResponse {
  resolved: number
  skipped: number[]
}

// ---------------------------------------------------------------------------
// Mappings
// ---------------------------------------------------------------------------

export interface MappingRow {
  id: number
  status: MappingStatus
  spoolman_spool_id: number
  spoolman_filament_id: number | null
  filamentdb_filament_id: string
  filamentdb_spool_id: string
  filamentdb_parent_id: string | null
  name: string | null
  vendor: string | null
  color: string | null
  spoolman_weight: number | null
  filamentdb_weight: number | null
  last_synced: string | null
}

export interface MappingUpdateRequest {
  filamentdb_filament_id?: string | null
  filamentdb_spool_id?: string | null
  filamentdb_parent_id?: string | null
}

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

export interface ConfigResponse {
  weight_source_of_truth: SourceOfTruth
  material_properties_source_of_truth: SourceOfTruth
  new_spool_source_of_truth: SourceOfTruth
  sync_weight_threshold_grams: number
  weight_precision_decimals: number
  auto_sync_enabled: boolean
  wizard_completed: boolean
  import_direction: SourceOfTruth | null
  variant_line_keywords: string | null
}

export interface ConfigUpdateRequest {
  weight_source_of_truth?: SourceOfTruth | null
  material_properties_source_of_truth?: SourceOfTruth | null
  new_spool_source_of_truth?: SourceOfTruth | null
  sync_weight_threshold_grams?: number | null
  weight_precision_decimals?: number | null
  variant_line_keywords?: string | null
}

// ---------------------------------------------------------------------------
// Wizard
// ---------------------------------------------------------------------------

export interface WizardConnectivityResponse {
  status: 'ok' | 'degraded' | 'error'
  bridge_version: string
  blocked: boolean
  systems: Record<string, SystemStatus>
}

export interface WizardDirectionRequest {
  import_direction: SourceOfTruth
  weight_source_of_truth?: SourceOfTruth | null
  material_properties_source_of_truth?: SourceOfTruth | null
  new_spool_source_of_truth?: SourceOfTruth | null
  include_empty_spools?: boolean | null
}

export interface WizardDirectionResponse {
  import_direction: SourceOfTruth | null
  include_empty_spools: boolean
}

export interface FilamentRef {
  spoolman_filament_id: number | null
  filamentdb_filament_id: string | null
  name: string | null
  vendor: string | null
  color: string | null
  material?: string | null
}

export interface MatchPairRow {
  spoolman: FilamentRef
  filamentdb: FilamentRef
  confidence: number
  vendor_dedup_hint: string | null
}

export interface AmbiguousRow {
  spoolman: FilamentRef
  candidates: FilamentRef[]
}

export interface WizardMatchesResponse {
  matched: MatchPairRow[]
  unmatched_spoolman: FilamentRef[]
  unmatched_filamentdb: FilamentRef[]
  ambiguous: AmbiguousRow[]
  saved_decisions: MatchDecision[]
}

export interface MatchDecision {
  spoolman_filament_id: number
  action: 'link' | 'create' | 'skip'
  filamentdb_id?: string | null
}

export interface WizardMatchesRequest {
  decisions: MatchDecision[]
}

export interface WizardDecisionAck {
  persisted: number
}

export interface WeightPreviewRow {
  direction: SyncDirection
  spoolman_spool_id: number | null
  filamentdb_filament_id: string | null
  filamentdb_spool_id: string | null
  name: string | null
  net_weight: number | null
  gross_weight: number | null
  tare: number
  tare_source: 'spoolman' | 'filamentdb' | 'default'
  override_tare: number | null
}

export interface WizardWeightsResponse {
  direction: SyncDirection
  rows: WeightPreviewRow[]
}

export interface VariantGroupRow {
  base_name: string
  vendor: string | null
  suggested_parent: FilamentRef
  variants: FilamentRef[]
}

export interface VariantPropConflict {
  field: string
  master_value: unknown
  member_value: unknown
}

export interface SMVariantMemberRow {
  ref: FilamentRef
  is_master: boolean
  conflicts: VariantPropConflict[]
}

export interface SMVariantGroupRow {
  base_name: string
  vendor: string | null
  material: string | null
  suggested_master: FilamentRef
  members: SMVariantMemberRow[]
}

export interface SMVariantDecision {
  master_spoolman_filament_id: number
  variant_spoolman_filament_ids: number[]
  existing_fdb_parent_id?: string | null
}

export interface SMVariantsRequest {
  groups: SMVariantDecision[]
}

export interface WizardVariantsResponse {
  direction: string
  sm_groups: SMVariantGroupRow[]
  fdb_groups: VariantGroupRow[]
}

// ---------------------------------------------------------------------------
// Variances endpoint (merged Weights + Variants step)
// ---------------------------------------------------------------------------

export interface VariancesFilament {
  ref: FilamentRef
  spool_ids: number[]
  tare: number
  tare_source: 'spoolman' | 'default'
  is_master: boolean
  conflicts: VariantPropConflict[]
  suggest_exclude: boolean
  material: string | null
  density: number | null
  spool_weight: number | null
  settings_extruder_temp: number | null
  settings_bed_temp: number | null
  // Phase 1 enriched display fields
  material_type: string | null
  diameter: number | null
  color_hex: string | null
}

// Phase 2 — per-group reconcile decisions
export interface ReconciledField {
  field: string
  value: unknown
  source: 'spoolman_filament' | 'manual'
  source_spoolman_filament_id: number | null
}

export interface VariancesGroupReconcile {
  master_spoolman_filament_id: number
  fields: ReconciledField[]
}

export interface SMVariancesDecisionsRequest {
  groups: SMVariantDecision[]
  reconcile?: VariancesGroupReconcile[]
}

export interface VariancesGroupRow {
  base_name: string
  vendor: string | null
  material: string | null
  finish?: string | null
  suggested_master: FilamentRef
  members: VariancesFilament[]
  existing_fdb_parent: FilamentRef | null
}

export interface VariancesResponse {
  direction: string
  groups: VariancesGroupRow[]
  ungrouped: VariancesFilament[]
}

export interface VariantDecision {
  parent_filamentdb_id: string
  variant_filamentdb_ids: string[]
}

export interface WizardVariantsRequest {
  groups: VariantDecision[]
}

export interface WizardTareOverride {
  spoolman_spool_id?: number | null
  filamentdb_spool_id?: string | null
  tare: number
}

export interface WizardExecuteRequest {
  tare_overrides: WizardTareOverride[]
}

export interface WizardExecuteRecord {
  entity_type: 'filament' | 'spool'
  action: 'created' | 'updated' | 'skipped' | 'failed'
  spoolman_filament_id: number | null
  spoolman_spool_id: number | null
  filamentdb_filament_id: string | null
  filamentdb_spool_id: string | null
  detail: string | null
  error: string | null
}

export interface WizardExecuteResponse {
  cycle_id: string
  direction: SyncDirection
  created: number
  updated: number
  skipped: number
  failed: number
  wizard_completed: boolean
  records: WizardExecuteRecord[]
}

// ---------------------------------------------------------------------------
// Wizard preview (FR-4 foundation — read-only reconcile surface)
// ---------------------------------------------------------------------------

export interface NameCollisionEntry {
  normalized_name: string
  sm_filament_ids: number[]
  vs_existing: boolean
  intra_batch: boolean
  existing_fdb_filament_id: string | null
}

export interface EmptyActiveEntry {
  spoolman_spool_id: number
  spoolman_filament_id: number | null
  name: string | null
}

export interface DefaultTareEntry {
  spoolman_spool_id: number
  spoolman_filament_id: number | null
  name: string | null
  planned_gross: number
  default_tare_used: number
}

export interface VariantGroupPreviewEntry {
  base_name: string
  vendor: string | null
  material: string | null
  sm_filament_ids: number[]
}

export interface PreviewFlagCounts {
  name_collision: number
  empty_active: number
  default_tare: number
  variant_group: number
}

// Phase 4 — planned writes summary
export interface PlannedWriteField {
  name: string
  old: unknown
  new: unknown
}

export interface PlannedWrite {
  system: 'filamentdb' | 'spoolman'
  entity_type: 'filament' | 'spool'
  action: 'create' | 'update'
  target_label: string
  fields: PlannedWriteField[]
}

export interface WizardPreviewResponse {
  direction: SyncDirection
  plan_rows: WizardExecuteRecord[]
  flag_counts: PreviewFlagCounts
  name_collisions: NameCollisionEntry[]
  empty_active: EmptyActiveEntry[]
  default_tare: DefaultTareEntry[]
  variant_groups: VariantGroupPreviewEntry[]
  variant_plan: SMVariantGroupRow[]
  include_empty_spools: boolean
  planned_writes: PlannedWrite[]
}

// ---------------------------------------------------------------------------
// Backup
// ---------------------------------------------------------------------------

export interface BackupExport {
  schema_version: number
  exported_at: string
  config: Record<string, unknown>
  filament_mappings: Record<string, unknown>[]
  spool_mappings: Record<string, unknown>[]
  open_conflicts: Record<string, unknown>[]
}

export interface BackupImportResponse {
  schema_version: number
  config: number
  filament_mappings: number
  spool_mappings: number
  conflicts: number
}

// ---------------------------------------------------------------------------
// Sync log
// ---------------------------------------------------------------------------

export interface SyncLogEntry {
  id: number
  cycle_id: string
  timestamp: string
  direction: string
  action: string
  entity_type: string
  spoolman_id: number | null
  filamentdb_filament_id: string | null
  filamentdb_spool_id: string | null
  field_name: string | null
  old_value: unknown
  new_value: unknown
  error_message: string | null
}

export interface SyncLogResponse {
  items: SyncLogEntry[]
  total: number
  limit: number
  offset: number
}

// ---------------------------------------------------------------------------
// Error envelope (from api/errors.py)
// ---------------------------------------------------------------------------

export interface ApiErrorDetail {
  code: string
  message: string
}

export interface ApiError {
  detail: ApiErrorDetail | string
}
