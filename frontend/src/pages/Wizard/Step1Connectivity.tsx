import { getWizardConnectivity } from '../../api/client'
import { useApi } from '../../api/hooks'
import { SystemStatusBadge } from '../../components/StatusBadge'
import type { WizardCtx } from './index'

export default function Step1Connectivity({ next }: WizardCtx) {
  const { data, loading, error } = useApi(getWizardConnectivity)

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-gray-800">Connectivity check</h2>
        <p className="text-sm text-gray-500 mt-1">
          Both systems must be reachable before proceeding.
        </p>
      </div>

      {loading && <p className="text-gray-500">Checking…</p>}
      {error && <p className="text-red-600">{error}</p>}

      {data && (
        <>
          <div className="bg-white rounded-lg border border-gray-200 divide-y divide-gray-100">
            {Object.entries(data.systems).map(([name, sys]) => (
              <div key={name} className="px-5 py-4 flex items-center justify-between">
                <div>
                  <p className="font-medium text-gray-800 capitalize">{name}</p>
                  <p className="text-xs text-gray-400">{sys.url}</p>
                  {sys.version && <p className="text-xs text-gray-400">v{sys.version}</p>}
                  {sys.error && <p className="text-xs text-red-500 mt-1">{sys.error}</p>}
                  <div className="flex gap-3 mt-1">
                    {Object.entries(sys.counts).map(([k, v]) => (
                      <span key={k} className="text-xs text-gray-500">{k}: {v}</span>
                    ))}
                  </div>
                </div>
                <SystemStatusBadge status={sys.status} />
              </div>
            ))}
          </div>

          {data.blocked ? (
            <div className="bg-red-50 border border-red-200 rounded p-4">
              <p className="text-red-700 font-medium text-sm">
                One or more systems are unreachable. Fix connectivity before continuing.
              </p>
            </div>
          ) : (
            <div className="bg-green-50 border border-green-200 rounded p-4">
              <p className="text-green-700 text-sm">All systems reachable. Ready to continue.</p>
            </div>
          )}

          <div className="flex justify-end">
            <button
              onClick={next}
              disabled={data.blocked}
              className="px-5 py-2 bg-indigo-600 text-white rounded text-sm font-medium hover:bg-indigo-700 disabled:opacity-40"
            >
              Next →
            </button>
          </div>
        </>
      )}
    </div>
  )
}
