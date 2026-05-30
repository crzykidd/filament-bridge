import { useState } from 'react'
import { getConflicts, resolveConflict, bulkResolveConflicts } from '../api/client'
import { useApi } from '../api/hooks'
import { DeepLinks } from '../components/DeepLinks'
import type { ConflictResponse } from '../api/types'

type Resolution = 'spoolman' | 'filamentdb' | 'manual'

function ValueDisplay({ value }: { value: unknown }) {
  if (value == null) return <span className="text-gray-400">—</span>
  const s = typeof value === 'object' ? JSON.stringify(value) : String(value)
  return <span className="font-mono text-xs">{s}</span>
}

function ResolveRow({ conflict, onResolved }: { conflict: ConflictResponse; onResolved: () => void }) {
  const [resolution, setResolution] = useState<Resolution>('spoolman')
  const [manualValue, setManualValue] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function submit() {
    setSubmitting(true)
    setErr(null)
    try {
      await resolveConflict(conflict.id, {
        resolution,
        value: resolution === 'manual' ? manualValue : undefined,
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
      <div className="flex items-start justify-between gap-4">
        <div>
          <span className="text-xs text-gray-500 uppercase tracking-wide">{conflict.entity_type}</span>
          <h3 className="font-medium text-gray-900">{conflict.field_name}</h3>
          <p className="text-xs text-gray-400 mt-0.5">Detected {new Date(conflict.detected_at).toLocaleString()}</p>
        </div>
        <DeepLinks
          filamentdbFilamentId={conflict.filamentdb_filament_id}
          spoolmanSpoolId={conflict.spoolman_id}
        />
      </div>

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
          onClick={submit}
          disabled={submitting || (resolution === 'manual' && !manualValue.trim())}
          className="ml-auto px-4 py-1.5 bg-indigo-600 text-white rounded text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
        >
          {submitting ? 'Saving…' : 'Resolve'}
        </button>
      </div>
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

  const rows: ConflictResponse[] = data ?? []

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
        <p className="text-gray-500">No {tab} conflicts.</p>
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
                  <div className="bg-white rounded-lg border border-gray-200 p-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <span className="text-xs text-gray-500 uppercase">{c.entity_type}</span>
                        <h3 className="font-medium text-gray-900">{c.field_name}</h3>
                        <p className="text-xs text-gray-400">
                          Resolved {c.resolved_at ? new Date(c.resolved_at).toLocaleString() : '—'} via {c.resolution}
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
