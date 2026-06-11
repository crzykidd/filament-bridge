/**
 * Frontend tests for SyncedRecords — "See conflict" deep-link.
 *
 * Tests:
 *   - A conflict row with conflict_id renders the "See conflict" button.
 *   - Clicking "See conflict" navigates to /conflicts?highlight=<id>.
 *   - A non-conflict row does NOT show "See conflict".
 *   - A conflict row with conflict_id === null does NOT show "See conflict".
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import React from 'react'

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockNavigate = vi.fn()

vi.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
}))

vi.mock('../api/client', () => ({
  getMappings: vi.fn(),
}))

vi.mock('../components/DeepLinkContext', () => ({
  useDeepLinkBases: () => ({ filamentdbUrl: 'http://fdb.test', spoolmanUrl: 'http://sm.test' }),
  DeepLinkProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('../components/ColorDisplay', () => ({
  ColorDisplay: () => null,
}))

vi.mock('../components/DeepLinks', () => ({
  DeepLinks: () => null,
}))

vi.mock('../components/StatusBadge', () => ({
  StatusBadge: ({ status }: { status: string }) => <span data-testid="status-badge">{status}</span>,
}))

vi.mock('../api/hooks', () => ({
  useApi: vi.fn(),
}))

vi.mock('../utils/datetime', () => ({
  formatLocal: (v: string | null) => v ?? '—',
}))

import { useApi } from '../api/hooks'
import type { MappingRow } from '../api/types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeConflictRow(overrides?: Partial<MappingRow>): MappingRow {
  return {
    id: 1,
    status: 'conflict',
    spoolman_spool_id: 10,
    spoolman_filament_id: 5,
    filamentdb_filament_id: 'fil-001',
    filamentdb_spool_id: 'spool-001',
    filamentdb_parent_id: null,
    name: 'ELEGOO PLA Red',
    vendor: 'ELEGOO',
    color: 'FF0000',
    spoolman_weight: 300,
    filamentdb_weight: 500,
    last_synced: null,
    multi_color_hexes: null,
    multi_color_direction: null,
    remaining_weight: 300,
    is_empty: false,
    conflict_id: 42,
    detail: [],
    ...overrides,
  }
}

function makeInSyncRow(overrides?: Partial<MappingRow>): MappingRow {
  return {
    id: 2,
    status: 'in_sync',
    spoolman_spool_id: 20,
    spoolman_filament_id: 6,
    filamentdb_filament_id: 'fil-002',
    filamentdb_spool_id: 'spool-002',
    filamentdb_parent_id: null,
    name: 'ELEGOO PLA Blue',
    vendor: 'ELEGOO',
    color: '0000FF',
    spoolman_weight: 400,
    filamentdb_weight: 600,
    last_synced: null,
    multi_color_hexes: null,
    multi_color_direction: null,
    remaining_weight: 400,
    is_empty: false,
    conflict_id: null,
    detail: [],
    ...overrides,
  }
}

// ---------------------------------------------------------------------------
// Import component under test AFTER mocks
// ---------------------------------------------------------------------------

const SyncedRecordsModule = await import('./SyncedRecords')
const SyncedRecords = SyncedRecordsModule.default

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

function renderWithRows(rows: MappingRow[]) {
  vi.mocked(useApi).mockReturnValue({
    data: rows,
    loading: false,
    error: null,
    reload: vi.fn(),
    refetch: vi.fn(),
  })
  return render(<SyncedRecords />)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('SyncedRecords — "See conflict" link', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders "See conflict" button on a conflict row with conflict_id set', () => {
    renderWithRows([makeConflictRow()])
    expect(screen.getByRole('button', { name: /see conflict/i })).toBeInTheDocument()
  })

  it('clicking "See conflict" navigates to /conflicts?highlight=<conflict_id>', () => {
    renderWithRows([makeConflictRow({ conflict_id: 42 })])
    fireEvent.click(screen.getByRole('button', { name: /see conflict/i }))
    expect(mockNavigate).toHaveBeenCalledWith('/conflicts?highlight=42')
  })

  it('does NOT render "See conflict" on an in_sync row', () => {
    renderWithRows([makeInSyncRow()])
    expect(screen.queryByRole('button', { name: /see conflict/i })).not.toBeInTheDocument()
  })

  it('does NOT render "See conflict" when conflict row has conflict_id === null', () => {
    renderWithRows([makeConflictRow({ conflict_id: null })])
    expect(screen.queryByRole('button', { name: /see conflict/i })).not.toBeInTheDocument()
  })

  it('renders "See conflict" for each distinct conflict row when multiple are shown', () => {
    renderWithRows([
      makeConflictRow({ id: 1, spoolman_spool_id: 10, conflict_id: 42 }),
      makeConflictRow({ id: 2, spoolman_spool_id: 11, conflict_id: 99 }),
    ])
    const buttons = screen.getAllByRole('button', { name: /see conflict/i })
    expect(buttons).toHaveLength(2)
  })
})
