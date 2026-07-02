/**
 * Frontend tests for SyncedRecords:
 *
 * Existing:
 *   - "See conflict" deep-link behaviour
 *   - Sortable columns
 *   - Filament-only rows (kind="filament")
 *
 * New (issue #40 — Unlink action):
 *   - Render smoke test: mounts with spool rows without crash
 *   - Unlink: spool row shows "Unlink" button in expanded detail; clicking it shows
 *     the confirm panel; confirming calls deleteMapping and reloads
 *   - Filament-only rows do NOT show the Unlink button
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
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
  getVersionInfo: vi.fn(() => Promise.resolve({ mobile_labels_enabled: false })),
  deleteMapping: vi.fn(),
  printLabel: vi.fn(),
  BridgeApiError: class BridgeApiError extends Error {
    constructor(public status: number, public code: string, message: string) {
      super(message)
      this.name = 'BridgeApiError'
    }
  },
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
  parseUtc: (v: string) => new Date(v),
}))

import { useApi } from '../api/hooks'
import { deleteMapping } from '../api/client'
import type { MappingRow } from '../api/types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeConflictRow(overrides?: Partial<MappingRow>): MappingRow {
  return {
    id: 1,
    status: 'conflict',
    kind: 'spool',
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
    kind: 'spool',
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

function makeFilamentOnlyRow(overrides?: Partial<MappingRow>): MappingRow {
  return {
    id: 99,
    status: 'pending',
    kind: 'filament',
    spoolman_spool_id: null,
    spoolman_filament_id: 115,
    filamentdb_filament_id: 'fil-115',
    filamentdb_spool_id: null,
    filamentdb_parent_id: null,
    name: 'PLA Grey',
    vendor: 'ELEGOO',
    color: '808080',
    spoolman_weight: null,
    filamentdb_weight: null,
    last_synced: null,
    multi_color_hexes: null,
    multi_color_direction: null,
    remaining_weight: null,
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

const reloadMock = vi.fn().mockResolvedValue(undefined)

function renderWithRows(rows: MappingRow[]) {
  vi.mocked(useApi).mockReturnValue({
    data: rows,
    loading: false,
    error: null,
    reload: reloadMock,
    refetch: reloadMock,
  })
  return render(<SyncedRecords />)
}

/** Expand a row by clicking its name cell. */
function expandRow(name: string) {
  fireEvent.click(screen.getByText(name))
}

// ---------------------------------------------------------------------------
// Smoke test
// ---------------------------------------------------------------------------

describe('SyncedRecords — render smoke test', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('mounts with spool rows without crash', () => {
    renderWithRows([makeInSyncRow(), makeConflictRow()])
    expect(screen.getByText('ELEGOO PLA Blue')).toBeInTheDocument()
    expect(screen.getByText('ELEGOO PLA Red')).toBeInTheDocument()
  })

  it('mounts with filament-only rows without crash', () => {
    renderWithRows([makeFilamentOnlyRow()])
    expect(screen.getByText('PLA Grey')).toBeInTheDocument()
  })

  it('mounts with empty data without crash', () => {
    renderWithRows([])
    expect(screen.getByText('No records')).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Unlink action
// ---------------------------------------------------------------------------

describe('SyncedRecords — Unlink action', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows Unlink button in expanded spool row detail', () => {
    renderWithRows([makeInSyncRow()])
    expandRow('ELEGOO PLA Blue')
    expect(screen.getByRole('button', { name: /^unlink$/i })).toBeInTheDocument()
  })

  it('clicking Unlink shows the confirm panel with bridge-local disclaimer', () => {
    renderWithRows([makeInSyncRow()])
    expandRow('ELEGOO PLA Blue')
    fireEvent.click(screen.getByRole('button', { name: /^unlink$/i }))
    expect(screen.getByText(/not deleted or modified/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /yes, unlink/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /cancel/i })).toBeInTheDocument()
  })

  it('confirming Unlink calls deleteMapping with the row id and reloads', async () => {
    vi.mocked(deleteMapping).mockResolvedValue(undefined)
    renderWithRows([makeInSyncRow({ id: 7 })])
    expandRow('ELEGOO PLA Blue')
    fireEvent.click(screen.getByRole('button', { name: /^unlink$/i }))
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /yes, unlink/i }))
    })
    await waitFor(() => {
      expect(deleteMapping).toHaveBeenCalledWith(7)
      expect(reloadMock).toHaveBeenCalled()
    })
  })

  it('Cancel hides the confirm panel without calling deleteMapping', () => {
    renderWithRows([makeInSyncRow()])
    expandRow('ELEGOO PLA Blue')
    fireEvent.click(screen.getByRole('button', { name: /^unlink$/i }))
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }))
    expect(screen.queryByText(/not deleted or modified/i)).not.toBeInTheDocument()
    expect(deleteMapping).not.toHaveBeenCalled()
  })

  it('shows error message when deleteMapping rejects', async () => {
    const { BridgeApiError } = await import('../api/client')
    vi.mocked(deleteMapping).mockRejectedValue(new BridgeApiError(404, 'mapping_not_found', 'No such mapping'))
    renderWithRows([makeInSyncRow()])
    expandRow('ELEGOO PLA Blue')
    fireEvent.click(screen.getByRole('button', { name: /^unlink$/i }))
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /yes, unlink/i }))
    })
    await waitFor(() => {
      expect(screen.getByText(/no such mapping/i)).toBeInTheDocument()
    })
  })

  it('does NOT show Unlink button for filament-only rows', () => {
    renderWithRows([makeFilamentOnlyRow()])
    expandRow('PLA Grey')
    expect(screen.queryByRole('button', { name: /^unlink$/i })).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Weight (net) / (gross) labels in the expanded detail grid (#55)
// ---------------------------------------------------------------------------

describe('SyncedRecords — Weight net/gross labels', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('labels the expanded Weight row (net) on Spoolman and (gross) on Filament DB', () => {
    renderWithRows([makeInSyncRow({
      detail: [{ field: 'weight', label: 'Weight', spoolman: 300, filamentdb: 500 }],
    })])
    expandRow('ELEGOO PLA Blue')
    expect(screen.getByText('(net)')).toBeInTheDocument()
    expect(screen.getByText('(gross)')).toBeInTheDocument()
  })

  it('omits the suffix on an empty weight side', () => {
    renderWithRows([makeInSyncRow({
      detail: [{ field: 'weight', label: 'Weight', spoolman: 300, filamentdb: null }],
    })])
    expandRow('ELEGOO PLA Blue')
    expect(screen.getByText('(net)')).toBeInTheDocument()
    expect(screen.queryByText('(gross)')).not.toBeInTheDocument()
  })

  it('does not label non-weight detail rows', () => {
    renderWithRows([makeInSyncRow({
      detail: [{ field: 'material', label: 'Material', spoolman: 'PLA', filamentdb: 'PLA' }],
    })])
    expandRow('ELEGOO PLA Blue')
    expect(screen.queryByText('(net)')).not.toBeInTheDocument()
    expect(screen.queryByText('(gross)')).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// "See conflict" deep-link (existing tests — must still pass)
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

describe('SyncedRecords — sortable columns', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  const rowA = makeInSyncRow({ id: 1, name: 'Charlie', vendor: 'Zeta', spoolman_weight: 100, filamentdb_weight: 900 })
  const rowB = makeInSyncRow({ id: 2, name: 'Alpha', vendor: 'Mu', spoolman_weight: 300, filamentdb_weight: 500 })
  const rowC = makeInSyncRow({ id: 3, name: 'Bravo', vendor: 'Aardvark', spoolman_weight: 200, filamentdb_weight: 700 })

  // Read the rendered name column (td:nth-child(2)) in DOM order, skipping the header row.
  function rowNames(): string[] {
    return screen.getAllByRole('row')
      .slice(1)
      .map(r => (r.querySelector('td:nth-child(2)')?.textContent ?? '').trim())
  }

  it('sorts by Name ascending, then descending on a second click', () => {
    renderWithRows([rowA, rowB, rowC])
    fireEvent.click(screen.getByText('Name'))
    expect(rowNames()).toEqual(['Alpha', 'Bravo', 'Charlie'])
    fireEvent.click(screen.getByText('Name'))
    expect(rowNames()).toEqual(['Charlie', 'Bravo', 'Alpha'])
  })

  it('sorts by SM weight numerically (not lexically)', () => {
    renderWithRows([rowA, rowB, rowC])
    fireEvent.click(screen.getByText('SM weight'))
    expect(rowNames()).toEqual(['Charlie', 'Bravo', 'Alpha']) // 100, 200, 300
  })

  it('sorts by Vendor ascending', () => {
    renderWithRows([rowA, rowB, rowC])
    fireEvent.click(screen.getByText('Vendor'))
    expect(rowNames()).toEqual(['Bravo', 'Alpha', 'Charlie']) // Aardvark, Mu, Zeta
  })

  it('keeps rows with a missing weight value last in both directions', () => {
    const noWeight = makeInSyncRow({ id: 4, name: 'NoWeight', spoolman_weight: null })
    renderWithRows([rowB, noWeight]) // Alpha=300, NoWeight=null
    fireEvent.click(screen.getByText('SM weight')) // asc
    expect(rowNames()).toEqual(['Alpha', 'NoWeight'])
    fireEvent.click(screen.getByText('SM weight')) // desc — null still last
    expect(rowNames()).toEqual(['Alpha', 'NoWeight'])
  })
})

describe('SyncedRecords — filament-only rows (kind="filament")', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders a filament-only row with name and "(filament only)" hint', () => {
    renderWithRows([makeFilamentOnlyRow()])
    expect(screen.getByText('PLA Grey')).toBeInTheDocument()
    expect(screen.getByText('(filament only)')).toBeInTheDocument()
  })

  it('renders filament-only and spool rows together without crash', () => {
    renderWithRows([makeFilamentOnlyRow(), makeInSyncRow()])
    expect(screen.getByText('PLA Grey')).toBeInTheDocument()
    expect(screen.getByText('ELEGOO PLA Blue')).toBeInTheDocument()
  })

  it('filament-only row does not show "See conflict" when conflict_id is null', () => {
    renderWithRows([makeFilamentOnlyRow({ conflict_id: null })])
    expect(screen.queryByRole('button', { name: /see conflict/i })).not.toBeInTheDocument()
  })

  it('filament-only row shows "See conflict" when conflict_id is set', () => {
    renderWithRows([makeFilamentOnlyRow({ status: 'conflict', conflict_id: 77 })])
    expect(screen.getByRole('button', { name: /see conflict/i })).toBeInTheDocument()
  })
})
