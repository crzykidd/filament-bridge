import { useState, useMemo } from 'react'
import { getConflicts, resolveConflict, bulkResolveConflicts } from '../api/client'
import { useApi } from '../api/hooks'
import { DeepLinks } from '../components/DeepLinks'
import { ColorDisplay } from '../components/ColorDisplay'
import type { ConflictResponse } from '../api/types'
import { formatLocal } from '../utils/datetime'

type Resolution = 'spoolman' | 'filamentdb' | 'manual'
type SortKey = 'detected' | 'type' | 'label'

// ---------------------------------------------------------------------------
// Conflict type classification
// ---------------------------------------------------------------------------

type ConflictType = 'deleted' | 'new_spool_sm' | 'new_spool_fdb' | 'weight' | 'multicolor' | 'property'

const TYPE_LABELS: Record<ConflictType, string> = {
  deleted: 'Deleted record',
  new_spool_sm: 'New spool (Spoolman)',
  new_spool_fdb: 'New spool (Filament DB)',
  weight: 'Weight',
  multicolor: 'Multicolor',
  property: 'Property',
}

const TYPE_BADGE_COLORS: Record<ConflictType, string> = {
  deleted: 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400',
  new_spool_sm: 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400',
  new_spool_fdb: 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400',
  weight: 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400',
  multicolor: 'bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400',
  property: 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300',
}

const TYPE_ORDER: ConflictType[] = ['deleted', 'new_spool_sm', 'new_spool_fdb', 'weight', 'multicolor', 'property']

const DELETION_FIELD = '__record_deleted__'

function classifyConflict(c: ConflictResponse): ConflictType {
  if (c.field_name === DELETION_FIELD) return 'deleted'
  if (c.field_name === 'new_spool') return c.spoolman_id != null ? 'new_spool_sm' : 'new_spool_fdb'
  if (c.field_name === 'weight' || c.field_name === 'remaining_weight') return 'weight'
  if (c.field_name === 'multicolor') return 'multicolor'
  return 'property'
}

function isNewSpool(c: ConflictResponse): boolean {
  return c.field_name === 'new_spool'
}

function deletedSideLabel(conflict: ConflictResponse): string {
  const descriptor = (conflict.spoolman_value ?? conflict.filamentdb_value) as { deleted_side?: string } | null
  if (descriptor?.deleted_side === 'filamentdb') return 'Filament DB'
  if (descriptor?.deleted_side === 'spoolman') return 'Spoolman'
  return 'one side'
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ValueDisplay({ value }: { value: unknown }) {
  if (value == null) return <span className="text-gray-400 dark:text-gray-500">—</span>
  const s = typeof value === 'object' ? JSON.stringify(value) : String(value)
  return <span className="font-mono text-xs text-gray-900 dark:text-gray-100">{s}</span>
}

/**
 * The expanded resolve / detail body — rendered inside a CollapsibleConflict
 * when expanded.
 */
function ConflictDetail({ conflict, onResolved }: { conflict: ConflictResponse; onResolved: () => void }) {
  const [resolution, setResolution] = useState<Resolution>('spoolman')
  const [manualValue, setManualValue] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const isDeletion = conflict.field_name === DELETION_FIELD
  const newSpool = isNewSpool(conflict)

  async function submit(overrideResolution?: Resolution) {
    const res = overrideResolution ?? resolution
    setSubmitting(true)
    setErr(null)
    try {
      await resolveConflict(conflict.id, {
        resolution: res,
        value: res === 'manual' ? manualValue : undefined,
      })
      onResolved()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="border-t border-gray-100 dark:border-gray-700 mt-0 px-4 pb-4 pt-3 space-y-3">
      {/* Values grid (not shown for deletion or new_spool) */}
      {!isDeletion && !newSpool && (
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div className="bg-emerald-50 dark:bg-emerald-900/20 rounded p-3">
            <p className="text-xs font-medium text-emerald-700 dark:text-emerald-400 mb-1">Spoolman value</p>
            <ValueDisplay value={conflict.spoolman_value} />
          </div>
          <div className="bg-blue-50 dark:bg-blue-900/20 rounded p-3">
            <p className="text-xs font-medium text-blue-700 dark:text-blue-400 mb-1">Filament DB value</p>
            <ValueDisplay value={conflict.filamentdb_value} />
          </div>
        </div>
      )}

      {isDeletion && (
        <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded p-3 text-sm text-amber-800 dark:text-amber-300">
          This record was deleted in <strong>{deletedSideLabel(conflict)}</strong>. Removing the
          mapping will drop the pair from Synced Records. The deleted record will not be recreated.
        </div>
      )}

      {newSpool && (
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Dismisses this notice — create the record via the{' '}
          <span className="font-medium text-gray-700 dark:text-gray-300">Bulk Import Wizard</span>.
        </p>
      )}

      {/* Action row */}
      {isDeletion ? (
        <div className="flex items-center gap-2">
          <button
            onClick={() => submit('spoolman')}
            disabled={submitting}
            className="px-4 py-1.5 bg-red-600 text-white rounded text-sm font-medium hover:bg-red-700 disabled:opacity-50"
          >
            {submitting ? 'Removing…' : 'Remove mapping'}
          </button>
        </div>
      ) : newSpool ? (
        <div className="flex items-center gap-2">
          <button
            onClick={() => submit('spoolman')}
            disabled={submitting}
            className="px-4 py-1.5 bg-gray-600 text-white rounded text-sm font-medium hover:bg-gray-700 disabled:opacity-50"
          >
            {submitting ? 'Dismissing…' : 'Dismiss'}
          </button>
        </div>
      ) : (
        <div className="flex items-center gap-2 flex-wrap">
          {(['spoolman', 'filamentdb', 'manual'] as const).map(r => (
            <button
              key={r}
              onClick={() => setResolution(r)}
              className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
                resolution === r
                  ? 'bg-indigo-600 text-white'
                  : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
              }`}
            >
              Use {r === 'manual' ? 'manual value' : r}
            </button>
          ))}
          {resolution === 'manual' && (
            <input
              type="text"
              placeholder="Enter value…"
              value={manualValue}
              onChange={e => setManualValue(e.target.value)}
              className="border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 rounded px-3 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
            />
          )}
          <button
            onClick={() => submit()}
            disabled={submitting || (resolution === 'manual' && !manualValue.trim())}
            className="ml-auto px-4 py-1.5 bg-indigo-600 text-white rounded text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
          >
            {submitting ? 'Saving…' : 'Resolve'}
          </button>
        </div>
      )}
      {err && <p className="text-sm text-red-600 dark:text-red-400">{err}</p>}
    </div>
  )
}

/**
 * Compact single-row conflict card with expand/collapse.
 */
function CollapsibleConflict({
  conflict,
  expanded,
  onToggle,
  onResolved,
  tab,
  selected,
  onSelect,
}: {
  conflict: ConflictResponse
  expanded: boolean
  onToggle: () => void
  onResolved: () => void
  tab: 'open' | 'resolved'
  selected: boolean
  onSelect: () => void
}) {
  const type = classifyConflict(conflict)
  const fieldLabel = conflict.field_name === DELETION_FIELD ? 'Record deleted' : conflict.field_name

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
      {/* Compact summary row */}
      <div
        className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-750 select-none"
        onClick={onToggle}
      >
        {/* Checkbox (open tab only, stop propagation so click doesn't expand) */}
        {tab === 'open' && (
          <input
            type="checkbox"
            checked={selected}
            onClick={e => e.stopPropagation()}
            onChange={onSelect}
            className="h-4 w-4 rounded border-gray-300 dark:border-gray-600 text-indigo-600 shrink-0"
          />
        )}

        {/* Type badge */}
        <span className={`shrink-0 inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${TYPE_BADGE_COLORS[type]}`}>
          {TYPE_LABELS[type]}
        </span>

        {/* Color swatch */}
        <ColorDisplay
          colorHex={conflict.color_hex}
          multiColorHexes={conflict.multi_color_hexes}
          multiColorDirection={conflict.multi_color_direction}
          showLabel={false}
        />

        {/* Identity label */}
        <span className="flex-1 text-sm font-medium text-gray-800 dark:text-gray-200 truncate min-w-0">
          {conflict.label ?? `SM #${conflict.spoolman_id}`}
        </span>

        {/* Field / entity */}
        <span className="shrink-0 text-xs text-gray-400 dark:text-gray-500 hidden sm:block">{conflict.entity_type}</span>
        <span className="shrink-0 text-xs font-mono text-gray-500 dark:text-gray-400 hidden md:block">{fieldLabel}</span>

        {/* Detected time */}
        <span className="shrink-0 text-xs text-gray-400 dark:text-gray-500 hidden lg:block">
          {formatLocal(conflict.detected_at)}
        </span>

        {/* Deep links (stop click so expanding doesn't fight the link) */}
        <span onClick={e => e.stopPropagation()}>
          <DeepLinks
            filamentdbFilamentId={conflict.filamentdb_filament_id}
            spoolmanSpoolId={conflict.spoolman_id}
          />
        </span>

        {/* Resolved badge (resolved tab only) */}
        {tab === 'resolved' && conflict.resolution && (
          <span className="shrink-0 text-xs text-gray-400 dark:text-gray-500">via {conflict.resolution}</span>
        )}

        {/* Caret */}
        <span className={`shrink-0 text-gray-400 dark:text-gray-500 transition-transform ${expanded ? 'rotate-180' : ''}`}>
          ▾
        </span>
      </div>

      {/* Expanded detail */}
      {expanded && tab === 'open' && (
        <ConflictDetail conflict={conflict} onResolved={onResolved} />
      )}
      {expanded && tab === 'resolved' && (
        <div className="border-t border-gray-100 dark:border-gray-700 px-4 py-3 text-sm text-gray-500 dark:text-gray-400 space-y-1">
          <p>Resolved {formatLocal(conflict.resolved_at)} via <strong>{conflict.resolution}</strong></p>
          {conflict.resolved_value != null && (
            <p>Recorded value: <ValueDisplay value={conflict.resolved_value} /></p>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function Conflicts() {
  const [tab, setTab] = useState<'open' | 'resolved'>('open')
  const { data, loading, error, reload } = useApi(() => getConflicts(tab), [tab])

  const [selected, setSelected] = useState<number[]>([])
  const [bulkRes, setBulkRes] = useState<Resolution>('spoolman')
  const [bulking, setBulking] = useState(false)
  const [typeFilter, setTypeFilter] = useState<ConflictType | 'all'>('all')
  const [sortKey, setSortKey] = useState<SortKey>('detected')
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set())

  const allRows: ConflictResponse[] = data ?? []

  // Counts per type — only types present in the current tab's data
  const typeCounts: { type: ConflictType; label: string; count: number }[] = TYPE_ORDER
    .map(t => ({ type: t, label: TYPE_LABELS[t], count: allRows.filter(c => classifyConflict(c) === t).length }))
    .filter(entry => entry.count > 0)

  // If the active filter has no rows (e.g. after resolving the last of a type), fall back to 'all'
  const activeFilter: ConflictType | 'all' =
    typeFilter !== 'all' && !typeCounts.find(e => e.type === typeFilter)
      ? 'all'
      : typeFilter

  const filtered: ConflictResponse[] =
    activeFilter === 'all' ? allRows : allRows.filter(c => classifyConflict(c) === activeFilter)

  const rows: ConflictResponse[] = useMemo(() => {
    const copy = [...filtered]
    if (sortKey === 'detected') {
      copy.sort((a, b) => b.detected_at.localeCompare(a.detected_at))
    } else if (sortKey === 'type') {
      copy.sort((a, b) => TYPE_ORDER.indexOf(classifyConflict(a)) - TYPE_ORDER.indexOf(classifyConflict(b)))
    } else if (sortKey === 'label') {
      copy.sort((a, b) => {
        const la = (a.label ?? `SM #${a.spoolman_id}`).toLowerCase()
        const lb = (b.label ?? `SM #${b.spoolman_id}`).toLowerCase()
        return la.localeCompare(lb)
      })
    }
    return copy
  }, [filtered, sortKey])

  function toggleExpand(id: number) {
    setExpandedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function expandAll() {
    setExpandedIds(new Set(rows.map(r => r.id)))
  }

  function collapseAll() {
    setExpandedIds(new Set())
  }

  async function handleBulk() {
    if (selected.length === 0) return
    setBulking(true)
    try {
      await bulkResolveConflicts({ ids: selected, resolution: bulkRes })
      setSelected([])
      void reload()
    } catch (e) {
      console.error(e)
    } finally {
      setBulking(false)
    }
  }

  function toggleSelect(id: number) {
    setSelected(s => s.includes(id) ? s.filter(x => x !== id) : [...s, id])
  }

  return (
    <div className="p-8 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Conflicts</h1>
        <div className="flex gap-2">
          {(['open', 'resolved'] as const).map(t => (
            <button
              key={t}
              onClick={() => { setTab(t); setSelected([]); setExpandedIds(new Set()) }}
              className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
                tab === t
                  ? 'bg-indigo-600 text-white'
                  : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
              }`}
            >
              {t.charAt(0).toUpperCase() + t.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* Info banner — explain what Resolve does */}
      <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg px-4 py-3 text-sm text-blue-800 dark:text-blue-300 space-y-1">
        <p>
          <strong>Resolving a conflict records your choice and removes it from the queue</strong> — it does
          not write to Spoolman or Filament DB (upstream apply is a planned follow-up). Deletion conflicts
          remove the bridge mapping only.
        </p>
      </div>

      {loading && <p className="text-gray-500 dark:text-gray-400">Loading…</p>}
      {error && <p className="text-red-600 dark:text-red-400">{error}</p>}

      {/* Filter bar + Sort + Expand controls */}
      {!loading && !error && allRows.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          {typeCounts.length > 1 && (
            <>
              <button
                onClick={() => { setTypeFilter('all'); setSelected([]) }}
                className={`px-3 py-1.5 rounded-full text-sm font-medium transition-colors ${
                  activeFilter === 'all'
                    ? 'bg-gray-800 dark:bg-gray-200 text-white dark:text-gray-900'
                    : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                }`}
              >
                All ({allRows.length})
              </button>
              {typeCounts.map(({ type, label, count }) => (
                <button
                  key={type}
                  onClick={() => { setTypeFilter(type); setSelected([]) }}
                  className={`px-3 py-1.5 rounded-full text-sm font-medium transition-colors ${
                    activeFilter === type
                      ? 'bg-gray-800 dark:bg-gray-200 text-white dark:text-gray-900'
                      : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                  }`}
                >
                  {label} ({count})
                </button>
              ))}
              <span className="w-px h-5 bg-gray-200 dark:bg-gray-600 mx-1" />
            </>
          )}

          {/* Sort control */}
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-gray-500 dark:text-gray-400">Sort:</span>
            {([
              ['detected', 'Newest'],
              ['type', 'Type'],
              ['label', 'Label'],
            ] as [SortKey, string][]).map(([key, lbl]) => (
              <button
                key={key}
                onClick={() => setSortKey(key)}
                className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                  sortKey === key
                    ? 'bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300'
                    : 'bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-600'
                }`}
              >
                {lbl}
              </button>
            ))}
          </div>

          {rows.length > 1 && (
            <>
              <span className="w-px h-5 bg-gray-200 dark:bg-gray-600 mx-1" />
              <button
                onClick={expandAll}
                className="px-2.5 py-1 rounded text-xs font-medium bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-600"
              >
                Expand all
              </button>
              <button
                onClick={collapseAll}
                className="px-2.5 py-1 rounded text-xs font-medium bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-600"
              >
                Collapse all
              </button>
            </>
          )}
        </div>
      )}

      {/* Bulk resolve bar */}
      {tab === 'open' && selected.length > 0 && (
        <div className="flex items-center gap-3 bg-indigo-50 dark:bg-indigo-900/20 border border-indigo-200 dark:border-indigo-800 rounded p-3">
          <span className="text-sm text-indigo-700 dark:text-indigo-300">{selected.length} selected</span>
          {(['spoolman', 'filamentdb'] as const).map(r => (
            <button
              key={r}
              onClick={() => setBulkRes(r)}
              className={`px-3 py-1 rounded text-sm font-medium ${
                bulkRes === r
                  ? 'bg-indigo-600 text-white'
                  : 'bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200'
              }`}
            >
              Use {r}
            </button>
          ))}
          <button
            onClick={handleBulk}
            disabled={bulking}
            className="px-4 py-1 bg-indigo-600 text-white rounded text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
          >
            {bulking ? 'Resolving…' : 'Bulk resolve'}
          </button>
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && rows.length === 0 && (
        <p className="text-gray-500 dark:text-gray-400">
          {activeFilter === 'all'
            ? `No ${tab} conflicts.`
            : `No ${tab} ${TYPE_LABELS[activeFilter].toLowerCase()} conflicts.`}
        </p>
      )}

      {/* Conflict rows */}
      <div className="space-y-2">
        {rows.map(c => (
          <CollapsibleConflict
            key={c.id}
            conflict={c}
            expanded={expandedIds.has(c.id)}
            onToggle={() => toggleExpand(c.id)}
            onResolved={reload}
            tab={tab}
            selected={selected.includes(c.id)}
            onSelect={() => toggleSelect(c.id)}
          />
        ))}
      </div>
    </div>
  )
}
