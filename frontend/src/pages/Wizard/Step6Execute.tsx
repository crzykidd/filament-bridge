import { useState } from 'react'
import { postWizardExecute } from '../../api/client'
import { DeepLinks } from '../../components/DeepLinks'
import { BackupSafetyDialog } from '../../components/BackupSafetyDialog'
import { HelpTip } from '../../components/HelpTip'
import type { WizardExecuteResponse, WizardExecuteRecord } from '../../api/types'
import type { WizardCtx } from './index'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const ACTION_COLORS: Record<string, string> = {
  created: 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400',
  updated: 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400',
  skipped: 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300',
  failed:  'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400',
}

function RecordLabel({ rec }: { rec: WizardExecuteRecord }) {
  // Fall back to a synthetic label from IDs when no human-readable label is present.
  const text =
    rec.label ||
    (rec.spoolman_spool_id != null
      ? `Spool #${rec.spoolman_spool_id}`
      : rec.spoolman_filament_id != null
      ? `SM Filament #${rec.spoolman_filament_id}`
      : rec.filamentdb_spool_id != null
      ? `FDB Spool ${rec.filamentdb_spool_id}`
      : rec.filamentdb_filament_id != null
      ? `FDB Filament ${rec.filamentdb_filament_id}`
      : '—')
  return <span className="font-medium">{text}</span>
}

// ---------------------------------------------------------------------------
// Result view
// ---------------------------------------------------------------------------

function ExecuteResultView({ result }: { result: WizardExecuteResponse }) {
  const failed  = result.records.filter(r => r.action === 'failed')
  const created = result.records.filter(r => r.action === 'created')
  const updated = result.records.filter(r => r.action === 'updated')
  const skipped = result.records.filter(r => r.action === 'skipped')

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-200">Execute complete</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
          Direction: {result.direction.replace(/_/g, ' ')} ·
          Wizard completed: {result.wizard_completed ? 'Yes' : 'No'}
        </p>
      </div>

      {/* Summary counters */}
      <div className="grid grid-cols-4 gap-3">
        {[
          {
            label: 'Created',
            value: result.created,
            color: 'text-green-600 dark:text-green-400',
            filaments: result.created_filaments,
            spools: result.created_spools,
          },
          {
            label: 'Updated',
            value: result.updated,
            color: 'text-blue-600 dark:text-blue-400',
            filaments: result.updated_filaments,
            spools: result.updated_spools,
          },
          {
            label: 'Skipped',
            value: result.skipped,
            color: 'text-gray-500 dark:text-gray-400',
            filaments: result.skipped_filaments,
            spools: result.skipped_spools,
          },
          {
            label: 'Failed',
            value: result.failed,
            color: 'text-red-600 dark:text-red-400',
            filaments: result.failed_filaments,
            spools: result.failed_spools,
          },
        ].map(c => (
          <div key={c.label} className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-3 text-center">
            <p className="text-xs text-gray-500 dark:text-gray-400">{c.label}</p>
            <p className={`text-2xl font-bold ${c.color}`}>{c.value}</p>
            {c.value > 0 && (
              <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">
                {c.filaments}f / {c.spools}s
              </p>
            )}
          </div>
        ))}
      </div>

      {/* Failures — always visible, impossible to miss */}
      {failed.length > 0 && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-300 dark:border-red-700 rounded-lg p-4 space-y-3">
          <h3 className="text-sm font-semibold text-red-700 dark:text-red-400">
            Failed ({failed.length}) — these records were not imported
          </h3>
          <ul className="space-y-2">
            {failed.map((rec, i) => (
              <li key={i} className="flex items-start gap-3 text-sm">
                <span className="mt-0.5 shrink-0">
                  <span className={`inline-flex px-1.5 py-0.5 rounded text-xs font-medium ${ACTION_COLORS.failed}`}>
                    {rec.entity_type}
                  </span>
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-red-700 dark:text-red-300">
                    <RecordLabel rec={rec} />
                  </div>
                  <div className="text-red-600 dark:text-red-400 text-xs mt-0.5 break-words">
                    {rec.error ?? rec.detail ?? 'Unknown error'}
                  </div>
                </div>
                <div className="shrink-0">
                  <DeepLinks
                    filamentdbFilamentId={rec.filamentdb_filament_id}
                    spoolmanSpoolId={rec.spoolman_spool_id}
                    spoolmanFilamentId={rec.spoolman_filament_id}
                  />
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Full per-record table (created + updated + skipped) */}
      {(created.length > 0 || updated.length > 0 || skipped.length > 0) && (
        <div className="overflow-x-auto bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
          <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700 text-sm">
            <thead className="bg-gray-50 dark:bg-gray-750">
              <tr>
                {['Type', 'Action', 'Record', 'Detail', 'Links'].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
              {[...created, ...updated, ...skipped].map((rec, i) => (
                <tr key={i} className="hover:bg-gray-50 dark:hover:bg-gray-750">
                  <td className="px-4 py-2 text-gray-600 dark:text-gray-300 text-xs">{rec.entity_type}</td>
                  <td className="px-4 py-2">
                    <span className={`inline-flex px-1.5 py-0.5 rounded text-xs font-medium ${ACTION_COLORS[rec.action] ?? ''}`}>
                      {rec.action}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-xs text-gray-700 dark:text-gray-300">
                    <RecordLabel rec={rec} />
                  </td>
                  <td className="px-4 py-2 text-xs text-gray-600 dark:text-gray-300">
                    {rec.detail ?? '—'}
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
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function Step6Execute({ prev, tareOverrides }: WizardCtx) {
  const [confirmed, setConfirmed] = useState(false)
  const [executing, setExecuting] = useState(false)
  const [result, setResult] = useState<WizardExecuteResponse | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [showBackupDialog, setShowBackupDialog] = useState(false)

  async function runExecute() {
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

  function handleExecute() {
    setShowBackupDialog(true)
  }

  if (result) {
    return <ExecuteResultView result={result} />
  }

  return (
    <>
      <BackupSafetyDialog
        open={showBackupDialog}
        actionLabel="Run initial sync"
        onCancel={() => setShowBackupDialog(false)}
        onProceed={() => { setShowBackupDialog(false); void runExecute() }}
      />

      <div className="space-y-5">
        <div>
          <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-200">Execute initial sync</h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            This will write to both Spoolman and Filament DB. Review your choices before proceeding.
          </p>
          {tareOverrides.length > 0 && (
            <p className="flex items-center text-sm text-gray-500 dark:text-gray-400 mt-1">
              {tareOverrides.length} tare override{tareOverrides.length !== 1 ? 's' : ''} applied.
              <HelpTip text="Tare values you set in Variances; submitted with this run only." />
            </p>
          )}
        </div>

        <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded p-4">
          <p className="text-amber-800 dark:text-amber-300 text-sm font-medium">This action writes to both upstream systems and cannot be undone automatically.</p>
          <label className="flex items-center gap-2 mt-3 cursor-pointer">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={e => setConfirmed(e.target.checked)}
              className="w-4 h-4 rounded border-gray-300 dark:border-gray-600 text-indigo-600"
            />
            <span className="text-sm text-amber-800 dark:text-amber-300">I understand and want to proceed</span>
          </label>
        </div>

        {err && <p className="text-sm text-red-600 dark:text-red-400">{err}</p>}

        <div className="flex justify-between">
          <button onClick={prev} className="px-5 py-2 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 rounded text-sm font-medium hover:bg-gray-200 dark:hover:bg-gray-600">
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
    </>
  )
}
