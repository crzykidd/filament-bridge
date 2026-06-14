import { getReconcile } from '../api/client'
import { useApi } from '../api/hooks'
import { DeepLinks } from '../components/DeepLinks'
import type { AmbiguousRow, ReconcileMatchRow, ReconcileMissingRow } from '../api/types'

function fmtWeight(w: number | null): string {
  if (w == null) return '—'
  return `${w.toFixed(1)} g`
}

function fmtSpools(count: number): string {
  return count === 1 ? '1 spool' : `${count} spools`
}

// ---------------------------------------------------------------------------
// Row components
// ---------------------------------------------------------------------------

function MatchedRow({ row }: { row: ReconcileMatchRow }) {
  return (
    <tr className="border-t border-gray-100 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-750">
      <td className="px-4 py-3">
        <div className="font-medium text-gray-900 dark:text-gray-100">{row.spoolman.name ?? '—'}</div>
        <div className="text-xs text-gray-400 dark:text-gray-500">{row.spoolman.vendor ?? '—'}</div>
      </td>
      <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-300">{row.spoolman.color ?? '—'}</td>
      <td className="px-4 py-3">
        <div className="font-medium text-gray-900 dark:text-gray-100">{row.filamentdb.name ?? '—'}</div>
        <div className="text-xs text-gray-400 dark:text-gray-500">{row.filamentdb.vendor ?? '—'}</div>
      </td>
      <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-300">
        <div>{fmtSpools(row.spoolman_spools)} · {fmtWeight(row.spoolman_weight)}</div>
        <div className="text-xs text-gray-400 dark:text-gray-500">{fmtSpools(row.filamentdb_spools)} · {fmtWeight(row.filamentdb_weight)}</div>
      </td>
      <td className="px-4 py-3 text-sm">
        {row.linked
          ? <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300">linked</span>
          : <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400">name match</span>
        }
      </td>
      <td className="px-4 py-3">
        <DeepLinks
          filamentdbFilamentId={row.filamentdb.filamentdb_filament_id}
          spoolmanFilamentId={row.spoolman.spoolman_filament_id ?? undefined}
        />
      </td>
    </tr>
  )
}

function MissingRow({ row, side }: { row: ReconcileMissingRow; side: 'spoolman' | 'filamentdb' }) {
  return (
    <tr className="border-t border-gray-100 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-750">
      <td className="px-4 py-3">
        <div className="font-medium text-gray-900 dark:text-gray-100">{row.ref.name ?? '—'}</div>
        <div className="text-xs text-gray-400 dark:text-gray-500">{row.ref.vendor ?? '—'}</div>
      </td>
      <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-300">{row.ref.color ?? '—'}</td>
      <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-300">{row.ref.material ?? '—'}</td>
      <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-300">
        {fmtSpools(row.spool_count)} · {fmtWeight(row.weight_total)}
      </td>
      <td className="px-4 py-3">
        <DeepLinks
          filamentdbFilamentId={side === 'filamentdb' ? row.ref.filamentdb_filament_id : null}
          spoolmanFilamentId={side === 'spoolman' ? (row.ref.spoolman_filament_id ?? undefined) : undefined}
        />
      </td>
    </tr>
  )
}

function AmbiguousRowItem({ row }: { row: AmbiguousRow }) {
  return (
    <tr className="border-t border-gray-100 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-750">
      <td className="px-4 py-3">
        <div className="font-medium text-gray-900 dark:text-gray-100">{row.spoolman.name ?? '—'}</div>
        <div className="text-xs text-gray-400 dark:text-gray-500">{row.spoolman.vendor ?? '—'}</div>
      </td>
      <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-300">{row.spoolman.color ?? '—'}</td>
      <td className="px-4 py-3">
        <ul className="space-y-1">
          {row.candidates.map((c, i) => (
            <li key={c.filamentdb_filament_id ?? i} className="text-sm text-gray-700 dark:text-gray-300">
              {c.vendor ? `${c.vendor} · ` : ''}{c.name ?? '—'}{c.color ? ` · ${c.color}` : ''}
              <span className="ml-2 text-xs text-gray-400 dark:text-gray-500">(FDB: {c.filamentdb_filament_id})</span>
            </li>
          ))}
        </ul>
      </td>
      <td className="px-4 py-3">
        <DeepLinks
          spoolmanFilamentId={row.spoolman.spoolman_filament_id ?? undefined}
        />
      </td>
    </tr>
  )
}

// ---------------------------------------------------------------------------
// Section wrapper
// ---------------------------------------------------------------------------

function Section({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  return (
    <div>
      <h2 className="text-base font-semibold text-gray-700 dark:text-gray-300 mb-2">
        {title}
        <span className="ml-2 text-sm font-normal text-gray-400 dark:text-gray-500">({count})</span>
      </h2>
      {children}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function Reconcile() {
  const { data, loading, error, reload } = useApi(getReconcile)

  return (
    <div className="p-8 space-y-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Reconcile</h1>
        <button
          onClick={() => void reload()}
          disabled={loading}
          className="px-3 py-1.5 text-sm font-medium rounded bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 hover:bg-gray-200 dark:hover:bg-gray-600 disabled:opacity-50"
        >
          {loading ? 'Loading…' : 'Refresh'}
        </button>
      </div>

      {loading && !data && <p className="text-gray-500 dark:text-gray-400">Loading…</p>}
      {error && <p className="text-red-600 dark:text-red-400">{error}</p>}

      {data && (
        <>
          {/* Summary header */}
          <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex flex-wrap gap-4 text-sm">
              <span className="text-gray-500 dark:text-gray-400">
                <span className="font-medium text-gray-700 dark:text-gray-300">{data.summary.spoolman_filaments}</span> SM filaments
              </span>
              <span className="text-gray-300 dark:text-gray-600">·</span>
              <span className="text-gray-500 dark:text-gray-400">
                <span className="font-medium text-gray-700 dark:text-gray-300">{data.summary.filamentdb_filaments}</span> FDB filaments
              </span>
              <span className="text-gray-300 dark:text-gray-600">·</span>
              <span className="text-green-600 dark:text-green-400 font-medium">
                {data.summary.matched} matched
              </span>
              {data.summary.only_in_spoolman > 0 && (
                <>
                  <span className="text-gray-300 dark:text-gray-600">·</span>
                  <span className="text-amber-600 dark:text-amber-400 font-medium">
                    {data.summary.only_in_spoolman} only in Spoolman
                  </span>
                </>
              )}
              {data.summary.only_in_filamentdb > 0 && (
                <>
                  <span className="text-gray-300 dark:text-gray-600">·</span>
                  <span className="text-amber-600 dark:text-amber-400 font-medium">
                    {data.summary.only_in_filamentdb} only in Filament DB
                  </span>
                </>
              )}
              {data.summary.ambiguous > 0 && (
                <>
                  <span className="text-gray-300 dark:text-gray-600">·</span>
                  <span className="text-red-600 dark:text-red-400 font-medium">
                    {data.summary.ambiguous} ambiguous
                  </span>
                </>
              )}
            </div>
          </div>

          <p className="text-xs text-gray-400 dark:text-gray-500">
            Read-only report — this page does not modify either system. To import missing items, use the{' '}
            <a href="/wizard" className="underline hover:text-gray-600 dark:hover:text-gray-300">Bulk Import Wizard</a>.
          </p>

          {/* Matched */}
          <Section title="Matched" count={data.matched.length}>
            {data.matched.length === 0 ? (
              <p className="text-sm text-gray-400 dark:text-gray-500 italic">No matched filaments.</p>
            ) : (
              <div className="overflow-x-auto bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
                <table className="min-w-full text-sm">
                  <thead className="bg-gray-50 dark:bg-gray-750">
                    <tr>
                      {(['Spoolman', 'SM Color', 'Filament DB', 'Spools / Weight', 'Match type', 'Links'] as const).map(h => (
                        <th key={h} className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.matched.map((row, i) => (
                      <MatchedRow key={`${row.spoolman.spoolman_filament_id}-${row.filamentdb.filamentdb_filament_id}-${i}`} row={row} />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Section>

          {/* Only in Spoolman */}
          <Section title="Only in Spoolman" count={data.only_in_spoolman.length}>
            {data.only_in_spoolman.length === 0 ? (
              <p className="text-sm text-gray-400 dark:text-gray-500 italic">No Spoolman-only filaments.</p>
            ) : (
              <div className="overflow-x-auto bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
                <table className="min-w-full text-sm">
                  <thead className="bg-gray-50 dark:bg-gray-750">
                    <tr>
                      {(['Name / Vendor', 'Color', 'Material', 'Spools / Weight', 'Links'] as const).map(h => (
                        <th key={h} className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.only_in_spoolman.map((row, i) => (
                      <MissingRow key={`sm-${row.ref.spoolman_filament_id ?? i}`} row={row} side="spoolman" />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Section>

          {/* Only in Filament DB */}
          <Section title="Only in Filament DB" count={data.only_in_filamentdb.length}>
            {data.only_in_filamentdb.length === 0 ? (
              <p className="text-sm text-gray-400 dark:text-gray-500 italic">No Filament DB-only filaments.</p>
            ) : (
              <div className="overflow-x-auto bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
                <table className="min-w-full text-sm">
                  <thead className="bg-gray-50 dark:bg-gray-750">
                    <tr>
                      {(['Name / Vendor', 'Color', 'Material', 'Spools / Weight', 'Links'] as const).map(h => (
                        <th key={h} className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.only_in_filamentdb.map((row, i) => (
                      <MissingRow key={`fdb-${row.ref.filamentdb_filament_id ?? i}`} row={row} side="filamentdb" />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Section>

          {/* Ambiguous */}
          <Section title="Ambiguous" count={data.ambiguous.length}>
            {data.ambiguous.length === 0 ? (
              <p className="text-sm text-gray-400 dark:text-gray-500 italic">No ambiguous filaments.</p>
            ) : (
              <div className="overflow-x-auto bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
                <table className="min-w-full text-sm">
                  <thead className="bg-gray-50 dark:bg-gray-750">
                    <tr>
                      {(['Spoolman', 'SM Color', 'FDB Candidates', 'Links'] as const).map(h => (
                        <th key={h} className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.ambiguous.map((row, i) => (
                      <AmbiguousRowItem key={`amb-${row.spoolman.spoolman_filament_id ?? i}`} row={row} />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Section>
        </>
      )}
    </div>
  )
}
