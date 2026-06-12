/**
 * Frontend tests for the Conflicts page:
 *   - Phase B master_divergence conflict card
 *   - ?highlight=<id> deep-link: expands + marks the matching row, graceful fallback
 *   - Per-type detail panel (entity label, side-by-side values)
 *   - new_spool / new_filament Add flow (wired to importConflictRecord)
 *   - Bulk Add button appears for importable selections
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
  importConflictRecord: vi.fn(),
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

import { getDivergenceContext, resolveConflict, importConflictRecord } from '../api/client'
import { useApi } from '../api/hooks'
import type { ConflictResponse, DivergenceContextResponse, WizardExecuteResponse } from '../api/types'

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

function makeNewSpoolConflict(overrides?: Partial<ConflictResponse>): ConflictResponse {
  return {
    id: 3,
    status: 'open',
    entity_type: 'spool',
    field_name: 'new_spool',
    conflict_type: 'cross_system',
    spoolman_id: 55,
    filamentdb_filament_id: null,
    filamentdb_spool_id: null,
    spoolman_value: null,
    filamentdb_value: null,
    detected_at: '2026-06-10T13:00:00Z',
    resolved_at: null,
    resolution: null,
    resolved_value: null,
    label: 'ELEGOO PLA Red Spool',
    vendor: 'ELEGOO',
    name: 'PLA Red',
    color_hex: 'ff0000',
    multi_color_hexes: null,
    multi_color_direction: null,
    material: 'PLA',
    ...overrides,
  }
}

function makeNewFilamentConflict(overrides?: Partial<ConflictResponse>): ConflictResponse {
  return {
    id: 4,
    status: 'open',
    entity_type: 'filament',
    field_name: 'new_filament',
    conflict_type: 'cross_system',
    spoolman_id: 77,
    filamentdb_filament_id: null,
    filamentdb_spool_id: null,
    spoolman_value: null,
    filamentdb_value: null,
    detected_at: '2026-06-10T14:00:00Z',
    resolved_at: null,
    resolution: null,
    resolved_value: null,
    label: 'Bambu PLA Basic Blue',
    vendor: 'Bambu',
    name: 'PLA Basic Blue',
    color_hex: '0000ff',
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

const mockImportResponse: WizardExecuteResponse = {
  cycle_id: 'test-cycle-1',
  direction: 'spoolman_to_filamentdb',
  created: 1,
  updated: 0,
  skipped: 0,
  failed: 0,
  wizard_completed: false,
  records: [
    {
      entity_type: 'filament',
      action: 'created',
      spoolman_filament_id: 77,
      spoolman_spool_id: null,
      filamentdb_filament_id: 'new-fdb-id',
      filamentdb_spool_id: null,
      label: 'Bambu PLA Basic Blue',
      detail: null,
      error: null,
    },
  ],
  created_filaments: 1,
  created_spools: 0,
  updated_filaments: 0,
  updated_spools: 0,
  skipped_filaments: 0,
  skipped_spools: 0,
  failed_filaments: 0,
  failed_spools: 0,
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
// Tests — master_divergence
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

  it('shows FILAMENT entity label in master_divergence expanded panel', async () => {
    renderConflictsWithData([makeMasterDivergenceConflict()])

    const row = screen.getByText('ELEGOO PLA Black').closest('[class*="flex items-center"]')
    if (row) fireEvent.click(row)

    await waitFor(() => {
      expect(screen.getByText('FILAMENT')).toBeInTheDocument()
    })
  })
})

// ---------------------------------------------------------------------------
// Tests — non-master_divergence conflict types
// ---------------------------------------------------------------------------

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
      expect(screen.getByText('Use Spoolman')).toBeInTheDocument()
      expect(screen.getByText('Use Filament DB')).toBeInTheDocument()
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
      expect(screen.getByText('Use Spoolman')).toBeInTheDocument()
    })

    expect(getDivergenceContext).not.toHaveBeenCalled()
  })

  it('shows side-by-side field values for cross_system conflict', async () => {
    renderConflictsWithData([makeCrossSystemConflict()])

    const row = screen.getByText('ELEGOO PLA White').closest('[class*="flex items-center"]')
    if (row) fireEvent.click(row)

    await waitFor(() => {
      // The side-by-side grid shows "Spoolman" and "Filament DB" column headers
      expect(screen.getByText('Spoolman')).toBeInTheDocument()
      expect(screen.getByText('Filament DB')).toBeInTheDocument()
    })
  })

  it('shows FILAMENT entity label for a filament conflict', async () => {
    renderConflictsWithData([makeCrossSystemConflict()])

    const row = screen.getByText('ELEGOO PLA White').closest('[class*="flex items-center"]')
    if (row) fireEvent.click(row)

    await waitFor(() => {
      expect(screen.getByText('FILAMENT')).toBeInTheDocument()
    })
  })

  it('shows SPOOL entity label for a spool conflict', async () => {
    // cross_system conflict on a spool (not new_spool)
    renderConflictsWithData([makeCrossSystemConflict({ id: 5, entity_type: 'spool', label: 'SM Spool Weight' })])

    const row = screen.getByText('SM Spool Weight').closest('[class*="flex items-center"]')
    if (row) fireEvent.click(row)

    await waitFor(() => {
      expect(screen.getByText('SPOOL')).toBeInTheDocument()
    })
  })
})

// ---------------------------------------------------------------------------
// Tests — new_spool "Add" flow
// ---------------------------------------------------------------------------

describe('Conflicts page — new_spool Add flow', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSearchParams = new URLSearchParams()
    vi.mocked(importConflictRecord).mockResolvedValue(mockImportResponse)
    vi.mocked(resolveConflict).mockResolvedValue({
      ...makeNewSpoolConflict(),
      status: 'resolved',
      resolution: 'spoolman',
    })
  })

  it('renders "New spool (Spoolman)" badge for new_spool conflict with spoolman_id set', async () => {
    renderConflictsWithData([makeNewSpoolConflict()])

    await waitFor(() => {
      const elements = screen.getAllByText('New spool (Spoolman)')
      const badge = elements.find(el => el.tagName === 'SPAN')
      expect(badge).toBeInTheDocument()
    })
  })

  it('shows Add and Dismiss buttons when new_spool card is expanded', async () => {
    renderConflictsWithData([makeNewSpoolConflict()])

    const row = screen.getByText('ELEGOO PLA Red Spool').closest('[class*="flex items-center"]')
    if (row) fireEvent.click(row)

    await waitFor(() => {
      expect(screen.getByText('Add')).toBeInTheDocument()
      expect(screen.getByText('Dismiss')).toBeInTheDocument()
    })
  })

  it('clicking Add opens the import form with Preview import button', async () => {
    renderConflictsWithData([makeNewSpoolConflict()])

    const row = screen.getByText('ELEGOO PLA Red Spool').closest('[class*="flex items-center"]')
    if (row) fireEvent.click(row)

    await waitFor(() => expect(screen.getByText('Add')).toBeInTheDocument())

    fireEvent.click(screen.getByText('Add'))

    await waitFor(() => {
      expect(screen.getByText('Preview import')).toBeInTheDocument()
    })
  })

  it('preview calls importConflictRecord with dry_run=true', async () => {
    renderConflictsWithData([makeNewSpoolConflict()])

    const row = screen.getByText('ELEGOO PLA Red Spool').closest('[class*="flex items-center"]')
    if (row) fireEvent.click(row)

    await waitFor(() => expect(screen.getByText('Add')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Add'))
    await waitFor(() => expect(screen.getByText('Preview import')).toBeInTheDocument())

    fireEvent.click(screen.getByText('Preview import'))

    await waitFor(() => {
      expect(importConflictRecord).toHaveBeenCalledWith(3, expect.objectContaining({ dry_run: true }))
    })
  })

  it('shows preview results after dry run succeeds', async () => {
    renderConflictsWithData([makeNewSpoolConflict()])

    const row = screen.getByText('ELEGOO PLA Red Spool').closest('[class*="flex items-center"]')
    if (row) fireEvent.click(row)

    await waitFor(() => expect(screen.getByText('Add')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Add'))
    await waitFor(() => expect(screen.getByText('Preview import')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Preview import'))

    await waitFor(() => {
      expect(screen.getByText('Preview')).toBeInTheDocument()
      expect(screen.getByText('Confirm import')).toBeInTheDocument()
    })
  })

  it('confirm import calls importConflictRecord with dry_run=false', async () => {
    renderConflictsWithData([makeNewSpoolConflict()])

    const row = screen.getByText('ELEGOO PLA Red Spool').closest('[class*="flex items-center"]')
    if (row) fireEvent.click(row)

    await waitFor(() => expect(screen.getByText('Add')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Add'))
    await waitFor(() => expect(screen.getByText('Preview import')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Preview import'))
    await waitFor(() => expect(screen.getByText('Confirm import')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Confirm import'))

    await waitFor(() => {
      expect(importConflictRecord).toHaveBeenCalledWith(3, expect.objectContaining({ dry_run: false }))
    })
  })

  it('Dismiss calls resolveConflict with resolution=spoolman (not the import endpoint)', async () => {
    renderConflictsWithData([makeNewSpoolConflict()])

    const row = screen.getByText('ELEGOO PLA Red Spool').closest('[class*="flex items-center"]')
    if (row) fireEvent.click(row)

    await waitFor(() => expect(screen.getByText('Dismiss')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Dismiss'))

    await waitFor(() => {
      expect(resolveConflict).toHaveBeenCalledWith(3, expect.objectContaining({ resolution: 'spoolman' }))
    })
    expect(importConflictRecord).not.toHaveBeenCalled()
  })
})

// ---------------------------------------------------------------------------
// Tests — new_filament conflict
// ---------------------------------------------------------------------------

describe('Conflicts page — new_filament conflict', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSearchParams = new URLSearchParams()
    vi.mocked(importConflictRecord).mockResolvedValue(mockImportResponse)
  })

  it('renders "New filament (Spoolman)" badge for new_filament with spoolman_id set', async () => {
    renderConflictsWithData([makeNewFilamentConflict()])

    await waitFor(() => {
      const elements = screen.getAllByText('New filament (Spoolman)')
      const badge = elements.find(el => el.tagName === 'SPAN')
      expect(badge).toBeInTheDocument()
    })
  })

  it('shows Add and Dismiss buttons for new_filament conflict', async () => {
    renderConflictsWithData([makeNewFilamentConflict()])

    const row = screen.getByText('Bambu PLA Basic Blue').closest('[class*="flex items-center"]')
    if (row) fireEvent.click(row)

    await waitFor(() => {
      expect(screen.getByText('Add')).toBeInTheDocument()
      expect(screen.getByText('Dismiss')).toBeInTheDocument()
    })
  })

  it('does NOT call importConflictRecord before user clicks Preview import', async () => {
    renderConflictsWithData([makeNewFilamentConflict()])

    const row = screen.getByText('Bambu PLA Basic Blue').closest('[class*="flex items-center"]')
    if (row) fireEvent.click(row)

    await waitFor(() => expect(screen.getByText('Add')).toBeInTheDocument())

    expect(importConflictRecord).not.toHaveBeenCalled()
  })
})

// ---------------------------------------------------------------------------
// Tests — bulk Add
// ---------------------------------------------------------------------------

describe('Conflicts page — bulk Add', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSearchParams = new URLSearchParams()
    vi.mocked(importConflictRecord).mockResolvedValue(mockImportResponse)
  })

  it('shows "Add selected" button when importable conflicts are checked', async () => {
    renderConflictsWithData([makeNewSpoolConflict()])

    // Check the checkbox
    const checkbox = screen.getByRole('checkbox')
    fireEvent.click(checkbox)

    await waitFor(() => {
      expect(screen.getByText('Add selected')).toBeInTheDocument()
    })
  })

  it('does NOT show "Add selected" button when only non-importable conflicts are checked', async () => {
    renderConflictsWithData([makeCrossSystemConflict()])

    const checkbox = screen.getByRole('checkbox')
    fireEvent.click(checkbox)

    await waitFor(() => {
      // Bulk resolve bar appears but not Add selected
      expect(screen.getByText('Bulk resolve')).toBeInTheDocument()
    })
    expect(screen.queryByText('Add selected')).not.toBeInTheDocument()
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
      expect(screen.getByText('Use Spoolman')).toBeInTheDocument()
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
    expect(screen.queryByText('Use Spoolman')).not.toBeInTheDocument()

    const card = document.querySelector('[data-conflict-id="2"]')
    expect(card?.className).not.toMatch(/ring-2/)
  })
})

// ---------------------------------------------------------------------------
// Tests — identity on new_filament / new_spool cards (Bug 2)
// ---------------------------------------------------------------------------

describe('Conflicts page — identity on new_filament / new_spool cards', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSearchParams = new URLSearchParams()
    vi.mocked(importConflictRecord).mockResolvedValue(mockImportResponse)
    vi.mocked(resolveConflict).mockResolvedValue({
      ...makeNewFilamentConflict(),
      status: 'resolved',
      resolution: 'spoolman',
    })
  })

  it('shows vendor · name (id) identity line in the detail panel for a new_filament conflict', async () => {
    renderConflictsWithData([makeNewFilamentConflict()])

    const row = screen.getByText('Bambu PLA Basic Blue').closest('[class*="flex items-center"]')
    if (row) fireEvent.click(row)

    await waitFor(() => {
      // The newRecordIdentityLine renders "Bambu · PLA Basic Blue (SM #77)" with the · separator
      expect(screen.getByText('Bambu · PLA Basic Blue (SM #77)')).toBeInTheDocument()
    })
  })

  it('shows vendor · name (id) identity line in the detail panel for a new_spool conflict', async () => {
    vi.mocked(resolveConflict).mockResolvedValue({
      ...makeNewSpoolConflict(),
      status: 'resolved',
      resolution: 'spoolman',
    })
    renderConflictsWithData([makeNewSpoolConflict()])

    const row = screen.getByText('ELEGOO PLA Red Spool').closest('[class*="flex items-center"]')
    if (row) fireEvent.click(row)

    await waitFor(() => {
      // "ELEGOO · PLA Red (SM #55)" — dot-separated identity line in the detail panel
      expect(screen.getByText('ELEGOO · PLA Red (SM #55)')).toBeInTheDocument()
    })
  })

  it('degrades gracefully for a legacy new_filament conflict with no vendor/name', async () => {
    const legacy = makeNewFilamentConflict({
      vendor: null,
      name: null,
      color_hex: null,
      label: 'SM #77',
    })
    renderConflictsWithData([legacy])

    const row = screen.getByText('SM #77').closest('[class*="flex items-center"]')
    if (row) fireEvent.click(row)

    // Should show the standard description without crashing.
    await waitFor(() => {
      expect(screen.getByText('Add')).toBeInTheDocument()
      expect(screen.getByText('Dismiss')).toBeInTheDocument()
    })
    // No identity line when vendor/name are null (graceful fallback)
    expect(screen.queryByText(/·/)).not.toBeInTheDocument()
  })
})
