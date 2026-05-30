import { useState } from 'react'
import { getWizardMatches, postWizardMatches } from '../../api/client'
import { useApi } from '../../api/hooks'
import { DeepLinks } from '../../components/DeepLinks'
import type { FilamentRef, MatchDecision } from '../../api/types'
import type { WizardCtx } from './index'

function FilamentTag({ ref: f }: { ref: FilamentRef }) {
  if (!f) return null
  return (
    <span className="text-sm">
      <span className="font-medium">{f.name ?? '—'}</span>
      {f.vendor && <span className="text-gray-500"> · {f.vendor}</span>}
      {f.color && <span className="text-gray-400"> · {f.color}</span>}
    </span>
  )
}

export default function Step3Matches({ next, prev }: WizardCtx) {
  const { data, loading, error } = useApi(getWizardMatches)
  const [decisions, setDecisions] = useState<Record<number, MatchDecision>>({})
  const [saving, setSaving] = useState(false)
  const [saveErr, setSaveErr] = useState<string | null>(null)

  function setDecision(smId: number, action: 'link' | 'create' | 'skip', fdbId?: string) {
    setDecisions(d => ({ ...d, [smId]: { spoolman_filament_id: smId, action, filamentdb_id: fdbId } }))
  }

  function getAction(smId: number): 'link' | 'create' | 'skip' | undefined {
    return decisions[smId]?.action
  }

  async function handleSave() {
    if (!data) return
    setSaving(true)
    setSaveErr(null)

    const allDecisions: MatchDecision[] = []
    // pre-matched: default to link unless user overrode
    for (const pair of data.matched) {
      const smId = pair.spoolman.spoolman_filament_id!
      allDecisions.push(decisions[smId] ?? {
        spoolman_filament_id: smId,
        action: 'link',
        filamentdb_id: pair.filamentdb.filamentdb_filament_id ?? undefined,
      })
    }
    // unmatched spoolman: must have a decision
    for (const sm of data.unmatched_spoolman) {
      const smId = sm.spoolman_filament_id!
      const d = decisions[smId]
      if (d) allDecisions.push(d)
    }
    // ambiguous: must have a decision
    for (const amb of data.ambiguous) {
      const smId = amb.spoolman.spoolman_filament_id!
      const d = decisions[smId]
      if (d) allDecisions.push(d)
    }

    try {
      await postWizardMatches({ decisions: allDecisions })
      next()
    } catch (e) {
      setSaveErr(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <p className="text-gray-500">Loading match data…</p>
  if (error) return <p className="text-red-600">{error}</p>
  if (!data) return null

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-gray-800">Match review</h2>
        <p className="text-sm text-gray-500 mt-1">
          Review auto-matched pairs, resolve ambiguous matches, and decide what to do with unmatched items.
        </p>
      </div>

      {/* Matched */}
      {data.matched.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <div className="px-5 py-3 bg-green-50 border-b border-gray-200">
            <h3 className="text-sm font-semibold text-green-800">Matched ({data.matched.length})</h3>
          </div>
          <div className="divide-y divide-gray-100">
            {data.matched.map(pair => {
              const smId = pair.spoolman.spoolman_filament_id!
              const action = getAction(smId) ?? 'link'
              return (
                <div key={smId} className="px-5 py-3 flex items-center gap-4">
                  <div className="flex-1 grid grid-cols-2 gap-4">
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-emerald-600 font-medium uppercase">SM</span>
                      <FilamentTag ref={pair.spoolman} />
                      <DeepLinks spoolmanFilamentId={pair.spoolman.spoolman_filament_id} />
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-blue-600 font-medium uppercase">FDB</span>
                      <FilamentTag ref={pair.filamentdb} />
                      <DeepLinks filamentdbFilamentId={pair.filamentdb.filamentdb_filament_id} />
                    </div>
                  </div>
                  <div className="flex items-center gap-1 text-xs text-gray-400">
                    {pair.vendor_dedup_hint && (
                      <span className="px-1.5 py-0.5 bg-yellow-100 text-yellow-700 rounded text-xs">
                        vendor: {pair.vendor_dedup_hint}
                      </span>
                    )}
                    <span>{(pair.confidence * 100).toFixed(0)}%</span>
                  </div>
                  <div className="flex gap-1">
                    {(['link', 'skip'] as const).map(a => (
                      <button
                        key={a}
                        onClick={() => setDecision(smId, a, a === 'link' ? pair.filamentdb.filamentdb_filament_id ?? undefined : undefined)}
                        className={`px-2 py-1 rounded text-xs font-medium ${
                          action === a ? 'bg-indigo-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                        }`}
                      >
                        {a}
                      </button>
                    ))}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Ambiguous */}
      {data.ambiguous.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <div className="px-5 py-3 bg-yellow-50 border-b border-gray-200">
            <h3 className="text-sm font-semibold text-yellow-800">Ambiguous ({data.ambiguous.length}) — pick one</h3>
          </div>
          <div className="divide-y divide-gray-100">
            {data.ambiguous.map(amb => {
              const smId = amb.spoolman.spoolman_filament_id!
              const d = decisions[smId]
              return (
                <div key={smId} className="px-5 py-4 space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-emerald-600 font-medium uppercase">SM</span>
                    <FilamentTag ref={amb.spoolman} />
                    <DeepLinks spoolmanFilamentId={smId} />
                  </div>
                  <div className="pl-4 space-y-1">
                    {amb.candidates.map(c => (
                      <div key={c.filamentdb_filament_id} className="flex items-center gap-2">
                        <button
                          onClick={() => setDecision(smId, 'link', c.filamentdb_filament_id ?? undefined)}
                          className={`px-2 py-0.5 rounded text-xs font-medium ${
                            d?.action === 'link' && d.filamentdb_id === c.filamentdb_filament_id
                              ? 'bg-indigo-600 text-white'
                              : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                          }`}
                        >
                          Link
                        </button>
                        <FilamentTag ref={c} />
                        <DeepLinks filamentdbFilamentId={c.filamentdb_filament_id} />
                      </div>
                    ))}
                    <div className="flex gap-1">
                      {(['create', 'skip'] as const).map(a => (
                        <button
                          key={a}
                          onClick={() => setDecision(smId, a)}
                          className={`px-2 py-0.5 rounded text-xs font-medium ${
                            d?.action === a ? 'bg-indigo-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                          }`}
                        >
                          {a}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Unmatched Spoolman */}
      {data.unmatched_spoolman.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <div className="px-5 py-3 bg-gray-50 border-b border-gray-200">
            <h3 className="text-sm font-semibold text-gray-700">Unmatched in Spoolman ({data.unmatched_spoolman.length})</h3>
          </div>
          <div className="divide-y divide-gray-100">
            {data.unmatched_spoolman.map(sm => {
              const smId = sm.spoolman_filament_id!
              const action = getAction(smId) ?? 'create'
              return (
                <div key={smId} className="px-5 py-3 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-emerald-600 font-medium uppercase">SM</span>
                    <FilamentTag ref={sm} />
                    <DeepLinks spoolmanFilamentId={smId} />
                  </div>
                  <div className="flex gap-1">
                    {(['create', 'skip'] as const).map(a => (
                      <button
                        key={a}
                        onClick={() => setDecision(smId, a)}
                        className={`px-2 py-1 rounded text-xs font-medium ${
                          action === a ? 'bg-indigo-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                        }`}
                      >
                        {a}
                      </button>
                    ))}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Unmatched FDB */}
      {data.unmatched_filamentdb.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <div className="px-5 py-3 bg-gray-50 border-b border-gray-200">
            <h3 className="text-sm font-semibold text-gray-700">Unmatched in Filament DB ({data.unmatched_filamentdb.length}) — will be created in Spoolman</h3>
          </div>
          <div className="divide-y divide-gray-100">
            {data.unmatched_filamentdb.map(f => (
              <div key={f.filamentdb_filament_id} className="px-5 py-3 flex items-center gap-2">
                <span className="text-xs text-blue-600 font-medium uppercase">FDB</span>
                <FilamentTag ref={f} />
                <DeepLinks filamentdbFilamentId={f.filamentdb_filament_id} />
              </div>
            ))}
          </div>
        </div>
      )}

      {saveErr && <p className="text-sm text-red-600">{saveErr}</p>}

      <div className="flex justify-between">
        <button onClick={prev} className="px-5 py-2 bg-gray-100 text-gray-700 rounded text-sm font-medium hover:bg-gray-200">
          ← Back
        </button>
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-5 py-2 bg-indigo-600 text-white rounded text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save & Next →'}
        </button>
      </div>
    </div>
  )
}
