import type {
  AuthStatusResponse,
  VersionInfo,
  AutoSyncRequest,
  AutoSyncResponse,
  BackupExport,
  BackupFilamentDbResponse,
  BackupImportResponse,
  BackupSpoolmanResponse,
  BulkResolveRequest,
  BulkResolveResponse,
  ClearRefsResponse,
  ConfigResponse,
  ConfigUpdateRequest,
  ConflictImportRequest,
  ConflictResolveRequest,
  ConflictResponse,
  CycleResultResponse,
  DivergenceContextResponse,
  FilamentSuggestionsResponse,
  FullResetResponse,
  HealthResponse,
  MappingRow,
  MappingUpdateRequest,
  MobileSpoolDetail,
  MobileSpoolUpdateRequest,
  OpenTagApplyRequest,
  OpenTagApplyResponse,
  OpenTagCacheStatus,
  OpenTagClearResponse,
  OpenTagCompletenessResponse,
  OpenTagDatasetMeta,
  OpenTagIgnoreResponse,
  OpenTagMatchesResponse,
  OpenTagSearchResponse,
  ReconcileResponse,
  ResetStateResponse,
  SMVariancesDecisionsRequest,
  SyncLogDeleteResponse,
  SyncLogResponse,
  SyncStatusResponse,
  VariancesResponse,
  ContainerNameOverridesRequest,
  WizardConnectivityResponse,
  WizardDecisionAck,
  WizardDirectionRequest,
  WizardDirectionResponse,
  WizardExecuteRequest,
  WizardExecuteResponse,
  WizardMatchesRequest,
  WizardMatchesResponse,
  WizardPreviewResponse,
  WizardVariantsRequest,
  WizardWeightsResponse,
  WizardVariantsResponse,
} from './types'

export class BridgeApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message)
    this.name = 'BridgeApiError'
  }
}

// Callback that App.tsx registers so the client can signal a 401 to the auth gate.
// Kept as a simple module-level variable to avoid React import cycles.
let _on401: (() => void) | null = null
export function register401Handler(cb: () => void): void {
  _on401 = cb
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    // credentials:'include' is required for the httpOnly fb_session cookie to be sent
    credentials: 'include',
    ...init,
  })
  if (!res.ok) {
    // On 401, fire the handler so the auth gate re-checks status and shows login.
    // Skip the callback for auth endpoints themselves to avoid redirect loops.
    if (res.status === 401 && !path.startsWith('/auth/')) {
      _on401?.()
    }
    let code = 'unknown_error'
    let message = `HTTP ${res.status}`
    try {
      const body = await res.json()
      if (body?.detail && typeof body.detail === 'object') {
        code = body.detail.code ?? code
        message = body.detail.message ?? message
      } else if (typeof body?.detail === 'string') {
        message = body.detail
      }
    } catch {
      // ignore parse error
    }
    throw new BridgeApiError(res.status, code, message)
  }
  if (res.status === 204) return undefined as unknown as T
  return res.json() as Promise<T>
}

function json<T>(path: string, method: string, body: unknown): Promise<T> {
  return request<T>(path, { method, body: JSON.stringify(body) })
}

// ---------------------------------------------------------------------------
// Version / update check
// ---------------------------------------------------------------------------

export const getVersionInfo = () => request<VersionInfo>('/version')

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

export const getHealth = () => request<HealthResponse>('/health')

// ---------------------------------------------------------------------------
// Sync
// ---------------------------------------------------------------------------

export const getSyncStatus = () => request<SyncStatusResponse>('/sync/status')
export const triggerSync = () => request<CycleResultResponse>('/sync/trigger', { method: 'POST' })
export const triggerDryRun = () => request<CycleResultResponse>('/sync/dry-run', { method: 'POST' })
export const setAutoSync = (body: AutoSyncRequest) => json<AutoSyncResponse>('/sync/auto', 'POST', body)

// ---------------------------------------------------------------------------
// Conflicts
// ---------------------------------------------------------------------------

export const getConflicts = (status: 'open' | 'resolved' = 'open') =>
  request<ConflictResponse[]>(`/conflicts?status=${status}`)

export const resolveConflict = (id: number, body: ConflictResolveRequest) =>
  json<ConflictResponse>(`/conflicts/${id}/resolve`, 'POST', body)

export const bulkResolveConflicts = (body: BulkResolveRequest) =>
  json<BulkResolveResponse>('/conflicts/bulk-resolve', 'POST', body)

export const getDivergenceContext = (conflictId: number) =>
  request<DivergenceContextResponse>(`/conflicts/${conflictId}/divergence-context`)

export const importConflictRecord = (conflictId: number, body: ConflictImportRequest) =>
  json<WizardExecuteResponse>(`/conflicts/${conflictId}/import`, 'POST', body)

export const getFilamentSuggestions = (conflictId: number) =>
  request<FilamentSuggestionsResponse>(`/conflicts/${conflictId}/filament-suggestions`)

// ---------------------------------------------------------------------------
// Mappings
// ---------------------------------------------------------------------------

export const getMappings = () => request<MappingRow[]>('/mappings')
export const updateMapping = (id: number, body: MappingUpdateRequest) =>
  json<MappingRow>(`/mappings/${id}`, 'PUT', body)
export const deleteMapping = (id: number) =>
  request<void>(`/mappings/${id}`, { method: 'DELETE' })

// ---------------------------------------------------------------------------
// Mobile updates (phase 2 — scan/update page + in-nav page)
// ---------------------------------------------------------------------------

export const getMobileSpool = (fil: string, spool: string) =>
  request<MobileSpoolDetail>(`/mobile/spool/${fil}/${spool}`)

export const updateMobileSpool = (fil: string, spool: string, body: MobileSpoolUpdateRequest) =>
  json<MobileSpoolDetail>(`/mobile/spool/${fil}/${spool}`, 'PATCH', body)

export const getMobileLocations = () => request<string[]>('/mobile/locations')

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

export const getConfig = () => request<ConfigResponse>('/config')
export const updateConfig = (body: ConfigUpdateRequest) => json<ConfigResponse>('/config', 'PUT', body)

// ---------------------------------------------------------------------------
// Sync log
// ---------------------------------------------------------------------------

export interface SyncLogParams {
  entity_type?: string
  direction?: string
  action?: string
  limit?: number
  offset?: number
  windows?: number
}

export const getSyncLog = (params: SyncLogParams = {}) => {
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '') qs.set(k, String(v))
  }
  const q = qs.toString()
  return request<SyncLogResponse>(`/sync-log${q ? `?${q}` : ''}`)
}

export const clearSyncLog = () =>
  request<SyncLogDeleteResponse>('/sync-log', { method: 'DELETE' })

// ---------------------------------------------------------------------------
// Backup
// ---------------------------------------------------------------------------

export const exportBackup = () => request<BackupExport>('/backup/export')
export const importBackup = (body: BackupExport) =>
  json<BackupImportResponse>('/backup/import', 'POST', body)
export const backupSpoolman = () =>
  request<BackupSpoolmanResponse>('/backup/spoolman', { method: 'POST' })
export const backupFilamentDb = () =>
  request<BackupFilamentDbResponse>('/backup/filamentdb', { method: 'POST' })

// ---------------------------------------------------------------------------
// Wizard
// ---------------------------------------------------------------------------

export const getWizardConnectivity = () =>
  request<WizardConnectivityResponse>('/wizard/connectivity')

export const getWizardDirection = () =>
  request<WizardDirectionResponse>('/wizard/direction')

export const postWizardDirection = (body: WizardDirectionRequest) =>
  json<WizardDecisionAck>('/wizard/direction', 'POST', body)

export const getWizardMatches = () => request<WizardMatchesResponse>('/wizard/matches')
export const postWizardMatches = (body: WizardMatchesRequest) =>
  json<WizardDecisionAck>('/wizard/matches', 'POST', body)
export const postWizardMatchSkip = (smFilamentId: number) =>
  request<WizardDecisionAck>(`/wizard/matches/${smFilamentId}/skip`, { method: 'POST' })

export const getWizardWeights = () => request<WizardWeightsResponse>('/wizard/weights')

export const getWizardVariants = () => request<WizardVariantsResponse>('/wizard/variants')
export const postWizardVariants = (body: WizardVariantsRequest) =>
  json<WizardDecisionAck>('/wizard/variants', 'POST', body)
export const postWizardSmVariants = (body: SMVariancesDecisionsRequest) =>
  json<WizardDecisionAck>('/wizard/variants/sm', 'POST', body)

export const getWizardVariances = () => request<VariancesResponse>('/wizard/variances')

export const getWizardPreview = () => request<WizardPreviewResponse>('/wizard/preview')

export const postWizardContainerNameOverrides = (body: ContainerNameOverridesRequest) =>
  json<WizardDecisionAck>('/wizard/container-name-overrides', 'POST', body)

export const postWizardExecute = (body: WizardExecuteRequest) =>
  json<WizardExecuteResponse>('/wizard/execute', 'POST', body)

// ---------------------------------------------------------------------------
// OpenTag cleanup tool
// ---------------------------------------------------------------------------

export const getOpenTagStatus = () => request<OpenTagCacheStatus>('/openprinttag/status')
/**
 * Fetch OpenTag matches. Returns the cached result instantly when present; pass
 * `recompute` to force a fresh (server-offloaded) match and re-cache. The optional
 * `signal` lets callers abort the request (e.g. on component unmount).
 */
export const getOpenTagMatches = (recompute = false, signal?: AbortSignal) =>
  request<OpenTagMatchesResponse>(
    `/openprinttag/matches${recompute ? '?recompute=true' : ''}`,
    signal ? { signal } : undefined,
  )
/**
 * Refresh the OpenTag dataset. Default (`pull=false`) runs a cheap upstream
 * commit-SHA check: an unchanged commit only bumps the cache age (`unchanged=true`,
 * no heavy download); a changed/unknown SHA re-downloads. Pass `pull=true` to skip
 * the check and force a full download ("Pull contents anyway").
 */
export const postOpenTagRefresh = (pull = false) =>
  request<OpenTagDatasetMeta>(
    `/openprinttag/refresh${pull ? '?pull=true' : ''}`,
    { method: 'POST' },
  )
export const postOpenTagApply = (body: OpenTagApplyRequest) =>
  json<OpenTagApplyResponse>('/openprinttag/apply', 'POST', body)
/** Clear (unmatch) a filament's OpenTag identity directly — standalone counterpart
 *  to the Apply-flow unmatch. Blanks SM slug/uuid + removes those FDB settings keys. */
export const postOpenTagClear = (filamentId: number) =>
  request<OpenTagClearResponse>(`/openprinttag/clear/${filamentId}`, { method: 'POST' })

export const postOpenTagIgnore = (filamentId: number, ignored: boolean) =>
  request<OpenTagIgnoreResponse>(
    `/openprinttag/ignore/${filamentId}?ignored=${ignored}`,
    { method: 'POST' },
  )
export const getOpenTagSearch = (
  brand: string,
  material: string,
  q: string,
  limit = 20,
) => {
  const params = new URLSearchParams()
  if (brand) params.set('brand', brand)
  if (material) params.set('material', material)
  if (q) params.set('q', q)
  params.set('limit', String(limit))
  return request<OpenTagSearchResponse>(`/openprinttag/search?${params.toString()}`)
}

/** OpenPrintTag completeness report — which matched records are missing data. */
export const getOpenTagMissingValues = () =>
  request<OpenTagCompletenessResponse>('/openprinttag/completeness')

// ---------------------------------------------------------------------------
// Reconcile
// ---------------------------------------------------------------------------

export const getReconcile = () => request<ReconcileResponse>('/reconcile')

// ---------------------------------------------------------------------------
// Debug reset tools (only available when debug_mode=true)
// ---------------------------------------------------------------------------

export const clearSpoolmanFdbRefs = () =>
  request<ClearRefsResponse>('/debug/clear-spoolman-fdb-refs', { method: 'POST' })

export const clearSpoolmanOpentagIds = () =>
  request<ClearRefsResponse>('/debug/clear-spoolman-opentag-ids', { method: 'POST' })

export const resetBridgeState = () =>
  request<ResetStateResponse>('/debug/reset-bridge-state', { method: 'POST' })

export const fullReset = () =>
  request<FullResetResponse>('/debug/full-reset', { method: 'POST' })

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

export const getAuthStatus = () => request<AuthStatusResponse>('/auth/status')

export const authSetup = (password: string) =>
  json<AuthStatusResponse>('/auth/setup', 'POST', { password })

export const authLogin = (password: string) =>
  json<AuthStatusResponse>('/auth/login', 'POST', { password })

export const authLogout = () =>
  request<{ ok: boolean }>('/auth/logout', { method: 'POST' })

export const authChangePassword = (current_password: string, new_password: string) =>
  json<{ ok: boolean }>('/auth/change-password', 'POST', { current_password, new_password })

export const authRegenerateToken = () =>
  request<{ api_token: string }>('/auth/api-token/regenerate', { method: 'POST' })
