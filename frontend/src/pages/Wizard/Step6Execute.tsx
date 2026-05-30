import { useState } from 'react'
import { postWizardExecute } from '../../api/client'
import { DeepLinks } from '../../components/DeepLinks'
import type { WizardExecuteResponse } from '../../api/types'
import type { WizardCtx } from './index'

export default function Step6Execute({ prev, tareOverrides }: WizardCtx) {
  const [confirmed, setConfirmed] = useState(false)
  const [executing, setExecuting] = useState(false)
  const [result, setResult] = useState<WizardExecuteResponse | null>(null)
  const [err, setErr] = useState<string | null>(null)

  async function handleExecute() {
    setExecuting(true)
    setErr(null)
    try {
      const res = await postWizardExecute({ tare_overrides: tareOverrides })
      setResult(res)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setExecuting(false)
    }
  }

  if (result) {
    const actionColors: Record<string, string> = {
      created: 'bg-green-100 text-green-700',
      updated: 'bg-blue-100 text-blue-700',
      skipped: 'bg-gray-100 text-gray-600',
      failed: 'bg-red-100 text-red-700',
    }

    return (
      <div className="space-y-5">
        <div>
          <h2 className="text-lg font-semibold text-gray-800">Execute complete</h2>
          <p className="text-sm text-gray-500 mt-1">
            Direction: {result.direction.replace(/_/g, ' ')} ·
            Wizard completed: {result.wizard_completed ? 'Yes' : 'No'}
          </p>
        </div>

        <div className="grid grid-cols-4 gap-3">
          {[
            { label: 'Created', value: result.created, color: 'text-green-600' },
            { label: 'Updated', value: result.updated, color: 'text-blue-600' },
            { label: 'Skipped', value: result.skipped, color: 'text-gray-500' },
            { label: 'Failed', value: result.failed, color: 'text-red-600' },
          ].map(c => (
            <div key={c.label} className="bg-white rounded-lg border border-gray-200 p-3 text-center">
              <p className="text-xs text-gray-500">{c.label}</p>
              <p className={`text-2xl font-bold ${c.color}`}>{c.value}</p>
            </div>
          ))}
        </div>

        <div className="overflow-x-auto bg-white rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50">
              <tr>
                {['Type', 'Action', 'Detail', 'Links'].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {result.records.map((rec, i) => (
                <tr key={i} className="hover:bg-gray-50">
                  <td className="px-4 py-2 text-gray-600 text-xs">{rec.entity_type}</td>
                  <td className="px-4 py-2">
                    <span className={`inline-flex px-1.5 py-0.5 rounded text-xs font-medium ${actionColors[rec.action] ?? ''}`}>
                      {rec.action}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-xs text-gray-600">
                    {rec.error
                      ? <span className="text-red-600">{rec.error}</span>
                      : rec.detail ?? '—'}
                  </td>
                  <td className="px-4 py-2">
                    <DeepLinks
                      filamentdbFilamentId={rec.filamentdb_filament_id}
                      spoolmanSpoolId={rec.spoolman_spool_id}
                      spoolmanFilamentId={rec.spoolman_filament_id}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-gray-800">Execute initial sync</h2>
        <p className="text-sm text-gray-500 mt-1">
          This will write to both Spoolman and Filament DB. Review your choices before proceeding.
        </p>
        {tareOverrides.length > 0 && (
          <p className="text-sm text-gray-500 mt-1">
            {tareOverrides.length} tare override{tareOverrides.length !== 1 ? 's' : ''} applied.
          </p>
        )}
      </div>

      <div className="bg-amber-50 border border-amber-200 rounded p-4">
        <p className="text-amber-800 text-sm font-medium">This action writes to both upstream systems and cannot be undone automatically.</p>
        <label className="flex items-center gap-2 mt-3 cursor-pointer">
          <input
            type="checkbox"
            checked={confirmed}
            onChange={e => setConfirmed(e.target.checked)}
            className="w-4 h-4 rounded border-gray-300 text-indigo-600"
          />
          <span className="text-sm text-amber-800">I understand and want to proceed</span>
        </label>
      </div>

      {err && <p className="text-sm text-red-600">{err}</p>}

      <div className="flex justify-between">
        <button onClick={prev} className="px-5 py-2 bg-gray-100 text-gray-700 rounded text-sm font-medium hover:bg-gray-200">
          ← Back
        </button>
        <button
          onClick={handleExecute}
          disabled={!confirmed || executing}
          className="px-6 py-2 bg-red-600 text-white rounded text-sm font-medium hover:bg-red-700 disabled:opacity-40"
        >
          {executing ? 'Executing…' : 'Execute sync'}
        </button>
      </div>
    </div>
  )
}
