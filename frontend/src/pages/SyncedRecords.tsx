import { Fragment, useState } from 'react'
import { Link } from 'react-router-dom'
import { getMappings } from '../api/client'
import { useApi } from '../api/hooks'
import { StatusBadge } from '../components/StatusBadge'
import { DeepLinks } from '../components/DeepLinks'
import { ColorDisplay } from '../components/ColorDisplay'
import type { MappingDetailField, MappingRow, MappingStatus } from '../api/types'
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

function fmtDetailValue(v: string | number | null): string {
  if (v === null || v === undefined || v === '') return '—'
  return String(v)
}

/** Expanded detail: per-field Spoolman (emerald) vs Filament DB (blue), small + neat. */
function DetailGrid({ detail }: { detail: MappingDetailField[] }) {
  if (!detail || detail.length === 0) {
    return <p className="text-xs text-gray-400 dark:text-gray-500 italic">No detail available.</p>
  }
  return (
    <div className="grid grid-cols-[10rem_1fr_1fr] gap-x-4 gap-y-1 text-xs max-w-2xl">
      <div className="font-medium text-gray-400 dark:text-gray-500 uppercase tracking-wide">Field</div>
      <div className="font-medium text-emerald-700 dark:text-emerald-400">Spoolman</div>
      <div className="font-medium text-blue-700 dark:text-blue-400">Filament DB</div>
      {detail.map(d => (
        <Fragment key={d.field}>
          <div className="text-gray-600 dark:text-gray-300">{d.label}</div>
          <div className="font-mono text-gray-800 dark:text-gray-200">{fmtDetailValue(d.spoolman)}</div>
          <div className="font-mono text-gray-800 dark:text-gray-200">{fmtDetailValue(d.filamentdb)}</div>
        </Fragment>
      ))}
    </div>
  )
}

export default function SyncedRecords() {
  const { data, loading, error } = useApi(getMappings)
  const [statusFilter, setStatusFilter] = useState<MappingStatus | ''>('')
  const [search, setSearch] = useState('')
  const [hideEmpty, setHideEmpty] = useState(false)
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set())

  const toggleExpand = (id: number) =>
    setExpandedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

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
      <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Synced Records</h1>

      <div className="flex gap-3 flex-wrap items-center">
        <input
          type="text"
          placeholder="Search name / vendor / color…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="border border-gray-300 dark:border-gray-600 rounded px-3 py-1.5 text-sm w-64 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder:text-gray-400 dark:placeholder:text-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-400"
        />
        <div className="flex gap-1">
          {STATUS_OPTIONS.map(opt => (
            <button
              key={opt.value}
              onClick={() => setStatusFilter(opt.value as MappingStatus | '')}
              className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
                statusFilter === opt.value
                  ? 'bg-indigo-600 text-white'
                  : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-300 cursor-pointer select-none ml-2">
          <input
            type="checkbox"
            checked={hideEmpty}
            onChange={e => setHideEmpty(e.target.checked)}
            className="rounded border-gray-300 dark:border-gray-600 text-indigo-600 focus:ring-indigo-400"
          />
          Hide empty spools
        </label>
      </div>

      {loading && <p className="text-gray-500 dark:text-gray-400">Loading…</p>}
      {error && <p className="text-red-600 dark:text-red-400">{error}</p>}

      {!loading && !error && (
        <>
          {rows.length > 1 && (
            <div className="flex items-center gap-2 text-xs">
              <button onClick={() => setExpandedIds(new Set(rows.map(r => r.id)))}
                className="text-indigo-600 dark:text-indigo-400 hover:text-indigo-800 dark:hover:text-indigo-300">Expand all</button>
              <span className="text-gray-300 dark:text-gray-600">|</span>
              <button onClick={() => setExpandedIds(new Set())}
                className="text-indigo-600 dark:text-indigo-400 hover:text-indigo-800 dark:hover:text-indigo-300">Collapse all</button>
            </div>
          )}
          <div className="overflow-x-auto bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
            <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700 text-sm">
              <thead className="bg-gray-50 dark:bg-gray-750">
                <tr>
                  <th className="w-8 px-2 py-3" />
                  {['Name', 'Vendor', 'Color', 'SM weight', 'FDB weight', 'Status', 'Last synced', 'Links'].map(h => (
                    <th key={h} className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={9} className="px-4 py-6 text-center text-gray-400 dark:text-gray-500">{emptyMessage}</td>
                  </tr>
                )}
                {rows.map(row => {
                  const expanded = expandedIds.has(row.id)
                  return (
                    <Fragment key={row.id}>
                      <tr
                        className="hover:bg-gray-50 dark:hover:bg-gray-750 cursor-pointer select-none"
                        onClick={() => toggleExpand(row.id)}
                      >
                        <td className="w-8 px-2 py-3 text-center">
                          <span className={`inline-block text-gray-400 dark:text-gray-500 transition-transform ${expanded ? 'rotate-180' : ''}`}>▾</span>
                        </td>
                        <td className="px-4 py-3 font-medium text-gray-900 dark:text-gray-100">{row.name ?? '—'}</td>
                        <td className="px-4 py-3 text-gray-600 dark:text-gray-300">{row.vendor ?? '—'}</td>
                        <td className="px-4 py-3">
                          <ColorDisplay
                            colorHex={row.color}
                            multiColorHexes={row.multi_color_hexes}
                            multiColorDirection={row.multi_color_direction}
                            showLabel
                          />
                        </td>
                        <td className="px-4 py-3 text-gray-600 dark:text-gray-300">{fmtWeight(row.spoolman_weight, '(net)')}</td>
                        <td className="px-4 py-3 text-gray-600 dark:text-gray-300">{fmtWeight(row.filamentdb_weight, '(gross)')}</td>
                        <td className="px-4 py-3" onClick={e => e.stopPropagation()}>
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
                        <td className="px-4 py-3 text-gray-500 dark:text-gray-400">{formatLocal(row.last_synced)}</td>
                        <td className="px-4 py-3" onClick={e => e.stopPropagation()}>
                          <DeepLinks
                            filamentdbFilamentId={row.filamentdb_filament_id}
                            spoolmanSpoolId={row.spoolman_spool_id}
                            spoolmanFilamentId={row.spoolman_filament_id}
                          />
                        </td>
                      </tr>
                      {expanded && (
                        <tr className="bg-gray-50/60 dark:bg-gray-900/30">
                          <td colSpan={9} className="px-6 py-3 border-t border-gray-100 dark:border-gray-700">
                            <DetailGrid detail={row.detail} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
