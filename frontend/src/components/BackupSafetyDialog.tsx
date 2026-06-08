/**
 * BackupSafetyDialog — pre-write safety gate.
 *
 * Shows before any destructive action that writes to Spoolman or Filament DB.
 * The user can trigger a server-side Spoolman backup in one click and is
 * reminded to run mongodump for Filament DB (no backup API available).
 * The Proceed button is disabled until EITHER the Spoolman backup succeeds OR
 * the acknowledgment checkbox is checked.
 */

import { useState } from 'react'
import { backupSpoolman } from '../api/client'

interface BackupSafetyDialogProps {
  open: boolean
  actionLabel: string
  onCancel: () => void
  onProceed: () => void
}

const MONGODUMP_CMD =
  'docker exec <mongo-container> mongodump --archive=/data/db/fdb-$(date +%F).archive'

export function BackupSafetyDialog({
  open,
  actionLabel,
  onCancel,
  onProceed,
}: BackupSafetyDialogProps) {
  const [backupState, setBackupState] = useState<'idle' | 'loading' | 'ok' | 'error'>('idle')
  const [backupDetail, setBackupDetail] = useState<string>('')
  const [acknowledged, setAcknowledged] = useState(false)
  const [copyDone, setCopyDone] = useState(false)

  if (!open) return null

  const canProceed = backupState === 'ok' || acknowledged

  async function handleBackup() {
    setBackupState('loading')
    setBackupDetail('')
    try {
      const res = await backupSpoolman()
      if (res.success) {
        setBackupState('ok')
        setBackupDetail(res.detail)
      } else {
        setBackupState('error')
        setBackupDetail(res.detail)
      }
    } catch (e: unknown) {
      setBackupState('error')
      setBackupDetail(e instanceof Error ? e.message : String(e))
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
    // Reset internal state for the next time the dialog opens
    setBackupState('idle')
    setBackupDetail('')
    setAcknowledged(false)
    setCopyDone(false)
  }

  function handleCancel() {
    onCancel()
    setBackupState('idle')
    setBackupDetail('')
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
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg mx-4 overflow-hidden">
        {/* Header */}
        <div className="px-6 pt-5 pb-4 border-b border-gray-200">
          <h2 id="backup-dialog-title" className="text-lg font-semibold text-gray-900">
            Back up before you continue
          </h2>
          <p className="text-sm text-gray-500 mt-1">
            <strong className="text-amber-700">Alpha feature:</strong> this action writes to
            Spoolman and Filament DB. We recommend backing up both systems first.
          </p>
        </div>

        {/* Body */}
        <div className="px-6 py-5 space-y-5">
          {/* Spoolman backup */}
          <div className="space-y-2">
            <p className="text-sm font-medium text-gray-800">Spoolman</p>
            <p className="text-xs text-gray-500">
              Triggers a server-side backup on your Spoolman instance. The archive is written
              into Spoolman's own data volume — the bridge does not store it.
            </p>
            <div className="flex items-center gap-3 flex-wrap">
              <button
                type="button"
                onClick={() => void handleBackup()}
                disabled={backupState === 'loading' || backupState === 'ok'}
                className="px-4 py-2 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {backupState === 'loading' ? (
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

              {backupState === 'ok' && (
                <span className="text-sm text-green-700 flex items-center gap-1">
                  <svg className="w-4 h-4 shrink-0" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                  </svg>
                  Spoolman backed up
                  {backupDetail && (
                    <span className="text-xs text-gray-500 font-mono truncate max-w-[200px]" title={backupDetail}>
                      — {backupDetail}
                    </span>
                  )}
                </span>
              )}

              {backupState === 'error' && (
                <span className="text-sm text-red-600 flex items-center gap-1">
                  <svg className="w-4 h-4 shrink-0" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm-1-11a1 1 0 112 0v4a1 1 0 11-2 0V7zm0 6a1 1 0 112 0 1 1 0 01-2 0z" clipRule="evenodd" />
                  </svg>
                  {backupDetail || 'Backup failed'}
                </span>
              )}
            </div>
          </div>

          {/* FDB backup reminder */}
          <div className="space-y-2">
            <p className="text-sm font-medium text-gray-800">Filament DB</p>
            <p className="text-xs text-gray-500">
              Filament DB has no backup API. Run mongodump manually — replace{' '}
              <code className="bg-gray-100 px-1 rounded">&lt;mongo-container&gt;</code> with your
              MongoDB container name.
            </p>
            <div className="flex items-center gap-2">
              <code className="flex-1 text-xs bg-gray-100 border border-gray-200 rounded px-3 py-2 font-mono text-gray-700 break-all">
                {MONGODUMP_CMD}
              </code>
              <button
                type="button"
                onClick={handleCopy}
                className="shrink-0 px-3 py-2 text-xs border border-gray-300 rounded hover:bg-gray-50 text-gray-600"
              >
                {copyDone ? 'Copied!' : 'Copy'}
              </button>
            </div>
          </div>

          {/* Acknowledgment */}
          <label className="flex items-start gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={e => setAcknowledged(e.target.checked)}
              className="mt-0.5 w-4 h-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
            />
            <span className="text-sm text-gray-700">
              I've backed up my data (or accept the risk)
            </span>
          </label>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-200 flex justify-end gap-3">
          <button
            type="button"
            onClick={handleCancel}
            className="px-4 py-2 text-sm border border-gray-300 rounded hover:bg-gray-50 text-gray-700"
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
