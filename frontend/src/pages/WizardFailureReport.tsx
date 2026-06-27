import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getWizardLastRun } from '../api/client'
import { WizardRunReport } from '../components/WizardRunReport'
import type { WizardLastRunResponse } from '../api/types'
import { formatLocal } from '../utils/datetime'

export default function WizardFailureReport() {
  const navigate = useNavigate()
  const [data, setData] = useState<WizardLastRunResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getWizardLastRun()
      .then(r => setData(r))
      .catch(e => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="p-8 space-y-6 max-w-4xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Wizard Import Report</h1>
          {data && (
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
              Direction: {data.direction.replace(/_/g, ' ')} ·
              Run at: {formatLocal(data.at)} ·
              Completed: {data.completed ? 'Yes' : 'No'}
            </p>
          )}
        </div>
        <button
          onClick={() => navigate('/wizard')}
          className="px-4 py-2 bg-indigo-600 text-white rounded text-sm font-medium hover:bg-indigo-700"
        >
          Re-run wizard
        </button>
      </div>

      {loading && (
        <p className="text-sm text-gray-500 dark:text-gray-400">Loading report…</p>
      )}

      {error && (
        <div className="rounded-lg border border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-900/20 px-4 py-3">
          <p className="text-sm text-red-700 dark:text-red-300">Failed to load report: {error}</p>
        </div>
      )}

      {!loading && !error && !data && (
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-8 text-center">
          <p className="text-gray-500 dark:text-gray-400">No wizard run recorded yet.</p>
          <button
            onClick={() => navigate('/wizard')}
            className="mt-4 px-4 py-2 bg-indigo-600 text-white rounded text-sm font-medium hover:bg-indigo-700"
          >
            Run wizard
          </button>
        </div>
      )}

      {data && (
        <>
          {data.failed > 0 && (
            <div className="rounded-lg border border-amber-200 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/20 px-4 py-3">
              <p className="text-sm text-amber-800 dark:text-amber-300">
                {data.failed} record{data.failed !== 1 ? 's' : ''} failed to import.
                Re-running the wizard retries failed records — already-imported records will be skipped (idempotent).
              </p>
            </div>
          )}
          <WizardRunReport
            records={data.records}
            created={data.created}
            updated={data.updated}
            skipped={data.skipped}
            failed={data.failed}
          />
        </>
      )}
    </div>
  )
}
