import { useState } from 'react'
import { getWizardVariants, postWizardSmVariants, postWizardVariants } from '../../api/client'
import { useApi } from '../../api/hooks'
import { DeepLinks } from '../../components/DeepLinks'
import type { SMVariantDecision, VariantDecision } from '../../api/types'
import type { WizardCtx } from './index'

export default function Step5Variants({ next, prev }: WizardCtx) {
  const { data, loading, error } = useApi(getWizardVariants)
  const [saving, setSaving] = useState(false)
  const [saveErr, setSaveErr] = useState<string | null>(null)

  if (loading) return <p className="text-gray-500">Loading variant groups…</p>
  if (error) return <p className="text-red-600">{error}</p>
  if (!data) return null

  return data.direction === 'spoolman'
    ? <SMVariants data={data} next={next} prev={prev} saving={saving} setSaving={setSaving} saveErr={saveErr} setSaveErr={setSaveErr} />
    : <FDBVariants data={data} next={next} prev={prev} saving={saving} setSaving={setSaving} saveErr={saveErr} setSaveErr={setSaveErr} />
}

// ---------------------------------------------------------------------------
// SM direction — master/variant grouping for greenfield FDB imports
// ---------------------------------------------------------------------------

type SMProps = {
  data: NonNullable<ReturnType<typeof useApi<typeof getWizardVariants>>['data']>
  next: () => void
  prev: () => void
  saving: boolean
  setSaving: (v: boolean) => void
  saveErr: string | null
  setSaveErr: (v: string | null) => void
}

function SMVariants({ data, next, prev, saving, setSaving, saveErr, setSaveErr }: SMProps) {
  // masters[groupIdx] = selected master SM filament id (default: suggested_master)
  const [masters, setMasters] = useState<Record<number, number>>(() => {
    const init: Record<number, number> = {}
    data.sm_groups.forEach((g, i) => {
      init[i] = g.suggested_master.spoolman_filament_id!
    })
    return init
  })
  // excluded[groupIdx] = set of SM filament ids excluded from the group (kept flat)
  const [excluded, setExcluded] = useState<Record<number, Set<number>>>(() => {
    const init: Record<number, Set<number>> = {}
    data.sm_groups.forEach((_, i) => { init[i] = new Set() })
    return init
  })

  function toggleExclude(groupIdx: number, smId: number, isMaster: boolean) {
    if (isMaster) return  // can't exclude the master
    setExcluded(prev => {
      const next = { ...prev }
      const s = new Set(prev[groupIdx])
      if (s.has(smId)) s.delete(smId); else s.add(smId)
      next[groupIdx] = s
      return next
    })
  }

  function pickMaster(groupIdx: number, smId: number) {
    setMasters(prev => ({ ...prev, [groupIdx]: smId }))
    // Un-exclude the new master if it was excluded
    setExcluded(prev => {
      const next = { ...prev }
      const s = new Set(prev[groupIdx])
      s.delete(smId)
      next[groupIdx] = s
      return next
    })
  }

  async function handleSave() {
    if (!data) { next(); return }
    setSaving(true)
    setSaveErr(null)

    const groups: SMVariantDecision[] = []
    data.sm_groups.forEach((g, i) => {
      const masterId = masters[i]
      const excludedSet = excluded[i] ?? new Set()
      const variants = g.members
        .filter(m => !m.is_master || m.ref.spoolman_filament_id !== masterId)
        .filter(m => m.ref.spoolman_filament_id !== masterId)
        .filter(m => !excludedSet.has(m.ref.spoolman_filament_id!))
        .map(m => m.ref.spoolman_filament_id!)
      // Only include groups that still have at least one variant
      if (variants.length > 0) {
        groups.push({ master_spoolman_filament_id: masterId, variant_spoolman_filament_ids: variants })
      }
    })

    try {
      await postWizardSmVariants({ groups })
      next()
    } catch (e) {
      setSaveErr(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  if (data.sm_groups.length === 0) {
    return (
      <div className="space-y-5">
        <div>
          <h2 className="text-lg font-semibold text-gray-800">Variants</h2>
          <p className="text-sm text-gray-500 mt-1">No variant groups detected. You can skip this step.</p>
        </div>
        <div className="flex justify-between">
          <button onClick={prev} className="px-5 py-2 bg-gray-100 text-gray-700 rounded text-sm font-medium hover:bg-gray-200">← Back</button>
          <button onClick={next} className="px-5 py-2 bg-indigo-600 text-white rounded text-sm font-medium hover:bg-indigo-700">Next →</button>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-gray-800">Variant groups</h2>
        <p className="text-sm text-gray-500 mt-1">
          Select a master for each group. Un-check members to leave them flat. Groups with only a master are kept flat too.
        </p>
      </div>

      <div className="space-y-4">
        {data.sm_groups.map((group, i) => {
          const masterId = masters[i]
          const excludedSet = excluded[i] ?? new Set()
          return (
            <div key={i} className="bg-white rounded-lg border border-gray-200 p-5">
              <div className="mb-3">
                <p className="font-medium text-gray-800">{group.base_name}</p>
                <div className="flex gap-3 text-xs text-gray-500 mt-0.5">
                  {group.vendor && <span>{group.vendor}</span>}
                  {group.material && <span>{group.material}</span>}
                </div>
              </div>
              <div className="space-y-2">
                {group.members.map(member => {
                  const smId = member.ref.spoolman_filament_id!
                  const isMaster = smId === masterId
                  const isExcluded = excludedSet.has(smId)
                  return (
                    <div key={smId} className={`flex items-start gap-3 p-2 rounded ${isExcluded ? 'opacity-40' : ''}`}>
                      {/* master radio */}
                      <input
                        type="radio"
                        name={`master-${i}`}
                        checked={isMaster}
                        onChange={() => pickMaster(i, smId)}
                        className="mt-1 accent-indigo-600"
                        title="Set as master (parent)"
                      />
                      {/* include checkbox — disabled for master */}
                      <input
                        type="checkbox"
                        checked={!isExcluded}
                        disabled={isMaster}
                        onChange={() => toggleExclude(i, smId, isMaster)}
                        className="mt-1 accent-indigo-600"
                        title={isMaster ? 'Master cannot be excluded' : 'Include in group'}
                      />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className={`text-sm ${isMaster ? 'font-semibold text-indigo-700' : 'text-gray-700'}`}>
                            {member.ref.name}
                          </span>
                          {isMaster && <span className="text-xs bg-indigo-100 text-indigo-700 px-1.5 py-0.5 rounded">master</span>}
                          {member.ref.color && (
                            <span className="text-xs text-gray-400 font-mono">{member.ref.color}</span>
                          )}
                          <DeepLinks spoolmanFilamentId={member.ref.spoolman_filament_id} />
                        </div>
                        {member.conflicts.length > 0 && (
                          <div className="mt-1 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1">
                            Conflicts with master:
                            {member.conflicts.map(c => (
                              <span key={c.field} className="ml-1">
                                <span className="font-medium">{c.field}</span>
                                {' '}({String(c.member_value)} vs {String(c.master_value)})
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>

      {saveErr && <p className="text-sm text-red-600">{saveErr}</p>}

      <div className="flex justify-between">
        <button onClick={prev} className="px-5 py-2 bg-gray-100 text-gray-700 rounded text-sm font-medium hover:bg-gray-200">← Back</button>
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

// ---------------------------------------------------------------------------
// FDB direction — existing parent/variant grouping (unchanged behavior)
// ---------------------------------------------------------------------------

type FDBProps = SMProps

function FDBVariants({ data, next, prev, saving, setSaving, saveErr, setSaveErr }: FDBProps) {
  const [skipped, setSkipped] = useState<Set<number>>(new Set())

  async function handleSave() {
    if (!data) { next(); return }
    setSaving(true)
    setSaveErr(null)

    const groups: VariantDecision[] = data.fdb_groups
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

  if (data.fdb_groups.length === 0) {
    return (
      <div className="space-y-5">
        <div>
          <h2 className="text-lg font-semibold text-gray-800">Variants</h2>
          <p className="text-sm text-gray-500 mt-1">No variant groups detected. You can skip this step.</p>
        </div>
        <div className="flex justify-between">
          <button onClick={prev} className="px-5 py-2 bg-gray-100 text-gray-700 rounded text-sm font-medium hover:bg-gray-200">← Back</button>
          <button onClick={next} className="px-5 py-2 bg-indigo-600 text-white rounded text-sm font-medium hover:bg-indigo-700">Next →</button>
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
        {data.fdb_groups.map((group, i) => (
          <div key={i} className={`bg-white rounded-lg border border-gray-200 p-5 ${skipped.has(i) ? 'opacity-50' : ''}`}>
            <div className="flex items-center justify-between mb-3">
              <div>
                <p className="font-medium text-gray-800">{group.base_name}</p>
                {group.vendor && <p className="text-xs text-gray-500">{group.vendor}</p>}
              </div>
              <button
                onClick={() => toggleSkip(i)}
                className={`px-3 py-1 rounded text-xs font-medium ${skipped.has(i) ? 'bg-gray-200 text-gray-600' : 'bg-yellow-100 text-yellow-700 hover:bg-yellow-200'}`}
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
        <button onClick={prev} className="px-5 py-2 bg-gray-100 text-gray-700 rounded text-sm font-medium hover:bg-gray-200">← Back</button>
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
