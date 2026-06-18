/**
 * BackupSafetyDialog — optional pre-write backup prompt.
 *
 * Shown before actions that write to Spoolman or Filament DB. Offers one-click
 * backups of both systems; the Proceed button is always enabled so the user is
 * never blocked. For the two debug Danger-Zone clears (which are irreversible and
 * test-only), use DebugConfirmDialog instead — it preserves a strict acknowledgement gate.
 */

import { useState } from 'react'
import { backupFilamentDb, backupSpoolman } from '../api/client'

interface BackupSafetyDialogProps {
  open: boolean
  actionLabel: string
  onCancel: () => void
  onProceed: () => void
}

export type BackupState = 'idle' | 'loading' | 'ok' | 'error'

const MONGODUMP_CMD =
  'docker exec <mongo-container> mongodump --archive=/data/db/fdb-$(date +%F).archive'

/**
 * Shared backup-buttons block used by both BackupSafetyDialog and DebugConfirmDialog.
 */
export function BackupButtons({
  smState,
  smDetail,
  fdbState,
  fdbDetail,
  copyDone,
  onBackupSpoolman,
  onBackupFilamentDb,
  onCopy,
}: {
  smState: BackupState
  smDetail: string
  fdbState: BackupState
  fdbDetail: string
  copyDone: boolean
  onBackupSpoolman: () => void
  onBackupFilamentDb: () => void
  onCopy: () => void
}) {
  return (
    <div className="space-y-5">
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
            onClick={onBackupSpoolman}
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
            onClick={onBackupFilamentDb}
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
            onClick={onCopy}
            className="text-xs border border-gray-300 dark:border-gray-600 rounded px-1.5 py-0.5 hover:bg-gray-50 dark:hover:bg-gray-700 text-gray-500 dark:text-gray-400"
          >
            {copyDone ? 'Copied!' : 'Copy'}
          </button>
        </p>
      </div>
    </div>
  )
}

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
  const [copyDone, setCopyDone] = useState(false)

  if (!open) return null

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
    setCopyDone(false)
  }

  function handleCancel() {
    onCancel()
    setSmState('idle')
    setSmDetail('')
    setFdbState('idle')
    setFdbDetail('')
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
            Back up first? (optional)
          </h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            You can back up Spoolman and Filament DB before continuing. Both buttons are optional — click <strong>Continue</strong> whenever you're ready.
          </p>
        </div>

        {/* Body */}
        <div className="px-6 py-5">
          <BackupButtons
            smState={smState}
            smDetail={smDetail}
            fdbState={fdbState}
            fdbDetail={fdbDetail}
            copyDone={copyDone}
            onBackupSpoolman={() => void handleBackupSpoolman()}
            onBackupFilamentDb={() => void handleBackupFilamentDb()}
            onCopy={handleCopy}
          />
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
            className="px-5 py-2 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700 font-medium"
          >
            Continue — {actionLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
