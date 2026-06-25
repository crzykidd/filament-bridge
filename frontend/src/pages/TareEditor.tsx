import { useMemo, useState } from 'react'
import { getTareRows, bulkSetTare } from '../api/client'
import { useApi } from '../api/hooks'
import { DeepLinks } from '../components/DeepLinks'
import { HelpTip } from '../components/HelpTip'
import type { TareFailure, TareRow, TareStatus } from '../api/types'

function fmtTare(v: number | null): string {
  return v == null ? '—' : `${v.toFixed(1)} g`
}

const STATUS_STYLES: Record<TareStatus, string> = {
  set: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
  missing: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
  mismatch: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
}

const STATUS_LABEL: Record<TareStatus, string> = {
  set: 'Set', missing: 'Missing', mismatch: 'Mismatch',
}

const ROLE_LABEL: Record<TareRow['role'], string> = {
  standalone: 'Standalone', master: 'Master', variant: 'Variant',
}

/** A new-tare input is dirty when it parses to a value different from the current effective tare. */
function isDirty(row: TareRow, raw: string | undefined): boolean {
  if (raw === undefined) return false
  const trimmed = raw.trim()
  if (trimmed === '') return false
  const n = Number(trimmed)
  if (!Number.isFinite(n) || n < 0) return false
  return n !== row.effective_tare
}

export default function TareEditor() {
  const { data, loading, error, reload } = useApi(getTareRows)
  const [search, setSearch] = useState('')
  const [needsOnly, setNeedsOnly] = useState(false)
  const [edits, setEdits] = useState<Record<number, string>>({})
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [bulkValue, setBulkValue] = useState('')
  const [saving, setSaving] = useState(false)
  const [result, setResult] = useState<{ updated: number; failed: TareFailure[] } | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)

  const allRows = useMemo(() => data?.rows ?? [], [data])

  const rows = useMemo(() => {
    let r = allRows
    if (needsOnly) r = r.filter(x => x.status !== 'set')
    if (search.trim()) {
      const q = search.toLowerCase()
      r = r.filter(x => x.name?.toLowerCase().includes(q) || x.vendor?.toLowerCase().includes(q))
    }
    return r
  }, [allRows, needsOnly, search])

  const dirtyUpdates = useMemo(
    () =>
      allRows
        .filter(row => row.editable && isDirty(row, edits[row.filament_mapping_id]))
        .map(row => ({
          filament_mapping_id: row.filament_mapping_id,
          tare_grams: Number(edits[row.filament_mapping_id].trim()),
        })),
    [allRows, edits],
  )

  const editableVisible = rows.filter(r => r.editable)
  const allSelected = editableVisible.length > 0 && editableVisible.every(r => selected.has(r.filament_mapping_id))

  function setEdit(id: number, value: string) {
    setEdits(prev => ({ ...prev, [id]: value }))
  }

  function toggleSelect(id: number) {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleSelectAll() {
    if (allSelected) setSelected(new Set())
    else setSelected(new Set(editableVisible.map(r => r.filament_mapping_id)))
  }

  function applyBulkToSelected() {
    const trimmed = bulkValue.trim()
    if (trimmed === '' || !Number.isFinite(Number(trimmed))) return
    setEdits(prev => {
      const next = { ...prev }
      for (const id of selected) next[id] = trimmed
      return next
    })
  }

  async function handleSave() {
    if (dirtyUpdates.length === 0) return
    setSaving(true)
    setSaveError(null)
    setResult(null)
    try {
      const res = await bulkSetTare(dirtyUpdates)
      setResult(res)
      // Clear successfully-saved edits + selection, then refetch live values.
      const failedIds = new Set(res.failed.map(f => f.filament_mapping_id))
      setEdits(prev => {
        const next: Record<number, string> = {}
        for (const [k, v] of Object.entries(prev)) {
          if (failedIds.has(Number(k))) next[Number(k)] = v
        }
        return next
      })
      setSelected(new Set())
      reload()
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const failedIds = new Set((result?.failed ?? []).map(f => f.filament_mapping_id))

  return (
    <div className="p-8 space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Tare Editor</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1 max-w-3xl">
          Edit the empty-reel tare weight (Filament DB <code>spoolWeight</code> / Spoolman{' '}
          <code>spool_weight</code>) for mapped filaments. Tare is shared by every spool of a
          filament and drives the net↔gross weight conversion, so a correct value matters. Saving
          writes both systems at once. Variants inherit their tare from the parent — edit the
          parent or a standalone filament.
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
            checked={needsOnly}
            onChange={e => setNeedsOnly(e.target.checked)}
            className="rounded border-gray-300 dark:border-gray-600 text-indigo-600 focus:ring-indigo-400"
          />
          Only missing / mismatched
          <HelpTip text="Show only filaments with no tare set, or whose Spoolman and Filament DB tare disagree." />
        </label>
      </div>

      {/* Bulk-set controls */}
      <div className="flex gap-2 flex-wrap items-center bg-gray-50 dark:bg-gray-800/60 border border-gray-200 dark:border-gray-700 rounded px-3 py-2">
        <span className="text-sm text-gray-600 dark:text-gray-300">
          {selected.size} selected
        </span>
        <input
          type="number"
          min={0}
          step="0.1"
          placeholder="grams"
          value={bulkValue}
          onChange={e => setBulkValue(e.target.value)}
          className="border border-gray-300 dark:border-gray-600 rounded px-2 py-1 text-sm w-28 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-400"
        />
        <button
          onClick={applyBulkToSelected}
          disabled={selected.size === 0 || bulkValue.trim() === ''}
          className="px-3 py-1 rounded text-sm font-medium bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-200 hover:bg-gray-300 dark:hover:bg-gray-600 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Apply to selected
        </button>
        <span className="flex-1" />
        <button
          onClick={() => void handleSave()}
          disabled={saving || dirtyUpdates.length === 0}
          className="px-4 py-1.5 rounded text-sm font-semibold bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {saving ? 'Saving…' : `Save ${dirtyUpdates.length} change${dirtyUpdates.length === 1 ? '' : 's'}`}
        </button>
      </div>

      {result && (
        <div className="text-sm rounded border px-3 py-2 border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-900/20 text-emerald-800 dark:text-emerald-300">
          Saved tare for {result.updated} filament{result.updated === 1 ? '' : 's'}.
          {result.failed.length > 0 && (
            <ul className="mt-1 list-disc list-inside text-red-700 dark:text-red-300">
              {result.failed.map((f, i) => (
                <li key={i}>Mapping {f.filament_mapping_id ?? '?'}: {f.error}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      {saveError && <p className="text-red-600 dark:text-red-400 text-sm">{saveError}</p>}

      {loading && <p className="text-gray-500 dark:text-gray-400">Loading…</p>}
      {error && <p className="text-red-600 dark:text-red-400">{error}</p>}

      {!loading && !error && (
        <div className="overflow-x-auto bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
          <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700 text-sm">
            <thead className="bg-gray-50 dark:bg-gray-750">
              <tr>
                <th className="w-8 px-2 py-3 text-center">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={toggleSelectAll}
                    className="rounded border-gray-300 dark:border-gray-600 text-indigo-600 focus:ring-indigo-400"
                    aria-label="Select all editable rows"
                  />
                </th>
                {(['Name', 'Vendor', 'Role', 'SM tare', 'FDB tare', 'New tare', 'Status', 'Links'] as const).map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
              {rows.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-4 py-6 text-center text-gray-400 dark:text-gray-500">
                    No filaments to show.
                  </td>
                </tr>
              )}
              {rows.map(row => {
                const id = row.filament_mapping_id
                const raw = edits[id]
                const dirty = isDirty(row, raw)
                const failed = failedIds.has(id)
                return (
                  <tr key={id} className={`hover:bg-gray-50 dark:hover:bg-gray-750 ${failed ? 'bg-red-50/60 dark:bg-red-900/10' : ''}`}>
                    <td className="w-8 px-2 py-3 text-center">
                      {row.editable && (
                        <input
                          type="checkbox"
                          checked={selected.has(id)}
                          onChange={() => toggleSelect(id)}
                          className="rounded border-gray-300 dark:border-gray-600 text-indigo-600 focus:ring-indigo-400"
                          aria-label={`Select ${row.name ?? id}`}
                        />
                      )}
                    </td>
                    <td className="px-4 py-3 font-medium text-gray-900 dark:text-gray-100">{row.name ?? '—'}</td>
                    <td className="px-4 py-3 text-gray-600 dark:text-gray-300">{row.vendor ?? '—'}</td>
                    <td className="px-4 py-3 text-gray-600 dark:text-gray-300">
                      {ROLE_LABEL[row.role]}
                      {row.role === 'variant' && row.parent_name && (
                        <span className="block text-xs text-gray-400 dark:text-gray-500">
                          ← {row.parent_name}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-gray-600 dark:text-gray-300">{fmtTare(row.spoolman_tare)}</td>
                    <td className="px-4 py-3 text-gray-600 dark:text-gray-300">{fmtTare(row.filamentdb_tare)}</td>
                    <td className="px-4 py-3">
                      {row.editable ? (
                        <input
                          type="number"
                          min={0}
                          step="0.1"
                          value={raw ?? (row.effective_tare != null ? String(row.effective_tare) : '')}
                          onChange={e => setEdit(id, e.target.value)}
                          className={`border rounded px-2 py-1 text-sm w-24 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-400 ${
                            dirty ? 'border-indigo-400 ring-1 ring-indigo-300' : 'border-gray-300 dark:border-gray-600'
                          }`}
                        />
                      ) : (
                        <span className="text-gray-400 dark:text-gray-500 italic" title="Inherited from parent — edit the parent">
                          {fmtTare(row.effective_tare)} (inherited)
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${STATUS_STYLES[row.status]}`}>
                        {STATUS_LABEL[row.status]}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <DeepLinks
                        filamentdbFilamentId={row.filamentdb_id}
                        spoolmanFilamentId={row.spoolman_filament_id}
                      />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
