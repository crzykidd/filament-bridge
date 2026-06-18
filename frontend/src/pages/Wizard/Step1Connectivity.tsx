import { getWizardConnectivity } from '../../api/client'
import { useApi } from '../../api/hooks'
import { WizardActionBar } from '../../components/WizardActionBar'
import { SystemStatusBadge } from '../../components/StatusBadge'
import type { WizardCtx } from './index'

export default function Step1Connectivity({ next }: WizardCtx) {
  const { data, loading, error } = useApi(getWizardConnectivity)

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-200">Connectivity check</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
          Both systems must be reachable before proceeding.
        </p>
      </div>

      {loading && <p className="text-gray-500 dark:text-gray-400">Checking…</p>}
      {error && <p className="text-red-600 dark:text-red-400">{error}</p>}

      {data && (
        <>
          {/* Top action bar */}
          <WizardActionBar onNext={next} nextDisabled={data.blocked} />

          <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 divide-y divide-gray-100 dark:divide-gray-700">
            {Object.entries(data.systems).map(([name, sys]) => (
              <div key={name} className="px-5 py-4 flex items-center justify-between">
                <div>
                  <p className="font-medium text-gray-800 dark:text-gray-200 capitalize">{name}</p>
                  <p className="text-xs text-gray-400 dark:text-gray-500">{sys.url}</p>
                  {sys.version && <p className="text-xs text-gray-400 dark:text-gray-500">v{sys.version}</p>}
                  {sys.error && <p className="text-xs text-red-500 dark:text-red-400 mt-1">{sys.error}</p>}
                  <div className="flex gap-3 mt-1">
                    {Object.entries(sys.counts).map(([k, v]) => (
                      <span key={k} className="text-xs text-gray-500 dark:text-gray-400">{k}: {v}</span>
                    ))}
                  </div>
                  {sys.warnings?.map(w => (
                    <p key={w} className="text-xs text-amber-700 dark:text-amber-400 mt-1">⚠️ {w}</p>
                  ))}
                </div>
                <SystemStatusBadge status={sys.status} />
              </div>
            ))}
          </div>

          {data.blocked ? (
            <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded p-4">
              <p className="text-red-700 dark:text-red-400 font-medium text-sm">
                One or more systems are unreachable. Fix connectivity before continuing.
              </p>
            </div>
          ) : (
            <div className="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded p-4">
              <p className="text-green-700 dark:text-green-400 text-sm">All systems reachable. Ready to continue.</p>
            </div>
          )}

          {/* Bottom action bar */}
          <WizardActionBar onNext={next} nextDisabled={data.blocked} />
        </>
      )}
    </div>
  )
}
