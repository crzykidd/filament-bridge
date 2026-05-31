import { useEffect, useRef, useState } from 'react'
import { getWizardMatches, postWizardMatches } from '../../api/client'
import { useApi } from '../../api/hooks'
import { DeepLinks } from '../../components/DeepLinks'
import type { AmbiguousRow, FilamentRef, MatchDecision, MatchPairRow } from '../../api/types'
import type { WizardCtx } from './index'

type SubgroupDim = 'material' | 'vendor'
type SortDir = 'asc' | 'desc'
interface SortState { col: string; dir: SortDir }
type SectionKey = 'matched' | 'unmatched_sm' | 'ambiguous' | 'unmatched_fdb'

function FilamentTag({ filament: f }: { filament: FilamentRef }) {
  if (!f) return null
  return (
    <span className="text-sm">
      <span className="font-medium">{f.name ?? '—'}</span>
      {f.vendor && <span className="text-gray-500"> · {f.vendor}</span>}
      {f.color && <span className="text-gray-400"> · {f.color}</span>}
    </span>
  )
}

function TriCheckbox({
  checked, indeterminate, onChange, disabled,
}: {
  checked: boolean; indeterminate: boolean; onChange: (v: boolean) => void; disabled?: boolean
}) {
  const ref = useRef<HTMLInputElement>(null)
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = indeterminate
  }, [indeterminate])
  return (
    <input
      ref={ref}
      type="checkbox"
      checked={checked}
      disabled={disabled}
      onChange={e => onChange(e.target.checked)}
      className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 disabled:cursor-not-allowed"
    />
  )
}

function SortBtn({ col, label, sort, onSort }: {
  col: string; label: string; sort: SortState; onSort: (col: string) => void
}) {
  const active = sort.col === col
  return (
    <button
      onClick={() => onSort(col)}
      className={`flex items-center gap-0.5 text-xs font-medium uppercase tracking-wide ${
        active ? 'text-indigo-600' : 'text-gray-400 hover:text-indigo-400'
      }`}
    >
      {label}
      {active && <span className="ml-0.5">{sort.dir === 'asc' ? '↑' : '↓'}</span>}
    </button>
  )
}

function getField(ref: FilamentRef, col: string): string {
  if (col === 'name') return ref.name ?? ''
  if (col === 'vendor') return ref.vendor ?? ''
  if (col === 'material') return ref.material ?? ''
  if (col === 'color') return ref.color ?? ''
  return ''
}

function sortByRef<T>(items: T[], getRef: (i: T) => FilamentRef, sort: SortState): T[] {
  return [...items].sort((a, b) => {
    const cmp = getField(getRef(a), sort.col).localeCompare(getField(getRef(b), sort.col))
    return sort.dir === 'asc' ? cmp : -cmp
  })
}

function groupBy<T>(items: T[], keyFn: (i: T) => string): [string, T[]][] {
  const map = new Map<string, T[]>()
  for (const item of items) {
    const k = keyFn(item)
    if (!map.has(k)) map.set(k, [])
    map.get(k)!.push(item)
  }
  return [...map.entries()].sort(([a], [b]) => a.localeCompare(b))
}

function triState(flags: boolean[]): { checked: boolean; indeterminate: boolean } {
  const n = flags.filter(Boolean).length
  if (n === 0) return { checked: false, indeterminate: false }
  if (n === flags.length) return { checked: true, indeterminate: false }
  return { checked: false, indeterminate: true }
}

export default function Step3Matches({ next, prev }: WizardCtx) {
  const { data, loading, error, reload } = useApi(getWizardMatches)
  const [decisions, setDecisions] = useState<Record<number, MatchDecision>>({})
  const [rescanning, setRescanning] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveErr, setSaveErr] = useState<string | null>(null)
  const [subgroupBy, setSubgroupBy] = useState<SubgroupDim>('material')
  const [sorts, setSorts] = useState<Record<SectionKey, SortState>>({
    matched: { col: 'name', dir: 'asc' },
    unmatched_sm: { col: 'name', dir: 'asc' },
    ambiguous: { col: 'name', dir: 'asc' },
    unmatched_fdb: { col: 'name', dir: 'asc' },
  })
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const hydrated = useRef(false)

  // First load: hydrate from saved_decisions. Rescan: prune SM ids that vanished.
  useEffect(() => {
    if (!data) return
    if (!hydrated.current) {
      hydrated.current = true
      const init: Record<number, MatchDecision> = {}
      for (const d of data.saved_decisions) init[d.spoolman_filament_id] = d
      setDecisions(init)
    } else {
      const valid = new Set([
        ...data.matched.map(p => p.spoolman.spoolman_filament_id!),
        ...data.unmatched_spoolman.map(s => s.spoolman_filament_id!),
        ...data.ambiguous.map(a => a.spoolman.spoolman_filament_id!),
      ])
      setDecisions(prev => {
        const next: Record<number, MatchDecision> = {}
        for (const [k, v] of Object.entries(prev)) {
          if (valid.has(Number(k))) next[Number(k)] = v
        }
        return next
      })
    }
  }, [data])

  function dec(smId: number): MatchDecision | undefined { return decisions[smId] }

  function setDec(smId: number, action: MatchDecision['action'], fdbId?: string | null) {
    setDecisions(d => ({ ...d, [smId]: { spoolman_filament_id: smId, action, filamentdb_id: fdbId } }))
  }

  function toggleSort(s: SectionKey, col: string) {
    setSorts(ss => ({
      ...ss,
      [s]: ss[s].col === col ? { col, dir: ss[s].dir === 'asc' ? 'desc' : 'asc' } : { col, dir: 'asc' },
    }))
  }

  function toggleCollapse(key: string) {
    setCollapsed(s => { const n = new Set(s); if (n.has(key)) n.delete(key); else n.add(key); return n })
  }

  async function handleRescan() {
    setRescanning(true)
    try { await reload() } finally { setRescanning(false) }
  }

  async function handleSave() {
    if (!data) return
    setSaving(true)
    setSaveErr(null)
    const all: MatchDecision[] = []
    for (const pair of data.matched) {
      const smId = pair.spoolman.spoolman_filament_id!
      all.push(decisions[smId] ?? {
        spoolman_filament_id: smId,
        action: 'link',
        filamentdb_id: pair.filamentdb.filamentdb_filament_id,
      })
    }
    for (const sm of data.unmatched_spoolman) {
      const d = decisions[sm.spoolman_filament_id!]
      if (d) all.push(d)
    }
    for (const amb of data.ambiguous) {
      const d = decisions[amb.spoolman.spoolman_filament_id!]
      if (d) all.push(d)
    }
    try {
      await postWizardMatches({ decisions: all })
      next()
    } catch (e) {
      setSaveErr(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  if (loading && !data) return <p className="text-gray-500">Loading match data…</p>
  if (error) return <p className="text-red-600">{error}</p>
  if (!data) return null

  const sgKey = (ref: FilamentRef) => (subgroupBy === 'material' ? ref.material : ref.vendor) ?? '—'
  const sortCols = ['name', 'vendor', 'material'] as const

  function renderSortBar(section: SectionKey) {
    return (
      <div className="flex items-center gap-2">
        {sortCols.map(col => (
          <SortBtn key={col} col={col} label={col} sort={sorts[section]} onSort={c => toggleSort(section, c)} />
        ))}
      </div>
    )
  }

  function renderGroupHeader(
    gKey: string, label: string, count: number,
    tri?: { checked: boolean; indeterminate: boolean },
    onTri?: (v: boolean) => void,
  ) {
    return (
      <div className="px-5 py-2 bg-gray-50 border-b border-gray-100 flex items-center gap-3">
        {tri && onTri && <TriCheckbox {...tri} onChange={onTri} />}
        <button
          onClick={() => toggleCollapse(gKey)}
          className="flex items-center gap-1 text-xs font-medium text-gray-600 hover:text-gray-800"
        >
          <span>{collapsed.has(gKey) ? '▶' : '▼'}</span>
          <span>{label}</span>
          <span className="text-gray-400">({count})</span>
        </button>
      </div>
    )
  }

  // --- Matched ---
  const matchedSorted = sortByRef(data.matched, p => p.spoolman, sorts.matched)
  const matchedGroups = groupBy(matchedSorted, p => sgKey(p.spoolman))
  const matchedIncluded = (p: MatchPairRow) => (dec(p.spoolman.spoolman_filament_id!)?.action ?? 'link') !== 'skip'
  const matchedTableTri = triState(data.matched.map(matchedIncluded))

  function bulkSetMatched(pairs: MatchPairRow[], include: boolean) {
    setDecisions(d => {
      const n = { ...d }
      for (const p of pairs) {
        const smId = p.spoolman.spoolman_filament_id!
        n[smId] = include
          ? { spoolman_filament_id: smId, action: 'link', filamentdb_id: p.filamentdb.filamentdb_filament_id }
          : { spoolman_filament_id: smId, action: 'skip' }
      }
      return n
    })
  }

  // --- Ambiguous ---
  const ambSorted = sortByRef(data.ambiguous, a => a.spoolman, sorts.ambiguous)
  const ambGroups = groupBy(ambSorted, a => sgKey(a.spoolman))
  const ambIncluded = (a: AmbiguousRow) => dec(a.spoolman.spoolman_filament_id!)?.action === 'link'
  const ambTableTri = triState(data.ambiguous.map(ambIncluded))

  function bulkSetAmb(ambs: AmbiguousRow[], include: boolean) {
    setDecisions(d => {
      const n = { ...d }
      for (const a of ambs) {
        const smId = a.spoolman.spoolman_filament_id!
        const existing = d[smId]
        if (!include) {
          n[smId] = { spoolman_filament_id: smId, action: 'skip', filamentdb_id: existing?.filamentdb_id }
        } else if (existing?.filamentdb_id) {
          n[smId] = { spoolman_filament_id: smId, action: 'link', filamentdb_id: existing.filamentdb_id }
        }
      }
      return n
    })
  }

  // --- Unmatched SM ---
  const unmSMSorted = sortByRef(data.unmatched_spoolman, s => s, sorts.unmatched_sm)
  const unmSMGroups = groupBy(unmSMSorted, sgKey)
  const unmSMIncluded = (s: FilamentRef) => (dec(s.spoolman_filament_id!)?.action ?? 'create') !== 'skip'
  const unmSMTableTri = triState(data.unmatched_spoolman.map(unmSMIncluded))

  function bulkSetUnmSM(items: FilamentRef[], include: boolean) {
    setDecisions(d => {
      const n = { ...d }
      for (const s of items) {
        const smId = s.spoolman_filament_id!
        n[smId] = { spoolman_filament_id: smId, action: include ? 'create' : 'skip' }
      }
      return n
    })
  }

  // --- Unmatched FDB ---
  const unmFDBSorted = sortByRef(data.unmatched_filamentdb, f => f, sorts.unmatched_fdb)
  const unmFDBGroups = groupBy(unmFDBSorted, sgKey)

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-gray-800">Match review</h2>
          <p className="text-sm text-gray-500 mt-1">
            Review auto-matched pairs, resolve ambiguous matches, and decide what to do with unmatched items.
          </p>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <span className="text-xs text-gray-500">Group by:</span>
          <div className="flex rounded border border-gray-200 overflow-hidden text-xs">
            {(['material', 'vendor'] as const).map(dim => (
              <button
                key={dim}
                onClick={() => setSubgroupBy(dim)}
                className={`px-3 py-1.5 font-medium ${
                  subgroupBy === dim ? 'bg-indigo-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'
                }`}
              >
                {dim === 'vendor' ? 'Brand' : 'Material'}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Matched */}
      {data.matched.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <div className="px-5 py-3 bg-green-50 border-b border-gray-200 flex items-center gap-3">
            <TriCheckbox {...matchedTableTri} onChange={v => bulkSetMatched(data.matched, v)} />
            <h3 className="text-sm font-semibold text-green-800 flex-1">Matched ({data.matched.length})</h3>
            {renderSortBar('matched')}
          </div>
          {matchedGroups.map(([g, pairs]) => {
            const gKey = `matched:${g}`
            const gTri = triState(pairs.map(matchedIncluded))
            return (
              <div key={g}>
                {renderGroupHeader(gKey, g, pairs.length, gTri, v => bulkSetMatched(pairs, v))}
                {!collapsed.has(gKey) && (
                  <div className="divide-y divide-gray-100">
                    {pairs.map(pair => {
                      const smId = pair.spoolman.spoolman_filament_id!
                      return (
                        <div key={smId} className="px-5 py-3 flex items-center gap-3">
                          <TriCheckbox
                            checked={matchedIncluded(pair)} indeterminate={false}
                            onChange={v => setDec(smId, v ? 'link' : 'skip', v ? pair.filamentdb.filamentdb_filament_id : undefined)}
                          />
                          <div className="flex-1 grid grid-cols-2 gap-4">
                            <div className="flex items-center gap-2">
                              <span className="text-xs text-emerald-600 font-medium uppercase">SM</span>
                              <FilamentTag filament={pair.spoolman} />
                              <DeepLinks spoolmanFilamentId={pair.spoolman.spoolman_filament_id} />
                            </div>
                            <div className="flex items-center gap-2">
                              <span className="text-xs text-blue-600 font-medium uppercase">FDB</span>
                              <FilamentTag filament={pair.filamentdb} />
                              <DeepLinks filamentdbFilamentId={pair.filamentdb.filamentdb_filament_id} />
                            </div>
                          </div>
                          <div className="flex items-center gap-1 text-xs text-gray-400 shrink-0">
                            {pair.vendor_dedup_hint && (
                              <span className="px-1.5 py-0.5 bg-yellow-100 text-yellow-700 rounded">
                                vendor: {pair.vendor_dedup_hint}
                              </span>
                            )}
                            <span>{(pair.confidence * 100).toFixed(0)}%</span>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Ambiguous */}
      {data.ambiguous.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <div className="px-5 py-3 bg-yellow-50 border-b border-gray-200 flex items-center gap-3">
            <TriCheckbox {...ambTableTri} onChange={v => bulkSetAmb(data.ambiguous, v)} />
            <h3 className="text-sm font-semibold text-yellow-800 flex-1">
              Ambiguous ({data.ambiguous.length}) — pick one
            </h3>
            {renderSortBar('ambiguous')}
          </div>
          {ambGroups.map(([g, ambs]) => {
            const gKey = `ambiguous:${g}`
            const gTri = triState(ambs.map(ambIncluded))
            return (
              <div key={g}>
                {renderGroupHeader(gKey, g, ambs.length, gTri, v => bulkSetAmb(ambs, v))}
                {!collapsed.has(gKey) && (
                  <div className="divide-y divide-gray-100">
                    {ambs.map(amb => {
                      const smId = amb.spoolman.spoolman_filament_id!
                      const d = dec(smId)
                      const hasFdb = d?.filamentdb_id != null
                      return (
                        <div key={smId} className="px-5 py-4 space-y-2">
                          <div className="flex items-center gap-3">
                            <TriCheckbox
                              checked={d?.action === 'link'}
                              indeterminate={false}
                              disabled={!hasFdb}
                              onChange={v => {
                                if (!v) {
                                  setDecisions(prev => ({
                                    ...prev,
                                    [smId]: { spoolman_filament_id: smId, action: 'skip', filamentdb_id: prev[smId]?.filamentdb_id },
                                  }))
                                } else if (d?.filamentdb_id) {
                                  setDec(smId, 'link', d.filamentdb_id)
                                }
                              }}
                            />
                            <span className="text-xs text-emerald-600 font-medium uppercase">SM</span>
                            <FilamentTag filament={amb.spoolman} />
                            <DeepLinks spoolmanFilamentId={smId} />
                          </div>
                          <div className="pl-9 space-y-1">
                            {amb.candidates.map(c => (
                              <div key={c.filamentdb_filament_id} className="flex items-center gap-2">
                                <button
                                  onClick={() => setDec(smId, 'link', c.filamentdb_filament_id)}
                                  className={`px-2 py-0.5 rounded text-xs font-medium ${
                                    d?.action === 'link' && d.filamentdb_id === c.filamentdb_filament_id
                                      ? 'bg-indigo-600 text-white'
                                      : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                                  }`}
                                >
                                  Link
                                </button>
                                <FilamentTag filament={c} />
                                <DeepLinks filamentdbFilamentId={c.filamentdb_filament_id} />
                              </div>
                            ))}
                            <div className="flex gap-1 mt-1">
                              {(['create', 'skip'] as const).map(a => (
                                <button
                                  key={a}
                                  onClick={() => setDec(smId, a)}
                                  className={`px-2 py-0.5 rounded text-xs font-medium ${
                                    d?.action === a ? 'bg-indigo-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                                  }`}
                                >
                                  {a}
                                </button>
                              ))}
                            </div>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Unmatched Spoolman */}
      {data.unmatched_spoolman.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <div className="px-5 py-3 bg-gray-50 border-b border-gray-200 flex items-center gap-3">
            <TriCheckbox {...unmSMTableTri} onChange={v => bulkSetUnmSM(data.unmatched_spoolman, v)} />
            <h3 className="text-sm font-semibold text-gray-700 flex-1">
              Unmatched in Spoolman ({data.unmatched_spoolman.length})
            </h3>
            {renderSortBar('unmatched_sm')}
          </div>
          {unmSMGroups.map(([g, items]) => {
            const gKey = `unmatched_sm:${g}`
            const gTri = triState(items.map(unmSMIncluded))
            return (
              <div key={g}>
                {renderGroupHeader(gKey, g, items.length, gTri, v => bulkSetUnmSM(items, v))}
                {!collapsed.has(gKey) && (
                  <div className="divide-y divide-gray-100">
                    {items.map(sm => {
                      const smId = sm.spoolman_filament_id!
                      return (
                        <div key={smId} className="px-5 py-3 flex items-center gap-3">
                          <TriCheckbox
                            checked={unmSMIncluded(sm)} indeterminate={false}
                            onChange={v => setDec(smId, v ? 'create' : 'skip')}
                          />
                          <span className="text-xs text-emerald-600 font-medium uppercase">SM</span>
                          <FilamentTag filament={sm} />
                          <DeepLinks spoolmanFilamentId={smId} />
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Unmatched FDB — informational, no checkboxes */}
      {data.unmatched_filamentdb.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <div className="px-5 py-3 bg-gray-50 border-b border-gray-200 flex items-center gap-3">
            <h3 className="text-sm font-semibold text-gray-700 flex-1">
              Unmatched in Filament DB ({data.unmatched_filamentdb.length}) — will be created in Spoolman
            </h3>
            {renderSortBar('unmatched_fdb')}
          </div>
          {unmFDBGroups.map(([g, items]) => {
            const gKey = `unmatched_fdb:${g}`
            return (
              <div key={g}>
                <div className="px-5 py-2 bg-gray-50 border-b border-gray-100 flex items-center gap-1">
                  <button
                    onClick={() => toggleCollapse(gKey)}
                    className="flex items-center gap-1 text-xs font-medium text-gray-600 hover:text-gray-800"
                  >
                    <span>{collapsed.has(gKey) ? '▶' : '▼'}</span>
                    <span>{g}</span>
                    <span className="text-gray-400">({items.length})</span>
                  </button>
                </div>
                {!collapsed.has(gKey) && (
                  <div className="divide-y divide-gray-100">
                    {items.map(f => (
                      <div key={f.filamentdb_filament_id} className="px-5 py-3 flex items-center gap-2">
                        <span className="text-xs text-blue-600 font-medium uppercase">FDB</span>
                        <FilamentTag filament={f} />
                        <DeepLinks filamentdbFilamentId={f.filamentdb_filament_id} />
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {saveErr && <p className="text-sm text-red-600">{saveErr}</p>}

      <div className="flex justify-between items-center">
        <button onClick={prev} className="px-5 py-2 bg-gray-100 text-gray-700 rounded text-sm font-medium hover:bg-gray-200">
          ← Back
        </button>
        <div className="flex items-center gap-3">
          <button
            onClick={handleRescan}
            disabled={rescanning || (loading && !saving)}
            className="px-4 py-2 bg-white border border-gray-300 text-gray-700 rounded text-sm font-medium hover:bg-gray-50 disabled:opacity-50 flex items-center gap-2"
          >
            {rescanning
              ? <><span className="inline-block w-3 h-3 border-2 border-gray-400 border-t-transparent rounded-full animate-spin" />Rescanning…</>
              : '↻ Rescan'}
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
    </div>
  )
}
