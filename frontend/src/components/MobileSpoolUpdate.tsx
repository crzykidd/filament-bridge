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
import {
  getMobileSpool,
  getMobileLocations,
  updateMobileSpool,
  logMobileDryCycle,
  getMobilePrinters,
  getMobileSpoolAssignment,
  setMobileSpoolAssignment,
  clearMobileSpoolAssignment,
} from '../api/client'
import { useApi } from '../api/hooks'
import { BridgeApiError } from '../api/client'
import { ColorDisplay } from './ColorDisplay'
import { DeepLinks } from './DeepLinks'
import { PrintLabelButton } from './PrintLabelButton'
import type {
  MobileSpoolDetail,
  MobileWeightMode,
  MobileSpoolUpdateRequest,
  MobilePrinter,
  MobileSpoolAssignment,
} from '../api/types'

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

  // Printers + current assignment are fetched once (best-effort — never block page).
  const { data: printers } = useApi<MobilePrinter[]>(getMobilePrinters, [])
  const { data: initialAssignment, reload: reloadAssignment } = useApi<MobileSpoolAssignment | null>(
    () => getMobileSpoolAssignment(filId, spoolId),
    [filId, spoolId],
  )

  // --- Form state (initialized lazily from the loaded detail) ---------------
  const [grossInput, setGrossInput] = useState('')
  const [location, setLocation] = useState<string | null>(null)
  const [addingNewLocation, setAddingNewLocation] = useState(false)
  const [weightMode, setWeightMode] = useState<MobileWeightMode | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [savedMsg, setSavedMsg] = useState<string | null>(null)

  // Dry cycle state (lazy init from recommended values)
  const [dryTemp, setDryTemp] = useState<string | null>(null)
  const [dryDuration, setDryDuration] = useState<string | null>(null)
  const [dryNotes, setDryNotes] = useState('')
  const [drySubmitting, setDrySubmitting] = useState(false)
  const [dryErr, setDryErr] = useState<string | null>(null)
  const [drySavedMsg, setDrySavedMsg] = useState<string | null>(null)

  // Printer slot picker state
  const [selectedPrinterId, setSelectedPrinterId] = useState<string>('')
  const [selectedSlotId, setSelectedSlotId] = useState<string>('')
  const [slotSubmitting, setSlotSubmitting] = useState(false)
  const [slotErr, setSlotErr] = useState<string | null>(null)
  const [slotSavedMsg, setSlotSavedMsg] = useState<string | null>(null)

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

  // Dry cycle effective values: user input (once set) falls back to filament recommendation.
  const effectiveDryTemp = dryTemp ?? (detail.recommended_drying_temp_c != null ? String(detail.recommended_drying_temp_c) : '')
  const effectiveDryDuration = dryDuration ?? (detail.recommended_drying_time_min != null ? String(detail.recommended_drying_time_min) : '')

  async function handleLogDryCycle() {
    setDrySubmitting(true)
    setDryErr(null)
    setDrySavedMsg(null)
    try {
      const tempNum = effectiveDryTemp.trim() !== '' ? Number(effectiveDryTemp) : null
      const durNum = effectiveDryDuration.trim() !== '' ? Number(effectiveDryDuration) : null
      await logMobileDryCycle(filId, spoolId, {
        ...(tempNum != null && Number.isFinite(tempNum) ? { temp_c: tempNum } : {}),
        ...(durNum != null && Number.isFinite(durNum) ? { duration_min: durNum } : {}),
        ...(dryNotes.trim() ? { notes: dryNotes.trim() } : {}),
      })
      setDryNotes('')
      setDrySavedMsg('Dry cycle logged.')
      await reload()
    } catch (e) {
      setDryErr(e instanceof BridgeApiError ? e.message : String(e))
    } finally {
      setDrySubmitting(false)
    }
  }

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
        <dt className="text-gray-500 dark:text-gray-400">Last dried</dt>
        <dd className="text-right font-medium text-gray-900 dark:text-gray-100">
          {detail.last_dried_at
            ? new Date(detail.last_dried_at).toLocaleDateString()
            : '—'}
          {detail.dry_cycle_count != null && detail.dry_cycle_count > 0
            ? <span className="text-gray-400 dark:text-gray-500"> · {detail.dry_cycle_count} cycles</span>
            : null}
        </dd>
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

      {/* Log dry cycle — FDB-only one-way write, separate from Save */}
      <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4 space-y-3">
        <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-200">Log dry cycle</h2>
        <p className="text-xs text-gray-500 dark:text-gray-400">
          Logged immediately when you tap Log dry cycle — separate from Save.
        </p>
        <div>
          <label htmlFor="dry-temp" className={labelCls}>Temperature (°C)</label>
          <input
            id="dry-temp"
            type="text"
            inputMode="numeric"
            value={effectiveDryTemp}
            onChange={e => setDryTemp(e.target.value)}
            placeholder="e.g. 65"
            className={inputCls}
            autoComplete="off"
            data-1p-ignore="true"
            data-lpignore="true"
            data-bwignore="true"
            data-form-type="other"
          />
        </div>
        <div>
          <label htmlFor="dry-duration" className={labelCls}>Duration (minutes)</label>
          <input
            id="dry-duration"
            type="text"
            inputMode="numeric"
            value={effectiveDryDuration}
            onChange={e => setDryDuration(e.target.value)}
            placeholder="e.g. 240"
            className={inputCls}
            autoComplete="off"
            data-1p-ignore="true"
            data-lpignore="true"
            data-bwignore="true"
            data-form-type="other"
          />
        </div>
        <div>
          <label htmlFor="dry-notes" className={labelCls}>Notes (optional)</label>
          <input
            id="dry-notes"
            type="text"
            value={dryNotes}
            onChange={e => setDryNotes(e.target.value)}
            placeholder="e.g. pre-print drying"
            className={inputCls}
            autoComplete="off"
            data-1p-ignore="true"
            data-lpignore="true"
            data-bwignore="true"
            data-form-type="other"
          />
        </div>
        <div className="space-y-2">
          <button
            type="button"
            onClick={() => { void handleLogDryCycle() }}
            disabled={drySubmitting}
            className="w-full bg-teal-600 text-white rounded px-4 py-2.5 text-base font-medium hover:bg-teal-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {drySubmitting ? 'Logging…' : 'Log dry cycle'}
          </button>
          {dryErr && <p className="text-sm text-red-600 dark:text-red-400">{dryErr}</p>}
          {drySavedMsg && !dryErr && (
            <div className="bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded p-2.5 text-sm text-emerald-800 dark:text-emerald-300">
              {drySavedMsg}
            </div>
          )}
        </div>
      </div>

      {/* Printer + Slot assignment — FDB-only, one-way write, no Spoolman mirror */}
      <PrinterSlotPicker
        filId={filId}
        spoolId={spoolId}
        isRetired={detail.is_retired ?? false}
        printers={printers ?? []}
        currentAssignment={initialAssignment ?? null}
        selectedPrinterId={selectedPrinterId}
        selectedSlotId={selectedSlotId}
        onPrinterChange={pid => { setSelectedPrinterId(pid); setSelectedSlotId(''); setSlotErr(null); setSlotSavedMsg(null) }}
        onSlotChange={sid => { setSelectedSlotId(sid); setSlotErr(null); setSlotSavedMsg(null) }}
        submitting={slotSubmitting}
        err={slotErr}
        savedMsg={slotSavedMsg}
        onAssign={async () => {
          setSlotSubmitting(true)
          setSlotErr(null)
          setSlotSavedMsg(null)
          try {
            await setMobileSpoolAssignment(filId, spoolId, {
              printer_id: selectedPrinterId,
              slot_id: selectedSlotId,
            })
            setSlotSavedMsg('Assigned.')
            setSelectedPrinterId('')
            setSelectedSlotId('')
            await reloadAssignment()
          } catch (e) {
            setSlotErr(e instanceof BridgeApiError ? e.message : String(e))
          } finally {
            setSlotSubmitting(false)
          }
        }}
        onClear={async () => {
          setSlotSubmitting(true)
          setSlotErr(null)
          setSlotSavedMsg(null)
          try {
            await clearMobileSpoolAssignment(filId, spoolId)
            setSlotSavedMsg('Assignment cleared.')
            setSelectedPrinterId('')
            setSelectedSlotId('')
            await reloadAssignment()
          } catch (e) {
            setSlotErr(e instanceof BridgeApiError ? e.message : String(e))
          } finally {
            setSlotSubmitting(false)
          }
        }}
      />

      {/* Print label (LabelForge) — feature is already gated on the route here */}
      <div className="border-t border-gray-100 dark:border-gray-700 pt-4">
        <PrintLabelButton filId={filId} spoolId={spoolId} />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// PrinterSlotPicker — sub-component for the printer + slot assignment section
// ---------------------------------------------------------------------------

interface PrinterSlotPickerProps {
  filId: string
  spoolId: string
  isRetired: boolean
  printers: MobilePrinter[]
  currentAssignment: MobileSpoolAssignment | null
  selectedPrinterId: string
  selectedSlotId: string
  onPrinterChange: (printerId: string) => void
  onSlotChange: (slotId: string) => void
  submitting: boolean
  err: string | null
  savedMsg: string | null
  onAssign: () => void
  onClear: () => void
}

function PrinterSlotPicker({
  spoolId,
  isRetired,
  printers,
  currentAssignment,
  selectedPrinterId,
  selectedSlotId,
  onPrinterChange,
  onSlotChange,
  submitting,
  err,
  savedMsg,
  onAssign,
  onClear,
}: PrinterSlotPickerProps) {
  const inputCls =
    'w-full border border-gray-300 dark:border-gray-600 rounded px-3 py-2 text-base bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-400'
  const labelCls = 'block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1'

  const selectedPrinter = printers.find(p => p.printer_id === selectedPrinterId) ?? null
  const selectedSlot = selectedPrinter?.slots.find(s => s.slot_id === selectedSlotId) ?? null

  // Occupied warning: slot has a different spool loaded
  const occupiedByOther =
    selectedSlot !== null &&
    selectedSlot.spool_id !== null &&
    selectedSlot.spool_id !== spoolId

  const canAssign = !submitting && selectedPrinterId !== '' && selectedSlotId !== ''

  return (
    <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4 space-y-3">
      <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-200">Printer slot</h2>

      {/* Current assignment summary */}
      <p className="text-xs text-gray-500 dark:text-gray-400">
        {currentAssignment
          ? <>Currently: <span className="font-medium text-gray-700 dark:text-gray-300">{currentAssignment.printer_name} — {currentAssignment.slot_name}</span></>
          : 'Currently unassigned'}
      </p>

      {isRetired ? (
        <p className="text-xs text-amber-700 dark:text-amber-400">
          This spool is retired and cannot be assigned to a printer slot.
        </p>
      ) : (
        <>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            FDB-only — Spoolman has no printer-slot concept. One spool per slot; assigning displaces any current occupant.
          </p>

          {/* Printer select */}
          <div>
            <label htmlFor="slot-printer" className={labelCls}>Printer</label>
            <select
              id="slot-printer"
              value={selectedPrinterId}
              onChange={e => onPrinterChange(e.target.value)}
              className={inputCls}
              disabled={submitting || printers.length === 0}
            >
              <option value="">— Select printer —</option>
              {printers.map(p => (
                <option key={p.printer_id} value={p.printer_id}>{p.printer_name}</option>
              ))}
            </select>
          </div>

          {/* Slot select (only shown after a printer is chosen) */}
          {selectedPrinter && (
            <div>
              <label htmlFor="slot-slot" className={labelCls}>Slot</label>
              <select
                id="slot-slot"
                value={selectedSlotId}
                onChange={e => onSlotChange(e.target.value)}
                className={inputCls}
                disabled={submitting}
              >
                <option value="">— Select slot —</option>
                {selectedPrinter.slots.map(s => (
                  <option key={s.slot_id} value={s.slot_id}>
                    {s.slot_name}
                    {s.spool_id && s.spool_id !== spoolId ? ' (occupied)' : ''}
                    {s.spool_id === spoolId ? ' (current)' : ''}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Occupied-slot warning */}
          {occupiedByOther && (
            <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700 rounded p-2.5 text-xs text-amber-800 dark:text-amber-300">
              This slot is occupied by another spool (FDB spool id: {selectedSlot!.spool_id}).
              Assigning will move that spool out.
            </div>
          )}

          {/* Assign + Clear buttons */}
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onAssign}
              disabled={!canAssign}
              className="flex-1 bg-indigo-600 text-white rounded px-4 py-2 text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {submitting ? 'Saving…' : 'Assign'}
            </button>
            {currentAssignment && (
              <button
                type="button"
                onClick={onClear}
                disabled={submitting}
                className="flex-1 bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 rounded px-4 py-2 text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-600 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Clear
              </button>
            )}
          </div>
        </>
      )}

      {err && <p className="text-sm text-red-600 dark:text-red-400">{err}</p>}
      {savedMsg && !err && (
        <div className="bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded p-2.5 text-sm text-emerald-800 dark:text-emerald-300">
          {savedMsg}
        </div>
      )}
    </div>
  )
}
