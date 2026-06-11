import { useState, useRef, useEffect } from 'react'
import { useBlocker, Link } from 'react-router-dom'
import { getConfig, updateConfig, setAutoSync, exportBackup, importBackup, clearSpoolmanFdbRefs, resetBridgeState, fullReset, authChangePassword, authRegenerateToken, getAuthStatus } from '../api/client'
import { useApi } from '../api/hooks'
import { BackupSafetyDialog } from '../components/BackupSafetyDialog'
import type { SyncDirection2, ConflictPolicy, VariantParentMode } from '../api/types'
import { useTheme } from '../context/ThemeContext'
import type { ThemeMode } from '../context/ThemeContext'
import { HelpTip } from '../components/HelpTip'

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

type MatConflictPolicy = Exclude<ConflictPolicy, 'newest_wins'>

function DirectionSelect({
  label,
  value,
  onChange,
  tip,
  tipHref,
}: {
  label: string
  value: SyncDirection2
  onChange: (v: SyncDirection2) => void
  tip?: string
  tipHref?: string
}) {
  const options: { value: SyncDirection2; label: string }[] = [
    { value: 'two_way', label: 'Two-way' },
    { value: 'spoolman_to_filamentdb', label: 'Spoolman → Filament DB' },
    { value: 'filamentdb_to_spoolman', label: 'Filament DB → Spoolman' },
  ]
  return (
    <div className="flex items-center justify-between py-2">
      <span className="flex items-center text-sm font-medium text-gray-700 dark:text-gray-300">
        {label}
        {tip && <HelpTip text={tip} learnMoreHref={tipHref} />}
      </span>
      <select
        value={value}
        onChange={e => onChange(e.target.value as SyncDirection2)}
        className="border border-gray-300 dark:border-gray-600 rounded px-2 py-1 text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-400"
      >
        {options.map(o => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  )
}

function WeightConflictSelect({
  value,
  direction,
  onChange,
}: {
  value: ConflictPolicy
  direction: SyncDirection2
  onChange: (v: ConflictPolicy) => void
}) {
  const options: { value: ConflictPolicy; label: string }[] = [
    { value: 'manual', label: 'Manual review' },
    { value: 'spoolman_wins', label: 'Spoolman wins' },
    { value: 'filamentdb_wins', label: 'Filament DB wins' },
    { value: 'newest_wins', label: 'Newest wins (timestamp)' },
  ]
  const disabled = direction !== 'two_way'
  return (
    <div className={`flex flex-col gap-1 py-2 ${disabled ? 'opacity-40' : ''}`}>
      <div className="flex items-center justify-between">
        <span className="flex items-center text-sm font-medium text-gray-700 dark:text-gray-300">
          On conflict
          <HelpTip
            text="Used only in two-way mode when both sides changed between syncs. Manual queues it for you; the others pick a winner automatically."
            learnMoreHref="/docs/conflicts"
          />
        </span>
        <select
          value={value}
          disabled={disabled}
          onChange={e => onChange(e.target.value as ConflictPolicy)}
          className="border border-gray-300 dark:border-gray-600 rounded px-2 py-1 text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-400 disabled:cursor-not-allowed"
        >
          {options.map(o => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </div>
      {(value === 'spoolman_wins' || value === 'filamentdb_wins' || value === 'newest_wins') &&
       direction === 'two_way' && (
        <p className="text-xs text-amber-600 dark:text-amber-400">
          Warning: auto-resolving weight conflicts can silently discard real consumption
          history. Use manual review when in doubt.
        </p>
      )}
      {value === 'newest_wins' && direction === 'two_way' && (
        <p className="text-xs text-gray-400 dark:text-gray-500">
          Newest wins compares timestamps across two separate servers — clock skew can
          produce incorrect results. Frequent syncing minimises this risk.
        </p>
      )}
    </div>
  )
}

function MatPropConflictSelect({
  value,
  direction,
  onChange,
}: {
  value: MatConflictPolicy
  direction: SyncDirection2
  onChange: (v: MatConflictPolicy) => void
}) {
  const options: { value: MatConflictPolicy; label: string }[] = [
    { value: 'manual', label: 'Manual review' },
    { value: 'spoolman_wins', label: 'Spoolman wins' },
    { value: 'filamentdb_wins', label: 'Filament DB wins' },
  ]
  const disabled = direction !== 'two_way'
  return (
    <div className={`flex items-center justify-between py-2 ${disabled ? 'opacity-40' : ''}`}>
      <span className="flex items-center text-sm font-medium text-gray-700 dark:text-gray-300">
        On conflict
        <HelpTip text="Newest-wins isn't available here — Spoolman doesn't timestamp filament edits." />
      </span>
      <select
        value={value}
        disabled={disabled}
        onChange={e => onChange(e.target.value as MatConflictPolicy)}
        className="border border-gray-300 dark:border-gray-600 rounded px-2 py-1 text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-400 disabled:cursor-not-allowed"
      >
        {options.map(o => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Appearance section
// ---------------------------------------------------------------------------

const THEME_OPTIONS: { value: ThemeMode; label: string; description: string }[] = [
  { value: 'light', label: 'Light', description: 'Always use the light theme.' },
  { value: 'dark', label: 'Dark', description: 'Always use the dark theme.' },
  { value: 'system', label: 'System', description: 'Follow your OS preference.' },
]

function AppearanceSection() {
  const { mode, setMode } = useTheme()
  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-5 space-y-3">
      <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Appearance</h2>
      <p className="text-xs text-gray-400 dark:text-gray-500">
        Choose a color theme. The preference is stored locally in your browser.
      </p>
      <div className="flex gap-2">
        {THEME_OPTIONS.map(opt => (
          <button
            key={opt.value}
            type="button"
            title={opt.description}
            onClick={() => setMode(opt.value)}
            className={`flex-1 px-3 py-2 rounded border text-sm font-medium transition-colors ${
              mode === opt.value
                ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300'
                : 'border-gray-200 dark:border-gray-600 text-gray-600 dark:text-gray-400 hover:border-gray-300 dark:hover:border-gray-500 hover:bg-gray-50 dark:hover:bg-gray-700'
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function Settings() {
  const { data, loading, error, reload } = useApi(getConfig)
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState('')

  // Two-axis state per category
  const [weightDir, setWeightDir] = useState<SyncDirection2 | null>(null)
  const [weightPolicy, setWeightPolicy] = useState<ConflictPolicy | null>(null)
  const [matDir, setMatDir] = useState<SyncDirection2 | null>(null)
  const [matPolicy, setMatPolicy] = useState<MatConflictPolicy | null>(null)
  const [newSpoolDir, setNewSpoolDir] = useState<SyncDirection2 | null>(null)

  const [threshold, setThreshold] = useState('')
  const [precision, setPrecision] = useState<number | null>(null)
  const [variantKeywords, setVariantKeywords] = useState<string | null>(null)
  const [vendorAliases, setVendorAliases] = useState<string | null>(null)
  const [colorKeywords, setColorKeywords] = useState<string | null>(null)
  const [neverImportEmpties, setNeverImportEmpties] = useState<boolean | null>(null)

  // Scheduler & Logs state
  const [syncIntervalMinutes, setSyncIntervalMinutes] = useState<number | null>(null)
  const [syncLogRetentionDays, setSyncLogRetentionDays] = useState<number | null>(null)
  const [togglingAutoSync, setTogglingAutoSync] = useState(false)
  const [autoSyncMsg, setAutoSyncMsg] = useState('')
  const [showAutoSyncBackupDialog, setShowAutoSyncBackupDialog] = useState(false)

  const [exporting, setExporting] = useState(false)
  const [importing, setImporting] = useState(false)
  const [importMsg, setImportMsg] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  // Variant parent mode state
  const [variantParentMode, setVariantParentModeState] = useState<VariantParentMode | null>(null)

  // Container parent marker state
  const [containerMarkerEnabled, setContainerMarkerEnabled] = useState<boolean | null>(null)
  const [containerMarkerText, setContainerMarkerText] = useState<string | null>(null)

  // Debug mode state
  const [debugMode, setDebugModeState] = useState<boolean | null>(null)
  const [togglingDebugMode, setTogglingDebugMode] = useState(false)
  const [showClearRefsDialog, setShowClearRefsDialog] = useState(false)
  const [clearRefsMsg, setClearRefsMsg] = useState('')
  const [clearingRefs, setClearingRefs] = useState(false)
  const [resettingState, setResettingState] = useState(false)
  const [resetStateMsg, setResetStateMsg] = useState('')
  const [showFullResetDialog, setShowFullResetDialog] = useState(false)
  const [fullResetting, setFullResetting] = useState(false)
  const [fullResetMsg, setFullResetMsg] = useState('')

  // Security section state
  const [authEnabled, setAuthEnabled] = useState(false)
  const [currentPw, setCurrentPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [changePwMsg, setChangePwMsg] = useState('')
  const [changingPw, setChangingPw] = useState(false)
  const [tokenVisible, setTokenVisible] = useState(false)
  const [tokenMsg, setTokenMsg] = useState('')
  const [regeneratingToken, setRegeneratingToken] = useState(false)
  const [togglingToken, setTogglingToken] = useState(false)
  const [tokenToggleMsg, setTokenToggleMsg] = useState('')

  // --- Unsaved-changes guard ---------------------------------------------
  const isDirty = !!data && (
    (weightDir != null && weightDir !== data.weight_sync_direction) ||
    (weightPolicy != null && weightPolicy !== data.weight_conflict_policy) ||
    (matDir != null && matDir !== data.material_properties_sync_direction) ||
    (matPolicy != null && matPolicy !== data.material_properties_conflict_policy) ||
    (newSpoolDir != null && newSpoolDir !== data.new_spool_sync_direction) ||
    (threshold !== '' && threshold !== String(data.sync_weight_threshold_grams)) ||
    (precision != null && precision !== data.weight_precision_decimals) ||
    (variantKeywords != null && variantKeywords !== (data.variant_line_keywords ?? '')) ||
    (vendorAliases != null && vendorAliases !== (data.opentag_vendor_aliases ?? '')) ||
    (colorKeywords != null && colorKeywords !== (data.opentag_color_keywords ?? '')) ||
    (neverImportEmpties != null && neverImportEmpties !== data.never_import_empties) ||
    (syncIntervalMinutes != null && syncIntervalMinutes !== Math.round(data.sync_interval_seconds / 60)) ||
    (syncLogRetentionDays != null && syncLogRetentionDays !== data.sync_log_retention_days) ||
    (variantParentMode != null && variantParentMode !== data.variant_parent_mode) ||
    (containerMarkerEnabled != null && containerMarkerEnabled !== (data.container_parent_marker !== '')) ||
    (containerMarkerText != null && containerMarkerEnabled !== false &&
      containerMarkerText !== data.container_parent_marker)
  )

  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      isDirty && currentLocation.pathname !== nextLocation.pathname,
  )
  useEffect(() => {
    if (blocker.state === 'blocked') {
      if (window.confirm('You have unsaved changes on this page. Leave without saving?')) {
        blocker.proceed()
      } else {
        blocker.reset()
      }
    }
  }, [blocker])

  useEffect(() => {
    if (!isDirty) return
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault()
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [isDirty])

  useEffect(() => {
    getAuthStatus().then(s => setAuthEnabled(s.auth_enabled)).catch(() => {})
  }, [])

  if (loading) return <div className="p-8 text-gray-500 dark:text-gray-400">Loading…</div>
  if (error) return <div className="p-8 text-red-600 dark:text-red-400">{error}</div>
  if (!data) return null

  const wDir = weightDir ?? data.weight_sync_direction
  const wPol = weightPolicy ?? data.weight_conflict_policy
  const mDir = matDir ?? data.material_properties_sync_direction
  const mPol = (matPolicy ?? data.material_properties_conflict_policy) as MatConflictPolicy
  const nsDir = newSpoolDir ?? data.new_spool_sync_direction
  const thresh = threshold !== '' ? threshold : String(data.sync_weight_threshold_grams)
  const prec = precision ?? data.weight_precision_decimals
  const vkw = variantKeywords ?? data.variant_line_keywords ?? ''
  const valiases = vendorAliases ?? data.opentag_vendor_aliases ?? ''
  const vcolorkw = colorKeywords ?? data.opentag_color_keywords ?? ''
  const neverEmpties = neverImportEmpties ?? data.never_import_empties

  const effectiveIntervalMinutes = syncIntervalMinutes ?? Math.round(data.sync_interval_seconds / 60)
  const effectiveRetentionDays = syncLogRetentionDays ?? data.sync_log_retention_days
  const showIntervalWarning = effectiveIntervalMinutes > 5

  const effectiveVariantParentMode = variantParentMode ?? data.variant_parent_mode
  const effectiveDebugMode = debugMode ?? data.debug_mode

  const savedMarker = data.container_parent_marker
  const effectiveMarkerEnabled = containerMarkerEnabled ?? (savedMarker !== '')
  const effectiveMarkerText = containerMarkerText ?? (savedMarker !== '' ? savedMarker : '(Master)')
  const effectiveMarkerValue = effectiveMarkerEnabled ? effectiveMarkerText : ''

  async function handleDebugModeToggle() {
    setTogglingDebugMode(true)
    try {
      const newValue = !effectiveDebugMode
      await updateConfig({ debug_mode: newValue })
      setDebugModeState(newValue)
      void reload()
    } catch (e) {
      console.error('Error toggling debug mode:', e)
    } finally {
      setTogglingDebugMode(false)
    }
  }

  async function doClearRefs() {
    setClearingRefs(true)
    setClearRefsMsg('')
    try {
      const result = await clearSpoolmanFdbRefs()
      setClearRefsMsg(
        `Done: ${result.cleared} spool(s) cleared${result.failed > 0 ? `, ${result.failed} failed (see logs)` : ''}.`,
      )
    } catch (e) {
      setClearRefsMsg(e instanceof Error ? e.message : 'Error clearing refs.')
    } finally {
      setClearingRefs(false)
    }
  }

  async function handleResetBridgeState() {
    const confirmed = window.confirm(
      'Reset bridge sync state?\n\n' +
      'This will clear ALL mappings, snapshots, conflicts, and the sync log — ' +
      'and reset the setup wizard so it can be re-run.\n\n' +
      'This does NOT touch Spoolman or Filament DB. Proceed?',
    )
    if (!confirmed) return
    setResettingState(true)
    setResetStateMsg('')
    try {
      const result = await resetBridgeState()
      setResetStateMsg(
        `Reset complete: ${result.filament_mappings} filament mapping(s), ` +
        `${result.spool_mappings} spool mapping(s), ` +
        `${result.snapshots} snapshot(s), ` +
        `${result.conflicts} conflict(s), ` +
        `${result.sync_log} sync log entry/entries deleted. Wizard reset.`,
      )
      void reload()
    } catch (e) {
      setResetStateMsg(e instanceof Error ? e.message : 'Error resetting state.')
    } finally {
      setResettingState(false)
    }
  }

  async function doFullReset() {
    setFullResetting(true)
    setFullResetMsg('')
    try {
      const result = await fullReset()
      let msg =
        `Reset complete: ${result.filament_mappings} filament mapping(s), ` +
        `${result.spool_mappings} spool mapping(s), ` +
        `${result.snapshots} snapshot(s), ` +
        `${result.conflicts} conflict(s), ` +
        `${result.sync_log} sync log entry/entries deleted. Wizard reset. ` +
        `Spoolman: ${result.spoolman_cleared} spool(s) cleared` +
        (result.spoolman_failed > 0 ? `, ${result.spoolman_failed} failed (see logs)` : '') +
        '.'
      if (result.spoolman_error) {
        msg += ` Spoolman error: ${result.spoolman_error}`
      }
      setFullResetMsg(msg)
      void reload()
    } catch (e) {
      setFullResetMsg(e instanceof Error ? e.message : 'Error during full reset.')
    } finally {
      setFullResetting(false)
    }
  }

  async function doEnableAutoSync() {
    setTogglingAutoSync(true)
    setAutoSyncMsg('')
    try {
      await setAutoSync({ enabled: true })
      setAutoSyncMsg('Auto-sync enabled.')
      void reload()
    } catch (e) {
      setAutoSyncMsg(e instanceof Error ? e.message : 'Error enabling auto-sync.')
    } finally {
      setTogglingAutoSync(false)
    }
  }

  async function handleAutoSyncToggle() {
    if (data.auto_sync_enabled) {
      setTogglingAutoSync(true)
      setAutoSyncMsg('')
      try {
        await setAutoSync({ enabled: false })
        setAutoSyncMsg('Auto-sync disabled.')
        void reload()
      } catch (e) {
        setAutoSyncMsg(e instanceof Error ? e.message : 'Error disabling auto-sync.')
      } finally {
        setTogglingAutoSync(false)
      }
    } else {
      setShowAutoSyncBackupDialog(true)
    }
  }

  async function handleChangePassword() {
    setChangePwMsg('')
    if (!currentPw || !newPw) { setChangePwMsg('All fields are required.'); return }
    if (newPw !== confirmPw) { setChangePwMsg('New passwords do not match.'); return }
    setChangingPw(true)
    try {
      await authChangePassword(currentPw, newPw)
      setChangePwMsg('Password changed.')
      setCurrentPw(''); setNewPw(''); setConfirmPw('')
    } catch (e) {
      setChangePwMsg(e instanceof Error ? e.message : 'Error changing password.')
    } finally {
      setChangingPw(false)
    }
  }

  async function handleRegenerateToken() {
    if (!window.confirm('Generate a new API token? The old token will stop working immediately.')) return
    setRegeneratingToken(true)
    setTokenMsg('')
    try {
      await authRegenerateToken()
      setTokenMsg('New token generated.')
      void reload()
    } catch (e) {
      setTokenMsg(e instanceof Error ? e.message : 'Error generating token.')
    } finally {
      setRegeneratingToken(false)
    }
  }

  async function handleTokenToggle() {
    setTogglingToken(true)
    setTokenToggleMsg('')
    try {
      await updateConfig({ api_token_enabled: !data.api_token_enabled })
      setTokenToggleMsg(data.api_token_enabled ? 'API token disabled.' : 'API token enabled.')
      void reload()
    } catch (e) {
      setTokenToggleMsg(e instanceof Error ? e.message : 'Error toggling token.')
    } finally {
      setTogglingToken(false)
    }
  }

  async function handleSave() {
    setSaving(true)
    setSaveMsg('')
    try {
      await updateConfig({
        weight_sync_direction: wDir,
        weight_conflict_policy: wPol,
        material_properties_sync_direction: mDir,
        material_properties_conflict_policy: mPol,
        new_spool_sync_direction: nsDir,
        sync_weight_threshold_grams: parseFloat(thresh) || undefined,
        weight_precision_decimals: prec,
        variant_line_keywords: variantKeywords ?? undefined,
        opentag_vendor_aliases: vendorAliases ?? undefined,
        opentag_color_keywords: colorKeywords ?? undefined,
        sync_interval_seconds: syncIntervalMinutes != null ? syncIntervalMinutes * 60 : undefined,
        sync_log_retention_days: syncLogRetentionDays ?? undefined,
        never_import_empties: neverImportEmpties ?? undefined,
        variant_parent_mode: variantParentMode ?? undefined,
        container_parent_marker: (containerMarkerEnabled != null || containerMarkerText != null)
          ? effectiveMarkerValue
          : undefined,
      })
      setSaveMsg('Saved.')
      void reload()
    } catch (e) {
      setSaveMsg(e instanceof Error ? e.message : 'Error saving.')
    } finally {
      setSaving(false)
    }
  }

  async function handleExport() {
    setExporting(true)
    try {
      const backup = await exportBackup()
      const blob = new Blob([JSON.stringify(backup, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `filament-bridge-backup-${new Date().toISOString().slice(0, 10)}.json`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      console.error(e)
    } finally {
      setExporting(false)
    }
  }

  async function handleImport(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setImporting(true)
    setImportMsg('')
    try {
      const text = await file.text()
      const backup = JSON.parse(text)
      const result = await importBackup(backup)
      setImportMsg(`Imported: ${result.spool_mappings} spool mappings, ${result.filament_mappings} filament mappings, ${result.conflicts} conflicts.`)
      void reload()
    } catch (e) {
      setImportMsg(e instanceof Error ? e.message : 'Import failed.')
    } finally {
      setImporting(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  // Shared class fragments
  const inputCls = 'border border-gray-300 dark:border-gray-600 rounded px-2 py-1 text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-400'
  const cardCls = 'bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-5'
  const dividerCls = 'border-t border-gray-100 dark:border-gray-700'
  const labelCls = 'text-sm font-medium text-gray-700 dark:text-gray-300'
  const subTextCls = 'text-xs text-gray-500 dark:text-gray-400'
  const toggleOnCls = 'bg-indigo-600'
  const toggleOffCls = 'bg-gray-200 dark:bg-gray-600'

  return (
    <>
    <BackupSafetyDialog
      open={showAutoSyncBackupDialog}
      actionLabel="Enable auto-sync"
      onCancel={() => setShowAutoSyncBackupDialog(false)}
      onProceed={() => { setShowAutoSyncBackupDialog(false); void doEnableAutoSync() }}
    />
    <BackupSafetyDialog
      open={showClearRefsDialog}
      actionLabel="Clear Filament DB references from Spoolman"
      onCancel={() => setShowClearRefsDialog(false)}
      onProceed={() => { setShowClearRefsDialog(false); void doClearRefs() }}
    />
    {showFullResetDialog && (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 dark:bg-black/70">
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl border border-red-300 dark:border-red-700 max-w-md w-full mx-4 p-6 space-y-4">
          <h2 className="text-base font-semibold text-red-700 dark:text-red-400">Full reset — confirm</h2>
          <p className="text-sm text-gray-700 dark:text-gray-300">
            This will perform <strong>both</strong> cleanup actions at once:
          </p>
          <ul className="text-sm text-gray-700 dark:text-gray-300 list-disc pl-5 space-y-1">
            <li>Clear all bridge mappings, snapshots, conflicts, and the sync log</li>
            <li>Re-arm the setup wizard so it can be run again</li>
            <li>Blank the Filament DB cross-reference fields on every Spoolman spool</li>
          </ul>
          <p className="text-sm font-medium text-gray-800 dark:text-gray-200">
            This does <span className="underline">NOT</span> delete any records in Filament DB or Spoolman.
          </p>
          <p className="text-xs text-red-600 dark:text-red-400">
            This action is irreversible. Use only during testing with a wiped or disposable dataset.
          </p>
          <div className="flex gap-3 justify-end pt-2">
            <button
              type="button"
              onClick={() => setShowFullResetDialog(false)}
              className="px-4 py-2 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 rounded text-sm font-medium hover:bg-gray-200 dark:hover:bg-gray-600"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => { setShowFullResetDialog(false); void doFullReset() }}
              className="px-4 py-2 bg-red-600 text-white rounded text-sm font-medium hover:bg-red-700"
            >
              Full reset
            </button>
          </div>
        </div>
      </div>
    )}
    <div className="p-8 space-y-6 max-w-2xl">
      <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Settings</h1>

      {/* Appearance */}
      <AppearanceSection />

      {/* Scheduler & Logs */}
      <div className={`${cardCls} space-y-3`}>
        <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-1">Scheduler &amp; Logs</h2>

        {/* Auto-sync toggle */}
        <div className="flex items-center justify-between py-2">
          <div>
            <span className="flex items-center">
              <span className={labelCls}>Auto-sync enabled</span>
              <HelpTip text="Runs a sync cycle on the interval below. Stays off until you enable it; enabling asks you to back up first." />
            </span>
            <p className={`${subTextCls} mt-0.5`}>
              Requires the setup wizard to be completed first.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void handleAutoSyncToggle()}
            disabled={togglingAutoSync}
            className={`relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 dark:focus:ring-offset-gray-800 disabled:opacity-50 disabled:cursor-not-allowed ${
              data.auto_sync_enabled ? toggleOnCls : toggleOffCls
            }`}
            aria-pressed={data.auto_sync_enabled}
          >
            <span
              className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
                data.auto_sync_enabled ? 'translate-x-5' : 'translate-x-0'
              }`}
            />
          </button>
        </div>
        {autoSyncMsg && <p className={`text-xs text-gray-600 dark:text-gray-300`}>{autoSyncMsg}</p>}

        {/* Sync interval */}
        <div className={`flex flex-col gap-1 py-2 ${dividerCls}`}>
          <div className="flex items-center justify-between">
            <span className={labelCls}>Sync interval (minutes)</span>
            <input
              type="number"
              min="1"
              step="1"
              value={effectiveIntervalMinutes}
              onChange={e => setSyncIntervalMinutes(Math.max(1, parseInt(e.target.value, 10) || 1))}
              className={`w-24 ${inputCls} text-right`}
            />
          </div>
          {showIntervalWarning && (
            <p className="text-xs text-amber-600 dark:text-amber-400">
              Longer intervals give both systems more time to change the same record between
              syncs, raising the chance of merge conflicts.
            </p>
          )}
          <p className={subTextCls}>
            Minimum 1 minute. Takes effect immediately without a restart.
          </p>
        </div>

        {/* Sync-log retention */}
        <div className={`flex flex-col gap-1 py-2 ${dividerCls}`}>
          <div className="flex items-center justify-between">
            <span className={labelCls}>Sync-log retention (days)</span>
            <input
              type="number"
              min="0"
              step="1"
              value={effectiveRetentionDays}
              onChange={e => setSyncLogRetentionDays(Math.max(0, parseInt(e.target.value, 10) || 0))}
              className={`w-24 ${inputCls} text-right`}
            />
          </div>
          <p className={subTextCls}>
            Old sync-log rows are pruned at the start of each auto-sync cycle. Set to 0 to keep
            all entries forever.
          </p>
        </div>

        <p className={`${subTextCls} ${dividerCls} pt-3`}>
          Application logs go to the container&apos;s stdout — rotation is handled by your Docker
          logging driver.
        </p>
      </div>

      {/* Weight sync */}
      <div className={`${cardCls} space-y-1`}>
        <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">Weight sync</h2>
        <p className={`${subTextCls} mb-3`}>
          Controls which direction weight changes flow and what happens when both
          sides change between syncs.
        </p>
        <DirectionSelect
          label="Direction"
          value={wDir}
          onChange={v => {
            setWeightDir(v)
            if (v !== 'two_way') setWeightPolicy('manual')
          }}
          tip="Which side's weight changes get copied to the other. One-way ignores changes on the locked side; two-way syncs both and can conflict."
          tipHref="/docs/sync-model"
        />
        <WeightConflictSelect
          value={wPol}
          direction={wDir}
          onChange={v => setWeightPolicy(v)}
        />
      </div>

      {/* Material properties sync */}
      <div className={`${cardCls} space-y-1`}>
        <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">Material properties sync</h2>
        <p className={`${subTextCls} mb-3`}>
          Controls direction for field sync, multicolor/color, density, diameter,
          temperatures, and cost.
        </p>
        <DirectionSelect
          label="Direction"
          value={mDir}
          onChange={v => {
            setMatDir(v)
            if (v !== 'two_way') setMatPolicy('manual')
          }}
          tip="Covers material/type, density, diameter, temperatures, cost, color, and finish tags."
          tipHref="/docs/sync-model"
        />
        <MatPropConflictSelect
          value={mPol}
          direction={mDir}
          onChange={v => setMatPolicy(v)}
        />
      </div>

      {/* New spools */}
      <div className={`${cardCls} space-y-1`}>
        <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">New spools</h2>
        <p className={`${subTextCls} mb-3`}>
          Controls which newly-detected unmapped spools are automatically created in the
          other system. Two-way creates in both directions (default behavior).
        </p>
        <DirectionSelect
          label="Direction"
          value={nsDir}
          onChange={v => setNewSpoolDir(v)}
          tip="When an unmapped spool appears in one system, the bridge creates it in the other. Direction limits which side gets auto-created."
        />
        <div className={`flex items-start justify-between py-3 ${dividerCls}`}>
          <div>
            <span className="flex items-center">
              <span className={labelCls}>Never import empties</span>
              <HelpTip text="Applies to wizard imports only — the ongoing engine doesn't create records for depleted spools either way." />
            </span>
            <p className={`${subTextCls} mt-0.5`}>
              Empty/depleted spools are skipped on import; the filament definition is still imported.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setNeverImportEmpties(!neverEmpties)}
            className={`relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 dark:focus:ring-offset-gray-800 ml-4 mt-0.5 ${
              neverEmpties ? toggleOnCls : toggleOffCls
            }`}
            aria-pressed={neverEmpties}
          >
            <span
              className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
                neverEmpties ? 'translate-x-5' : 'translate-x-0'
              }`}
            />
          </button>
        </div>
      </div>

      {/* Variant parent mode */}
      <div className={`bg-white dark:bg-gray-800 rounded-lg border p-5 space-y-3 ${
        effectiveVariantParentMode === 'unset'
          ? 'border-amber-400 dark:border-amber-600'
          : 'border-gray-200 dark:border-gray-700'
      }`}>
        <div className="flex items-center justify-between">
          <span className="flex items-center gap-1">
            <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Variant parent mode</h2>
            <HelpTip
              text="How the wizard builds Filament DB's parent/variant tree from flat Spoolman filaments. Choose once before the first import; existing mappings are never changed."
              learnMoreHref="/docs/variant-parent-mode"
            />
          </span>
          {effectiveVariantParentMode === 'unset' && (
            <span className="text-xs font-medium text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 border border-amber-300 dark:border-amber-700 rounded px-2 py-0.5">
              Choose a mode before running the wizard
            </span>
          )}
        </div>
        <p className="text-xs text-gray-500 dark:text-gray-400">
          Controls how the Bulk Import Wizard builds the parent/variant structure in Filament DB
          from flat Spoolman filaments.{' '}
          <Link to="/docs/variant-parent-mode" className="text-indigo-600 dark:text-indigo-400 hover:underline">
            Read the details
          </Link>
        </p>
        <div className="space-y-2">
          {(['promote_color', 'generic_container'] as const).map(mode => (
            <label key={mode} className="flex items-start gap-3 cursor-pointer">
              <input
                type="radio"
                name="variant_parent_mode"
                value={mode}
                checked={effectiveVariantParentMode === mode}
                onChange={() => setVariantParentModeState(mode)}
                className="mt-0.5 h-4 w-4 text-indigo-600 border-gray-300 dark:border-gray-600 focus:ring-indigo-500"
              />
              <div>
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                  {mode === 'promote_color' ? 'Promote a color to parent' : 'Generic container parent'}
                </span>
                <p className={`${subTextCls} mt-0.5`}>
                  {mode === 'promote_color'
                    ? 'One color is promoted as the Filament DB parent; the others become variants. Matches the wizard\'s original behavior.'
                    : 'A colorless container is created for every group (even single-color). All colors are variants under it. Uniform structure — every color is always a child.'}
                </p>
              </div>
            </label>
          ))}
        </div>
        {effectiveVariantParentMode === 'unset' && (
          <p className="text-xs text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700 rounded p-2">
            The Bulk Import Wizard (Spoolman &rarr; Filament DB direction) will not run until you
            choose a mode and save.
          </p>
        )}

        {effectiveVariantParentMode === 'generic_container' && (
          <div className={`mt-3 pt-3 ${dividerCls} space-y-2`}>
            <div className="flex items-center gap-3">
              <input
                type="checkbox"
                id="container-marker-enabled"
                checked={effectiveMarkerEnabled}
                onChange={e => {
                  setContainerMarkerEnabled(e.target.checked)
                  if (e.target.checked && effectiveMarkerText === '') {
                    setContainerMarkerText('(Master)')
                  }
                }}
                className="rounded border-gray-300 dark:border-gray-600 text-indigo-600 focus:ring-indigo-500"
              />
              <label htmlFor="container-marker-enabled" className={`${labelCls} cursor-pointer`}>
                Append a marker to container parent names
              </label>
            </div>
            {effectiveMarkerEnabled && (
              <div className="pl-7 space-y-1">
                <input
                  type="text"
                  value={effectiveMarkerText}
                  onChange={e => setContainerMarkerText(e.target.value)}
                  placeholder="(Master)"
                  className={`${inputCls} w-48`}
                />
                <p className={subTextCls}>
                  Keeps container names distinct from their color variants (e.g. "ELEGOO PLA {effectiveMarkerText}").
                  On a name collision you can rename or skip per-record at Preview.
                </p>
              </div>
            )}
            {!effectiveMarkerEnabled && (
              <p className={`pl-7 ${subTextCls}`}>
                Containers will have no suffix (e.g. "ELEGOO PLA"). If a collision occurs you can
                rename or skip per-record at the Preview step.
              </p>
            )}
          </div>
        )}
      </div>

      {/* Other settings */}
      <div className={`${cardCls} space-y-1`}>
        <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">Other settings</h2>
        <div className="flex items-center justify-between py-3">
          <span className="flex items-center">
            <span className={labelCls}>Weight sync threshold (g)</span>
            <HelpTip text="Changes smaller than this are ignored, so net↔gross rounding doesn't cause endless tiny updates. Default 2 g." />
          </span>
          <input
            type="number"
            min="0.1"
            step="0.5"
            value={thresh}
            onChange={e => setThreshold(e.target.value)}
            className={`w-24 ${inputCls} text-right`}
          />
        </div>
        <div className="flex items-center justify-between py-3">
          <span className="flex items-center">
            <span className={labelCls}>Weight precision (decimal places)</span>
            <HelpTip text="Decimal places used when comparing and writing weights." />
          </span>
          <select
            value={prec}
            onChange={e => setPrecision(Number(e.target.value))}
            className={inputCls}
          >
            {[0, 1, 2, 3, 4].map(n => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </div>
        <div className={`flex flex-col gap-1 py-3 ${dividerCls}`}>
          <span className="flex items-center">
            <span className={labelCls}>Variant line keywords</span>
            <HelpTip text="Used by the wizard when grouping colors into variant lines. Changes apply to the next wizard run." />
          </span>
          <input
            type="text"
            value={vkw}
            onChange={e => setVariantKeywords(e.target.value)}
            placeholder="silk, matte, rapid, …"
            className={inputCls}
          />
          <span className={subTextCls}>
            Words that mark a distinct variant line, e.g. <code className="bg-gray-100 dark:bg-gray-700 px-1 rounded">silk, matte, rapid</code>.
            Filaments whose names contain different keywords won't be grouped together.
          </span>
        </div>
        <div className={`flex flex-col gap-1 py-3 ${dividerCls}`}>
          <span className="flex items-center">
            <span className={labelCls}>Manufacturer mappings (Spoolman → OpenTag)</span>
            <HelpTip text="Only affects the OpenTag Cleanup matcher, not sync." learnMoreHref="/docs/opentag-cleanup" />
          </span>
          <input
            type="text"
            value={valiases}
            onChange={e => setVendorAliases(e.target.value)}
            placeholder="prusa=prusament, polyterra=polymaker"
            className={inputCls}
          />
          <span className={subTextCls}>
            Maps Spoolman vendor names to OpenTag brand names for the OpenTag cleanup matcher,
            e.g. <code className="bg-gray-100 dark:bg-gray-700 px-1 rounded">prusa=prusament, polyterra=polymaker</code>. Required when the vendor
            name in Spoolman differs from the brand name used in OpenTag.
          </span>
        </div>
        <div className={`flex flex-col gap-1 py-3 ${dividerCls}`}>
          <span className={labelCls}>Color word mappings (OpenTag matcher)</span>
          <input
            type="text"
            value={vcolorkw}
            onChange={e => setColorKeywords(e.target.value)}
            placeholder="galaxy=black, cool=grey, jet=black"
            className={inputCls}
          />
          <span className={subTextCls}>
            Maps color/marketing words to canonical base colors so "Jet Black" and "Galaxy Black"
            both reduce to "black" for matching. Format: <code className="bg-gray-100 dark:bg-gray-700 px-1 rounded">keyword=base_color</code>, e.g.{' '}
            <code className="bg-gray-100 dark:bg-gray-700 px-1 rounded">galaxy=black, cool=grey</code>. Merged on top of built-in defaults — leave blank
            to use defaults only.
          </span>
        </div>
        <div className="pt-2 flex items-center gap-3">
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-2 bg-indigo-600 text-white rounded text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
          {isDirty && !saving && (
            <span className="text-xs font-medium text-amber-600 dark:text-amber-400">Unsaved changes</span>
          )}
          {saveMsg && <span className="text-sm text-gray-600 dark:text-gray-300">{saveMsg}</span>}
        </div>
      </div>

      <div className={`${cardCls} space-y-3`}>
        <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Backup</h2>
        <div className="flex gap-3 flex-wrap items-center">
          <button
            onClick={handleExport}
            disabled={exporting}
            className="px-4 py-2 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 rounded text-sm font-medium hover:bg-gray-200 dark:hover:bg-gray-600 disabled:opacity-50"
          >
            {exporting ? 'Exporting…' : 'Download backup'}
          </button>
          <label className="px-4 py-2 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 rounded text-sm font-medium hover:bg-gray-200 dark:hover:bg-gray-600 cursor-pointer">
            {importing ? 'Importing…' : 'Import backup'}
            <input
              ref={fileRef}
              type="file"
              accept=".json"
              className="hidden"
              onChange={handleImport}
              disabled={importing}
            />
          </label>
        </div>
        {importMsg && <p className="text-sm text-gray-600 dark:text-gray-300">{importMsg}</p>}
      </div>

      <div className="bg-gray-50 dark:bg-gray-800/50 rounded-lg border border-gray-200 dark:border-gray-700 p-5 text-sm text-gray-500 dark:text-gray-400 space-y-1">
        <p>Wizard completed: <strong className="text-gray-700 dark:text-gray-300">{data.wizard_completed ? 'Yes' : 'No'}</strong></p>
        {data.import_direction && (
          <p>Import direction: <strong className="text-gray-700 dark:text-gray-300">{data.import_direction}</strong></p>
        )}
      </div>

      {/* Security — only shown when AUTH_ENABLED=true */}
      {authEnabled && (
        <div className={`${cardCls} space-y-4`}>
          <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Security</h2>

          {/* Change password */}
          <div className={`space-y-2 pb-4 ${dividerCls}`}>
            <h3 className={`text-sm font-medium text-gray-700 dark:text-gray-300`}>Change password</h3>
            <div className="space-y-2 max-w-xs">
              <input
                type="password"
                placeholder="Current password"
                value={currentPw}
                onChange={e => setCurrentPw(e.target.value)}
                className={`w-full ${inputCls}`}
              />
              <input
                type="password"
                placeholder="New password"
                value={newPw}
                onChange={e => setNewPw(e.target.value)}
                className={`w-full ${inputCls}`}
              />
              <input
                type="password"
                placeholder="Confirm new password"
                value={confirmPw}
                onChange={e => setConfirmPw(e.target.value)}
                className={`w-full ${inputCls}`}
              />
              <button
                type="button"
                onClick={() => void handleChangePassword()}
                disabled={changingPw}
                className="px-4 py-2 bg-indigo-600 text-white rounded text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
              >
                {changingPw ? 'Saving…' : 'Change password'}
              </button>
              {changePwMsg && <p className="text-xs text-gray-600 dark:text-gray-300">{changePwMsg}</p>}
            </div>
          </div>

          {/* API token */}
          <div className="space-y-2">
            <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300">API token</h3>
            <p className={subTextCls}>
              Enables machine access via <code className="bg-gray-100 dark:bg-gray-700 px-1 rounded">Authorization: Bearer &lt;token&gt;</code> or{' '}
              <code className="bg-gray-100 dark:bg-gray-700 px-1 rounded">X-API-Key: &lt;token&gt;</code>. Only enable if you have an integration that needs it.
            </p>

            {/* Enable/disable toggle */}
            <div className="flex items-center justify-between py-1">
              <span className="flex items-center text-sm text-gray-700 dark:text-gray-300">
                Token authentication enabled
                <HelpTip
                  text="Lets scripts call the bridge API with Authorization: Bearer or X-API-Key instead of a login cookie."
                  learnMoreHref="/docs/security"
                />
              </span>
              <button
                type="button"
                onClick={() => void handleTokenToggle()}
                disabled={togglingToken || !data.api_token}
                title={!data.api_token ? 'Generate a token first' : undefined}
                className={`relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 dark:focus:ring-offset-gray-800 disabled:opacity-50 disabled:cursor-not-allowed ${
                  data.api_token_enabled ? toggleOnCls : toggleOffCls
                }`}
                aria-pressed={data.api_token_enabled}
              >
                <span
                  className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
                    data.api_token_enabled ? 'translate-x-5' : 'translate-x-0'
                  }`}
                />
              </button>
            </div>
            {tokenToggleMsg && <p className="text-xs text-gray-600 dark:text-gray-300">{tokenToggleMsg}</p>}

            {/* Token display */}
            {data.api_token && (
              <div className="flex items-center gap-2 mt-1">
                <code className="text-xs bg-gray-100 dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded px-2 py-1 font-mono break-all text-gray-800 dark:text-gray-200">
                  {tokenVisible ? data.api_token : '••••••••••••••••••••'}
                </code>
                <button
                  type="button"
                  onClick={() => setTokenVisible(v => !v)}
                  className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline whitespace-nowrap"
                >
                  {tokenVisible ? 'Hide' : 'Show'}
                </button>
                <button
                  type="button"
                  onClick={() => { void navigator.clipboard.writeText(data.api_token ?? '') }}
                  className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline whitespace-nowrap"
                >
                  Copy
                </button>
              </div>
            )}

            <button
              type="button"
              onClick={() => void handleRegenerateToken()}
              disabled={regeneratingToken}
              className="px-4 py-2 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 rounded text-sm font-medium hover:bg-gray-200 dark:hover:bg-gray-600 disabled:opacity-50 mt-1"
            >
              {regeneratingToken ? 'Generating…' : data.api_token ? 'Regenerate token' : 'Generate token'}
            </button>
            {tokenMsg && <p className="text-xs text-gray-600 dark:text-gray-300">{tokenMsg}</p>}
          </div>
        </div>
      )}

      {/* Debug mode */}
      <div className={`${cardCls} space-y-3`}>
        <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Debug mode</h2>
        <p className={subTextCls}>
          For development and testing only. Enables destructive reset tools below.
          Never enable in production.
        </p>
        <div className="flex items-center justify-between py-2">
          <span className={labelCls}>Debug mode enabled</span>
          <button
            type="button"
            onClick={() => void handleDebugModeToggle()}
            disabled={togglingDebugMode}
            className={`relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 dark:focus:ring-offset-gray-800 disabled:opacity-50 disabled:cursor-not-allowed ${
              effectiveDebugMode ? toggleOnCls : toggleOffCls
            }`}
            aria-pressed={effectiveDebugMode}
          >
            <span
              className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
                effectiveDebugMode ? 'translate-x-5' : 'translate-x-0'
              }`}
            />
          </button>
        </div>

        {effectiveDebugMode && (
          <div className="rounded-lg border-2 border-red-300 dark:border-red-700 bg-red-50 dark:bg-red-900/20 p-4 space-y-4 mt-2">
            <h3 className="text-sm font-semibold text-red-700 dark:text-red-400">Danger zone</h3>
            <p className="text-xs text-red-600 dark:text-red-400">
              These actions are irreversible. Use only during testing with a wiped or
              disposable dataset.
            </p>

            {/* Clear Spoolman cross-refs (Spoolman only) */}
            <div className="space-y-2">
              <p className="text-sm font-medium text-gray-800 dark:text-gray-200">
                Clear Spoolman cross-refs <span className="font-normal text-gray-500 dark:text-gray-400">(Spoolman only)</span>
              </p>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                Blanks <code className="bg-gray-100 dark:bg-gray-700 px-1 rounded">filamentdb_id</code>,{' '}
                <code className="bg-gray-100 dark:bg-gray-700 px-1 rounded">filamentdb_spool_id</code>, and{' '}
                <code className="bg-gray-100 dark:bg-gray-700 px-1 rounded">filamentdb_parent_id</code> on every Spoolman spool that has any set.
                Writes to Spoolman only — does NOT touch the bridge DB. Use "Full reset" to do both.
              </p>
              <button
                type="button"
                onClick={() => setShowClearRefsDialog(true)}
                disabled={clearingRefs}
                className="px-4 py-2 bg-red-600 text-white rounded text-sm font-medium hover:bg-red-700 disabled:opacity-50"
              >
                {clearingRefs ? 'Clearing…' : 'Clear Spoolman cross-refs (Spoolman only)'}
              </button>
              {clearRefsMsg && (
                <p className="text-xs text-gray-700 dark:text-gray-300">{clearRefsMsg}</p>
              )}
            </div>

            {/* Reset bridge DB (bridge only) */}
            <div className="space-y-2 border-t border-red-200 dark:border-red-800 pt-4">
              <p className="text-sm font-medium text-gray-800 dark:text-gray-200">
                Reset bridge DB <span className="font-normal text-gray-500 dark:text-gray-400">(bridge only)</span>
              </p>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                Clears the bridge's mappings, snapshots, conflicts, and sync log, and re-arms
                the setup wizard — does NOT touch Spoolman or Filament DB. Use "Full reset"
                to also clear the Spoolman cross-refs.
              </p>
              <button
                type="button"
                onClick={() => void handleResetBridgeState()}
                disabled={resettingState}
                className="px-4 py-2 bg-red-600 text-white rounded text-sm font-medium hover:bg-red-700 disabled:opacity-50"
              >
                {resettingState ? 'Resetting…' : 'Reset bridge DB (bridge only)'}
              </button>
              {resetStateMsg && (
                <p className="text-xs text-gray-700 dark:text-gray-300">{resetStateMsg}</p>
              )}
            </div>

            {/* Full reset (bridge DB + Spoolman links) */}
            <div className="space-y-2 border-t border-red-200 dark:border-red-800 pt-4">
              <p className="text-sm font-medium text-gray-800 dark:text-gray-200">
                Full reset <span className="font-normal text-gray-500 dark:text-gray-400">(bridge DB + Spoolman links)</span>
              </p>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                Does both cleanups at once: clears all bridge mappings/conflicts/snapshots/log,
                re-arms the setup wizard, AND blanks the Filament DB cross-reference fields on
                Spoolman spools. Does NOT delete any records in Filament DB or Spoolman.
              </p>
              <button
                type="button"
                onClick={() => setShowFullResetDialog(true)}
                disabled={fullResetting}
                className="px-4 py-2 bg-red-600 text-white rounded text-sm font-medium hover:bg-red-700 disabled:opacity-50"
              >
                {fullResetting ? 'Resetting…' : 'Full reset (bridge DB + Spoolman links)'}
              </button>
              {fullResetMsg && (
                <p className="text-xs text-gray-700 dark:text-gray-300">{fullResetMsg}</p>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
    </>
  )
}
