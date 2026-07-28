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

import { useRef, useState } from 'react'
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
  // Spool number is by far the most common way to look one up on a phone, and iOS/iPadOS
  // gives no "letters + number row" keyboard — so default to the numeric keypad and offer a
  // toggle back to a full text keyboard for the occasional name/vendor/color search. `type`
  // stays "text" (the filter below matches numbers and text alike); only the on-screen
  // keyboard changes. (#79)
  const [numericKeypad, setNumericKeypad] = useState(true)
  const searchRef = useRef<HTMLInputElement>(null)

  const toggleKeypad = () => {
    setNumericKeypad(m => !m)
    // iOS only re-renders the on-screen keyboard on a focus change, so blur + refocus to
    // actually swap it when the field is already focused.
    const el = searchRef.current
    if (el) {
      el.blur()
      requestAnimationFrame(() => el.focus())
    }
  }

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
        <div className="relative">
          <input
            ref={searchRef}
            type="text"
            inputMode={numericKeypad ? 'numeric' : 'text'}
            placeholder={numericKeypad ? 'Search by # …' : 'Search name / vendor / color …'}
            value={search}
            onChange={e => { setSearch(e.target.value); setSelected(null) }}
            className="w-full border border-gray-300 dark:border-gray-600 rounded pl-3 pr-14 py-2 text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder:text-gray-400 dark:placeholder:text-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-400"
          />
          <button
            type="button"
            onClick={toggleKeypad}
            aria-label={numericKeypad ? 'Switch to text keyboard' : 'Switch to number keypad'}
            title={numericKeypad ? 'Switch to text keyboard' : 'Switch to number keypad'}
            className="absolute right-1.5 top-1/2 -translate-y-1/2 px-2 py-1 text-xs font-medium rounded border border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-600 focus:outline-none focus:ring-2 focus:ring-indigo-400"
          >
            {numericKeypad ? 'Abc' : '123'}
          </button>
        </div>

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
