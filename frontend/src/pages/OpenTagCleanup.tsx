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
import { BackupSafetyDialog } from '../components/BackupSafetyDialog'
import { DeepLinks } from '../components/DeepLinks'
import { HelpTip } from '../components/HelpTip'
import type {
  OpenTagApplyRequest,
  OpenTagCacheStatus,
  OpenTagCandidate,
  OpenTagDatasetMeta,
  OpenTagFieldDecision,
  OpenTagFieldRow,
  OpenTagFilamentDecision,
  OpenTagFilamentMatch,
  OpenTagMatchesResponse,
} from '../api/types'
import { parseUtc } from '../utils/datetime'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatAge(fetchedAt: string | null): string {
  if (!fetchedAt) return 'never'
  const d = parseUtc(fetchedAt)
  const diffMs = Date.now() - d.getTime()
  const h = Math.floor(diffMs / 3_600_000)
  const m = Math.floor((diffMs % 3_600_000) / 60_000)
  if (h > 0) return `${h}h ${m}m ago`
  return `${m}m ago`
}

function confidenceBadge(c: number) {
  const pct = Math.round(c * 100)
  const bg =
    pct >= 70 ? 'bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-300' :
    pct >= 40 ? 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-800 dark:text-yellow-300' :
    'bg-red-100 dark:bg-red-900/30 text-red-800 dark:text-red-300'
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
      className="inline-block w-4 h-4 rounded border border-gray-300 dark:border-gray-600 align-middle mr-1"
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
    <tr className="hover:bg-gray-50 dark:hover:bg-gray-700/40">
      <td className="px-3 py-2 text-xs font-mono text-gray-500 dark:text-gray-400 whitespace-nowrap">{row.field}</td>
      <td className="px-3 py-2 text-sm text-gray-700 dark:text-gray-300">
        {isColor && <ColorSwatch hex={renderValue(row.spoolman_value)} />}
        {renderValue(row.spoolman_value)}
      </td>
      <td className="px-3 py-2 text-sm text-indigo-700 dark:text-indigo-400">
        {isColor && <ColorSwatch hex={renderValue(row.opentag_value)} />}
        {renderValue(row.opentag_value)}
      </td>
      <td className="px-3 py-2">
        {decision.keep_mine ? (
          <span className="text-xs text-gray-600 dark:text-gray-400 italic">keeping mine</span>
        ) : (
          <div className="flex items-center gap-1">
            {isColor && <ColorSwatch hex={colorHex} />}
            <input
              type={typeof decision.value === 'number' ? 'number' : 'text'}
              className="border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 rounded px-2 py-0.5 text-xs w-32 focus:outline-none focus:ring-1 focus:ring-indigo-400"
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
        <span className="inline-flex items-center">
          <button
            type="button"
            className={`text-xs px-2 py-0.5 rounded border transition-colors ${
              decision.keep_mine
                ? 'bg-gray-100 dark:bg-gray-700 border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-200 dark:hover:bg-gray-600'
                : 'bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-600 text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700'
            }`}
            onClick={() => onChange({ ...decision, keep_mine: !decision.keep_mine })}
          >
            {decision.keep_mine ? 'undo' : 'keep mine'}
          </button>
          {!decision.keep_mine && (
            <HelpTip text="Skips this field when applying — your current Spoolman value stays." />
          )}
        </span>
      </td>
    </tr>
  )
}

// ---------------------------------------------------------------------------
// Candidate dropdown option label
// ---------------------------------------------------------------------------

function candidateLabel(c: OpenTagCandidate): string {
  const pct = Math.round(c.confidence * 100)
  return `${c.opt_brand ?? '?'} · ${c.opt_name ?? '?'}  (${pct}%)`
}

// ---------------------------------------------------------------------------
// OpenTag stamped-badge helpers
// ---------------------------------------------------------------------------

/** Normalize a field value for comparison: lowercase + trim, null / "" / "—" → "". */
function normalizeFieldValue(v: unknown): string {
  if (v === null || v === undefined) return ''
  const s = String(v).trim().toLowerCase()
  if (s === '' || s === '—') return ''
  return s
}

const IDENTITY_FIELDS = new Set(['extra.openprinttag_slug', 'extra.openprinttag_uuid'])

/**
 * Derive the badge state for a filament card.
 * - existingUuid: the current Spoolman value of extra.openprinttag_uuid (candidate-independent).
 * - dataDiffers: true when the selected candidate has any non-identity field whose
 *   normalised spoolman_value ≠ normalised opentag_value.
 */
function computeBadgeState(
  match: OpenTagFilamentMatch,
  activeCandidate: OpenTagCandidate | null,
): { existingUuid: string; dataDiffers: boolean } {
  // existingUuid — find in top-level fields first, then candidate fields.
  const allFieldSources: OpenTagFieldRow[][] = [match.fields]
  if (activeCandidate) allFieldSources.push(activeCandidate.fields)
  let existingUuid = ''
  for (const rows of allFieldSources) {
    const uuidRow = rows.find(r => r.field === 'extra.openprinttag_uuid')
    if (uuidRow !== undefined) {
      existingUuid = normalizeFieldValue(uuidRow.spoolman_value)
      break
    }
  }

  // dataDiffers — over the active candidate's (or top-level) display fields,
  // excluding identity fields.
  const displayRows = activeCandidate ? activeCandidate.fields : match.fields
  const dataDiffers = displayRows
    .filter(r => !IDENTITY_FIELDS.has(r.field))
    .some(
      r => normalizeFieldValue(r.spoolman_value) !== normalizeFieldValue(r.opentag_value),
    )

  return { existingUuid, dataDiffers }
}

/** Small badge shown when the Spoolman filament already carries an OPT uuid. */
function OpenTagStampedBadge({ existingUuid, dataDiffers }: { existingUuid: string; dataDiffers: boolean }) {
  if (!existingUuid) return null
  if (dataDiffers) {
    return (
      <span
        className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded border text-xs font-medium bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 border-amber-300 dark:border-amber-700"
        title="Tagged in OpenPrintTag — Spoolman data differs from OpenTag"
      >
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" className="w-3 h-3 shrink-0">
          <path d="M2 3a1 1 0 0 1 1-1h4.586a1 1 0 0 1 .707.293l5.414 5.414a1 1 0 0 1 0 1.414l-4.586 4.586a1 1 0 0 1-1.414 0L2.293 8.293A1 1 0 0 1 2 7.586V3Z" />
        </svg>
        OPT
      </span>
    )
  }
  return (
    <span
      className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded border text-xs font-medium bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400 border-gray-200 dark:border-gray-600"
      title="Already tagged in OpenPrintTag — in sync"
    >
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" className="w-3 h-3 shrink-0">
        <path d="M2 3a1 1 0 0 1 1-1h4.586a1 1 0 0 1 .707.293l5.414 5.414a1 1 0 0 1 0 1.414l-4.586 4.586a1 1 0 0 1-1.414 0L2.293 8.293A1 1 0 0 1 2 7.586V3Z" />
      </svg>
      OPT
    </span>
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
  selectedCandidateIdx: number
  onCandidateChange: (idx: number) => void
}

function FilamentCard({
  match,
  decisions,
  onFieldChange,
  onIgnore,
  ignored,
  selectedCandidateIdx,
  onCandidateChange,
}: FilamentCardProps) {
  const [expanded, setExpanded] = useState(true)

  // Active candidate: use structured candidates[selectedCandidateIdx] when available,
  // otherwise fall back to the top-level match fields (backward-compat / no-match rows).
  const activeCandidateIdx = Math.min(
    selectedCandidateIdx,
    Math.max(0, (match.candidates?.length ?? 1) - 1),
  )
  const activeCandidate: OpenTagCandidate | null =
    match.candidates && match.candidates.length > 0
      ? match.candidates[activeCandidateIdx]
      : null

  const displayFields = activeCandidate ? activeCandidate.fields : match.fields
  const displayConfidence = activeCandidate ? activeCandidate.confidence : match.confidence
  const displayMulticolorMismatch = activeCandidate
    ? activeCandidate.multicolor_mismatch
    : (match.multicolor_mismatch ?? false)

  const hasCandidates = match.candidates && match.candidates.length > 1

  // Badge state — recomputed when activeCandidate changes (candidate switch updates dataDiffers).
  const { existingUuid, dataDiffers } = computeBadgeState(match, activeCandidate)

  return (
    <div className={`border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 rounded-lg mb-4 ${ignored ? 'opacity-50' : ''}`}>
      <div
        className="flex items-center justify-between px-4 py-2 bg-gray-50 dark:bg-gray-900/40 rounded-t-lg cursor-pointer select-none"
        onClick={() => setExpanded(e => !e)}
      >
        <div className="flex items-center gap-3">
          <ColorSwatch hex={match.spoolman_color_hex} />
          <span className="font-medium text-sm text-gray-900 dark:text-gray-100">{match.spoolman_name}</span>
          {match.spoolman_vendor && (
            <span className="text-xs text-gray-500 dark:text-gray-400">{match.spoolman_vendor}</span>
          )}
          {match.spoolman_material && (
            <span className="px-1.5 py-0.5 rounded bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 text-xs">
              {match.spoolman_material}
            </span>
          )}
          <DeepLinks spoolmanFilamentId={match.spoolman_filament_id} />
          {displayMulticolorMismatch && (
            <span
              className="px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-900/30 text-amber-800 dark:text-amber-300 text-xs font-medium"
              title="Spoolman has multicolor data but the matched OpenTag entry is single-color"
            >
              multicolor mismatch
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {/* Candidate dropdown — shown when there are multiple candidates */}
          {hasCandidates && (
            <select
              className="text-xs border border-indigo-200 dark:border-indigo-700 rounded px-1 py-0.5 bg-white dark:bg-gray-700 text-indigo-700 dark:text-indigo-300 max-w-xs focus:outline-none focus:ring-1 focus:ring-indigo-400"
              value={activeCandidateIdx}
              onClick={e => e.stopPropagation()}
              onChange={e => {
                e.stopPropagation()
                onCandidateChange(Number(e.target.value))
              }}
            >
              {match.candidates!.map((c, i) => (
                <option key={c.opt_uuid ?? c.opt_slug ?? i} value={i}>
                  {i === 0 ? '★ ' : ''}{candidateLabel(c)}
                </option>
              ))}
            </select>
          )}
          {!hasCandidates && activeCandidate && (
            <span className="text-xs text-indigo-600 dark:text-indigo-400">
              → {activeCandidate.opt_brand} / {activeCandidate.opt_name}
            </span>
          )}
          {!hasCandidates && !activeCandidate && match.opt_brand && (
            <span className="text-xs text-indigo-600 dark:text-indigo-400">
              → {match.opt_brand} / {match.opt_name}
            </span>
          )}
          <OpenTagStampedBadge existingUuid={existingUuid} dataDiffers={dataDiffers} />
          <span className="inline-flex items-center">
            {confidenceBadge(displayConfidence)}
            <HelpTip
              text="Match score vs the OpenTag entry: material, brand, color name, color hex, and finish all contribute. Below 30% = unmatched."
              learnMoreHref="/docs/opentag-cleanup"
            />
          </span>
          {(activeCandidate?.opt_slug ?? match.opt_slug) && (
            <span className="text-xs text-gray-600 dark:text-gray-400 font-mono">
              {activeCandidate?.opt_slug ?? match.opt_slug}
            </span>
          )}
          {activeCandidate?.opt_color_hex && (
            <ColorSwatch hex={activeCandidate.opt_color_hex} />
          )}
          <span className="inline-flex items-center ml-2" onClick={e => e.stopPropagation()}>
            <button
              type="button"
              className={`text-xs px-2 py-0.5 rounded border ${
                ignored
                  ? 'bg-gray-200 dark:bg-gray-700 border-gray-400 dark:border-gray-600 text-gray-700 dark:text-gray-200'
                  : 'bg-white dark:bg-gray-800 border-orange-300 dark:border-orange-700 text-orange-600 dark:text-orange-400 hover:bg-orange-50 dark:hover:bg-orange-900/20'
              }`}
              onClick={() => onIgnore(!ignored)}
            >
              {ignored ? 'unignore' : 'ignore match'}
            </button>
            {!ignored && (
              <HelpTip text="Excludes this filament from the apply entirely." />
            )}
          </span>
          <span className="text-gray-400 dark:text-gray-500">{expanded ? '▲' : '▼'}</span>
        </div>
      </div>

      {expanded && !ignored && displayFields.length > 0 && (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm divide-y divide-gray-200 dark:divide-gray-700">
            <thead>
              <tr className="bg-gray-50 dark:bg-gray-900/40 text-xs text-gray-500 dark:text-gray-400 uppercase">
                <th className="px-3 py-1 text-left">Field</th>
                <th className="px-3 py-1 text-left">Spoolman</th>
                <th className="px-3 py-1 text-left">OpenTag</th>
                <th className="px-3 py-1 text-left">Use value</th>
                <th className="px-3 py-1 text-left" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
              {displayFields.map(row => (
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

      {expanded && !ignored && displayFields.length === 0 && (
        <p className="px-4 py-3 text-sm text-gray-500 dark:text-gray-400 italic">
          {displayConfidence < 0.30
            ? (match.no_match_reason ?? 'No confident match found — ignore or select an alternate below.')
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
  selectedCandidates,
  onApply,
  onBack,
  applying,
}: {
  matches: OpenTagFilamentMatch[]
  fieldDecisions: Record<number, Record<string, OpenTagFieldDecision>>
  ignoredIds: Set<number>
  selectedCandidates: Record<number, number>
  onApply: () => void
  onBack: () => void
  applying: boolean
}) {
  const writes = useMemo<PendingWrite[]>(() => {
    const result: PendingWrite[] = []
    for (const m of matches) {
      if (ignoredIds.has(m.spoolman_filament_id)) continue
      const decisions = fieldDecisions[m.spoolman_filament_id] ?? {}
      const candidateIdx = selectedCandidates[m.spoolman_filament_id] ?? 0
      const activeFields = m.candidates?.[candidateIdx]?.fields ?? m.fields
      for (const row of activeFields) {
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
  }, [matches, fieldDecisions, ignoredIds, selectedCandidates])

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
      <h2 className="text-lg font-semibold mb-1 text-gray-900 dark:text-gray-100">Confirm writes</h2>
      <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
        {writes.length} field writes across {Object.keys(byFilament).length} filaments.
        {ignoredIds.size > 0 && ` (${ignoredIds.size} ignored)`}
        {' '}Review everything below before applying.
      </p>

      {writes.length === 0 ? (
        <p className="text-gray-500 dark:text-gray-400 italic text-sm">Nothing to write — all fields kept or ignored.</p>
      ) : (
        <div className="space-y-4 mb-6">
          {Object.entries(byFilament).map(([smId, { name, writes: ws }]) => (
            <div key={smId} className="border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 rounded-lg overflow-hidden">
              <div className="px-4 py-2 bg-indigo-50 dark:bg-indigo-900/30 flex items-center gap-2">
                <span className="font-medium text-sm text-gray-900 dark:text-gray-100">{name}</span>
                <span className="text-xs text-gray-500 dark:text-gray-400">SM #{smId}</span>
                <span className="ml-auto text-xs text-gray-500 dark:text-gray-400">{ws.length} writes</span>
              </div>
              <table className="min-w-full text-xs divide-y divide-gray-200 dark:divide-gray-700">
                <thead>
                  <tr className="bg-gray-50 dark:bg-gray-900/40 text-gray-500 dark:text-gray-400 uppercase">
                    <th className="px-3 py-1 text-left">Field</th>
                    <th className="px-3 py-1 text-left">Old</th>
                    <th className="px-3 py-1 text-left">New</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                  {ws.map(w => (
                    <tr key={w.field}>
                      <td className="px-3 py-1 font-mono text-gray-500 dark:text-gray-400">{w.field}</td>
                      <td className="px-3 py-1 text-gray-500 dark:text-gray-400">{renderValue(w.oldValue)}</td>
                      <td className="px-3 py-1 text-indigo-700 dark:text-indigo-400 font-medium">{renderValue(w.newValue)}</td>
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
          className="px-4 py-2 text-sm border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 rounded hover:bg-gray-50 dark:hover:bg-gray-700"
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
type SortBy = 'confidence' | 'brand' | 'material' | 'name' | 'spoolman_id'

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
  if (sortBy === 'spoolman_id') return 'Spoolman ID (low→high)'
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
    if (sortBy === 'spoolman_id') return a.spoolman_filament_id - b.spoolman_filament_id
    // name
    return (a.spoolman_name ?? '').toLowerCase() < (b.spoolman_name ?? '').toLowerCase() ? -1 : 1
  })
}

interface GroupSectionProps {
  group: MatchGroup
  fieldDecisions: Record<number, Record<string, OpenTagFieldDecision>>
  ignoredIds: Set<number>
  selectedCandidates: Record<number, number>
  onFieldChange: (smId: number, field: string, updated: OpenTagFieldDecision) => void
  onIgnore: (smId: number, ignored: boolean) => void
  onCandidateChange: (smId: number, idx: number, match: OpenTagFilamentMatch) => void
  showHeader: boolean
  collapsed: boolean
  onToggleCollapse: () => void
  onIgnoreAll: (ignoreAll: boolean) => void
}

/** Derive the existingUuid for a match from its field rows (same logic as computeBadgeState). */
function getExistingUuid(match: OpenTagFilamentMatch, activeCandidate: OpenTagCandidate | null): string {
  const sources = [match.fields]
  if (activeCandidate) sources.push(activeCandidate.fields)
  for (const rows of sources) {
    const row = rows.find(r => r.field === 'extra.openprinttag_uuid')
    if (row !== undefined) return normalizeFieldValue(row.spoolman_value)
  }
  return ''
}

function GroupSection({
  group,
  fieldDecisions,
  ignoredIds,
  selectedCandidates,
  onFieldChange,
  onIgnore,
  onCandidateChange,
  showHeader,
  collapsed,
  onToggleCollapse,
  onIgnoreAll,
}: GroupSectionProps) {
  // Compute group summary counts
  const matchedCount = group.matches.filter(m => m.opt_uuid != null || m.confidence > 0).length
  const noMatchCount = group.matches.filter(m => m.opt_uuid == null).length
  const taggedCount = group.matches.filter(m => {
    const candidateIdx = selectedCandidates[m.spoolman_filament_id] ?? 0
    const activeCandidate = m.candidates?.[candidateIdx] ?? null
    return getExistingUuid(m, activeCandidate) !== ''
  }).length
  const total = group.matches.length

  const allIgnored = group.matches.length > 0 && group.matches.every(m => ignoredIds.has(m.spoolman_filament_id))

  return (
    <div className="mb-4">
      {showHeader && (
        <div
          className="flex items-center gap-2 w-full px-3 py-1.5 bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 rounded-md mb-2 select-none cursor-pointer"
          onClick={onToggleCollapse}
        >
          <span className="text-gray-400 dark:text-gray-500 text-xs w-3 shrink-0">
            {collapsed ? '▸' : '▾'}
          </span>
          <span className="text-sm font-semibold text-gray-700 dark:text-gray-200">{group.key}</span>
          <span className="text-xs text-gray-500 dark:text-gray-400 ml-1">
            {matchedCount} matched · {noMatchCount} no-match · {taggedCount} tagged
            <span className="ml-1 text-gray-500 dark:text-gray-400">({total})</span>
          </span>
          <button
            type="button"
            className={`ml-auto text-xs px-2 py-0.5 rounded border transition-colors ${
              allIgnored
                ? 'bg-gray-200 dark:bg-gray-700 border-gray-400 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-300 dark:hover:bg-gray-600'
                : 'bg-white dark:bg-gray-800 border-orange-300 dark:border-orange-700 text-orange-600 dark:text-orange-400 hover:bg-orange-50 dark:hover:bg-orange-900/20'
            }`}
            onClick={e => { e.stopPropagation(); onIgnoreAll(!allIgnored) }}
          >
            {allIgnored ? 'Unignore all' : 'Ignore all'}
          </button>
        </div>
      )}
      {!collapsed && group.matches.map(m => (
        <FilamentCard
          key={m.spoolman_filament_id}
          match={m}
          decisions={fieldDecisions[m.spoolman_filament_id] ?? {}}
          onFieldChange={(field, updated) => onFieldChange(m.spoolman_filament_id, field, updated)}
          onIgnore={ignored => onIgnore(m.spoolman_filament_id, ignored)}
          ignored={ignoredIds.has(m.spoolman_filament_id)}
          selectedCandidateIdx={selectedCandidates[m.spoolman_filament_id] ?? 0}
          onCandidateChange={(idx) => onCandidateChange(m.spoolman_filament_id, idx, m)}
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
  const [showBackupDialog, setShowBackupDialog] = useState(false)

  // Per-filament field decisions: smId → { fieldName → decision }
  const [fieldDecisions, setFieldDecisions] = useState<Record<number, Record<string, OpenTagFieldDecision>>>({})
  // Ignored filament IDs
  const [ignoredIds, setIgnoredIds] = useState<Set<number>>(new Set())
  // Per-filament selected candidate index (default 0 = best)
  const [selectedCandidates, setSelectedCandidates] = useState<Record<number, number>>({})
  // Per-group collapsed state: group key → collapsed (default: all collapsed)
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({})

  // Filter toggles
  const [hideMatched, setHideMatched] = useState(false)
  const [hideAlreadyTagged, setHideAlreadyTagged] = useState(false)

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
      last_count: Math.max(data.dataset.count, prev?.last_count ?? 0),
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
    // Reset candidate selections — new data means start from best (index 0)
    setSelectedCandidates({})
  }, [])

  // Run the full load: optionally refresh dataset first, then fetch matches.
  // skipRefresh=true when the cache is already fresh (warm run).
  const runLoad = useCallback(async (skipRefresh: boolean) => {
    setWorking(true)
    setError(null)
    setStatusMsg(null)
    try {
      if (!skipRefresh) {
        const known = cacheStatus?.last_count || cacheStatus?.count || 0
        const recordHint = known > 0 ? `${known.toLocaleString()}+ records` : 'thousands of records'
        setStatusMsg(
          'Fetching the OpenTag dataset from Filament DB… ' +
          `(first load downloads ${recordHint} — up to a minute)`,
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
  }, [_applyMatchesData, cacheStatus])

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

  // When the user picks a different candidate, reset that filament's field decisions
  // to the new candidate's default OPT values and record the selection.
  const handleCandidateChange = useCallback(
    (smId: number, idx: number, match: OpenTagFilamentMatch) => {
      setSelectedCandidates(prev => ({ ...prev, [smId]: idx }))
      const candidate = match.candidates?.[idx]
      if (!candidate) return
      const newDecisions: Record<string, OpenTagFieldDecision> = {}
      for (const row of candidate.fields) {
        newDecisions[row.field] = { field: row.field, value: row.opentag_value, keep_mine: false }
      }
      setFieldDecisions(prev => ({ ...prev, [smId]: newDecisions }))
    },
    [],
  )

  const handleToggleCollapse = useCallback((groupKey: string) => {
    setCollapsedGroups(prev => ({ ...prev, [groupKey]: !(prev[groupKey] ?? true) }))
  }, [])

  const handleIgnoreAll = useCallback((group: MatchGroup, ignoreAll: boolean) => {
    setIgnoredIds(prev => {
      const next = new Set(prev)
      for (const m of group.matches) {
        if (ignoreAll) next.add(m.spoolman_filament_id)
        else next.delete(m.spoolman_filament_id)
      }
      return next
    })
  }, [])

  const runApply = async () => {
    if (!response) return
    setApplying(true)
    setError(null)
    try {
      const decisions: OpenTagFilamentDecision[] = response.matches.map(m => {
        if (ignoredIds.has(m.spoolman_filament_id)) {
          return { spoolman_filament_id: m.spoolman_filament_id, ignored: true, fields: [] }
        }
        // Use selected candidate for identity (slug/uuid) and active fields
        const candidateIdx = selectedCandidates[m.spoolman_filament_id] ?? 0
        const activeCandidate = m.candidates?.[candidateIdx] ?? null
        const activeFields = activeCandidate ? activeCandidate.fields : m.fields
        const dMap = fieldDecisions[m.spoolman_filament_id] ?? {}
        const fields: OpenTagFieldDecision[] = activeFields.map(row => {
          const d = dMap[row.field] ?? { field: row.field, value: row.opentag_value, keep_mine: false }
          return d
        })
        const slug = activeCandidate?.opt_slug ?? m.opt_slug ?? undefined
        const uuid = activeCandidate?.opt_uuid ?? m.opt_uuid ?? undefined
        return {
          spoolman_filament_id: m.spoolman_filament_id,
          ignored: false,
          fields,
          openprinttag_slug: slug,
          openprinttag_uuid: uuid,
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

  const handleApply = () => {
    setShowBackupDialog(true)
  }

  const matches = response?.matches ?? []

  // Apply filter toggles before the withMatch/noMatch split so groups, no-match
  // details, and count summaries all reflect the active filters.
  const filteredMatches = useMemo(() => {
    let list = matches
    if (hideMatched) {
      list = list.filter(m => m.opt_uuid == null && m.confidence < 0.30)
    }
    if (hideAlreadyTagged) {
      list = list.filter(m => {
        const candidateIdx = selectedCandidates[m.spoolman_filament_id] ?? 0
        const activeCandidate = m.candidates?.[candidateIdx] ?? null
        return getExistingUuid(m, activeCandidate) === ''
      })
    }
    return list
  }, [matches, hideMatched, hideAlreadyTagged, selectedCandidates])

  const withMatch = filteredMatches.filter(m => m.confidence >= 0.30)
  const noMatch = filteredMatches.filter(m => m.confidence < 0.30)
  const filterActive = hideMatched || hideAlreadyTagged
  const hiddenCount = matches.length - filteredMatches.length

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
    <>
    <BackupSafetyDialog
      open={showBackupDialog}
      actionLabel="Apply OpenTag writes"
      onCancel={() => setShowBackupDialog(false)}
      onProceed={() => { setShowBackupDialog(false); void runApply() }}
    />
    <div className="p-6 max-w-5xl mx-auto">
      <h1 className="text-2xl font-bold mb-1 text-gray-900 dark:text-gray-100">OpenTag Cleanup</h1>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
        Match your Spoolman filaments against the OpenPrintTag database, review field
        differences, and apply canonical data — including pushing OpenTag identity into
        Filament DB.
      </p>

      {/* Dataset status banner — populated instantly from cache, no FDB fetch */}
      <div className="flex items-center gap-4 mb-6 p-3 bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg">
        {cacheStatus?.exists ? (
          <>
            <span className="text-sm text-gray-600 dark:text-gray-300">
              OpenTag dataset: <strong>{cacheStatus.count}</strong> materials
            </span>
            <span className="text-sm text-gray-500 dark:text-gray-400">
              fetched {formatAge(cacheStatus.fetched_at)}
            </span>
            {cacheStatus.stale && (
              <span className="px-2 py-0.5 rounded bg-yellow-100 dark:bg-yellow-900/30 text-yellow-800 dark:text-yellow-300 text-xs">stale</span>
            )}
          </>
        ) : (
          <span className="text-sm text-gray-500 dark:text-gray-400">
            {cacheStatus === null ? 'Checking dataset cache…' : 'No dataset cached yet.'}
          </span>
        )}
        <div className="ml-auto flex gap-2">
          <button
            type="button"
            className="px-3 py-1 text-sm border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 rounded hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50"
            onClick={() => runLoad(true)}
            disabled={working}
            title="Re-scan Spoolman and recompute matches against the current dataset (no download)"
          >
            {working ? 'Working…' : 'Reprocess records'}
          </button>
          <button
            type="button"
            className="px-3 py-1 text-sm border border-indigo-300 dark:border-indigo-700 text-indigo-600 dark:text-indigo-400 rounded hover:bg-indigo-50 dark:hover:bg-indigo-900/20 disabled:opacity-50"
            onClick={handleRefresh}
            disabled={working}
            title="Re-download the OpenTag dataset from Filament DB, then reprocess"
          >
            {working ? 'Working…' : 'Refresh dataset'}
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 px-4 py-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded text-sm text-red-700 dark:text-red-400">
          <strong>Error:</strong> {error}
        </div>
      )}

      {working && statusMsg && (
        <div className="mb-4 flex items-center gap-3 px-4 py-3 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded text-sm text-blue-700 dark:text-blue-300">
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
            <p className="text-sm text-gray-600 dark:text-gray-300">
              {withMatch.length} matches found, {noMatch.length} unmatched, {ignoredIds.size} ignored
              {filterActive && (
                <span className="ml-2 text-xs text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-900/30 border border-amber-200 dark:border-amber-800 rounded px-1.5 py-0.5">
                  {hiddenCount} hidden by filter
                </span>
              )}
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
          <div className="flex flex-wrap items-center gap-4 mb-3 px-3 py-2 bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg">
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-500 dark:text-gray-400 font-medium">Group by:</span>
              {(['none', 'brand', 'material'] as GroupBy[]).map(g => (
                <button
                  key={g}
                  type="button"
                  className={`text-xs px-2 py-0.5 rounded border transition-colors ${
                    groupBy === g
                      ? 'bg-indigo-100 dark:bg-indigo-900/40 border-indigo-400 dark:border-indigo-600 text-indigo-700 dark:text-indigo-300 font-semibold'
                      : 'bg-white dark:bg-gray-700 border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-600'
                  }`}
                  onClick={() => setGroupBy(g)}
                >
                  {g === 'none' ? 'None' : groupLabel(g)}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-500 dark:text-gray-400 font-medium">Sort by:</span>
              {(['confidence', 'brand', 'material', 'name', 'spoolman_id'] as SortBy[]).map(s => (
                <button
                  key={s}
                  type="button"
                  className={`text-xs px-2 py-0.5 rounded border transition-colors ${
                    sortBy === s
                      ? 'bg-indigo-100 dark:bg-indigo-900/40 border-indigo-400 dark:border-indigo-600 text-indigo-700 dark:text-indigo-300 font-semibold'
                      : 'bg-white dark:bg-gray-700 border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-600'
                  }`}
                  onClick={() => setSortBy(s)}
                  title={sortLabel(s)}
                >
                  {s === 'confidence' ? 'Confidence' : s === 'brand' ? 'Brand' : s === 'material' ? 'Material' : s === 'spoolman_id' ? 'SM ID' : 'Name'}
                </button>
              ))}
            </div>
            {groupBy !== 'none' && (
              <div className="flex items-center gap-2 ml-auto">
                <button
                  type="button"
                  className="text-xs px-2 py-0.5 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-600"
                  onClick={() => {
                    const next: Record<string, boolean> = {}
                    for (const g of displayGroups) next[g.key] = false
                    setCollapsedGroups(next)
                  }}
                >
                  Expand all
                </button>
                <button
                  type="button"
                  className="text-xs px-2 py-0.5 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-600"
                  onClick={() => {
                    const next: Record<string, boolean> = {}
                    for (const g of displayGroups) next[g.key] = true
                    setCollapsedGroups(next)
                  }}
                >
                  Collapse all
                </button>
              </div>
            )}
            {/* Filter toggles */}
            <div className={`flex items-center gap-3 ${groupBy === 'none' ? 'ml-auto' : ''}`}>
              <label className="flex items-center gap-1.5 text-xs text-gray-600 dark:text-gray-300 cursor-pointer select-none">
                <input
                  type="checkbox"
                  className="w-3.5 h-3.5 rounded border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-indigo-600 focus:ring-indigo-400"
                  checked={hideMatched}
                  onChange={e => setHideMatched(e.target.checked)}
                />
                Hide matched
              </label>
              <label className="flex items-center gap-1.5 text-xs text-gray-600 dark:text-gray-300 cursor-pointer select-none">
                <input
                  type="checkbox"
                  className="w-3.5 h-3.5 rounded border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-indigo-600 focus:ring-indigo-400"
                  checked={hideAlreadyTagged}
                  onChange={e => setHideAlreadyTagged(e.target.checked)}
                />
                Hide already-tagged
                <HelpTip text="Hides filaments that already carry an OpenPrintTag UUID." />
              </label>
            </div>
          </div>

          {/* Bulk-action bar */}
          <div className="flex items-center gap-3 mb-4 px-3 py-2 bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg">
            <span className="text-sm text-gray-600 dark:text-gray-300">
              {withMatch.length - withMatch.filter(m => ignoredIds.has(m.spoolman_filament_id)).length} of {withMatch.length} selected
            </span>
            <div className="ml-auto flex items-center gap-2">
              <button
                type="button"
                className="text-xs px-3 py-1 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-600 disabled:opacity-40 disabled:cursor-not-allowed"
                onClick={() => setIgnoredIds(new Set())}
                disabled={withMatch.length === 0}
              >
                Select all
              </button>
              <button
                type="button"
                className="text-xs px-3 py-1 rounded border border-orange-300 dark:border-orange-700 bg-white dark:bg-gray-700 text-orange-600 dark:text-orange-400 hover:bg-orange-50 dark:hover:bg-orange-900/20 disabled:opacity-40 disabled:cursor-not-allowed"
                onClick={() => setIgnoredIds(new Set(withMatch.map(m => m.spoolman_filament_id)))}
                disabled={withMatch.length === 0}
              >
                Ignore all
              </button>
            </div>
          </div>

          {withMatch.length === 0 && noMatch.length === 0 && (
            <p className="text-gray-500 dark:text-gray-400 italic text-sm">No Spoolman filaments found.</p>
          )}

          {displayGroups.map(group => (
            <GroupSection
              key={group.key || '__flat__'}
              group={group}
              fieldDecisions={fieldDecisions}
              ignoredIds={ignoredIds}
              selectedCandidates={selectedCandidates}
              onFieldChange={handleFieldChange}
              onIgnore={handleIgnore}
              onCandidateChange={handleCandidateChange}
              showHeader={groupBy !== 'none'}
              collapsed={groupBy === 'none' ? false : (collapsedGroups[group.key] ?? true)}
              onToggleCollapse={() => handleToggleCollapse(group.key)}
              onIgnoreAll={(ignoreAll) => handleIgnoreAll(group, ignoreAll)}
            />
          ))}

          {noMatch.length > 0 && (
            <details className="mt-4">
              <summary className="text-sm text-gray-500 dark:text-gray-400 cursor-pointer select-none">
                {noMatch.length} unmatched filaments (confidence &lt; 30%)
              </summary>
              <div className="mt-2 space-y-2 pl-4">
                {noMatch.map(m => (
                  <div key={m.spoolman_filament_id} className="flex flex-wrap items-center gap-2 py-1 border-b border-gray-100 dark:border-gray-700 last:border-0">
                    <ColorSwatch hex={m.spoolman_color_hex} />
                    <span className="text-sm font-medium text-gray-700 dark:text-gray-200">{m.spoolman_name}</span>
                    {!m.spoolman_vendor ? (
                      <span className="px-1.5 py-0.5 rounded bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300 text-xs font-medium border border-red-200 dark:border-red-800">
                        No manufacturer
                      </span>
                    ) : (
                      <span className="text-xs text-gray-600 dark:text-gray-400">{m.spoolman_vendor}</span>
                    )}
                    {m.spoolman_material && (
                      <span className="px-1.5 py-0.5 rounded bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 text-xs">
                        {m.spoolman_material}
                      </span>
                    )}
                    <DeepLinks spoolmanFilamentId={m.spoolman_filament_id} />
                    {confidenceBadge(m.confidence)}
                    {m.no_match_reason && (
                      <span className="text-xs text-gray-600 dark:text-gray-400 italic">{m.no_match_reason}</span>
                    )}
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
          selectedCandidates={selectedCandidates}
          onApply={handleApply}
          onBack={() => setStep('review')}
          applying={applying}
        />
      )}

      {step === 'done' && applyResult && (
        <div className="px-6 py-8 text-center">
          <div className="text-4xl mb-4">{applyResult.errors === 0 ? '✓' : '⚠'}</div>
          <h2 className="text-xl font-semibold mb-2 text-gray-900 dark:text-gray-100">
            {applyResult.errors === 0 ? 'Done!' : 'Completed with errors'}
          </h2>
          <p className="text-gray-600 dark:text-gray-400 mb-6">
            Applied {applyResult.applied} filament updates.
            {applyResult.errors > 0 && ` ${applyResult.errors} errors — check the sync log.`}
          </p>
          <button
            type="button"
            className="px-4 py-2 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 rounded text-sm hover:bg-gray-50 dark:hover:bg-gray-700"
            onClick={() => { setStep('review'); runLoad(true) }}
          >
            Start over
          </button>
        </div>
      )}
    </div>
    </>
  )
}
