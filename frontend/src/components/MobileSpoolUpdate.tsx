/**
 * MobileSpoolUpdate — the shared mobile-first spool update card.
 *
 * Reachable two ways:
 *   - the bare QR scan target (`/scan/:filId/:spoolId`, no side nav)
 *   - the in-nav "Mobile updates" page (search → select a spool)
 *
 * Reads a live `MobileSpoolDetail` and lets the user type a scale (gross) weight
 * and/or change the location, then Save → one PATCH. Net is derived as
 * `gross − tare` for a live preview. Weight-save mode defaults to the detail's
 * `weight_default_mode` (from the global setting) and is overridable per-save.
 *
 * Inline banners only (no toast system) — matching Conflicts.tsx.
 */

import { useState } from 'react'
import { getMobileSpool, getMobileLocations, updateMobileSpool } from '../api/client'
import { useApi } from '../api/hooks'
import { BridgeApiError } from '../api/client'
import { ColorDisplay } from './ColorDisplay'
import { DeepLinks } from './DeepLinks'
import { PrintLabelButton } from './PrintLabelButton'
import type { MobileSpoolDetail, MobileWeightMode, MobileSpoolUpdateRequest } from '../api/types'

interface MobileSpoolUpdateProps {
  filId: string
  spoolId: string
}

function fmtGrams(g: number | null | undefined): string {
  if (g == null) return '—'
  return `${g.toFixed(1)} g`
}

const WEIGHT_MODE_OPTIONS: { value: MobileWeightMode; label: string; hint: string }[] = [
  { value: 'direct_correction', label: 'Correct weight', hint: 'Absolute true-up' },
  { value: 'usage', label: 'Log as usage', hint: 'Records a usage entry on a decrease' },
]

export function MobileSpoolUpdate({ filId, spoolId }: MobileSpoolUpdateProps) {
  const { data, loading, error, reload } = useApi<MobileSpoolDetail>(
    () => getMobileSpool(filId, spoolId),
    [filId, spoolId],
  )
  // Locations are best-effort — failures here must not block the page.
  const { data: locations } = useApi<string[]>(getMobileLocations, [])

  // --- Form state (initialized lazily from the loaded detail) ---------------
  const [grossInput, setGrossInput] = useState('')
  const [location, setLocation] = useState<string | null>(null)
  const [addingNewLocation, setAddingNewLocation] = useState(false)
  const [weightMode, setWeightMode] = useState<MobileWeightMode | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [savedMsg, setSavedMsg] = useState<string | null>(null)

  if (loading) {
    return <p className="text-sm text-gray-500 dark:text-gray-400">Loading…</p>
  }
  if (error || !data) {
    // The feature-disabled 403 surfaces here too — show the message, don't crash.
    return <p className="text-sm text-red-600 dark:text-red-400">{error ?? 'Spool not found.'}</p>
  }

  const detail = data
  const effectiveMode: MobileWeightMode = weightMode ?? detail.weight_default_mode
  const effectiveLocation = location ?? detail.location ?? ''

  // Live net preview from the entered gross weight.
  const grossNum = grossInput.trim() === '' ? null : Number(grossInput)
  const grossValid = grossNum != null && Number.isFinite(grossNum) && grossNum >= 0
  const netPreview = grossValid ? grossNum - detail.tare : null

  const locationChanged = effectiveLocation !== (detail.location ?? '')

  // Location dropdown options: every known location (from Filament DB + Spoolman),
  // with the current value guaranteed present so it shows as selected.
  const NEW_LOCATION = '__new_location__'
  const knownLocations = locations ?? []
  const locationOptions =
    effectiveLocation && !knownLocations.includes(effectiveLocation)
      ? [effectiveLocation, ...knownLocations]
      : knownLocations
  const hasWeight = grossInput.trim() !== ''
  // Save is allowed when a valid weight is entered OR the location changed.
  // A weight that's been typed but is invalid blocks the save.
  const weightOk = hasWeight && grossValid
  const weightBlocks = hasWeight && !grossValid
  const canSave = !submitting && !weightBlocks && (weightOk || locationChanged)

  async function handleSave() {
    setSubmitting(true)
    setErr(null)
    setSavedMsg(null)
    try {
      const body: MobileSpoolUpdateRequest = { weight_mode: effectiveMode }
      if (weightOk) body.gross_grams = grossNum
      if (locationChanged) body.location = effectiveLocation
      await updateMobileSpool(filId, spoolId, body)
      // Refresh from the server (post-write agreed values) and reset the inputs.
      setGrossInput('')
      setLocation(null)
      setAddingNewLocation(false)
      setSavedMsg('Saved.')
      await reload()
    } catch (e) {
      setErr(e instanceof BridgeApiError ? e.message : String(e))
    } finally {
      setSubmitting(false)
    }
  }

  const inputCls =
    'w-full border border-gray-300 dark:border-gray-600 rounded px-3 py-2 text-base bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 placeholder:text-gray-400 dark:placeholder:text-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-400'
  const labelCls = 'block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1'

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 shadow-sm p-6 w-full max-w-md space-y-5">
      {/* Header — brand / color / number */}
      <div className="space-y-1">
        <div className="flex items-center justify-between gap-2">
          <h1 className="text-lg font-bold text-gray-900 dark:text-gray-100 leading-tight">
            {detail.brand ?? 'Unknown brand'}
          </h1>
          <span className="text-sm font-mono text-gray-500 dark:text-gray-400 shrink-0">
            #{detail.number}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <ColorDisplay colorHex={detail.color_hex} showLabel={false} />
          <span className="text-sm text-gray-700 dark:text-gray-300">
            {detail.color_name ?? '—'}
            {detail.material ? <span className="text-gray-400 dark:text-gray-500"> · {detail.material}</span> : null}
          </span>
        </div>
        <div className="flex items-center gap-3 pt-1">
          <DeepLinks
            filamentdbFilamentId={detail.filamentdb_filament_id}
            spoolmanSpoolId={detail.spoolman_spool_id}
            spoolmanFilamentId={detail.spoolman_filament_id}
          />
        </div>
      </div>

      {/* Current weight + location summary */}
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm border-t border-gray-100 dark:border-gray-700 pt-3">
        <dt className="text-gray-500 dark:text-gray-400">Current (gross)</dt>
        <dd className="text-right font-medium text-gray-900 dark:text-gray-100">{fmtGrams(detail.gross)}</dd>
        <dt className="text-gray-500 dark:text-gray-400">Current (net)</dt>
        <dd className="text-right font-medium text-gray-900 dark:text-gray-100">{fmtGrams(detail.net)}</dd>
        <dt className="text-gray-500 dark:text-gray-400">Location</dt>
        <dd className="text-right font-medium text-gray-900 dark:text-gray-100">{detail.location ?? '—'}</dd>
      </dl>

      {/* Weight input — gross / scale reading */}
      <div>
        <label htmlFor="gross" className={labelCls}>
          Scale weight (total / gross), grams
        </label>
        <input
          id="gross"
          type="text"
          inputMode="decimal"
          value={grossInput}
          onChange={e => setGrossInput(e.target.value)}
          placeholder={`e.g. ${detail.gross != null ? detail.gross.toFixed(0) : '1000'}`}
          className={inputCls}
          autoComplete="off"
          data-1p-ignore="true"
          data-lpignore="true"
          data-bwignore="true"
          data-form-type="other"
        />
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
          {hasWeight && !grossValid ? (
            <span className="text-red-600 dark:text-red-400">Enter a non-negative number.</span>
          ) : netPreview != null ? (
            <>
              Net preview: <span className="font-medium text-gray-700 dark:text-gray-300">{netPreview.toFixed(1)} g</span>{' '}
              <span className="text-gray-400 dark:text-gray-500">(− {detail.tare.toFixed(0)} g tare)</span>
            </>
          ) : (
            <>Tare (empty reel): {detail.tare.toFixed(0)} g</>
          )}
        </p>
      </div>

      {/* Weight-save mode toggle */}
      <div>
        <span className={labelCls}>On save</span>
        <div className="flex rounded overflow-hidden border border-gray-300 dark:border-gray-600">
          {WEIGHT_MODE_OPTIONS.map(opt => (
            <button
              key={opt.value}
              type="button"
              title={opt.hint}
              onClick={() => setWeightMode(opt.value)}
              className={`flex-1 py-2 text-sm font-medium transition-colors ${
                effectiveMode === opt.value
                  ? 'bg-indigo-600 text-white'
                  : 'bg-white dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-600'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Location quick-change */}
      <div>
        <label htmlFor="location" className={labelCls}>
          Location
        </label>
        {!addingNewLocation ? (
          <select
            id="location"
            value={effectiveLocation}
            onChange={e => {
              const v = e.target.value
              if (v === NEW_LOCATION) {
                setAddingNewLocation(true)
                setLocation('')
              } else {
                setLocation(v)
              }
            }}
            className={inputCls}
          >
            <option value="">— Select location —</option>
            {locationOptions.map(loc => (
              <option key={loc} value={loc}>{loc}</option>
            ))}
            <option value={NEW_LOCATION}>➕ New location…</option>
          </select>
        ) : (
          <div className="flex gap-2">
            <input
              id="location"
              type="text"
              value={effectiveLocation}
              onChange={e => setLocation(e.target.value)}
              placeholder="New location name"
              className={inputCls}
              autoFocus
              autoComplete="off"
              data-1p-ignore="true"
              data-lpignore="true"
              data-bwignore="true"
              data-form-type="other"
            />
            <button
              type="button"
              onClick={() => { setAddingNewLocation(false); setLocation(null) }}
              className="px-3 py-1.5 text-sm text-gray-600 dark:text-gray-300 whitespace-nowrap"
            >
              Cancel
            </button>
          </div>
        )}
      </div>

      {/* Save + inline banners */}
      <div className="space-y-2">
        <button
          type="button"
          onClick={() => { void handleSave() }}
          disabled={!canSave}
          className="w-full bg-indigo-600 text-white rounded px-4 py-2.5 text-base font-medium hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {submitting ? 'Saving…' : 'Save'}
        </button>
        {err && <p className="text-sm text-red-600 dark:text-red-400">{err}</p>}
        {savedMsg && !err && (
          <div className="bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded p-2.5 text-sm text-emerald-800 dark:text-emerald-300">
            {savedMsg}
          </div>
        )}
      </div>

      {/* Print label (LabelForge) — feature is already gated on the route here */}
      <div className="border-t border-gray-100 dark:border-gray-700 pt-4">
        <PrintLabelButton filId={filId} spoolId={spoolId} />
      </div>
    </div>
  )
}
