/**
 * ScanTarget — the bare QR scan-target page (`/scan/:filId/:spoolId`).
 *
 * Rendered OUTSIDE the <Layout/> wrapper (no nav): this is what a phone
 * opens after scanning the label QR (via the `/r/{fil}/{spool}` redirect). It is
 * a single-purpose, full-screen frame around the shared MobileSpoolUpdate card
 * (frame modeled on Login.tsx). If the feature is disabled the API 403s and the
 * card surfaces that message inline rather than crashing.
 *
 * A search box at the top lets a user jump to any other mapped spool without
 * re-scanning. Typing queries GET /api/mobile/spools?q=… (mobile-gated, so it
 * works under both the normal-login and the public-scan auth contexts). Selecting
 * a result navigates to /scan/<fil>/<spool>, which reloads this same page for
 * the chosen spool.
 */

import { useState, useRef, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { MobileSpoolUpdate } from '../components/MobileSpoolUpdate'
import { getMobileSpools } from '../api/client'
import type { MobileSpoolSearchResult } from '../api/types'
import { ColorDisplay } from '../components/ColorDisplay'

function SpoolSearch() {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<MobileSpoolSearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (!query.trim()) {
      setResults([])
      setOpen(false)
      return
    }
    debounceRef.current = setTimeout(async () => {
      setLoading(true)
      setError(null)
      try {
        const data = await getMobileSpools(query)
        setResults(data)
        setOpen(true)
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : 'Search failed')
        setOpen(false)
      } finally {
        setLoading(false)
      }
    }, 250)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [query])

  function handleSelect(r: MobileSpoolSearchResult) {
    setQuery('')
    setResults([])
    setOpen(false)
    navigate(`/scan/${r.filamentdb_filament_id}/${r.filamentdb_spool_id}`)
  }

  return (
    <div className="w-full max-w-md mb-4">
      <input
        type="search"
        aria-label="Search spools"
        placeholder="Search name / vendor / color / # …"
        value={query}
        onChange={e => setQuery(e.target.value)}
        className="w-full border border-gray-300 dark:border-gray-600 rounded px-3 py-2 text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder:text-gray-400 dark:placeholder:text-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-400"
      />

      {loading && (
        <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">Searching…</p>
      )}
      {error && (
        <p className="mt-1 text-xs text-red-500 dark:text-red-400">{error}</p>
      )}

      {open && !loading && (
        <div className="mt-1 border border-gray-200 dark:border-gray-700 rounded-lg divide-y divide-gray-100 dark:divide-gray-700 overflow-hidden bg-white dark:bg-gray-800 shadow">
          {results.length === 0 ? (
            <p className="text-sm text-gray-400 dark:text-gray-500 px-3 py-2">No matching spools.</p>
          ) : (
            results.map(r => (
              <button
                key={`${r.filamentdb_filament_id}/${r.filamentdb_spool_id}`}
                type="button"
                onClick={() => handleSelect(r)}
                className="w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
              >
                <ColorDisplay
                  colorHex={r.color}
                  multiColorHexes={r.multi_color_hexes}
                  multiColorDirection={r.multi_color_direction}
                />
                <span className="flex-1 text-sm text-gray-900 dark:text-gray-100 truncate">
                  {r.name ?? '—'}
                  {r.vendor ? (
                    <span className="text-gray-400 dark:text-gray-500"> · {r.vendor}</span>
                  ) : null}
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
  )
}

export default function ScanTarget() {
  const { filId, spoolId } = useParams<{ filId: string; spoolId: string }>()

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 flex flex-col items-center px-4 py-8">
      <SpoolSearch />
      {filId && spoolId ? (
        <MobileSpoolUpdate filId={filId} spoolId={spoolId} />
      ) : (
        <p className="text-sm text-red-600 dark:text-red-400 mt-12">Invalid scan link.</p>
      )}
    </div>
  )
}
