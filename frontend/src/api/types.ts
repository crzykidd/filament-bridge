// Mirrors backend/app/schemas/api.py and backend/app/api/health.py exactly.
// If a field shape conflicts, the backend wins — fix here, never change the API.

// ---------------------------------------------------------------------------
// Backup
// ---------------------------------------------------------------------------

export interface BackupSpoolmanResponse {
  success: boolean
  detail: string
}

export interface BackupFilamentDbResponse {
  success: boolean
  detail: string
}

export type SourceOfTruth = 'spoolman' | 'filamentdb'
export type SyncDirection = 'spoolman_to_filamentdb' | 'filamentdb_to_spoolman'
export type SyncDirection2 = 'two_way' | 'spoolman_to_filamentdb' | 'filamentdb_to_spoolman'
export type ConflictPolicy = 'manual' | 'spoolman_wins' | 'filamentdb_wins' | 'newest_wins'
export type MappingStatus = 'in_sync' | 'pending' | 'conflict' | 'unlinked'
export type VariantParentMode = 'unset' | 'promote_color' | 'generic_container'

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
  action: 'create' | 'update' | 'conflict' | 'skip' | 'matched'
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
  sync_blocked: boolean
  sync_blocked_reasons: string[]
}

// ---------------------------------------------------------------------------
// Conflicts
// ---------------------------------------------------------------------------

export interface ConflictResponse {
  id: number
  status: 'open' | 'resolved'
  entity_type: string
  field_name: string
  // "cross_system" — both sides changed. "master_divergence" — SM→FDB would override
  // an inherited variant field; requires action before applying.
  conflict_type: string
  spoolman_id: number | null
  filamentdb_filament_id: string | null
  filamentdb_spool_id: string | null
  spoolman_value: unknown
  filamentdb_value: unknown
  detected_at: string
  resolved_at: string | null
  resolution: string | null
  resolved_value: unknown
  // Identity fields sourced from the Spoolman snapshot (read-only enrichment).
  label: string | null
  vendor: string | null
  name: string | null
  color_hex: string | null
  multi_color_hexes: string | null
  multi_color_direction: string | null
  material: string | null
}

export interface ConflictResolveRequest {
  resolution: 'spoolman' | 'filamentdb' | 'manual'
  value?: unknown
  // Required for master_divergence conflicts; ignored for other types.
  action?: 'apply_all' | 'variant_override' | 'ignore'
}

export interface DivergenceVariantEntry {
  fdb_id: string
  name: string | null
  color_hex: string | null
  spoolman_filament_id: number | null
  current_value: unknown
  inherited: boolean
}

export interface DivergenceContextResponse {
  master_fdb_id: string
  master_name: string | null
  master_current_value: unknown
  field_name: string   // SM field name (e.g. "density", "material")
  fdb_path: string     // FDB path (e.g. "density", "type")
  variants: DivergenceVariantEntry[]
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

export interface MappingDetailField {
  field: string
  label: string
  spoolman: string | number | null
  filamentdb: string | number | null
}

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
  // Enrichment fields
  multi_color_hexes: string | null
  multi_color_direction: string | null
  remaining_weight: number | null
  is_empty: boolean
  conflict_id: number | null
  detail: MappingDetailField[]
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
  sync_weight_threshold_grams: number
  weight_precision_decimals: number
  auto_sync_enabled: boolean
  wizard_completed: boolean
  import_direction: SourceOfTruth | null
  variant_line_keywords: string | null
  opentag_vendor_aliases: string | null
  opentag_color_keywords: string | null
  weight_sync_direction: SyncDirection2
  weight_conflict_policy: ConflictPolicy
  material_properties_sync_direction: SyncDirection2
  material_properties_conflict_policy: Exclude<ConflictPolicy, 'newest_wins'>
  new_spool_sync_direction: SyncDirection2
  // Scheduler settings
  sync_interval_seconds: number
  sync_log_retention_days: number
  // Import behaviour
  never_import_empties: boolean
  // Debug mode — exposes /api/debug/* reset endpoints when true
  debug_mode: boolean
  // Variant parent mode for the Bulk Import Wizard (Spoolman → FDB direction)
  variant_parent_mode: VariantParentMode
  // Container parent marker appended to generic-container names (default "(Master)", empty = no suffix)
  container_parent_marker: string
  // API token — value shown in Settings UI; null = not yet generated
  api_token: string | null
  api_token_enabled: boolean
  // Required settings that must be configured before the bridge is usable
  required_settings_unset: string[]
}

export interface ConfigUpdateRequest {
  sync_weight_threshold_grams?: number | null
  weight_precision_decimals?: number | null
  variant_line_keywords?: string | null
  opentag_vendor_aliases?: string | null
  opentag_color_keywords?: string | null
  weight_sync_direction?: SyncDirection2 | null
  weight_conflict_policy?: ConflictPolicy | null
  material_properties_sync_direction?: SyncDirection2 | null
  material_properties_conflict_policy?: Exclude<ConflictPolicy, 'newest_wins'> | null
  new_spool_sync_direction?: SyncDirection2 | null
  // Scheduler settings
  sync_interval_seconds?: number | null
  sync_log_retention_days?: number | null
  // Import behaviour
  never_import_empties?: boolean | null
  // Debug mode
  debug_mode?: boolean | null
  // Variant parent mode
  variant_parent_mode?: VariantParentMode | null
  // Container parent marker (empty string = no suffix)
  container_parent_marker?: string | null
  // API token enable/disable (value is managed via /auth/api-token/regenerate)
  api_token_enabled?: boolean | null
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
  /** True when the Spoolman filament has a non-empty openprinttag_uuid extra field. */
  openprinttag?: boolean
  /** True when this FDB ref is a synthetic container parent (bridge-owned, no SM counterpart). */
  is_master_container?: boolean
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
  /** True when this collision is on a synthetic container parent name. */
  is_container_collision?: boolean
  /** The cluster key string for this container collision. */
  cluster_key?: string | null
  /** The proposed container name before any user override. */
  proposed_name?: string | null
}

export interface ContainerNameOverride {
  cluster_key: string
  name_override: string | null
  skip: boolean
}

export interface ContainerNameOverridesRequest {
  overrides: ContainerNameOverride[]
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
  container_name_overrides: ContainerNameOverride[]
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

export interface SyncLogDeleteResponse {
  deleted: number
}

// ---------------------------------------------------------------------------
// OpenTag cleanup tool
// ---------------------------------------------------------------------------

export interface OpenTagDatasetMeta {
  fetched_at: string | null
  count: number
  stale: boolean
}

export interface OpenTagCacheStatus {
  exists: boolean
  fetched_at: string | null
  count: number
  stale: boolean
  max_age_hours: number
  /** Largest record count seen on any prior successful grab (0 if never fetched). */
  last_count: number
}

export interface OpenTagFieldRow {
  field: string
  spoolman_value: unknown
  opentag_value: unknown
  suggested_value: unknown
}

export interface OpenTagCandidate {
  opt_uuid: string | null
  opt_slug: string | null
  opt_brand: string | null
  opt_name: string | null
  opt_color_hex: string | null
  confidence: number
  multicolor_mismatch: boolean
  fields: OpenTagFieldRow[]
}

export interface OpenTagFilamentMatch {
  spoolman_filament_id: number
  spoolman_name: string
  spoolman_vendor: string | null
  spoolman_material: string | null
  spoolman_color_hex: string | null
  opt_uuid: string | null
  opt_slug: string | null
  opt_brand: string | null
  opt_name: string | null
  confidence: number
  fields: OpenTagFieldRow[]
  alternates: Record<string, unknown>[]
  candidates: OpenTagCandidate[]
  ignored?: boolean
  multicolor_mismatch?: boolean
  no_match_reason?: string | null
}

export interface OpenTagMatchesResponse {
  dataset: OpenTagDatasetMeta
  matches: OpenTagFilamentMatch[]
}

export interface OpenTagFieldDecision {
  field: string
  value: unknown
  keep_mine: boolean
}

export interface OpenTagFilamentDecision {
  spoolman_filament_id: number
  ignored: boolean
  fields: OpenTagFieldDecision[]
  fdb_filament_id?: string | null
  openprinttag_slug?: string | null
  openprinttag_uuid?: string | null
}

export interface OpenTagApplyRequest {
  decisions: OpenTagFilamentDecision[]
}

export interface OpenTagApplyFilamentResult {
  spoolman_filament_id: number
  status: 'ok' | 'ignored' | 'error'
  error: string | null
  fields_written: string[]
  fdb_settings_updated: boolean
}

export interface OpenTagApplyResponse {
  applied: number
  ignored: number
  errors: number
  results: OpenTagApplyFilamentResult[]
}

// ---------------------------------------------------------------------------
// Debug reset tools
// ---------------------------------------------------------------------------

export interface ClearRefsResponse {
  cleared: number
  failed: number
}

export interface ResetStateResponse {
  filament_mappings: number
  spool_mappings: number
  snapshots: number
  conflicts: number
  sync_log: number
  wizard_completed_reset: boolean
}

// ---------------------------------------------------------------------------
// Version / update check
// ---------------------------------------------------------------------------

export interface VersionInfo {
  current: string
  latest: string | null
  update_available: boolean
  release_url: string | null
  release_name: string | null
  release_notes: string | null
  channel: string
  commit: string | null
  build: string
  is_dev: boolean
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

export interface AuthStatusResponse {
  auth_enabled: boolean
  password_set: boolean
  authenticated: boolean
  api_token_enabled: boolean
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
