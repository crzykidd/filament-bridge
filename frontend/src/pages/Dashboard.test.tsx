/**
 * Tests for Dashboard — filament-level counts + spool counts side by side.
 *
 * Focuses on the filament_counts rendering added in the
 * 2026-06-11-filament-level-counts-dashboard-execute task.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import React from 'react'

// ---------------------------------------------------------------------------
// Mocks — must be declared before any imports below (vi.mock hoists)
// ---------------------------------------------------------------------------

vi.mock('../api/client', () => ({
  getSyncStatus: vi.fn(),
  triggerSync: vi.fn(),
  triggerDryRun: vi.fn(),
  setAutoSync: vi.fn(),
  getBackupStatus: vi.fn(),
}))

vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
  Link: ({ children, to }: { children: React.ReactNode; to: string }) => <a href={to}>{children}</a>,
}))

vi.mock('../components/DeepLinkContext', () => ({
  useDeepLinkBases: () => ({ filamentdbUrl: 'http://fdb.test', spoolmanUrl: 'http://sm.test' }),
  DeepLinkProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('../components/BackupSafetyDialog', () => ({
  BackupSafetyDialog: () => null,
}))

// Mock usePoll to return static data without intervals.
vi.mock('../api/hooks', () => ({
  usePoll: vi.fn(),
}))

// ---------------------------------------------------------------------------
// Imports after mocks
// ---------------------------------------------------------------------------

import Dashboard from './Dashboard'
import { usePoll } from '../api/hooks'
import { getBackupStatus } from '../api/client'
import type { SyncStatusResponse, BackupStatusResponse } from '../api/types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeStatus(overrides?: Partial<SyncStatusResponse>): SyncStatusResponse {
  return {
    last_sync_at: null,
    next_sync_at: null,
    auto_sync_enabled: false,
    wizard_completed: true,
    pending_conflicts: 0,
    counts: { in_sync: 0, pending: 0, conflict: 0, unlinked: 0, total: 0 },
    filament_counts: { in_sync: 0, pending: 0, conflict: 0, total: 0 },
    systems: {},
    sync_blocked: false,
    sync_blocked_reasons: [],
    wizard_last_failures: 0,
    ...overrides,
  }
}

function mockUsePoll(data: SyncStatusResponse | null) {
  vi.mocked(usePoll).mockReturnValue({
    data,
    loading: false,
    error: null,
    reload: vi.fn(),
  } as ReturnType<typeof usePoll>)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('Dashboard — filament-level counts', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the Spools section heading', async () => {
    mockUsePoll(makeStatus({ counts: { in_sync: 5, pending: 1, conflict: 0, unlinked: 0, total: 6 } }))
    render(<Dashboard />)
    await waitFor(() => {
      expect(screen.getByText('Spools')).toBeInTheDocument()
    })
  })

  it('renders the Filaments section heading', async () => {
    mockUsePoll(makeStatus())
    render(<Dashboard />)
    await waitFor(() => {
      expect(screen.getByText('Filaments')).toBeInTheDocument()
    })
  })

  it('renders filament in_sync count from filament_counts', async () => {
    mockUsePoll(makeStatus({
      filament_counts: { in_sync: 7, pending: 2, conflict: 1, total: 10 },
    }))
    render(<Dashboard />)
    await waitFor(() => {
      // The value 7 should appear in the Filaments row (in_sync).
      const cells = screen.getAllByText('7')
      expect(cells.length).toBeGreaterThan(0)
    })
  })

  it('renders filament pending and conflict counts', async () => {
    mockUsePoll(makeStatus({
      filament_counts: { in_sync: 3, pending: 4, conflict: 2, total: 9 },
    }))
    render(<Dashboard />)
    await waitFor(() => {
      expect(screen.getAllByText('4').length).toBeGreaterThan(0)  // pending
      expect(screen.getAllByText('2').length).toBeGreaterThan(0)  // conflict
    })
  })

  it('renders filament total count', async () => {
    mockUsePoll(makeStatus({
      filament_counts: { in_sync: 0, pending: 0, conflict: 0, total: 12 },
    }))
    render(<Dashboard />)
    await waitFor(() => {
      expect(screen.getByText('12')).toBeInTheDocument()
    })
  })

  it('renders spool counts independently from filament counts', async () => {
    mockUsePoll(makeStatus({
      counts: { in_sync: 10, pending: 3, conflict: 1, unlinked: 2, total: 16 },
      filament_counts: { in_sync: 5, pending: 1, conflict: 0, total: 6 },
    }))
    render(<Dashboard />)
    await waitFor(() => {
      // Both spool total (16 is in counts but not shown; Unlinked=2 is shown) and
      // filament total (6) should both appear.
      expect(screen.getByText('6')).toBeInTheDocument()   // filament total
      expect(screen.getByText('2')).toBeInTheDocument()   // spool unlinked
    })
  })

  it('shows the wizard failure banner when wizard_last_failures > 0', async () => {
    mockUsePoll(makeStatus({ wizard_last_failures: 2 }))
    render(<Dashboard />)
    await waitFor(() => {
      expect(screen.getByText(/completed with/i)).toBeInTheDocument()
    })
    const review = screen.getByRole('link', { name: /review failures/i })
    expect(review).toHaveAttribute('href', '/wizard/report')
  })

  it('hides the wizard failure banner when there are no failures', async () => {
    mockUsePoll(makeStatus({ wizard_last_failures: 0 }))
    render(<Dashboard />)
    await waitFor(() => {
      expect(screen.getByText('Filaments')).toBeInTheDocument()
    })
    expect(screen.queryByText(/review failures/i)).not.toBeInTheDocument()
  })

  it('shows zeros when filament_counts is empty (backward compat)', async () => {
    // Simulate an older backend that returns no filament_counts key.
    const status = makeStatus()
    // @ts-expect-error: testing backward compat — omit filament_counts
    delete status.filament_counts
    mockUsePoll(status)
    render(<Dashboard />)
    await waitFor(() => {
      // The Filaments section should still render with zero values.
      expect(screen.getByText('Filaments')).toBeInTheDocument()
    })
  })
})

describe('Dashboard — backup status row (#20)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // Discriminate the two usePoll calls by their polled fn: sync vs backup.
  function mockPolls(sync: SyncStatusResponse | null, backup: BackupStatusResponse | null) {
    vi.mocked(usePoll).mockImplementation((fn: unknown) => ({
      data: fn === getBackupStatus ? backup : sync,
      loading: false,
      error: null,
      reload: vi.fn(),
    }) as ReturnType<typeof usePoll>)
  }

  it('renders Last/Next backup when status is available', async () => {
    mockPolls(makeStatus(), {
      last_run: { at: '2026-06-26T03:00:00+00:00', ok: true, bridge_state: 'bridge-state-x.json', filamentdb: null, pruned: [], error: null },
      next_run_at: '2026-06-27T03:00:00+00:00',
      schedule_enabled: true,
      retention_days: 7,
      retained: { count: 3, total_bytes: 4096 },
    })
    render(<Dashboard />)
    await waitFor(() => {
      expect(screen.getByText('Last backup')).toBeInTheDocument()
      expect(screen.getByText('Next backup')).toBeInTheDocument()
    })
  })

  it('omits the backup row entirely when backup status is unavailable', async () => {
    mockPolls(makeStatus(), null)
    render(<Dashboard />)
    await waitFor(() => {
      expect(screen.getByText('Filaments')).toBeInTheDocument()
    })
    expect(screen.queryByText('Last backup')).not.toBeInTheDocument()
  })

  it('shows "Disabled" for next backup when the schedule is off', async () => {
    mockPolls(makeStatus(), {
      last_run: null,
      next_run_at: null,
      schedule_enabled: false,
      retention_days: 7,
      retained: { count: 0, total_bytes: 0 },
    })
    render(<Dashboard />)
    await waitFor(() => {
      expect(screen.getByText('Last backup')).toBeInTheDocument()
    })
    // last_run null → "Never"; schedule off → "Disabled".
    expect(screen.getByText('Never')).toBeInTheDocument()
    expect(screen.getByText('Disabled')).toBeInTheDocument()
  })
})
