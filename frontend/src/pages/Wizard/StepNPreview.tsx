import { useState, useEffect } from 'react'
import { getWizardPreview, getConfig, postWizardContainerNameOverrides } from '../../api/client'
import { useApi } from '../../api/hooks'
import { DeepLinks } from '../../components/DeepLinks'
import { HelpTip } from '../../components/HelpTip'
import type { PlannedWrite, ContainerNameOverride, NameCollisionEntry } from '../../api/types'
import type { WizardCtx } from './index'

type FlagKey = 'name_collision' | 'empty_active' | 'default_tare' | 'variant_group'
type PlannedWritesFilter = 'all' | 'filamentdb' | 'spoolman'

const FLAG_LABELS: Record<FlagKey, string> = {
  name_collision: 'Name collisions',
  empty_active: 'Empty active spools',
  default_tare: 'Default tare used',
  variant_group: 'Variant groups',
}

function emptyActiveLabel(neverImportEmpties: boolean): string {
  return neverImportEmpties
    ? "Empty/archived spools (skipped — 'Never import empties' is on)"
    : 'Empty/archived spools (will be imported; archived → retired)'
}

export default function StepNPreview({ next, prev, goTo }: WizardCtx) {
  const { data, loading, error } = useApi(getWizardPreview)
  const { data: config } = useApi(getConfig)
  const [open, setOpen] = useState<Set<FlagKey>>(new Set())
  const [plannedWritesFilter, setPlannedWritesFilter] = useState<PlannedWritesFilter>('all')

  // Container name overrides: cluster_key → {name_override, skip}
  // Hydrated from the backend's saved state on load; updated inline.
  const [containerOverrides, setContainerOverrides] = useState<Record<string, ContainerNameOverride>>({})
  const [savingOverrides, setSavingOverrides] = useState(false)

  // Hydrate containerOverrides from backend when data loads
  useEffect(() => {
    if (!data) return
    const saved: Record<string, ContainerNameOverride> = {}
    for (const o of data.container_name_overrides ?? []) {
      saved[o.cluster_key] = o
    }
    setContainerOverrides(saved)
  }, [data])

  function toggle(key: FlagKey) {
    setOpen(s => {
      const n = new Set(s)
      if (n.has(key)) n.delete(key); else n.add(key)
      return n
    })
  }

  if (loading) return <p className="text-gray-500 dark:text-gray-400">Loading preview…</p>
  if (error) return <p className="text-red-600 dark:text-red-400">{error}</p>
  if (!data) return null

  const created = data.plan_rows.filter(r => r.action === 'created')
  const matched = data.plan_rows.filter(r => r.action === 'updated')
  const createdFilaments = created.filter(r => r.entity_type === 'filament').length
  const createdSpools = created.filter(r => r.entity_type === 'spool').length
  const matchedFilaments = matched.filter(r => r.entity_type === 'filament').length
  const matchedSpools = matched.filter(r => r.entity_type === 'spool').length

  const isSpoolmanImport = data.direction === 'spoolman_to_filamentdb'

  async function saveContainerOverride(override: ContainerNameOverride) {
    setSavingOverrides(true)
    try {
      const updated = { ...containerOverrides, [override.cluster_key]: override }
      setContainerOverrides(updated)
      await postWizardContainerNameOverrides({ overrides: Object.values(updated) })
    } catch (e) {
      console.error('Error saving container override:', e)
    } finally {
      setSavingOverrides(false)
    }
  }

  // Shared action bar — rendered at top and bottom of this long step
  const actionBar = (
    <div className="flex justify-between">
      <button onClick={prev} className="px-5 py-2 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 rounded text-sm font-medium hover:bg-gray-200 dark:hover:bg-gray-600">
        ← Back
      </button>
      <button onClick={next} className="px-5 py-2 bg-indigo-600 text-white rounded text-sm font-medium hover:bg-indigo-700">
        Next →
      </button>
    </div>
  )

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-200">Preview (dry run)</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
          A read-only preview of what the initial sync would do. Nothing is written to either system.
        </p>
      </div>

      {/* Top action bar */}
      {actionBar}

      {!isSpoolmanImport && (
        <div className="bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-700 rounded p-4 text-sm text-gray-600 dark:text-gray-300">
          The reconcile preview is currently available for the Spoolman → Filament DB import
          direction. The summary below reflects your selected direction
          ({data.direction.replace(/_/g, ' ')}).
        </div>
      )}

      {/* Plan summary */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          { label: 'Filaments created', value: createdFilaments, color: 'text-green-600' },
          { label: 'Spools created', value: createdSpools, color: 'text-green-600' },
          { label: 'Filaments matched', value: matchedFilaments, color: 'text-blue-600' },
          { label: 'Spools matched', value: matchedSpools, color: 'text-blue-600' },
        ].map(c => (
          <div key={c.label} className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-3 text-center">
            <p className="text-xs text-gray-500 dark:text-gray-400">{c.label}</p>
            <p className={`text-2xl font-bold ${c.color}`}>{c.value}</p>
          </div>
        ))}
      </div>

      {/* Flag counts at a glance */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {(Object.keys(FLAG_LABELS) as FlagKey[]).map(key => (
          <div key={key} className="bg-white dark:bg-gray-800 rounded-lg border border-amber-200 dark:border-amber-700 p-3 text-center">
            <p className="text-xs text-gray-500 dark:text-gray-400">{FLAG_LABELS[key]}</p>
            <p className="text-2xl font-bold text-amber-600">{data.flag_counts[key]}</p>
          </div>
        ))}
      </div>

      {/* Non-blocking notice about flagged items */}
      <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700 rounded p-4">
        <p className="text-amber-800 dark:text-amber-200 text-sm">
          The flagged items below need attention before executing. Name collisions will be recorded
          as individual failures per-record (the rest of the batch continues). Fix variant groupings
          or proceed to Execute to handle them per-record.
        </p>
      </div>

      {/* Name collisions */}
      <FlagSection
        flagKey="name_collision"
        count={data.flag_counts.name_collision}
        open={open.has('name_collision')}
        onToggle={() => toggle('name_collision')}
        tip="Names that already exist in Filament DB or repeat within this import — rename, fix grouping, or they fail per-record."
      >
        <div className="divide-y divide-gray-100 dark:divide-gray-700">
          {data.name_collisions.map((c, i) => (
            <CollisionRow
              key={i}
              collision={c}
              override={c.cluster_key ? containerOverrides[c.cluster_key] : undefined}
              saving={savingOverrides}
              onSaveOverride={saveContainerOverride}
              goTo={goTo}
            />
          ))}
        </div>
      </FlagSection>

      {/* Empty active — badge color is informational (blue) when never_import_empties=true (spools skipped),
          amber when never_import_empties=false (spools will be imported) */}
      <FlagSection
        flagKey="empty_active"
        label={emptyActiveLabel(config?.never_import_empties ?? false)}
        count={data.flag_counts.empty_active}
        open={open.has('empty_active')}
        onToggle={() => toggle('empty_active')}
        infoOnly={config?.never_import_empties ?? false}
        tip="Depleted or archived Spoolman spools. Archived spools import as retired Filament DB spools. If 'Never import empties' is on, depleted spools are skipped; archived non-empty spools still import as retired."
      >
        <div className="divide-y divide-gray-100 dark:divide-gray-700">
          {(config?.never_import_empties ?? false) && (
            <p className="px-4 py-2 text-xs text-amber-600">
              These spools are excluded from the import ("Never import empties" is on in Settings).
            </p>
          )}
          {!(config?.never_import_empties ?? false) && (
            <p className="px-4 py-2 text-xs text-blue-600">
              These spools will be imported. Archived spools import as <strong>retired</strong> Filament DB spools.
              Turn on "Never import empties" in Settings to skip depleted ones.
            </p>
          )}
          {data.empty_active.map((e, i) => (
            <div key={i} className="px-4 py-2 text-sm flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 min-w-0">
                <span className="text-gray-700 dark:text-gray-200">{e.name ?? `Spool #${e.spoolman_spool_id}`}</span>
                {e.archived && (
                  <span className="inline-flex px-1.5 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-700 shrink-0">
                    archived → imports as retired
                  </span>
                )}
              </div>
              <DeepLinks
                spoolmanSpoolId={e.spoolman_spool_id}
                spoolmanFilamentId={e.spoolman_filament_id}
              />
            </div>
          ))}
        </div>
      </FlagSection>

      {/* Default tare */}
      <FlagSection
        flagKey="default_tare"
        count={data.flag_counts.default_tare}
        open={open.has('default_tare')}
        onToggle={() => toggle('default_tare')}
        tip="No reel weight found anywhere — 200 g assumed; fix per-group in Variances."
      >
        <div className="divide-y divide-gray-100 dark:divide-gray-700">
          {data.default_tare.map((t, i) => (
            <div key={i} className="px-4 py-2 text-sm flex items-center justify-between gap-3">
              <div>
                <span className="text-gray-700 dark:text-gray-200">{t.name ?? `Spool #${t.spoolman_spool_id}`}</span>
                <span className="ml-2 text-xs text-gray-500 dark:text-gray-400">
                  gross {t.planned_gross} g (tare {t.default_tare_used} g default)
                </span>
              </div>
              <DeepLinks
                spoolmanSpoolId={t.spoolman_spool_id}
                spoolmanFilamentId={t.spoolman_filament_id}
              />
            </div>
          ))}
        </div>
      </FlagSection>

      {/* Variant groups */}
      <FlagSection
        flagKey="variant_group"
        count={data.flag_counts.variant_group}
        open={open.has('variant_group')}
        onToggle={() => toggle('variant_group')}
        tip="Parent/variant trees this import will create."
      >
        <div className="divide-y divide-gray-100 dark:divide-gray-700">
          {data.variant_groups.map((g, i) => (
            <div key={i} className="px-4 py-2 text-sm">
              <div className="flex items-center gap-2">
                <span className="font-medium text-gray-800 dark:text-gray-100">{g.base_name}</span>
                {g.vendor && <span className="text-xs text-gray-500 dark:text-gray-400">{g.vendor}</span>}
                {g.material && <span className="text-xs text-gray-400 dark:text-gray-500">{g.material}</span>}
              </div>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                {g.sm_filament_ids.length} filaments: {g.sm_filament_ids.join(', ')}
              </p>
            </div>
          ))}
        </div>
      </FlagSection>

      {/* Phase 4: Planned writes — structured pre-flight write summary */}
      {isSpoolmanImport && (data.planned_writes?.length ?? 0) > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300">
              Planned writes
              <span className="ml-2 text-xs text-gray-400 dark:text-gray-500">({data.planned_writes.length} total)</span>
            </h3>
            {/* Filter chips */}
            <div className="flex gap-1">
              {(['all', 'filamentdb', 'spoolman'] as const).map(f => (
                <button
                  key={f}
                  onClick={() => setPlannedWritesFilter(f)}
                  className={`px-2.5 py-1 text-xs rounded-full border font-medium transition-colors ${
                    plannedWritesFilter === f
                      ? 'bg-indigo-600 text-white border-indigo-600'
                      : 'bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-300 border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700'
                  }`}
                >
                  {f === 'all' ? 'All' : f === 'filamentdb' ? 'Filament DB' : 'Spoolman'}
                  {f !== 'all' && (
                    <span className="ml-1 text-xs opacity-70">
                      ({data.planned_writes.filter(w => w.system === f).length})
                    </span>
                  )}
                </button>
              ))}
            </div>
          </div>
          <PlannedWritesList
            writes={data.planned_writes}
            filter={plannedWritesFilter}
          />
        </div>
      )}

      {/* Bottom action bar */}
      {actionBar}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Container-collision row with editable rename/skip (item 4)
// ---------------------------------------------------------------------------

function CollisionRow({
  collision,
  override,
  saving,
  onSaveOverride,
  goTo,
}: {
  collision: NameCollisionEntry
  override: ContainerNameOverride | undefined
  saving: boolean
  onSaveOverride: (o: ContainerNameOverride) => void
  goTo: (step: number) => void
}) {
  const [nameEdit, setNameEdit] = useState(
    override?.name_override ?? collision.proposed_name ?? collision.normalized_name
  )
  const skipped = override?.skip ?? false

  // For container collisions: show editable rename + skip
  if (collision.is_container_collision && collision.cluster_key) {
    const clusterKey = collision.cluster_key
    // Check if the edited name still collides vs existing
    const stillCollides = collision.vs_existing && nameEdit.trim() === (collision.proposed_name ?? collision.normalized_name)

    return (
      <div className="px-4 py-3 text-sm">
        <div className="flex items-start gap-2 mb-2">
          <span className="inline-flex px-1.5 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-700 shrink-0 mt-0.5">
            Container
          </span>
          <div className="min-w-0">
            <span className="font-medium text-gray-800 dark:text-gray-100">
              {collision.proposed_name ?? collision.normalized_name}
            </span>
            <p className="mt-0.5 text-xs text-amber-700 dark:text-amber-400">
              {collision.vs_existing
                ? 'This container name already exists in Filament DB — rename it or skip this cluster.'
                : 'Two clusters in this batch would produce the same container name — rename one.'}
            </p>
          </div>
          <div className="flex items-center gap-1.5 shrink-0 ml-auto">
            {collision.vs_existing && (
              <span className="inline-flex px-1.5 py-0.5 rounded text-xs font-medium bg-red-100 text-red-700">
                vs existing
              </span>
            )}
            {collision.intra_batch && (
              <span className="inline-flex px-1.5 py-0.5 rounded text-xs font-medium bg-orange-100 text-orange-700">
                intra-batch
              </span>
            )}
            {collision.existing_fdb_filament_id && (
              <DeepLinks filamentdbFilamentId={collision.existing_fdb_filament_id} />
            )}
            <button
              type="button"
              onClick={() => goTo(3)}
              className="px-2 py-0.5 text-xs rounded border border-indigo-300 text-indigo-600 hover:bg-indigo-50 whitespace-nowrap"
              title="Return to Variances step to fix variant grouping"
            >
              Fix variant mapping
            </button>
          </div>
        </div>
        {!skipped ? (
          <div className="flex items-center gap-2 mt-1 pl-0.5">
            <label className="text-xs text-gray-500 dark:text-gray-400 shrink-0">Rename to:</label>
            <input
              type="text"
              value={nameEdit}
              onChange={e => setNameEdit(e.target.value)}
              className={`flex-1 border rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-indigo-400 bg-white dark:bg-gray-700 text-gray-800 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 ${
                stillCollides ? 'border-red-400' : 'border-gray-300 dark:border-gray-600'
              }`}
              placeholder="New container name…"
              disabled={saving}
            />
            <button
              type="button"
              disabled={saving || !nameEdit.trim()}
              onClick={() => onSaveOverride({ cluster_key: clusterKey, name_override: nameEdit.trim(), skip: false })}
              className="px-2.5 py-1 text-xs rounded bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 shrink-0"
            >
              Save name
            </button>
            <button
              type="button"
              disabled={saving}
              onClick={() => onSaveOverride({ cluster_key: clusterKey, name_override: null, skip: true })}
              className="px-2.5 py-1 text-xs rounded border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 shrink-0"
            >
              Skip cluster
            </button>
            {stillCollides && (
              <span className="text-xs text-red-600 shrink-0">Name still collides</span>
            )}
            {override?.name_override && !stillCollides && (
              <span className="text-xs text-green-600 shrink-0">Renamed</span>
            )}
          </div>
        ) : (
          <div className="flex items-center gap-2 mt-1 pl-0.5">
            <span className="text-xs text-gray-500 dark:text-gray-400 italic">This cluster will be skipped.</span>
            <button
              type="button"
              disabled={saving}
              onClick={() => {
                const resetName = collision.proposed_name ?? collision.normalized_name
                setNameEdit(resetName)
                onSaveOverride({ cluster_key: clusterKey, name_override: null, skip: false })
              }}
              className="px-2 py-0.5 text-xs rounded border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50"
            >
              Undo skip
            </button>
          </div>
        )}
      </div>
    )
  }

  // Regular (non-container) collision
  return (
    <div className="px-4 py-3 text-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <span className="font-medium text-gray-800 dark:text-gray-100">{collision.normalized_name}</span>
          {collision.sm_filament_ids.length > 0 && (
            <span className="ml-2 text-xs text-gray-500 dark:text-gray-400">
              SM filament{collision.sm_filament_ids.length !== 1 ? 's' : ''}: {collision.sm_filament_ids.join(', ')}
            </span>
          )}
          <p className="mt-0.5 text-xs text-amber-700 dark:text-amber-400">
            {collision.vs_existing
              ? 'This name already exists in Filament DB — the create will fail with a 409. Go back to Variances to fix grouping, or this record will be skipped.'
              : 'Two items in this batch share the same name — only one will be created.'}
          </p>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {collision.vs_existing && (
            <span className="inline-flex px-1.5 py-0.5 rounded text-xs font-medium bg-red-100 text-red-700">
              vs existing
            </span>
          )}
          {collision.intra_batch && (
            <span className="inline-flex px-1.5 py-0.5 rounded text-xs font-medium bg-orange-100 text-orange-700">
              intra-batch
            </span>
          )}
          {collision.existing_fdb_filament_id && (
            <DeepLinks filamentdbFilamentId={collision.existing_fdb_filament_id} />
          )}
          <button
            type="button"
            onClick={() => goTo(3)}
            className="px-2 py-0.5 text-xs rounded border border-indigo-300 text-indigo-600 hover:bg-indigo-50 whitespace-nowrap"
            title="Return to Variances step to fix variant grouping"
          >
            Fix variant mapping
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Planned writes list component (Phase 4)
// ---------------------------------------------------------------------------

function PlannedWritesList({
  writes,
  filter,
}: {
  writes: PlannedWrite[]
  filter: PlannedWritesFilter
}) {
  const filtered = filter === 'all' ? writes : writes.filter(w => w.system === filter)
  if (filtered.length === 0) {
    return <p className="text-xs text-gray-400">No writes planned for this filter.</p>
  }
  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 divide-y divide-gray-100 dark:divide-gray-700">
      {filtered.map((w, i) => (
        <div key={i} className="px-4 py-3">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className={`inline-flex px-1.5 py-0.5 rounded text-xs font-medium ${
              w.system === 'filamentdb'
                ? 'bg-blue-100 text-blue-700'
                : 'bg-orange-100 text-orange-700'
            }`}>
              {w.system === 'filamentdb' ? 'Filament DB' : 'Spoolman'}
            </span>
            <span className={`inline-flex px-1.5 py-0.5 rounded text-xs font-medium ${
              w.action === 'create' ? 'bg-green-100 text-green-700' : 'bg-amber-100 text-amber-700'
            }`}>
              {w.action}
            </span>
            <span className="text-xs text-gray-500 dark:text-gray-400 capitalize">{w.entity_type}</span>
            <span className="text-sm text-gray-800 dark:text-gray-100 font-medium truncate">{w.target_label}</span>
          </div>
          {w.fields.length > 0 && (
            <div className="flex flex-wrap gap-x-4 gap-y-0.5 pl-1">
              {w.fields.map((f, fi) => (
                <span key={fi} className="text-xs text-gray-500 dark:text-gray-400">
                  <span className="font-medium text-gray-700 dark:text-gray-300">{f.name}</span>
                  {f.old != null && (
                    <span className="text-gray-400 dark:text-gray-500"> {String(f.old)} →</span>
                  )}
                  {' '}
                  <span className="text-gray-800 dark:text-gray-200">{f.new != null ? String(f.new) : '—'}</span>
                </span>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function FlagSection({
  flagKey, label, count, open, onToggle, infoOnly, tip, children,
}: {
  flagKey: FlagKey
  label?: string
  count: number
  open: boolean
  onToggle: () => void
  infoOnly?: boolean
  tip?: string
  children: React.ReactNode
}) {
  const displayLabel = label ?? FLAG_LABELS[flagKey]
  const badgeClass = count > 0
    ? (infoOnly ? 'bg-blue-100 text-blue-700' : 'bg-amber-100 text-amber-700')
    : 'bg-gray-100 text-gray-500'
  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
      <button
        onClick={onToggle}
        disabled={count === 0}
        className="w-full flex items-center justify-between px-4 py-3 text-left disabled:opacity-60"
      >
        <span className="inline-flex items-center font-medium text-gray-800 dark:text-gray-200">
          {displayLabel}
          {tip && <HelpTip text={tip} />}
        </span>
        <span className="flex items-center gap-2">
          <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${badgeClass}`}>
            {count}
          </span>
          {count > 0 && <span className="text-gray-400 dark:text-gray-500 text-xs">{open ? '▲' : '▼'}</span>}
        </span>
      </button>
      {open && count > 0 && <div className="border-t border-gray-100 dark:border-gray-700">{children}</div>}
    </div>
  )
}
