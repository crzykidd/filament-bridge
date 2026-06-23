import { useState, useMemo, useEffect, useRef, useCallback, Fragment } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  getConflicts,
  resolveConflict,
  bulkResolveConflicts,
  getDivergenceContext,
  importConflictRecord,
  getFilamentSuggestions,
} from '../api/client'
import { useApi } from '../api/hooks'
import { DeepLinks } from '../components/DeepLinks'
import { ColorDisplay } from '../components/ColorDisplay'
import { HelpTip } from '../components/HelpTip'
import type {
  ConflictResponse,
  DivergenceContextResponse,
  DivergenceVariantEntry,
  FilamentSuggestion,
  WizardExecuteRecord,
  WizardExecuteResponse,
} from '../api/types'
import { formatLocal } from '../utils/datetime'

type Resolution = 'spoolman' | 'filamentdb' | 'manual'
type SortKey = 'detected' | 'type' | 'label'

// ---------------------------------------------------------------------------
// Conflict type classification
// ---------------------------------------------------------------------------

type ConflictType =
  | 'deleted'
  | 'new_spool_sm'
  | 'new_spool_fdb'
  | 'new_filament_sm'
  | 'new_filament_fdb'
  | 'weight'
  | 'multicolor'
  | 'property'
  | 'master_divergence'

const TYPE_LABELS: Record<ConflictType, string> = {
  deleted: 'Deleted record',
  new_spool_sm: 'New spool (Spoolman)',
  new_spool_fdb: 'New spool (Filament DB)',
  new_filament_sm: 'New filament (Spoolman)',
  new_filament_fdb: 'New filament (Filament DB)',
  weight: 'Weight',
  multicolor: 'Multicolor',
  property: 'Property',
  master_divergence: 'Master divergence',
}

const TYPE_BADGE_COLORS: Record<ConflictType, string> = {
  deleted: 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400',
  new_spool_sm: 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400',
  new_spool_fdb: 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400',
  new_filament_sm: 'bg-teal-100 dark:bg-teal-900/30 text-teal-700 dark:text-teal-400',
  new_filament_fdb: 'bg-cyan-100 dark:bg-cyan-900/30 text-cyan-700 dark:text-cyan-400',
  weight: 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400',
  multicolor: 'bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400',
  property: 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300',
  master_divergence: 'bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-400',
}

const TYPE_ORDER: ConflictType[] = [
  'deleted',
  'new_spool_sm',
  'new_spool_fdb',
  'new_filament_sm',
  'new_filament_fdb',
  'weight',
  'multicolor',
  'property',
  'master_divergence',
]

const DELETION_FIELD = '__record_deleted__'

function classifyConflict(c: ConflictResponse): ConflictType {
  if (c.conflict_type === 'master_divergence') return 'master_divergence'
  if (c.field_name === DELETION_FIELD) return 'deleted'
  if (c.field_name === 'new_spool') return c.spoolman_id != null ? 'new_spool_sm' : 'new_spool_fdb'
  if (c.field_name === 'new_filament') return c.spoolman_id != null ? 'new_filament_sm' : 'new_filament_fdb'
  if (c.field_name === 'weight' || c.field_name === 'remaining_weight') return 'weight'
  if (c.field_name === 'multicolor') return 'multicolor'
  return 'property'
}

function isImportable(c: ConflictResponse): boolean {
  return c.field_name === 'new_spool' || c.field_name === 'new_filament'
}

function deletedSideLabel(conflict: ConflictResponse): string {
  const descriptor = (conflict.spoolman_value ?? conflict.filamentdb_value) as { deleted_side?: string } | null
  if (descriptor?.deleted_side === 'filamentdb') return 'Filament DB'
  if (descriptor?.deleted_side === 'spoolman') return 'Spoolman'
  return 'one side'
}

function entityLabel(conflict: ConflictResponse): string {
  return conflict.entity_type === 'spool' ? 'SPOOL' : 'FILAMENT'
}

/**
 * Build a human-readable identity line for new_filament / new_spool cards.
 * Shows "Vendor · Name (SM #id)" or "Vendor · Name (FDB id…)" as available.
 * Falls back gracefully for legacy rows that have no enriched identity.
 */
function newRecordIdentityLine(conflict: ConflictResponse): string | null {
  const { vendor, name, spoolman_id, filamentdb_filament_id } = conflict
  const parts: string[] = []
  if (vendor) parts.push(vendor)
  if (name) parts.push(name)
  if (parts.length === 0) return null
  const idPart = spoolman_id != null
    ? `(SM #${spoolman_id})`
    : filamentdb_filament_id != null
      ? `(FDB ${filamentdb_filament_id.slice(0, 8)}…)`
      : ''
  return [parts.join(' · '), idPart].filter(Boolean).join(' ')
}

// ---------------------------------------------------------------------------
// Shared sub-components
// ---------------------------------------------------------------------------

function ValueDisplay({ value }: { value: unknown }) {
  if (value == null) return <span className="text-gray-400 dark:text-gray-500">—</span>
  const s = typeof value === 'object' ? JSON.stringify(value) : String(value)
  return <span className="font-mono text-xs text-gray-900 dark:text-gray-100">{s}</span>
}

/** Two-column Spoolman | FDB grid, reusing the SyncedRecords DetailGrid styling. */
function SideBySideGrid({ rows }: { rows: { field: string; label: string; sm: unknown; fdb: unknown }[] }) {
  if (rows.length === 0) return null
  return (
    <div className="grid grid-cols-[10rem_1fr_1fr] gap-x-4 gap-y-1 text-xs max-w-2xl">
      <div className="font-medium text-gray-400 dark:text-gray-500 uppercase tracking-wide">Field</div>
      <div className="font-medium text-emerald-700 dark:text-emerald-400">Spoolman</div>
      <div className="font-medium text-blue-700 dark:text-blue-400">Filament DB</div>
      {rows.map(r => (
        <Fragment key={r.field}>
          <div className="text-gray-600 dark:text-gray-300">{r.label}</div>
          <div className="font-mono text-gray-800 dark:text-gray-200">
            <ValueDisplay value={r.sm} />
          </div>
          <div className="font-mono text-gray-800 dark:text-gray-200">
            <ValueDisplay value={r.fdb} />
          </div>
        </Fragment>
      ))}
    </div>
  )
}

/** Compact import preview table (WizardExecuteRecord list). */
function ImportPreview({ records }: { records: WizardExecuteRecord[] }) {
  if (records.length === 0) return <p className="text-xs text-gray-400 dark:text-gray-500 italic">Nothing to import.</p>
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-gray-400 dark:text-gray-500 uppercase tracking-wide border-b border-gray-100 dark:border-gray-700">
            <th className="pb-1 pr-3">Type</th>
            <th className="pb-1 pr-3">Action</th>
            <th className="pb-1">Label</th>
          </tr>
        </thead>
        <tbody>
          {records.map((r, i) => (
            <tr key={i} className="border-b border-gray-50 dark:border-gray-800 last:border-0">
              <td className="py-0.5 pr-3 text-gray-500 dark:text-gray-400">{r.entity_type}</td>
              <td className="py-0.5 pr-3">
                <span className={`font-medium ${
                  r.action === 'created' ? 'text-emerald-600 dark:text-emerald-400'
                    : r.action === 'updated' ? 'text-blue-600 dark:text-blue-400'
                    : r.action === 'failed' ? 'text-red-600 dark:text-red-400'
                    : 'text-gray-500 dark:text-gray-400'
                }`}>{r.action}</span>
              </td>
              <td className="py-0.5 text-gray-700 dark:text-gray-300">{r.label ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Import flow for new_spool / new_filament conflicts
// ---------------------------------------------------------------------------

type ImportStep = 'form' | 'preview' | 'done'

/** Format a suggestion label for the dropdown: "Vendor · Name (score%)" */
function suggestionLabel(s: FilamentSuggestion): string {
  const parts: string[] = []
  if (s.vendor) parts.push(s.vendor)
  if (s.name) parts.push(s.name)
  const base = parts.join(' · ') || s.filamentdb_id
  const pct = Math.round(s.score * 100)
  const master = s.is_master_container ? ' [Master]' : ''
  return `${base}${master} (${pct}%)`
}

/** Validate a 24-char lowercase hex MongoDB ObjectId string. */
function is24Hex(s: string): boolean {
  return /^[0-9a-fA-F]{24}$/.test(s.trim())
}

function NewRecordAddFlow({
  conflict,
  onResolved,
  onCancel,
}: {
  conflict: ConflictResponse
  onResolved: () => void
  onCancel: () => void
}) {
  const isSmToFdb = conflict.spoolman_id != null
  const [filamentAction, setFilamentAction] = useState<'create' | 'link'>('create')
  // Suggestion selected from dropdown
  const [selectedSuggestionId, setSelectedSuggestionId] = useState<string>('')
  // Manual 24-char override (takes precedence when filled and valid)
  const [manualId, setManualId] = useState('')
  const [tare, setTare] = useState('')
  const [step, setStep] = useState<ImportStep>('form')
  const [preview, setPreview] = useState<WizardExecuteResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  // Suggestions state
  const [suggestions, setSuggestions] = useState<FilamentSuggestion[] | null>(null)
  const [suggestionsLoading, setSuggestionsLoading] = useState(false)
  const [suggestionsErr, setSuggestionsErr] = useState<string | null>(null)

  // Load suggestions when user switches to "link" mode
  useEffect(() => {
    if (filamentAction !== 'link' || !isSmToFdb) return
    if (suggestions !== null) return  // already loaded
    setSuggestionsLoading(true)
    setSuggestionsErr(null)
    getFilamentSuggestions(conflict.id)
      .then(res => setSuggestions(res.suggestions))
      .catch(e => setSuggestionsErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setSuggestionsLoading(false))
  }, [filamentAction, isSmToFdb, conflict.id, suggestions])

  // The effective FDB id: manual override wins if valid, else selected suggestion.
  const effectiveFilamentdbId = manualId.trim() && is24Hex(manualId)
    ? manualId.trim()
    : selectedSuggestionId || null

  const linkReady = filamentAction !== 'link' || effectiveFilamentdbId != null

  async function runPreview() {
    setLoading(true)
    setErr(null)
    try {
      const res = await importConflictRecord(conflict.id, {
        dry_run: true,
        filament_action: filamentAction,
        filamentdb_id: filamentAction === 'link' ? effectiveFilamentdbId : null,
        tare_override: tare.trim() ? parseFloat(tare) : null,
      })
      setPreview(res)
      setStep('preview')
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  async function runExecute() {
    setLoading(true)
    setErr(null)
    try {
      await importConflictRecord(conflict.id, {
        dry_run: false,
        filament_action: filamentAction,
        filamentdb_id: filamentAction === 'link' ? effectiveFilamentdbId : null,
        tare_override: tare.trim() ? parseFloat(tare) : null,
      })
      setStep('done')
      onResolved()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  if (step === 'done') {
    return (
      <div className="bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded p-3 text-sm text-emerald-800 dark:text-emerald-300">
        Imported successfully — conflict resolved.
      </div>
    )
  }

  if (step === 'preview' && preview != null) {
    return (
      <div className="space-y-3">
        <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded p-3 text-sm text-blue-800 dark:text-blue-300">
          <strong>Preview</strong> — no changes written yet. Review below, then confirm.
        </div>
        <div className="text-xs text-gray-500 dark:text-gray-400">
          Creates: {preview.created_filaments} filament(s), {preview.created_spools} spool(s) ·
          Updates: {preview.updated_filaments + preview.updated_spools} ·
          Skips: {preview.skipped_filaments + preview.skipped_spools}
        </div>
        <ImportPreview records={preview.records} />
        {err && <p className="text-sm text-red-600 dark:text-red-400">{err}</p>}
        <div className="flex gap-2">
          <button
            onClick={runExecute}
            disabled={loading}
            className="px-4 py-1.5 bg-emerald-600 text-white rounded text-sm font-medium hover:bg-emerald-700 disabled:opacity-50"
          >
            {loading ? 'Importing…' : 'Confirm import'}
          </button>
          <button
            onClick={() => { setStep('form'); setErr(null) }}
            className="px-3 py-1.5 bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-200 rounded text-sm font-medium hover:bg-gray-300 dark:hover:bg-gray-600"
          >
            Back
          </button>
        </div>
      </div>
    )
  }

  // step === 'form'
  return (
    <div className="space-y-3">
      {/* Only show filament action picker for SM→FDB (FDB→SM always creates) */}
      {isSmToFdb && (
        <div className="space-y-2">
          <p className="text-sm font-medium text-gray-700 dark:text-gray-300">Filament action</p>
          <div className="flex gap-2">
            {(['create', 'link'] as const).map(opt => (
              <button
                key={opt}
                onClick={() => setFilamentAction(opt)}
                className={`px-3 py-1.5 rounded text-sm font-medium border transition-colors ${
                  filamentAction === opt
                    ? 'bg-indigo-600 text-white border-indigo-600'
                    : 'bg-white dark:bg-gray-700 border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-600'
                }`}
              >
                {opt === 'create' ? 'Create new filament' : 'Link to existing filament'}
              </button>
            ))}
          </div>

          {filamentAction === 'link' && (
            <div className="space-y-2">
              {/* Suggestions dropdown */}
              {suggestionsLoading && (
                <p className="text-xs text-gray-400 dark:text-gray-500">Loading suggestions…</p>
              )}
              {suggestionsErr && (
                <p className="text-xs text-red-500 dark:text-red-400">Could not load suggestions: {suggestionsErr}</p>
              )}
              {!suggestionsLoading && suggestions !== null && (
                <div className="flex items-center gap-2">
                  <label className="text-sm text-gray-600 dark:text-gray-300 shrink-0">Suggested match</label>
                  {suggestions.length === 0 ? (
                    <span className="text-xs text-gray-400 dark:text-gray-500 italic">No suggestions — use the manual ID field below.</span>
                  ) : (
                    <select
                      value={selectedSuggestionId}
                      onChange={e => setSelectedSuggestionId(e.target.value)}
                      className="flex-1 border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 rounded px-3 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
                    >
                      <option value="">— pick a suggestion —</option>
                      {suggestions.map(s => (
                        <option key={s.filamentdb_id} value={s.filamentdb_id}>
                          {suggestionLabel(s)}
                        </option>
                      ))}
                    </select>
                  )}
                </div>
              )}
              {/* Manual 24-char hex override */}
              <div className="flex items-center gap-2">
                <label className="text-sm text-gray-600 dark:text-gray-300 shrink-0">
                  Manual FDB ID
                  <HelpTip text="24-character hex MongoDB ObjectId. Overrides the suggestion above when filled." />
                </label>
                <input
                  type="text"
                  placeholder="24-char hex id (optional override)…"
                  value={manualId}
                  onChange={e => setManualId(e.target.value)}
                  className={`flex-1 border rounded px-3 py-1 text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-400 ${
                    manualId.trim() && !is24Hex(manualId)
                      ? 'border-red-400 dark:border-red-500'
                      : 'border-gray-300 dark:border-gray-600'
                  }`}
                />
              </div>
              {manualId.trim() && !is24Hex(manualId) && (
                <p className="text-xs text-red-500 dark:text-red-400">Must be exactly 24 hex characters.</p>
              )}
              {effectiveFilamentdbId && (
                <p className="text-xs text-gray-400 dark:text-gray-500">
                  Will link to FDB ID: <span className="font-mono">{effectiveFilamentdbId}</span>
                </p>
              )}
            </div>
          )}
        </div>
      )}

      <div className="flex items-center gap-2">
        <label className="text-sm text-gray-600 dark:text-gray-300 shrink-0">Tare override (g)</label>
        <input
          type="number"
          placeholder="Optional, e.g. 200"
          value={tare}
          onChange={e => setTare(e.target.value)}
          min={0}
          className="w-40 border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 rounded px-3 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
        />
        <HelpTip text="Overrides the filament's spool_weight for the weight conversion. Leave blank to use the default from Spoolman." />
      </div>

      {err && <p className="text-sm text-red-600 dark:text-red-400">{err}</p>}

      <div className="flex gap-2">
        <button
          onClick={runPreview}
          disabled={loading || !linkReady || (manualId.trim() !== '' && !is24Hex(manualId))}
          className="px-4 py-1.5 bg-emerald-600 text-white rounded text-sm font-medium hover:bg-emerald-700 disabled:opacity-50"
        >
          {loading ? 'Loading…' : 'Preview import'}
        </button>
        <button
          onClick={onCancel}
          className="px-3 py-1.5 bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-200 rounded text-sm font-medium hover:bg-gray-300 dark:hover:bg-gray-600"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Master-divergence specialized card
// ---------------------------------------------------------------------------

function VariantRow({ v, fieldName }: { v: DivergenceVariantEntry; fieldName: string }) {
  return (
    <div className="flex items-center gap-3 py-1.5 border-b border-gray-100 dark:border-gray-700 last:border-0">
      {/* Color swatch (small) */}
      {v.color_hex && (
        <span
          className="shrink-0 w-4 h-4 rounded-full border border-gray-200 dark:border-gray-600"
          style={{ backgroundColor: `#${v.color_hex.replace(/^#/, '')}` }}
        />
      )}
      <span className="flex-1 text-sm text-gray-800 dark:text-gray-200 truncate min-w-0">
        {v.name ?? v.fdb_id}
        {v.inherited && (
          <span className="ml-1.5 text-xs text-gray-400 dark:text-gray-500">(inherited)</span>
        )}
      </span>
      <span className="shrink-0 font-mono text-xs text-gray-500 dark:text-gray-400">
        {String(v.current_value ?? '—')}
      </span>
      <span onClick={e => e.stopPropagation()}>
        <DeepLinks
          filamentdbFilamentId={v.fdb_id}
          spoolmanFilamentId={v.spoolman_filament_id ?? undefined}
        />
      </span>
    </div>
  )
}

/**
 * Specialized resolution panel for master_divergence conflicts.
 * Shows the variant list fetched from GET /conflicts/:id/divergence-context
 * and three action buttons.
 */
function MasterDivergenceDetail({
  conflict,
  onResolved,
}: {
  conflict: ConflictResponse
  onResolved: () => void
}) {
  const [ctx, setCtx] = useState<DivergenceContextResponse | null>(null)
  const [loadingCtx, setLoadingCtx] = useState(false)
  const [ctxErr, setCtxErr] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [confirmAction, setConfirmAction] = useState<'apply_all' | 'variant_override' | 'ignore' | null>(null)

  // Fetch context on first render.
  useEffect(() => {
    let cancelled = false
    setLoadingCtx(true)
    getDivergenceContext(conflict.id)
      .then(c => { if (!cancelled) { setCtx(c); setLoadingCtx(false) } })
      .catch(e => { if (!cancelled) { setCtxErr(e instanceof Error ? e.message : String(e)); setLoadingCtx(false) } })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conflict.id])

  async function submit(action: 'apply_all' | 'variant_override' | 'ignore') {
    setSubmitting(true)
    setErr(null)
    try {
      await resolveConflict(conflict.id, {
        resolution: 'spoolman',
        action,
      })
      onResolved()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setSubmitting(false)
      setConfirmAction(null)
    }
  }

  const variantCount = ctx?.variants.length ?? '?'
  const masterName = ctx?.master_name ?? conflict.filamentdb_filament_id
  const fieldLabel = conflict.field_name
  const incomingValue = String(conflict.spoolman_value ?? '?')
  const masterValue = ctx != null ? String(ctx.master_current_value ?? '—') : '…'

  return (
    <div className="border-t border-gray-100 dark:border-gray-700 mt-0 px-4 pb-4 pt-3 space-y-3">
      {/* Entity type label */}
      <div className="flex items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-orange-600 dark:text-orange-400">
          {entityLabel(conflict)}
        </span>
        <span className="text-xs text-gray-400 dark:text-gray-500">master_divergence on field: {fieldLabel}</span>
      </div>

      {/* Header: field + incoming vs master values */}
      <div className="grid grid-cols-2 gap-4 text-sm">
        <div className="bg-emerald-50 dark:bg-emerald-900/20 rounded p-3">
          <p className="text-xs font-medium text-emerald-700 dark:text-emerald-400 mb-1">
            Incoming Spoolman value
          </p>
          <span className="font-mono text-xs text-gray-900 dark:text-gray-100">{incomingValue}</span>
        </div>
        <div className="bg-blue-50 dark:bg-blue-900/20 rounded p-3">
          <p className="text-xs font-medium text-blue-700 dark:text-blue-400 mb-1">
            Master ({masterName}) current value
          </p>
          <span className="font-mono text-xs text-gray-900 dark:text-gray-100">{masterValue}</span>
        </div>
      </div>

      {/* Explanation */}
      <div className="bg-orange-50 dark:bg-orange-900/20 border border-orange-200 dark:border-orange-800 rounded p-3 text-sm text-orange-800 dark:text-orange-300">
        This variant inherits <strong>{fieldLabel}</strong> from its master. The incoming Spoolman value
        differs from the master's value. Choose how to resolve:
      </div>

      {/* Variant list */}
      {loadingCtx && <p className="text-sm text-gray-400 dark:text-gray-500">Loading variant list…</p>}
      {ctxErr && <p className="text-sm text-red-500 dark:text-red-400">{ctxErr}</p>}
      {ctx && ctx.variants.length > 0 && (
        <div className="border border-gray-200 dark:border-gray-700 rounded overflow-hidden">
          <div className="bg-gray-50 dark:bg-gray-750 px-3 py-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">
            Variants in this line ({ctx.variants.length})
          </div>
          <div className="px-3">
            {ctx.variants.map(v => (
              <VariantRow key={v.fdb_id} v={v} fieldName={fieldLabel} />
            ))}
          </div>
        </div>
      )}

      {/* Confirm prompt */}
      {confirmAction === 'apply_all' && (
        <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded p-3 text-sm text-amber-800 dark:text-amber-300 space-y-2">
          <p>
            <strong>Apply to all variants</strong> will write <em>{incomingValue}</em> to the master
            and all {variantCount} variant(s) in Filament DB, and to their Spoolman filaments.
          </p>
          <div className="flex gap-2">
            <button
              onClick={() => submit('apply_all')}
              disabled={submitting}
              className="px-3 py-1.5 bg-orange-600 text-white rounded text-sm font-medium hover:bg-orange-700 disabled:opacity-50"
            >
              {submitting ? 'Applying…' : 'Confirm apply to all'}
            </button>
            <button
              onClick={() => setConfirmAction(null)}
              className="px-3 py-1.5 bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-200 rounded text-sm font-medium hover:bg-gray-300 dark:hover:bg-gray-600"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {confirmAction !== 'apply_all' && (
        <div className="flex flex-wrap items-start gap-3">
          <div className="flex flex-col items-start gap-1">
            <button
              onClick={() => setConfirmAction('apply_all')}
              disabled={submitting}
              className="px-4 py-1.5 bg-orange-600 text-white rounded text-sm font-medium hover:bg-orange-700 disabled:opacity-50"
              title={`Write ${incomingValue} to master and all variants in FDB and Spoolman`}
            >
              Apply to all variants
            </button>
            <span className="text-xs text-gray-400 dark:text-gray-500 pl-1">Writes value to master + every variant</span>
          </div>
          <div className="flex flex-col items-start gap-1">
            <button
              onClick={() => submit('variant_override')}
              disabled={submitting}
              className="px-4 py-1.5 bg-indigo-600 text-white rounded text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
              title="Write this value to this variant only; master and siblings unchanged"
            >
              {submitting ? 'Saving…' : "Make variant's own setting"}
            </button>
            <span className="text-xs text-gray-400 dark:text-gray-500 pl-1">Overrides this variant only, master unchanged</span>
          </div>
          <div className="flex flex-col items-start gap-1">
            <button
              onClick={() => submit('ignore')}
              disabled={submitting}
              className="px-4 py-1.5 bg-gray-500 text-white rounded text-sm font-medium hover:bg-gray-600 disabled:opacity-50"
              title="No write; store baselines so this won't re-queue next cycle"
            >
              {submitting ? 'Saving…' : 'Ignore'}
            </button>
            <span className="text-xs text-gray-400 dark:text-gray-500 pl-1">No write; stores baselines to prevent re-queue</span>
          </div>
        </div>
      )}

      {err && <p className="text-sm text-red-600 dark:text-red-400">{err}</p>}
    </div>
  )
}

/**
 * The expanded resolve / detail body — rendered inside a CollapsibleConflict
 * when expanded (non-master_divergence types).
 */
function ConflictDetail({ conflict, onResolved }: { conflict: ConflictResponse; onResolved: () => void }) {
  const [resolution, setResolution] = useState<Resolution>('spoolman')
  const [manualValue, setManualValue] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [showAddFlow, setShowAddFlow] = useState(false)

  const isDeletion = conflict.field_name === DELETION_FIELD
  const importable = isImportable(conflict)
  const isSmToFdb = conflict.spoolman_id != null

  async function submit(overrideResolution?: Resolution) {
    const res = overrideResolution ?? resolution
    setSubmitting(true)
    setErr(null)
    try {
      await resolveConflict(conflict.id, {
        resolution: res,
        value: res === 'manual' ? manualValue : undefined,
      })
      onResolved()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="border-t border-gray-100 dark:border-gray-700 mt-0 px-4 pb-4 pt-3 space-y-3">
      {/* Entity type label */}
      <div className="flex items-center gap-2">
        <span className={`text-xs font-semibold uppercase tracking-wide ${
          isDeletion ? 'text-red-600 dark:text-red-400'
          : importable ? 'text-emerald-600 dark:text-emerald-400'
          : 'text-indigo-600 dark:text-indigo-400'
        }`}>
          {entityLabel(conflict)}
        </span>
        {!isDeletion && !importable && (
          <span className="text-xs text-gray-400 dark:text-gray-500">field: {conflict.field_name}</span>
        )}
        {importable && (
          <span className="text-xs text-gray-500 dark:text-gray-400">
            {conflict.field_name === 'new_filament' ? 'Unmapped filament' : 'Unmapped spool'}
            {' — '}
            {isSmToFdb ? 'exists in Spoolman, not yet in Filament DB' : 'exists in Filament DB, not yet in Spoolman'}
          </span>
        )}
      </div>

      {/* Values grid (cross_system / weight / property / multicolor) */}
      {!isDeletion && !importable && (
        <SideBySideGrid rows={[
          {
            field: conflict.field_name,
            label: conflict.field_name,
            sm: conflict.spoolman_value,
            fdb: conflict.filamentdb_value,
          },
        ]} />
      )}

      {/* Deletion explanation */}
      {isDeletion && (
        <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded p-3 text-sm text-amber-800 dark:text-amber-300">
          This record was deleted in <strong>{deletedSideLabel(conflict)}</strong>. Removing the
          mapping will drop the pair from Synced Records. The deleted record will not be recreated.
        </div>
      )}

      {/* New record: Add flow or framing */}
      {importable && !showAddFlow && (
        <div className="space-y-2">
          {/* Identity row: color swatch + vendor · name (id) */}
          {(() => {
            const identLine = newRecordIdentityLine(conflict)
            return identLine != null ? (
              <div className="flex items-center gap-2">
                <ColorDisplay
                  colorHex={conflict.color_hex}
                  multiColorHexes={conflict.multi_color_hexes}
                  multiColorDirection={conflict.multi_color_direction}
                  showLabel={false}
                />
                <span className="text-sm font-medium text-gray-800 dark:text-gray-200">
                  {identLine}
                </span>
              </div>
            ) : null
          })()}
          <p className="text-sm text-gray-600 dark:text-gray-300">
            {conflict.field_name === 'new_filament'
              ? 'This filament has no counterpart in the other system. Use "Add" to import it, or "Dismiss" to clear the notice.'
              : 'This spool has no counterpart in the other system. Use "Add" to import it, or "Dismiss" to clear the notice.'}
          </p>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowAddFlow(true)}
              className="px-4 py-1.5 bg-emerald-600 text-white rounded text-sm font-medium hover:bg-emerald-700"
            >
              Add
            </button>
            <button
              onClick={() => submit('spoolman')}
              disabled={submitting}
              className="px-4 py-1.5 bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-200 rounded text-sm font-medium hover:bg-gray-300 dark:hover:bg-gray-600 disabled:opacity-50"
            >
              {submitting ? 'Dismissing…' : 'Dismiss'}
            </button>
          </div>
        </div>
      )}

      {importable && showAddFlow && (
        <NewRecordAddFlow
          conflict={conflict}
          onResolved={onResolved}
          onCancel={() => setShowAddFlow(false)}
        />
      )}

      {/* Action row — deletion */}
      {isDeletion && (
        <div className="flex items-center gap-2">
          <button
            onClick={() => submit('spoolman')}
            disabled={submitting}
            className="px-4 py-1.5 bg-red-600 text-white rounded text-sm font-medium hover:bg-red-700 disabled:opacity-50"
          >
            {submitting ? 'Removing…' : 'Remove mapping'}
          </button>
        </div>
      )}

      {/* Action row — cross_system / weight / property / multicolor */}
      {!isDeletion && !importable && (
        <div className="space-y-2">
          <p className="text-xs text-gray-400 dark:text-gray-500">
            Pick a side — the chosen value is written to both systems and the conflict is cleared.
          </p>
          <div className="flex items-center gap-2 flex-wrap">
            <button
              onClick={() => setResolution('spoolman')}
              className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
                resolution === 'spoolman'
                  ? 'bg-emerald-600 text-white'
                  : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
              }`}
            >
              Use Spoolman
            </button>
            <button
              onClick={() => setResolution('filamentdb')}
              className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
                resolution === 'filamentdb'
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
              }`}
            >
              Use Filament DB
            </button>
            <button
              onClick={() => setResolution('manual')}
              className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
                resolution === 'manual'
                  ? 'bg-indigo-600 text-white'
                  : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
              }`}
            >
              Manual value
            </button>
            {resolution === 'manual' && (
              <input
                type="text"
                placeholder="Enter value…"
                value={manualValue}
                onChange={e => setManualValue(e.target.value)}
                className="border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 rounded px-3 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
              />
            )}
            <button
              onClick={() => submit()}
              disabled={submitting || (resolution === 'manual' && !manualValue.trim())}
              className="ml-auto px-4 py-1.5 bg-indigo-600 text-white rounded text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
            >
              {submitting ? 'Saving…' : 'Resolve'}
            </button>
          </div>
        </div>
      )}

      {err && <p className="text-sm text-red-600 dark:text-red-400">{err}</p>}
    </div>
  )
}

/**
 * Compact single-row conflict card with expand/collapse.
 */
function CollapsibleConflict({
  conflict,
  expanded,
  onToggle,
  onResolved,
  tab,
  selected,
  onSelect,
  highlighted,
}: {
  conflict: ConflictResponse
  expanded: boolean
  onToggle: () => void
  onResolved: () => void
  tab: 'open' | 'resolved'
  selected: boolean
  onSelect: () => void
  highlighted?: boolean
}) {
  const type = classifyConflict(conflict)
  const fieldLabel = conflict.field_name === DELETION_FIELD ? 'Record deleted' : conflict.field_name

  return (
    <div
      data-conflict-id={conflict.id}
      className={`bg-white dark:bg-gray-800 rounded-lg border overflow-hidden transition-all duration-700 ${
        highlighted
          ? 'border-amber-400 dark:border-amber-500 ring-2 ring-amber-300 dark:ring-amber-600'
          : 'border-gray-200 dark:border-gray-700'
      }`}
    >
      {/* Compact summary row */}
      <div
        className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-750 select-none"
        onClick={onToggle}
      >
        {/* Checkbox (open tab only, stop propagation so click doesn't expand) */}
        {tab === 'open' && (
          <input
            type="checkbox"
            checked={selected}
            onClick={e => e.stopPropagation()}
            onChange={onSelect}
            className="h-4 w-4 rounded border-gray-300 dark:border-gray-600 text-indigo-600 shrink-0"
          />
        )}

        {/* Type badge */}
        <span className={`shrink-0 inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${TYPE_BADGE_COLORS[type]}`}>
          {TYPE_LABELS[type]}
        </span>

        {/* Color swatch */}
        <ColorDisplay
          colorHex={conflict.color_hex}
          multiColorHexes={conflict.multi_color_hexes}
          multiColorDirection={conflict.multi_color_direction}
          showLabel={false}
        />

        {/* Identity label */}
        <span className="flex-1 text-sm font-medium text-gray-800 dark:text-gray-200 truncate min-w-0">
          {conflict.label ?? `SM #${conflict.spoolman_id}`}
        </span>

        {/* Field / entity */}
        <span className="shrink-0 text-xs text-gray-400 dark:text-gray-500 hidden sm:block">{conflict.entity_type}</span>
        <span className="shrink-0 text-xs font-mono text-gray-500 dark:text-gray-400 hidden md:block">{fieldLabel}</span>

        {/* Detected time */}
        <span className="shrink-0 text-xs text-gray-400 dark:text-gray-500 hidden lg:block">
          {formatLocal(conflict.detected_at)}
        </span>

        {/* Deep links (stop click so expanding doesn't fight the link) */}
        <span onClick={e => e.stopPropagation()}>
          <DeepLinks
            filamentdbFilamentId={conflict.filamentdb_filament_id}
            spoolmanSpoolId={conflict.spoolman_id}
          />
        </span>

        {/* Resolved badge (resolved tab only) */}
        {tab === 'resolved' && conflict.resolution && (
          <span className="shrink-0 text-xs text-gray-400 dark:text-gray-500">via {conflict.resolution}</span>
        )}

        {/* Caret */}
        <span className={`shrink-0 text-gray-400 dark:text-gray-500 transition-transform ${expanded ? 'rotate-180' : ''}`}>
          ▾
        </span>
      </div>

      {/* Expanded detail */}
      {expanded && tab === 'open' && conflict.conflict_type === 'master_divergence' && (
        <MasterDivergenceDetail conflict={conflict} onResolved={onResolved} />
      )}
      {expanded && tab === 'open' && conflict.conflict_type !== 'master_divergence' && (
        <ConflictDetail conflict={conflict} onResolved={onResolved} />
      )}
      {expanded && tab === 'resolved' && (
        <div className="border-t border-gray-100 dark:border-gray-700 px-4 py-3 text-sm text-gray-500 dark:text-gray-400 space-y-1">
          <p>Resolved {formatLocal(conflict.resolved_at)} via <strong>{conflict.resolution}</strong></p>
          {conflict.resolved_value != null && (
            <p>Recorded value: <ValueDisplay value={conflict.resolved_value} /></p>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Bulk Add modal for new_spool / new_filament conflicts
// ---------------------------------------------------------------------------

function BulkAddModal({
  conflicts,
  onDone,
  onCancel,
}: {
  conflicts: ConflictResponse[]
  onDone: () => void
  onCancel: () => void
}) {
  const [results, setResults] = useState<{ id: number; label: string | null; status: 'pending' | 'ok' | 'error'; msg?: string }[]>(
    conflicts.map(c => ({ id: c.id, label: c.label, status: 'pending' }))
  )
  const [running, setRunning] = useState(false)
  const [done, setDone] = useState(false)

  async function runAll() {
    setRunning(true)
    const next = [...results]
    for (let i = 0; i < conflicts.length; i++) {
      try {
        await importConflictRecord(conflicts[i].id, { dry_run: false, filament_action: 'create' })
        next[i] = { ...next[i], status: 'ok' }
      } catch (e) {
        next[i] = { ...next[i], status: 'error', msg: e instanceof Error ? e.message : String(e) }
      }
      setResults([...next])
    }
    setRunning(false)
    setDone(true)
  }

  const okCount = results.filter(r => r.status === 'ok').length
  const errCount = results.filter(r => r.status === 'error').length

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 dark:bg-black/60">
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl max-w-lg w-full mx-4 p-6 space-y-4">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
          Bulk Add — {conflicts.length} record(s)
        </h2>

        {!done && !running && (
          <p className="text-sm text-gray-600 dark:text-gray-300">
            Each selected record will be imported using "create new filament" as the default.
            Records that need a specific link or tare override should be handled individually.
          </p>
        )}

        <div className="space-y-1 max-h-64 overflow-y-auto">
          {results.map(r => (
            <div key={r.id} className="flex items-center gap-2 text-sm py-0.5">
              <span className={`w-2 h-2 rounded-full shrink-0 ${
                r.status === 'ok' ? 'bg-emerald-500'
                : r.status === 'error' ? 'bg-red-500'
                : 'bg-gray-300 dark:bg-gray-600'
              }`} />
              <span className="flex-1 text-gray-700 dark:text-gray-300 truncate">{r.label ?? `#${r.id}`}</span>
              {r.status === 'ok' && <span className="text-xs text-emerald-600 dark:text-emerald-400">imported</span>}
              {r.status === 'error' && <span className="text-xs text-red-600 dark:text-red-400 truncate max-w-[12rem]">{r.msg}</span>}
            </div>
          ))}
        </div>

        {done && (
          <p className="text-sm font-medium">
            Done: <span className="text-emerald-600 dark:text-emerald-400">{okCount} imported</span>
            {errCount > 0 && <>, <span className="text-red-600 dark:text-red-400">{errCount} failed</span></>}
          </p>
        )}

        <div className="flex gap-2 justify-end">
          {!done && (
            <button
              onClick={runAll}
              disabled={running}
              className="px-4 py-1.5 bg-emerald-600 text-white rounded text-sm font-medium hover:bg-emerald-700 disabled:opacity-50"
            >
              {running ? 'Importing…' : 'Import all'}
            </button>
          )}
          <button
            onClick={() => { onDone() }}
            className="px-3 py-1.5 bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-200 rounded text-sm font-medium hover:bg-gray-300 dark:hover:bg-gray-600"
          >
            {done ? 'Close' : 'Cancel'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function Conflicts() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [tab, setTab] = useState<'open' | 'resolved'>('open')
  const { data, loading, error, reload } = useApi(() => getConflicts(tab), [tab])

  const [selected, setSelected] = useState<number[]>([])
  const [bulkRes, setBulkRes] = useState<Resolution>('spoolman')
  const [bulking, setBulking] = useState(false)
  const [typeFilter, setTypeFilter] = useState<ConflictType | 'all'>('all')
  const [sortKey, setSortKey] = useState<SortKey>('detected')
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set())
  const [highlightId, setHighlightId] = useState<number | null>(null)
  const highlightHandledRef = useRef(false)
  const [notFoundId, setNotFoundId] = useState<number | null>(null)
  const [showBulkAdd, setShowBulkAdd] = useState(false)

  const allRows: ConflictResponse[] = data ?? []

  // Handle the ?highlight=<id> deep-link from Synced Records conflict rows.
  // Runs once per page load (after data arrives) — expand + scroll + briefly highlight.
  const clearHighlight = useCallback(() => {
    setHighlightId(null)
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      next.delete('highlight')
      return next
    }, { replace: true })
  }, [setSearchParams])

  useEffect(() => {
    if (loading || highlightHandledRef.current) return
    const raw = searchParams.get('highlight')
    if (!raw) return

    const targetId = parseInt(raw, 10)
    if (isNaN(targetId)) {
      highlightHandledRef.current = true
      clearHighlight()
      return
    }

    // Only handle once — even if data reloads after resolve
    highlightHandledRef.current = true

    const found = allRows.find(c => c.id === targetId)
    if (!found) {
      // Conflict not in the open list — may already be resolved or not exist
      setNotFoundId(targetId)
      clearHighlight()
      return
    }

    // Expand the row, highlight it, then scroll to it
    setExpandedIds(prev => new Set([...prev, targetId]))
    setHighlightId(targetId)

    // Scroll after a brief render tick so the expanded row is in the DOM
    requestAnimationFrame(() => {
      const el = document.querySelector(`[data-conflict-id="${targetId}"]`)
      if (el && typeof (el as HTMLElement).scrollIntoView === 'function') {
        ;(el as HTMLElement).scrollIntoView({ behavior: 'smooth', block: 'center' })
      }
    })

    // Remove the highlight ring after 2.5 s so it's a flash, not permanent
    const timer = setTimeout(() => {
      clearHighlight()
    }, 2500)
    return () => clearTimeout(timer)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, allRows.length])

  // Counts per type — only types present in the current tab's data
  const typeCounts: { type: ConflictType; label: string; count: number }[] = TYPE_ORDER
    .map(t => ({ type: t, label: TYPE_LABELS[t], count: allRows.filter(c => classifyConflict(c) === t).length }))
    .filter(entry => entry.count > 0)

  // If the active filter has no rows (e.g. after resolving the last of a type), fall back to 'all'
  const activeFilter: ConflictType | 'all' =
    typeFilter !== 'all' && !typeCounts.find(e => e.type === typeFilter)
      ? 'all'
      : typeFilter

  const filtered: ConflictResponse[] =
    activeFilter === 'all' ? allRows : allRows.filter(c => classifyConflict(c) === activeFilter)

  const rows: ConflictResponse[] = useMemo(() => {
    const copy = [...filtered]
    if (sortKey === 'detected') {
      copy.sort((a, b) => b.detected_at.localeCompare(a.detected_at))
    } else if (sortKey === 'type') {
      copy.sort((a, b) => TYPE_ORDER.indexOf(classifyConflict(a)) - TYPE_ORDER.indexOf(classifyConflict(b)))
    } else if (sortKey === 'label') {
      copy.sort((a, b) => {
        const la = (a.label ?? `SM #${a.spoolman_id}`).toLowerCase()
        const lb = (b.label ?? `SM #${b.spoolman_id}`).toLowerCase()
        return la.localeCompare(lb)
      })
    }
    return copy
  }, [filtered, sortKey])

  function toggleExpand(id: number) {
    setExpandedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function expandAll() {
    setExpandedIds(new Set(rows.map(r => r.id)))
  }

  function collapseAll() {
    setExpandedIds(new Set())
  }

  async function handleBulk() {
    if (selected.length === 0) return
    setBulking(true)
    try {
      await bulkResolveConflicts({ ids: selected, resolution: bulkRes })
      setSelected([])
      void reload()
    } catch (e) {
      console.error(e)
    } finally {
      setBulking(false)
    }
  }

  function toggleSelect(id: number) {
    setSelected(s => s.includes(id) ? s.filter(x => x !== id) : [...s, id])
  }

  // Selected importable conflicts for bulk-add
  const selectedImportable = selected
    .map(id => allRows.find(c => c.id === id))
    .filter((c): c is ConflictResponse => c != null && isImportable(c))

  return (
    <div className="p-8 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Conflicts</h1>
        <div className="flex gap-2">
          {(['open', 'resolved'] as const).map(t => (
            <button
              key={t}
              onClick={() => { setTab(t); setSelected([]); setExpandedIds(new Set()) }}
              className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
                tab === t
                  ? 'bg-indigo-600 text-white'
                  : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
              }`}
            >
              {t.charAt(0).toUpperCase() + t.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* Info banner — explain what Resolve does */}
      <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg px-4 py-3 text-sm text-blue-800 dark:text-blue-300 space-y-1">
        <p>
          <strong>Resolving a conflict writes your chosen value to both systems and removes it from the queue.</strong>{' '}
          For cross-system conflicts the picked value is applied to Spoolman and Filament DB and both snapshots
          are refreshed, so it does not re-queue next cycle. <strong>Deletion</strong> conflicts remove the bridge mapping.{' '}
          <strong>Master divergence</strong> conflicts apply changes upstream when you choose an action.{' '}
          <strong>New spool / filament</strong> conflicts can be imported directly via the "Add" button.
        </p>
      </div>

      {loading && <p className="text-gray-500 dark:text-gray-400">Loading…</p>}
      {error && <p className="text-red-600 dark:text-red-400">{error}</p>}

      {/* Filter bar + Sort + Expand controls */}
      {!loading && !error && allRows.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          {typeCounts.length > 1 && (
            <>
              <button
                onClick={() => { setTypeFilter('all'); setSelected([]) }}
                className={`px-3 py-1.5 rounded-full text-sm font-medium transition-colors ${
                  activeFilter === 'all'
                    ? 'bg-gray-800 dark:bg-gray-200 text-white dark:text-gray-900'
                    : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                }`}
              >
                All ({allRows.length})
              </button>
              {typeCounts.map(({ type, label, count }) => (
                <span key={type} className="inline-flex items-center">
                  <button
                    onClick={() => { setTypeFilter(type); setSelected([]) }}
                    className={`px-3 py-1.5 rounded-full text-sm font-medium transition-colors ${
                      activeFilter === type
                        ? 'bg-gray-800 dark:bg-gray-200 text-white dark:text-gray-900'
                        : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                    }`}
                  >
                    {label} ({count})
                  </button>
                  {type === 'master_divergence' && (
                    <HelpTip
                      text="A Spoolman value would override a setting this variant inherits from its Filament DB parent. Resolving applies your chosen action upstream."
                      learnMoreHref="/docs/conflicts"
                    />
                  )}
                </span>
              ))}
              <span className="w-px h-5 bg-gray-200 dark:bg-gray-600 mx-1" />
            </>
          )}

          {/* Sort control */}
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-gray-500 dark:text-gray-400">Sort:</span>
            {([
              ['detected', 'Newest'],
              ['type', 'Type'],
              ['label', 'Label'],
            ] as [SortKey, string][]).map(([key, lbl]) => (
              <button
                key={key}
                onClick={() => setSortKey(key)}
                className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                  sortKey === key
                    ? 'bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300'
                    : 'bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-600'
                }`}
              >
                {lbl}
              </button>
            ))}
          </div>

          {rows.length > 1 && (
            <>
              <span className="w-px h-5 bg-gray-200 dark:bg-gray-600 mx-1" />
              <button
                onClick={expandAll}
                className="px-2.5 py-1 rounded text-xs font-medium bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-600"
              >
                Expand all
              </button>
              <button
                onClick={collapseAll}
                className="px-2.5 py-1 rounded text-xs font-medium bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-600"
              >
                Collapse all
              </button>
            </>
          )}
        </div>
      )}

      {/* Bulk action bar */}
      {tab === 'open' && selected.length > 0 && (
        <div className="space-y-2">
          {/* Bulk Add — shown when at least one selected is importable */}
          {selectedImportable.length > 0 && (
            <div className="flex items-center gap-3 bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded p-3">
              <span className="text-sm text-emerald-700 dark:text-emerald-300">
                {selectedImportable.length} importable selected
              </span>
              <button
                onClick={() => setShowBulkAdd(true)}
                className="px-4 py-1 bg-emerald-600 text-white rounded text-sm font-medium hover:bg-emerald-700"
              >
                Add selected
              </button>
              <HelpTip text="Bulk-imports each selected new-spool or new-filament conflict using 'create' as the filament action. For link-to-existing or custom tare, use the individual Add flow instead." />
            </div>
          )}

          {/* Bulk resolve (dismiss) */}
          <div className="flex items-center gap-3 bg-indigo-50 dark:bg-indigo-900/20 border border-indigo-200 dark:border-indigo-800 rounded p-3">
            <span className="text-sm text-indigo-700 dark:text-indigo-300">{selected.length} selected</span>
            {(['spoolman', 'filamentdb'] as const).map(r => (
              <button
                key={r}
                onClick={() => setBulkRes(r)}
                className={`px-3 py-1 rounded text-sm font-medium ${
                  bulkRes === r
                    ? 'bg-indigo-600 text-white'
                    : 'bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200'
                }`}
              >
                Use {r}
              </button>
            ))}
            <HelpTip text="Records the choice only — no values are written upstream. Make the actual edit in the system you chose, and sync propagates it." />
            <button
              onClick={handleBulk}
              disabled={bulking}
              className="px-4 py-1 bg-indigo-600 text-white rounded text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
            >
              {bulking ? 'Resolving…' : 'Bulk resolve'}
            </button>
          </div>
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && rows.length === 0 && (
        <p className="text-gray-500 dark:text-gray-400">
          {activeFilter === 'all'
            ? `No ${tab} conflicts.`
            : `No ${tab} ${TYPE_LABELS[activeFilter].toLowerCase()} conflicts.`}
        </p>
      )}

      {/* Not-found notice when deep-link target is already resolved or missing */}
      {notFoundId != null && (
        <div className="flex items-center justify-between bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700 rounded-lg px-4 py-2 text-sm text-amber-700 dark:text-amber-300">
          <span>Conflict #{notFoundId} was not found in the open queue — it may already be resolved.</span>
          <button
            onClick={() => setNotFoundId(null)}
            className="ml-4 text-amber-500 dark:text-amber-400 hover:text-amber-700 dark:hover:text-amber-200 font-medium text-xs"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Conflict rows */}
      <div className="space-y-2">
        {rows.map(c => (
          <CollapsibleConflict
            key={c.id}
            conflict={c}
            expanded={expandedIds.has(c.id)}
            onToggle={() => toggleExpand(c.id)}
            onResolved={reload}
            tab={tab}
            selected={selected.includes(c.id)}
            onSelect={() => toggleSelect(c.id)}
            highlighted={highlightId === c.id}
          />
        ))}
      </div>

      {/* Bulk Add modal */}
      {showBulkAdd && (
        <BulkAddModal
          conflicts={selectedImportable}
          onDone={() => { setShowBulkAdd(false); setSelected([]); void reload() }}
          onCancel={() => setShowBulkAdd(false)}
        />
      )}
    </div>
  )
}
