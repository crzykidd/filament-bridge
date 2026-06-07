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
  postOpenTagApply,
  postOpenTagRefresh,
} from '../api/client'
import type {
  OpenTagApplyRequest,
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
      // slug/uuid are always written if present
      if (m.opt_slug) result.push({ smId: m.spoolman_filament_id, name: m.spoolman_name, field: 'extra.openprinttag_slug', oldValue: null, newValue: m.opt_slug })
      if (m.opt_uuid) result.push({ smId: m.spoolman_filament_id, name: m.spoolman_name, field: 'extra.openprinttag_uuid', oldValue: null, newValue: m.opt_uuid })
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
// Main page
// ---------------------------------------------------------------------------

type Step = 'review' | 'confirm' | 'done'

export default function OpenTagCleanup() {
  const [loading, setLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [response, setResponse] = useState<OpenTagMatchesResponse | null>(null)
  const [step, setStep] = useState<Step>('review')
  const [applying, setApplying] = useState(false)
  const [applyResult, setApplyResult] = useState<{ applied: number; errors: number } | null>(null)

  // Per-filament field decisions: smId → { fieldName → decision }
  const [fieldDecisions, setFieldDecisions] = useState<Record<number, Record<string, OpenTagFieldDecision>>>({})
  // Ignored filament IDs
  const [ignoredIds, setIgnoredIds] = useState<Set<number>>(new Set())

  const fetchMatches = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getOpenTagMatches()
      setResponse(data)
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
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchMatches()
  }, [fetchMatches])

  const handleRefresh = async () => {
    setRefreshing(true)
    setError(null)
    try {
      await postOpenTagRefresh()
      await fetchMatches()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setRefreshing(false)
    }
  }

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

  const dataset: OpenTagDatasetMeta | null = response?.dataset ?? null
  const matches = response?.matches ?? []
  const withMatch = matches.filter(m => m.confidence >= 0.30)
  const noMatch = matches.filter(m => m.confidence < 0.30)

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <h1 className="text-2xl font-bold mb-1">OpenTag Cleanup</h1>
      <p className="text-sm text-gray-500 mb-6">
        Match your Spoolman filaments against the OpenPrintTag database, review field
        differences, and apply canonical data — including pushing OpenTag identity into
        Filament DB.
      </p>

      {/* Dataset status bar */}
      <div className="flex items-center gap-4 mb-6 p-3 bg-gray-50 border border-gray-200 rounded-lg">
        {dataset ? (
          <>
            <span className="text-sm text-gray-600">
              Dataset: <strong>{dataset.count}</strong> materials
            </span>
            <span className="text-sm text-gray-500">
              Fetched {formatAge(dataset.fetched_at)}
            </span>
            {dataset.stale && (
              <span className="px-2 py-0.5 rounded bg-yellow-100 text-yellow-800 text-xs">stale</span>
            )}
          </>
        ) : (
          <span className="text-sm text-gray-500">No cached dataset</span>
        )}
        <button
          type="button"
          className="ml-auto px-3 py-1 text-sm border border-indigo-300 text-indigo-600 rounded hover:bg-indigo-50 disabled:opacity-50"
          onClick={handleRefresh}
          disabled={refreshing || loading}
        >
          {refreshing ? 'Refreshing…' : 'Refresh dataset'}
        </button>
      </div>

      {error && (
        <div className="mb-4 px-4 py-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">
          <strong>Error:</strong> {error}
        </div>
      )}

      {(loading || refreshing) && (
        <div className="mb-4 px-4 py-3 bg-blue-50 border border-blue-200 rounded text-sm text-blue-700">
          {refreshing
            ? 'Refreshing dataset from Filament DB — the first download can take 20–60 seconds…'
            : 'Loading matches — fetching the OpenTag dataset from Filament DB if not cached (first load can take 20–60 seconds)…'}
        </div>
      )}

      {!loading && step === 'review' && response && (
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

          {withMatch.length === 0 && noMatch.length === 0 && (
            <p className="text-gray-500 italic text-sm">No Spoolman filaments found.</p>
          )}

          {withMatch.map(m => (
            <FilamentCard
              key={m.spoolman_filament_id}
              match={m}
              decisions={fieldDecisions[m.spoolman_filament_id] ?? {}}
              onFieldChange={(field, updated) =>
                handleFieldChange(m.spoolman_filament_id, field, updated)
              }
              onIgnore={ignored => handleIgnore(m.spoolman_filament_id, ignored)}
              ignored={ignoredIds.has(m.spoolman_filament_id)}
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

      {!loading && step === 'confirm' && response && (
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
            onClick={() => { setStep('review'); fetchMatches() }}
          >
            Start over
          </button>
        </div>
      )}
    </div>
  )
}
