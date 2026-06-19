/**
 * DebugConfirmDialog — strict confirm gate for Danger-Zone debug actions.
 *
 * Used by the two Settings Danger-Zone clears:
 *   - Clear Spoolman cross-refs (filamentdb_id / filamentdb_spool_id / filamentdb_parent_id)
 *   - Clear Spoolman OpenPrintTag ids (openprinttag_slug / uuid / ignore)
 *
 * The Confirm button is disabled until the user checks the acknowledgement checkbox.
 * Both one-click backup buttons are retained because these clears write irreversibly
 * to Spoolman.
 */

import { useState } from 'react'
import { backupFilamentDb, backupSpoolman } from '../api/client'
import { BackupButtons } from './BackupSafetyDialog'
import type { BackupState } from './BackupSafetyDialog'

interface DebugConfirmDialogProps {
  open: boolean
  /** Short label for the action, e.g. "Clear Filament DB references from Spoolman" */
  actionLabel: string
  /** One-sentence description of what will be erased. */
  warningBody: string
  onCancel: () => void
  onConfirm: () => void
}

const MONGODUMP_CMD =
  'docker exec <mongo-container> mongodump --archive=/data/db/fdb-$(date +%F).archive'

export function DebugConfirmDialog({
  open,
  actionLabel,
  warningBody,
  onCancel,
  onConfirm,
}: DebugConfirmDialogProps) {
  const [smState, setSmState] = useState<BackupState>('idle')
  const [smDetail, setSmDetail] = useState<string>('')
  const [fdbState, setFdbState] = useState<BackupState>('idle')
  const [fdbDetail, setFdbDetail] = useState<string>('')
  const [copyDone, setCopyDone] = useState(false)
  const [acknowledged, setAcknowledged] = useState(false)

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

  function reset() {
    setSmState('idle')
    setSmDetail('')
    setFdbState('idle')
    setFdbDetail('')
    setCopyDone(false)
    setAcknowledged(false)
  }

  function handleConfirm() {
    onConfirm()
    reset()
  }

  function handleCancel() {
    onCancel()
    reset()
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      role="dialog"
      aria-modal="true"
      aria-labelledby="debug-confirm-dialog-title"
    >
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl w-full max-w-lg mx-4 overflow-hidden">
        {/* Header */}
        <div className="px-6 pt-5 pb-4 border-b border-red-200 dark:border-red-800">
          <h2 id="debug-confirm-dialog-title" className="text-lg font-semibold text-red-700 dark:text-red-400">
            Debug action — confirm
          </h2>
          <p className="text-sm text-gray-700 dark:text-gray-300 mt-1">
            <strong>{actionLabel}</strong>
          </p>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            {warningBody}
          </p>
          <p className="text-xs text-red-600 dark:text-red-400 mt-2 font-medium">
            This action is irreversible. Use only during testing with a wiped or disposable dataset.
          </p>
        </div>

        {/* Body — optional backup buttons */}
        <div className="px-6 py-5 space-y-5">
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

          {/* Acknowledgement */}
          <label className="flex items-start gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={e => setAcknowledged(e.target.checked)}
              className="mt-0.5 w-4 h-4 rounded border-gray-300 dark:border-gray-600 text-red-600 focus:ring-red-500"
            />
            <span className="text-sm text-gray-700 dark:text-gray-300">
              I understand this is irreversible and I am running in a test environment.
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
            onClick={handleConfirm}
            disabled={!acknowledged}
            className="px-5 py-2 text-sm bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-40 disabled:cursor-not-allowed font-medium"
          >
            Confirm — {actionLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
