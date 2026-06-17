/**
 * HelpTip — a small circled "?" that shows a tooltip on hover, focus, and tap.
 *
 * Props:
 *   text         — plain-text tooltip content (1–3 sentences)
 *   learnMoreHref — optional in-app or external URL, rendered as "Learn more ↗" link
 *
 * Accessibility: tabIndex=0, aria-describedby, Escape/blur closes.
 *
 * Positioning: the bubble is rendered in a portal on <body> with position:fixed, so it
 * can never be clipped by the sidebar, the page header, or any overflow:hidden ancestor.
 * It prefers to sit above the icon and flips below when there isn't room near the top of
 * the viewport; horizontally it is clamped to stay on-screen, and the caret tracks the icon.
 */

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

interface HelpTipProps {
  text: string
  learnMoreHref?: string
}

const MARGIN = 8 // min gap from the viewport edge
const GAP = 8 // gap between the icon and the bubble

interface Coords {
  top: number
  left: number
  placeAbove: boolean
  caretLeft: number
}

export function HelpTip({ text, learnMoreHref }: HelpTipProps) {
  const [open, setOpen] = useState(false)
  const [coords, setCoords] = useState<Coords | null>(null)
  const ref = useRef<HTMLSpanElement>(null)
  const btnRef = useRef<HTMLButtonElement>(null)
  const tipRef = useRef<HTMLSpanElement>(null)

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

  // Position the portaled bubble against the icon, flipping/clamping to the viewport.
  const reposition = useCallback(() => {
    const btn = btnRef.current
    const tip = tipRef.current
    if (!btn || !tip) return
    const b = btn.getBoundingClientRect()
    const tw = tip.offsetWidth
    const th = tip.offsetHeight
    const centerX = b.left + b.width / 2
    const left = Math.max(MARGIN, Math.min(centerX - tw / 2, window.innerWidth - tw - MARGIN))
    const placeAbove = b.top >= th + GAP + MARGIN
    const top = placeAbove ? b.top - th - GAP : b.bottom + GAP
    const caretLeft = Math.max(10, Math.min(centerX - left, tw - 10))
    setCoords({ top, left, placeAbove, caretLeft })
  }, [])

  // Measure + position once the bubble is in the DOM, and keep it pinned on scroll/resize.
  useLayoutEffect(() => {
    if (!open) {
      setCoords(null)
      return
    }
    reposition()
    window.addEventListener('scroll', reposition, true)
    window.addEventListener('resize', reposition)
    return () => {
      window.removeEventListener('scroll', reposition, true)
      window.removeEventListener('resize', reposition)
    }
  }, [open, reposition])

  // Close when focus moves outside the component
  function handleBlur(e: React.FocusEvent) {
    if (!ref.current?.contains(e.relatedTarget as Node)) close()
  }

  const tooltipId = `helptip-${Math.random().toString(36).slice(2)}`

  return (
    <span ref={ref} className="relative inline-flex items-center align-middle" onBlur={handleBlur}>
      {/* The "?" button */}
      <button
        ref={btnRef}
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

      {/* Tooltip bubble — portaled to <body> so it escapes sidebar/header/overflow clipping */}
      {open &&
        createPortal(
          <span
            ref={tipRef}
            id={tooltipId}
            role="tooltip"
            style={{
              position: 'fixed',
              top: coords?.top ?? 0,
              left: coords?.left ?? 0,
              visibility: coords ? 'visible' : 'hidden',
            }}
            className="z-[100] w-72 max-w-[18rem] rounded-lg border border-gray-200 dark:border-gray-600 bg-gray-800 dark:bg-gray-700 text-gray-100 shadow-lg px-3 py-2 text-xs leading-relaxed pointer-events-none"
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
            {/* Caret — points down when the bubble is above the icon, up when below */}
            <span
              style={{ left: coords?.caretLeft ?? 0 }}
              className={
                coords?.placeAbove
                  ? 'absolute top-full -translate-x-1/2 -mt-px border-4 border-transparent border-t-gray-800 dark:border-t-gray-700'
                  : 'absolute bottom-full -translate-x-1/2 -mb-px border-4 border-transparent border-b-gray-800 dark:border-b-gray-700'
              }
            />
          </span>,
          document.body,
        )}
    </span>
  )
}
