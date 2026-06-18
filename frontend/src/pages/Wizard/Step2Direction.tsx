import { useState } from 'react'
import { postWizardDirection } from '../../api/client'
import type { SourceOfTruth } from '../../api/types'
import type { WizardCtx } from './index'
import { HelpTip } from '../../components/HelpTip'
import { WizardActionBar } from '../../components/WizardActionBar'

type SOT = SourceOfTruth

export default function Step2Direction({ next, prev }: WizardCtx) {
  const [direction, setDirection] = useState<SOT>('spoolman')
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function handleSave() {
    setSaving(true)
    setErr(null)
    try {
      await postWizardDirection({
        import_direction: direction,
      })
      next()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-200">Import direction</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
          Choose which system's data is imported into the other during this run.
        </p>
      </div>

      {/* Top action bar */}
      <WizardActionBar
        onBack={prev}
        onNext={handleSave}
        nextLabel="Save & Next →"
        busy={saving}
        busyLabel="Saving…"
      />

      <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-5 space-y-2">
        <p className="flex items-center text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">
          Initial import direction
          <HelpTip text="One-time import direction for THIS run. Ongoing sync direction lives in Settings." />
        </p>
        <div className="grid grid-cols-2 gap-3">
          {([
            { value: 'spoolman', label: 'Spoolman → Filament DB', desc: 'Import Spoolman filaments/spools into Filament DB' },
            { value: 'filamentdb', label: 'Filament DB → Spoolman', desc: 'Import Filament DB filaments/spools into Spoolman' },
          ] as { value: SOT; label: string; desc: string }[]).map(opt => (
            <button
              key={opt.value}
              onClick={() => setDirection(opt.value)}
              className={`text-left p-4 rounded-lg border-2 transition-colors ${
                direction === opt.value
                  ? 'border-indigo-600 bg-indigo-50 dark:bg-indigo-900/20 dark:border-indigo-500'
                  : 'border-gray-200 dark:border-gray-600 hover:border-gray-300 dark:hover:border-gray-500'
              }`}
            >
              <p className="font-medium text-sm text-gray-800 dark:text-gray-200">{opt.label}</p>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">{opt.desc}</p>
            </button>
          ))}
        </div>
      </div>

      <p className="text-sm text-gray-500 dark:text-gray-400">
        Ongoing source-of-truth settings (weight, material properties, new spools) are
        configured in <strong className="text-gray-700 dark:text-gray-300">Settings</strong> and apply to all future sync cycles.
        Empty/depleted spool behaviour is also controlled by the "Never import empties"
        toggle in Settings.
      </p>

      {err && <p className="text-sm text-red-600 dark:text-red-400">{err}</p>}

      {/* Bottom action bar */}
      <WizardActionBar
        onBack={prev}
        onNext={handleSave}
        nextLabel="Save & Next →"
        busy={saving}
        busyLabel="Saving…"
      />
    </div>
  )
}
