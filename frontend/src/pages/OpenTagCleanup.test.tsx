/**
 * Tests for OpenTagCleanup — formatMatchAge unit tests and a render smoke test
 * to catch use-before-declare / TDZ crashes that tsc/vitest unit tests miss.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { formatMatchAge } from '../utils/datetime'

// ---------------------------------------------------------------------------
// formatMatchAge unit tests
// ---------------------------------------------------------------------------

describe('formatMatchAge', () => {
  it('returns "just now" for a very recent timestamp', () => {
    const ts = new Date(Date.now() - 10_000).toISOString()
    expect(formatMatchAge(ts)).toBe('just now')
  })

  it('formats minutes correctly', () => {
    const ts = new Date(Date.now() - 5 * 60_000).toISOString()
    expect(formatMatchAge(ts)).toBe('5 minutes ago')
  })

  it('uses singular for 1 minute', () => {
    const ts = new Date(Date.now() - 60_000).toISOString()
    expect(formatMatchAge(ts)).toBe('1 minute ago')
  })

  it('formats hours correctly', () => {
    const ts = new Date(Date.now() - 18 * 3_600_000).toISOString()
    expect(formatMatchAge(ts)).toBe('18 hours ago')
  })

  it('uses singular for 1 hour', () => {
    const ts = new Date(Date.now() - 3_600_000).toISOString()
    expect(formatMatchAge(ts)).toBe('1 hour ago')
  })

  it('formats days correctly', () => {
    const ts = new Date(Date.now() - 2 * 86_400_000).toISOString()
    expect(formatMatchAge(ts)).toBe('2 days ago')
  })

  it('uses singular for 1 day', () => {
    const ts = new Date(Date.now() - 86_400_000).toISOString()
    expect(formatMatchAge(ts)).toBe('1 day ago')
  })

  it('returns "never" for null', () => {
    expect(formatMatchAge(null)).toBe('never')
  })
})

// ---------------------------------------------------------------------------
// OpenTagCleanup render smoke test
// ---------------------------------------------------------------------------

vi.mock('../api/client', () => ({
  getOpenTagStatus: vi.fn().mockResolvedValue(null),
  getOpenTagMatches: vi.fn().mockResolvedValue({ matches: [], updates_count: 0, stale_inputs: false, computed_at: null, dataset: { fetched_at: null, count: 0, stale: false } }),
  postOpenTagRefresh: vi.fn().mockResolvedValue({ unchanged: false, count: 0, fetched_at: null, commit_sha: null }),
  postOpenTagApply: vi.fn().mockResolvedValue({ results: [] }),
  postOpenTagIgnore: vi.fn().mockResolvedValue({}),
  getOpenTagSearch: vi.fn().mockResolvedValue([]),
  getOpenTagMissingValues: vi.fn().mockResolvedValue({ items: [], audited_fields: [] }),
  getAuthStatus: vi.fn(),
  getVersionInfo: vi.fn(),
  register401Handler: vi.fn(),
}))

vi.mock('../components/DeepLinks', () => ({
  DeepLinks: () => null,
}))

vi.mock('../components/BackupSafetyDialog', () => ({
  BackupSafetyDialog: () => null,
}))

vi.mock('../components/HelpTip', () => ({
  HelpTip: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('../components/WizardActionBar', () => ({
  WizardActionBar: () => null,
}))

vi.mock('../components/DeepLinkContext', () => ({
  DeepLinkProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useDeepLinkConfig: () => ({ filamentDbUrl: 'http://fdb', spoolmanUrl: 'http://sm' }),
}))

describe('OpenTagCleanup render smoke test', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('mounts without crashing and shows the toolbar', async () => {
    const { default: OpenTagCleanup } = await import('./OpenTagCleanup')
    render(<OpenTagCleanup />)
    // Verify the main action buttons are rendered
    expect(screen.getByRole('button', { name: /Matches/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Re-match/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Force re-download dataset/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Show missing values/i })).toBeInTheDocument()
  })
})
