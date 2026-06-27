import { Fragment, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getMappings, getVersionInfo } from '../api/client'
import { useApi } from '../api/hooks'
import { StatusBadge } from '../components/StatusBadge'
import { DeepLinks } from '../components/DeepLinks'
import { ColorDisplay } from '../components/ColorDisplay'
import { HelpTip } from '../components/HelpTip'
import { PrintLabelButton } from '../components/PrintLabelButton'
import type { MappingDetailField, MappingRow, MappingStatus } from '../api/types'
import { formatLocal, parseUtc } from '../utils/datetime'

function isFilamentRow(row: MappingRow): boolean {
  return row.kind === 'filament'
}

type SortKey = 'name' | 'vendor' | 'spoolman_weight' | 'filamentdb_weight' | 'last_synced'
type SortDir = 'asc' | 'desc'

// Column header label → sortable row field. Headers absent here are not sortable.
const SORTABLE: Record<string, SortKey> = {
  Name: 'name',
  Vendor: 'vendor',
  'SM weight': 'spoolman_weight',
  'FDB weight': 'filamentdb_weight',
  'Last synced': 'last_synced',
}

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
  const navigate = useNavigate()
  const [statusFilter, setStatusFilter] = useState<MappingStatus | ''>('')
  const [search, setSearch] = useState('')
  const [hideEmpty, setHideEmpty] = useState(false)
  const [sortKey, setSortKey] = useState<SortKey | null>(null)
  const [sortDir, setSortDir] = useState<SortDir>('asc')
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set())
  // The Print-label action only appears when the mobile/labels feature is enabled.
  const [labelsEnabled, setLabelsEnabled] = useState(false)

  useEffect(() => {
    getVersionInfo().then(v => setLabelsEnabled(v.mobile_labels_enabled)).catch(() => {})
  }, [])

  const toggleExpand = (id: number) =>
    setExpandedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  // Click a sortable header: same column toggles asc↔desc; a new column starts ascending.
  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(d => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('asc')
    }
  }

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
  if (sortKey) {
    const dir = sortDir === 'asc' ? 1 : -1
    // Copy before sorting so we never mutate the cached `data` array (rows === data when unfiltered).
    rows = [...rows].sort((a, b) => {
      const av = a[sortKey]
      const bv = b[sortKey]
      // Missing values always sort last, regardless of direction.
      const aEmpty = av === null || av === undefined || av === ''
      const bEmpty = bv === null || bv === undefined || bv === ''
      if (aEmpty && bEmpty) return 0
      if (aEmpty) return 1
      if (bEmpty) return -1
      let cmp: number
      if (sortKey === 'name' || sortKey === 'vendor') {
        cmp = String(av).localeCompare(String(bv), undefined, { sensitivity: 'base' })
      } else if (sortKey === 'last_synced') {
        cmp = parseUtc(String(av)).getTime() - parseUtc(String(bv)).getTime()
      } else {
        cmp = (av as number) - (bv as number)
      }
      return cmp * dir
    })
  }

  const emptyMessage = EMPTY_MESSAGES[statusFilter] ?? 'No records'
  // Base table has 9 columns (chevron + 8 headers); +1 for the Labels action column.
  const colCount = labelsEnabled ? 10 : 9

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
          <HelpTip text="Hides spools with 0 g remaining in Spoolman." />
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
                  {(['Name', 'Vendor', 'Color', 'SM weight', 'FDB weight', 'Status', 'Last synced', 'Links'] as const).map(h => {
                    const sk: SortKey | undefined = SORTABLE[h]
                    const active = sk && sortKey === sk
                    return (
                      <th
                        key={h}
                        onClick={sk ? () => toggleSort(sk) : undefined}
                        aria-sort={active ? (sortDir === 'asc' ? 'ascending' : 'descending') : undefined}
                        className={`px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide ${
                          sk ? 'cursor-pointer select-none hover:text-gray-700 dark:hover:text-gray-200' : ''
                        }`}
                      >
                        {h === 'SM weight' ? (
                          <span className="inline-flex items-center">
                            SM weight
                            <HelpTip text="Net filament weight from Spoolman (reel excluded), as of the last sync." />
                          </span>
                        ) : h === 'FDB weight' ? (
                          <span className="inline-flex items-center">
                            FDB weight
                            <HelpTip text="Gross weight from Filament DB (filament + empty reel), as of the last sync." />
                          </span>
                        ) : h}
                        {active && <span className="ml-1">{sortDir === 'asc' ? '▲' : '▼'}</span>}
                      </th>
                    )
                  })}
                  {labelsEnabled && (
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">
                      Labels
                    </th>
                  )}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={colCount} className="px-4 py-6 text-center text-gray-400 dark:text-gray-500">{emptyMessage}</td>
                  </tr>
                )}
                {rows.map(row => {
                  const expanded = expandedIds.has(row.id)
                  const filamentOnly = isFilamentRow(row)
                  return (
                    <Fragment key={`${row.kind}-${row.id}`}>
                      <tr
                        className="hover:bg-gray-50 dark:hover:bg-gray-750 cursor-pointer select-none"
                        onClick={() => toggleExpand(row.id)}
                      >
                        <td className="w-8 px-2 py-3 text-center">
                          <span className={`inline-block text-gray-400 dark:text-gray-500 transition-transform ${expanded ? 'rotate-180' : ''}`}>▾</span>
                        </td>
                        <td className="px-4 py-3 font-medium text-gray-900 dark:text-gray-100">
                          {row.name ?? '—'}
                          {filamentOnly && (
                            <span className="ml-2 text-xs text-gray-400 dark:text-gray-500 font-normal">(filament only)</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-gray-600 dark:text-gray-300">{row.vendor ?? '—'}</td>
                        <td className="px-4 py-3">
                          <ColorDisplay
                            colorHex={row.color ?? undefined}
                            multiColorHexes={row.multi_color_hexes}
                            multiColorDirection={row.multi_color_direction}
                            showLabel
                          />
                        </td>
                        <td className="px-4 py-3 text-gray-600 dark:text-gray-300">
                          {filamentOnly ? <span className="text-gray-400 dark:text-gray-500">—</span> : fmtWeight(row.spoolman_weight, '(net)')}
                        </td>
                        <td className="px-4 py-3 text-gray-600 dark:text-gray-300">
                          {filamentOnly ? <span className="text-gray-400 dark:text-gray-500">—</span> : fmtWeight(row.filamentdb_weight, '(gross)')}
                        </td>
                        <td className="px-4 py-3" onClick={e => e.stopPropagation()}>
                          <div className="flex flex-col items-start gap-1">
                            <StatusBadge status={row.status} />
                            {row.status === 'conflict' && row.conflict_id != null && (
                              <button
                                onClick={() => navigate(`/conflicts?highlight=${row.conflict_id}`)}
                                className="inline-flex items-center gap-1 text-xs font-medium text-amber-600 dark:text-amber-400 hover:text-amber-800 dark:hover:text-amber-300 transition-colors"
                                title="Jump to this conflict in the Conflicts page"
                              >
                                <svg className="w-3 h-3 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                  <path strokeLinecap="round" strokeLinejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                                </svg>
                                See conflict
                              </button>
                            )}
                          </div>
                        </td>
                        <td className="px-4 py-3 text-gray-500 dark:text-gray-400">{formatLocal(row.last_synced)}</td>
                        <td className="px-4 py-3" onClick={e => e.stopPropagation()}>
                          <DeepLinks
                            filamentdbFilamentId={row.filamentdb_filament_id}
                            spoolmanSpoolId={filamentOnly ? undefined : (row.spoolman_spool_id ?? undefined)}
                            spoolmanFilamentId={row.spoolman_filament_id ?? undefined}
                          />
                        </td>
                        {labelsEnabled && (
                          <td className="px-4 py-3" onClick={e => e.stopPropagation()}>
                            {!filamentOnly && row.filamentdb_spool_id ? (
                              <PrintLabelButton
                                filId={row.filamentdb_filament_id}
                                spoolId={row.filamentdb_spool_id}
                                variant="compact"
                              />
                            ) : (
                              <span className="text-gray-300 dark:text-gray-600">—</span>
                            )}
                          </td>
                        )}
                      </tr>
                      {expanded && (
                        <tr className="bg-gray-50/60 dark:bg-gray-900/30">
                          <td colSpan={colCount} className="px-6 py-3 border-t border-gray-100 dark:border-gray-700">
                            {filamentOnly ? (
                              <p className="text-xs text-gray-500 dark:text-gray-400 italic">
                                Filament only — no spool in Spoolman. This filament was imported but has no spool records.
                              </p>
                            ) : (
                              <>
                                <div className="flex items-center gap-1 mb-2">
                                  <span className="text-xs text-gray-400 dark:text-gray-500">Snapshot values</span>
                                  <HelpTip text="Last-known values per side from the bridge's snapshots — '—' means the field hasn't been baselined by a sync yet." />
                                </div>
                                <DetailGrid detail={row.detail} />
                              </>
                            )}
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
