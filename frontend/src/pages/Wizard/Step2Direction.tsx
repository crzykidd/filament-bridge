import { useState } from 'react'
import { postWizardDirection } from '../../api/client'
import type { SourceOfTruth } from '../../api/types'
import type { WizardCtx } from './index'

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
        <h2 className="text-lg font-semibold text-gray-800">Import direction</h2>
        <p className="text-sm text-gray-500 mt-1">
          Choose which system's data is imported into the other during this run.
        </p>
      </div>

      <div className="bg-white rounded-lg border border-gray-200 p-5 space-y-2">
        <p className="text-sm font-semibold text-gray-700 mb-3">Initial import direction</p>
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
                  ? 'border-indigo-600 bg-indigo-50'
                  : 'border-gray-200 hover:border-gray-300'
              }`}
            >
              <p className="font-medium text-sm">{opt.label}</p>
              <p className="text-xs text-gray-500 mt-1">{opt.desc}</p>
            </button>
          ))}
        </div>
      </div>

      <p className="text-sm text-gray-500">
        Ongoing source-of-truth settings (weight, material properties, new spools) are
        configured in <strong>Settings</strong> and apply to all future sync cycles.
        Empty/depleted spool behaviour is also controlled by the "Never import empties"
        toggle in Settings.
      </p>

      {err && <p className="text-sm text-red-600">{err}</p>}

      <div className="flex justify-between">
        <button onClick={prev} className="px-5 py-2 bg-gray-100 text-gray-700 rounded text-sm font-medium hover:bg-gray-200">
          ← Back
        </button>
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-5 py-2 bg-indigo-600 text-white rounded text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save & Next →'}
        </button>
      </div>
    </div>
  )
}
