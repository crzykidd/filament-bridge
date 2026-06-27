import { useState } from 'react'
import { postWizardExecute } from '../../api/client'
import { BackupSafetyDialog } from '../../components/BackupSafetyDialog'
import { HelpTip } from '../../components/HelpTip'
import { WizardActionBar } from '../../components/WizardActionBar'
import { WizardRunReport } from '../../components/WizardRunReport'
import type { WizardExecuteResponse } from '../../api/types'
import type { WizardCtx } from './index'

// ---------------------------------------------------------------------------
// Result view
// ---------------------------------------------------------------------------

function ExecuteResultView({ result }: { result: WizardExecuteResponse }) {
  // Per-type (filament/spool) counter breakdown — richer than the shared report's
  // flat counters, which is why we render our own here and pass showCounters={false}.
  const counters = [
    { label: 'Created', value: result.created, color: 'text-green-600 dark:text-green-400', filaments: result.created_filaments, spools: result.created_spools },
    { label: 'Updated', value: result.updated, color: 'text-blue-600 dark:text-blue-400', filaments: result.updated_filaments, spools: result.updated_spools },
    { label: 'Skipped', value: result.skipped, color: 'text-gray-500 dark:text-gray-400', filaments: result.skipped_filaments, spools: result.skipped_spools },
    { label: 'Failed',  value: result.failed,  color: 'text-red-600 dark:text-red-400',  filaments: result.failed_filaments,  spools: result.failed_spools },
  ]

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-200">Execute complete</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
          Direction: {result.direction.replace(/_/g, ' ')} ·
          Wizard completed: {result.wizard_completed ? 'Yes' : 'No'}
        </p>
      </div>

      {/* Summary counters with per-type (filament/spool) breakdown */}
      <div className="grid grid-cols-4 gap-3">
        {counters.map(c => (
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

      {/* Failures-first list + succeeded table (shared with the persistent Failure Report) */}
      <WizardRunReport
        records={result.records}
        created={result.created}
        updated={result.updated}
        skipped={result.skipped}
        failed={result.failed}
        showCounters={false}
      />
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

        {/* Top action bar — Execute button is red (destructive); passed via extra slot */}
        <WizardActionBar
          onBack={prev}
          extra={
            <button
              onClick={handleExecute}
              disabled={!confirmed || executing}
              className="px-6 py-2 bg-red-600 text-white rounded text-sm font-medium hover:bg-red-700 disabled:opacity-40"
            >
              {executing ? 'Executing…' : 'Execute sync'}
            </button>
          }
        />

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

        {/* Bottom action bar */}
        <WizardActionBar
          onBack={prev}
          extra={
            <button
              onClick={handleExecute}
              disabled={!confirmed || executing}
              className="px-6 py-2 bg-red-600 text-white rounded text-sm font-medium hover:bg-red-700 disabled:opacity-40"
            >
              {executing ? 'Executing…' : 'Execute sync'}
            </button>
          }
        />
      </div>
    </>
  )
}
