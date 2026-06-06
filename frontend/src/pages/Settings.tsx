import { useState, useRef } from 'react'
import { getConfig, updateConfig, exportBackup, importBackup } from '../api/client'
import { useApi } from '../api/hooks'
import type { SourceOfTruth, SyncDirection2, ConflictPolicy } from '../api/types'

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

type MatConflictPolicy = Exclude<ConflictPolicy, 'newest_wins'>

function DirectionSelect({
  label,
  value,
  onChange,
}: {
  label: string
  value: SyncDirection2
  onChange: (v: SyncDirection2) => void
}) {
  const options: { value: SyncDirection2; label: string }[] = [
    { value: 'two_way', label: 'Two-way' },
    { value: 'spoolman_to_filamentdb', label: 'Spoolman → Filament DB' },
    { value: 'filamentdb_to_spoolman', label: 'Filament DB → Spoolman' },
  ]
  return (
    <div className="flex items-center justify-between py-2">
      <span className="text-sm font-medium text-gray-700">{label}</span>
      <select
        value={value}
        onChange={e => onChange(e.target.value as SyncDirection2)}
        className="border border-gray-300 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
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
        <span className="text-sm font-medium text-gray-700">On conflict</span>
        <select
          value={value}
          disabled={disabled}
          onChange={e => onChange(e.target.value as ConflictPolicy)}
          className="border border-gray-300 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 disabled:cursor-not-allowed"
        >
          {options.map(o => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </div>
      {(value === 'spoolman_wins' || value === 'filamentdb_wins' || value === 'newest_wins') &&
       direction === 'two_way' && (
        <p className="text-xs text-amber-600">
          Warning: auto-resolving weight conflicts can silently discard real consumption
          history. Use manual review when in doubt.
        </p>
      )}
      {value === 'newest_wins' && direction === 'two_way' && (
        <p className="text-xs text-gray-400">
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
      <span className="text-sm font-medium text-gray-700">On conflict</span>
      <select
        value={value}
        disabled={disabled}
        onChange={e => onChange(e.target.value as MatConflictPolicy)}
        className="border border-gray-300 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 disabled:cursor-not-allowed"
      >
        {options.map(o => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  )
}

function SotSelect({
  label,
  value,
  onChange,
}: {
  label: string
  value: SourceOfTruth
  onChange: (v: SourceOfTruth) => void
}) {
  return (
    <div className="flex items-center justify-between py-3 border-b border-gray-100 last:border-0">
      <span className="text-sm font-medium text-gray-700">{label}</span>
      <div className="flex gap-2">
        {(['spoolman', 'filamentdb'] as SourceOfTruth[]).map(opt => (
          <button
            key={opt}
            onClick={() => onChange(opt)}
            className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
              value === opt ? 'bg-indigo-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            {opt === 'spoolman' ? 'Spoolman' : 'Filament DB'}
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

  // Legacy fields kept as-is
  const [newSpoolSot, setNewSpoolSot] = useState<SourceOfTruth | null>(null)
  const [threshold, setThreshold] = useState('')
  const [precision, setPrecision] = useState<number | null>(null)
  const [variantKeywords, setVariantKeywords] = useState<string | null>(null)

  const [exporting, setExporting] = useState(false)
  const [importing, setImporting] = useState(false)
  const [importMsg, setImportMsg] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  if (loading) return <div className="p-8 text-gray-500">Loading…</div>
  if (error) return <div className="p-8 text-red-600">{error}</div>
  if (!data) return null

  const wDir = weightDir ?? data.weight_sync_direction
  const wPol = weightPolicy ?? data.weight_conflict_policy
  const mDir = matDir ?? data.material_properties_sync_direction
  const mPol = (matPolicy ?? data.material_properties_conflict_policy) as MatConflictPolicy
  const nSot = newSpoolSot ?? data.new_spool_source_of_truth
  const thresh = threshold !== '' ? threshold : String(data.sync_weight_threshold_grams)
  const prec = precision ?? data.weight_precision_decimals
  const vkw = variantKeywords ?? data.variant_line_keywords ?? ''

  async function handleSave() {
    setSaving(true)
    setSaveMsg('')
    try {
      await updateConfig({
        weight_sync_direction: wDir,
        weight_conflict_policy: wPol,
        material_properties_sync_direction: mDir,
        material_properties_conflict_policy: mPol,
        new_spool_source_of_truth: nSot,
        sync_weight_threshold_grams: parseFloat(thresh) || undefined,
        weight_precision_decimals: prec,
        variant_line_keywords: variantKeywords ?? undefined,
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

  return (
    <div className="p-8 space-y-6 max-w-2xl">
      <h1 className="text-2xl font-bold text-gray-900">Settings</h1>

      {/* Weight sync */}
      <div className="bg-white rounded-lg border border-gray-200 p-5 space-y-1">
        <h2 className="text-sm font-semibold text-gray-700 mb-2">Weight sync</h2>
        <p className="text-xs text-gray-400 mb-3">
          Controls which direction weight changes flow and what happens when both
          sides change between syncs.
        </p>
        <DirectionSelect
          label="Direction"
          value={wDir}
          onChange={v => {
            setWeightDir(v)
            // Reset policy to manual when leaving two_way (policy is irrelevant in one-way)
            if (v !== 'two_way') setWeightPolicy('manual')
          }}
        />
        <WeightConflictSelect
          value={wPol}
          direction={wDir}
          onChange={v => setWeightPolicy(v)}
        />
      </div>

      {/* Material properties sync */}
      <div className="bg-white rounded-lg border border-gray-200 p-5 space-y-1">
        <h2 className="text-sm font-semibold text-gray-700 mb-2">Material properties sync</h2>
        <p className="text-xs text-gray-400 mb-3">
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
        />
        <MatPropConflictSelect
          value={mPol}
          direction={mDir}
          onChange={v => setMatPolicy(v)}
        />
      </div>

      {/* Other settings */}
      <div className="bg-white rounded-lg border border-gray-200 p-5 space-y-1">
        <h2 className="text-sm font-semibold text-gray-700 mb-2">Other settings</h2>
        <SotSelect label="New spools" value={nSot} onChange={v => setNewSpoolSot(v)} />
        <div className="flex items-center justify-between py-3">
          <span className="text-sm font-medium text-gray-700">Weight sync threshold (g)</span>
          <input
            type="number"
            min="0.1"
            step="0.5"
            value={thresh}
            onChange={e => setThreshold(e.target.value)}
            className="w-24 border border-gray-300 rounded px-2 py-1 text-sm text-right focus:outline-none focus:ring-2 focus:ring-indigo-400"
          />
        </div>
        <div className="flex items-center justify-between py-3">
          <span className="text-sm font-medium text-gray-700">Weight precision (decimal places)</span>
          <select
            value={prec}
            onChange={e => setPrecision(Number(e.target.value))}
            className="border border-gray-300 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
          >
            {[0, 1, 2, 3, 4].map(n => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1 py-3 border-b border-gray-100">
          <span className="text-sm font-medium text-gray-700">Variant line keywords</span>
          <input
            type="text"
            value={vkw}
            onChange={e => setVariantKeywords(e.target.value)}
            placeholder="silk, matte, rapid, …"
            className="border border-gray-300 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
          />
          <span className="text-xs text-gray-400">
            Words that mark a distinct variant line, e.g. <code>silk, matte, rapid</code>.
            Filaments whose names contain different keywords won't be grouped together.
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
          {saveMsg && <span className="text-sm text-gray-600">{saveMsg}</span>}
        </div>
      </div>

      <div className="bg-white rounded-lg border border-gray-200 p-5 space-y-3">
        <h2 className="text-sm font-semibold text-gray-700">Backup</h2>
        <div className="flex gap-3 flex-wrap items-center">
          <button
            onClick={handleExport}
            disabled={exporting}
            className="px-4 py-2 bg-gray-100 text-gray-700 rounded text-sm font-medium hover:bg-gray-200 disabled:opacity-50"
          >
            {exporting ? 'Exporting…' : 'Download backup'}
          </button>
          <label className="px-4 py-2 bg-gray-100 text-gray-700 rounded text-sm font-medium hover:bg-gray-200 cursor-pointer">
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
        {importMsg && <p className="text-sm text-gray-600">{importMsg}</p>}
      </div>

      <div className="bg-gray-50 rounded-lg border border-gray-200 p-5 text-sm text-gray-500 space-y-1">
        <p>Wizard completed: <strong>{data.wizard_completed ? 'Yes' : 'No'}</strong></p>
        {data.import_direction && (
          <p>Import direction: <strong>{data.import_direction}</strong></p>
        )}
      </div>
    </div>
  )
}
