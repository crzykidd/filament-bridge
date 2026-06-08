import { useState } from 'react'
import { getSyncLog } from '../api/client'
import { useApi } from '../api/hooks'
import { DeepLinks } from '../components/DeepLinks'
import { formatLocal } from '../utils/datetime'

const PAGE_SIZE = 50

export default function SyncLog() {
  const [offset, setOffset] = useState(0)
  const [entityType, setEntityType] = useState('')
  const [direction, setDirection] = useState('')
  const [action, setAction] = useState('')

  const { data, loading, error } = useApi(
    () => getSyncLog({ entity_type: entityType, direction, action, limit: PAGE_SIZE, offset }),
    [offset, entityType, direction, action],
  )

  const items = data?.items ?? []
  const total = data?.total ?? 0

  function reset() { setOffset(0) }

  return (
    <div className="p-8 space-y-4">
      <h1 className="text-2xl font-bold text-gray-900">Sync Log</h1>

      <div className="flex gap-3 flex-wrap text-sm">
        <select
          value={entityType}
          onChange={e => { setEntityType(e.target.value); reset() }}
          className="border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
        >
          <option value="">All types</option>
          <option value="spool">Spool</option>
          <option value="filament">Filament</option>
        </select>
        <select
          value={direction}
          onChange={e => { setDirection(e.target.value); reset() }}
          className="border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
        >
          <option value="">All directions</option>
          <option value="spoolman_to_filamentdb">Spoolman → FDB</option>
          <option value="filamentdb_to_spoolman">FDB → Spoolman</option>
        </select>
        <select
          value={action}
          onChange={e => { setAction(e.target.value); reset() }}
          className="border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
        >
          <option value="">All actions</option>
          <option value="create">Create</option>
          <option value="update">Update</option>
          <option value="skip">Skip</option>
          <option value="conflict">Conflict</option>
          <option value="error">Error</option>
        </select>
      </div>

      {loading && <p className="text-gray-500">Loading…</p>}
      {error && <p className="text-red-600">{error}</p>}

      {!loading && !error && (
        <>
          <div className="overflow-x-auto bg-white rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  {['Time', 'Direction', 'Action', 'Type', 'Field', 'Old → New', 'Links'].map(h => (
                    <th key={h} className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {items.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-4 py-6 text-center text-gray-400">No log entries</td>
                  </tr>
                )}
                {items.map(entry => (
                  <tr key={entry.id} className={`hover:bg-gray-50 ${entry.action === 'error' ? 'bg-red-50' : ''}`}>
                    <td className="px-4 py-2 text-gray-500 whitespace-nowrap text-xs">
                      {formatLocal(entry.timestamp)}
                    </td>
                    <td className="px-4 py-2 text-gray-600 text-xs whitespace-nowrap">
                      {entry.direction === 'spoolman_to_filamentdb' ? 'SM → FDB' : 'FDB → SM'}
                    </td>
                    <td className="px-4 py-2">
                      <span className={`inline-flex px-1.5 py-0.5 rounded text-xs font-medium ${
                        entry.action === 'error' ? 'bg-red-100 text-red-700'
                        : entry.action === 'conflict' ? 'bg-yellow-100 text-yellow-700'
                        : entry.action === 'create' ? 'bg-green-100 text-green-700'
                        : 'bg-gray-100 text-gray-600'
                      }`}>
                        {entry.action}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-gray-600 text-xs">{entry.entity_type}</td>
                    <td className="px-4 py-2 text-gray-600 text-xs font-mono">{entry.field_name ?? '—'}</td>
                    <td className="px-4 py-2 text-xs font-mono text-gray-500">
                      {entry.error_message
                        ? <span className="text-red-600">{entry.error_message}</span>
                        : entry.old_value != null || entry.new_value != null
                          ? <span>{String(entry.old_value ?? '—')} → {String(entry.new_value ?? '—')}</span>
                          : '—'}
                    </td>
                    <td className="px-4 py-2">
                      <DeepLinks
                        filamentdbFilamentId={entry.filamentdb_filament_id}
                        spoolmanSpoolId={entry.spoolman_id}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between text-sm text-gray-500">
            <span>
              {total === 0 ? '0 entries' : `${offset + 1}–${Math.min(offset + PAGE_SIZE, total)} of ${total}`}
            </span>
            <div className="flex gap-2">
              <button
                onClick={() => setOffset(o => Math.max(0, o - PAGE_SIZE))}
                disabled={offset === 0}
                className="px-3 py-1 rounded bg-gray-100 hover:bg-gray-200 disabled:opacity-40"
              >
                ← Prev
              </button>
              <button
                onClick={() => setOffset(o => o + PAGE_SIZE)}
                disabled={offset + PAGE_SIZE >= total}
                className="px-3 py-1 rounded bg-gray-100 hover:bg-gray-200 disabled:opacity-40"
              >
                Next →
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
