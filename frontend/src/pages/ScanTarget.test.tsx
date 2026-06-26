/**
 * Tests for ScanTarget — the bare QR scan-target page.
 *
 * Covers:
 *   - renders the search box and the MobileSpoolUpdate card
 *   - typing a query calls getMobileSpools and shows results
 *   - selecting a result navigates to /scan/<fil>/<spool>
 *   - no results message when the search returns empty
 *   - the search box is present even when filId/spoolId are missing
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import React from 'react'

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockNavigate = vi.fn()

vi.mock('react-router-dom', () => ({
  useParams: vi.fn(),
  useNavigate: () => mockNavigate,
}))

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client')
  return {
    ...actual,
    getMobileSpools: vi.fn(),
  }
})

vi.mock('../components/MobileSpoolUpdate', () => ({
  MobileSpoolUpdate: ({ filId, spoolId }: { filId: string; spoolId: string }) => (
    <div data-testid="mobile-spool-update">{filId}/{spoolId}</div>
  ),
}))

vi.mock('../components/ColorDisplay', () => ({
  ColorDisplay: () => <span data-testid="color-display" />,
}))

// ---------------------------------------------------------------------------
// Imports (after mocks)
// ---------------------------------------------------------------------------

import { useParams } from 'react-router-dom'
import { getMobileSpools } from '../api/client'
import type { MobileSpoolSearchResult } from '../api/types'
import ScanTarget from './ScanTarget'

function makeResult(overrides?: Partial<MobileSpoolSearchResult>): MobileSpoolSearchResult {
  return {
    filamentdb_filament_id: 'fil-001',
    filamentdb_spool_id: 'spool-001',
    spoolman_spool_id: 42,
    name: 'Galaxy Black',
    vendor: 'ELEGOO',
    color: 'FF0000',
    multi_color_hexes: null,
    multi_color_direction: null,
    ...overrides,
  }
}

describe('ScanTarget', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(useParams as ReturnType<typeof vi.fn>).mockReturnValue({ filId: 'fil-001', spoolId: 'spool-001' })
    ;(getMobileSpools as ReturnType<typeof vi.fn>).mockResolvedValue([])
  })

  it('renders the search box and the MobileSpoolUpdate card', () => {
    render(<ScanTarget />)
    expect(screen.getByRole('searchbox', { name: /search spools/i })).toBeInTheDocument()
    expect(screen.getByTestId('mobile-spool-update')).toBeInTheDocument()
    expect(screen.getByTestId('mobile-spool-update').textContent).toBe('fil-001/spool-001')
  })

  it('calls getMobileSpools after typing and shows results', async () => {
    ;(getMobileSpools as ReturnType<typeof vi.fn>).mockResolvedValue([makeResult()])
    render(<ScanTarget />)

    const input = screen.getByRole('searchbox', { name: /search spools/i })
    fireEvent.change(input, { target: { value: 'gal' } })

    await waitFor(() => expect(getMobileSpools).toHaveBeenCalledWith('gal'))
    await waitFor(() => expect(screen.getByText('Galaxy Black')).toBeInTheDocument())
    expect(screen.getByText('#42')).toBeInTheDocument()
    // Vendor is rendered inside a nested span as " · ELEGOO"; use regex to find it.
    expect(screen.getByText(/ELEGOO/)).toBeInTheDocument()
  })

  it('navigates to /scan/<fil>/<spool> when a result is selected', async () => {
    ;(getMobileSpools as ReturnType<typeof vi.fn>).mockResolvedValue([
      makeResult({ filamentdb_filament_id: 'fil-002', filamentdb_spool_id: 'spool-002', spoolman_spool_id: 7 }),
    ])
    render(<ScanTarget />)

    fireEvent.change(screen.getByRole('searchbox', { name: /search spools/i }), { target: { value: 'gal' } })
    await waitFor(() => screen.getByText('Galaxy Black'))

    fireEvent.click(screen.getByRole('button', { name: /galaxy black/i }))
    expect(mockNavigate).toHaveBeenCalledWith('/scan/fil-002/spool-002')
  })

  it('shows "No matching spools" when search returns empty', async () => {
    ;(getMobileSpools as ReturnType<typeof vi.fn>).mockResolvedValue([])
    render(<ScanTarget />)

    fireEvent.change(screen.getByRole('searchbox', { name: /search spools/i }), { target: { value: 'zzz' } })
    await waitFor(() => expect(getMobileSpools).toHaveBeenCalledWith('zzz'))
    await waitFor(() => expect(screen.getByText(/no matching spools/i)).toBeInTheDocument())
  })

  it('renders the search box even when filId/spoolId are missing', () => {
    ;(useParams as ReturnType<typeof vi.fn>).mockReturnValue({})
    render(<ScanTarget />)
    expect(screen.getByRole('searchbox', { name: /search spools/i })).toBeInTheDocument()
    expect(screen.getByText(/invalid scan link/i)).toBeInTheDocument()
  })
})
