/** Small "OPT" pill shown next to a filament that is tagged in OpenPrintTag. */
export function OptBadge() {
  return (
    <span
      title="OpenPrintTag tagged"
      className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded border text-xs font-medium bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-300 border-gray-200 dark:border-gray-600 shrink-0"
    >
      {/* tag glyph */}
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" className="w-3 h-3">
        <path fillRule="evenodd" d="M4.5 2A2.5 2.5 0 0 0 2 4.5v2.379a2.5 2.5 0 0 0 .732 1.767l5.622 5.622a2.5 2.5 0 0 0 3.536 0l2.378-2.378a2.5 2.5 0 0 0 0-3.536L8.646 2.732A2.5 2.5 0 0 0 6.879 2H4.5ZM5.25 5.5a.75.75 0 1 1 0-1.5.75.75 0 0 1 0 1.5Z" clipRule="evenodd" />
      </svg>
      OPT
    </span>
  )
}
