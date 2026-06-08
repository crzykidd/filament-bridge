/**
 * datetime.ts — shared timestamp formatting helpers.
 *
 * The backend emits naive-UTC strings like "2026-06-08T05:27:48" (no timezone
 * offset, no Z suffix). Browsers treat those as LOCAL time when passed to
 * `new Date()`, which is wrong.  We detect that pattern and append "Z" so the
 * runtime parses them correctly as UTC before converting to the viewer's local
 * timezone.
 */

/** Regex: bare ISO datetime with no timezone offset and no Z suffix. */
const BARE_ISO_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/

function ensureUtc(value: string): string {
  return BARE_ISO_RE.test(value.trim()) ? value.trim() + 'Z' : value
}

export interface FormatLocalOpts {
  /** Render date only (no time component). */
  dateOnly?: boolean
  /** Include seconds in the time component. */
  seconds?: boolean
}

/**
 * Parse an ISO/UTC timestamp string and render it in the browser's local
 * timezone via `toLocaleString`.
 *
 * Returns '—' for null, undefined, empty string, or unparseable input.
 * Treats bare ISO datetimes (no tz offset, no Z) as UTC.
 */
export function formatLocal(
  value: string | null | undefined,
  opts?: FormatLocalOpts,
): string {
  if (!value) return '—'

  const d = new Date(ensureUtc(value))
  if (isNaN(d.getTime())) return '—'

  if (opts?.dateOnly) {
    return d.toLocaleDateString(undefined, {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    })
  }

  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    ...(opts?.seconds ? { second: '2-digit' } : {}),
  })
}

/**
 * Ensure a UTC timestamp string is correctly parsed as UTC before use in
 * relative-time calculations (e.g. "3 min ago" logic).
 * Use this when you need a `Date` object, not a formatted string.
 */
export function parseUtc(value: string): Date {
  return new Date(ensureUtc(value))
}
