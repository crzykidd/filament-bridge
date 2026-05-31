import { useState } from 'react'
import { getWizardPreview } from '../../api/client'
import { useApi } from '../../api/hooks'
import { DeepLinks } from '../../components/DeepLinks'
import type { WizardCtx } from './index'

type FlagKey = 'name_collision' | 'empty_active' | 'default_tare' | 'variant_group'

const FLAG_LABELS: Record<FlagKey, string> = {
  name_collision: 'Name collisions',
  empty_active: 'Empty active spools',
  default_tare: 'Default tare used',
  variant_group: 'Variant groups',
}

export default function StepNPreview({ next, prev }: WizardCtx) {
  const { data, loading, error } = useApi(getWizardPreview)
  const [open, setOpen] = useState<Set<FlagKey>>(new Set())

  function toggle(key: FlagKey) {
    setOpen(s => {
      const n = new Set(s)
      if (n.has(key)) n.delete(key); else n.add(key)
      return n
    })
  }

  if (loading) return <p className="text-gray-500">Loading preview…</p>
  if (error) return <p className="text-red-600">{error}</p>
  if (!data) return null

  const created = data.plan_rows.filter(r => r.action === 'created')
  const matched = data.plan_rows.filter(r => r.action === 'updated')
  const createdFilaments = created.filter(r => r.entity_type === 'filament').length
  const createdSpools = created.filter(r => r.entity_type === 'spool').length
  const matchedFilaments = matched.filter(r => r.entity_type === 'filament').length
  const matchedSpools = matched.filter(r => r.entity_type === 'spool').length

  const isSpoolmanImport = data.direction === 'spoolman_to_filamentdb'

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-gray-800">Preview (dry run)</h2>
        <p className="text-sm text-gray-500 mt-1">
          A read-only preview of what the initial sync would do. Nothing is written to either system.
        </p>
      </div>

      {!isSpoolmanImport && (
        <div className="bg-gray-50 border border-gray-200 rounded p-4 text-sm text-gray-600">
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
          <div key={c.label} className="bg-white rounded-lg border border-gray-200 p-3 text-center">
            <p className="text-xs text-gray-500">{c.label}</p>
            <p className={`text-2xl font-bold ${c.color}`}>{c.value}</p>
          </div>
        ))}
      </div>

      {/* Flag counts at a glance */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {(Object.keys(FLAG_LABELS) as FlagKey[]).map(key => (
          <div key={key} className="bg-white rounded-lg border border-amber-200 p-3 text-center">
            <p className="text-xs text-gray-500">{FLAG_LABELS[key]}</p>
            <p className="text-2xl font-bold text-amber-600">{data.flag_counts[key]}</p>
          </div>
        ))}
      </div>

      {/* Non-blocking notice about future decision UI */}
      <div className="bg-amber-50 border border-amber-200 rounded p-4">
        <p className="text-amber-800 text-sm">
          The flagged items below need a human decision before they can be reconciled. Surfacing
          them here is read-only — resolving them will arrive in a later release. You can still
          proceed to Execute; flagged items are handled per-record there.
        </p>
      </div>

      {/* Name collisions */}
      <FlagSection
        flagKey="name_collision"
        count={data.flag_counts.name_collision}
        open={open.has('name_collision')}
        onToggle={() => toggle('name_collision')}
      >
        <div className="divide-y divide-gray-100">
          {data.name_collisions.map((c, i) => (
            <div key={i} className="px-4 py-2 text-sm flex items-center justify-between gap-3">
              <div>
                <span className="font-medium text-gray-800">{c.normalized_name}</span>
                <span className="ml-2 text-xs text-gray-500">
                  SM filament{c.sm_filament_ids.length !== 1 ? 's' : ''}: {c.sm_filament_ids.join(', ')}
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                {c.vs_existing && (
                  <span className="inline-flex px-1.5 py-0.5 rounded text-xs font-medium bg-red-100 text-red-700">
                    vs existing
                  </span>
                )}
                {c.intra_batch && (
                  <span className="inline-flex px-1.5 py-0.5 rounded text-xs font-medium bg-orange-100 text-orange-700">
                    intra-batch
                  </span>
                )}
                {c.existing_fdb_filament_id && (
                  <DeepLinks filamentdbFilamentId={c.existing_fdb_filament_id} />
                )}
              </div>
            </div>
          ))}
        </div>
      </FlagSection>

      {/* Empty active */}
      <FlagSection
        flagKey="empty_active"
        count={data.flag_counts.empty_active}
        open={open.has('empty_active')}
        onToggle={() => toggle('empty_active')}
      >
        <div className="divide-y divide-gray-100">
          {data.empty_active.map((e, i) => (
            <div key={i} className="px-4 py-2 text-sm flex items-center justify-between gap-3">
              <span className="text-gray-700">{e.name ?? `Spool #${e.spoolman_spool_id}`}</span>
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
      >
        <div className="divide-y divide-gray-100">
          {data.default_tare.map((t, i) => (
            <div key={i} className="px-4 py-2 text-sm flex items-center justify-between gap-3">
              <div>
                <span className="text-gray-700">{t.name ?? `Spool #${t.spoolman_spool_id}`}</span>
                <span className="ml-2 text-xs text-gray-500">
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
      >
        <div className="divide-y divide-gray-100">
          {data.variant_groups.map((g, i) => (
            <div key={i} className="px-4 py-2 text-sm">
              <div className="flex items-center gap-2">
                <span className="font-medium text-gray-800">{g.base_name}</span>
                {g.vendor && <span className="text-xs text-gray-500">{g.vendor}</span>}
                {g.material && <span className="text-xs text-gray-400">{g.material}</span>}
              </div>
              <p className="text-xs text-gray-500 mt-0.5">
                {g.sm_filament_ids.length} filaments: {g.sm_filament_ids.join(', ')}
              </p>
            </div>
          ))}
        </div>
      </FlagSection>

      <div className="flex justify-between">
        <button onClick={prev} className="px-5 py-2 bg-gray-100 text-gray-700 rounded text-sm font-medium hover:bg-gray-200">
          ← Back
        </button>
        <button onClick={next} className="px-5 py-2 bg-indigo-600 text-white rounded text-sm font-medium hover:bg-indigo-700">
          Next →
        </button>
      </div>
    </div>
  )
}

function FlagSection({
  flagKey, count, open, onToggle, children,
}: {
  flagKey: FlagKey
  count: number
  open: boolean
  onToggle: () => void
  children: React.ReactNode
}) {
  return (
    <div className="bg-white rounded-lg border border-gray-200">
      <button
        onClick={onToggle}
        disabled={count === 0}
        className="w-full flex items-center justify-between px-4 py-3 text-left disabled:opacity-60"
      >
        <span className="font-medium text-gray-800">{FLAG_LABELS[flagKey]}</span>
        <span className="flex items-center gap-2">
          <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${
            count > 0 ? 'bg-amber-100 text-amber-700' : 'bg-gray-100 text-gray-500'
          }`}>
            {count}
          </span>
          {count > 0 && <span className="text-gray-400 text-xs">{open ? '▲' : '▼'}</span>}
        </span>
      </button>
      {open && count > 0 && <div className="border-t border-gray-100">{children}</div>}
    </div>
  )
}
