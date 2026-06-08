import { useState } from 'react'
import { Link } from 'react-router-dom'
import { getMappings } from '../api/client'
import { useApi } from '../api/hooks'
import { StatusBadge } from '../components/StatusBadge'
import { DeepLinks } from '../components/DeepLinks'
import { ColorDisplay } from '../components/ColorDisplay'
import type { MappingRow, MappingStatus } from '../api/types'
import { formatLocal } from '../utils/datetime'

const STATUS_OPTIONS: Array<{ value: MappingStatus | ''; label: string }> = [
  { value: '', label: 'All' },
  { value: 'in_sync', label: 'In Sync' },
  { value: 'pending', label: 'Pending' },
  { value: 'conflict', label: 'Conflict' },
  { value: 'unlinked', label: 'Unlinked' },
]

// Empty-state messages per filter
const EMPTY_MESSAGES: Record<string, string> = {
  unlinked: 'No unlinked records',
  conflict: 'No conflict records',
  pending: 'No pending records',
  in_sync: 'No in-sync records',
  '': 'No records',
}

function fmtWeight(w: number | null, suffix: string) {
  if (w == null) return '—'
  return `${w.toFixed(1)} g ${suffix}`
}

export default function SyncedRecords() {
  const { data, loading, error } = useApi(getMappings)
  const [statusFilter, setStatusFilter] = useState<MappingStatus | ''>('')
  const [search, setSearch] = useState('')
  const [hideEmpty, setHideEmpty] = useState(false)

  let rows: MappingRow[] = data ?? []
  if (statusFilter) rows = rows.filter(r => r.status === statusFilter)
  if (hideEmpty) rows = rows.filter(r => !r.is_empty)
  if (search.trim()) {
    const q = search.toLowerCase()
    rows = rows.filter(r =>
      r.name?.toLowerCase().includes(q) ||
      r.vendor?.toLowerCase().includes(q) ||
      r.color?.toLowerCase().includes(q)
    )
  }

  const emptyMessage = EMPTY_MESSAGES[statusFilter] ?? 'No records'

  return (
    <div className="p-8 space-y-4">
      <h1 className="text-2xl font-bold text-gray-900">Synced Records</h1>

      <div className="flex gap-3 flex-wrap items-center">
        <input
          type="text"
          placeholder="Search name / vendor / color…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="border border-gray-300 rounded px-3 py-1.5 text-sm w-64 focus:outline-none focus:ring-2 focus:ring-indigo-400"
        />
        <div className="flex gap-1">
          {STATUS_OPTIONS.map(opt => (
            <button
              key={opt.value}
              onClick={() => setStatusFilter(opt.value as MappingStatus | '')}
              className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
                statusFilter === opt.value
                  ? 'bg-indigo-600 text-white'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer select-none ml-2">
          <input
            type="checkbox"
            checked={hideEmpty}
            onChange={e => setHideEmpty(e.target.checked)}
            className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-400"
          />
          Hide empty spools
        </label>
      </div>

      {loading && <p className="text-gray-500">Loading…</p>}
      {error && <p className="text-red-600">{error}</p>}

      {!loading && !error && (
        <div className="overflow-x-auto bg-white rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50">
              <tr>
                {['Name', 'Vendor', 'Color', 'SM weight', 'FDB weight', 'Status', 'Last synced', 'Links'].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {rows.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-6 text-center text-gray-400">{emptyMessage}</td>
                </tr>
              )}
              {rows.map(row => (
                <tr key={row.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-900">{row.name ?? '—'}</td>
                  <td className="px-4 py-3 text-gray-600">{row.vendor ?? '—'}</td>
                  <td className="px-4 py-3">
                    <ColorDisplay
                      colorHex={row.color}
                      multiColorHexes={row.multi_color_hexes}
                      multiColorDirection={row.multi_color_direction}
                      showLabel
                    />
                  </td>
                  <td className="px-4 py-3 text-gray-600">{fmtWeight(row.spoolman_weight, '(net)')}</td>
                  <td className="px-4 py-3 text-gray-600">{fmtWeight(row.filamentdb_weight, '(gross)')}</td>
                  <td className="px-4 py-3">
                    {row.status === 'conflict' ? (
                      <Link
                        to={row.conflict_id != null ? `/conflicts#conflict-${row.conflict_id}` : '/conflicts'}
                        className="hover:opacity-75"
                        title="View conflict"
                      >
                        <StatusBadge status={row.status} />
                      </Link>
                    ) : (
                      <StatusBadge status={row.status} />
                    )}
                  </td>
                  <td className="px-4 py-3 text-gray-500">{formatLocal(row.last_synced)}</td>
                  <td className="px-4 py-3">
                    <DeepLinks
                      filamentdbFilamentId={row.filamentdb_filament_id}
                      spoolmanSpoolId={row.spoolman_spool_id}
                      spoolmanFilamentId={row.spoolman_filament_id}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
