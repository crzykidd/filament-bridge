import { DeepLinks } from './DeepLinks'
import type { WizardExecuteRecord } from '../api/types'

const ACTION_COLORS: Record<string, string> = {
  created: 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400',
  updated: 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400',
  skipped: 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300',
  failed:  'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400',
}

export function RecordLabel({ rec }: { rec: WizardExecuteRecord }) {
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

interface WizardRunReportProps {
  records: WizardExecuteRecord[]
  created: number
  updated: number
  skipped: number
  failed: number
  /** Show the flat summary counter tiles. Default true; callers that render their own
   *  (richer) counters pass false to avoid a duplicate row. */
  showCounters?: boolean
}

/** Renders a wizard execute result with failures first (red banner), then a table of succeeded records. */
export function WizardRunReport({ records, created, updated, skipped, failed, showCounters = true }: WizardRunReportProps) {
  const failedRecs  = records.filter(r => r.action === 'failed')
  const succeededRecs = records.filter(r => r.action !== 'failed')
  const createdRecs = records.filter(r => r.action === 'created')
  const updatedRecs = records.filter(r => r.action === 'updated')
  const skippedRecs = records.filter(r => r.action === 'skipped')

  return (
    <div className="space-y-5">
      {/* Summary counters */}
      {showCounters && (
        <div className="grid grid-cols-4 gap-3">
          {[
            { label: 'Created', value: created, color: 'text-green-600 dark:text-green-400' },
            { label: 'Updated', value: updated, color: 'text-blue-600 dark:text-blue-400' },
            { label: 'Skipped', value: skipped, color: 'text-gray-500 dark:text-gray-400' },
            { label: 'Failed',  value: failed,  color: 'text-red-600 dark:text-red-400' },
          ].map(c => (
            <div key={c.label} className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-3 text-center">
              <p className="text-xs text-gray-500 dark:text-gray-400">{c.label}</p>
              <p className={`text-2xl font-bold ${c.color}`}>{c.value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Failures — always visible, impossible to miss */}
      {failedRecs.length > 0 && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-300 dark:border-red-700 rounded-lg p-4 space-y-3">
          <h3 className="text-sm font-semibold text-red-700 dark:text-red-400">
            Failed ({failedRecs.length}) — these records were not imported
          </h3>
          <ul className="space-y-2">
            {failedRecs.map((rec, i) => (
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
      {succeededRecs.length > 0 && (
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
              {[...createdRecs, ...updatedRecs, ...skippedRecs].map((rec, i) => (
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
