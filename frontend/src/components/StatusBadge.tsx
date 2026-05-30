import type { MappingStatus } from '../api/types'

const MAPPING_STYLES: Record<MappingStatus, string> = {
  in_sync: 'bg-green-100 text-green-800',
  pending: 'bg-yellow-100 text-yellow-800',
  conflict: 'bg-red-100 text-red-800',
  unlinked: 'bg-gray-100 text-gray-600',
}

const MAPPING_LABELS: Record<MappingStatus, string> = {
  in_sync: 'In Sync',
  pending: 'Pending',
  conflict: 'Conflict',
  unlinked: 'Unlinked',
}

export function StatusBadge({ status }: { status: MappingStatus }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${MAPPING_STYLES[status]}`}>
      {MAPPING_LABELS[status]}
    </span>
  )
}

type SystemStatus = 'ok' | 'degraded' | 'error'

const SYSTEM_STYLES: Record<SystemStatus, string> = {
  ok: 'bg-green-100 text-green-800',
  degraded: 'bg-yellow-100 text-yellow-800',
  error: 'bg-red-100 text-red-800',
}

export function SystemStatusBadge({ status }: { status: SystemStatus }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${SYSTEM_STYLES[status]}`}>
      {status}
    </span>
  )
}
