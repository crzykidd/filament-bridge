import { useMemo, useState } from 'react'
import {
  getWizardVariances,
  getWizardVariants,
  getWizardWeights,
  postWizardMatchSkip,
  postWizardSmVariants,
  postWizardVariants,
} from '../../api/client'
import { useApi } from '../../api/hooks'
import { DeepLinks } from '../../components/DeepLinks'
import { HelpTip } from '../../components/HelpTip'
import { OptBadge } from '../../components/OptBadge'
import { WizardActionBar } from '../../components/WizardActionBar'
import type {
  ReconciledField,
  SMVariantDecision,
  VariancesFilament,
  VariancesGroupRow,
  VariancesGroupReconcile,
  VariancesResponse,
  VariantDecision,
  VariantPropConflict,
  WizardTareOverride,
} from '../../api/types'
import type { WizardCtx } from './index'

// ---------------------------------------------------------------------------
// Canonical key mapping — frontend reconcile field names → backend _RECONCILE_FIELD_MAP keys
// ReconciledField.field MUST use canonical keys so the backend applies them correctly.
// Raw SM field names are used only for display labels and computeConflicts keying.
// ---------------------------------------------------------------------------

const CONFLICT_FIELD_TO_CANONICAL: Record<string, string> = {
  material: 'type',
  density: 'density',
  diameter: 'diameter',
  settings_extruder_temp: 'nozzle_temp',
  settings_bed_temp: 'bed_temp',
}

// Human-readable labels for conflicting field names (used in badges and conflict boxes)
const CONFLICT_FIELD_LABELS: Record<string, string> = {
  material: 'material/type',
  density: 'density',
  diameter: 'diameter',
  settings_extruder_temp: 'nozzle temp',
  settings_bed_temp: 'bed temp',
}

// ---------------------------------------------------------------------------
// Client-side conflict computation — mirrors backend sm_prop_conflicts
// ---------------------------------------------------------------------------

function computeConflicts(master: VariancesFilament, member: VariancesFilament): VariantPropConflict[] {
  // mirrors backend sm_prop_conflicts — spool_weight (tare) intentionally excluded
  const checks: Array<[string, unknown, unknown]> = [
    ['material', master.material ?? null, member.material ?? null],
    ['density', master.density ?? null, member.density ?? null],
    ['diameter', master.diameter ?? null, member.diameter ?? null],
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
// Color swatch helper
// ---------------------------------------------------------------------------

function ColorSwatch({ hex }: { hex: string | null | undefined }) {
  if (!hex) return null
  return (
    <span
      className="inline-block w-3.5 h-3.5 rounded-full border border-gray-300 dark:border-gray-600 shrink-0"
      style={{ backgroundColor: hex.startsWith('#') ? hex : `#${hex}` }}
      title={hex}
    />
  )
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

export default function StepVariances({ next, prev, setTareOverrides }: WizardCtx) {
  const { data, loading, error } = useApi(getWizardVariances)

  if (loading) return <p className="text-gray-500 dark:text-gray-400">Loading…</p>
  if (error) return <p className="text-red-600 dark:text-red-400">{error}</p>
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
  const [attachDecision, setAttachDecision] = useState<Record<number, 'attach' | 'create_new'>>(() => {
    const init: Record<number, 'attach' | 'create_new'> = {}
    data.groups.forEach((g, i) => { init[i] = g.existing_fdb_parent ? 'attach' : 'create_new' })
    return init
  })

  // D2 manual grouping: extra groups created from standalone selections
  const [extraGroupMemberships, setExtraGroupMemberships] = useState<Record<number, Set<number>>>({})
  const [extraMasters, setExtraMasters] = useState<Record<number, number>>({})
  const [selectedForGrouping, setSelectedForGrouping] = useState<Set<number>>(new Set())

  // Part A: ignored filament ids (Ignore action → match skip posted to backend)
  const [ignoredIds, setIgnoredIds] = useState<Set<number>>(new Set())
  // Which member row is showing its "Move to" dropdown
  const [movingMember, setMovingMember] = useState<{ fromGroupType: 'auto' | 'extra'; fromIdx: number; smId: number } | null>(null)
  // Which standalone row is showing its "Move to" dropdown
  const [movingStandaloneId, setMovingStandaloneId] = useState<number | null>(null)
  // Which filament is currently being ignored (loading state)
  const [ignoringId, setIgnoringId] = useState<number | null>(null)
  const [ignoreErr, setIgnoreErr] = useState<string | null>(null)

  // Phase 2: reconcile decisions per group — reconcileByGroup[groupIdx] = {field → ReconciledField}
  const [reconcileByGroup, setReconcileByGroup] = useState<Record<number, Record<string, ReconciledField>>>({})

  // tare per SM filament id (string for input binding; empty string when unknown/required)
  const [tareBySMId, setTareBySMId] = useState<Record<number, string>>(() => {
    const init: Record<number, string> = {}
    for (const g of data.groups) {
      for (const m of g.members) {
        init[m.ref.spoolman_filament_id!] = m.tare != null ? String(m.tare) : ''
      }
    }
    for (const f of data.ungrouped) {
      init[f.ref.spoolman_filament_id!] = f.tare != null ? String(f.tare) : ''
    }
    return init
  })

  // groupIdx for which the "add member" dropdown is open (null = none)
  const [addingTo, setAddingTo] = useState<number | null>(null)

  const [saving, setSaving] = useState(false)
  const [saveErr, setSaveErr] = useState<string | null>(null)

  // P2.6: sort control for groups and standalone sections
  type VariancesSortKey = 'vendor' | 'material'
  const [sortBy, setSortBy] = useState<VariancesSortKey>('vendor')

  // Compute how many filaments still need a tare value entered (blocks "Save & Next")
  const missingTareCount = useMemo(() => {
    let count = 0
    // Check auto-group masters (tare applies to the whole group via master)
    for (const [idx] of data.groups.entries()) {
      if (groupMembership[idx].size === 0) continue  // dissolved group
      const masterId = masters[idx]
      const val = tareBySMId[masterId]
      if (val === '' || val === undefined || isNaN(parseFloat(val))) count++
    }
    // Check extra groups
    for (const [idxStr, membership] of Object.entries(extraGroupMemberships)) {
      if (membership.size === 0) continue
      const masterId = extraMasters[parseInt(idxStr)]
      const val = tareBySMId[masterId]
      if (val === '' || val === undefined || isNaN(parseFloat(val))) count++
    }
    // Check standalone (ungrouped, not ignored)
    for (const f of effectiveUngrouped) {
      const smId = f.ref.spoolman_filament_id!
      const val = tareBySMId[smId]
      if (val === '' || val === undefined || isNaN(parseFloat(val))) count++
    }
    return count
  }, [data.groups, groupMembership, masters, extraGroupMemberships, extraMasters, effectiveUngrouped, tareBySMId])

  // Lookup map: all filament data by SM id (static from API response)
  const allFilamentData = useMemo(() => {
    const map = new Map<number, VariancesFilament>()
    for (const g of data.groups) {
      for (const m of g.members) map.set(m.ref.spoolman_filament_id!, m)
    }
    for (const f of data.ungrouped) map.set(f.ref.spoolman_filament_id!, f)
    return map
  }, [data])

  // Effective ungrouped pool: all filaments NOT in any group AND not ignored
  const effectiveUngrouped = useMemo<VariancesFilament[]>(() => {
    const inAnyGroup = new Set<number>()
    for (const membership of Object.values(groupMembership)) {
      for (const id of membership) inAnyGroup.add(id)
    }
    for (const membership of Object.values(extraGroupMemberships)) {
      for (const id of membership) inAnyGroup.add(id)
    }
    return Array.from(allFilamentData.values()).filter(
      f => !inAnyGroup.has(f.ref.spoolman_filament_id!) && !ignoredIds.has(f.ref.spoolman_filament_id!)
    )
  }, [allFilamentData, groupMembership, extraGroupMemberships, ignoredIds])

  function pickMaster(groupIdx: number, smId: number) {
    setMasters(prev => ({ ...prev, [groupIdx]: smId }))
  }

  function addMember(groupIdx: number, smId: number) {
    setGroupMembership(prev => {
      const s = new Set(prev[groupIdx]); s.add(smId)
      return { ...prev, [groupIdx]: s }
    })
    setAddingTo(null)
  }

  // Remove smId from auto group at groupIdx, promoting master if needed
  function makeStandaloneFromAutoGroup(groupIdx: number, smId: number) {
    const masterId = masters[groupIdx]
    const currentSet = groupMembership[groupIdx]
    setGroupMembership(prev => {
      const s = new Set(prev[groupIdx]); s.delete(smId)
      return { ...prev, [groupIdx]: s }
    })
    if (smId === masterId) {
      const remaining = Array.from(currentSet).filter(id => id !== smId)
      if (remaining.length > 0) setMasters(prev => ({ ...prev, [groupIdx]: remaining[0] }))
    }
  }

  // Remove smId from extra group at extraIdx, promoting master if needed
  function makeStandaloneFromExtraGroup(extraIdx: number, smId: number) {
    const masterId = extraMasters[extraIdx]
    const currentSet = extraGroupMemberships[extraIdx]
    setExtraGroupMemberships(prev => {
      const s = new Set(prev[extraIdx]); s.delete(smId)
      return { ...prev, [extraIdx]: s }
    })
    if (smId === masterId) {
      const remaining = Array.from(currentSet).filter(id => id !== smId)
      if (remaining.length > 0) setExtraMasters(prev => ({ ...prev, [extraIdx]: remaining[0] }))
    }
  }

  // Move smId from its source group to a target (auto-N, extra-N, or 'new')
  function moveMember(fromGroupType: 'auto' | 'extra', fromIdx: number, smId: number, target: string) {
    if (fromGroupType === 'auto') makeStandaloneFromAutoGroup(fromIdx, smId)
    else makeStandaloneFromExtraGroup(fromIdx, smId)

    if (target === 'new') {
      const newIdx = Object.keys(extraGroupMemberships).length
      setExtraGroupMemberships(prev => ({ ...prev, [newIdx]: new Set([smId]) }))
      setExtraMasters(prev => ({ ...prev, [newIdx]: smId }))
    } else {
      const [tType, tIdxStr] = target.split('-')
      const tIdx = parseInt(tIdxStr)
      if (tType === 'auto') {
        setGroupMembership(prev => {
          const s = new Set(prev[tIdx]); s.add(smId)
          return { ...prev, [tIdx]: s }
        })
      } else if (tType === 'extra') {
        setExtraGroupMemberships(prev => {
          const s = new Set(prev[tIdx]); s.add(smId)
          return { ...prev, [tIdx]: s }
        })
      }
    }
    setMovingMember(null)
  }

  // Ignore: POST skip decision to backend, then remove from local state
  async function ignoreFilament(smId: number, fromGroupType?: 'auto' | 'extra', fromIdx?: number) {
    setIgnoringId(smId)
    setIgnoreErr(null)
    try {
      await postWizardMatchSkip(smId)
      if (fromGroupType === 'auto' && fromIdx !== undefined) makeStandaloneFromAutoGroup(fromIdx, smId)
      else if (fromGroupType === 'extra' && fromIdx !== undefined) makeStandaloneFromExtraGroup(fromIdx, smId)
      setIgnoredIds(prev => new Set([...prev, smId]))
    } catch (e) {
      setIgnoreErr(e instanceof Error ? e.message : String(e))
    } finally {
      setIgnoringId(null)
    }
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
      // Phase 2: build reconcile list from per-group reconcile state
      const reconcile: VariancesGroupReconcile[] = []
      for (const [idxStr, fieldMap] of Object.entries(reconcileByGroup)) {
        const groupIdx = parseInt(idxStr)
        const masterId = masters[groupIdx]
        if (masterId == null) continue
        const fields = Object.values(fieldMap)
        if (fields.length > 0) {
          reconcile.push({ master_spoolman_filament_id: masterId, fields })
        }
      }
      await postWizardSmVariants({ groups, reconcile: reconcile.length > 0 ? reconcile : undefined })

      // Expand per-group / per-standalone tare to per-spool overrides
      const tare: WizardTareOverride[] = []
      for (const [idx] of data.groups.entries()) {
        const masterId = masters[idx]
        const groupTare = parseFloat(tareBySMId[masterId] ?? '')
        if (isNaN(groupTare)) continue  // missing tare — gate above blocks Save before reaching here
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
        const groupTare = parseFloat(tareBySMId[masterId] ?? '')
        if (isNaN(groupTare)) continue  // missing tare — gate above blocks Save before reaching here
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
        const filTare = parseFloat(tareBySMId[smId] ?? '')
        if (isNaN(filTare)) continue  // missing tare — gate above blocks Save before reaching here
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

  // Build the "Move to" option list for a member in group (fromGroupType, fromIdx)
  function moveTargetOptions(fromGroupType: 'auto' | 'extra', fromIdx: number) {
    const options: { value: string; label: string }[] = []
    data.groups.forEach((g, gi) => {
      if (fromGroupType === 'auto' && gi === fromIdx) return
      if (groupMembership[gi].size > 0) {
        options.push({ value: `auto-${gi}`, label: g.base_name || `Group ${gi + 1}` })
      }
    })
    Object.entries(extraGroupMemberships).forEach(([idxStr, m]) => {
      const ei = parseInt(idxStr)
      if (fromGroupType === 'extra' && ei === fromIdx) return
      if (m.size > 0) options.push({ value: `extra-${ei}`, label: `Manual group ${ei + 1}` })
    })
    options.push({ value: 'new', label: 'New group' })
    return options
  }

  // Target options for standalone rows — all existing groups (no "from" exclusion)
  function standaloneTargetOptions(): { value: string; label: string }[] {
    const options: { value: string; label: string }[] = []
    data.groups.forEach((g, gi) => {
      if (groupMembership[gi].size > 0) {
        options.push({ value: `auto-${gi}`, label: g.base_name || `Group ${gi + 1}` })
      }
    })
    Object.entries(extraGroupMemberships).forEach(([idxStr, m]) => {
      const ei = parseInt(idxStr)
      if (m.size > 0) options.push({ value: `extra-${ei}`, label: `Manual group ${ei + 1}` })
    })
    options.push({ value: 'new', label: 'New group' })
    return options
  }

  // Move a standalone filament into an existing group (or create a new one)
  function moveFromStandalone(smId: number, target: string) {
    if (target === 'new') {
      const newIdx = Object.keys(extraGroupMemberships).length
      setExtraGroupMemberships(prev => ({ ...prev, [newIdx]: new Set([smId]) }))
      setExtraMasters(prev => ({ ...prev, [newIdx]: smId }))
    } else {
      const [tType, tIdxStr] = target.split('-')
      const tIdx = parseInt(tIdxStr)
      if (tType === 'auto') {
        setGroupMembership(prev => {
          const s = new Set(prev[tIdx]); s.add(smId)
          return { ...prev, [tIdx]: s }
        })
      } else if (tType === 'extra') {
        setExtraGroupMemberships(prev => {
          const s = new Set(prev[tIdx]); s.add(smId)
          return { ...prev, [tIdx]: s }
        })
      }
    }
    setMovingStandaloneId(null)
  }

  if (data.groups.length === 0 && effectiveUngrouped.length === 0) {
    return (
      <div className="space-y-5">
        <div>
          <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-200">Variances</h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">No variant groups or tare adjustments needed.</p>
        </div>
        <WizardActionBar onBack={prev} onNext={() => { setTareOverrides([]); next() }} />
      </div>
    )
  }


  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-200">Variances</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
          Review variant groupings and tare (empty-reel) weights. One tare per group applies to all members.
        </p>
      </div>

      {/* Top action bar */}
      <WizardActionBar
        onBack={prev}
        onNext={handleSave}
        nextLabel="Save & Next →"
        nextDisabled={missingTareCount > 0}
        busy={saving}
        busyLabel="Saving…"
        extra={missingTareCount > 0 ? (
          <span className="text-xs text-red-600 dark:text-red-400">
            Enter tare for {missingTareCount} filament{missingTareCount !== 1 ? 's' : ''} to continue
          </span>
        ) : undefined}
      />

      {/* P2.6: Sort control */}
      {(data.groups.length > 0 || data.ungrouped.length > 0) && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500 dark:text-gray-400">Sort by:</span>
          {(['vendor', 'material'] as const).map(key => (
            <button
              key={key}
              onClick={() => setSortBy(key)}
              className={`px-2.5 py-1 text-xs rounded-full border font-medium transition-colors ${
                sortBy === key
                  ? 'bg-indigo-600 text-white border-indigo-600'
                  : 'bg-white dark:bg-gray-700 text-gray-600 dark:text-gray-300 border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-600'
              }`}
            >
              {key === 'vendor' ? 'Brand A→Z' : 'Material A→Z'}
            </button>
          ))}
        </div>
      )}

      {/* Variant groups */}
      {data.groups.length > 0 && (
        <div className="space-y-4">
          <h3 className="text-sm font-medium text-gray-700 dark:text-gray-200">Variant groups</h3>
          {/* Sorted index array so original groupIdx stays valid for state keying */}
          {[...data.groups.keys()]
            .sort((a, b) => {
              const ga = data.groups[a], gb = data.groups[b]
              const va = sortBy === 'vendor' ? (ga.vendor ?? '') : (ga.material ?? '')
              const vb = sortBy === 'vendor' ? (gb.vendor ?? '') : (gb.material ?? '')
              return va.toLowerCase() < vb.toLowerCase() ? -1 : va.toLowerCase() > vb.toLowerCase() ? 1 : 0
            })
            .map((groupIdx) => {
          const group = data.groups[groupIdx]
            const masterId = masters[groupIdx]
            const membership = groupMembership[groupIdx]
            if (membership.size === 0) return null  // group dissolved — all members moved/ignored
            // Attaching to an existing Filament DB parent: that FDB parent IS the master.
            // All Spoolman colors below become its variants, so we must NOT ask the user to
            // pick a Spoolman color as master (and there's nothing to reconcile against it).
            const attaching = !!(group.existing_fdb_parent && attachDecision[groupIdx] === 'attach')
            const masterTareVal = tareBySMId[masterId] ?? ''
            const masterData = allFilamentData.get(masterId)
            const tareNeedsInput = masterTareVal === '' || isNaN(parseFloat(masterTareVal))
            const addCandidates = effectiveUngrouped.filter(f => !membership.has(f.ref.spoolman_filament_id!))
            const moveTargets = moveTargetOptions('auto', groupIdx)

            return (
              <div key={groupIdx} className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-5">
                {/* D3: attach-vs-create choice */}
                {group.existing_fdb_parent && (
                  <div className="mb-3 bg-blue-50 dark:bg-blue-900/30 border border-blue-200 dark:border-blue-800 rounded p-3">
                    <p className="text-xs font-medium text-blue-800 dark:text-blue-300 mb-2">
                      Existing Filament DB parent found: <span className="font-semibold">{group.existing_fdb_parent.name}</span>
                    </p>
                    <div className="flex items-center gap-2">
                      {(['attach', 'create_new'] as const).map(opt => (
                        <button
                          key={opt}
                          onClick={() => setAttachDecision(prev => ({ ...prev, [groupIdx]: opt }))}
                          className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                            attachDecision[groupIdx] === opt
                              ? 'bg-blue-600 text-white'
                              : 'bg-white dark:bg-gray-700 text-blue-700 dark:text-blue-300 border border-blue-300 dark:border-blue-700 hover:bg-blue-50 dark:hover:bg-gray-600'
                          }`}
                        >
                          {opt === 'attach' ? `Attach to «${group.existing_fdb_parent.name}»` : 'Create new parent'}
                        </button>
                      ))}
                      <HelpTip text="Attach: new colors become variants of your existing Filament DB parent. Create new: a separate parent is created for this group." />
                    </div>
                    {attaching && (
                      <p className="mt-2 text-xs text-blue-700 dark:text-blue-300">
                        <span className="font-semibold">{group.existing_fdb_parent!.name}</span> is the master.
                        All colors below attach to it as <span className="font-medium">variants</span> — no Spoolman color is the master.
                      </p>
                    )}
                  </div>
                )}

                {/* Group header: name + finish pill + tare */}
                <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="font-medium text-gray-800 dark:text-gray-100">{group.base_name}</p>
                    <div className="flex flex-wrap gap-2 text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                      {group.vendor && <span>{group.vendor}</span>}
                      {group.material && <span>{group.material}</span>}
                      {group.finish && (
                        <span className="bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300 px-1.5 py-0.5 rounded capitalize">{group.finish}</span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <label className="flex items-center text-xs text-gray-500 dark:text-gray-400 whitespace-nowrap">
                      Empty-reel tare (g):
                      <HelpTip text="Weight of the empty spool. Used to convert Spoolman's net weight to Filament DB's gross weight; one tare applies to the whole group." />
                    </label>
                    <input
                      type="number" min="0" step="1"
                      placeholder="required"
                      value={masterTareVal}
                      onChange={e => setTareBySMId(prev => ({ ...prev, [masterId]: e.target.value }))}
                      className={`w-20 border rounded px-2 py-1 text-xs text-right focus:outline-none focus:ring-2 dark:bg-gray-700 dark:text-gray-100 ${
                        tareNeedsInput
                          ? 'border-red-400 dark:border-red-500 focus:ring-red-400'
                          : 'border-gray-300 dark:border-gray-600 focus:ring-indigo-400'
                      }`}
                    />
                    {tareNeedsInput && (
                      <span className="text-xs bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300 px-1.5 py-0.5 rounded">required</span>
                    )}
                  </div>
                </div>

                <div className="mb-3 text-xs text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-900/30 border border-amber-200 dark:border-amber-800 rounded px-3 py-2">
                  {attaching
                    ? <>All colors here attach to «{group.existing_fdb_parent!.name}» and use this empty-reel tare: <strong>{masterTareVal} g</strong>. Filament DB stores one tare per filament.</>
                    : <>All variants in this group will use the master's empty-reel tare: <strong>{masterTareVal} g</strong>. Filament DB stores one tare per filament.</>}
                </div>

                {/* Per-member rows with labeled action buttons */}
                <div className="space-y-1">
                  {Array.from(membership).filter(id => !ignoredIds.has(id)).map(smId => {
                    const filData = allFilamentData.get(smId)
                    if (!filData) return null
                    const isMaster = !attaching && smId === masterId
                    const conflicts = attaching ? [] : getLiveConflicts(groupIdx, smId)
                    const isMoving = movingMember?.smId === smId && movingMember.fromGroupType === 'auto' && movingMember.fromIdx === groupIdx
                    const isIgnoring = ignoringId === smId
                    return (
                      <div key={smId} className="flex items-start gap-2 p-2 rounded hover:bg-gray-50 dark:hover:bg-gray-700/40">
                        <span className="flex items-start">
                          {attaching ? (
                            // No master radio when attaching — the existing FDB parent is the master.
                            <span className="mt-1 w-3.5 h-3.5 shrink-0" aria-hidden="true" />
                          ) : (
                            <>
                              <input
                                type="radio"
                                name={`master-${groupIdx}`}
                                checked={isMaster}
                                onChange={() => pickMaster(groupIdx, smId)}
                                className="mt-1 accent-indigo-600 shrink-0"
                                title="Set as master (parent)"
                              />
                              {isMaster && (
                                <HelpTip text="The master becomes (or maps to) the Filament DB parent. Variants inherit its print settings." />
                              )}
                            </>
                          )}
                        </span>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <ColorSwatch hex={filData.color_hex} />
                            <span className={`text-sm ${isMaster ? 'font-semibold text-indigo-700 dark:text-indigo-300' : 'text-gray-700 dark:text-gray-200'}`}>
                              {filData.ref.name}
                            </span>
                            {filData.ref.openprinttag && <OptBadge />}
                            {isMaster && <span className="text-xs bg-indigo-100 text-indigo-700 px-1.5 py-0.5 rounded">master</span>}
                            {filData.color_hex && <span className="text-xs text-gray-400 dark:text-gray-500 font-mono">{filData.color_hex}</span>}
                            {/* Type chip — primary source is SM material; FDB material_type shown as mismatch only */}
                            <span className="text-xs bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-800 px-1.5 py-0.5 rounded">
                              {filData.material ?? '—'}
                            </span>
                            {filData.material_type && filData.material_type !== filData.material && (
                              <span className="text-xs bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-800 px-1.5 py-0.5 rounded">
                                FDB: {filData.material_type}
                              </span>
                            )}
                            {/* Diameter chip — always shown, dash when null */}
                            <span className="text-xs bg-gray-50 dark:bg-gray-700 text-gray-600 dark:text-gray-300 border border-gray-200 dark:border-gray-600 px-1.5 py-0.5 rounded">
                              {filData.diameter != null ? `${filData.diameter} mm` : '⌀ —'}
                            </span>
                            {/* Density chip — always shown, dash when null */}
                            <span className="text-xs bg-gray-50 dark:bg-gray-700 text-gray-600 dark:text-gray-300 border border-gray-200 dark:border-gray-600 px-1.5 py-0.5 rounded">
                              {filData.density != null ? `${filData.density} g/cm³` : 'ρ —'}
                            </span>
                            {/* Temps — editable inputs for master, read-only chip for non-master */}
                            {isMaster ? (
                              <span className="inline-flex items-center gap-1 text-xs bg-orange-50 dark:bg-orange-900/30 text-orange-700 dark:text-orange-300 border border-orange-200 dark:border-orange-800 px-1.5 py-0.5 rounded">
                                🌡
                                <input
                                  type="number"
                                  min="0"
                                  step="1"
                                  placeholder={filData.settings_extruder_temp != null ? String(filData.settings_extruder_temp) : '—'}
                                  value={
                                    reconcileByGroup[groupIdx]?.['nozzle_temp']?.value != null
                                      ? String(reconcileByGroup[groupIdx]['nozzle_temp'].value)
                                      : filData.settings_extruder_temp != null
                                        ? String(filData.settings_extruder_temp)
                                        : ''
                                  }
                                  onChange={e => {
                                    const raw = e.target.value
                                    if (raw === '') {
                                      // Clear override — remove the key entirely
                                      setReconcileByGroup(prev => {
                                        const groupMap = { ...(prev[groupIdx] ?? {}) }
                                        delete groupMap['nozzle_temp']
                                        return { ...prev, [groupIdx]: groupMap }
                                      })
                                      return
                                    }
                                    const parsed = parseInt(raw, 10)
                                    if (isNaN(parsed)) return
                                    setReconcileByGroup(prev => ({
                                      ...prev,
                                      [groupIdx]: {
                                        ...(prev[groupIdx] ?? {}),
                                        nozzle_temp: { field: 'nozzle_temp', value: parsed, source: 'manual', source_spoolman_filament_id: null },
                                      },
                                    }))
                                  }}
                                  className="w-12 bg-transparent border-b border-orange-300 dark:border-orange-700 text-center focus:outline-none focus:border-orange-500"
                                  title="Nozzle temp (°C)"
                                />
                                °/
                                <input
                                  type="number"
                                  min="0"
                                  step="1"
                                  placeholder={filData.settings_bed_temp != null ? String(filData.settings_bed_temp) : '—'}
                                  value={
                                    reconcileByGroup[groupIdx]?.['bed_temp']?.value != null
                                      ? String(reconcileByGroup[groupIdx]['bed_temp'].value)
                                      : filData.settings_bed_temp != null
                                        ? String(filData.settings_bed_temp)
                                        : ''
                                  }
                                  onChange={e => {
                                    const raw = e.target.value
                                    if (raw === '') {
                                      // Clear override — remove the key entirely
                                      setReconcileByGroup(prev => {
                                        const groupMap = { ...(prev[groupIdx] ?? {}) }
                                        delete groupMap['bed_temp']
                                        return { ...prev, [groupIdx]: groupMap }
                                      })
                                      return
                                    }
                                    const parsed = parseInt(raw, 10)
                                    if (isNaN(parsed)) return
                                    setReconcileByGroup(prev => ({
                                      ...prev,
                                      [groupIdx]: {
                                        ...(prev[groupIdx] ?? {}),
                                        bed_temp: { field: 'bed_temp', value: parsed, source: 'manual', source_spoolman_filament_id: null },
                                      },
                                    }))
                                  }}
                                  className="w-12 bg-transparent border-b border-orange-300 dark:border-orange-700 text-center focus:outline-none focus:border-orange-500"
                                  title="Bed temp (°C)"
                                />
                                °
                              </span>
                            ) : (filData.settings_extruder_temp != null || filData.settings_bed_temp != null) ? (
                              <span className="text-xs bg-orange-50 dark:bg-orange-900/30 text-orange-700 dark:text-orange-300 border border-orange-200 dark:border-orange-800 px-1.5 py-0.5 rounded">
                                {filData.settings_extruder_temp ?? '—'}° / {filData.settings_bed_temp ?? '—'}°
                              </span>
                            ) : null}
                            <DeepLinks spoolmanFilamentId={filData.ref.spoolman_filament_id} />
                          </div>
                          {conflicts.length > 0 && (
                            <div className="mt-1 text-xs text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-900/30 border border-amber-200 dark:border-amber-800 rounded px-2 py-1">
                              Conflicts with master:
                              {conflicts.map(c => (
                                <span key={c.field} className="ml-1">
                                  <span className="font-medium">{CONFLICT_FIELD_LABELS[c.field] ?? c.field}</span>
                                  {' '}({String(c.member_value)} vs {String(c.master_value)})
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                        {/* Per-member actions */}
                        <div className="flex items-center gap-1 shrink-0 mt-0.5">
                          {isMoving ? (
                            <>
                              <select
                                className="text-xs border border-gray-200 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 rounded px-2 py-1"
                                defaultValue=""
                                onChange={e => { if (e.target.value) moveMember('auto', groupIdx, smId, e.target.value) }}
                                autoFocus
                              >
                                <option value="" disabled>Move to…</option>
                                {moveTargets.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                              </select>
                              <button onClick={() => setMovingMember(null)} className="text-xs text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 px-1">✕</button>
                            </>
                          ) : (
                            <>
                              <button
                                onClick={() => setMovingMember({ fromGroupType: 'auto', fromIdx: groupIdx, smId })}
                                className="text-xs px-2 py-1 text-gray-600 dark:text-gray-300 border border-gray-200 dark:border-gray-600 rounded hover:bg-gray-100 dark:hover:bg-gray-700"
                              >Move to…</button>
                              <button
                                onClick={() => makeStandaloneFromAutoGroup(groupIdx, smId)}
                                className="text-xs px-2 py-1 text-gray-600 dark:text-gray-300 border border-gray-200 dark:border-gray-600 rounded hover:bg-gray-100 dark:hover:bg-gray-700"
                              >Standalone</button>
                              <button
                                disabled={isIgnoring}
                                onClick={() => ignoreFilament(smId, 'auto', groupIdx)}
                                className="text-xs px-2 py-1 text-red-600 dark:text-red-400 border border-red-200 dark:border-red-800 rounded hover:bg-red-50 dark:hover:bg-red-900/20 disabled:opacity-50"
                              >{isIgnoring ? '…' : 'Ignore'}</button>
                            </>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>

                {/* Phase 2: per-group reconcile UI for conflicting fields */}
                {(() => {
                  // Attaching to an existing FDB parent: it's the master and holds the canonical
                  // properties, so there's no Spoolman master to reconcile against — hide the section.
                  if (attaching) return null
                  // Collect all conflicts across all members (excluding master).
                  // material_type is derived/display-only and not in _RECONCILE_FIELD_MAP — skip it.
                  const conflictFields = new Map<string, { values: Map<string, { smId: number; value: unknown }[]> }>()
                  for (const smId of Array.from(membership)) {
                    const filData = allFilamentData.get(smId)
                    if (!filData || smId === masterId) continue
                    const conflicts = getLiveConflicts(groupIdx, smId)
                    for (const c of conflicts) {
                      if (c.field === 'material_type') continue  // display-only, not reconcilable
                      if (!conflictFields.has(c.field)) conflictFields.set(c.field, { values: new Map() })
                      const valKey = String(c.member_value)
                      const entry = conflictFields.get(c.field)!
                      if (!entry.values.has(valKey)) entry.values.set(valKey, [])
                      entry.values.get(valKey)!.push({ smId, value: c.member_value })
                    }
                  }
                  if (conflictFields.size === 0) return null
                  const masterData = allFilamentData.get(masterId)
                  return (
                    <div className="mt-3 bg-amber-50 dark:bg-amber-900/30 border border-amber-200 dark:border-amber-800 rounded p-3 space-y-2">
                      <p className="text-xs font-medium text-amber-800 dark:text-amber-300">Reconcile conflicting properties</p>
                      <p className="text-xs text-amber-700 dark:text-amber-300">Choose which value to use for each conflicting field. This will be applied to both Filament DB and Spoolman on execute.</p>
                      {Array.from(conflictFields.entries()).map(([rawField, { values }]) => {
                        // Translate raw SM field name → canonical key for backend _RECONCILE_FIELD_MAP
                        const canonicalKey = CONFLICT_FIELD_TO_CANONICAL[rawField] ?? rawField
                        const current = reconcileByGroup[groupIdx]?.[canonicalKey]
                        const masterVal = masterData ? (masterData as Record<string, unknown>)[rawField] : undefined
                        // All distinct values: master value + member values
                        const allValues: { label: string; value: unknown; smId: number | null }[] = [
                          { label: `Master (${String(masterVal ?? 'none')})`, value: masterVal, smId: masterId },
                          ...Array.from(values.entries()).map(([valKey, entries]) => ({
                            label: `${valKey} (${entries.map(e => e.smId).join(', ')})`,
                            value: entries[0].value,
                            smId: entries[0].smId,
                          })),
                        ]
                        return (
                          <div key={canonicalKey} className="flex flex-wrap items-center gap-2">
                            <span className="text-xs font-medium text-gray-700 dark:text-gray-200 w-28 shrink-0">{rawField}:</span>
                            {allValues.map((opt, i) => {
                              const isSelected = current?.value === opt.value ||
                                (current == null && i === 0)  // default: master value
                              return (
                                <button
                                  key={i}
                                  onClick={() => setReconcileByGroup(prev => ({
                                    ...prev,
                                    [groupIdx]: {
                                      ...(prev[groupIdx] ?? {}),
                                      // Key by canonical name; value.field is also canonical
                                      [canonicalKey]: {
                                        field: canonicalKey,
                                        value: opt.value,
                                        source: 'spoolman_filament',
                                        source_spoolman_filament_id: opt.smId,
                                      },
                                    },
                                  }))}
                                  className={`text-xs px-2 py-1 rounded border transition-colors ${
                                    isSelected
                                      ? 'bg-amber-600 text-white border-amber-600'
                                      : 'bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-200 border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-600'
                                  }`}
                                >
                                  {opt.label}
                                </button>
                              )
                            })}
                            <input
                              type="text"
                              placeholder="Manual value…"
                              className="text-xs border border-gray-300 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 rounded px-2 py-1 w-24 focus:outline-none focus:ring-1 focus:ring-amber-400"
                              onBlur={e => {
                                const v = e.target.value.trim()
                                if (!v) return
                                const num = parseFloat(v)
                                const parsed = isNaN(num) ? v : num
                                setReconcileByGroup(prev => ({
                                  ...prev,
                                  [groupIdx]: {
                                    ...(prev[groupIdx] ?? {}),
                                    [canonicalKey]: { field: canonicalKey, value: parsed, source: 'manual', source_spoolman_filament_id: null },
                                  },
                                }))
                              }}
                            />
                          </div>
                        )
                      })}
                    </div>
                  )
                })()}

                {addCandidates.length > 0 && (
                  <div className="mt-3">
                    {addingTo === groupIdx ? (
                      <div className="flex items-center gap-2">
                        <select
                          className="text-xs border border-gray-200 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 rounded px-2 py-1 flex-1"
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
                          className="text-xs text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 shrink-0">Cancel</button>
                      </div>
                    ) : (
                      <button onClick={() => setAddingTo(groupIdx)}
                        className="text-xs text-indigo-600 dark:text-indigo-400 hover:text-indigo-800 font-medium">
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
            <h3 className="text-sm font-medium text-gray-700 dark:text-gray-200">Standalone filaments</h3>
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
            <p className="text-xs text-gray-500 dark:text-gray-400">Select one more to enable grouping.</p>
          )}
          <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 divide-y divide-gray-100 dark:divide-gray-700">
            {[...effectiveUngrouped]
              .sort((a, b) => {
                const va = sortBy === 'vendor' ? (a.ref.vendor ?? '') : (a.material ?? '')
                const vb = sortBy === 'vendor' ? (b.ref.vendor ?? '') : (b.material ?? '')
                return va.toLowerCase() < vb.toLowerCase() ? -1 : va.toLowerCase() > vb.toLowerCase() ? 1 : 0
              })
              .map(f => {
              const smId = f.ref.spoolman_filament_id!
              const isIgnoring = ignoringId === smId
              return (
                <div key={smId} className="flex flex-wrap items-center gap-3 px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-700/40">
                  {/* Manual grouping checkbox */}
                  <input
                    type="checkbox"
                    checked={selectedForGrouping.has(smId)}
                    onChange={() => toggleSelectForGrouping(smId)}
                    className="h-4 w-4 rounded border-gray-300 dark:border-gray-600 dark:bg-gray-700 text-indigo-600 focus:ring-indigo-500 shrink-0"
                    title="Select to group as variants"
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <ColorSwatch hex={f.color_hex} />
                      <span className="text-sm text-gray-700 dark:text-gray-200">{f.ref.name}</span>
                      {f.ref.openprinttag && <OptBadge />}
                      {f.ref.vendor && <span className="text-xs text-gray-400 dark:text-gray-500">{f.ref.vendor}</span>}
                      {f.color_hex && <span className="text-xs font-mono text-gray-400 dark:text-gray-500">{f.color_hex}</span>}
                      {/* Type chip — primary source is SM material; FDB material_type shown as mismatch only */}
                      <span className="text-xs bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-800 px-1.5 py-0.5 rounded">
                        {f.material ?? '—'}
                      </span>
                      {f.material_type && f.material_type !== f.material && (
                        <span className="text-xs bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-800 px-1.5 py-0.5 rounded">
                          FDB: {f.material_type}
                        </span>
                      )}
                      {/* Diameter chip — always shown, dash when null */}
                      <span className="text-xs bg-gray-50 dark:bg-gray-700 text-gray-600 dark:text-gray-300 border border-gray-200 dark:border-gray-600 px-1.5 py-0.5 rounded">
                        {f.diameter != null ? `${f.diameter} mm` : '⌀ —'}
                      </span>
                      {/* Density chip — always shown, dash when null */}
                      <span className="text-xs bg-gray-50 dark:bg-gray-700 text-gray-600 dark:text-gray-300 border border-gray-200 dark:border-gray-600 px-1.5 py-0.5 rounded">
                        {f.density != null ? `${f.density} g/cm³` : 'ρ —'}
                      </span>
                      {/* Temps chip — shown when at least one temp is set */}
                      {(f.settings_extruder_temp != null || f.settings_bed_temp != null) && (
                        <span className="text-xs bg-orange-50 dark:bg-orange-900/30 text-orange-700 dark:text-orange-300 border border-orange-200 dark:border-orange-800 px-1.5 py-0.5 rounded">
                          {f.settings_extruder_temp ?? '—'}° / {f.settings_bed_temp ?? '—'}°
                        </span>
                      )}
                      {f.suggest_exclude && (
                        <span className="inline-flex items-center gap-1">
                          <span className="text-xs bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 px-1.5 py-0.5 rounded">
                            {f.conflicts && f.conflicts.length > 0
                              ? (() => {
                                  const labels = [...new Set(f.conflicts.map(c => CONFLICT_FIELD_LABELS[c.field] ?? c.field))]
                                  return `suggested standalone — ${labels.join(', ')} differ`
                                })()
                              : 'suggested standalone'}
                          </span>
                          <HelpTip text="This member's print properties differ from the master's, so it may not belong in the group. Move it out or reconcile the values below." />
                        </span>
                      )}
                      <DeepLinks spoolmanFilamentId={smId} />
                    </div>
                  </div>
                  <label className="flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400 shrink-0">
                    Tare (g):
                    {(() => {
                      const standaloneTareVal = tareBySMId[smId] ?? ''
                      const standaloneTareNeedsInput = standaloneTareVal === '' || isNaN(parseFloat(standaloneTareVal))
                      return (
                        <>
                          <input
                            type="number" min="0" step="1"
                            placeholder="required"
                            value={standaloneTareVal}
                            onChange={e => setTareBySMId(prev => ({ ...prev, [smId]: e.target.value }))}
                            className={`w-20 border rounded px-2 py-1 text-xs text-right focus:outline-none focus:ring-2 dark:bg-gray-700 dark:text-gray-100 ${
                              standaloneTareNeedsInput
                                ? 'border-red-400 dark:border-red-500 focus:ring-red-400'
                                : 'border-gray-300 dark:border-gray-600 focus:ring-indigo-400'
                            }`}
                          />
                          {standaloneTareNeedsInput && (
                            <span className="text-xs bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300 px-1.5 py-0.5 rounded">required</span>
                          )}
                        </>
                      )
                    })()}
                  </label>
                  {movingStandaloneId === smId ? (
                    <>
                      <select
                        className="text-xs border border-gray-200 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 rounded px-2 py-1 shrink-0"
                        defaultValue=""
                        onChange={e => { if (e.target.value) moveFromStandalone(smId, e.target.value) }}
                        autoFocus
                      >
                        <option value="" disabled>Move to…</option>
                        {standaloneTargetOptions().map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                      </select>
                      <button onClick={() => setMovingStandaloneId(null)} className="text-xs text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 px-1 shrink-0">✕</button>
                    </>
                  ) : (
                    <button
                      onClick={() => setMovingStandaloneId(smId)}
                      className="text-xs px-2 py-1 text-gray-600 dark:text-gray-300 border border-gray-200 dark:border-gray-600 rounded hover:bg-gray-100 dark:hover:bg-gray-700 shrink-0"
                    >Move to…</button>
                  )}
                  <button
                    disabled={isIgnoring}
                    onClick={() => ignoreFilament(smId)}
                    className="text-xs px-2 py-1 text-red-600 dark:text-red-400 border border-red-200 dark:border-red-800 rounded hover:bg-red-50 dark:hover:bg-red-900/20 disabled:opacity-50 shrink-0"
                  >{isIgnoring ? '…' : 'Ignore'}</button>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Extra groups from manual selection */}
      {Object.keys(extraGroupMemberships).length > 0 && (
        <div className="space-y-4">
          <h3 className="text-sm font-medium text-gray-700 dark:text-gray-200">Manually grouped</h3>
          {Object.entries(extraGroupMemberships).map(([idxStr, membership]) => {
            const extraIdx = parseInt(idxStr)
            if (membership.size === 0) return null
            const masterId = extraMasters[extraIdx]
            const masterTareVal = tareBySMId[masterId] ?? ''
            const extraTareNeedsInput = masterTareVal === '' || isNaN(parseFloat(masterTareVal))
            const moveTargetsExtra = moveTargetOptions('extra', extraIdx)
            return (
              <div key={extraIdx} className="bg-white dark:bg-gray-800 rounded-lg border border-indigo-200 dark:border-indigo-800 p-4 space-y-2">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium text-gray-700 dark:text-gray-200">Manual group {extraIdx + 1}</p>
                  <button
                    onClick={() => {
                      setExtraGroupMemberships(prev => { const n = { ...prev }; delete n[extraIdx]; return n })
                      setExtraMasters(prev => { const n = { ...prev }; delete n[extraIdx]; return n })
                    }}
                    className="text-xs text-gray-400 dark:text-gray-500 hover:text-red-500"
                  >
                    Disband
                  </button>
                </div>
                {Array.from(membership).filter(id => !ignoredIds.has(id)).map(smId => {
                  const filData = allFilamentData.get(smId)
                  if (!filData) return null
                  const isMaster = smId === masterId
                  const isMoving = movingMember?.smId === smId && movingMember.fromGroupType === 'extra' && movingMember.fromIdx === extraIdx
                  const isIgnoring = ignoringId === smId
                  return (
                    <div key={smId} className="flex items-center gap-2">
                      <input type="radio" name={`extra-master-${extraIdx}`}
                        checked={isMaster}
                        onChange={() => setExtraMasters(prev => ({ ...prev, [extraIdx]: smId }))}
                        className="accent-indigo-600 shrink-0"
                        title="Set as master" />
                      <span className={`text-sm flex-1 min-w-0 ${isMaster ? 'font-semibold text-indigo-700 dark:text-indigo-300' : 'text-gray-700 dark:text-gray-200'}`}>
                        {filData.ref.name}
                      </span>
                      {filData.ref.openprinttag && <OptBadge />}
                      {isMaster && <span className="text-xs bg-indigo-100 text-indigo-700 px-1.5 py-0.5 rounded">master</span>}
                      <div className="flex items-center gap-1 shrink-0">
                        {isMoving ? (
                          <>
                            <select
                              className="text-xs border border-gray-200 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 rounded px-2 py-1"
                              defaultValue=""
                              onChange={e => { if (e.target.value) moveMember('extra', extraIdx, smId, e.target.value) }}
                              autoFocus
                            >
                              <option value="" disabled>Move to…</option>
                              {moveTargetsExtra.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                            </select>
                            <button onClick={() => setMovingMember(null)} className="text-xs text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 px-1">✕</button>
                          </>
                        ) : (
                          <>
                            <button
                              onClick={() => setMovingMember({ fromGroupType: 'extra', fromIdx: extraIdx, smId })}
                              className="text-xs px-2 py-1 text-gray-600 dark:text-gray-300 border border-gray-200 dark:border-gray-600 rounded hover:bg-gray-100 dark:hover:bg-gray-700"
                            >Move to…</button>
                            <button
                              onClick={() => makeStandaloneFromExtraGroup(extraIdx, smId)}
                              className="text-xs px-2 py-1 text-gray-600 dark:text-gray-300 border border-gray-200 dark:border-gray-600 rounded hover:bg-gray-100 dark:hover:bg-gray-700"
                            >Standalone</button>
                            <button
                              disabled={isIgnoring}
                              onClick={() => ignoreFilament(smId, 'extra', extraIdx)}
                              className="text-xs px-2 py-1 text-red-600 dark:text-red-400 border border-red-200 dark:border-red-800 rounded hover:bg-red-50 dark:hover:bg-red-900/20 disabled:opacity-50"
                            >{isIgnoring ? '…' : 'Ignore'}</button>
                          </>
                        )}
                      </div>
                    </div>
                  )
                })}
                <label className="flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400">
                  Group tare (g):
                  <input type="number" min="0" step="1"
                    placeholder="required"
                    value={masterTareVal}
                    onChange={e => setTareBySMId(prev => ({ ...prev, [masterId]: e.target.value }))}
                    className={`w-20 border rounded px-2 py-1 text-xs text-right focus:outline-none focus:ring-2 dark:bg-gray-700 dark:text-gray-100 ${
                      extraTareNeedsInput
                        ? 'border-red-400 dark:border-red-500 focus:ring-red-400'
                        : 'border-gray-300 dark:border-gray-600 focus:ring-indigo-400'
                    }`} />
                  {extraTareNeedsInput && (
                    <span className="text-xs bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300 px-1.5 py-0.5 rounded">required</span>
                  )}
                </label>
              </div>
            )
          })}
        </div>
      )}

      {ignoreErr && <p className="text-sm text-red-600 dark:text-red-400">Ignore failed: {ignoreErr}</p>}
      {saveErr && <p className="text-sm text-red-600 dark:text-red-400">{saveErr}</p>}

      {/* Bottom action bar */}
      <WizardActionBar
        onBack={prev}
        onNext={handleSave}
        nextLabel="Save & Next →"
        nextDisabled={missingTareCount > 0}
        busy={saving}
        busyLabel="Saving…"
        extra={missingTareCount > 0 ? (
          <span className="text-xs text-red-600 dark:text-red-400">
            Enter tare for {missingTareCount} filament{missingTareCount !== 1 ? 's' : ''} to continue
          </span>
        ) : undefined}
      />
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

  // FDB direction: count rows where tare is unknown and no override has been entered
  const missingTareFdbCount = useMemo(() => {
    if (!weightsData) return 0
    return weightsData.rows.filter(row => {
      if (row.tare_source !== 'needs_input') return false
      const key = `${row.spoolman_spool_id ?? 'null'}_${row.filamentdb_spool_id ?? 'null'}`
      const val = overrides[key]
      return !val || isNaN(parseFloat(val))
    }).length
  }, [weightsData, overrides])

  if (varLoading || wtLoading) return <p className="text-gray-500 dark:text-gray-400">Loading variant groups…</p>
  if (varError || wtError) return <p className="text-red-600 dark:text-red-400">{varError ?? wtError}</p>
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
        <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-100">Variances</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">Review variant groupings and weight conversions.</p>
      </div>

      {/* Top action bar */}
      <WizardActionBar
        onBack={prev}
        onNext={handleSave}
        nextLabel="Save & Next →"
        nextDisabled={missingTareFdbCount > 0}
        busy={saving}
        busyLabel="Saving…"
        extra={missingTareFdbCount > 0 ? (
          <span className="text-xs text-red-600 dark:text-red-400">
            Enter tare for {missingTareFdbCount} spool{missingTareFdbCount !== 1 ? 's' : ''} to continue
          </span>
        ) : undefined}
      />

      {/* FDB variant groups */}
      {(variantsData.fdb_groups?.length ?? 0) > 0 ? (
        <div className="space-y-3">
          <h3 className="text-sm font-medium text-gray-700 dark:text-gray-200">Variant groups</h3>
          {variantsData.fdb_groups.map((group, i) => (
            <div key={i} className={`bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-5 ${skipped.has(i) ? 'opacity-50' : ''}`}>
              <div className="flex items-center justify-between mb-3">
                <div>
                  <p className="font-medium text-gray-800 dark:text-gray-100">{group.base_name}</p>
                  {group.vendor && <p className="text-xs text-gray-500 dark:text-gray-400">{group.vendor}</p>}
                </div>
                <button onClick={() => toggleSkip(i)}
                  className={`px-3 py-1 rounded text-xs font-medium ${skipped.has(i) ? 'bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-300' : 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-300 hover:bg-yellow-200 dark:hover:bg-yellow-800/40'}`}>
                  {skipped.has(i) ? 'Unskip' : 'Skip'}
                </button>
              </div>
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase w-14">Parent</span>
                  <span className="text-sm font-medium">{group.suggested_parent.name}</span>
                  <DeepLinks filamentdbFilamentId={group.suggested_parent.filamentdb_filament_id} />
                </div>
                <div className="pl-14 space-y-1">
                  {group.variants.map(v => (
                    <div key={v.filamentdb_filament_id} className="flex items-center gap-2">
                      <span className="text-sm text-gray-600 dark:text-gray-300">{v.name}</span>
                      {v.color && <span className="text-xs text-gray-400 dark:text-gray-500">{v.color}</span>}
                      <DeepLinks filamentdbFilamentId={v.filamentdb_filament_id} />
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-gray-500 dark:text-gray-400">No variant groups detected in Filament DB.</p>
      )}

      {/* Weight review */}
      {weightsData && weightsData.rows.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-sm font-medium text-gray-700 dark:text-gray-200">Weight conversions</h3>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            Override tare (empty reel) per spool if needed.
            Direction: <strong>{weightsData.direction.replace(/_/g, ' ')}</strong>.
          </p>
          <div className="overflow-x-auto bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
            <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700 text-sm">
              <thead className="bg-gray-50 dark:bg-gray-900/40">
                <tr>
                  {['Spool', 'Net (g)', 'Gross (g)', 'Tare (g)', 'Source', 'Override tare', 'Links'].map(h => (
                    <th key={h} className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                {weightsData.rows.map(row => {
                  const key = rowKey(row.spoolman_spool_id, row.filamentdb_spool_id)
                  return (
                    <tr key={key} className="hover:bg-gray-50 dark:hover:bg-gray-700/40">
                      <td className="px-4 py-3 font-medium text-gray-900 dark:text-gray-100">{row.name ?? '—'}</td>
                      <td className="px-4 py-3 text-gray-600 dark:text-gray-300">{row.net_weight?.toFixed(1) ?? '—'}</td>
                      <td className="px-4 py-3 text-gray-600 dark:text-gray-300">{row.gross_weight?.toFixed(1) ?? '—'}</td>
                      <td className="px-4 py-3 text-gray-600 dark:text-gray-300">
                        {row.tare != null ? row.tare.toFixed(1) : <span className="text-red-500 dark:text-red-400">—</span>}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`text-xs px-1.5 py-0.5 rounded ${
                          row.tare_source === 'needs_input'
                            ? 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300'
                            : row.tare_source === 'default'
                              ? 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-300'
                              : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300'
                        }`}>
                          {row.tare_source === 'needs_input' ? 'required' : row.tare_source}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        {(() => {
                          const overrideVal = overrides[key] ?? ''
                          const needsOverride = row.tare_source === 'needs_input' && (!overrideVal || isNaN(parseFloat(overrideVal)))
                          return (
                            <input type="number" min="0" step="1"
                              placeholder={row.tare != null ? row.tare.toFixed(0) : 'required'}
                              value={overrideVal}
                              onChange={e => setOverrides(o => ({ ...o, [key]: e.target.value }))}
                              className={`w-20 border rounded px-2 py-1 text-xs text-right focus:outline-none focus:ring-2 dark:bg-gray-700 dark:text-gray-100 ${
                                needsOverride
                                  ? 'border-red-400 dark:border-red-500 focus:ring-red-400'
                                  : 'border-gray-300 dark:border-gray-600 focus:ring-indigo-400'
                              }`} />
                          )
                        })()}
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

      {saveErr && <p className="text-sm text-red-600 dark:text-red-400">{saveErr}</p>}

      {/* Bottom action bar */}
      <WizardActionBar
        onBack={prev}
        onNext={handleSave}
        nextLabel="Save & Next →"
        nextDisabled={missingTareFdbCount > 0}
        busy={saving}
        busyLabel="Saving…"
        extra={missingTareFdbCount > 0 ? (
          <span className="text-xs text-red-600 dark:text-red-400">
            Enter tare for {missingTareFdbCount} spool{missingTareFdbCount !== 1 ? 's' : ''} to continue
          </span>
        ) : undefined}
      />
    </div>
  )
}
