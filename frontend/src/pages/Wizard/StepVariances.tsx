import { useMemo, useState } from 'react'
import {
  getWizardVariances,
  getWizardVariants,
  getWizardWeights,
  postWizardSmVariants,
  postWizardVariants,
} from '../../api/client'
import { useApi } from '../../api/hooks'
import { DeepLinks } from '../../components/DeepLinks'
import type {
  SMVariantDecision,
  VariancesFilament,
  VariancesGroupRow,
  VariancesResponse,
  VariantDecision,
  VariantPropConflict,
  WizardTareOverride,
} from '../../api/types'
import type { WizardCtx } from './index'

// ---------------------------------------------------------------------------
// Client-side conflict computation — mirrors backend sm_prop_conflicts
// ---------------------------------------------------------------------------

function computeConflicts(master: VariancesFilament, member: VariancesFilament): VariantPropConflict[] {
  const checks: Array<[string, unknown, unknown]> = [
    ['material', master.material ?? null, member.material ?? null],
    ['density', master.density ?? null, member.density ?? null],
    ['spool_weight', master.spool_weight ?? null, member.spool_weight ?? null],
    ['settings_extruder_temp', master.settings_extruder_temp ?? null, member.settings_extruder_temp ?? null],
    ['settings_bed_temp', master.settings_bed_temp ?? null, member.settings_bed_temp ?? null],
  ]
  const result: VariantPropConflict[] = []
  for (const [field, mv, memv] of checks) {
    if (mv === null && memv === null) continue
    if (mv !== memv) result.push({ field, master_value: mv, member_value: memv })
  }
  return result
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

export default function StepVariances({ next, prev, setTareOverrides }: WizardCtx) {
  const { data, loading, error } = useApi(getWizardVariances)

  if (loading) return <p className="text-gray-500">Loading…</p>
  if (error) return <p className="text-red-600">{error}</p>
  if (!data) return null

  return data.direction === 'spoolman'
    ? <SMVariancesStep data={data} next={next} prev={prev} setTareOverrides={setTareOverrides} />
    : <FDBVariancesStep next={next} prev={prev} setTareOverrides={setTareOverrides} />
}

// ---------------------------------------------------------------------------
// SM direction — rich grouping + tare UI
// ---------------------------------------------------------------------------

type SMProps = {
  data: VariancesResponse
  next: () => void
  prev: () => void
  setTareOverrides: (o: WizardTareOverride[]) => void
}

function SMVariancesStep({ data, next, prev, setTareOverrides }: SMProps) {
  // groupMembership[groupIdx] = set of SM filament ids in that group
  // D2: members pre-flagged with suggest_exclude start unchecked (excluded from the group)
  const [groupMembership, setGroupMembership] = useState<Record<number, Set<number>>>(() => {
    const init: Record<number, Set<number>> = {}
    data.groups.forEach((g, i) => {
      init[i] = new Set(
        g.members
          .filter(m => !m.suggest_exclude)
          .map(m => m.ref.spoolman_filament_id!)
      )
    })
    return init
  })

  // masters[groupIdx] = currently selected master SM filament id
  const [masters, setMasters] = useState<Record<number, number>>(() => {
    const init: Record<number, number> = {}
    data.groups.forEach((g, i) => {
      init[i] = g.suggested_master.spoolman_filament_id!
    })
    return init
  })

  // D3: attachDecision[groupIdx] = 'attach' | 'create_new'
  // Default to 'attach' when an existing FDB parent is present
  const [attachDecision, setAttachDecision] = useState<Record<number, 'attach' | 'create_new'>>(() => {
    const init: Record<number, 'attach' | 'create_new'> = {}
    data.groups.forEach((g, i) => { init[i] = g.existing_fdb_parent ? 'attach' : 'create_new' })
    return init
  })

  // D2 manual grouping: extra groups created from standalone selections
  const [extraGroupMemberships, setExtraGroupMemberships] = useState<Record<number, Set<number>>>({})
  const [extraMasters, setExtraMasters] = useState<Record<number, number>>({})
  const [selectedForGrouping, setSelectedForGrouping] = useState<Set<number>>(new Set())

  // tare per SM filament id (string for input binding)
  const [tareBySMId, setTareBySMId] = useState<Record<number, string>>(() => {
    const init: Record<number, string> = {}
    for (const g of data.groups) {
      for (const m of g.members) init[m.ref.spoolman_filament_id!] = String(m.tare)
    }
    for (const f of data.ungrouped) init[f.ref.spoolman_filament_id!] = String(f.tare)
    return init
  })

  // groupIdx for which the "add member" dropdown is open (null = none)
  const [addingTo, setAddingTo] = useState<number | null>(null)

  const [saving, setSaving] = useState(false)
  const [saveErr, setSaveErr] = useState<string | null>(null)

  // Lookup map: all filament data by SM id (static from API response)
  const allFilamentData = useMemo(() => {
    const map = new Map<number, VariancesFilament>()
    for (const g of data.groups) {
      for (const m of g.members) map.set(m.ref.spoolman_filament_id!, m)
    }
    for (const f of data.ungrouped) map.set(f.ref.spoolman_filament_id!, f)
    return map
  }, [data])

  // Effective ungrouped pool: all filaments NOT currently in any group (including extra groups)
  const effectiveUngrouped = useMemo<VariancesFilament[]>(() => {
    const inAnyGroup = new Set<number>()
    for (const membership of Object.values(groupMembership)) {
      for (const id of membership) inAnyGroup.add(id)
    }
    for (const membership of Object.values(extraGroupMemberships)) {
      for (const id of membership) inAnyGroup.add(id)
    }
    return Array.from(allFilamentData.values()).filter(
      f => !inAnyGroup.has(f.ref.spoolman_filament_id!)
    )
  }, [allFilamentData, groupMembership, extraGroupMemberships])

  function pickMaster(groupIdx: number, smId: number) {
    setMasters(prev => ({ ...prev, [groupIdx]: smId }))
  }

  function toggleMember(groupIdx: number, smId: number) {
    const masterId = masters[groupIdx]
    if (smId === masterId) return
    setGroupMembership(prev => {
      const next = { ...prev }
      const s = new Set(prev[groupIdx])
      if (s.has(smId)) s.delete(smId); else s.add(smId)
      next[groupIdx] = s
      return next
    })
  }

  function addMember(groupIdx: number, smId: number) {
    setGroupMembership(prev => {
      const next = { ...prev }
      const s = new Set(prev[groupIdx])
      s.add(smId)
      next[groupIdx] = s
      return next
    })
    setAddingTo(null)
  }

  function getLiveConflicts(groupIdx: number, memberSmId: number): VariantPropConflict[] {
    const masterId = masters[groupIdx]
    if (memberSmId === masterId) return []
    const masterData = allFilamentData.get(masterId)
    const memberData = allFilamentData.get(memberSmId)
    if (!masterData || !memberData) return []
    return computeConflicts(masterData, memberData)
  }

  function toggleSelectForGrouping(smId: number) {
    setSelectedForGrouping(prev => {
      const n = new Set(prev)
      if (n.has(smId)) n.delete(smId); else n.add(smId)
      return n
    })
  }

  function createGroupFromSelected() {
    if (selectedForGrouping.size < 2) return
    const memberArr = Array.from(selectedForGrouping)
    const extraIdx = Object.keys(extraGroupMemberships).length
    setExtraGroupMemberships(prev => ({ ...prev, [extraIdx]: new Set(memberArr) }))
    setExtraMasters(prev => ({ ...prev, [extraIdx]: memberArr[0] }))
    setSelectedForGrouping(new Set())
  }

  async function handleSave() {
    setSaving(true)
    setSaveErr(null)
    try {
      // Build variant decisions from current group membership (D3: include attach decision)
      const groups: SMVariantDecision[] = []
      for (const [idx] of data.groups.entries()) {
        const masterId = masters[idx]
        const variants = Array.from(groupMembership[idx]).filter(id => id !== masterId)
        if (variants.length > 0 || attachDecision[idx] === 'attach') {
          const decision: SMVariantDecision = {
            master_spoolman_filament_id: masterId,
            variant_spoolman_filament_ids: variants,
          }
          if (attachDecision[idx] === 'attach' && data.groups[idx].existing_fdb_parent?.filamentdb_filament_id) {
            decision.existing_fdb_parent_id = data.groups[idx].existing_fdb_parent!.filamentdb_filament_id!
          }
          groups.push(decision)
        }
      }
      // D2 manual groups from standalone selections
      for (const [idxStr, membership] of Object.entries(extraGroupMemberships)) {
        const extraIdx = parseInt(idxStr)
        const masterId = extraMasters[extraIdx]
        const variants = Array.from(membership).filter(id => id !== masterId)
        if (variants.length > 0) {
          groups.push({ master_spoolman_filament_id: masterId, variant_spoolman_filament_ids: variants })
        }
      }
      await postWizardSmVariants({ groups })

      // Expand per-group / per-standalone tare to per-spool overrides
      const tare: WizardTareOverride[] = []
      for (const [idx] of data.groups.entries()) {
        const masterId = masters[idx]
        const groupTare = parseFloat(tareBySMId[masterId] ?? '200')
        if (isNaN(groupTare)) continue
        for (const smId of Array.from(groupMembership[idx])) {
          const filData = allFilamentData.get(smId)
          if (!filData) continue
          for (const spoolId of filData.spool_ids) {
            tare.push({ spoolman_spool_id: spoolId, tare: groupTare })
          }
        }
      }
      // Extra groups from manual grouping
      for (const [idxStr, membership] of Object.entries(extraGroupMemberships)) {
        const extraIdx = parseInt(idxStr)
        const masterId = extraMasters[extraIdx]
        const groupTare = parseFloat(tareBySMId[masterId] ?? '200')
        if (isNaN(groupTare)) continue
        for (const smId of Array.from(membership)) {
          const filData = allFilamentData.get(smId)
          if (!filData) continue
          for (const spoolId of filData.spool_ids) {
            tare.push({ spoolman_spool_id: spoolId, tare: groupTare })
          }
        }
      }
      for (const f of effectiveUngrouped) {
        const smId = f.ref.spoolman_filament_id!
        const filTare = parseFloat(tareBySMId[smId] ?? String(f.tare))
        if (isNaN(filTare)) continue
        for (const spoolId of f.spool_ids) {
          tare.push({ spoolman_spool_id: spoolId, tare: filTare })
        }
      }

      setTareOverrides(tare)
      next()
    } catch (e) {
      setSaveErr(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  if (data.groups.length === 0 && effectiveUngrouped.length === 0) {
    return (
      <div className="space-y-5">
        <div>
          <h2 className="text-lg font-semibold text-gray-800">Variances</h2>
          <p className="text-sm text-gray-500 mt-1">No variant groups or tare adjustments needed.</p>
        </div>
        <div className="flex justify-between">
          <button onClick={prev} className="px-5 py-2 bg-gray-100 text-gray-700 rounded text-sm font-medium hover:bg-gray-200">← Back</button>
          <button onClick={() => { setTareOverrides([]); next() }} className="px-5 py-2 bg-indigo-600 text-white rounded text-sm font-medium hover:bg-indigo-700">Next →</button>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-gray-800">Variances</h2>
        <p className="text-sm text-gray-500 mt-1">
          Review variant groupings and tare (empty-reel) weights. One tare per group applies to all members.
        </p>
      </div>

      {/* Variant groups */}
      {data.groups.length > 0 && (
        <div className="space-y-4">
          <h3 className="text-sm font-medium text-gray-700">Variant groups</h3>
          {data.groups.map((group: VariancesGroupRow, groupIdx: number) => {
            const masterId = masters[groupIdx]
            const membership = groupMembership[groupIdx]
            const masterTareVal = tareBySMId[masterId] ?? '200'
            const masterData = allFilamentData.get(masterId)
            const tareIsDefault = masterData?.tare_source === 'default'
            const addCandidates = effectiveUngrouped.filter(f => !membership.has(f.ref.spoolman_filament_id!))

            return (
              <div key={groupIdx} className="bg-white rounded-lg border border-gray-200 p-5">
                {/* D3: attach-vs-create choice */}
                {group.existing_fdb_parent && (
                  <div className="mb-3 bg-blue-50 border border-blue-200 rounded p-3">
                    <p className="text-xs font-medium text-blue-800 mb-2">
                      Existing Filament DB parent found: <span className="font-semibold">{group.existing_fdb_parent.name}</span>
                    </p>
                    <div className="flex gap-2">
                      {(['attach', 'create_new'] as const).map(opt => (
                        <button
                          key={opt}
                          onClick={() => setAttachDecision(prev => ({ ...prev, [groupIdx]: opt }))}
                          className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                            attachDecision[groupIdx] === opt
                              ? 'bg-blue-600 text-white'
                              : 'bg-white text-blue-700 border border-blue-300 hover:bg-blue-50'
                          }`}
                        >
                          {opt === 'attach'
                            ? `Attach to «${group.existing_fdb_parent.name}»`
                            : 'Create new parent'}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="font-medium text-gray-800">{group.base_name}</p>
                    <div className="flex gap-3 text-xs text-gray-500 mt-0.5">
                      {group.vendor && <span>{group.vendor}</span>}
                      {group.material && <span>{group.material}</span>}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <label className="text-xs text-gray-500 whitespace-nowrap">Empty-reel tare (g):</label>
                    <input
                      type="number" min="0" step="1"
                      value={masterTareVal}
                      onChange={e => setTareBySMId(prev => ({ ...prev, [masterId]: e.target.value }))}
                      className="w-20 border border-gray-300 rounded px-2 py-1 text-xs text-right focus:outline-none focus:ring-2 focus:ring-indigo-400"
                    />
                    {tareIsDefault && (
                      <span className="text-xs bg-yellow-100 text-yellow-700 px-1.5 py-0.5 rounded">default</span>
                    )}
                  </div>
                </div>

                <div className="mb-3 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-2">
                  All variants in this group will use the master's empty-reel tare: <strong>{masterTareVal} g</strong>.
                  Filament DB stores one tare per filament.
                </div>

                <div className="space-y-2">
                  {Array.from(membership).map(smId => {
                    const filData = allFilamentData.get(smId)
                    if (!filData) return null
                    const isMaster = smId === masterId
                    const conflicts = getLiveConflicts(groupIdx, smId)
                    return (
                      <div key={smId} className="flex items-start gap-3 p-2 rounded hover:bg-gray-50">
                        <input
                          type="radio"
                          name={`master-${groupIdx}`}
                          checked={isMaster}
                          onChange={() => pickMaster(groupIdx, smId)}
                          className="mt-1 accent-indigo-600"
                          title="Set as master (parent)"
                        />
                        <input
                          type="checkbox"
                          checked
                          disabled={isMaster}
                          onChange={() => toggleMember(groupIdx, smId)}
                          className="mt-1 accent-indigo-600"
                          title={isMaster ? 'Master cannot be removed' : 'Remove from group (leaves flat)'}
                        />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className={`text-sm ${isMaster ? 'font-semibold text-indigo-700' : 'text-gray-700'}`}>
                              {filData.ref.name}
                            </span>
                            {isMaster && (
                              <span className="text-xs bg-indigo-100 text-indigo-700 px-1.5 py-0.5 rounded">master</span>
                            )}
                            {filData.ref.color && (
                              <span className="text-xs text-gray-400 font-mono">{filData.ref.color}</span>
                            )}
                            <DeepLinks spoolmanFilamentId={filData.ref.spoolman_filament_id} />
                          </div>
                          {conflicts.length > 0 && (
                            <div className="mt-1 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1">
                              Conflicts with master:
                              {conflicts.map(c => (
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

                {addCandidates.length > 0 && (
                  <div className="mt-3">
                    {addingTo === groupIdx ? (
                      <div className="flex items-center gap-2">
                        <select
                          className="text-xs border border-gray-200 rounded px-2 py-1 flex-1"
                          defaultValue=""
                          onChange={e => { if (e.target.value) addMember(groupIdx, parseInt(e.target.value)) }}
                        >
                          <option value="" disabled>Select filament to add…</option>
                          {addCandidates.map(f => (
                            <option key={f.ref.spoolman_filament_id} value={f.ref.spoolman_filament_id!}>
                              {f.ref.name}{f.ref.vendor ? ` (${f.ref.vendor})` : ''}
                            </option>
                          ))}
                        </select>
                        <button onClick={() => setAddingTo(null)}
                          className="text-xs text-gray-500 hover:text-gray-700 shrink-0">Cancel</button>
                      </div>
                    ) : (
                      <button onClick={() => setAddingTo(groupIdx)}
                        className="text-xs text-indigo-600 hover:text-indigo-800 font-medium">
                        + Add member
                      </button>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Standalone (ungrouped) filaments */}
      {effectiveUngrouped.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium text-gray-700">Standalone filaments</h3>
            {selectedForGrouping.size >= 2 && (
              <button
                onClick={createGroupFromSelected}
                className="px-3 py-1 text-xs font-medium bg-indigo-600 text-white rounded hover:bg-indigo-700"
              >
                Group as variants ({selectedForGrouping.size})
              </button>
            )}
          </div>
          {selectedForGrouping.size > 0 && selectedForGrouping.size < 2 && (
            <p className="text-xs text-gray-500">Select one more to enable grouping.</p>
          )}
          <div className="bg-white rounded-lg border border-gray-200 divide-y divide-gray-100">
            {effectiveUngrouped.map(f => {
              const smId = f.ref.spoolman_filament_id!
              return (
                <div key={smId} className="flex flex-wrap items-center gap-3 px-4 py-3 hover:bg-gray-50">
                  {/* D2 manual grouping checkbox */}
                  <input
                    type="checkbox"
                    checked={selectedForGrouping.has(smId)}
                    onChange={() => toggleSelectForGrouping(smId)}
                    className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 shrink-0"
                    title="Select to group as variants"
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm text-gray-700">{f.ref.name}</span>
                      {f.ref.vendor && <span className="text-xs text-gray-400">{f.ref.vendor}</span>}
                      {f.ref.color && <span className="text-xs font-mono text-gray-400">{f.ref.color}</span>}
                      {f.suggest_exclude && (
                        <span className="text-xs bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded">
                          suggested standalone (prop conflict)
                        </span>
                      )}
                      <DeepLinks spoolmanFilamentId={smId} />
                    </div>
                  </div>
                  <label className="flex items-center gap-1.5 text-xs text-gray-500 shrink-0">
                    Tare (g):
                    <input
                      type="number" min="0" step="1"
                      value={tareBySMId[smId] ?? String(f.tare)}
                      onChange={e => setTareBySMId(prev => ({ ...prev, [smId]: e.target.value }))}
                      className="w-20 border border-gray-300 rounded px-2 py-1 text-xs text-right focus:outline-none focus:ring-2 focus:ring-indigo-400"
                    />
                    {f.tare_source === 'default' && (
                      <span className="text-xs bg-yellow-100 text-yellow-700 px-1.5 py-0.5 rounded">default</span>
                    )}
                  </label>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* D2 extra groups from manual selection */}
      {Object.keys(extraGroupMemberships).length > 0 && (
        <div className="space-y-4">
          <h3 className="text-sm font-medium text-gray-700">Manually grouped</h3>
          {Object.entries(extraGroupMemberships).map(([idxStr, membership]) => {
            const extraIdx = parseInt(idxStr)
            const masterId = extraMasters[extraIdx]
            const masterTareVal = tareBySMId[masterId] ?? '200'
            return (
              <div key={extraIdx} className="bg-white rounded-lg border border-indigo-200 p-4 space-y-2">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium text-gray-700">Manual group {extraIdx + 1}</p>
                  <button
                    onClick={() => {
                      setExtraGroupMemberships(prev => { const n = {...prev}; delete n[extraIdx]; return n })
                      setExtraMasters(prev => { const n = {...prev}; delete n[extraIdx]; return n })
                    }}
                    className="text-xs text-gray-400 hover:text-red-500"
                  >
                    Disband
                  </button>
                </div>
                {Array.from(membership).map(smId => {
                  const filData = allFilamentData.get(smId)
                  if (!filData) return null
                  const isMaster = smId === masterId
                  return (
                    <div key={smId} className="flex items-center gap-3">
                      <input type="radio" name={`extra-master-${extraIdx}`}
                        checked={isMaster}
                        onChange={() => setExtraMasters(prev => ({ ...prev, [extraIdx]: smId }))}
                        className="accent-indigo-600"
                        title="Set as master" />
                      <span className={`text-sm ${isMaster ? 'font-semibold text-indigo-700' : 'text-gray-700'}`}>
                        {filData.ref.name}
                      </span>
                      {isMaster && <span className="text-xs bg-indigo-100 text-indigo-700 px-1.5 py-0.5 rounded">master</span>}
                    </div>
                  )
                })}
                <label className="flex items-center gap-1.5 text-xs text-gray-500">
                  Group tare (g):
                  <input type="number" min="0" step="1"
                    value={masterTareVal}
                    onChange={e => setTareBySMId(prev => ({ ...prev, [masterId]: e.target.value }))}
                    className="w-20 border border-gray-300 rounded px-2 py-1 text-xs text-right focus:outline-none focus:ring-2 focus:ring-indigo-400" />
                </label>
              </div>
            )
          })}
        </div>
      )}

      {saveErr && <p className="text-sm text-red-600">{saveErr}</p>}

      <div className="flex justify-between">
        <button onClick={prev}
          className="px-5 py-2 bg-gray-100 text-gray-700 rounded text-sm font-medium hover:bg-gray-200">
          ← Back
        </button>
        <button onClick={handleSave} disabled={saving}
          className="px-5 py-2 bg-indigo-600 text-white rounded text-sm font-medium hover:bg-indigo-700 disabled:opacity-50">
          {saving ? 'Saving…' : 'Save & Next →'}
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// FDB direction — existing FDB variant groups + weight review (moved)
// ---------------------------------------------------------------------------

type FDBProps = {
  next: () => void
  prev: () => void
  setTareOverrides: (o: WizardTareOverride[]) => void
}

function FDBVariancesStep({ next, prev, setTareOverrides }: FDBProps) {
  const { data: variantsData, loading: varLoading, error: varError } = useApi(getWizardVariants)
  const { data: weightsData, loading: wtLoading, error: wtError } = useApi(getWizardWeights)
  const [overrides, setOverrides] = useState<Record<string, string>>({})
  const [skipped, setSkipped] = useState<Set<number>>(new Set())
  const [saving, setSaving] = useState(false)
  const [saveErr, setSaveErr] = useState<string | null>(null)

  if (varLoading || wtLoading) return <p className="text-gray-500">Loading variant groups…</p>
  if (varError || wtError) return <p className="text-red-600">{varError ?? wtError}</p>
  if (!variantsData) return null

  function rowKey(spoolmanId: number | null, fdbId: string | null) {
    return `${spoolmanId ?? 'null'}_${fdbId ?? 'null'}`
  }

  function toggleSkip(i: number) {
    setSkipped(s => { const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n })
  }

  async function handleSave() {
    setSaving(true)
    setSaveErr(null)
    try {
      const groups: VariantDecision[] = (variantsData?.fdb_groups ?? [])
        .filter((_, i) => !skipped.has(i))
        .map(g => ({
          parent_filamentdb_id: g.suggested_parent.filamentdb_filament_id!,
          variant_filamentdb_ids: g.variants
            .map(v => v.filamentdb_filament_id)
            .filter((id): id is string => id != null),
        }))
      await postWizardVariants({ groups })

      const tare: WizardTareOverride[] = []
      if (weightsData) {
        for (const row of weightsData.rows) {
          const key = rowKey(row.spoolman_spool_id, row.filamentdb_spool_id)
          const val = overrides[key]
          if (val && !isNaN(parseFloat(val))) {
            tare.push({
              spoolman_spool_id: row.spoolman_spool_id,
              filamentdb_spool_id: row.filamentdb_spool_id,
              tare: parseFloat(val),
            })
          }
        }
      }
      setTareOverrides(tare)
      next()
    } catch (e) {
      setSaveErr(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-gray-800">Variances</h2>
        <p className="text-sm text-gray-500 mt-1">Review variant groupings and weight conversions.</p>
      </div>

      {/* FDB variant groups */}
      {(variantsData.fdb_groups?.length ?? 0) > 0 ? (
        <div className="space-y-3">
          <h3 className="text-sm font-medium text-gray-700">Variant groups</h3>
          {variantsData.fdb_groups.map((group, i) => (
            <div key={i} className={`bg-white rounded-lg border border-gray-200 p-5 ${skipped.has(i) ? 'opacity-50' : ''}`}>
              <div className="flex items-center justify-between mb-3">
                <div>
                  <p className="font-medium text-gray-800">{group.base_name}</p>
                  {group.vendor && <p className="text-xs text-gray-500">{group.vendor}</p>}
                </div>
                <button onClick={() => toggleSkip(i)}
                  className={`px-3 py-1 rounded text-xs font-medium ${skipped.has(i) ? 'bg-gray-200 text-gray-600' : 'bg-yellow-100 text-yellow-700 hover:bg-yellow-200'}`}>
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
      ) : (
        <p className="text-sm text-gray-500">No variant groups detected in Filament DB.</p>
      )}

      {/* Weight review */}
      {weightsData && weightsData.rows.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-sm font-medium text-gray-700">Weight conversions</h3>
          <p className="text-xs text-gray-500">
            Override tare (empty reel) per spool if needed.
            Direction: <strong>{weightsData.direction.replace(/_/g, ' ')}</strong>.
          </p>
          <div className="overflow-x-auto bg-white rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  {['Spool', 'Net (g)', 'Gross (g)', 'Tare (g)', 'Source', 'Override tare', 'Links'].map(h => (
                    <th key={h} className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {weightsData.rows.map(row => {
                  const key = rowKey(row.spoolman_spool_id, row.filamentdb_spool_id)
                  return (
                    <tr key={key} className="hover:bg-gray-50">
                      <td className="px-4 py-3 font-medium text-gray-900">{row.name ?? '—'}</td>
                      <td className="px-4 py-3 text-gray-600">{row.net_weight?.toFixed(1) ?? '—'}</td>
                      <td className="px-4 py-3 text-gray-600">{row.gross_weight?.toFixed(1) ?? '—'}</td>
                      <td className="px-4 py-3 text-gray-600">{row.tare.toFixed(1)}</td>
                      <td className="px-4 py-3">
                        <span className={`text-xs px-1.5 py-0.5 rounded ${row.tare_source === 'default' ? 'bg-yellow-100 text-yellow-700' : 'bg-gray-100 text-gray-600'}`}>
                          {row.tare_source}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <input type="number" min="0" step="1" placeholder={row.tare.toFixed(0)}
                          value={overrides[key] ?? ''}
                          onChange={e => setOverrides(o => ({ ...o, [key]: e.target.value }))}
                          className="w-20 border border-gray-300 rounded px-2 py-1 text-xs text-right focus:outline-none focus:ring-2 focus:ring-indigo-400" />
                      </td>
                      <td className="px-4 py-3">
                        <DeepLinks filamentdbFilamentId={row.filamentdb_filament_id} spoolmanSpoolId={row.spoolman_spool_id} />
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {saveErr && <p className="text-sm text-red-600">{saveErr}</p>}

      <div className="flex justify-between">
        <button onClick={prev} className="px-5 py-2 bg-gray-100 text-gray-700 rounded text-sm font-medium hover:bg-gray-200">← Back</button>
        <button onClick={handleSave} disabled={saving}
          className="px-5 py-2 bg-indigo-600 text-white rounded text-sm font-medium hover:bg-indigo-700 disabled:opacity-50">
          {saving ? 'Saving…' : 'Save & Next →'}
        </button>
      </div>
    </div>
  )
}
