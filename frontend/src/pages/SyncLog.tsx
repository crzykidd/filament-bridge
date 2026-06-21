import { useState } from 'react'
import { clearSyncLog, getSyncLog } from '../api/client'
import type { SyncLogEntry } from '../api/types'
import { useApi } from '../api/hooks'
import { DeepLinks } from '../components/DeepLinks'
import { formatLocal } from '../utils/datetime'

const PAGE_SIZE = 50

type WindowMode = 'all' | 'last10' | 'last25'

function windowsParam(mode: WindowMode): number | undefined {
  if (mode === 'last10') return 10
  if (mode === 'last25') return 25
  return undefined
}

/** Group entries by cycle_id (null cycle_id gets its own bucket keyed as ''). */
function groupByCycle(items: SyncLogEntry[]): { cycleId: string | null; entries: SyncLogEntry[] }[] {
  const order: (string | null)[] = []
  const map = new Map<string, SyncLogEntry[]>()
  for (const entry of items) {
    const key = entry.cycle_id ?? ''
    if (!map.has(key)) {
      order.push(entry.cycle_id ?? null)
      map.set(key, [])
    }
    map.get(key)!.push(entry)
  }
  return order.map(cycleId => ({ cycleId, entries: map.get(cycleId ?? '')! }))
}

export default function SyncLog() {
  const [offset, setOffset] = useState(0)
  const [entityType, setEntityType] = useState('')
  const [direction, setDirection] = useState('')
  const [action, setAction] = useState('')
  const [windowMode, setWindowMode] = useState<WindowMode>('all')
  const [clearing, setClearing] = useState(false)

  const windows = windowsParam(windowMode)

  const { data, loading, error, reload } = useApi(
    () => getSyncLog({
      entity_type: entityType,
      direction,
      action,
      limit: windowMode === 'all' ? PAGE_SIZE : undefined,
      offset: windowMode === 'all' ? offset : undefined,
      windows,
    }),
    [offset, entityType, direction, action, windowMode],
  )

  const items = data?.items ?? []
  const total = data?.total ?? 0

  function reset() { setOffset(0) }

  function handleWindowMode(mode: WindowMode) {
    setWindowMode(mode)
    reset()
  }

  async function handleClear() {
    if (!window.confirm('Clear all sync log entries? This cannot be undone.')) return
    setClearing(true)
    try {
      await clearSyncLog()
      reload()
    } finally {
      setClearing(false)
    }
  }

  const groups = windowMode !== 'all' ? groupByCycle(items) : null

  return (
    <div className="p-8 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Sync Log</h1>
        <button
          onClick={handleClear}
          disabled={clearing || total === 0}
          className="px-3 py-1.5 rounded text-sm bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400 border border-red-200 dark:border-red-800 hover:bg-red-100 dark:hover:bg-red-900/40 disabled:opacity-40"
        >
          {clearing ? 'Clearing…' : 'Clear log'}
        </button>
      </div>

      <div className="flex gap-3 flex-wrap text-sm items-center">
        {/* View selector */}
        <div className="flex rounded border border-gray-300 dark:border-gray-600 overflow-hidden text-xs">
          {(['all', 'last10', 'last25'] as WindowMode[]).map(mode => (
            <button
              key={mode}
              onClick={() => handleWindowMode(mode)}
              className={`px-3 py-1.5 ${
                windowMode === mode
                  ? 'bg-indigo-600 text-white'
                  : 'bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700'
              }`}
            >
              {mode === 'all' ? 'All' : mode === 'last10' ? 'Last 10 windows' : 'Last 25 windows'}
            </button>
          ))}
        </div>

        <select
          value={entityType}
          onChange={e => { setEntityType(e.target.value); reset() }}
          className="border border-gray-300 dark:border-gray-600 rounded px-2 py-1.5 text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-400"
        >
          <option value="">All types</option>
          <option value="spool">Spool</option>
          <option value="filament">Filament</option>
        </select>
        <select
          value={direction}
          onChange={e => { setDirection(e.target.value); reset() }}
          className="border border-gray-300 dark:border-gray-600 rounded px-2 py-1.5 text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-400"
        >
          <option value="">All directions</option>
          <option value="spoolman_to_filamentdb">Spoolman → FDB</option>
          <option value="filamentdb_to_spoolman">FDB → Spoolman</option>
        </select>
        <select
          value={action}
          onChange={e => { setAction(e.target.value); reset() }}
          className="border border-gray-300 dark:border-gray-600 rounded px-2 py-1.5 text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-400"
        >
          <option value="">All actions</option>
          <option value="create">Create</option>
          <option value="update">Update</option>
          <option value="skip">Skip</option>
          <option value="conflict">Conflict</option>
          <option value="error">Error</option>
        </select>
      </div>

      {loading && <p className="text-gray-500 dark:text-gray-400">Loading…</p>}
      {error && <p className="text-red-600 dark:text-red-400">{error}</p>}

      {!loading && !error && (
        <>
          <div className="overflow-x-auto bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
            <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700 text-sm">
              <thead className="bg-gray-50 dark:bg-gray-750">
                <tr>
                  {['Time', 'Direction', 'Action', 'Type', 'Record', 'Field', 'Old → New', 'Links'].map(h => (
                    <th key={h} className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                {items.length === 0 && (
                  <tr>
                    <td colSpan={8} className="px-4 py-6 text-center text-gray-400 dark:text-gray-500">No log entries</td>
                  </tr>
                )}

                {/* Window mode: render cycle group headers + entries */}
                {groups !== null && groups.map(({ cycleId, entries }) => (
                  <>
                    <tr key={`hdr-${cycleId ?? 'manual'}`} className="bg-indigo-50 dark:bg-indigo-900/20">
                      <td colSpan={8} className="px-4 py-1.5 text-xs font-semibold text-indigo-700 dark:text-indigo-300">
                        {cycleId
                          ? <>Sync window <span className="font-mono">{cycleId.slice(0, 8)}</span> — {formatLocal(entries[0].timestamp)} — {entries.length} {entries.length === 1 ? 'entry' : 'entries'}</>
                          : <>Manual / wizard — {entries.length} {entries.length === 1 ? 'entry' : 'entries'}</>
                        }
                      </td>
                    </tr>
                    {entries.map(entry => <EntryRow key={entry.id} entry={entry} />)}
                  </>
                ))}

                {/* All mode: flat list */}
                {groups === null && items.map(entry => <EntryRow key={entry.id} entry={entry} />)}
              </tbody>
            </table>
          </div>

          {windowMode === 'all' && (
            <div className="flex items-center justify-between text-sm text-gray-500 dark:text-gray-400">
              <span>
                {total === 0 ? '0 entries' : `${offset + 1}–${Math.min(offset + PAGE_SIZE, total)} of ${total}`}
              </span>
              <div className="flex gap-2">
                <button
                  onClick={() => setOffset(o => Math.max(0, o - PAGE_SIZE))}
                  disabled={offset === 0}
                  className="px-3 py-1 rounded bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-700 dark:text-gray-300 disabled:opacity-40"
                >
                  ← Prev
                </button>
                <button
                  onClick={() => setOffset(o => o + PAGE_SIZE)}
                  disabled={offset + PAGE_SIZE >= total}
                  className="px-3 py-1 rounded bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-700 dark:text-gray-300 disabled:opacity-40"
                >
                  Next →
                </button>
              </div>
            </div>
          )}

          {windowMode !== 'all' && (
            <p className="text-sm text-gray-500 dark:text-gray-400">
              {total === 0 ? '0 entries' : `${total} ${total === 1 ? 'entry' : 'entries'} across ${groups?.length ?? 0} ${(groups?.length ?? 0) === 1 ? 'window' : 'windows'}`}
            </p>
          )}
        </>
      )}
    </div>
  )
}

function EntryRow({ entry }: { entry: SyncLogEntry }) {
  return (
    <tr className={`hover:bg-gray-50 dark:hover:bg-gray-750 ${entry.action === 'error' ? 'bg-red-50 dark:bg-red-900/20' : ''}`}>
      <td className="px-4 py-2 text-gray-500 dark:text-gray-400 whitespace-nowrap text-xs">
        {formatLocal(entry.timestamp)}
      </td>
      <td className="px-4 py-2 text-gray-600 dark:text-gray-300 text-xs whitespace-nowrap">
        {entry.direction === 'spoolman_to_filamentdb' ? 'SM → FDB' : 'FDB → SM'}
      </td>
      <td className="px-4 py-2">
        <span className={`inline-flex px-1.5 py-0.5 rounded text-xs font-medium ${
          entry.action === 'error' ? 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400'
          : entry.action === 'conflict' ? 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400'
          : entry.action === 'create' ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400'
          : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300'
        }`}>
          {entry.action}
        </span>
      </td>
      <td className="px-4 py-2 text-gray-600 dark:text-gray-300 text-xs">{entry.entity_type}</td>
      <td className="px-4 py-2 text-xs">
        {entry.label
          ? <span className="text-gray-800 dark:text-gray-100">{entry.label}</span>
          : <span className="text-gray-400 dark:text-gray-500">—</span>}
        {entry.spoolman_id != null && (
          <span className="text-gray-400 dark:text-gray-500 ml-1.5 font-mono">SM #{entry.spoolman_id}</span>
        )}
      </td>
      <td className="px-4 py-2 text-gray-600 dark:text-gray-300 text-xs font-mono">{entry.field_name ?? '—'}</td>
      <td className="px-4 py-2 text-xs font-mono text-gray-500 dark:text-gray-400">
        {entry.error_message
          ? <span className="text-red-600 dark:text-red-400">{entry.error_message}</span>
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
  )
}
