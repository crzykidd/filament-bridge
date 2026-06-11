/**
 * Tests for DocsViewer:
 *  - renders fetched markdown content
 *  - rewrites a relative .md link to /docs/<slug>
 *  - shows not-found state on HTTP 404
 *  - shows not-found state when slug contains invalid characters
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import React from 'react'

// ---------------------------------------------------------------------------
// Mocks — must come before the module import
// ---------------------------------------------------------------------------

// Capture the slug passed to useParams so we can control it per test
let _slug: string | undefined = 'README'

vi.mock('react-router-dom', () => ({
  useParams: () => ({ slug: _slug }),
  Link: ({ to, children, ...rest }: { to: string; children: React.ReactNode; [k: string]: unknown }) => (
    <a href={to} {...rest}>
      {children}
    </a>
  ),
}))

// ---------------------------------------------------------------------------
// Module import AFTER mocks
// ---------------------------------------------------------------------------

const { default: DocsViewer } = await import('./DocsViewer')

// ---------------------------------------------------------------------------
// fetch mock helpers
// ---------------------------------------------------------------------------

function mockFetchOk(body: string) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      text: () => Promise.resolve(body),
    }),
  )
}

function mockFetch404() {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: false,
      text: () => Promise.resolve(''),
    }),
  )
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('DocsViewer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    _slug = undefined // default: no slug → README
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders fetched markdown content', async () => {
    mockFetchOk('# Hello World\n\nThis is a paragraph.')
    _slug = undefined

    render(<DocsViewer />)

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /hello world/i })).toBeInTheDocument()
    })
    expect(screen.getByText(/this is a paragraph/i)).toBeInTheDocument()
  })

  it('rewrites a relative .md link to /docs/<slug>', async () => {
    mockFetchOk('[See config](configuration.md)')
    _slug = 'README'

    render(<DocsViewer />)

    await waitFor(() => {
      const link = screen.getByRole('link', { name: /see config/i })
      expect(link).toHaveAttribute('href', '/docs/configuration')
    })
  })

  it('rewrites a relative .md link that includes an anchor', async () => {
    mockFetchOk('[Details](variant-parent-mode.md#section)')
    _slug = 'README'

    render(<DocsViewer />)

    await waitFor(() => {
      const link = screen.getByRole('link', { name: /details/i })
      // The anchor is preserved in the href
      expect(link).toHaveAttribute('href', '/docs/variant-parent-mode#section')
    })
  })

  it('shows not-found state on HTTP 404', async () => {
    mockFetch404()
    _slug = 'nonexistent-doc'

    render(<DocsViewer />)

    await waitFor(() => {
      expect(screen.getByText(/doc not found/i)).toBeInTheDocument()
    })
  })

  it('shows not-found state when slug contains invalid characters', async () => {
    // Fetch should NOT be called for an invalid slug
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    _slug = '../etc/passwd'

    render(<DocsViewer />)

    await waitFor(() => {
      expect(screen.getByText(/doc not found/i)).toBeInTheDocument()
    })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('external links open in a new tab', async () => {
    mockFetchOk('[GitHub](https://github.com/example)')
    _slug = 'README'

    render(<DocsViewer />)

    await waitFor(() => {
      const link = screen.getByRole('link', { name: /github/i })
      expect(link).toHaveAttribute('href', 'https://github.com/example')
      expect(link).toHaveAttribute('target', '_blank')
    })
  })
})
