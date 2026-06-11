/**
 * HelpTip — a small circled "?" that shows a tooltip on hover, focus, and tap.
 *
 * Props:
 *   text         — plain-text tooltip content (1–3 sentences)
 *   learnMoreHref — optional in-app or external URL, rendered as "Learn more ↗" link
 *
 * Accessibility: tabIndex=0, aria-describedby, Escape/blur closes.
 * No layout shift: tooltip is absolutely positioned above the icon (z-50).
 */

import { useCallback, useEffect, useRef, useState } from 'react'

interface HelpTipProps {
  text: string
  learnMoreHref?: string
}

export function HelpTip({ text, learnMoreHref }: HelpTipProps) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLSpanElement>(null)

  const close = useCallback(() => setOpen(false), [])

  // Close on Escape key
  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') close()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, close])

  // Close when focus moves outside the component
  function handleBlur(e: React.FocusEvent) {
    if (!ref.current?.contains(e.relatedTarget as Node)) close()
  }

  const tooltipId = `helptip-${Math.random().toString(36).slice(2)}`

  return (
    <span
      ref={ref}
      className="relative inline-flex items-center align-middle"
      onBlur={handleBlur}
    >
      {/* The "?" button */}
      <button
        type="button"
        tabIndex={0}
        aria-label="Help"
        aria-describedby={open ? tooltipId : undefined}
        aria-expanded={open}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onClick={() => setOpen(v => !v)}
        className="inline-flex items-center justify-center w-[1.1rem] h-[1.1rem] rounded-full border border-gray-300 dark:border-gray-500 text-gray-400 dark:text-gray-500 text-[0.65rem] font-medium leading-none cursor-default select-none ml-1.5 hover:border-gray-400 dark:hover:border-gray-400 hover:text-gray-500 dark:hover:text-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-400 focus:ring-offset-1 dark:focus:ring-offset-gray-800 shrink-0"
      >
        ?
      </button>

      {/* Tooltip bubble */}
      {open && (
        <span
          id={tooltipId}
          role="tooltip"
          className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 z-50 w-72 max-w-[18rem] rounded-lg border border-gray-200 dark:border-gray-600 bg-gray-800 dark:bg-gray-700 text-gray-100 shadow-lg px-3 py-2 text-xs leading-relaxed pointer-events-none"
        >
          {text}
          {learnMoreHref && (
            <a
              href={learnMoreHref}
              target={learnMoreHref.startsWith('/') ? undefined : '_blank'}
              rel={learnMoreHref.startsWith('/') ? undefined : 'noopener noreferrer'}
              className="block mt-1.5 text-indigo-300 hover:text-indigo-200 underline pointer-events-auto"
            >
              Learn more ↗
            </a>
          )}
          {/* Caret */}
          <span className="absolute top-full left-1/2 -translate-x-1/2 -mt-px border-4 border-transparent border-t-gray-800 dark:border-t-gray-700" />
        </span>
      )}
    </span>
  )
}
