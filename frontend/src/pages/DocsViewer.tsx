/**
 * DocsViewer — renders a markdown file from /docs-md/<slug>.md inside the app.
 *
 * Route: /docs/:slug (no slug → shows README.md, the docs index)
 * Markdown is fetched from /docs-md/<slug>.md (served by the SPA fallback in
 * production, and by the vite dev plugin in development).
 * Rendered with react-markdown + remark-gfm; styled with manual Tailwind classes.
 * Relative .md links are rewritten to /docs/<slug> (in-app navigation).
 * External links open in a new tab.
 */

import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Components } from 'react-markdown'
import type { AnchorHTMLAttributes } from 'react'

// Slug allow-list: only lowercase letters, digits, and hyphens.
const SLUG_RE = /^[a-z0-9-]+$/

function slugFromHref(href: string): string | null {
  // Matches a relative .md link with an optional anchor, e.g. "configuration.md" or
  // "variant-parent-mode.md#section".
  const m = href.match(/^([a-z0-9-]+)\.md(#[^\s]*)?$/)
  if (!m) return null
  return m[1] + (m[2] ?? '')
}

// ---------------------------------------------------------------------------
// react-markdown component overrides (Tailwind prose-like classes)
// ---------------------------------------------------------------------------

const mdComponents: Components = {
  // Headings
  h1: ({ children, ...props }) => (
    <h1
      className="text-2xl font-bold text-gray-900 dark:text-gray-100 mt-0 mb-4"
      {...props}
    >
      {children}
    </h1>
  ),
  h2: ({ children, ...props }) => (
    <h2
      className="text-xl font-semibold text-gray-800 dark:text-gray-200 mt-8 mb-3 border-b border-gray-200 dark:border-gray-700 pb-1"
      {...props}
    >
      {children}
    </h2>
  ),
  h3: ({ children, ...props }) => (
    <h3
      className="text-base font-semibold text-gray-800 dark:text-gray-200 mt-6 mb-2"
      {...props}
    >
      {children}
    </h3>
  ),
  h4: ({ children, ...props }) => (
    <h4
      className="text-sm font-semibold text-gray-700 dark:text-gray-300 mt-4 mb-1"
      {...props}
    >
      {children}
    </h4>
  ),
  // Paragraphs
  p: ({ children, ...props }) => (
    <p
      className="text-sm text-gray-700 dark:text-gray-300 mb-4 leading-relaxed"
      {...props}
    >
      {children}
    </p>
  ),
  // Lists
  ul: ({ children, ...props }) => (
    <ul
      className="list-disc list-outside pl-5 mb-4 space-y-1 text-sm text-gray-700 dark:text-gray-300"
      {...props}
    >
      {children}
    </ul>
  ),
  ol: ({ children, ...props }) => (
    <ol
      className="list-decimal list-outside pl-5 mb-4 space-y-1 text-sm text-gray-700 dark:text-gray-300"
      {...props}
    >
      {children}
    </ol>
  ),
  li: ({ children, ...props }) => (
    <li className="leading-relaxed" {...props}>
      {children}
    </li>
  ),
  // Code
  code: ({ children, className, ...props }) => {
    // Block code (inside <pre>) has a language class; inline code does not.
    const isBlock = !!className
    if (isBlock) {
      return (
        <code
          className={`block bg-gray-100 dark:bg-gray-800 text-gray-800 dark:text-gray-200 rounded p-3 text-xs font-mono overflow-x-auto ${className ?? ''}`}
          {...props}
        >
          {children}
        </code>
      )
    }
    return (
      <code
        className="bg-gray-100 dark:bg-gray-800 text-gray-800 dark:text-gray-200 rounded px-1 py-0.5 text-xs font-mono"
        {...props}
      >
        {children}
      </code>
    )
  },
  pre: ({ children, ...props }) => (
    <pre
      className="bg-gray-100 dark:bg-gray-800 rounded mb-4 overflow-x-auto"
      {...props}
    >
      {children}
    </pre>
  ),
  // Tables
  table: ({ children, ...props }) => (
    <div className="overflow-x-auto mb-4">
      <table
        className="min-w-full text-sm border-collapse border border-gray-200 dark:border-gray-700"
        {...props}
      >
        {children}
      </table>
    </div>
  ),
  thead: ({ children, ...props }) => (
    <thead className="bg-gray-50 dark:bg-gray-800" {...props}>
      {children}
    </thead>
  ),
  th: ({ children, ...props }) => (
    <th
      className="border border-gray-200 dark:border-gray-700 px-3 py-2 text-left text-xs font-semibold text-gray-700 dark:text-gray-300"
      {...props}
    >
      {children}
    </th>
  ),
  td: ({ children, ...props }) => (
    <td
      className="border border-gray-200 dark:border-gray-700 px-3 py-2 text-xs text-gray-700 dark:text-gray-300 align-top"
      {...props}
    >
      {children}
    </td>
  ),
  // Blockquotes
  blockquote: ({ children, ...props }) => (
    <blockquote
      className="border-l-4 border-indigo-400 dark:border-indigo-600 pl-4 mb-4 italic text-gray-600 dark:text-gray-400 text-sm"
      {...props}
    >
      {children}
    </blockquote>
  ),
  // Horizontal rule
  hr: ({ ...props }) => (
    <hr className="border-gray-200 dark:border-gray-700 my-6" {...props} />
  ),
  // Strong / em
  strong: ({ children, ...props }) => (
    <strong className="font-semibold text-gray-900 dark:text-gray-100" {...props}>
      {children}
    </strong>
  ),
  em: ({ children, ...props }) => (
    <em className="italic" {...props}>
      {children}
    </em>
  ),
  // Links — rewrite relative .md refs to in-app /docs/<slug>
  a: ({ href, children, ...props }: AnchorHTMLAttributes<HTMLAnchorElement>) => {
    if (!href) {
      return <span {...props}>{children}</span>
    }
    // External link
    if (/^https?:\/\//.test(href)) {
      return (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="text-indigo-600 dark:text-indigo-400 hover:underline"
          {...props}
        >
          {children}
        </a>
      )
    }
    // Relative .md link → in-app navigation
    const inAppSlug = slugFromHref(href)
    if (inAppSlug !== null) {
      return (
        <Link
          to={`/docs/${inAppSlug}`}
          className="text-indigo-600 dark:text-indigo-400 hover:underline"
        >
          {children}
        </Link>
      )
    }
    // Anchor-only (#section) or other relative links
    return (
      <a
        href={href}
        className="text-indigo-600 dark:text-indigo-400 hover:underline"
        {...props}
      >
        {children}
      </a>
    )
  },
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function DocsViewer() {
  const { slug } = useParams<{ slug?: string }>()
  // No slug → docs index (README.md)
  const effectiveSlug = slug ?? 'README'

  const [content, setContent] = useState<string | null>(null)
  const [notFound, setNotFound] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // Validate slug before fetching
    if (effectiveSlug !== 'README' && !SLUG_RE.test(effectiveSlug.split('#')[0])) {
      setNotFound(true)
      setLoading(false)
      return
    }

    setLoading(true)
    setNotFound(false)
    setContent(null)

    // Strip anchor from slug before building filename
    const filename = effectiveSlug.split('#')[0]

    fetch(`/docs-md/${filename}.md`)
      .then(res => {
        if (!res.ok) {
          setNotFound(true)
          return null
        }
        return res.text()
      })
      .then(text => {
        if (text !== null) setContent(text)
      })
      .catch(() => {
        setNotFound(true)
      })
      .finally(() => {
        setLoading(false)
      })
  }, [effectiveSlug])

  return (
    <div className="p-6 max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <Link
          to="/docs"
          className="text-sm text-indigo-600 dark:text-indigo-400 hover:underline"
        >
          ← Docs
        </Link>
        <span className="text-gray-400 dark:text-gray-600 text-sm">
          {effectiveSlug === 'README' ? 'Index' : effectiveSlug}
        </span>
      </div>

      {loading && (
        <p className="text-sm text-gray-500 dark:text-gray-400">Loading…</p>
      )}

      {!loading && notFound && (
        <div className="text-center py-16">
          <p className="text-gray-500 dark:text-gray-400 text-sm">
            Doc not found: <code className="font-mono">{effectiveSlug}</code>
          </p>
          <Link
            to="/docs"
            className="mt-4 inline-block text-sm text-indigo-600 dark:text-indigo-400 hover:underline"
          >
            Back to docs index
          </Link>
        </div>
      )}

      {!loading && content !== null && (
        <article className="min-w-0">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
            {content}
          </ReactMarkdown>
        </article>
      )}
    </div>
  )
}
