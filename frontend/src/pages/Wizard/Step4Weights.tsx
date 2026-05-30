import { useState } from 'react'
import { getWizardWeights } from '../../api/client'
import { useApi } from '../../api/hooks'
import { DeepLinks } from '../../components/DeepLinks'
import type { WizardTareOverride } from '../../api/types'
import type { WizardCtx } from './index'

export default function Step4Weights({ next, prev, setTareOverrides }: WizardCtx) {
  const { data, loading, error } = useApi(getWizardWeights)
  const [overrides, setOverrides] = useState<Record<string, string>>({})

  function rowKey(spoolmanId: number | null, fdbId: string | null) {
    return `${spoolmanId ?? 'null'}_${fdbId ?? 'null'}`
  }

  function handleNext() {
    const tare: WizardTareOverride[] = []
    if (!data) { next(); return }
    for (const row of data.rows) {
      const key = rowKey(row.spoolman_spool_id, row.filamentdb_spool_id)
      const val = overrides[key]
      if (val && !isNaN(parseFloat(val))) {
        tare.push({
          spoolman_spool_id: row.spoolman_spool_id,
          filamentdb_spool_id: row.filamentdb_spool_id,
          tare: parseFloat(val),
        })
      }
    }
    setTareOverrides(tare)
    next()
  }

  if (loading) return <p className="text-gray-500">Loading weight preview…</p>
  if (error) return <p className="text-red-600">{error}</p>
  if (!data) return null

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-gray-800">Weight review</h2>
        <p className="text-sm text-gray-500 mt-1">
          Review net ↔ gross weight conversions. Override tare weights (empty reel) per spool if needed.
          Direction: <strong>{data.direction.replace(/_/g, ' ')}</strong>.
        </p>
      </div>

      <div className="overflow-x-auto bg-white rounded-lg border border-gray-200">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50">
            <tr>
              {['Spool', 'Net (g)', 'Gross (g)', 'Tare (g)', 'Tare source', 'Override tare', 'Links'].map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {data.rows.length === 0 && (
              <tr><td colSpan={7} className="px-4 py-6 text-center text-gray-400">No rows</td></tr>
            )}
            {data.rows.map(row => {
              const key = rowKey(row.spoolman_spool_id, row.filamentdb_spool_id)
              return (
                <tr key={key} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-900">{row.name ?? '—'}</td>
                  <td className="px-4 py-3 text-gray-600">{row.net_weight?.toFixed(1) ?? '—'}</td>
                  <td className="px-4 py-3 text-gray-600">{row.gross_weight?.toFixed(1) ?? '—'}</td>
                  <td className="px-4 py-3 text-gray-600">{row.tare.toFixed(1)}</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-1.5 py-0.5 rounded ${
                      row.tare_source === 'default'
                        ? 'bg-yellow-100 text-yellow-700'
                        : 'bg-gray-100 text-gray-600'
                    }`}>
                      {row.tare_source}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <input
                      type="number"
                      min="0"
                      step="1"
                      placeholder={row.tare.toFixed(0)}
                      value={overrides[key] ?? ''}
                      onChange={e => setOverrides(o => ({ ...o, [key]: e.target.value }))}
                      className="w-20 border border-gray-300 rounded px-2 py-1 text-xs text-right focus:outline-none focus:ring-2 focus:ring-indigo-400"
                    />
                  </td>
                  <td className="px-4 py-3">
                    <DeepLinks
                      filamentdbFilamentId={row.filamentdb_filament_id}
                      spoolmanSpoolId={row.spoolman_spool_id}
                    />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div className="flex justify-between">
        <button onClick={prev} className="px-5 py-2 bg-gray-100 text-gray-700 rounded text-sm font-medium hover:bg-gray-200">
          ← Back
        </button>
        <button
          onClick={handleNext}
          className="px-5 py-2 bg-indigo-600 text-white rounded text-sm font-medium hover:bg-indigo-700"
        >
          Next →
        </button>
      </div>
    </div>
  )
}
