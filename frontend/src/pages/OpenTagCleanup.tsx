/**
 * OpenTag Cleanup — standalone tool to match Spoolman filaments against the
 * OpenPrintTag dataset, review per-field, confirm, and apply writes to Spoolman
 * (including pushing openprinttag_slug/uuid into FDB's settings{} bag).
 *
 * Flow: Dataset status → Fetch matches → Review per filament → Confirm → Apply
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  getOpenTagMatches,
  getOpenTagStatus,
  postOpenTagApply,
  postOpenTagRefresh,
} from '../api/client'
import type {
  OpenTagApplyRequest,
  OpenTagCacheStatus,
  OpenTagDatasetMeta,
  OpenTagFieldDecision,
  OpenTagFieldRow,
  OpenTagFilamentDecision,
  OpenTagFilamentMatch,
  OpenTagMatchesResponse,
} from '../api/types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatAge(fetchedAt: string | null): string {
  if (!fetchedAt) return 'never'
  const d = new Date(fetchedAt)
  const diffMs = Date.now() - d.getTime()
  const h = Math.floor(diffMs / 3_600_000)
  const m = Math.floor((diffMs % 3_600_000) / 60_000)
  if (h > 0) return `${h}h ${m}m ago`
  return `${m}m ago`
}

function confidenceBadge(c: number) {
  const pct = Math.round(c * 100)
  const bg =
    pct >= 70 ? 'bg-green-100 text-green-800' :
    pct >= 40 ? 'bg-yellow-100 text-yellow-800' :
    'bg-red-100 text-red-800'
  return (
    <span className={`px-1.5 py-0.5 rounded text-xs font-mono ${bg}`}>
      {pct}%
    </span>
  )
}

function ColorSwatch({ hex }: { hex: string | null }) {
  if (!hex) return null
  const clean = hex.startsWith('#') ? hex : `#${hex}`
  return (
    <span
      className="inline-block w-4 h-4 rounded border border-gray-300 align-middle mr-1"
      style={{ backgroundColor: clean }}
      title={clean}
    />
  )
}

function renderValue(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (Array.isArray(v)) return `[${v.join(', ')}]`
  return String(v)
}

// ---------------------------------------------------------------------------
// Per-field review row
// ---------------------------------------------------------------------------

interface FieldRowProps {
  row: OpenTagFieldRow
  decision: OpenTagFieldDecision
  onChange: (updated: OpenTagFieldDecision) => void
}

function FieldReviewRow({ row, decision, onChange }: FieldRowProps) {
  const isColor = row.field === 'color_hex' || row.field === 'multi_color_hexes'
  const colorHex = isColor && typeof decision.value === 'string' ? decision.value : null

  return (
    <tr className="hover:bg-gray-50">
      <td className="px-3 py-2 text-xs font-mono text-gray-500 whitespace-nowrap">{row.field}</td>
      <td className="px-3 py-2 text-sm text-gray-700">
        {isColor && <ColorSwatch hex={renderValue(row.spoolman_value)} />}
        {renderValue(row.spoolman_value)}
      </td>
      <td className="px-3 py-2 text-sm text-indigo-700">
        {isColor && <ColorSwatch hex={renderValue(row.opentag_value)} />}
        {renderValue(row.opentag_value)}
      </td>
      <td className="px-3 py-2">
        {decision.keep_mine ? (
          <span className="text-xs text-gray-400 italic">keeping mine</span>
        ) : (
          <div className="flex items-center gap-1">
            {isColor && <ColorSwatch hex={colorHex} />}
            <input
              type={typeof decision.value === 'number' ? 'number' : 'text'}
              className="border border-gray-300 rounded px-2 py-0.5 text-xs w-32 focus:outline-none focus:ring-1 focus:ring-indigo-400"
              value={decision.value === null || decision.value === undefined ? '' : String(decision.value)}
              onChange={e => {
                const raw = e.target.value
                const val: unknown =
                  typeof row.opentag_value === 'number' ? (raw === '' ? null : Number(raw)) : raw
                onChange({ ...decision, value: val })
              }}
            />
          </div>
        )}
      </td>
      <td className="px-3 py-2">
        <button
          type="button"
          className={`text-xs px-2 py-0.5 rounded border transition-colors ${
            decision.keep_mine
              ? 'bg-gray-100 border-gray-300 text-gray-700 hover:bg-gray-200'
              : 'bg-white border-gray-300 text-gray-500 hover:bg-gray-100'
          }`}
          onClick={() => onChange({ ...decision, keep_mine: !decision.keep_mine })}
        >
          {decision.keep_mine ? 'undo' : 'keep mine'}
        </button>
      </td>
    </tr>
  )
}

// ---------------------------------------------------------------------------
// Per-filament review card
// ---------------------------------------------------------------------------

interface FilamentCardProps {
  match: OpenTagFilamentMatch
  decisions: Record<string, OpenTagFieldDecision>
  onFieldChange: (field: string, updated: OpenTagFieldDecision) => void
  onIgnore: (ignored: boolean) => void
  ignored: boolean
}

function FilamentCard({ match, decisions, onFieldChange, onIgnore, ignored }: FilamentCardProps) {
  const [expanded, setExpanded] = useState(true)

  return (
    <div className={`border rounded-lg mb-4 ${ignored ? 'opacity-50' : ''}`}>
      <div
        className="flex items-center justify-between px-4 py-2 bg-gray-50 rounded-t-lg cursor-pointer select-none"
        onClick={() => setExpanded(e => !e)}
      >
        <div className="flex items-center gap-3">
          <ColorSwatch hex={match.spoolman_color_hex} />
          <span className="font-medium text-sm">{match.spoolman_name}</span>
          {match.spoolman_vendor && (
            <span className="text-xs text-gray-500">{match.spoolman_vendor}</span>
          )}
          {match.spoolman_material && (
            <span className="px-1.5 py-0.5 rounded bg-blue-100 text-blue-700 text-xs">
              {match.spoolman_material}
            </span>
          )}
          <span className="text-xs text-gray-400">SM #{match.spoolman_filament_id}</span>
          {match.multicolor_mismatch && (
            <span
              className="px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 text-xs font-medium"
              title="Spoolman has multicolor data but the matched OpenTag entry is single-color"
            >
              multicolor mismatch
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {match.opt_brand && (
            <span className="text-xs text-indigo-600">
              → {match.opt_brand} / {match.opt_name}
            </span>
          )}
          {confidenceBadge(match.confidence)}
          {match.opt_slug && (
            <span className="text-xs text-gray-400 font-mono">{match.opt_slug}</span>
          )}
          <button
            type="button"
            className={`text-xs px-2 py-0.5 rounded border ml-2 ${
              ignored
                ? 'bg-gray-200 border-gray-400 text-gray-700'
                : 'bg-white border-orange-300 text-orange-600 hover:bg-orange-50'
            }`}
            onClick={e => { e.stopPropagation(); onIgnore(!ignored) }}
          >
            {ignored ? 'unignore' : 'ignore match'}
          </button>
          <span className="text-gray-400">{expanded ? '▲' : '▼'}</span>
        </div>
      </div>

      {expanded && !ignored && match.fields.length > 0 && (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm divide-y divide-gray-200">
            <thead>
              <tr className="bg-gray-50 text-xs text-gray-500 uppercase">
                <th className="px-3 py-1 text-left">Field</th>
                <th className="px-3 py-1 text-left">Spoolman</th>
                <th className="px-3 py-1 text-left">OpenTag</th>
                <th className="px-3 py-1 text-left">Use value</th>
                <th className="px-3 py-1 text-left" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {match.fields.map(row => (
                <FieldReviewRow
                  key={row.field}
                  row={row}
                  decision={decisions[row.field] ?? { field: row.field, value: row.opentag_value, keep_mine: false }}
                  onChange={updated => onFieldChange(row.field, updated)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {expanded && !ignored && match.fields.length === 0 && (
        <p className="px-4 py-3 text-sm text-gray-500 italic">
          {match.confidence < 0.30
            ? 'No confident match found — ignore or select an alternate below.'
            : 'No field differences detected.'}
        </p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Confirm step
// ---------------------------------------------------------------------------

interface PendingWrite {
  smId: number
  name: string
  field: string
  oldValue: unknown
  newValue: unknown
}

function ConfirmStep({
  matches,
  fieldDecisions,
  ignoredIds,
  onApply,
  onBack,
  applying,
}: {
  matches: OpenTagFilamentMatch[]
  fieldDecisions: Record<number, Record<string, OpenTagFieldDecision>>
  ignoredIds: Set<number>
  onApply: () => void
  onBack: () => void
  applying: boolean
}) {
  const writes = useMemo<PendingWrite[]>(() => {
    const result: PendingWrite[] = []
    for (const m of matches) {
      if (ignoredIds.has(m.spoolman_filament_id)) continue
      const decisions = fieldDecisions[m.spoolman_filament_id] ?? {}
      for (const row of m.fields) {
        const d = decisions[row.field] ?? { field: row.field, value: row.opentag_value, keep_mine: false }
        if (d.keep_mine || d.value === null || d.value === undefined) continue
        result.push({
          smId: m.spoolman_filament_id,
          name: m.spoolman_name,
          field: row.field,
          oldValue: row.spoolman_value,
          newValue: d.value,
        })
      }
      // slug/uuid now come from match.fields (with the real existing SM value as oldValue).
      // No explicit push here — _build_field_rows on the backend includes them as rows.
    }
    return result
  }, [matches, fieldDecisions, ignoredIds])

  const byFilament = useMemo(() => {
    const groups: Record<number, { name: string; writes: PendingWrite[] }> = {}
    for (const w of writes) {
      if (!groups[w.smId]) groups[w.smId] = { name: w.name, writes: [] }
      groups[w.smId].writes.push(w)
    }
    return groups
  }, [writes])

  return (
    <div>
      <h2 className="text-lg font-semibold mb-1">Confirm writes</h2>
      <p className="text-sm text-gray-600 mb-4">
        {writes.length} field writes across {Object.keys(byFilament).length} filaments.
        {ignoredIds.size > 0 && ` (${ignoredIds.size} ignored)`}
        {' '}Review everything below before applying.
      </p>

      {writes.length === 0 ? (
        <p className="text-gray-500 italic text-sm">Nothing to write — all fields kept or ignored.</p>
      ) : (
        <div className="space-y-4 mb-6">
          {Object.entries(byFilament).map(([smId, { name, writes: ws }]) => (
            <div key={smId} className="border rounded-lg overflow-hidden">
              <div className="px-4 py-2 bg-indigo-50 flex items-center gap-2">
                <span className="font-medium text-sm">{name}</span>
                <span className="text-xs text-gray-500">SM #{smId}</span>
                <span className="ml-auto text-xs text-gray-500">{ws.length} writes</span>
              </div>
              <table className="min-w-full text-xs divide-y divide-gray-200">
                <thead>
                  <tr className="bg-gray-50 text-gray-500 uppercase">
                    <th className="px-3 py-1 text-left">Field</th>
                    <th className="px-3 py-1 text-left">Old</th>
                    <th className="px-3 py-1 text-left">New</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {ws.map(w => (
                    <tr key={w.field}>
                      <td className="px-3 py-1 font-mono text-gray-500">{w.field}</td>
                      <td className="px-3 py-1 text-gray-500">{renderValue(w.oldValue)}</td>
                      <td className="px-3 py-1 text-indigo-700 font-medium">{renderValue(w.newValue)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      )}

      <div className="flex gap-3">
        <button
          type="button"
          className="px-4 py-2 text-sm border border-gray-300 rounded hover:bg-gray-50"
          onClick={onBack}
          disabled={applying}
        >
          Back
        </button>
        <button
          type="button"
          className="px-5 py-2 bg-indigo-600 text-white text-sm rounded hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
          onClick={onApply}
          disabled={applying || writes.length === 0}
        >
          {applying ? 'Applying…' : `Apply ${writes.length} writes`}
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Group / sort controls
// ---------------------------------------------------------------------------

type GroupBy = 'none' | 'brand' | 'material'
type SortBy = 'confidence' | 'brand' | 'material' | 'name'

interface MatchGroup {
  key: string
  matches: OpenTagFilamentMatch[]
}

function groupLabel(groupBy: GroupBy): string {
  if (groupBy === 'brand') return 'Brand'
  if (groupBy === 'material') return 'Material'
  return ''
}

function sortLabel(sortBy: SortBy): string {
  if (sortBy === 'confidence') return 'Confidence (high→low)'
  if (sortBy === 'brand') return 'Brand (A→Z)'
  if (sortBy === 'material') return 'Material (A→Z)'
  return 'Name (A→Z)'
}

function groupKey(m: OpenTagFilamentMatch, groupBy: GroupBy): string {
  if (groupBy === 'brand') return m.spoolman_vendor?.trim() || 'Unknown / no vendor'
  if (groupBy === 'material') return m.spoolman_material?.trim() || 'Unknown / no material'
  return ''
}

function sortMatches(list: OpenTagFilamentMatch[], sortBy: SortBy): OpenTagFilamentMatch[] {
  return [...list].sort((a, b) => {
    if (sortBy === 'confidence') return b.confidence - a.confidence
    if (sortBy === 'brand') {
      const av = (a.spoolman_vendor ?? '').toLowerCase()
      const bv = (b.spoolman_vendor ?? '').toLowerCase()
      if (av !== bv) return av < bv ? -1 : 1
      return (a.spoolman_name ?? '').toLowerCase() < (b.spoolman_name ?? '').toLowerCase() ? -1 : 1
    }
    if (sortBy === 'material') {
      const am = (a.spoolman_material ?? '').toLowerCase()
      const bm = (b.spoolman_material ?? '').toLowerCase()
      if (am !== bm) return am < bm ? -1 : 1
      return (a.spoolman_name ?? '').toLowerCase() < (b.spoolman_name ?? '').toLowerCase() ? -1 : 1
    }
    // name
    return (a.spoolman_name ?? '').toLowerCase() < (b.spoolman_name ?? '').toLowerCase() ? -1 : 1
  })
}

interface GroupSectionProps {
  group: MatchGroup
  fieldDecisions: Record<number, Record<string, OpenTagFieldDecision>>
  ignoredIds: Set<number>
  onFieldChange: (smId: number, field: string, updated: OpenTagFieldDecision) => void
  onIgnore: (smId: number, ignored: boolean) => void
  showHeader: boolean
}

function GroupSection({ group, fieldDecisions, ignoredIds, onFieldChange, onIgnore, showHeader }: GroupSectionProps) {
  const [collapsed, setCollapsed] = useState(false)

  return (
    <div className="mb-4">
      {showHeader && (
        <button
          type="button"
          className="flex items-center gap-2 w-full text-left px-3 py-1.5 bg-gray-100 hover:bg-gray-200 rounded-md mb-2 select-none"
          onClick={() => setCollapsed(c => !c)}
        >
          <span className="text-gray-400 text-xs w-3 shrink-0">
            {collapsed ? '▶' : '▼'}
          </span>
          <span className="text-sm font-semibold text-gray-700">{group.key}</span>
          <span className="text-xs text-gray-400 ml-1">({group.matches.length})</span>
        </button>
      )}
      {!collapsed && group.matches.map(m => (
        <FilamentCard
          key={m.spoolman_filament_id}
          match={m}
          decisions={fieldDecisions[m.spoolman_filament_id] ?? {}}
          onFieldChange={(field, updated) => onFieldChange(m.spoolman_filament_id, field, updated)}
          onIgnore={ignored => onIgnore(m.spoolman_filament_id, ignored)}
          ignored={ignoredIds.has(m.spoolman_filament_id)}
        />
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

type Step = 'review' | 'confirm' | 'done'

export default function OpenTagCleanup() {
  // Cache status — loaded instantly on mount, no fetch
  const [cacheStatus, setCacheStatus] = useState<OpenTagCacheStatus | null>(null)

  // Group / sort state
  const [groupBy, setGroupBy] = useState<GroupBy>('brand')
  const [sortBy, setSortBy] = useState<SortBy>('confidence')

  // Loading / work state
  const [working, setWorking] = useState(false)
  const [statusMsg, setStatusMsg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [response, setResponse] = useState<OpenTagMatchesResponse | null>(null)
  const [step, setStep] = useState<Step>('review')
  const [applying, setApplying] = useState(false)
  const [applyResult, setApplyResult] = useState<{ applied: number; errors: number } | null>(null)

  // Per-filament field decisions: smId → { fieldName → decision }
  const [fieldDecisions, setFieldDecisions] = useState<Record<number, Record<string, OpenTagFieldDecision>>>({})
  // Ignored filament IDs
  const [ignoredIds, setIgnoredIds] = useState<Set<number>>(new Set())

  // Load cache status on mount (instant — no network fetch to FDB)
  useEffect(() => {
    getOpenTagStatus()
      .then(s => setCacheStatus(s))
      .catch(() => { /* status unavailable — banner stays absent */ })
  }, [])

  const _applyMatchesData = useCallback((data: OpenTagMatchesResponse) => {
    setResponse(data)
    // Update cache status banner from the response's dataset meta
    setCacheStatus(prev => ({
      exists: true,
      fetched_at: data.dataset.fetched_at,
      count: data.dataset.count,
      stale: data.dataset.stale,
      max_age_hours: prev?.max_age_hours ?? 24,
    }))
    // Initialize decisions: default to OpenTag values for each field
    const initial: Record<number, Record<string, OpenTagFieldDecision>> = {}
    for (const m of data.matches) {
      initial[m.spoolman_filament_id] = {}
      for (const row of m.fields) {
        initial[m.spoolman_filament_id][row.field] = {
          field: row.field,
          value: row.opentag_value,
          keep_mine: false,
        }
      }
    }
    setFieldDecisions(initial)
  }, [])

  // Run the full load: optionally refresh dataset first, then fetch matches.
  // skipRefresh=true when the cache is already fresh (warm run).
  const runLoad = useCallback(async (skipRefresh: boolean) => {
    setWorking(true)
    setError(null)
    setStatusMsg(null)
    try {
      if (!skipRefresh) {
        setStatusMsg(
          'Fetching the OpenTag dataset from Filament DB… ' +
          '(first load downloads ≈​11k records — up to a minute)',
        )
        await postOpenTagRefresh()
        // Refresh status banner after fetch
        getOpenTagStatus().then(s => setCacheStatus(s)).catch(() => {})
      }
      setStatusMsg('Matching your Spoolman filaments…')
      const data = await getOpenTagMatches()
      _applyMatchesData(data)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setWorking(false)
      setStatusMsg(null)
    }
  }, [_applyMatchesData])

  // On mount: once status is known, kick off the appropriate load
  const [autoLoadDone, setAutoLoadDone] = useState(false)
  useEffect(() => {
    if (cacheStatus === null) return   // still waiting for status
    if (autoLoadDone) return           // already started
    setAutoLoadDone(true)
    runLoad(cacheStatus.exists && !cacheStatus.stale)
  }, [cacheStatus, autoLoadDone, runLoad])

  // Refresh button: always force a fresh fetch
  const handleRefresh = useCallback(async () => {
    runLoad(false)
  }, [runLoad])

  const handleFieldChange = useCallback(
    (smId: number, field: string, updated: OpenTagFieldDecision) => {
      setFieldDecisions(prev => ({
        ...prev,
        [smId]: { ...(prev[smId] ?? {}), [field]: updated },
      }))
    },
    [],
  )

  const handleIgnore = useCallback((smId: number, ignored: boolean) => {
    setIgnoredIds(prev => {
      const next = new Set(prev)
      if (ignored) next.add(smId)
      else next.delete(smId)
      return next
    })
  }, [])

  const handleApply = async () => {
    if (!response) return
    setApplying(true)
    setError(null)
    try {
      const decisions: OpenTagFilamentDecision[] = response.matches.map(m => {
        if (ignoredIds.has(m.spoolman_filament_id)) {
          return { spoolman_filament_id: m.spoolman_filament_id, ignored: true, fields: [] }
        }
        const dMap = fieldDecisions[m.spoolman_filament_id] ?? {}
        const fields: OpenTagFieldDecision[] = m.fields.map(row => {
          const d = dMap[row.field] ?? { field: row.field, value: row.opentag_value, keep_mine: false }
          return d
        })
        return {
          spoolman_filament_id: m.spoolman_filament_id,
          ignored: false,
          fields,
          openprinttag_slug: m.opt_slug ?? undefined,
          openprinttag_uuid: m.opt_uuid ?? undefined,
        }
      })
      const req: OpenTagApplyRequest = { decisions }
      const result = await postOpenTagApply(req)
      setApplyResult({ applied: result.applied, errors: result.errors })
      setStep('done')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setApplying(false)
    }
  }

  const matches = response?.matches ?? []
  const withMatch = matches.filter(m => m.confidence >= 0.30)
  const noMatch = matches.filter(m => m.confidence < 0.30)

  // Grouped + sorted display for the review step
  const displayGroups = useMemo<MatchGroup[]>(() => {
    const sorted = sortMatches(withMatch, sortBy)
    if (groupBy === 'none') {
      return [{ key: '', matches: sorted }]
    }
    // Build ordered group map
    const order: string[] = []
    const map = new Map<string, OpenTagFilamentMatch[]>()
    for (const m of sorted) {
      const k = groupKey(m, groupBy)
      if (!map.has(k)) {
        order.push(k)
        map.set(k, [])
      }
      map.get(k)!.push(m)
    }
    // Sort group keys A→Z (unknown last)
    order.sort((a, b) => {
      const aUnknown = a.startsWith('Unknown')
      const bUnknown = b.startsWith('Unknown')
      if (aUnknown && !bUnknown) return 1
      if (!aUnknown && bUnknown) return -1
      return a.toLowerCase() < b.toLowerCase() ? -1 : 1
    })
    return order.map(k => ({ key: k, matches: map.get(k)! }))
  }, [withMatch, groupBy, sortBy])

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <h1 className="text-2xl font-bold mb-1">OpenTag Cleanup</h1>
      <p className="text-sm text-gray-500 mb-6">
        Match your Spoolman filaments against the OpenPrintTag database, review field
        differences, and apply canonical data — including pushing OpenTag identity into
        Filament DB.
      </p>

      {/* Dataset status banner — populated instantly from cache, no FDB fetch */}
      <div className="flex items-center gap-4 mb-6 p-3 bg-gray-50 border border-gray-200 rounded-lg">
        {cacheStatus?.exists ? (
          <>
            <span className="text-sm text-gray-600">
              OpenTag dataset: <strong>{cacheStatus.count}</strong> materials
            </span>
            <span className="text-sm text-gray-500">
              fetched {formatAge(cacheStatus.fetched_at)}
            </span>
            {cacheStatus.stale && (
              <span className="px-2 py-0.5 rounded bg-yellow-100 text-yellow-800 text-xs">stale</span>
            )}
          </>
        ) : (
          <span className="text-sm text-gray-500">
            {cacheStatus === null ? 'Checking dataset cache…' : 'No dataset cached yet.'}
          </span>
        )}
        <button
          type="button"
          className="ml-auto px-3 py-1 text-sm border border-indigo-300 text-indigo-600 rounded hover:bg-indigo-50 disabled:opacity-50"
          onClick={handleRefresh}
          disabled={working}
        >
          {working ? 'Working…' : 'Refresh dataset'}
        </button>
      </div>

      {error && (
        <div className="mb-4 px-4 py-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">
          <strong>Error:</strong> {error}
        </div>
      )}

      {working && statusMsg && (
        <div className="mb-4 flex items-center gap-3 px-4 py-3 bg-blue-50 border border-blue-200 rounded text-sm text-blue-700">
          <svg className="animate-spin h-4 w-4 shrink-0 text-blue-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
          </svg>
          {statusMsg}
        </div>
      )}

      {!working && step === 'review' && response && (
        <div>
          <div className="flex items-center justify-between mb-4">
            <p className="text-sm text-gray-600">
              {withMatch.length} matches found, {noMatch.length} unmatched, {ignoredIds.size} ignored
            </p>
            <button
              type="button"
              className="px-4 py-2 bg-indigo-600 text-white text-sm rounded hover:bg-indigo-700 disabled:opacity-50"
              onClick={() => setStep('confirm')}
              disabled={withMatch.length === 0}
            >
              Review &amp; Confirm →
            </button>
          </div>

          {/* Group / sort controls */}
          <div className="flex flex-wrap items-center gap-4 mb-3 px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg">
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-500 font-medium">Group by:</span>
              {(['none', 'brand', 'material'] as GroupBy[]).map(g => (
                <button
                  key={g}
                  type="button"
                  className={`text-xs px-2 py-0.5 rounded border transition-colors ${
                    groupBy === g
                      ? 'bg-indigo-100 border-indigo-400 text-indigo-700 font-semibold'
                      : 'bg-white border-gray-300 text-gray-600 hover:bg-gray-100'
                  }`}
                  onClick={() => setGroupBy(g)}
                >
                  {g === 'none' ? 'None' : groupLabel(g)}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-500 font-medium">Sort by:</span>
              {(['confidence', 'brand', 'material', 'name'] as SortBy[]).map(s => (
                <button
                  key={s}
                  type="button"
                  className={`text-xs px-2 py-0.5 rounded border transition-colors ${
                    sortBy === s
                      ? 'bg-indigo-100 border-indigo-400 text-indigo-700 font-semibold'
                      : 'bg-white border-gray-300 text-gray-600 hover:bg-gray-100'
                  }`}
                  onClick={() => setSortBy(s)}
                  title={sortLabel(s)}
                >
                  {s === 'confidence' ? 'Confidence' : s === 'brand' ? 'Brand' : s === 'material' ? 'Material' : 'Name'}
                </button>
              ))}
            </div>
          </div>

          {/* Bulk-action bar */}
          <div className="flex items-center gap-3 mb-4 px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg">
            <span className="text-sm text-gray-600">
              {withMatch.length - withMatch.filter(m => ignoredIds.has(m.spoolman_filament_id)).length} of {withMatch.length} selected
            </span>
            <div className="ml-auto flex items-center gap-2">
              <button
                type="button"
                className="text-xs px-3 py-1 rounded border border-gray-300 bg-white text-gray-700 hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed"
                onClick={() => setIgnoredIds(new Set())}
                disabled={withMatch.length === 0}
              >
                Select all
              </button>
              <button
                type="button"
                className="text-xs px-3 py-1 rounded border border-orange-300 bg-white text-orange-600 hover:bg-orange-50 disabled:opacity-40 disabled:cursor-not-allowed"
                onClick={() => setIgnoredIds(new Set(withMatch.map(m => m.spoolman_filament_id)))}
                disabled={withMatch.length === 0}
              >
                Ignore all
              </button>
            </div>
          </div>

          {withMatch.length === 0 && noMatch.length === 0 && (
            <p className="text-gray-500 italic text-sm">No Spoolman filaments found.</p>
          )}

          {displayGroups.map(group => (
            <GroupSection
              key={group.key || '__flat__'}
              group={group}
              fieldDecisions={fieldDecisions}
              ignoredIds={ignoredIds}
              onFieldChange={handleFieldChange}
              onIgnore={handleIgnore}
              showHeader={groupBy !== 'none'}
            />
          ))}

          {noMatch.length > 0 && (
            <details className="mt-4">
              <summary className="text-sm text-gray-500 cursor-pointer select-none">
                {noMatch.length} unmatched filaments (confidence &lt; 30%)
              </summary>
              <div className="mt-2 space-y-1 pl-4">
                {noMatch.map(m => (
                  <div key={m.spoolman_filament_id} className="text-sm text-gray-400">
                    {m.spoolman_name} ({m.spoolman_vendor}) — {Math.round(m.confidence * 100)}%
                  </div>
                ))}
              </div>
            </details>
          )}
        </div>
      )}

      {!working && step === 'confirm' && response && (
        <ConfirmStep
          matches={matches}
          fieldDecisions={fieldDecisions}
          ignoredIds={ignoredIds}
          onApply={handleApply}
          onBack={() => setStep('review')}
          applying={applying}
        />
      )}

      {step === 'done' && applyResult && (
        <div className="px-6 py-8 text-center">
          <div className="text-4xl mb-4">{applyResult.errors === 0 ? '✓' : '⚠'}</div>
          <h2 className="text-xl font-semibold mb-2">
            {applyResult.errors === 0 ? 'Done!' : 'Completed with errors'}
          </h2>
          <p className="text-gray-600 mb-6">
            Applied {applyResult.applied} filament updates.
            {applyResult.errors > 0 && ` ${applyResult.errors} errors — check the sync log.`}
          </p>
          <button
            type="button"
            className="px-4 py-2 border border-gray-300 rounded text-sm hover:bg-gray-50"
            onClick={() => { setStep('review'); runLoad(true) }}
          >
            Start over
          </button>
        </div>
      )}
    </div>
  )
}
