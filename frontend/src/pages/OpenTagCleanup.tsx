/**
 * OpenTag Cleanup — standalone tool to match Spoolman filaments against the
 * OpenPrintTag dataset, review per-field, confirm, and apply writes to Spoolman
 * (including pushing openprinttag_slug/uuid into FDB's settings{} bag).
 *
 * Flow: Dataset status → Fetch matches → Review per filament → Confirm → Apply
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  getOpenTagMatches,
  getOpenTagMissingValues,
  getOpenTagSearch,
  getOpenTagStatus,
  postOpenTagApply,
  postOpenTagIgnore,
  postOpenTagRefresh,
} from '../api/client'
import { BackupSafetyDialog } from '../components/BackupSafetyDialog'
import { DeepLinks } from '../components/DeepLinks'
import { HelpTip } from '../components/HelpTip'
import { WizardActionBar } from '../components/WizardActionBar'
import type {
  AuditedField,
  AuditedFieldGroup,
  OpenTagApplyRequest,
  OpenTagCacheStatus,
  OpenTagCandidate,
  OpenTagCompletenessItem,
  OpenTagCompletenessResponse,
  OpenTagDatasetMeta,
  OpenTagFieldDecision,
  OpenTagFieldRow,
  OpenTagFilamentDecision,
  OpenTagFilamentMatch,
  OpenTagMatchesResponse,
} from '../api/types'
import { formatMatchAge, parseUtc } from '../utils/datetime'

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

/** Sentinel selected-candidate index meaning "— unmatch —" (clear the OpenTag identity). */
const UNMATCH_IDX = -1

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
        title="Tagged in OpenPrintTag — Spoolman data differs from OpenPrintTag"
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
  onSearchSelect: (candidate: OpenTagCandidate) => void
}

function FilamentCard({
  match,
  decisions,
  onFieldChange,
  onIgnore,
  ignored,
  selectedCandidateIdx,
  onCandidateChange,
  onSearchSelect,
}: FilamentCardProps) {
  // Default collapsed: expanding a group shows just the filament rows; the user expands a
  // row to see its field details (avoids opening every row's settings at once).
  const [expanded, setExpanded] = useState(false)

  // Manual search state — lets the user find a better OpenTag match by keyword
  const [showSearch, setShowSearch] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<OpenTagCandidate[]>([])
  const [isSearching, setIsSearching] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const runSearch = useCallback(async (q: string) => {
    if (!q.trim()) { setSearchResults([]); return }
    setIsSearching(true)
    setSearchError(null)
    try {
      const res = await getOpenTagSearch(
        match.spoolman_vendor ?? '',
        match.spoolman_material ?? '',
        q,
        12,
      )
      setSearchResults(res.results)
    } catch (e: unknown) {
      setSearchError(e instanceof Error ? e.message : 'Search failed')
    } finally {
      setIsSearching(false)
    }
  }, [match.spoolman_vendor, match.spoolman_material])

  const handleSearchInput = useCallback((value: string) => {
    setSearchQuery(value)
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current)
    searchTimerRef.current = setTimeout(() => { void runSearch(value) }, 350)
  }, [runSearch])

  // Unmatch sentinel: selectedCandidateIdx === UNMATCH_IDX means "— unmatch —" is staged.
  const isUnmatchStaged = selectedCandidateIdx === UNMATCH_IDX

  // Active candidate: use structured candidates[selectedCandidateIdx] when available,
  // otherwise fall back to the top-level match fields (backward-compat / no-match rows).
  const activeCandidateIdx = isUnmatchStaged ? 0 : Math.min(
    selectedCandidateIdx,
    Math.max(0, (match.candidates?.length ?? 1) - 1),
  )
  const activeCandidate: OpenTagCandidate | null =
    !isUnmatchStaged && match.candidates && match.candidates.length > 0
      ? match.candidates[activeCandidateIdx]
      : null

  const displayFields = activeCandidate ? activeCandidate.fields : match.fields
  const displayConfidence = activeCandidate ? activeCandidate.confidence : match.confidence
  const displayMulticolorMismatch = activeCandidate
    ? activeCandidate.multicolor_mismatch
    : (match.multicolor_mismatch ?? false)

  // Show the candidate dropdown whenever there's at least one match — a single-candidate
  // brand (only one OpenTag entry, e.g. TTYT3D) still gets the picker for consistency.
  const hasCandidates = !!match.candidates && match.candidates.length >= 1
  // The matcher returns best + up to 10 alternates (max 11). Below that the dropdown holds
  // every available match for the brand, so reassure the user nothing is truncated.
  const allCandidatesListed = !!match.candidates && match.candidates.length <= 10

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
              title="Spoolman has multicolor data but the matched OpenPrintTag entry is single-color"
            >
              multicolor mismatch
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {/* Candidate dropdown — shown when there are multiple candidates */}
          {hasCandidates && (
            <select
              className={`text-xs border rounded px-1 py-0.5 bg-white dark:bg-gray-700 max-w-xs focus:outline-none focus:ring-1 focus:ring-indigo-400 ${
                isUnmatchStaged
                  ? 'border-red-300 dark:border-red-700 text-red-600 dark:text-red-400'
                  : 'border-indigo-200 dark:border-indigo-700 text-indigo-700 dark:text-indigo-300'
              }`}
              value={isUnmatchStaged ? UNMATCH_IDX : activeCandidateIdx}
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
              {/* Unmatch is only meaningful for rows that already carry an OPT identity. */}
              {existingUuid && (
                <option value={UNMATCH_IDX}>— unmatch (clear OpenPrintTag identity) —</option>
              )}
            </select>
          )}
          {expanded && hasCandidates && allCandidatesListed && (
            <span className="text-[10px] text-gray-400 dark:text-gray-500 whitespace-nowrap">
              all filaments listed
            </span>
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
              text="Match score vs the OpenPrintTag entry: material, brand, color name, color hex, and finish all contribute. Below 30% = unmatched."
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
              onClick={() => {
                // When un-ignoring, just change status — keep the card collapsed so the
                // list doesn't balloon. The user can hit the ▼ arrow to expand details.
                if (ignored) setExpanded(false)
                onIgnore(!ignored)
              }}
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

      {/* Manual re-match — surfaced above the field list so it's easy to find when the
          auto-match is wrong or there's only one candidate to pick from. */}
      {expanded && !ignored && (
        <div className="px-4 py-2 border-b border-gray-100 dark:border-gray-700">
          {!showSearch ? (
            <button
              type="button"
              className="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded border border-indigo-300 dark:border-indigo-700 text-indigo-600 dark:text-indigo-300 hover:bg-indigo-50 dark:hover:bg-indigo-900/20"
              onClick={() => setShowSearch(true)}
            >
              🔍 Wrong match? Search OpenPrintTag manually…
            </button>
          ) : (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium text-gray-600 dark:text-gray-300">Search OpenPrintTag</span>
                <button
                  type="button"
                  className="text-xs text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300"
                  onClick={() => { setShowSearch(false); setSearchQuery(''); setSearchResults([]) }}
                >
                  ✕ close
                </button>
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="search"
                  className="border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 rounded px-2 py-1 text-xs w-56 focus:outline-none focus:ring-1 focus:ring-indigo-400"
                  placeholder="e.g. Silk Gold, Matte Blue…"
                  value={searchQuery}
                  onChange={e => handleSearchInput(e.target.value)}
                  autoFocus
                />
                {isSearching && (
                  <svg className="animate-spin h-3 w-3 text-indigo-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                  </svg>
                )}
              </div>
              {searchError && (
                <p className="text-xs text-red-600 dark:text-red-400">{searchError}</p>
              )}
              {searchResults.length > 0 && (
                <ul className="divide-y divide-gray-100 dark:divide-gray-700 border border-gray-200 dark:border-gray-600 rounded bg-white dark:bg-gray-800 max-h-48 overflow-y-auto text-xs">
                  {searchResults.map((c, i) => (
                    <li key={c.opt_uuid ?? c.opt_slug ?? i}>
                      <button
                        type="button"
                        className="w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-indigo-50 dark:hover:bg-indigo-900/30 transition-colors"
                        onClick={() => {
                          onSearchSelect(c)
                          setShowSearch(false)
                          setSearchQuery('')
                          setSearchResults([])
                        }}
                      >
                        {c.opt_color_hex && <ColorSwatch hex={c.opt_color_hex} />}
                        <span className="font-medium text-gray-800 dark:text-gray-100">{c.opt_brand}</span>
                        <span className="text-gray-600 dark:text-gray-300 flex-1 truncate">· {c.opt_name}</span>
                        <span className="shrink-0">{confidenceBadge(c.confidence)}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {!isSearching && searchQuery.trim() && searchResults.length === 0 && (
                <p className="text-xs text-gray-500 dark:text-gray-400 italic">No results found.</p>
              )}
            </div>
          )}
        </div>
      )}

      {expanded && !ignored && isUnmatchStaged && (
        <p className="px-4 py-3 text-sm text-red-600 dark:text-red-400">
          Will <strong>unmatch</strong> on Apply — clears this filament's OpenPrintTag
          identity (slug + UUID) in Spoolman and removes it from Filament DB. Pick a
          candidate above to re-match instead.
        </p>
      )}

      {expanded && !ignored && !isUnmatchStaged && displayFields.length > 0 && (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm divide-y divide-gray-200 dark:divide-gray-700">
            <thead>
              <tr className="bg-gray-50 dark:bg-gray-900/40 text-xs text-gray-500 dark:text-gray-400 uppercase">
                <th className="px-3 py-1 text-left">Field</th>
                <th className="px-3 py-1 text-left">Spoolman</th>
                <th className="px-3 py-1 text-left">OpenPrintTag</th>
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

      {expanded && !ignored && !isUnmatchStaged && displayFields.length === 0 && (
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
      // Unmatch staged → a single "clear identity" pending row, no field writes.
      if (selectedCandidates[m.spoolman_filament_id] === UNMATCH_IDX) {
        result.push({
          smId: m.spoolman_filament_id,
          name: m.spoolman_name,
          field: 'unmatch',
          oldValue: 'tagged',
          newValue: 'clear OpenPrintTag identity',
        })
        continue
      }
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

      {/* Top action bar */}
      <div className="mb-4">
        <WizardActionBar
          onBack={onBack}
          backLabel="Back"
          onNext={writes.length > 0 ? onApply : undefined}
          nextLabel={`Apply ${writes.length} writes`}
          busy={applying}
          busyLabel="Applying…"
          nextDisabled={writes.length === 0}
        />
      </div>

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

      {/* Bottom action bar */}
      <WizardActionBar
        onBack={onBack}
        backLabel="Back"
        onNext={writes.length > 0 ? onApply : undefined}
        nextLabel={`Apply ${writes.length} writes`}
        busy={applying}
        busyLabel="Applying…"
        nextDisabled={writes.length === 0}
      />
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
  onSearchSelect: (smId: number, candidate: OpenTagCandidate) => void
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
  onSearchSelect,
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
          onSearchSelect={(candidate) => onSearchSelect(m.spoolman_filament_id, candidate)}
        />
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Updates Review — focused view of already-tagged filaments with drifted data
// ---------------------------------------------------------------------------

interface UpdatesReviewProps {
  matches: OpenTagFilamentMatch[]
  onBack: () => void
  onApplied: () => void
}

/** One row in the updates review table — shows changed fields for a filament. */
function UpdatesReviewRow({
  match,
  checked,
  onCheck,
  onIgnore,
  ignoringId,
}: {
  match: OpenTagFilamentMatch
  checked: boolean
  onCheck: (checked: boolean) => void
  onIgnore: (ignored: boolean) => void
  ignoringId: boolean
}) {
  const [expanded, setExpanded] = useState(false)
  const activeCandidate = match.candidates?.[0] ?? null
  const displayFields = activeCandidate ? activeCandidate.fields : match.fields
  // Only show fields that actually differ (non-identity)
  const changedFields = displayFields.filter(
    r => !IDENTITY_FIELDS.has(r.field) &&
      normalizeFieldValue(r.spoolman_value) !== normalizeFieldValue(r.opentag_value),
  )

  return (
    <div className={`border border-gray-200 dark:border-gray-700 rounded-lg mb-2 overflow-hidden ${match.ignored_updates ? 'opacity-50' : ''}`}>
      <div className="flex items-center gap-3 px-3 py-2 bg-gray-50 dark:bg-gray-900/40">
        <input
          type="checkbox"
          className="w-4 h-4 rounded border-gray-300 dark:border-gray-600 text-indigo-600 focus:ring-indigo-400"
          checked={checked && !match.ignored_updates}
          disabled={match.ignored_updates}
          onChange={e => onCheck(e.target.checked)}
        />
        <ColorSwatch hex={match.spoolman_color_hex} />
        <span className="font-medium text-sm text-gray-900 dark:text-gray-100 flex-1 min-w-0 truncate">
          {match.spoolman_name}
        </span>
        {match.spoolman_vendor && (
          <span className="text-xs text-gray-500 dark:text-gray-400 shrink-0">{match.spoolman_vendor}</span>
        )}
        {match.spoolman_material && (
          <span className="px-1.5 py-0.5 rounded bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 text-xs shrink-0">
            {match.spoolman_material}
          </span>
        )}
        <DeepLinks spoolmanFilamentId={match.spoolman_filament_id} />
        <span className="text-xs text-amber-700 dark:text-amber-400 shrink-0 font-medium">
          {changedFields.length} field{changedFields.length !== 1 ? 's' : ''} changed
        </span>
        <button
          type="button"
          className={`text-xs px-2 py-0.5 rounded border shrink-0 ${
            match.ignored_updates
              ? 'bg-gray-200 dark:bg-gray-700 border-gray-400 dark:border-gray-600 text-gray-700 dark:text-gray-200'
              : 'bg-white dark:bg-gray-800 border-orange-300 dark:border-orange-700 text-orange-600 dark:text-orange-400 hover:bg-orange-50 dark:hover:bg-orange-900/20'
          } disabled:opacity-50 disabled:cursor-not-allowed`}
          onClick={() => onIgnore(!match.ignored_updates)}
          disabled={ignoringId}
          title={match.ignored_updates ? 'Un-ignore future updates for this filament' : 'Ignore future updates for this filament'}
        >
          {ignoringId ? '…' : match.ignored_updates ? 'Un-ignore' : 'Ignore future updates'}
        </button>
        <button
          type="button"
          className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline shrink-0"
          onClick={() => setExpanded(e => !e)}
        >
          {expanded ? 'Hide' : 'Show'} details
        </button>
      </div>
      {expanded && changedFields.length > 0 && (
        <div className="overflow-x-auto">
          <table className="min-w-full text-xs divide-y divide-gray-100 dark:divide-gray-700">
            <thead>
              <tr className="bg-gray-50 dark:bg-gray-900/40 text-gray-500 dark:text-gray-400 uppercase">
                <th className="px-3 py-1 text-left">Field</th>
                <th className="px-3 py-1 text-left">Current (Spoolman)</th>
                <th className="px-3 py-1 text-left">Updated (OpenPrintTag)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
              {changedFields.map(row => {
                const isColor = row.field === 'color_hex' || row.field === 'multi_color_hexes'
                return (
                  <tr key={row.field} className="hover:bg-gray-50 dark:hover:bg-gray-700/40">
                    <td className="px-3 py-1.5 font-mono text-gray-500 dark:text-gray-400">{row.field}</td>
                    <td className="px-3 py-1.5 text-gray-600 dark:text-gray-300">
                      {isColor && <ColorSwatch hex={renderValue(row.spoolman_value)} />}
                      {renderValue(row.spoolman_value)}
                    </td>
                    <td className="px-3 py-1.5 text-indigo-700 dark:text-indigo-400 font-medium">
                      {isColor && <ColorSwatch hex={renderValue(row.opentag_value)} />}
                      {renderValue(row.opentag_value)}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function UpdatesReviewSection({ matches, onBack, onApplied }: UpdatesReviewProps) {
  // The matches prop is already filtered to has_update===true (or ignored_updates===true shown separately)
  // We show non-ignored ones by default; ignored ones appear in a collapsible section.
  const activeMatches = matches.filter(m => !m.ignored_updates)
  const ignoredMatches = matches.filter(m => m.ignored_updates)

  const [selectedIds, setSelectedIds] = useState<Set<number>>(
    () => new Set(activeMatches.map(m => m.spoolman_filament_id)),
  )
  const [applying, setApplying] = useState(false)
  const [applyError, setApplyError] = useState<string | null>(null)
  const [applyResult, setApplyResult] = useState<{ applied: number; errors: number } | null>(null)
  // Track which filament IDs are currently being ignored (pending API call)
  const [ignoringIds, setIgnoringIds] = useState<Set<number>>(new Set())
  // Track local ignore state so UI updates immediately without re-fetching
  const [localIgnoredIds, setLocalIgnoredIds] = useState<Set<number>>(
    () => new Set(ignoredMatches.map(m => m.spoolman_filament_id)),
  )
  const [showIgnored, setShowIgnored] = useState(false)

  // Search + sort
  const [search, setSearch] = useState('')
  const [sortBy, setSortBy] = useState<SortBy>('brand')
  const [groupBy, setGroupBy] = useState<GroupBy>('brand')
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({})

  // Effective list: merge localIgnoredIds with the match data
  const effectiveMatches = useMemo(
    () => matches.map(m => ({
      ...m,
      ignored_updates: localIgnoredIds.has(m.spoolman_filament_id),
    })),
    [matches, localIgnoredIds],
  )
  const displayMatches = useMemo(() => {
    let list = effectiveMatches.filter(m => !m.ignored_updates)
    if (search.trim()) {
      const q = search.trim().toLowerCase()
      list = list.filter(m =>
        (m.spoolman_name ?? '').toLowerCase().includes(q) ||
        (m.spoolman_vendor ?? '').toLowerCase().includes(q),
      )
    }
    return sortMatches(list, sortBy)
  }, [effectiveMatches, search, sortBy])

  const displayIgnored = useMemo(
    () => effectiveMatches.filter(m => m.ignored_updates),
    [effectiveMatches],
  )

  // Groups
  const displayGroups = useMemo<MatchGroup[]>(() => {
    if (groupBy === 'none') return [{ key: '', matches: displayMatches }]
    const order: string[] = []
    const map = new Map<string, OpenTagFilamentMatch[]>()
    for (const m of displayMatches) {
      const k = groupKey(m, groupBy)
      if (!map.has(k)) { order.push(k); map.set(k, []) }
      map.get(k)!.push(m)
    }
    order.sort((a, b) => {
      const aU = a.startsWith('Unknown'); const bU = b.startsWith('Unknown')
      if (aU && !bU) return 1; if (!aU && bU) return -1
      return a.toLowerCase() < b.toLowerCase() ? -1 : 1
    })
    return order.map(k => ({ key: k, matches: map.get(k)! }))
  }, [displayMatches, groupBy])

  const toggleGroup = (key: string) =>
    setCollapsedGroups(prev => ({ ...prev, [key]: !(prev[key] ?? false) }))

  const allSelectedInView = displayMatches.length > 0 &&
    displayMatches.every(m => selectedIds.has(m.spoolman_filament_id))

  const toggleSelectAll = () => {
    if (allSelectedInView) {
      setSelectedIds(prev => {
        const next = new Set(prev)
        for (const m of displayMatches) next.delete(m.spoolman_filament_id)
        return next
      })
    } else {
      setSelectedIds(prev => {
        const next = new Set(prev)
        for (const m of displayMatches) next.add(m.spoolman_filament_id)
        return next
      })
    }
  }

  const handleIgnore = async (smId: number, ignore: boolean) => {
    setIgnoringIds(prev => new Set(prev).add(smId))
    try {
      await postOpenTagIgnore(smId, ignore)
      setLocalIgnoredIds(prev => {
        const next = new Set(prev)
        if (ignore) { next.add(smId); setSelectedIds(s => { const ns = new Set(s); ns.delete(smId); return ns }) }
        else next.delete(smId)
        return next
      })
    } catch {
      // Silently fail — user sees no change (the flag didn't stick)
    } finally {
      setIgnoringIds(prev => { const next = new Set(prev); next.delete(smId); return next })
    }
  }

  const handleApply = async () => {
    setApplying(true)
    setApplyError(null)
    try {
      const selectedMatches = displayMatches.filter(m => selectedIds.has(m.spoolman_filament_id))
      const decisions = selectedMatches.map(m => {
        const candidateIdx = 0 // always use best candidate in updates review
        const activeCandidate = m.candidates?.[candidateIdx] ?? null
        const activeFields = activeCandidate ? activeCandidate.fields : m.fields
        const fields = activeFields.map(row => ({
          field: row.field,
          value: row.opentag_value,
          keep_mine: false,
        }))
        const slug = activeCandidate?.opt_slug ?? m.opt_slug ?? undefined
        const uuid = activeCandidate?.opt_uuid ?? m.opt_uuid ?? undefined
        return {
          spoolman_filament_id: m.spoolman_filament_id,
          ignored: false,
          fields,
          openprinttag_slug: slug ?? null,
          openprinttag_uuid: uuid ?? null,
        }
      })
      const req: OpenTagApplyRequest = { decisions }
      const result = await postOpenTagApply(req)
      setApplyResult({ applied: result.applied, errors: result.errors })
      onApplied()
    } catch (e: unknown) {
      setApplyError(e instanceof Error ? e.message : String(e))
    } finally {
      setApplying(false)
    }
  }

  if (applyResult) {
    return (
      <div className="px-6 py-8 text-center">
        <div className="text-4xl mb-4">{applyResult.errors === 0 ? '✓' : '⚠'}</div>
        <h2 className="text-xl font-semibold mb-2 text-gray-900 dark:text-gray-100">
          {applyResult.errors === 0 ? 'Updates applied!' : 'Completed with errors'}
        </h2>
        <p className="text-gray-600 dark:text-gray-400 mb-6">
          Applied {applyResult.applied} filament updates.
          {applyResult.errors > 0 && ` ${applyResult.errors} errors — check the sync log.`}
        </p>
        <button
          type="button"
          className="px-4 py-2 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 rounded text-sm hover:bg-gray-50 dark:hover:bg-gray-700"
          onClick={onBack}
        >
          Back to main view
        </button>
      </div>
    )
  }

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <button
          type="button"
          className="text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
          onClick={onBack}
        >
          ← Back
        </button>
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
          Review OpenPrintTag updates
        </h2>
        <span className="text-sm text-gray-500 dark:text-gray-400">
          {displayMatches.length} filament{displayMatches.length !== 1 ? 's' : ''} with updated values
        </span>
      </div>
      <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
        These filaments are already tagged with an OpenPrintTag UUID but their Spoolman
        data differs from the latest OpenPrintTag dataset. Select the ones you want to update
        and click <strong>Apply selected</strong>.
      </p>

      {applyError && (
        <div className="mb-4 px-4 py-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded text-sm text-red-700 dark:text-red-400">
          <strong>Error:</strong> {applyError}
        </div>
      )}

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-3 mb-3 px-3 py-2 bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg">
        <input
          type="search"
          className="text-sm border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 rounded px-2 py-1 w-48 focus:outline-none focus:ring-1 focus:ring-indigo-400"
          placeholder="Search filaments…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500 dark:text-gray-400 font-medium">Group:</span>
          {(['none', 'brand', 'material'] as GroupBy[]).map(g => (
            <button key={g} type="button"
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
          <span className="text-xs text-gray-500 dark:text-gray-400 font-medium">Sort:</span>
          {(['brand', 'name'] as SortBy[]).map(s => (
            <button key={s} type="button"
              className={`text-xs px-2 py-0.5 rounded border transition-colors ${
                sortBy === s
                  ? 'bg-indigo-100 dark:bg-indigo-900/40 border-indigo-400 dark:border-indigo-600 text-indigo-700 dark:text-indigo-300 font-semibold'
                  : 'bg-white dark:bg-gray-700 border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-600'
              }`}
              onClick={() => setSortBy(s)}
            >
              {s === 'brand' ? 'Brand' : 'Name'}
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-3">
          <button type="button"
            className="text-xs px-3 py-1 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-600 disabled:opacity-40"
            onClick={toggleSelectAll}
            disabled={displayMatches.length === 0}
          >
            {allSelectedInView ? 'Deselect all' : 'Select all'}
          </button>
          <span className="text-sm text-gray-600 dark:text-gray-300">
            {selectedIds.size} of {displayMatches.length} selected
          </span>
          <button
            type="button"
            className="px-4 py-2 bg-indigo-600 text-white text-sm rounded hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
            onClick={handleApply}
            disabled={applying || selectedIds.size === 0}
          >
            {applying ? 'Applying…' : `Apply ${selectedIds.size} selected`}
          </button>
        </div>
      </div>

      {displayMatches.length === 0 && displayIgnored.length === 0 && (
        <p className="text-gray-500 dark:text-gray-400 italic text-sm py-4">
          No filaments with pending updates.
          {search && ' Try clearing the search filter.'}
        </p>
      )}

      {/* Groups */}
      {displayGroups.map(group => (
        <div key={group.key || '__flat__'} className="mb-4">
          {groupBy !== 'none' && (
            <div
              className="flex items-center gap-2 px-3 py-1.5 bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 rounded-md mb-2 select-none cursor-pointer"
              onClick={() => toggleGroup(group.key)}
            >
              <span className="text-gray-400 dark:text-gray-500 text-xs w-3">
                {collapsedGroups[group.key] ? '▸' : '▾'}
              </span>
              <span className="text-sm font-semibold text-gray-700 dark:text-gray-200">{group.key || 'Unknown'}</span>
              <span className="text-xs text-gray-500 dark:text-gray-400">({group.matches.length})</span>
            </div>
          )}
          {!collapsedGroups[group.key] && group.matches.map(m => (
            <UpdatesReviewRow
              key={m.spoolman_filament_id}
              match={m}
              checked={selectedIds.has(m.spoolman_filament_id)}
              onCheck={checked => setSelectedIds(prev => {
                const next = new Set(prev)
                if (checked) next.add(m.spoolman_filament_id)
                else next.delete(m.spoolman_filament_id)
                return next
              })}
              onIgnore={ignore => void handleIgnore(m.spoolman_filament_id, ignore)}
              ignoringId={ignoringIds.has(m.spoolman_filament_id)}
            />
          ))}
        </div>
      ))}

      {/* Ignored filaments section */}
      {displayIgnored.length > 0 && (
        <div className="mt-6 border-t border-gray-200 dark:border-gray-700 pt-4">
          <button
            type="button"
            className="text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 mb-2"
            onClick={() => setShowIgnored(v => !v)}
          >
            {showIgnored ? '▾' : '▸'} {displayIgnored.length} filament{displayIgnored.length !== 1 ? 's' : ''} with ignored updates
          </button>
          {showIgnored && displayIgnored.map(m => (
            <UpdatesReviewRow
              key={m.spoolman_filament_id}
              match={m}
              checked={false}
              onCheck={() => {}}
              onIgnore={ignore => void handleIgnore(m.spoolman_filament_id, ignore)}
              ignoringId={ignoringIds.has(m.spoolman_filament_id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Missing values report — OpenPrintTag record completeness for tagged filaments
// ---------------------------------------------------------------------------

type MissingSort = 'most-missing' | 'brand'

/** Human heading for a section scope ("material" | "package:<slug>" | "container:<slug>"). */
function sectionHeading(scope: string): string {
  if (scope === 'material') return 'Material'
  if (scope === 'package:none') return 'Package'
  if (scope.startsWith('package:')) return `Package — ${scope.slice('package:'.length)}`
  if (scope.startsWith('container:')) return `Container — ${scope.slice('container:'.length)}`
  return scope
}

/** One expandable row in the completeness report table. */
function MissingValuesRow({ item }: { item: OpenTagCompletenessItem }) {
  const [open, setOpen] = useState(false)
  const slugLink = item.opt_url ?? null

  return (
    <>
      <tr
        className="border-t border-gray-100 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700/40 cursor-pointer"
        onClick={() => setOpen(o => !o)}
      >
        <td className="px-3 py-2 text-sm text-gray-700 dark:text-gray-300">{item.brand ?? '—'}</td>
        <td className="px-3 py-2 text-sm text-gray-900 dark:text-gray-100">
          <div className="flex items-center gap-2">
            <span>{item.name ?? '—'}</span>
            <DeepLinks spoolmanFilamentId={item.spoolman_filament_id} />
          </div>
        </td>
        <td className="px-3 py-2 text-sm text-indigo-700 dark:text-indigo-400 font-mono">
          {slugLink ? (
            <a
              href={slugLink}
              target="_blank"
              rel="noopener noreferrer"
              className="hover:underline"
              onClick={e => e.stopPropagation()}
            >
              {item.opt_slug ?? '(linked)'}
            </a>
          ) : (
            item.opt_slug ?? '—'
          )}
        </td>
        <td className="px-3 py-2 text-sm">
          {item.stale_match ? (
            <span className="px-1.5 py-0.5 rounded text-xs bg-orange-100 dark:bg-orange-900/30 text-orange-800 dark:text-orange-300">
              stale tag
            </span>
          ) : item.missing_count === 0 ? (
            <span className="px-1.5 py-0.5 rounded text-xs bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-300">
              complete
            </span>
          ) : (
            <span className="px-1.5 py-0.5 rounded text-xs font-mono bg-amber-100 dark:bg-amber-900/30 text-amber-800 dark:text-amber-300">
              {item.missing_count} missing
            </span>
          )}
        </td>
      </tr>
      {open && (
        <tr className="bg-gray-50 dark:bg-gray-800/60">
          <td colSpan={4} className="px-3 py-3">
            {item.stale_match ? (
              <p className="text-sm text-orange-700 dark:text-orange-400">
                This filament's OpenPrintTag UUID (<span className="font-mono">{item.opt_uuid}</span>)
                is not in the current dataset — the tag may be stale. Re-match this filament or refresh
                the dataset.
              </p>
            ) : item.sections.length === 0 ? (
              <p className="text-sm text-gray-500 dark:text-gray-400 italic">
                This OpenPrintTag record has every supported field filled. Nothing to contribute.
              </p>
            ) : (
              <div className="space-y-3">
                {item.sections.map(section => (
                  <div key={section.scope}>
                    <p className="text-xs uppercase tracking-wide font-medium text-gray-500 dark:text-gray-400 mb-1">
                      {sectionHeading(section.scope)}
                    </p>
                    <ul className="flex flex-wrap gap-x-3 gap-y-1">
                      {section.fields.map(label => (
                        <li
                          key={label}
                          className="px-2 py-0.5 rounded text-xs bg-amber-100 dark:bg-amber-900/30 text-amber-800 dark:text-amber-300"
                        >
                          {label}
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  )
}

// localStorage key for persisted excluded-field set.
const _LS_EXCLUDED_KEY = 'fb_opt_missing_excluded_fields'

function _readExcludedKeys(): Set<string> {
  try {
    const raw = localStorage.getItem(_LS_EXCLUDED_KEY)
    if (!raw) return new Set()
    const parsed: unknown = JSON.parse(raw)
    if (Array.isArray(parsed)) return new Set(parsed as string[])
  } catch {
    // corrupt entry → default all-included
  }
  return new Set()
}

function _writeExcludedKeys(keys: Set<string>): void {
  try {
    localStorage.setItem(_LS_EXCLUDED_KEY, JSON.stringify([...keys]))
  } catch {
    // best-effort
  }
}

/** Per-scope label used in the chip group headers. */
function _scopeLabel(scope: string): string {
  if (scope === 'material') return 'Material'
  if (scope === 'package') return 'Package'
  if (scope === 'container') return 'Container'
  return scope
}

/** Apply excluded-field filter to a single item's sections, recomputing missing_count. */
function _applyExcludedToItem(
  item: OpenTagCompletenessItem,
  excludedLabels: Set<string>,
): OpenTagCompletenessItem {
  if (item.stale_match) return item  // stale tags are not field-filtered
  if (excludedLabels.size === 0) return item
  const filteredSections = item.sections.map(section => ({
    ...section,
    fields: section.fields.filter(label => !excludedLabels.has(label)),
  })).filter(section => section.fields.length > 0)
  const missing_count = filteredSections.reduce((sum, s) => sum + s.fields.length, 0)
  return { ...item, sections: filteredSections, missing_count }
}

/** Field toggle chips — one chip per audited field, grouped by scope. */
function FieldToggleChips({
  auditedFields,
  excludedKeys,
  excludedLabels,
  onToggle,
  onReset,
}: {
  auditedFields: AuditedFieldGroup[]
  excludedKeys: Set<string>
  excludedLabels: Set<string>
  onToggle: (field: AuditedField) => void
  onReset: () => void
}) {
  const excludedCount = excludedKeys.size
  return (
    <div className="mb-4 p-3 bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-medium text-gray-600 dark:text-gray-400 uppercase tracking-wide">
          Fields to count
        </span>
        {excludedCount > 0 && (
          <div className="flex items-center gap-2">
            <span className="text-xs text-amber-700 dark:text-amber-400">
              {excludedCount} field{excludedCount !== 1 ? 's' : ''} excluded
            </span>
            <button
              type="button"
              onClick={onReset}
              className="text-xs px-2 py-0.5 border border-gray-300 dark:border-gray-600 rounded text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700"
            >
              Reset
            </button>
          </div>
        )}
      </div>
      <div className="space-y-2">
        {auditedFields.map(group => (
          <div key={group.scope}>
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">{_scopeLabel(group.scope)}</p>
            <div className="flex flex-wrap gap-1.5">
              {group.fields.map(field => {
                const excluded = excludedLabels.has(field.label)
                return (
                  <button
                    key={field.key}
                    type="button"
                    onClick={() => onToggle(field)}
                    title={field.conditional ? `${field.label} (multicolor only)` : field.label}
                    className={`px-2 py-0.5 rounded text-xs border transition-colors ${
                      excluded
                        ? 'border-gray-300 dark:border-gray-600 text-gray-400 dark:text-gray-500 bg-white dark:bg-gray-900 line-through'
                        : 'border-indigo-300 dark:border-indigo-700 text-indigo-700 dark:text-indigo-300 bg-indigo-50 dark:bg-indigo-900/30 hover:bg-indigo-100 dark:hover:bg-indigo-900/50'
                    }`}
                  >
                    {field.label}{field.conditional ? ' *' : ''}
                  </button>
                )
              })}
            </div>
          </div>
        ))}
      </div>
      {auditedFields.some(g => g.fields.some(f => f.conditional)) && (
        <p className="mt-1.5 text-xs text-gray-400 dark:text-gray-500">* counted only for multicolor records</p>
      )}
    </div>
  )
}

/** Standalone completeness report view. Fetches its own data on first activation. */
function MissingValuesReport() {
  const [data, setData] = useState<OpenTagCompletenessResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sortBy, setSortBy] = useState<MissingSort>('most-missing')
  const [showComplete, setShowComplete] = useState(false)
  // Excluded field keys (cache_key) — derived from localStorage on first render.
  const [excludedKeys, setExcludedKeys] = useState<Set<string>>(() => _readExcludedKeys())

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    getOpenTagMissingValues()
      .then(d => { if (!cancelled) setData(d) })
      .catch((e: unknown) => { if (!cancelled) setError(e instanceof Error ? e.message : String(e)) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  // Build a set of excluded LABELS (used by _applyExcludedToItem which matches on labels).
  // Also build a map from key→label for toggling.
  const { excludedLabels, keyToLabel } = useMemo(() => {
    const kToL = new Map<string, string>()
    if (data?.audited_fields) {
      for (const group of data.audited_fields) {
        for (const f of group.fields) kToL.set(f.key, f.label)
      }
    }
    const labels = new Set<string>()
    for (const key of excludedKeys) {
      const label = kToL.get(key)
      if (label) labels.add(label)
    }
    return { excludedLabels: labels, keyToLabel: kToL }
  }, [excludedKeys, data])

  const handleToggleField = (field: AuditedField) => {
    setExcludedKeys(prev => {
      const next = new Set(prev)
      if (next.has(field.key)) next.delete(field.key)
      else next.add(field.key)
      _writeExcludedKeys(next)
      return next
    })
  }

  const handleResetExclusions = () => {
    setExcludedKeys(new Set())
    _writeExcludedKeys(new Set())
  }

  const rows = useMemo(() => {
    if (!data) return []
    // Apply per-field exclusion filter and recompute missing_count per item.
    let items = data.items.map(i => _applyExcludedToItem(i, excludedLabels))
    // Hide-complete toggle: a row is "complete" only when matched (not stale) and 0 missing.
    if (!showComplete) {
      items = items.filter(i => i.stale_match || i.missing_count > 0)
    }
    const sorted = [...items]
    if (sortBy === 'brand') {
      sorted.sort((a, b) =>
        (a.brand ?? '').localeCompare(b.brand ?? '') ||
        (a.name ?? '').localeCompare(b.name ?? ''))
    } else {
      // most-missing desc; stale tags sort to the top (treated as needing attention)
      sorted.sort((a, b) =>
        Number(b.stale_match) - Number(a.stale_match) ||
        b.missing_count - a.missing_count ||
        (a.brand ?? '').localeCompare(b.brand ?? ''))
    }
    return sorted
  }, [data, sortBy, showComplete, excludedLabels])

  if (loading) {
    return <div className="py-12 text-center text-gray-500 dark:text-gray-400">Loading completeness report…</div>
  }
  if (error) {
    return (
      <div className="my-4 px-4 py-3 bg-red-50 dark:bg-red-900/20 border border-red-300 dark:border-red-700 rounded text-sm text-red-800 dark:text-red-300">
        {error}
      </div>
    )
  }
  if (!data) return null

  const tagged = data.items.length
  const needWork = data.items.filter(i => i.missing_count > 0).length

  return (
    <div>
      <div className="mb-4 px-4 py-3 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-700 rounded-lg text-sm text-blue-800 dark:text-blue-300">
        <p className="font-medium mb-1">Which of your filaments most need OpenPrintTag data contributed?</p>
        <p>
          This optional tool audits the <strong>OpenPrintTag records</strong> for each of your tagged
          filaments — not your own spool data. For each tagged filament it lists every
          OpenPrintTag-supported field that the community database leaves empty, so you can decide
          which fields are worth contributing upstream.{' '}
          {tagged} tagged filament{tagged !== 1 ? 's' : ''},{' '}
          {needWork} with gaps{data.stale_count > 0 ? `, ${data.stale_count} stale tag${data.stale_count !== 1 ? 's' : ''}` : ''}.
        </p>
        <p className="mt-1 text-xs text-blue-700 dark:text-blue-400">
          Use the field toggles below to choose which fields count toward the gap tally — exclude
          any that are not relevant to you (e.g. chamber temp for PLA). The report never pre-judges
          applicability; you decide what is worth submitting. Heatbreak temperature is excluded
          globally: it has no upstream data yet.
        </p>
      </div>

      {/* Per-field toggle chips — derived from audited_fields in the API response. */}
      {data.audited_fields && data.audited_fields.length > 0 && (
        <FieldToggleChips
          auditedFields={data.audited_fields}
          excludedKeys={excludedKeys}
          excludedLabels={excludedLabels}
          onToggle={handleToggleField}
          onReset={handleResetExclusions}
        />
      )}

      <div className="flex items-center gap-4 mb-4">
        <label className="text-sm text-gray-600 dark:text-gray-300 flex items-center gap-2">
          Sort by
          <select
            className="border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 rounded px-2 py-1 text-sm"
            value={sortBy}
            onChange={e => setSortBy(e.target.value as MissingSort)}
          >
            <option value="most-missing">Most missing</option>
            <option value="brand">Brand (A→Z)</option>
          </select>
        </label>
        <label className="text-sm text-gray-600 dark:text-gray-300 flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            className="rounded border-gray-300 dark:border-gray-600"
            checked={showComplete}
            onChange={e => setShowComplete(e.target.checked)}
          />
          Show complete records
        </label>
      </div>

      {rows.length === 0 ? (
        <div className="py-12 text-center text-gray-500 dark:text-gray-400">
          {tagged === 0
            ? 'No tagged filaments yet — apply OpenPrintTag identities first (use Matches → Review).'
            : 'Every tagged filament has a complete OpenPrintTag record (for the selected fields).'}
        </div>
      ) : (
        <div className="overflow-x-auto bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg">
          <table className="min-w-full">
            <thead className="bg-gray-50 dark:bg-gray-700/40">
              <tr className="text-left text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
                <th className="px-3 py-2 font-medium">Brand</th>
                <th className="px-3 py-2 font-medium">Filament</th>
                <th className="px-3 py-2 font-medium">OPT match</th>
                <th className="px-3 py-2 font-medium"># missing</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(item => (
                <MissingValuesRow key={item.spoolman_filament_id} item={item} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

type Step = 'review' | 'confirm' | 'done'

/** Top-level toolbar action / active view. */
type ToolbarView = 'idle' | 'match' | 'missing-values'

export default function OpenTagCleanup() {
  // Cache status — loaded instantly on mount, no fetch
  const [cacheStatus, setCacheStatus] = useState<OpenTagCacheStatus | null>(null)

  /** Which toolbar action is active. Starts at 'idle' — nothing loads on mount. */
  const [toolbarView, setToolbarView] = useState<ToolbarView>('idle')

  // View mode: 'all' = main review flow, 'updates-review' = focused updates view
  const [viewMode, setViewMode] = useState<'all' | 'updates-review'>('all')

  // Group / sort state
  const [groupBy, setGroupBy] = useState<GroupBy>('brand')
  const [sortBy, setSortBy] = useState<SortBy>('confidence')

  // Loading / work state
  const [working, setWorking] = useState(false)
  const [statusMsg, setStatusMsg] = useState<string | null>(null)
  // "Dataset already up to date" note shown after a hash-checked check found no change.
  const [upToDateMsg, setUpToDateMsg] = useState<string | null>(null)
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

  // AbortController for the in-flight match/recompute fetch — aborted on unmount so
  // navigating away cancels the client wait and clears the loading state immediately.
  const matchAbortRef = useRef<AbortController | null>(null)

  // Load cache status on mount (instant — no network fetch to FDB)
  useEffect(() => {
    getOpenTagStatus()
      .then(s => setCacheStatus(s))
      .catch(() => { /* status unavailable — banner stays absent */ })
    return () => { matchAbortRef.current?.abort() }
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

  // Run the full load. `datasetMode` controls the dataset step:
  // - 'skip'  — don't touch the dataset (warm cache); serve/recompute matches only.
  // - 'check' — cheap upstream commit-SHA check; downloads only if the commit changed.
  //             When the commit is UNCHANGED the heavy match recompute is skipped too
  //             (the dataset is identical), and we offer "Pull contents anyway".
  // - 'pull'  — force a full tarball download regardless of the commit, then recompute.
  // recomputeMatches=true forces the server to re-score even on a warm dataset.
  const runLoad = useCallback(async (
    datasetMode: 'skip' | 'check' | 'pull',
    recomputeMatches = false,
  ) => {
    // Abort any prior in-flight match fetch before starting a new one.
    matchAbortRef.current?.abort()
    const controller = new AbortController()
    matchAbortRef.current = controller

    setWorking(true)
    setError(null)
    setStatusMsg(null)
    setUpToDateMsg(null)
    try {
      let datasetChanged = false
      if (datasetMode !== 'skip') {
        const known = cacheStatus?.last_count || cacheStatus?.count || 0
        const recordHint = known > 0 ? `${known.toLocaleString()}+ records` : 'thousands of records'
        setStatusMsg(
          datasetMode === 'pull'
            ? `Downloading the OpenPrintTag dataset from OpenPrintTag… (${recordHint} — up to a minute)`
            : 'Checking OpenPrintTag for updates…',
        )
        const meta = await postOpenTagRefresh(datasetMode === 'pull')
        // Refresh status banner after the check/download.
        getOpenTagStatus().then(s => setCacheStatus(s)).catch(() => {})
        if (datasetMode === 'check' && meta.unchanged) {
          // No content change — tell the user and bump the banner age.
          const n = meta.count.toLocaleString()
          const sha = meta.commit_sha ? meta.commit_sha.slice(0, 7) : 'same commit'
          setStatusMsg(null)
          setError(null)
          setUpToDateMsg(`Dataset already up to date (${sha} · ${n} records).`)
          if (!recomputeMatches) {
            // No recompute requested — report the dataset is fresh and stop.
            return
          }
          // Recompute requested: dataset is fresh, proceed without downloading.
        } else {
          datasetChanged = true
        }
      }
      // A dataset re-download/change always means a fresh recompute (cache invalid).
      const recompute = recomputeMatches || datasetChanged
      setStatusMsg(
        recompute ? 'Matching your Spoolman filaments…' : 'Loading your last match…',
      )
      const data = await getOpenTagMatches(recompute, controller.signal)
      _applyMatchesData(data)
    } catch (e: unknown) {
      // Swallow abort errors — the user navigated away or kicked off a newer fetch.
      if (e instanceof DOMException && e.name === 'AbortError') return
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      if (matchAbortRef.current === controller) {
        setWorking(false)
        setStatusMsg(null)
        matchAbortRef.current = null
      }
    }
  }, [_applyMatchesData, cacheStatus])

  // "Force re-download dataset": force the full tarball download regardless of commit SHA.
  const handleForcePull = useCallback(async () => {
    setToolbarView('match')
    setViewMode('all')
    runLoad('pull')
  }, [runLoad])

  // "Re-match": SHA-check OPT (download only if changed) + always re-read Spoolman + recompute.
  const handleReMatch = useCallback(() => {
    setToolbarView('match')
    setViewMode('all')
    runLoad('check', true)
  }, [runLoad])

  // "Matches" toolbar button: switch to match view and show the cached result (fast).
  const handleMatchToDb = useCallback(() => {
    setToolbarView('match')
    setViewMode('all')
    if (!response) {
      // First time: serve the cached match instantly when the dataset is warm; when
      // the cache is missing/stale, do a cheap SHA check (downloads only if changed).
      const warm = cacheStatus !== null && cacheStatus.exists && !cacheStatus.stale
      runLoad(warm ? 'skip' : 'check')
    }
    // If already loaded, just re-enter the view — don't re-fetch
  }, [response, cacheStatus, runLoad])

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
      // Unmatch sentinel: stage a clear; field decisions are irrelevant (none are written).
      if (idx === UNMATCH_IDX) return
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

  // When a user picks a search result, inject it as candidates[0] for that filament
  // (prepend so it becomes the active selection) and reset field decisions to its OPT values.
  const handleSearchSelect = useCallback(
    (smId: number, candidate: OpenTagCandidate) => {
      setResponse(prev => {
        if (!prev) return prev
        const matches = prev.matches.map(m => {
          if (m.spoolman_filament_id !== smId) return m
          // Prepend the search result; deduplicate by slug/uuid so repeated picks don't bloat the list
          const existing = m.candidates ?? []
          const filtered = existing.filter(
            c => c.opt_slug !== candidate.opt_slug || c.opt_uuid !== candidate.opt_uuid,
          )
          return { ...m, candidates: [candidate, ...filtered], confidence: candidate.confidence }
        })
        return { ...prev, matches }
      })
      // Reset field decisions to the injected candidate's OPT values
      setFieldDecisions(prev => {
        const newDecisions: Record<string, OpenTagFieldDecision> = {}
        for (const row of candidate.fields) {
          newDecisions[row.field] = { field: row.field, value: row.opentag_value, keep_mine: false }
        }
        return { ...prev, [smId]: newDecisions }
      })
      // Select index 0 (the just-injected candidate)
      setSelectedCandidates(prev => ({ ...prev, [smId]: 0 }))
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
        // Unmatch staged: emit a clear_identity decision (backend resolves the FDB id
        // from the SM cross-ref extra). No field/identity writes.
        if (selectedCandidates[m.spoolman_filament_id] === UNMATCH_IDX) {
          return {
            spoolman_filament_id: m.spoolman_filament_id,
            ignored: false,
            clear_identity: true,
            fields: [],
          }
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

  // Count of already-tagged filaments with drifted data (from backend, or computed locally)
  const updatesCount = response?.updates_count ?? matches.filter(m => m.has_update).length

  // Matches that should appear in the Updates Review view (has_update OR ignored_updates,
  // so the user can see/manage their ignores from that view too)
  const updateMatches = useMemo(
    () => matches.filter(m => m.has_update || m.ignored_updates),
    [matches],
  )

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
      actionLabel="Apply OpenPrintTag writes"
      onCancel={() => setShowBackupDialog(false)}
      onProceed={() => { setShowBackupDialog(false); void runApply() }}
    />
    <div className="p-6 max-w-5xl mx-auto">
      <h1 className="text-2xl font-bold mb-1 text-gray-900 dark:text-gray-100">OpenPrintTag Cleanup</h1>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
        Match your Spoolman filaments against the OpenPrintTag database, review field
        differences, and apply canonical data — including pushing OpenPrintTag identity into
        Filament DB.
      </p>

      {/* Top toolbar — pick an action first; nothing loads on mount */}
      <div className="flex items-center gap-2 mb-6 p-3 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg">
        <button
          type="button"
          className={`px-4 py-2 text-sm rounded border transition-colors ${
            toolbarView === 'match'
              ? 'bg-indigo-100 dark:bg-indigo-900/40 border-indigo-400 dark:border-indigo-600 text-indigo-700 dark:text-indigo-300 font-semibold'
              : 'border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700'
          }`}
          onClick={handleMatchToDb}
          disabled={working}
          title="Show your most recent match results (cached). Nothing is re-scanned — use Re-match to update."
        >
          Matches
        </button>
        <button
          type="button"
          className={`px-4 py-2 text-sm rounded border transition-colors ${
            working && toolbarView !== 'missing-values'
              ? 'bg-indigo-50 dark:bg-indigo-900/20 border-indigo-300 dark:border-indigo-700 text-indigo-700 dark:text-indigo-300 opacity-70 cursor-not-allowed'
              : 'border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700'
          }`}
          onClick={handleReMatch}
          disabled={working}
          title="Re-read your Spoolman filaments and check OpenPrintTag for updates, then re-score all matches."
        >
          Re-match
        </button>
        <button
          type="button"
          className="px-4 py-2 text-sm rounded border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50"
          onClick={() => void handleForcePull()}
          disabled={working}
          title="Download the full OpenPrintTag dataset even if it hasn't changed upstream."
        >
          Force re-download dataset
        </button>
        <button
          type="button"
          className={`px-4 py-2 text-sm rounded border transition-colors ${
            toolbarView === 'missing-values'
              ? 'bg-indigo-100 dark:bg-indigo-900/40 border-indigo-400 dark:border-indigo-600 text-indigo-700 dark:text-indigo-300 font-semibold'
              : 'border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700'
          }`}
          onClick={() => setToolbarView('missing-values')}
          title="Find which of your tagged filaments most need data contributed to OpenPrintTag (audits the OpenPrintTag database, not your spools)"
        >
          Show missing values
        </button>

        {/* Match freshness badge — always visible once matches have been loaded */}
        {response?.computed_at && (
          <div className="ml-auto">
            {response.stale_inputs ? (
              <span className="px-3 py-1.5 rounded bg-amber-100 dark:bg-amber-900/30 border border-amber-300 dark:border-amber-700 text-sm text-amber-800 dark:text-amber-300 whitespace-nowrap">
                Last matched {formatMatchAge(response.computed_at)} · Spoolman changed since — Re-match to update.
              </span>
            ) : (
              <span className="text-sm text-gray-500 dark:text-gray-400 whitespace-nowrap">
                Last matched {formatMatchAge(response.computed_at)}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Dataset status banner — populated instantly from cache, no FDB fetch */}
      <div className="flex items-center gap-4 mb-6 p-3 bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg">
        {cacheStatus?.exists ? (
          <>
            <span className="text-sm text-gray-600 dark:text-gray-300">
              OpenPrintTag dataset: <strong>{cacheStatus.count}</strong> materials
            </span>
            <span className="text-sm text-gray-500 dark:text-gray-400">
              fetched {formatAge(cacheStatus.fetched_at)}
            </span>
            {cacheStatus.stale && (
              <span className="px-2 py-0.5 rounded bg-yellow-100 dark:bg-yellow-900/30 text-yellow-800 dark:text-yellow-300 text-xs">stale</span>
            )}
            {upToDateMsg && (
              <span className="text-sm text-green-700 dark:text-green-400">
                {upToDateMsg}
              </span>
            )}
          </>
        ) : (
          <span className="text-sm text-gray-500 dark:text-gray-400">
            {cacheStatus === null ? 'Checking dataset cache…' : 'No dataset cached yet.'}
          </span>
        )}
      </div>

      {/* Idle landing state — shown when no action has been picked yet */}
      {toolbarView === 'idle' && (
        <div className="py-12 text-center text-gray-500 dark:text-gray-400">
          <p className="text-base mb-2 font-medium text-gray-700 dark:text-gray-200">Pick an action above to get started.</p>
          <p className="text-sm">
            <strong>Matches</strong> — show your most recent match results (cached; no re-scan).
          </p>
          <p className="text-sm mt-1">
            <strong>Re-match</strong> — re-read your Spoolman filaments, check OpenPrintTag for updates, and re-score all matches.
          </p>
          <p className="text-sm mt-1">
            <strong>Show missing values</strong> — find which of your tagged filaments most need data contributed to OpenPrintTag (audits the OpenPrintTag database, not your spools).
          </p>
        </div>
      )}

      {/* Missing values report — OpenPrintTag record completeness for tagged filaments */}
      {toolbarView === 'missing-values' && <MissingValuesReport />}

      {/* Updates available banner — shown once matches are loaded (match view only) */}
      {!working && toolbarView === 'match' && response && updatesCount > 0 && step === 'review' && viewMode === 'all' && (
        <div className="mb-4 flex items-center gap-4 px-4 py-3 bg-amber-50 dark:bg-amber-900/20 border border-amber-300 dark:border-amber-700 rounded-lg">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" className="w-4 h-4 text-amber-600 dark:text-amber-400 shrink-0">
            <path d="M2 3a1 1 0 0 1 1-1h4.586a1 1 0 0 1 .707.293l5.414 5.414a1 1 0 0 1 0 1.414l-4.586 4.586a1 1 0 0 1-1.414 0L2.293 8.293A1 1 0 0 1 2 7.586V3Z" />
          </svg>
          <span className="text-sm text-amber-800 dark:text-amber-300 font-medium">
            {updatesCount} filament{updatesCount !== 1 ? 's have' : ' has'} updated OpenPrintTag values
          </span>
          <span className="text-xs text-amber-700 dark:text-amber-400">
            Already-tagged filaments with data drift in the latest dataset.
          </span>
          <button
            type="button"
            className="ml-auto px-3 py-1.5 text-sm bg-amber-600 text-white rounded hover:bg-amber-700 font-medium"
            onClick={() => setViewMode('updates-review')}
          >
            Review updates
          </button>
        </div>
      )}

      {/* Error and progress — only shown when the match view is active */}
      {toolbarView === 'match' && error && (
        <div className="mb-4 px-4 py-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded text-sm text-red-700 dark:text-red-400">
          <strong>Error:</strong> {error}
        </div>
      )}

      {toolbarView === 'match' && working && statusMsg && (
        <div className="mb-4 flex items-center gap-3 px-4 py-3 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded text-sm text-blue-700 dark:text-blue-300">
          <svg className="animate-spin h-4 w-4 shrink-0 text-blue-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
          </svg>
          {statusMsg}
        </div>
      )}

      {/* Updates Review focused view */}
      {toolbarView === 'match' && !working && viewMode === 'updates-review' && response && (
        <UpdatesReviewSection
          matches={updateMatches}
          onBack={() => setViewMode('all')}
          onApplied={() => { setViewMode('all'); void runLoad(true, true) }}
        />
      )}

      {toolbarView === 'match' && !working && viewMode === 'all' && step === 'review' && response && (
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
              onSearchSelect={handleSearchSelect}
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

          {/* Bottom action bar */}
          <div className="mt-4">
            <WizardActionBar
              onNext={() => setStep('confirm')}
              nextLabel="Review & Confirm →"
              nextDisabled={withMatch.length === 0}
            />
          </div>
        </div>
      )}

      {toolbarView === 'match' && !working && viewMode === 'all' && step === 'confirm' && response && (
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

      {toolbarView === 'match' && viewMode === 'all' && step === 'done' && applyResult && (
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
            onClick={() => { setStep('review'); runLoad(true, true) }}
          >
            Start over
          </button>
        </div>
      )}
    </div>
    </>
  )
}
