import { useState } from 'react'
import { getConflicts, resolveConflict, bulkResolveConflicts } from '../api/client'
import { useApi } from '../api/hooks'
import { DeepLinks } from '../components/DeepLinks'
import type { ConflictResponse } from '../api/types'
import { formatLocal } from '../utils/datetime'

type Resolution = 'spoolman' | 'filamentdb' | 'manual'

// ---------------------------------------------------------------------------
// Color swatch (ported from StepVariances.tsx)
// ---------------------------------------------------------------------------

function ColorSwatch({ hex }: { hex: string | null | undefined }) {
  if (!hex) return null
  return (
    <span
      className="inline-block w-3.5 h-3.5 rounded-full border border-gray-300 shrink-0"
      style={{ backgroundColor: hex.startsWith('#') ? hex : `#${hex}` }}
      title={hex}
    />
  )
}

// ---------------------------------------------------------------------------
// Identity header — shown at the top of every conflict card
// ---------------------------------------------------------------------------

function ConflictIdentityHeader({ conflict }: { conflict: ConflictResponse }) {
  const { label, vendor: _vendor, color_hex, material, spoolman_id, filamentdb_filament_id, filamentdb_spool_id } = conflict
  return (
    <div className="flex items-center gap-2 flex-wrap pb-2 border-b border-gray-100 mb-2">
      <ColorSwatch hex={color_hex} />
      <span className="font-semibold text-gray-800 text-sm">{label ?? `SM #${spoolman_id}`}</span>
      {material && (
        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-600">
          {material}
        </span>
      )}
      {color_hex && (
        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-mono bg-gray-100 text-gray-500">
          {color_hex.startsWith('#') ? color_hex : `#${color_hex}`}
        </span>
      )}
      {spoolman_id != null && (
        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-emerald-50 text-emerald-700">
          SM #{spoolman_id}
        </span>
      )}
      {filamentdb_filament_id && (
        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-blue-50 text-blue-700">
          FDB fil {filamentdb_filament_id}
        </span>
      )}
      {filamentdb_spool_id && (
        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-blue-50 text-blue-600">
          FDB spool {filamentdb_spool_id}
        </span>
      )}
    </div>
  )
}

function ValueDisplay({ value }: { value: unknown }) {
  if (value == null) return <span className="text-gray-400">—</span>
  const s = typeof value === 'object' ? JSON.stringify(value) : String(value)
  return <span className="font-mono text-xs">{s}</span>
}

const DELETION_FIELD = '__record_deleted__'

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

const TYPE_ORDER: ConflictType[] = ['deleted', 'new_spool_sm', 'new_spool_fdb', 'weight', 'multicolor', 'property']

function classifyConflict(c: ConflictResponse): ConflictType {
  if (c.field_name === DELETION_FIELD) return 'deleted'
  if (c.field_name === 'new_spool') return c.spoolman_id != null ? 'new_spool_sm' : 'new_spool_fdb'
  if (c.field_name === 'weight' || c.field_name === 'remaining_weight') return 'weight'
  if (c.field_name === 'multicolor') return 'multicolor'
  return 'property'
}

function deletedSideLabel(conflict: ConflictResponse): string {
  const descriptor = (conflict.spoolman_value ?? conflict.filamentdb_value) as { deleted_side?: string } | null
  if (descriptor?.deleted_side === 'filamentdb') return 'Filament DB'
  if (descriptor?.deleted_side === 'spoolman') return 'Spoolman'
  return 'one side'
}

function ResolveRow({ conflict, onResolved }: { conflict: ConflictResponse; onResolved: () => void }) {
  const [resolution, setResolution] = useState<Resolution>('spoolman')
  const [manualValue, setManualValue] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const isDeletion = conflict.field_name === DELETION_FIELD

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
    <div className="bg-white rounded-lg border border-gray-200 p-5 space-y-3">
      <ConflictIdentityHeader conflict={conflict} />
      <div className="flex items-start justify-between gap-4">
        <div>
          <span className="text-xs text-gray-500 uppercase tracking-wide">{conflict.entity_type}</span>
          <h3 className="font-medium text-gray-900">
            {isDeletion ? 'Record deleted upstream' : conflict.field_name}
          </h3>
          <p className="text-xs text-gray-400 mt-0.5">Detected {formatLocal(conflict.detected_at)}</p>
        </div>
        <DeepLinks
          filamentdbFilamentId={conflict.filamentdb_filament_id}
          spoolmanSpoolId={conflict.spoolman_id}
        />
      </div>

      {isDeletion ? (
        <div className="bg-amber-50 border border-amber-200 rounded p-3 text-sm text-amber-800">
          This record was deleted in <strong>{deletedSideLabel(conflict)}</strong>. Removing the
          mapping will drop the pair from Synced Records. The deleted record will not be recreated.
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div className="bg-emerald-50 rounded p-3">
            <p className="text-xs font-medium text-emerald-700 mb-1">Spoolman value</p>
            <ValueDisplay value={conflict.spoolman_value} />
          </div>
          <div className="bg-blue-50 rounded p-3">
            <p className="text-xs font-medium text-blue-700 mb-1">Filament DB value</p>
            <ValueDisplay value={conflict.filamentdb_value} />
          </div>
        </div>
      )}

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
      ) : (
        <div className="flex items-center gap-2 flex-wrap">
          {(['spoolman', 'filamentdb', 'manual'] as const).map(r => (
            <button
              key={r}
              onClick={() => setResolution(r)}
              className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
                resolution === r
                  ? 'bg-indigo-600 text-white'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
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
              className="border border-gray-300 rounded px-3 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
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
      {err && <p className="text-sm text-red-600">{err}</p>}
    </div>
  )
}

export default function Conflicts() {
  const [tab, setTab] = useState<'open' | 'resolved'>('open')
  const { data, loading, error, reload } = useApi(() => getConflicts(tab), [tab])

  const [selected, setSelected] = useState<number[]>([])
  const [bulkRes, setBulkRes] = useState<Resolution>('spoolman')
  const [bulking, setBulking] = useState(false)
  const [typeFilter, setTypeFilter] = useState<ConflictType | 'all'>('all')

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

  const rows: ConflictResponse[] =
    activeFilter === 'all' ? allRows : allRows.filter(c => classifyConflict(c) === activeFilter)

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
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Conflicts</h1>
        <div className="flex gap-2">
          {(['open', 'resolved'] as const).map(t => (
            <button
              key={t}
              onClick={() => { setTab(t); setSelected([]) }}
              className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
                tab === t ? 'bg-indigo-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {t.charAt(0).toUpperCase() + t.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {loading && <p className="text-gray-500">Loading…</p>}
      {error && <p className="text-red-600">{error}</p>}

      {!loading && !error && allRows.length > 0 && typeCounts.length > 1 && (
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => { setTypeFilter('all'); setSelected([]) }}
            className={`px-3 py-1.5 rounded-full text-sm font-medium transition-colors ${
              activeFilter === 'all'
                ? 'bg-gray-800 text-white'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
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
                  ? 'bg-gray-800 text-white'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {label} ({count})
            </button>
          ))}
        </div>
      )}

      {tab === 'open' && selected.length > 0 && (
        <div className="flex items-center gap-3 bg-indigo-50 border border-indigo-200 rounded p-3">
          <span className="text-sm text-indigo-700">{selected.length} selected</span>
          {(['spoolman', 'filamentdb'] as const).map(r => (
            <button
              key={r}
              onClick={() => setBulkRes(r)}
              className={`px-3 py-1 rounded text-sm font-medium ${bulkRes === r ? 'bg-indigo-600 text-white' : 'bg-white border border-gray-300'}`}
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

      {!loading && !error && rows.length === 0 && (
        <p className="text-gray-500">
          {activeFilter === 'all'
            ? `No ${tab} conflicts.`
            : `No ${tab} ${TYPE_LABELS[activeFilter].toLowerCase()} conflicts.`}
        </p>
      )}

      <div className="space-y-3">
        {rows.map(c => (
          <div key={c.id} className="flex gap-3">
            {tab === 'open' && (
              <input
                type="checkbox"
                checked={selected.includes(c.id)}
                onChange={() => toggleSelect(c.id)}
                className="mt-5 h-4 w-4 rounded border-gray-300 text-indigo-600"
              />
            )}
            <div className="flex-1">
              {tab === 'open'
                ? <ResolveRow conflict={c} onResolved={reload} />
                : (
                  <div className="bg-white rounded-lg border border-gray-200 p-4 space-y-2">
                    <ConflictIdentityHeader conflict={c} />
                    <div className="flex items-center justify-between">
                      <div>
                        <span className="text-xs text-gray-500 uppercase">{c.entity_type}</span>
                        <h3 className="font-medium text-gray-900">{c.field_name}</h3>
                        <p className="text-xs text-gray-400">
                          Resolved {formatLocal(c.resolved_at)} via {c.resolution}
                        </p>
                      </div>
                      <DeepLinks
                        filamentdbFilamentId={c.filamentdb_filament_id}
                        spoolmanSpoolId={c.spoolman_id}
                      />
                    </div>
                  </div>
                )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
