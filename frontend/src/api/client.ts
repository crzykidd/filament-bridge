import type {
  AutoSyncRequest,
  AutoSyncResponse,
  BackupExport,
  BackupImportResponse,
  BulkResolveRequest,
  BulkResolveResponse,
  ConfigResponse,
  ConfigUpdateRequest,
  ConflictResolveRequest,
  ConflictResponse,
  CycleResultResponse,
  HealthResponse,
  MappingRow,
  MappingUpdateRequest,
  SyncLogResponse,
  SyncStatusResponse,
  WizardConnectivityResponse,
  WizardDecisionAck,
  WizardDirectionRequest,
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  })
  if (!res.ok) {
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

// ---------------------------------------------------------------------------
// Mappings
// ---------------------------------------------------------------------------

export const getMappings = () => request<MappingRow[]>('/mappings')
export const updateMapping = (id: number, body: MappingUpdateRequest) =>
  json<MappingRow>(`/mappings/${id}`, 'PUT', body)
export const deleteMapping = (id: number) =>
  request<void>(`/mappings/${id}`, { method: 'DELETE' })

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
}

export const getSyncLog = (params: SyncLogParams = {}) => {
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '') qs.set(k, String(v))
  }
  const q = qs.toString()
  return request<SyncLogResponse>(`/sync-log${q ? `?${q}` : ''}`)
}

// ---------------------------------------------------------------------------
// Backup
// ---------------------------------------------------------------------------

export const exportBackup = () => request<BackupExport>('/backup/export')
export const importBackup = (body: BackupExport) =>
  json<BackupImportResponse>('/backup/import', 'POST', body)

// ---------------------------------------------------------------------------
// Wizard
// ---------------------------------------------------------------------------

export const getWizardConnectivity = () =>
  request<WizardConnectivityResponse>('/wizard/connectivity')

export const postWizardDirection = (body: WizardDirectionRequest) =>
  json<WizardDecisionAck>('/wizard/direction', 'POST', body)

export const getWizardMatches = () => request<WizardMatchesResponse>('/wizard/matches')
export const postWizardMatches = (body: WizardMatchesRequest) =>
  json<WizardDecisionAck>('/wizard/matches', 'POST', body)

export const getWizardWeights = () => request<WizardWeightsResponse>('/wizard/weights')

export const getWizardVariants = () => request<WizardVariantsResponse>('/wizard/variants')
export const postWizardVariants = (body: WizardVariantsRequest) =>
  json<WizardDecisionAck>('/wizard/variants', 'POST', body)

export const getWizardPreview = () => request<WizardPreviewResponse>('/wizard/preview')

export const postWizardExecute = (body: WizardExecuteRequest) =>
  json<WizardExecuteResponse>('/wizard/execute', 'POST', body)
