/**
 * RequiredSettingsGate — shows a modal when required settings are unset.
 *
 * Reads GET /api/config on mount (and when deps change). If required_settings_unset
 * is non-empty, renders a non-dismissible modal listing them. The user must navigate
 * to Settings and configure them to clear the modal.
 *
 * A "Later" button dismisses the modal for the current session only; it will
 * re-appear on the next page load.
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getConfig } from '../api/client'

const SETTING_LABELS: Record<string, string> = {
  variant_parent_mode: 'Variant parent mode (required before running the Bulk Import Wizard)',
}

export function RequiredSettingsGate() {
  const [unset, setUnset] = useState<string[]>([])
  const [dismissed, setDismissed] = useState(false)
  const navigate = useNavigate()

  useEffect(() => {
    getConfig()
      .then(cfg => setUnset(cfg.required_settings_unset ?? []))
      .catch(() => {/* ignore — if config fails auth gate handles it */})
  }, [])

  const show = unset.length > 0 && !dismissed

  if (!show) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white dark:bg-gray-800 rounded-lg border border-amber-300 dark:border-amber-700 shadow-lg p-6 max-w-md w-full space-y-4">
        <h2 className="text-base font-semibold text-amber-800 dark:text-amber-300">Required settings not configured</h2>
        <p className="text-sm text-gray-700 dark:text-gray-300">
          The following settings must be configured before the bridge is fully usable:
        </p>
        <ul className="list-disc list-inside space-y-1">
          {unset.map(key => (
            <li key={key} className="text-sm text-gray-800 dark:text-gray-200">
              {SETTING_LABELS[key] ?? key}
            </li>
          ))}
        </ul>
        <div className="flex gap-3 pt-2">
          <button
            type="button"
            onClick={() => { setDismissed(true); void navigate('/settings') }}
            className="px-4 py-2 bg-indigo-600 text-white rounded text-sm font-medium hover:bg-indigo-700"
          >
            Go to Settings
          </button>
          <button
            type="button"
            onClick={() => setDismissed(true)}
            className="px-4 py-2 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 rounded text-sm font-medium hover:bg-gray-200 dark:hover:bg-gray-600"
          >
            Later
          </button>
        </div>
      </div>
    </div>
  )
}
