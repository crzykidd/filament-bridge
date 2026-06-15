/**
 * BackupSafetyDialog — pre-write safety gate.
 *
 * Shows before any destructive action that writes to Spoolman or Filament DB.
 * The user can trigger a server-side backup of both systems in one click.
 * The Proceed button is disabled until EITHER backup succeeds OR the
 * acknowledgment checkbox is checked.
 */

import { useState } from 'react'
import { backupFilamentDb, backupSpoolman } from '../api/client'

interface BackupSafetyDialogProps {
  open: boolean
  actionLabel: string
  onCancel: () => void
  onProceed: () => void
}

const MONGODUMP_CMD =
  'docker exec <mongo-container> mongodump --archive=/data/db/fdb-$(date +%F).archive'

type BackupState = 'idle' | 'loading' | 'ok' | 'error'

export function BackupSafetyDialog({
  open,
  actionLabel,
  onCancel,
  onProceed,
}: BackupSafetyDialogProps) {
  const [smState, setSmState] = useState<BackupState>('idle')
  const [smDetail, setSmDetail] = useState<string>('')
  const [fdbState, setFdbState] = useState<BackupState>('idle')
  const [fdbDetail, setFdbDetail] = useState<string>('')
  const [acknowledged, setAcknowledged] = useState(false)
  const [copyDone, setCopyDone] = useState(false)

  if (!open) return null

  const canProceed = smState === 'ok' || fdbState === 'ok' || acknowledged

  async function handleBackupSpoolman() {
    setSmState('loading')
    setSmDetail('')
    try {
      const res = await backupSpoolman()
      if (res.success) {
        setSmState('ok')
        setSmDetail(res.detail)
      } else {
        setSmState('error')
        setSmDetail(res.detail)
      }
    } catch (e: unknown) {
      setSmState('error')
      setSmDetail(e instanceof Error ? e.message : String(e))
    }
  }

  async function handleBackupFilamentDb() {
    setFdbState('loading')
    setFdbDetail('')
    try {
      const res = await backupFilamentDb()
      if (res.success) {
        setFdbState('ok')
        setFdbDetail(res.detail)
      } else {
        setFdbState('error')
        setFdbDetail(res.detail)
      }
    } catch (e: unknown) {
      setFdbState('error')
      setFdbDetail(e instanceof Error ? e.message : String(e))
    }
  }

  function handleCopy() {
    void navigator.clipboard.writeText(MONGODUMP_CMD).then(() => {
      setCopyDone(true)
      setTimeout(() => setCopyDone(false), 2000)
    })
  }

  function handleProceed() {
    onProceed()
    setSmState('idle')
    setSmDetail('')
    setFdbState('idle')
    setFdbDetail('')
    setAcknowledged(false)
    setCopyDone(false)
  }

  function handleCancel() {
    onCancel()
    setSmState('idle')
    setSmDetail('')
    setFdbState('idle')
    setFdbDetail('')
    setAcknowledged(false)
    setCopyDone(false)
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      role="dialog"
      aria-modal="true"
      aria-labelledby="backup-dialog-title"
    >
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl w-full max-w-lg mx-4 overflow-hidden">
        {/* Header */}
        <div className="px-6 pt-5 pb-4 border-b border-gray-200 dark:border-gray-700">
          <h2 id="backup-dialog-title" className="text-lg font-semibold text-gray-900 dark:text-gray-100">
            Back up before you continue
          </h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            <strong className="text-amber-700 dark:text-amber-400">Beta feature:</strong> this action writes to
            Spoolman and Filament DB. We recommend backing up both systems first.
          </p>
        </div>

        {/* Body */}
        <div className="px-6 py-5 space-y-5">
          {/* Spoolman backup */}
          <div className="space-y-2">
            <p className="text-sm font-medium text-gray-800 dark:text-gray-200">Spoolman</p>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Triggers a server-side backup on your Spoolman instance. The archive is written
              into Spoolman's own data volume — the bridge does not store it.
            </p>
            <div className="flex items-center gap-3 flex-wrap">
              <button
                type="button"
                onClick={() => void handleBackupSpoolman()}
                disabled={smState === 'loading' || smState === 'ok'}
                className="px-4 py-2 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {smState === 'loading' ? (
                  <span className="flex items-center gap-2">
                    <svg className="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                    </svg>
                    Backing up…
                  </span>
                ) : (
                  'Back up Spoolman now'
                )}
              </button>

              {smState === 'ok' && (
                <span className="text-sm text-green-700 dark:text-green-400 flex items-center gap-1">
                  <svg className="w-4 h-4 shrink-0" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                  </svg>
                  Spoolman backed up
                  {smDetail && (
                    <span className="text-xs text-gray-500 dark:text-gray-400 font-mono truncate max-w-[200px]" title={smDetail}>
                      — {smDetail}
                    </span>
                  )}
                </span>
              )}

              {smState === 'error' && (
                <span className="text-sm text-red-600 dark:text-red-400 flex items-center gap-1">
                  <svg className="w-4 h-4 shrink-0" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm-1-11a1 1 0 112 0v4a1 1 0 11-2 0V7zm0 6a1 1 0 112 0 1 1 0 01-2 0z" clipRule="evenodd" />
                  </svg>
                  {smDetail || 'Backup failed'}
                </span>
              )}
            </div>
          </div>

          {/* FDB backup */}
          <div className="space-y-2">
            <p className="text-sm font-medium text-gray-800 dark:text-gray-200">Filament DB</p>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Downloads a full JSON snapshot from Filament DB (<code className="bg-gray-100 dark:bg-gray-700 px-1 rounded">GET /api/snapshot</code>) and
              saves it to the bridge's data volume. The file persists as long as your bridge
              volume is mounted.
            </p>
            <div className="flex items-center gap-3 flex-wrap">
              <button
                type="button"
                onClick={() => void handleBackupFilamentDb()}
                disabled={fdbState === 'loading' || fdbState === 'ok'}
                className="px-4 py-2 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {fdbState === 'loading' ? (
                  <span className="flex items-center gap-2">
                    <svg className="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                    </svg>
                    Backing up…
                  </span>
                ) : (
                  'Back up Filament DB now'
                )}
              </button>

              {fdbState === 'ok' && (
                <span className="text-sm text-green-700 dark:text-green-400 flex items-center gap-1">
                  <svg className="w-4 h-4 shrink-0" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                  </svg>
                  Filament DB backed up
                  {fdbDetail && (
                    <span className="text-xs text-gray-500 dark:text-gray-400 font-mono truncate max-w-[200px]" title={fdbDetail}>
                      — {fdbDetail}
                    </span>
                  )}
                </span>
              )}

              {fdbState === 'error' && (
                <span className="text-sm text-red-600 dark:text-red-400 flex items-center gap-1">
                  <svg className="w-4 h-4 shrink-0" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm-1-11a1 1 0 112 0v4a1 1 0 11-2 0V7zm0 6a1 1 0 112 0 1 1 0 01-2 0z" clipRule="evenodd" />
                  </svg>
                  {fdbDetail || 'Backup failed'}
                </span>
              )}
            </div>
            <p className="text-xs text-gray-400 dark:text-gray-500">
              Or back up the raw MongoDB volume:{' '}
              <code className="bg-gray-100 dark:bg-gray-700 px-1 rounded text-gray-500 dark:text-gray-400">{MONGODUMP_CMD}</code>
              {' '}
              <button
                type="button"
                onClick={handleCopy}
                className="text-xs border border-gray-300 dark:border-gray-600 rounded px-1.5 py-0.5 hover:bg-gray-50 dark:hover:bg-gray-700 text-gray-500 dark:text-gray-400"
              >
                {copyDone ? 'Copied!' : 'Copy'}
              </button>
            </p>
          </div>

          {/* Acknowledgment */}
          <label className="flex items-start gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={e => setAcknowledged(e.target.checked)}
              className="mt-0.5 w-4 h-4 rounded border-gray-300 dark:border-gray-600 text-indigo-600 focus:ring-indigo-500"
            />
            <span className="text-sm text-gray-700 dark:text-gray-300">
              I've backed up my data (or accept the risk)
            </span>
          </label>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex justify-end gap-3">
          <button
            type="button"
            onClick={handleCancel}
            className="px-4 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded hover:bg-gray-50 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleProceed}
            disabled={!canProceed}
            className="px-5 py-2 text-sm bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-40 disabled:cursor-not-allowed font-medium"
          >
            Proceed — {actionLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
