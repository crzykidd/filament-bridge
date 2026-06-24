/**
 * PrintLabelButton — shared "Print label" action (phase 3).
 *
 * Calls POST /api/labels/print for a spool (FDB filament + spool ids). On a 409
 * media mismatch it surfaces a "Print anyway" retry that re-sends with
 * `override=true`. Inline success ("Printed — job #N") / error banners — no toast
 * system, matching Conflicts.tsx.
 *
 * Used on MobileSpoolUpdate (block variant) and as a SyncedRecords row action
 * (compact variant). Render only when `mobile_labels_enabled` (the caller gates).
 */

import { useState } from 'react'
import { printLabel, BridgeApiError } from '../api/client'

interface PrintLabelButtonProps {
  filId: string
  spoolId: string
  /** 'block' = full-width button (mobile card); 'compact' = small inline (table row). */
  variant?: 'block' | 'compact'
}

export function PrintLabelButton({ filId, spoolId, variant = 'block' }: PrintLabelButtonProps) {
  const [printing, setPrinting] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  // When a 409 media mismatch is returned, offer an override retry.
  const [canOverride, setCanOverride] = useState(false)

  async function doPrint(override: boolean) {
    setPrinting(true)
    setErr(null)
    setMsg(null)
    setCanOverride(false)
    try {
      const res = await printLabel(filId, spoolId, override)
      setMsg(res.job_id != null ? `Printed — job #${res.job_id}` : 'Printed.')
    } catch (e) {
      if (e instanceof BridgeApiError) {
        setErr(e.message)
        // A media mismatch is the one error the user can force past.
        if (e.status === 409 && e.code === 'media_mismatch') setCanOverride(true)
      } else {
        setErr(String(e))
      }
    } finally {
      setPrinting(false)
    }
  }

  const compact = variant === 'compact'
  const btnCls = compact
    ? 'inline-flex items-center gap-1 px-2 py-1 text-xs font-medium rounded bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 hover:bg-gray-200 dark:hover:bg-gray-600 disabled:opacity-50 disabled:cursor-not-allowed'
    : 'w-full inline-flex items-center justify-center gap-2 rounded px-4 py-2.5 text-base font-medium bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 hover:bg-gray-200 dark:hover:bg-gray-600 disabled:opacity-50 disabled:cursor-not-allowed'

  return (
    <div className={compact ? 'inline-flex flex-col items-start gap-1' : 'space-y-2'}>
      <button
        type="button"
        onClick={() => { void doPrint(false) }}
        disabled={printing}
        className={btnCls}
        title="Print a label for this spool via LabelForge"
      >
        {printing ? 'Printing…' : 'Print label'}
      </button>
      {canOverride && !printing && (
        <button
          type="button"
          onClick={() => { void doPrint(true) }}
          className={
            compact
              ? 'inline-flex items-center gap-1 px-2 py-1 text-xs font-medium rounded bg-amber-100 dark:bg-amber-900/30 text-amber-800 dark:text-amber-300 hover:bg-amber-200 dark:hover:bg-amber-900/50'
              : 'w-full rounded px-4 py-2 text-sm font-medium bg-amber-100 dark:bg-amber-900/30 text-amber-800 dark:text-amber-300 hover:bg-amber-200 dark:hover:bg-amber-900/50'
          }
        >
          Print anyway (loaded media differs)
        </button>
      )}
      {msg && !err && (
        <p className="text-xs text-emerald-700 dark:text-emerald-400">{msg}</p>
      )}
      {err && (
        <p className="text-xs text-red-600 dark:text-red-400 max-w-xs">{err}</p>
      )}
    </div>
  )
}
