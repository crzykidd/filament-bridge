/**
 * MobileUpdates — the in-nav "Mobile updates" page.
 *
 * A spool search box (reusing the SyncedRecords filter pattern over getMappings())
 * lets you pick a spool without scanning its QR; selecting a result renders the
 * shared MobileSpoolUpdate card below the search. Only spool rows (kind="spool"
 * with both FDB ids) are selectable — the mobile update flow is per-spool.
 *
 * The nav item that links here is gated on `mobile_labels_enabled` (Layout.tsx);
 * if a user reaches this page with the feature off, the card's API call 403s and
 * surfaces the message inline.
 */

import { useState } from 'react'
import { getMappings } from '../api/client'
import { useApi } from '../api/hooks'
import { ColorDisplay } from '../components/ColorDisplay'
import { MobileSpoolUpdate } from '../components/MobileSpoolUpdate'
import type { MappingRow } from '../api/types'

interface Selected {
  filId: string
  spoolId: string
}

function isSelectable(row: MappingRow): boolean {
  return row.kind === 'spool' && !!row.filamentdb_filament_id && !!row.filamentdb_spool_id
}

export default function MobileUpdates() {
  const { data, loading, error } = useApi(getMappings)
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<Selected | null>(null)

  let rows: MappingRow[] = (data ?? []).filter(isSelectable)
  if (search.trim()) {
    const q = search.toLowerCase()
    rows = rows.filter(r =>
      r.name?.toLowerCase().includes(q) ||
      r.vendor?.toLowerCase().includes(q) ||
      r.color?.toLowerCase().includes(q) ||
      String(r.spoolman_spool_id ?? '').includes(q),
    )
  }

  return (
    <div className="p-8 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Mobile updates</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
          Search for a spool to quickly update its weight (from a scale) and location — the same
          flow a phone reaches by scanning a label QR.
        </p>
      </div>

      <div className="max-w-md space-y-3">
        <input
          type="text"
          placeholder="Search name / vendor / color / # …"
          value={search}
          onChange={e => { setSearch(e.target.value); setSelected(null) }}
          className="w-full border border-gray-300 dark:border-gray-600 rounded px-3 py-2 text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder:text-gray-400 dark:placeholder:text-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-400"
        />

        {loading && <p className="text-sm text-gray-500 dark:text-gray-400">Loading…</p>}
        {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}

        {!loading && !error && search.trim() !== '' && !selected && (
          <div className="border border-gray-200 dark:border-gray-700 rounded-lg divide-y divide-gray-100 dark:divide-gray-700 overflow-hidden">
            {rows.length === 0 ? (
              <p className="text-sm text-gray-400 dark:text-gray-500 px-3 py-2">No matching spools.</p>
            ) : (
              rows.slice(0, 25).map(r => (
                <button
                  key={r.id}
                  type="button"
                  onClick={() => setSelected({ filId: r.filamentdb_filament_id, spoolId: r.filamentdb_spool_id! })}
                  className="w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
                >
                  <ColorDisplay
                    colorHex={r.color}
                    multiColorHexes={r.multi_color_hexes}
                    multiColorDirection={r.multi_color_direction}
                  />
                  <span className="flex-1 text-sm text-gray-900 dark:text-gray-100 truncate">
                    {r.name ?? '—'}
                    {r.vendor ? <span className="text-gray-400 dark:text-gray-500"> · {r.vendor}</span> : null}
                  </span>
                  <span className="text-xs font-mono text-gray-400 dark:text-gray-500 shrink-0">
                    #{r.spoolman_spool_id}
                  </span>
                </button>
              ))
            )}
          </div>
        )}
      </div>

      {selected && (
        <div className="space-y-3">
          <button
            type="button"
            onClick={() => setSelected(null)}
            className="text-sm text-indigo-600 dark:text-indigo-400 hover:underline"
          >
            ← Back to search
          </button>
          <MobileSpoolUpdate filId={selected.filId} spoolId={selected.spoolId} />
        </div>
      )}
    </div>
  )
}
