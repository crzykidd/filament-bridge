import { useEffect, useMemo, useRef, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import { getWizardMatches, postWizardMatches } from '../../api/client'
import { useApi } from '../../api/hooks'
import { DeepLinks } from '../../components/DeepLinks'
import { HelpTip } from '../../components/HelpTip'
import { OptBadge } from '../../components/OptBadge'
import { WizardActionBar } from '../../components/WizardActionBar'
import type { FilamentRef, MatchDecision, WizardMatchesResponse } from '../../api/types'
import type { WizardCtx } from './index'

// ── types ─────────────────────────────────────────────────────────────────────

type RowStatus = 'matched' | 'unmatched_sm' | 'ambiguous' | 'unmatched_fdb' | 'master_fdb'
type GroupDim = 'status' | 'material' | 'vendor'
type SortDir = 'asc' | 'desc'
type SortCol = 'name' | 'vendor' | 'material' | 'status' | 'confidence'

interface FlatRow {
  status: RowStatus
  smId: number | null
  fdbId: string | null
  sm: FilamentRef | null
  fdb: FilamentRef | null
  confidence: number | null
  vendorDedup: string | null
  candidates: FilamentRef[]
}

// ── constants ──────────────────────────────────────────────────────────────────

const STATUS_LABEL: Record<RowStatus, string> = {
  matched: 'Matched',
  ambiguous: 'Ambiguous',
  unmatched_sm: 'Unmatched (SM)',
  unmatched_fdb: 'Unmatched (FDB)',
  master_fdb: 'Master / Parent',
}
const STATUS_ORDER: Record<RowStatus, number> = {
  matched: 0, ambiguous: 1, unmatched_sm: 2, unmatched_fdb: 3, master_fdb: 4,
}
const STATUS_COLOR: Record<RowStatus, string> = {
  matched: 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300',
  ambiguous: 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-300',
  unmatched_sm: 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300',
  unmatched_fdb: 'bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-300',
  master_fdb: 'bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300',
}
const STATUS_HDR_BG: Record<RowStatus, string> = {
  matched: 'bg-green-50 dark:bg-gray-750', ambiguous: 'bg-yellow-50 dark:bg-gray-750',
  unmatched_sm: 'bg-gray-50 dark:bg-gray-750', unmatched_fdb: 'bg-gray-50 dark:bg-gray-750',
  master_fdb: 'bg-purple-50 dark:bg-gray-750',
}

// Shared grid template — must match in header, filter row, and member rows.
const G = 'grid grid-cols-[2rem_1.5fr_1.5fr_5rem_5.5rem] gap-3 px-4'

// ── row accessors ──────────────────────────────────────────────────────────────

function rName(r: FlatRow) { return r.sm?.name ?? r.fdb?.name ?? '' }
function rVendor(r: FlatRow) { return r.sm?.vendor ?? r.fdb?.vendor ?? '' }
function rMaterial(r: FlatRow) { return (r.sm?.material ?? r.fdb?.material ?? '') }

function groupKey(r: FlatRow, dim: GroupDim): string {
  if (dim === 'status') return r.status
  if (dim === 'material') return rMaterial(r) || '—'
  return rVendor(r) || '—'
}

function sortVal(r: FlatRow, col: SortCol): string | number {
  if (col === 'name') return rName(r).toLowerCase()
  if (col === 'vendor') return rVendor(r).toLowerCase()
  if (col === 'material') return rMaterial(r).toLowerCase()
  if (col === 'status') return STATUS_ORDER[r.status]
  if (col === 'confidence') return r.confidence ?? -1
  return ''
}

// A row is user-selectable only if bulkSet can actually act on it — exclude FDB-only,
// synthetic-master, and id-less rows. This MUST be the denominator for the select-all and
// group tri-state checkboxes so they match what bulkSet toggles; otherwise unselectable rows
// keep the box permanently indeterminate and "select all" can only ever select, never clear.
function isSelectable(r: FlatRow): boolean {
  return r.status !== 'unmatched_fdb' && r.status !== 'master_fdb' && r.smId != null
}

function isIncluded(r: FlatRow, decisions: Record<number, MatchDecision>): boolean {
  if (!isSelectable(r)) return false
  const d = decisions[r.smId]
  if (r.status === 'matched') return (d?.action ?? 'link') !== 'skip'
  if (r.status === 'unmatched_sm') return (d?.action ?? 'create') !== 'skip'
  if (r.status === 'ambiguous') return d?.action === 'link'
  return false
}

/**
 * Assemble the MatchDecision[] to persist from the loaded match data + the user's
 * per-row toggles. Mirrors what the checkboxes display:
 *   - matched rows default to `link` when untouched,
 *   - unmatched Spoolman rows default to `create` when untouched (they render
 *     checked-by-default), and
 *   - ambiguous rows have no safe default, so only explicit picks are persisted.
 * Exported for unit testing — the untouched-unmatched default is load-bearing:
 * without it, a user who clicks Next without toggling each new color imports nothing.
 */
export function buildSaveDecisions(
  data: WizardMatchesResponse,
  decisions: Record<number, MatchDecision>,
): MatchDecision[] {
  const all: MatchDecision[] = []
  for (const p of data.matched) {
    const id = p.spoolman.spoolman_filament_id!
    all.push(
      decisions[id] ?? {
        spoolman_filament_id: id,
        action: 'link',
        filamentdb_id: p.filamentdb.filamentdb_filament_id,
      },
    )
  }
  for (const s of data.unmatched_spoolman) {
    const id = s.spoolman_filament_id!
    all.push(decisions[id] ?? { spoolman_filament_id: id, action: 'create' })
  }
  for (const a of data.ambiguous) {
    const d = decisions[a.spoolman.spoolman_filament_id!]
    if (d) all.push(d)
  }
  return all
}

function triState(flags: boolean[]) {
  const n = flags.filter(Boolean).length
  if (n === 0) return { checked: false, indeterminate: false }
  if (n === flags.length) return { checked: true, indeterminate: false }
  return { checked: false, indeterminate: true }
}

// ── sub-components ─────────────────────────────────────────────────────────────

function TriCheckbox({ checked, indeterminate, onChange, disabled }: {
  checked: boolean; indeterminate: boolean; onChange: (v: boolean) => void; disabled?: boolean
}) {
  const ref = useRef<HTMLInputElement>(null)
  useEffect(() => { if (ref.current) ref.current.indeterminate = indeterminate }, [indeterminate])
  return (
    <input ref={ref} type="checkbox" checked={checked} disabled={disabled}
      onChange={e => onChange(e.target.checked)}
      className="mt-0.5 rounded border-gray-300 dark:border-gray-600 dark:bg-gray-700 text-indigo-600 focus:ring-indigo-500 disabled:cursor-not-allowed" />
  )
}

function FTag({ f, side }: { f: FilamentRef | null; side?: 'sm' | 'fdb' }) {
  if (!f) return null
  const sc = side === 'sm' ? 'text-emerald-600' : 'text-blue-600'
  return (
    <span className="text-sm flex flex-wrap items-center gap-1">
      {side && <span className={`text-xs font-medium uppercase ${sc}`}>{side.toUpperCase()}</span>}
      <span className="font-medium">{f.name ?? '—'}</span>
      {f.vendor && <span className="text-gray-500">· {f.vendor}</span>}
      {f.color && <span className="text-gray-400">· {f.color}</span>}
      {side === 'sm' && f.active_spool_count != null && (
        <span
          className={`text-xs ${f.active_spool_count === 0 ? 'text-amber-600 dark:text-amber-400' : 'text-gray-400 dark:text-gray-500'}`}
          title={f.active_spool_count === 0 ? 'No active spools — only archived/empty spools, which are skipped on import' : undefined}
        >
          · {f.active_spool_count} active {f.active_spool_count === 1 ? 'spool' : 'spools'}
        </span>
      )}
    </span>
  )
}

function StatusPill({ status }: { status: RowStatus }) {
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium ${STATUS_COLOR[status]}`}>
      {STATUS_LABEL[status]}
    </span>
  )
}

// ── MemberRow ──────────────────────────────────────────────────────────────────

interface MRProps {
  row: FlatRow
  decision: MatchDecision | undefined
  showStatus: boolean
  setDec: (id: number, action: MatchDecision['action'], fdbId?: string | null) => void
  setDecisions: Dispatch<SetStateAction<Record<number, MatchDecision>>>
}

function MemberRow({ row, decision, showStatus, setDec, setDecisions }: MRProps) {
  const smId = row.smId ?? 0

  if (row.status === 'matched') {
    const included = (decision?.action ?? 'link') !== 'skip'
    return (
      <div className={`${G} py-3 items-start`}>
        <TriCheckbox checked={included} indeterminate={false}
          onChange={v => setDec(smId, v ? 'link' : 'skip', v ? row.fdbId : undefined)} />
        <div className="flex flex-wrap items-center gap-1.5 min-w-0">
          <FTag f={row.sm} side="sm" />
          {row.smId != null && (
            <span className="text-xs text-gray-400">SM #{row.smId}</span>
          )}
          {row.sm?.openprinttag && <OptBadge />}
          <DeepLinks spoolmanFilamentId={row.sm?.spoolman_filament_id} />
        </div>
        <div className="flex flex-wrap items-center gap-1.5 min-w-0">
          <FTag f={row.fdb} side="fdb" />
          <DeepLinks filamentdbFilamentId={row.fdb?.filamentdb_filament_id} />
          {row.vendorDedup && (
            <span className="px-1.5 py-0.5 bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-300 rounded text-xs">
              vendor: {row.vendorDedup}
            </span>
          )}
        </div>
        <span className="text-xs text-gray-500 pt-0.5">{rMaterial(row) || '—'}</span>
        <div className="flex flex-col gap-1 items-start">
          {showStatus && <StatusPill status="matched" />}
          {row.confidence != null && (
            <span className="text-xs text-gray-400">{(row.confidence * 100).toFixed(0)}%</span>
          )}
        </div>
      </div>
    )
  }

  if (row.status === 'unmatched_sm') {
    const included = (decision?.action ?? 'create') !== 'skip'
    return (
      <div className={`${G} py-3 items-start`}>
        <TriCheckbox checked={included} indeterminate={false}
          onChange={v => setDec(smId, v ? 'create' : 'skip')} />
        <div className="flex flex-wrap items-center gap-1.5 min-w-0">
          <FTag f={row.sm} side="sm" />
          {row.smId != null && (
            <span className="text-xs text-gray-400">SM #{row.smId}</span>
          )}
          {row.sm?.openprinttag && <OptBadge />}
          <DeepLinks spoolmanFilamentId={smId} />
        </div>
        <span className="text-xs text-gray-400 italic pt-0.5">
          {included ? 'Will create in FDB' : 'Skip'}
        </span>
        <span className="text-xs text-gray-500 pt-0.5">{rMaterial(row) || '—'}</span>
        <div>{showStatus && <StatusPill status="unmatched_sm" />}</div>
      </div>
    )
  }

  if (row.status === 'unmatched_fdb' || row.status === 'master_fdb') {
    return (
      <div className={`${G} py-3 items-start`}>
        <div />
        <span className="text-xs text-gray-300 pt-0.5">—</span>
        <div className="flex flex-wrap items-center gap-1.5 min-w-0">
          <FTag f={row.fdb} side="fdb" />
          <DeepLinks filamentdbFilamentId={row.fdb?.filamentdb_filament_id} />
          {row.status === 'master_fdb' && (
            <span className="text-xs text-gray-400 italic">bridge-owned parent</span>
          )}
        </div>
        <span className="text-xs text-gray-500 pt-0.5">{rMaterial(row) || '—'}</span>
        <div className="flex items-center gap-1">
          {showStatus && <StatusPill status={row.status} />}
          {showStatus && row.status === 'master_fdb' && (
            <HelpTip text="A parent record owned by the bridge (or an existing FDB parent). Nothing to do here — it never syncs directly." />
          )}
        </div>
      </div>
    )
  }

  // ambiguous
  const hasFdb = decision?.filamentdb_id != null
  const isLinked = decision?.action === 'link'
  return (
    <div className="py-3">
      <div className={`${G} items-start`}>
        <TriCheckbox checked={isLinked} indeterminate={false} disabled={!hasFdb}
          onChange={v => {
            if (!v) {
              setDecisions(p => ({
                ...p,
                [smId]: { spoolman_filament_id: smId, action: 'skip', filamentdb_id: p[smId]?.filamentdb_id },
              }))
            } else if (decision?.filamentdb_id) {
              setDec(smId, 'link', decision.filamentdb_id)
            }
          }} />
        <div className="flex flex-wrap items-center gap-1.5 min-w-0">
          <FTag f={row.sm} side="sm" />
          {row.smId != null && (
            <span className="text-xs text-gray-400">SM #{row.smId}</span>
          )}
          {row.sm?.openprinttag && <OptBadge />}
          <DeepLinks spoolmanFilamentId={smId} />
        </div>
        <span className="text-xs text-gray-400 italic pt-0.5">Pick a match ↓</span>
        <span className="text-xs text-gray-500 pt-0.5">{rMaterial(row) || '—'}</span>
        <div>{showStatus && <StatusPill status="ambiguous" />}</div>
      </div>
      <div className="pl-16 pr-4 mt-1.5 space-y-1">
        {row.candidates.map(c => (
          <div key={c.filamentdb_filament_id} className="flex items-center gap-2">
            <button
              onClick={() => setDec(smId, 'link', c.filamentdb_filament_id)}
              className={`px-2 py-0.5 rounded text-xs font-medium shrink-0 ${
                isLinked && decision?.filamentdb_id === c.filamentdb_filament_id
                  ? 'bg-indigo-600 text-white'
                  : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
              }`}>Link</button>
            <FTag f={c} side="fdb" />
            <DeepLinks filamentdbFilamentId={c.filamentdb_filament_id} />
          </div>
        ))}
        <div className="flex gap-1 mt-1">
          {(['create', 'skip'] as const).map(a => (
            <button key={a} onClick={() => setDec(smId, a)}
              className={`px-2 py-0.5 rounded text-xs font-medium ${
                decision?.action === a ? 'bg-indigo-600 text-white' : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
              }`}>{a}</button>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Step3Matches ───────────────────────────────────────────────────────────────

export default function Step3Matches({ next, prev }: WizardCtx) {
  const { data, loading, error, reload } = useApi(getWizardMatches)
  const [decisions, setDecisions] = useState<Record<number, MatchDecision>>({})
  const [rescanning, setRescanning] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveErr, setSaveErr] = useState<string | null>(null)

  // toolbar
  const [groupBy, setGroupBy] = useState<GroupDim>('status')
  const [sortCol, setSortCol] = useState<SortCol>('name')
  const [sortDir, setSortDir] = useState<SortDir>('asc')
  const [search, setSearch] = useState('')
  const [filterStatus, setFilterStatus] = useState<RowStatus | 'all'>('all')
  const [filterOpt, setFilterOpt] = useState(false)
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [colFilter, setColFilter] = useState({ name: '', material: '' })

  const hydrated = useRef(false)

  // rehydrate decisions on load; prune stale ids on rescan
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

  // flatten all sections into a single row model
  const allRows = useMemo<FlatRow[]>(() => {
    if (!data) return []
    const rows: FlatRow[] = []
    for (const p of data.matched) rows.push({
      status: 'matched', smId: p.spoolman.spoolman_filament_id, fdbId: p.filamentdb.filamentdb_filament_id,
      sm: p.spoolman, fdb: p.filamentdb, confidence: p.confidence, vendorDedup: p.vendor_dedup_hint, candidates: [],
    })
    for (const a of data.ambiguous) rows.push({
      status: 'ambiguous', smId: a.spoolman.spoolman_filament_id, fdbId: null,
      sm: a.spoolman, fdb: null, confidence: null, vendorDedup: null, candidates: a.candidates,
    })
    for (const s of data.unmatched_spoolman) rows.push({
      status: 'unmatched_sm', smId: s.spoolman_filament_id, fdbId: null,
      sm: s, fdb: null, confidence: null, vendorDedup: null, candidates: [],
    })
    for (const f of data.unmatched_filamentdb) rows.push({
      status: f.is_master_container ? 'master_fdb' : 'unmatched_fdb',
      smId: null, fdbId: f.filamentdb_filament_id,
      sm: null, fdb: f, confidence: null, vendorDedup: null, candidates: [],
    })
    return rows
  }, [data])

  const optTaggedCount = useMemo(
    () => allRows.filter(r => r.sm?.openprinttag).length,
    [allRows],
  )

  const filtered = useMemo(() => allRows.filter(r => {
    if (filterStatus !== 'all' && r.status !== filterStatus) return false
    if (filterOpt) {
      // When filter is on, hide rows with no SM side or whose SM filament is not OPT-tagged.
      if (!r.sm?.openprinttag) return false
    }
    if (search) {
      const lq = search.toLowerCase()
      const hay = [rName(r), rVendor(r), rMaterial(r), r.fdb?.name ?? '', String(r.smId ?? '')].join(' ').toLowerCase()
      if (!hay.includes(lq)) return false
    }
    if (colFilter.name && !rName(r).toLowerCase().includes(colFilter.name.toLowerCase())) return false
    if (colFilter.material && !rMaterial(r).toLowerCase().includes(colFilter.material.toLowerCase())) return false
    return true
  }), [allRows, filterStatus, filterOpt, search, colFilter])

  const sorted = useMemo(() => [...filtered].sort((a, b) => {
    if (sortCol === 'confidence') {
      const d = (a.confidence ?? -1) - (b.confidence ?? -1)
      return sortDir === 'asc' ? d : -d
    }
    if (sortCol === 'status') {
      const d = STATUS_ORDER[a.status] - STATUS_ORDER[b.status]
      return sortDir === 'asc' ? d : -d
    }
    const cmp = String(sortVal(a, sortCol)).localeCompare(String(sortVal(b, sortCol)))
    return sortDir === 'asc' ? cmp : -cmp
  }), [filtered, sortCol, sortDir])

  const groups = useMemo<[string, FlatRow[]][]>(() => {
    const map = new Map<string, FlatRow[]>()
    for (const r of sorted) {
      const k = groupKey(r, groupBy)
      if (!map.has(k)) map.set(k, [])
      map.get(k)!.push(r)
    }
    if (groupBy === 'status') {
      const order: RowStatus[] = ['matched', 'ambiguous', 'unmatched_sm', 'unmatched_fdb']
      return order.filter(s => map.has(s)).map(s => [s, map.get(s)!])
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [sorted, groupBy])

  function setDec(smId: number, action: MatchDecision['action'], fdbId?: string | null) {
    setDecisions(d => ({ ...d, [smId]: { spoolman_filament_id: smId, action, filamentdb_id: fdbId } }))
  }

  function bulkSet(rows: FlatRow[], include: boolean) {
    setDecisions(d => {
      const n = { ...d }
      for (const r of rows) {
        if (r.status === 'unmatched_fdb' || r.status === 'master_fdb' || r.smId == null) continue
        const id = r.smId
        if (r.status === 'matched') {
          n[id] = include
            ? { spoolman_filament_id: id, action: 'link', filamentdb_id: r.fdbId }
            : { spoolman_filament_id: id, action: 'skip' }
        } else if (r.status === 'unmatched_sm') {
          n[id] = { spoolman_filament_id: id, action: include ? 'create' : 'skip' }
        } else if (r.status === 'ambiguous') {
          const ex = d[id]
          n[id] = !include
            ? { spoolman_filament_id: id, action: 'skip', filamentdb_id: ex?.filamentdb_id }
            : ex?.filamentdb_id
            ? { spoolman_filament_id: id, action: 'link', filamentdb_id: ex.filamentdb_id }
            : (ex ?? { spoolman_filament_id: id, action: 'skip' })
        }
      }
      return n
    })
  }

  function toggleCollapse(k: string) {
    setCollapsed(s => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n })
  }

  async function handleRescan() {
    setRescanning(true)
    try { await reload() } finally { setRescanning(false) }
  }

  async function handleSave() {
    if (!data) return
    setSaving(true); setSaveErr(null)
    const all = buildSaveDecisions(data, decisions)
    try { await postWizardMatches({ decisions: all }); next() }
    catch (e) { setSaveErr(e instanceof Error ? e.message : String(e)) }
    finally { setSaving(false) }
  }

  if (loading && !data) return <p className="text-gray-500 dark:text-gray-400">Loading match data…</p>
  if (error) return <p className="text-red-600 dark:text-red-400">{error}</p>
  if (!data) return null

  const actionable = sorted.filter(isSelectable)
  const tableTri = triState(actionable.map(r => isIncluded(r, decisions)))

  const rescanButton = (
    <button onClick={handleRescan} disabled={rescanning || (loading && !saving)}
      className="px-4 py-2 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 rounded text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 flex items-center gap-2">
      {rescanning
        ? <><span className="inline-block w-3 h-3 border-2 border-gray-400 border-t-transparent rounded-full animate-spin" />Rescanning…</>
        : '↻ Rescan'}
    </button>
  )

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-200">Match review</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
          Review auto-matched pairs, resolve ambiguous matches, and decide what to do with unmatched items.
        </p>
      </div>

      {/* Top action bar */}
      <WizardActionBar
        onBack={prev}
        onNext={handleSave}
        nextLabel="Save & Next →"
        busy={saving}
        busyLabel="Saving…"
        extra={rescanButton}
      />

      {/* Toolbar */}
      <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-3 space-y-2">
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-1.5">
            <span className="text-xs text-gray-500 shrink-0">Group by</span>
            <select value={groupBy} onChange={e => setGroupBy(e.target.value as GroupDim)}
              className="text-xs border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 rounded px-2 py-1 focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500">
              <option value="status">Status</option>
              <option value="material">Material</option>
              <option value="vendor">Brand</option>
            </select>
          </label>

          <label className="flex items-center gap-1.5">
            <span className="text-xs text-gray-500 shrink-0">Sort by</span>
            <select value={sortCol} onChange={e => setSortCol(e.target.value as SortCol)}
              className="text-xs border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 rounded px-2 py-1 focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500">
              <option value="name">Name</option>
              <option value="vendor">Brand</option>
              <option value="material">Material</option>
              <option value="status">Status</option>
              <option value="confidence">Confidence</option>
            </select>
            <button onClick={() => setSortDir(d => d === 'asc' ? 'desc' : 'asc')}
              title={sortDir === 'asc' ? 'Ascending' : 'Descending'}
              className="px-1.5 py-1 text-xs border border-gray-200 dark:border-gray-600 text-gray-700 dark:text-gray-200 rounded hover:bg-gray-50 dark:hover:bg-gray-700">
              {sortDir === 'asc' ? '↑' : '↓'}
            </button>
          </label>

          <div className="flex items-center gap-1.5 flex-1 min-w-36">
            <input type="text" placeholder="Search all fields…" value={search}
              onChange={e => setSearch(e.target.value)}
              className="text-xs border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 rounded px-2 py-1 w-full focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500" />
          </div>

          <label className="flex items-center gap-1.5">
            <span className="text-xs text-gray-500 shrink-0">Status</span>
            <select value={filterStatus} onChange={e => setFilterStatus(e.target.value as RowStatus | 'all')}
              className="text-xs border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 rounded px-2 py-1 focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500">
              <option value="all">All</option>
              <option value="matched">Matched</option>
              <option value="ambiguous">Ambiguous</option>
              <option value="unmatched_sm">Unmatched (SM)</option>
              <option value="unmatched_fdb">Unmatched (FDB)</option>
              <option value="master_fdb">Master / Parent</option>
            </select>
          </label>

          <label className="flex items-center gap-1.5 cursor-pointer select-none">
            <input type="checkbox" checked={filterOpt} onChange={e => setFilterOpt(e.target.checked)}
              className="rounded border-gray-300 dark:border-gray-600 dark:bg-gray-700 text-indigo-600 focus:ring-indigo-500" />
            <span className="text-xs text-gray-500 shrink-0">OpenPrintTag-tagged only</span>
            {optTaggedCount > 0 && (
              <span className="px-1.5 py-0.5 bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300 rounded text-xs font-medium">
                {optTaggedCount}
              </span>
            )}
          </label>

          {/* Summary stats */}
          {(() => {
            const masterCount = allRows.filter(r => r.status === 'master_fdb').length
            const unmatchedFdbCount = allRows.filter(r => r.status === 'unmatched_fdb').length
            return (
              <div className="ml-auto flex items-center gap-3 text-xs text-gray-500 dark:text-gray-400 shrink-0">
                <span>Total <span className="font-semibold text-gray-700 dark:text-gray-200">{allRows.length}</span></span>
                <span className="text-green-600 dark:text-green-400">✓ {data.matched.length}</span>
                {data.ambiguous.length > 0 && <span className="text-yellow-600 dark:text-yellow-400">? {data.ambiguous.length}</span>}
                {data.unmatched_spoolman.length > 0 && <span>+SM {data.unmatched_spoolman.length}</span>}
                {unmatchedFdbCount > 0 && <span>+FDB {unmatchedFdbCount}</span>}
                {masterCount > 0 && <span className="text-purple-600 dark:text-purple-400">♦ {masterCount} parent</span>}
              </div>
            )
          })()}
        </div>

        <div className="flex items-center gap-2 text-xs">
          <button onClick={() => setCollapsed(new Set(groups.map(([k]) => k)))}
            className="text-indigo-600 hover:text-indigo-800">Collapse all</button>
          <span className="text-gray-300 dark:text-gray-600">|</span>
          <button onClick={() => setCollapsed(new Set())}
            className="text-indigo-600 hover:text-indigo-800">Expand all</button>
          {filtered.length !== allRows.length && (
            <span className="text-gray-400 ml-2">{filtered.length} of {allRows.length} shown</span>
          )}
        </div>
      </div>

      {/* Table */}
      <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
        {/* Column headers + per-column filter inputs */}
        <div className="bg-gray-50 dark:bg-gray-750 border-b border-gray-200 dark:border-gray-700">
          <div className={`${G} py-2 items-center`}>
            <TriCheckbox {...tableTri} onChange={v => bulkSet(actionable, v)} />
            <span className="text-xs font-medium uppercase tracking-wide text-gray-500 dark:text-gray-300">Spoolman</span>
            <span className="text-xs font-medium uppercase tracking-wide text-gray-500 dark:text-gray-300">Filament DB</span>
            <span className="text-xs font-medium uppercase tracking-wide text-gray-500 dark:text-gray-300">Material</span>
            <span className="flex items-center text-xs font-medium uppercase tracking-wide text-gray-500 dark:text-gray-300">
              Status / %
              <HelpTip text="Fuzzy match score on vendor + name + color. 100% = exact or already cross-referenced." />
            </span>
          </div>
          <div className={`${G} pb-2 items-center`}>
            <div />
            <input type="text" placeholder="Name…" value={colFilter.name}
              onChange={e => setColFilter(f => ({ ...f, name: e.target.value }))}
              className="text-xs border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 rounded px-2 py-0.5 focus:ring-1 focus:ring-indigo-500" />
            <div />
            <input type="text" placeholder="Material…" value={colFilter.material}
              onChange={e => setColFilter(f => ({ ...f, material: e.target.value }))}
              className="text-xs border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 rounded px-2 py-0.5 focus:ring-1 focus:ring-indigo-500" />
            <div />
          </div>
        </div>

        {groups.length === 0 && (
          <div className="px-5 py-10 text-center text-sm text-gray-400">
            No rows match the current filters.
          </div>
        )}

        {groups.map(([gKey, rows]) => {
          const isStatusGrouping = groupBy === 'status'
          const gStatus = isStatusGrouping ? gKey as RowStatus : null
          const actionableInGroup = rows.filter(isSelectable)
          const gTri = triState(actionableInGroup.map(r => isIncluded(r, decisions)))
          const ambUnresolved = rows.filter(
            r => r.status === 'ambiguous' && decisions[r.smId!]?.action !== 'link'
          ).length
          const isCollapsed = collapsed.has(gKey)
          const headerBg = isStatusGrouping && gStatus ? STATUS_HDR_BG[gStatus] : 'bg-gray-50 dark:bg-gray-750'
          const gLabel = isStatusGrouping ? STATUS_LABEL[gStatus!] : gKey

          const statusBreakdown = !isStatusGrouping
            ? (['matched', 'ambiguous', 'unmatched_sm', 'unmatched_fdb'] as RowStatus[])
                .map(s => ({ s, n: rows.filter(r => r.status === s).length }))
                .filter(x => x.n > 0)
            : []

          return (
            <div key={gKey} className="border-b border-gray-100 dark:border-gray-700 last:border-b-0">
              {/* Group header */}
              <div className={`${headerBg} px-4 py-2.5 flex items-center gap-3`}>
                {actionableInGroup.length > 0
                  ? <TriCheckbox {...gTri} onChange={v => bulkSet(actionableInGroup, v)} />
                  : <div className="w-4 shrink-0" />}
                <button onClick={() => toggleCollapse(gKey)}
                  className="flex items-center gap-1.5 flex-1 text-left min-w-0">
                  <span className="text-gray-400 dark:text-gray-400 text-xs shrink-0">{isCollapsed ? '▶' : '▼'}</span>
                  <span className="text-sm font-medium text-gray-700 dark:text-gray-100 truncate">{gLabel}</span>
                  <span className="text-xs text-gray-400 dark:text-gray-400 shrink-0">({rows.length})</span>
                </button>
                {statusBreakdown.length > 0 && (
                  <div className="flex items-center gap-1 shrink-0">
                    {statusBreakdown.map(({ s, n }) => (
                      <span key={s} className={`px-1.5 py-0.5 rounded text-xs ${STATUS_COLOR[s]}`}>
                        {n} {s === 'matched' ? '✓' : s === 'ambiguous' ? '?' : s === 'unmatched_sm' ? 'SM' : 'FDB'}
                      </span>
                    ))}
                  </div>
                )}
                {ambUnresolved > 0 && (
                  <span className="text-xs text-amber-600 font-medium shrink-0">
                    ⚠ {ambUnresolved} unresolved
                  </span>
                )}
              </div>

              {!isCollapsed && (
                <div className="divide-y divide-gray-100 dark:divide-gray-700">
                  {rows.map(r => (
                    <MemberRow
                      key={`${r.status}:${r.smId ?? r.fdbId}`}
                      row={r}
                      decision={r.smId != null ? decisions[r.smId] : undefined}
                      showStatus={!isStatusGrouping}
                      setDec={setDec}
                      setDecisions={setDecisions}
                    />
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {saveErr && <p className="text-sm text-red-600 dark:text-red-400">{saveErr}</p>}

      {/* Bottom action bar */}
      <WizardActionBar
        onBack={prev}
        onNext={handleSave}
        nextLabel="Save & Next →"
        busy={saving}
        busyLabel="Saving…"
        extra={rescanButton}
      />
    </div>
  )
}
