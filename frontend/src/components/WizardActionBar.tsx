/**
 * WizardActionBar — shared navigation bar rendered at the top and bottom of
 * every wizard step and the OpenTag commit flow.
 *
 * Replaces the five hand-rolled `const actionBar` blocks that previously
 * lived in individual step files.
 *
 * Props:
 *   onBack?       — click handler for the Back button; bar renders without it when absent
 *   backLabel?    — defaults to "← Back"
 *   onNext?       — click handler for the primary forward button; omit on terminal views
 *   nextLabel?    — defaults to "Next →"
 *   nextDisabled? — disables the forward button
 *   busy?         — when true the forward button shows a spinner label (use `nextLabel`
 *                   for the non-busy text; e.g. "Save & Next →" / "Saving…" are handled
 *                   by passing `busy` + `busyLabel`)
 *   busyLabel?    — label shown while busy; defaults to the nextLabel + "…"
 *   extra?        — optional slot rendered between Back and Next (e.g. the Rescan button)
 */

import type { ReactNode } from 'react'

interface WizardActionBarProps {
  onBack?: () => void
  backLabel?: string
  onNext?: () => void
  nextLabel?: string
  nextDisabled?: boolean
  busy?: boolean
  busyLabel?: string
  extra?: ReactNode
}

export function WizardActionBar({
  onBack,
  backLabel = '← Back',
  onNext,
  nextLabel = 'Next →',
  nextDisabled = false,
  busy = false,
  busyLabel,
  extra,
}: WizardActionBarProps) {
  const resolvedBusyLabel = busyLabel ?? `${nextLabel.replace(/\s*→$/, '')}…`

  return (
    <div className="flex justify-between items-center">
      {onBack ? (
        <button
          onClick={onBack}
          disabled={busy}
          className="px-5 py-2 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 rounded text-sm font-medium hover:bg-gray-200 dark:hover:bg-gray-600 disabled:opacity-50"
        >
          {backLabel}
        </button>
      ) : (
        <div />
      )}

      <div className="flex items-center gap-3">
        {extra}
        {onNext && (
          <button
            onClick={onNext}
            disabled={nextDisabled || busy}
            className="px-5 py-2 bg-indigo-600 text-white rounded text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
          >
            {busy ? resolvedBusyLabel : nextLabel}
          </button>
        )}
      </div>
    </div>
  )
}
