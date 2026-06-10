import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getSyncStatus, triggerSync, triggerDryRun, setAutoSync } from '../api/client'
import { usePoll } from '../api/hooks'
import { SystemStatusBadge } from '../components/StatusBadge'
import { DeepLinks } from '../components/DeepLinks'
import { BackupSafetyDialog } from '../components/BackupSafetyDialog'
import type { CycleResultResponse, SyncPreviewEntry } from '../api/types'
import { formatLocal } from '../utils/datetime'

function PreviewRow({ entry, muted = false }: { entry: SyncPreviewEntry; muted?: boolean }) {
  return (
    <li className={`px-3 py-1.5 flex items-start gap-2 text-xs ${muted ? 'text-gray-400 dark:text-gray-500' : 'text-gray-600 dark:text-gray-300'}`}>
      <span className="shrink-0 mt-0.5">
        <DeepLinks
          filamentdbFilamentId={entry.fdb_filament_id}
          spoolmanSpoolId={entry.spoolman_id}
        />
      </span>
      <span className="grow min-w-0">
        {muted ? (
          <>
            <span className="font-medium text-gray-400 dark:text-gray-500">{entry.label}</span>
            <span className="ml-1.5 text-gray-300 dark:text-gray-600 italic">Matched — no updates</span>
          </>
        ) : (
          <>
            <span className="font-medium">{entry.label}</span>
            {entry.direction && (
              <span className="ml-1.5 text-gray-400 dark:text-gray-500">
                {entry.direction === 'spoolman_to_filamentdb' ? 'SM→FDB' : 'FDB→SM'}
              </span>
            )}
            {entry.field && (
              <span className="ml-1.5 text-indigo-600 dark:text-indigo-400">{entry.field}</span>
            )}
            {entry.old != null && entry.new != null && (
              <span className="ml-1.5 text-gray-500 dark:text-gray-400">
                {String(entry.old)} → {String(entry.new)}
              </span>
            )}
            {entry.reason && (
              <span className="ml-1.5 text-gray-400 dark:text-gray-500 italic">{entry.reason}</span>
            )}
          </>
        )}
      </span>
    </li>
  )
}

export default function Dashboard() {
  const { data, loading, error, reload } = usePoll(getSyncStatus, 15_000)
  const [syncing, setSyncing] = useState(false)
  const [syncResult, setSyncResult] = useState<CycleResultResponse | null>(null)
  const [syncError, setSyncError] = useState<string | null>(null)
  const [togglingAuto, setTogglingAuto] = useState(false)
  const [showMatched, setShowMatched] = useState(true)
  const [showAutoSyncBackupDialog, setShowAutoSyncBackupDialog] = useState(false)
  const navigate = useNavigate()

  async function handleManualSync() {
    setSyncing(true)
    setSyncResult(null)
    setSyncError(null)
    try {
      const result = await triggerSync()
      setSyncResult(result)
      void reload()
    } catch (e) {
      setSyncError(e instanceof Error ? e.message : String(e))
    } finally {
      setSyncing(false)
    }
  }

  async function handleDryRun() {
    setSyncing(true)
    setSyncResult(null)
    setSyncError(null)
    try {
      const result = await triggerDryRun()
      setSyncResult(result)
    } catch (e) {
      setSyncError(e instanceof Error ? e.message : String(e))
    } finally {
      setSyncing(false)
    }
  }

  async function doEnableAutoSync() {
    setTogglingAuto(true)
    try {
      await setAutoSync({ enabled: true })
      void reload()
    } catch (e) {
      console.error(e)
    } finally {
      setTogglingAuto(false)
    }
  }

  async function handleAutoSyncToggle() {
    if (!data) return
    if (data.auto_sync_enabled) {
      // Disabling is not gated — run immediately
      setTogglingAuto(true)
      try {
        await setAutoSync({ enabled: false })
        void reload()
      } catch (e) {
        console.error(e)
      } finally {
        setTogglingAuto(false)
      }
    } else {
      // Enabling is gated behind the backup safety dialog
      setShowAutoSyncBackupDialog(true)
    }
  }

  if (loading && !data) {
    return <div className="p-8 text-gray-500 dark:text-gray-400">Loading…</div>
  }

  if (error && !data) {
    return (
      <div className="p-8">
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded p-4 text-red-700 dark:text-red-400">
          <p className="font-medium">Could not reach the bridge API</p>
          <p className="text-sm mt-1">{error}</p>
        </div>
      </div>
    )
  }

  const counts = data?.counts ?? {}

  return (
    <>
    <BackupSafetyDialog
      open={showAutoSyncBackupDialog}
      actionLabel="Enable auto-sync"
      onCancel={() => setShowAutoSyncBackupDialog(false)}
      onProceed={() => { setShowAutoSyncBackupDialog(false); void doEnableAutoSync() }}
    />
    <div className="p-8 space-y-6 max-w-4xl">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Dashboard</h1>
        {!data?.wizard_completed && (
          <button
            onClick={() => navigate('/wizard')}
            className="px-4 py-2 bg-indigo-600 text-white rounded text-sm font-medium hover:bg-indigo-700"
          >
            Run setup wizard
          </button>
        )}
      </div>

      {/* Sync state */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {[
          { label: 'In Sync', value: counts['in_sync'] ?? 0, color: 'text-green-600 dark:text-green-400' },
          { label: 'Pending', value: counts['pending'] ?? 0, color: 'text-yellow-600 dark:text-yellow-400' },
          { label: 'Conflicts', value: counts['conflict'] ?? 0, color: 'text-red-600 dark:text-red-400' },
          { label: 'Unlinked', value: counts['unlinked'] ?? 0, color: 'text-gray-500 dark:text-gray-400' },
        ].map(c => (
          <div key={c.label} className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
            <p className="text-sm text-gray-500 dark:text-gray-400">{c.label}</p>
            <p className={`text-3xl font-bold mt-1 ${c.color}`}>{c.value}</p>
          </div>
        ))}
      </div>

      {/* Sync timing + controls */}
      <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-5 space-y-4">
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <span className="text-gray-500 dark:text-gray-400">Last sync</span>
            <p className="font-medium text-gray-900 dark:text-gray-100">{formatLocal(data?.last_sync_at)}</p>
          </div>
          <div>
            <span className="text-gray-500 dark:text-gray-400">Next sync</span>
            <p className="font-medium text-gray-900 dark:text-gray-100">{formatLocal(data?.next_sync_at)}</p>
          </div>
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          <button
            onClick={handleManualSync}
            disabled={syncing}
            className="px-4 py-2 bg-indigo-600 text-white rounded text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
          >
            {syncing ? 'Syncing…' : 'Sync now'}
          </button>
          <button
            onClick={handleDryRun}
            disabled={syncing}
            className="px-4 py-2 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 rounded text-sm font-medium hover:bg-gray-200 dark:hover:bg-gray-600 disabled:opacity-50"
          >
            Dry run
          </button>
          <button
            onClick={handleAutoSyncToggle}
            disabled={togglingAuto}
            className={`px-4 py-2 rounded text-sm font-medium transition-colors ${
              data?.auto_sync_enabled
                ? 'bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-300 hover:bg-green-200 dark:hover:bg-green-900/50'
                : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
            }`}
          >
            Auto-sync: {data?.auto_sync_enabled ? 'ON' : 'OFF'}
          </button>
        </div>

        {syncError && (
          <p className="text-sm text-red-600 dark:text-red-400">{syncError}</p>
        )}

        {syncResult && (
          <div className={`rounded p-3 text-sm ${
            syncResult.dry_run
              ? 'bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800'
              : 'bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800'
          }`}>
            <p className="font-medium mb-1 text-gray-900 dark:text-gray-100">
              {syncResult.dry_run ? 'Dry run preview' : 'Sync complete'}
            </p>
            <div className="flex gap-4 text-xs text-gray-600 dark:text-gray-400 flex-wrap">
              <span>Created: {syncResult.created}</span>
              <span>Updated: {syncResult.updated}</span>
              <span>Conflicts: {syncResult.conflicts}</span>
              <span>Skipped: {syncResult.skipped}</span>
              {syncResult.dry_run && (() => {
                const matchedCount = syncResult.preview.filter(p => p.action === 'matched').length
                return matchedCount > 0 ? <span className="text-gray-400 dark:text-gray-500">Matched: {matchedCount}</span> : null
              })()}
              {syncResult.errors > 0 && <span className="text-red-600 dark:text-red-400">Errors: {syncResult.errors}</span>}
            </div>
            {syncResult.dry_run && syncResult.preview.some(p => p.action === 'create' || p.action === 'update') && (
              <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
                Created and matched (Updated) items are applied by the{' '}
                <button onClick={() => navigate('/wizard')} className="underline hover:text-gray-700 dark:hover:text-gray-300">
                  initial-sync wizard
                </button>
                , not by &ldquo;Sync now&rdquo;.
              </p>
            )}
            {syncResult.dry_run && syncResult.preview.length > 0 && (
              <div className="mt-3 space-y-1">
                {(['create', 'update', 'conflict', 'skip'] as const).map(action => {
                  const entries = syncResult.preview.filter(p => p.action === action)
                  if (entries.length === 0) return null
                  const sectionLabel = { create: 'Created', update: 'Updated', conflict: 'Conflicts', skip: 'Skipped' }[action]
                  return (
                    <details key={action} className="rounded border border-yellow-200 dark:border-yellow-800 bg-white dark:bg-gray-800">
                      <summary className="px-3 py-1.5 cursor-pointer text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 select-none">
                        {sectionLabel} ({entries.length})
                      </summary>
                      <ul className="divide-y divide-gray-100 dark:divide-gray-700">
                        {entries.map((entry, i) => (
                          <PreviewRow key={i} entry={entry} />
                        ))}
                      </ul>
                    </details>
                  )
                })}
                {(() => {
                  const matchedEntries = syncResult.preview.filter(p => p.action === 'matched')
                  if (matchedEntries.length === 0) return null
                  return (
                    <div className="rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
                      <div className="px-3 py-1.5 flex items-center justify-between">
                        <span className="text-xs font-medium text-gray-500 dark:text-gray-400">
                          Matched — no updates ({matchedEntries.length})
                        </span>
                        <button
                          onClick={() => setShowMatched(v => !v)}
                          className="text-xs text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 underline"
                        >
                          {showMatched ? 'Hide' : 'Show'}
                        </button>
                      </div>
                      {showMatched && (
                        <ul className="divide-y divide-gray-100 dark:divide-gray-700">
                          {matchedEntries.map((entry, i) => (
                            <PreviewRow key={i} entry={entry} muted />
                          ))}
                        </ul>
                      )}
                    </div>
                  )
                })()}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Systems */}
      {data?.systems && (
        <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-5">
          <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">Connected systems</h2>
          <div className="space-y-3">
            {Object.entries(data.systems).map(([name, sys]) => (
              <div key={name}>
                <div className="flex items-center justify-between">
                  <div>
                    <span className="font-medium text-sm capitalize text-gray-900 dark:text-gray-100">{name}</span>
                    <span className="ml-2 text-xs text-gray-400 dark:text-gray-500">{sys.url}</span>
                    {sys.version && <span className="ml-2 text-xs text-gray-400 dark:text-gray-500">v{sys.version}</span>}
                    {sys.error && <span className="ml-2 text-xs text-red-500 dark:text-red-400">{sys.error}</span>}
                  </div>
                  <div className="flex items-center gap-3 text-xs text-gray-500 dark:text-gray-400">
                    {Object.entries(sys.counts).map(([k, v]) => (
                      <span key={k}>{k}: {v}</span>
                    ))}
                    <SystemStatusBadge status={sys.status} />
                  </div>
                </div>
                {sys.warnings?.map(w => (
                  <p key={w} className="mt-1 text-xs text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded px-2 py-1">
                    ⚠️ {w}
                  </p>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}

      {data?.pending_conflicts != null && data.pending_conflicts > 0 && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded p-4 flex items-center justify-between">
          <p className="text-red-700 dark:text-red-400 text-sm font-medium">
            {data.pending_conflicts} open conflict{data.pending_conflicts !== 1 ? 's' : ''} need resolution
          </p>
          <button
            onClick={() => navigate('/conflicts')}
            className="text-sm text-red-600 dark:text-red-400 underline hover:text-red-800 dark:hover:text-red-300"
          >
            Resolve
          </button>
        </div>
      )}
    </div>
    </>
  )
}
