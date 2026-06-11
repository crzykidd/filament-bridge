/**
 * Frontend tests for the Conflicts page:
 *   - Phase B master_divergence conflict card
 *   - ?highlight=<id> deep-link: expands + marks the matching row, graceful fallback
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import React from 'react'

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

// Mock the entire api/client module to avoid real network calls.
vi.mock('../api/client', () => ({
  getDivergenceContext: vi.fn(),
  resolveConflict: vi.fn(),
  getConflicts: vi.fn(),
  bulkResolveConflicts: vi.fn(),
}))

// Mock react-router-dom: provide a controllable useSearchParams.
const mockSetSearchParams = vi.fn()
let mockSearchParams = new URLSearchParams()

vi.mock('react-router-dom', () => ({
  useSearchParams: () => [mockSearchParams, mockSetSearchParams],
}))

// Mock DeepLinkContext to avoid the health endpoint call it makes on mount.
vi.mock('../components/DeepLinkContext', () => ({
  useDeepLinkBases: () => ({ filamentdbUrl: 'http://fdb.test', spoolmanUrl: 'http://sm.test' }),
  DeepLinkProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

// Mock ColorDisplay to keep rendering simple.
vi.mock('../components/ColorDisplay', () => ({
  ColorDisplay: () => null,
}))

// Mock useApi to control the conflict list without real fetch.
vi.mock('../api/hooks', () => ({
  useApi: vi.fn(),
}))

import { getDivergenceContext, resolveConflict } from '../api/client'
import { useApi } from '../api/hooks'
import type { ConflictResponse, DivergenceContextResponse } from '../api/types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeMasterDivergenceConflict(overrides?: Partial<ConflictResponse>): ConflictResponse {
  return {
    id: 1,
    status: 'open',
    entity_type: 'filament',
    field_name: 'density',
    conflict_type: 'master_divergence',
    spoolman_id: 42,
    filamentdb_filament_id: 'variant-001',
    filamentdb_spool_id: null,
    spoolman_value: 1.38,
    filamentdb_value: 1.24,
    detected_at: '2026-06-10T12:00:00Z',
    resolved_at: null,
    resolution: null,
    resolved_value: null,
    label: 'ELEGOO PLA Black',
    vendor: 'ELEGOO',
    name: 'PLA Black',
    color_hex: '111111',
    multi_color_hexes: null,
    multi_color_direction: null,
    material: 'PLA',
    ...overrides,
  }
}

function makeCrossSystemConflict(overrides?: Partial<ConflictResponse>): ConflictResponse {
  return {
    id: 2,
    status: 'open',
    entity_type: 'filament',
    field_name: 'density',
    conflict_type: 'cross_system',
    spoolman_id: 43,
    filamentdb_filament_id: 'fil-002',
    filamentdb_spool_id: null,
    spoolman_value: 1.38,
    filamentdb_value: 1.30,
    detected_at: '2026-06-10T11:00:00Z',
    resolved_at: null,
    resolution: null,
    resolved_value: null,
    label: 'ELEGOO PLA White',
    vendor: 'ELEGOO',
    name: 'PLA White',
    color_hex: 'ffffff',
    multi_color_hexes: null,
    multi_color_direction: null,
    material: 'PLA',
    ...overrides,
  }
}

const mockDivergenceContext: DivergenceContextResponse = {
  master_fdb_id: 'master-001',
  master_name: 'ELEGOO PLA',
  master_current_value: 1.30,
  field_name: 'density',
  fdb_path: 'density',
  variants: [
    {
      fdb_id: 'variant-001',
      name: 'PLA Black',
      color_hex: '111111',
      spoolman_filament_id: 42,
      current_value: 1.24,
      inherited: true,
    },
  ],
}

// ---------------------------------------------------------------------------
// Import the component under test AFTER mocks are set up.
// ---------------------------------------------------------------------------

// We test at the sub-component level by importing Conflicts as the default export
// and rendering with useApi returning a controlled conflict list.

// Import the Conflicts page (which contains MasterDivergenceDetail internally)
const ConflictsModule = await import('./Conflicts')
const Conflicts = ConflictsModule.default

// ---------------------------------------------------------------------------
// Wrapper that provides needed context
// ---------------------------------------------------------------------------

function renderConflictsWithData(conflicts: ConflictResponse[]) {
  const mockUseApi = vi.mocked(useApi)
  const reloadMock = vi.fn()
  mockUseApi.mockReturnValue({
    data: conflicts,
    loading: false,
    error: null,
    reload: reloadMock,
    refetch: reloadMock,
  })
  return render(<Conflicts />)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('Conflicts page — master_divergence card', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSearchParams = new URLSearchParams()
    // Default: divergence context fetch succeeds.
    vi.mocked(getDivergenceContext).mockResolvedValue(mockDivergenceContext)
    // Default: resolve succeeds.
    vi.mocked(resolveConflict).mockResolvedValue({
      ...makeMasterDivergenceConflict(),
      status: 'resolved',
      resolution: 'apply_all',
    })
  })

  it('renders a master_divergence conflict card with Master divergence badge', async () => {
    renderConflictsWithData([makeMasterDivergenceConflict()])

    await waitFor(() => {
      // The badge is a span with specific classes; use getAllByText and verify at least
      // one is a badge span.
      const elements = screen.getAllByText('Master divergence')
      const badge = elements.find(el => el.tagName === 'SPAN')
      expect(badge).toBeInTheDocument()
    })
  })

  it('does NOT show action buttons before the card is expanded', async () => {
    renderConflictsWithData([makeMasterDivergenceConflict()])

    await waitFor(() => {
      expect(screen.queryByText('Apply to all variants')).not.toBeInTheDocument()
    })
  })

  it('shows variant list and action buttons after expanding the card', async () => {
    renderConflictsWithData([makeMasterDivergenceConflict()])

    // Click to expand the card (click on the conflict row)
    const row = screen.getByText('ELEGOO PLA Black').closest('[class*="flex items-center"]')
    if (row) fireEvent.click(row)

    // Wait for the divergence context to load and buttons to appear
    await waitFor(() => {
      expect(screen.getByText('Apply to all variants')).toBeInTheDocument()
      expect(screen.getByText("Make variant's own setting")).toBeInTheDocument()
      expect(screen.getByText('Ignore')).toBeInTheDocument()
    })
  })

  it('calls getDivergenceContext when card is expanded', async () => {
    renderConflictsWithData([makeMasterDivergenceConflict()])

    const row = screen.getByText('ELEGOO PLA Black').closest('[class*="flex items-center"]')
    if (row) fireEvent.click(row)

    await waitFor(() => {
      expect(getDivergenceContext).toHaveBeenCalledWith(1)
    })
  })

  it('Apply to all variants shows confirm prompt before submitting', async () => {
    renderConflictsWithData([makeMasterDivergenceConflict()])

    const row = screen.getByText('ELEGOO PLA Black').closest('[class*="flex items-center"]')
    if (row) fireEvent.click(row)

    await waitFor(() => {
      expect(screen.getByText('Apply to all variants')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Apply to all variants'))

    await waitFor(() => {
      expect(screen.getByText('Confirm apply to all')).toBeInTheDocument()
    })

    // resolveConflict should NOT have been called yet
    expect(resolveConflict).not.toHaveBeenCalled()
  })

  it('calls resolveConflict with action=apply_all after confirmation', async () => {
    renderConflictsWithData([makeMasterDivergenceConflict()])

    const row = screen.getByText('ELEGOO PLA Black').closest('[class*="flex items-center"]')
    if (row) fireEvent.click(row)

    await waitFor(() => {
      expect(screen.getByText('Apply to all variants')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Apply to all variants'))

    await waitFor(() => {
      expect(screen.getByText('Confirm apply to all')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Confirm apply to all'))

    await waitFor(() => {
      expect(resolveConflict).toHaveBeenCalledWith(1, {
        resolution: 'spoolman',
        action: 'apply_all',
      })
    })
  })

  it('calls resolveConflict with action=variant_override', async () => {
    renderConflictsWithData([makeMasterDivergenceConflict()])

    const row = screen.getByText('ELEGOO PLA Black').closest('[class*="flex items-center"]')
    if (row) fireEvent.click(row)

    await waitFor(() => {
      expect(screen.getByText("Make variant's own setting")).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText("Make variant's own setting"))

    await waitFor(() => {
      expect(resolveConflict).toHaveBeenCalledWith(1, {
        resolution: 'spoolman',
        action: 'variant_override',
      })
    })
  })

  it('calls resolveConflict with action=ignore', async () => {
    renderConflictsWithData([makeMasterDivergenceConflict()])

    const row = screen.getByText('ELEGOO PLA Black').closest('[class*="flex items-center"]')
    if (row) fireEvent.click(row)

    await waitFor(() => {
      expect(screen.getByText('Ignore')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Ignore'))

    await waitFor(() => {
      expect(resolveConflict).toHaveBeenCalledWith(1, {
        resolution: 'spoolman',
        action: 'ignore',
      })
    })
  })
})

describe('Conflicts page — non-master_divergence conflict type', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSearchParams = new URLSearchParams()
  })

  it('renders standard resolution buttons for cross_system conflict', async () => {
    renderConflictsWithData([makeCrossSystemConflict()])

    // Expand the card
    const row = screen.getByText('ELEGOO PLA White').closest('[class*="flex items-center"]')
    if (row) fireEvent.click(row)

    await waitFor(() => {
      expect(screen.getByText('Use spoolman')).toBeInTheDocument()
      expect(screen.getByText('Use filamentdb')).toBeInTheDocument()
    })

    // Master divergence-specific buttons should NOT appear
    expect(screen.queryByText('Apply to all variants')).not.toBeInTheDocument()
    expect(screen.queryByText("Make variant's own setting")).not.toBeInTheDocument()
  })

  it('does NOT call getDivergenceContext for cross_system conflicts', async () => {
    renderConflictsWithData([makeCrossSystemConflict()])

    const row = screen.getByText('ELEGOO PLA White').closest('[class*="flex items-center"]')
    if (row) fireEvent.click(row)

    await waitFor(() => {
      expect(screen.getByText('Use spoolman')).toBeInTheDocument()
    })

    expect(getDivergenceContext).not.toHaveBeenCalled()
  })
})

// ---------------------------------------------------------------------------
// Highlight deep-link (from Synced Records "See conflict" button)
// ---------------------------------------------------------------------------

describe('Conflicts page — ?highlight=<id> deep-link', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSearchParams = new URLSearchParams()
    vi.mocked(getDivergenceContext).mockResolvedValue(mockDivergenceContext)
    vi.mocked(resolveConflict).mockResolvedValue({
      ...makeMasterDivergenceConflict(),
      status: 'resolved',
      resolution: 'spoolman',
    })
  })

  it('expands the matching conflict row when ?highlight=<id> is set', async () => {
    mockSearchParams = new URLSearchParams('highlight=2')
    renderConflictsWithData([makeCrossSystemConflict({ id: 2 })])

    // The row should be auto-expanded → resolution buttons visible
    await waitFor(() => {
      expect(screen.getByText('Use spoolman')).toBeInTheDocument()
    })
  })

  it('applies a highlight ring to the targeted conflict card', async () => {
    mockSearchParams = new URLSearchParams('highlight=2')
    renderConflictsWithData([makeCrossSystemConflict({ id: 2 })])

    await waitFor(() => {
      const card = document.querySelector('[data-conflict-id="2"]')
      expect(card).not.toBeNull()
      // The highlighted card should have the amber ring class applied
      expect(card?.className).toMatch(/ring-2/)
    })
  })

  it('shows a not-found notice when target conflict is not in the open list', async () => {
    mockSearchParams = new URLSearchParams('highlight=999')
    renderConflictsWithData([makeCrossSystemConflict({ id: 2 })])

    await waitFor(() => {
      expect(screen.getByText(/conflict #999 was not found/i)).toBeInTheDocument()
    })
  })

  it('does NOT expand or highlight when no ?highlight param is set', async () => {
    mockSearchParams = new URLSearchParams()
    renderConflictsWithData([makeCrossSystemConflict({ id: 2 })])

    // No auto-expand: resolution buttons should NOT be visible
    expect(screen.queryByText('Use spoolman')).not.toBeInTheDocument()

    const card = document.querySelector('[data-conflict-id="2"]')
    expect(card?.className).not.toMatch(/ring-2/)
  })
})
