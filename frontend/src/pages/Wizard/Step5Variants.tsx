import { useState } from 'react'
import { getWizardVariants, postWizardVariants } from '../../api/client'
import { useApi } from '../../api/hooks'
import { DeepLinks } from '../../components/DeepLinks'
import type { VariantDecision } from '../../api/types'
import type { WizardCtx } from './index'

export default function Step5Variants({ next, prev }: WizardCtx) {
  const { data, loading, error } = useApi(getWizardVariants)
  const [skipped, setSkipped] = useState<Set<number>>(new Set())
  const [saving, setSaving] = useState(false)
  const [saveErr, setSaveErr] = useState<string | null>(null)

  async function handleSave() {
    if (!data) { next(); return }
    setSaving(true)
    setSaveErr(null)

    const groups: VariantDecision[] = data.groups
      .filter((_, i) => !skipped.has(i))
      .map(g => ({
        parent_filamentdb_id: g.suggested_parent.filamentdb_filament_id!,
        variant_filamentdb_ids: g.variants
          .map(v => v.filamentdb_filament_id)
          .filter((id): id is string => id != null),
      }))

    try {
      await postWizardVariants({ groups })
      next()
    } catch (e) {
      setSaveErr(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  function toggleSkip(i: number) {
    setSkipped(s => {
      const next = new Set(s)
      if (next.has(i)) next.delete(i); else next.add(i)
      return next
    })
  }

  if (loading) return <p className="text-gray-500">Loading variant groups…</p>
  if (error) return <p className="text-red-600">{error}</p>
  if (!data) return null

  if (data.groups.length === 0) {
    return (
      <div className="space-y-5">
        <div>
          <h2 className="text-lg font-semibold text-gray-800">Variants</h2>
          <p className="text-sm text-gray-500 mt-1">No variant groups detected. You can skip this step.</p>
        </div>
        <div className="flex justify-between">
          <button onClick={prev} className="px-5 py-2 bg-gray-100 text-gray-700 rounded text-sm font-medium hover:bg-gray-200">
            ← Back
          </button>
          <button onClick={next} className="px-5 py-2 bg-indigo-600 text-white rounded text-sm font-medium hover:bg-indigo-700">
            Next →
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-gray-800">Variant groups</h2>
        <p className="text-sm text-gray-500 mt-1">
          Confirm or skip suggested parent/variant groupings. Skipped groups are left flat.
        </p>
      </div>

      <div className="space-y-3">
        {data.groups.map((group, i) => (
          <div key={i} className={`bg-white rounded-lg border border-gray-200 p-5 ${skipped.has(i) ? 'opacity-50' : ''}`}>
            <div className="flex items-center justify-between mb-3">
              <div>
                <p className="font-medium text-gray-800">{group.base_name}</p>
                {group.vendor && <p className="text-xs text-gray-500">{group.vendor}</p>}
              </div>
              <button
                onClick={() => toggleSkip(i)}
                className={`px-3 py-1 rounded text-xs font-medium ${
                  skipped.has(i)
                    ? 'bg-gray-200 text-gray-600'
                    : 'bg-yellow-100 text-yellow-700 hover:bg-yellow-200'
                }`}
              >
                {skipped.has(i) ? 'Unskip' : 'Skip'}
              </button>
            </div>
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium text-gray-500 uppercase w-14">Parent</span>
                <span className="text-sm font-medium">{group.suggested_parent.name}</span>
                <DeepLinks filamentdbFilamentId={group.suggested_parent.filamentdb_filament_id} />
              </div>
              <div className="pl-14 space-y-1">
                {group.variants.map(v => (
                  <div key={v.filamentdb_filament_id} className="flex items-center gap-2">
                    <span className="text-sm text-gray-600">{v.name}</span>
                    {v.color && <span className="text-xs text-gray-400">{v.color}</span>}
                    <DeepLinks filamentdbFilamentId={v.filamentdb_filament_id} />
                  </div>
                ))}
              </div>
            </div>
          </div>
        ))}
      </div>

      {saveErr && <p className="text-sm text-red-600">{saveErr}</p>}

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
