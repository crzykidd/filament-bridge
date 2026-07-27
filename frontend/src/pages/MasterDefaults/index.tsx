import { useMemo, useState } from 'react'
import { getMasterDefaults, applyMasterDefaults } from '../../api/client'
import { useApi } from '../../api/hooks'
import { DeepLinks } from '../../components/DeepLinks'
import { HelpTip } from '../../components/HelpTip'
import type { MasterDefaultField, MasterDefaultRow, MasterDefaultsFailure } from '../../api/types'

const FIELD_ORDER: MasterDefaultField[] = [
  'spool_weight', 'nozzle_temp', 'bed_temp', 'density', 'diameter', 'type',
]

const FIELD_LABEL: Record<MasterDefaultField, string> = {
  spool_weight: 'Tare (spool weight)',
  nozzle_temp: 'Nozzle temp',
  bed_temp: 'Bed temp',
  density: 'Density',
  diameter: 'Diameter',
  type: 'Material',
}

function fmtValue(field: MasterDefaultField, v: unknown): string {
  if (v == null) return '—'
  switch (field) {
    case 'spool_weight': return `${v} g`
    case 'nozzle_temp': case 'bed_temp': return `${v}°C`
    case 'density': return `${v} g/cm³`
    case 'diameter': return `${v} mm`
    default: return String(v)
  }
}

/** Composite selection key: one checkbox per (master, field). */
function cellKey(filamentdbId: string, field: MasterDefaultField): string {
  return `${filamentdbId}::${field}`
}

function fillableFields(row: MasterDefaultRow): MasterDefaultField[] {
  return FIELD_ORDER.filter(f => row.fields[f]?.would_fill)
}

export default function MasterDefaults() {
  const { data, loading, error, reload } = useApi(getMasterDefaults)
  const [search, setSearch] = useState('')
  const [fillableOnly, setFillableOnly] = useState(true)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [saving, setSaving] = useState(false)
  const [result, setResult] = useState<{ updated: number; failed: MasterDefaultsFailure[] } | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)

  const allRows = useMemo(() => data?.rows ?? [], [data])

  const rows = useMemo(() => {
    let r = allRows
    if (fillableOnly) r = r.filter(row => fillableFields(row).length > 0)
    if (search.trim()) {
      const q = search.toLowerCase()
      r = r.filter(row => row.name?.toLowerCase().includes(q) || row.vendor?.toLowerCase().includes(q))
    }
    return r
  }, [allRows, fillableOnly, search])

  const totalFillableCells = useMemo(
    () => allRows.reduce((n, row) => n + fillableFields(row).length, 0),
    [allRows],
  )

  function toggleCell(filamentdbId: string, field: MasterDefaultField) {
    setSelected(prev => {
      const next = new Set(prev)
      const key = cellKey(filamentdbId, field)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  function toggleMaster(row: MasterDefaultRow) {
    const fields = fillableFields(row)
    const keys = fields.map(f => cellKey(row.filamentdb_id, f))
    const allSel = keys.length > 0 && keys.every(k => selected.has(k))
    setSelected(prev => {
      const next = new Set(prev)
      for (const k of keys) {
        if (allSel) next.delete(k)
        else next.add(k)
      }
      return next
    })
  }

  function toggleSelectAll() {
    const allKeys = rows.flatMap(row => fillableFields(row).map(f => cellKey(row.filamentdb_id, f)))
    const allSel = allKeys.length > 0 && allKeys.every(k => selected.has(k))
    setSelected(allSel ? new Set() : new Set(allKeys))
  }

  async function handleApply() {
    // Group selected (filamentdb_id, field) cells back into per-master updates.
    const byMaster = new Map<string, MasterDefaultField[]>()
    for (const key of selected) {
      const [filamentdbId, field] = key.split('::') as [string, MasterDefaultField]
      const arr = byMaster.get(filamentdbId)
      if (arr) arr.push(field)
      else byMaster.set(filamentdbId, [field])
    }
    const updates = Array.from(byMaster, ([filamentdb_id, fields]) => ({ filamentdb_id, fields }))
    if (updates.length === 0) return

    setSaving(true)
    setSaveError(null)
    setResult(null)
    try {
      const res = await applyMasterDefaults(updates)
      setResult(res)
      setSelected(new Set())
      reload()
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const selectedCount = selected.size
  const failedIds = new Set((result?.failed ?? []).map(f => f.filamentdb_id))

  return (
    <div className="p-8 space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Master Defaults</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1 max-w-3xl">
          Every master/container filament (real variant parents and synthetic containers alike)
          that has a field its variants already collectively agree on — but the master itself
          hasn't been given yet. Tick the fields you want to fill and Apply; nothing writes until
          you do. A value already set on the master is never overwritten.
        </p>
      </div>

      <div className="flex gap-3 flex-wrap items-center">
        <input
          type="text"
          placeholder="Search name / vendor…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="border border-gray-300 dark:border-gray-600 rounded px-3 py-1.5 text-sm w-64 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder:text-gray-400 dark:placeholder:text-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-400"
        />
        <label className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-300 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={fillableOnly}
            onChange={e => setFillableOnly(e.target.checked)}
            className="rounded border-gray-300 dark:border-gray-600 text-indigo-600 focus:ring-indigo-400"
          />
          Only masters with something to fill
          <HelpTip text="Hide masters where every field already has a value or the family doesn't agree on one." />
        </label>
        <span className="text-sm text-gray-500 dark:text-gray-400">
          {totalFillableCells} fillable field{totalFillableCells === 1 ? '' : 's'} across {allRows.length} master{allRows.length === 1 ? '' : 's'}
        </span>
      </div>

      <div className="flex gap-2 flex-wrap items-center bg-gray-50 dark:bg-gray-800/60 border border-gray-200 dark:border-gray-700 rounded px-3 py-2">
        <button
          onClick={toggleSelectAll}
          className="px-3 py-1 rounded text-sm font-medium bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-200 hover:bg-gray-300 dark:hover:bg-gray-600"
        >
          Select all fillable
        </button>
        <span className="text-sm text-gray-600 dark:text-gray-300">{selectedCount} selected</span>
        <span className="flex-1" />
        <button
          onClick={() => void handleApply()}
          disabled={saving || selectedCount === 0}
          className="px-4 py-1.5 rounded text-sm font-semibold bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {saving ? 'Applying…' : `Apply ${selectedCount} field${selectedCount === 1 ? '' : 's'}`}
        </button>
      </div>

      {result && (
        <div className="text-sm rounded border px-3 py-2 border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-900/20 text-emerald-800 dark:text-emerald-300">
          Applied defaults to {result.updated} master{result.updated === 1 ? '' : 's'}.
          {result.failed.length > 0 && (
            <ul className="mt-1 list-disc list-inside text-red-700 dark:text-red-300">
              {result.failed.map((f, i) => (
                <li key={i}>{f.filamentdb_id ?? '?'}: {f.error}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      {saveError && <p className="text-red-600 dark:text-red-400 text-sm">{saveError}</p>}

      {loading && <p className="text-gray-500 dark:text-gray-400">Loading…</p>}
      {error && <p className="text-red-600 dark:text-red-400">{error}</p>}

      {!loading && !error && (
        <div className="space-y-4">
          {rows.length === 0 && (
            <p className="text-center text-gray-400 dark:text-gray-500 py-6">No masters to show.</p>
          )}
          {rows.map(row => {
            const fillable = fillableFields(row)
            const failed = failedIds.has(row.filamentdb_id)
            return (
              <div
                key={row.filamentdb_id}
                className={`bg-white dark:bg-gray-800 rounded-lg border ${failed ? 'border-red-300 dark:border-red-700' : 'border-gray-200 dark:border-gray-700'} overflow-hidden`}
              >
                <div className="flex items-center gap-3 px-4 py-3 bg-gray-50 dark:bg-gray-750 border-b border-gray-200 dark:border-gray-700">
                  <input
                    type="checkbox"
                    checked={fillable.length > 0 && fillable.every(f => selected.has(cellKey(row.filamentdb_id, f)))}
                    ref={el => {
                      if (el) {
                        const anySel = fillable.some(f => selected.has(cellKey(row.filamentdb_id, f)))
                        const allSel = fillable.length > 0 && fillable.every(f => selected.has(cellKey(row.filamentdb_id, f)))
                        el.indeterminate = anySel && !allSel
                      }
                    }}
                    onChange={() => toggleMaster(row)}
                    disabled={fillable.length === 0}
                    className="rounded border-gray-300 dark:border-gray-600 text-indigo-600 focus:ring-indigo-400 disabled:opacity-30"
                    aria-label={`Select all fillable fields for ${row.name ?? row.filamentdb_id}`}
                  />
                  <div className="flex-1 min-w-0">
                    <span className="font-semibold text-gray-900 dark:text-gray-100">{row.name ?? row.filamentdb_id}</span>
                    {row.vendor && <span className="ml-2 text-sm text-gray-500 dark:text-gray-400">{row.vendor}</span>}
                    <span className={`ml-2 inline-block px-2 py-0.5 rounded text-xs font-medium ${row.is_synthetic ? 'bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-300' : 'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300'}`}>
                      {row.is_synthetic ? 'Synthetic container' : 'Master'}
                    </span>
                    <span className="ml-2 text-xs text-gray-400 dark:text-gray-500">{row.variant_count} variant{row.variant_count === 1 ? '' : 's'}</span>
                  </div>
                  <DeepLinks filamentdbFilamentId={row.filamentdb_id} spoolmanFilamentId={row.spoolman_filament_id} />
                </div>

                {fillable.length === 0 ? (
                  <p className="px-4 py-3 text-sm text-gray-400 dark:text-gray-500">
                    Nothing to fill — every field is already set, or the family doesn't agree on one.
                  </p>
                ) : (
                  <table className="min-w-full divide-y divide-gray-100 dark:divide-gray-700 text-sm">
                    <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                      {fillable.map(field => {
                        const cell = row.fields[field]
                        const key = cellKey(row.filamentdb_id, field)
                        return (
                          <tr key={field}>
                            <td className="w-8 px-4 py-2 text-center">
                              <input
                                type="checkbox"
                                checked={selected.has(key)}
                                onChange={() => toggleCell(row.filamentdb_id, field)}
                                className="rounded border-gray-300 dark:border-gray-600 text-indigo-600 focus:ring-indigo-400"
                                aria-label={`Fill ${FIELD_LABEL[field]} for ${row.name ?? row.filamentdb_id}`}
                              />
                            </td>
                            <td className="px-2 py-2 font-medium text-gray-700 dark:text-gray-200 whitespace-nowrap">
                              {FIELD_LABEL[field]}
                            </td>
                            <td className="px-2 py-2 text-gray-400 dark:text-gray-500">—</td>
                            <td className="px-2 py-2 text-gray-400 dark:text-gray-500">→</td>
                            <td className="px-2 py-2 font-mono text-indigo-700 dark:text-indigo-300">
                              {fmtValue(field, cell.proposal)}
                            </td>
                            <td className="px-2 py-2 text-xs text-gray-400 dark:text-gray-500">
                              from {cell.breakdown.length} variant{cell.breakdown.length === 1 ? '' : 's'}
                              {cell.breakdown.length > 0 && (
                                <>: {cell.breakdown.map(b => b.name ?? b.filamentdb_id).join(', ')}</>
                              )}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
