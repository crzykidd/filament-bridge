import { useState } from 'react'
import { postWizardDirection } from '../../api/client'
import type { SourceOfTruth } from '../../api/types'
import type { WizardCtx } from './index'

type SOT = SourceOfTruth

export default function Step2Direction({ next, prev }: WizardCtx) {
  const [direction, setDirection] = useState<SOT>('spoolman')
  const [weightSot, setWeightSot] = useState<SOT>('spoolman')
  const [matSot, setMatSot] = useState<SOT>('filamentdb')
  const [newSpoolSot, setNewSpoolSot] = useState<SOT>('spoolman')
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  function SotPicker({ label, value, onChange }: { label: string; value: SOT; onChange: (v: SOT) => void }) {
    return (
      <div className="flex items-center justify-between py-2">
        <span className="text-sm text-gray-700">{label}</span>
        <div className="flex gap-2">
          {(['spoolman', 'filamentdb'] as SOT[]).map(opt => (
            <button
              key={opt}
              onClick={() => onChange(opt)}
              className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                value === opt ? 'bg-indigo-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {opt === 'spoolman' ? 'Spoolman' : 'Filament DB'}
            </button>
          ))}
        </div>
      </div>
    )
  }

  async function handleSave() {
    setSaving(true)
    setErr(null)
    try {
      await postWizardDirection({
        import_direction: direction,
        weight_source_of_truth: weightSot,
        material_properties_source_of_truth: matSot,
        new_spool_source_of_truth: newSpoolSot,
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
        <h2 className="text-lg font-semibold text-gray-800">Sync direction & source of truth</h2>
        <p className="text-sm text-gray-500 mt-1">
          Choose which system's data wins during the initial import.
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

      <div className="bg-white rounded-lg border border-gray-200 p-5 divide-y divide-gray-100">
        <p className="text-sm font-semibold text-gray-700 pb-2">Ongoing source of truth</p>
        <SotPicker label="Weight" value={weightSot} onChange={setWeightSot} />
        <SotPicker label="Material properties" value={matSot} onChange={setMatSot} />
        <SotPicker label="New spools" value={newSpoolSot} onChange={setNewSpoolSot} />
      </div>

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
