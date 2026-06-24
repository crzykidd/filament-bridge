/**
 * Frontend tests for the shared MobileSpoolUpdate component.
 *
 * Tests:
 *   - renders a fetched detail (brand, #number, current weights, location)
 *   - the net preview is computed from the entered gross weight minus tare
 *   - Save sends a PATCH with gross_grams + the default weight_mode
 *   - changing the weight-mode toggle is reflected in the PATCH body
 *   - a changed location is sent; an untouched location is omitted
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import React from 'react'

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client')
  return {
    ...actual,
    getMobileSpool: vi.fn(),
    getMobileLocations: vi.fn(),
    updateMobileSpool: vi.fn(),
  }
})

vi.mock('./DeepLinkContext', () => ({
  useDeepLinkBases: () => ({ filamentdbUrl: 'http://fdb.test', spoolmanUrl: 'http://sm.test' }),
}))

import { getMobileSpool, getMobileLocations, updateMobileSpool } from '../api/client'
import type { MobileSpoolDetail } from '../api/types'
import { MobileSpoolUpdate } from './MobileSpoolUpdate'

function makeDetail(overrides?: Partial<MobileSpoolDetail>): MobileSpoolDetail {
  return {
    filamentdb_filament_id: 'fil-001',
    filamentdb_spool_id: 'spool-001',
    spoolman_spool_id: 42,
    spoolman_filament_id: 7,
    number: 42,
    brand: 'ELEGOO',
    color_name: 'Red',
    color_hex: 'FF0000',
    material: 'PLA',
    gross: 1100,
    net: 900,
    tare: 200,
    location: 'Shelf A',
    weight_default_mode: 'direct_correction',
    ...overrides,
  }
}

describe('MobileSpoolUpdate', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(getMobileLocations as ReturnType<typeof vi.fn>).mockResolvedValue(['Shelf A', 'Dry box B'])
  })

  it('renders a fetched detail', async () => {
    ;(getMobileSpool as ReturnType<typeof vi.fn>).mockResolvedValue(makeDetail())
    render(<MobileSpoolUpdate filId="fil-001" spoolId="spool-001" />)

    await waitFor(() => expect(screen.getByText('ELEGOO')).toBeInTheDocument())
    expect(screen.getByText('#42')).toBeInTheDocument()
    // Current gross/net summary
    expect(screen.getByText('1100.0 g')).toBeInTheDocument()
    expect(screen.getByText('900.0 g')).toBeInTheDocument()
    expect(screen.getByText('Red')).toBeInTheDocument()
  })

  it('computes a live net preview from the entered gross weight minus tare', async () => {
    ;(getMobileSpool as ReturnType<typeof vi.fn>).mockResolvedValue(makeDetail({ tare: 200 }))
    render(<MobileSpoolUpdate filId="fil-001" spoolId="spool-001" />)

    await waitFor(() => expect(screen.getByText('ELEGOO')).toBeInTheDocument())
    const input = screen.getByLabelText(/scale weight/i)
    fireEvent.change(input, { target: { value: '1000' } })

    // 1000 gross − 200 tare = 800.0 g net preview
    await waitFor(() => expect(screen.getByText('800.0 g')).toBeInTheDocument())
  })

  it('Save sends a PATCH with gross_grams and the default weight_mode', async () => {
    ;(getMobileSpool as ReturnType<typeof vi.fn>).mockResolvedValue(makeDetail())
    ;(updateMobileSpool as ReturnType<typeof vi.fn>).mockResolvedValue(makeDetail({ gross: 1000, net: 800 }))
    render(<MobileSpoolUpdate filId="fil-001" spoolId="spool-001" />)

    await waitFor(() => expect(screen.getByText('ELEGOO')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText(/scale weight/i), { target: { value: '1000' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))

    await waitFor(() => expect(updateMobileSpool).toHaveBeenCalledTimes(1))
    expect(updateMobileSpool).toHaveBeenCalledWith('fil-001', 'spool-001', {
      gross_grams: 1000,
      weight_mode: 'direct_correction',
    })
  })

  it('reflects a weight-mode override in the PATCH body', async () => {
    ;(getMobileSpool as ReturnType<typeof vi.fn>).mockResolvedValue(makeDetail())
    ;(updateMobileSpool as ReturnType<typeof vi.fn>).mockResolvedValue(makeDetail())
    render(<MobileSpoolUpdate filId="fil-001" spoolId="spool-001" />)

    await waitFor(() => expect(screen.getByText('ELEGOO')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText(/scale weight/i), { target: { value: '950' } })
    fireEvent.click(screen.getByRole('button', { name: /log as usage/i }))
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))

    await waitFor(() => expect(updateMobileSpool).toHaveBeenCalledTimes(1))
    expect(updateMobileSpool).toHaveBeenCalledWith('fil-001', 'spool-001', {
      gross_grams: 950,
      weight_mode: 'usage',
    })
  })

  it('sends a changed location and omits an untouched one', async () => {
    ;(getMobileSpool as ReturnType<typeof vi.fn>).mockResolvedValue(makeDetail({ location: 'Shelf A' }))
    ;(updateMobileSpool as ReturnType<typeof vi.fn>).mockResolvedValue(makeDetail())
    render(<MobileSpoolUpdate filId="fil-001" spoolId="spool-001" />)

    await waitFor(() => expect(screen.getByText('ELEGOO')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText(/^location$/i), { target: { value: 'Dry box B' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))

    await waitFor(() => expect(updateMobileSpool).toHaveBeenCalledTimes(1))
    expect(updateMobileSpool).toHaveBeenCalledWith('fil-001', 'spool-001', {
      location: 'Dry box B',
      weight_mode: 'direct_correction',
    })
  })

  it('offers every known location in the dropdown, not just the current one', async () => {
    ;(getMobileSpool as ReturnType<typeof vi.fn>).mockResolvedValue(makeDetail({ location: 'Shelf A' }))
    ;(getMobileLocations as ReturnType<typeof vi.fn>).mockResolvedValue(['Shelf A', 'Dry box B', 'Bin C'])
    render(<MobileSpoolUpdate filId="fil-001" spoolId="spool-001" />)

    await waitFor(() => expect(screen.getByText('ELEGOO')).toBeInTheDocument())
    const select = screen.getByLabelText(/^location$/i) as HTMLSelectElement
    const optionValues = Array.from(select.options).map(o => o.value)
    // Every Filament DB / Spoolman location is selectable — not only the current bin.
    expect(optionValues).toContain('Shelf A')
    expect(optionValues).toContain('Dry box B')
    expect(optionValues).toContain('Bin C')
  })

  it('lets the user type a brand-new location via the dropdown escape hatch', async () => {
    ;(getMobileSpool as ReturnType<typeof vi.fn>).mockResolvedValue(makeDetail({ location: 'Shelf A' }))
    ;(updateMobileSpool as ReturnType<typeof vi.fn>).mockResolvedValue(makeDetail())
    render(<MobileSpoolUpdate filId="fil-001" spoolId="spool-001" />)

    await waitFor(() => expect(screen.getByText('ELEGOO')).toBeInTheDocument())
    // Choosing the "New location…" sentinel swaps the select for a text input.
    fireEvent.change(screen.getByLabelText(/^location$/i), { target: { value: '__new_location__' } })
    fireEvent.change(screen.getByLabelText(/^location$/i), { target: { value: 'Custom shelf' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))

    await waitFor(() => expect(updateMobileSpool).toHaveBeenCalledTimes(1))
    expect(updateMobileSpool).toHaveBeenCalledWith('fil-001', 'spool-001', {
      location: 'Custom shelf',
      weight_mode: 'direct_correction',
    })
  })

  it('shows an error banner when the detail fetch fails (e.g. feature disabled 403)', async () => {
    ;(getMobileSpool as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Mobile updates are disabled'))
    render(<MobileSpoolUpdate filId="fil-001" spoolId="spool-001" />)

    await waitFor(() =>
      expect(screen.getByText(/mobile updates are disabled/i)).toBeInTheDocument(),
    )
  })
})
