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
    logMobileDryCycle: vi.fn(),
    getMobilePrinters: vi.fn(),
    getMobileSpoolAssignment: vi.fn(),
    setMobileSpoolAssignment: vi.fn(),
    clearMobileSpoolAssignment: vi.fn(),
  }
})

vi.mock('./DeepLinkContext', () => ({
  useDeepLinkBases: () => ({ filamentdbUrl: 'http://fdb.test', spoolmanUrl: 'http://sm.test' }),
}))

import {
  getMobileSpool,
  getMobileLocations,
  updateMobileSpool,
  logMobileDryCycle,
  getMobilePrinters,
  getMobileSpoolAssignment,
  setMobileSpoolAssignment,
  clearMobileSpoolAssignment,
} from '../api/client'
import type { MobileSpoolDetail, MobilePrinter, MobileSpoolAssignment } from '../api/types'
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
    recommended_drying_temp_c: 65,
    recommended_drying_time_min: 240,
    last_dried_at: null,
    dry_cycle_count: null,
    ...overrides,
  }
}

const makePrinter = (overrides?: Partial<MobilePrinter>): MobilePrinter => ({
  printer_id: 'printer-1',
  printer_name: 'Bambu X1C',
  slots: [
    { slot_id: 'slot-1', slot_name: 'AMS 1', spool_id: null, filament_id: null },
    { slot_id: 'slot-2', slot_name: 'AMS 2', spool_id: 'spool-999', filament_id: 'fil-999' },
  ],
  ...overrides,
})

const makeAssignment = (overrides?: Partial<MobileSpoolAssignment>): MobileSpoolAssignment => ({
  printer_id: 'printer-1',
  printer_name: 'Bambu X1C',
  slot_id: 'slot-1',
  slot_name: 'AMS 1',
  filament_id: 'fil-001',
  ...overrides,
})

describe('MobileSpoolUpdate', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(getMobileLocations as ReturnType<typeof vi.fn>).mockResolvedValue(['Shelf A', 'Dry box B'])
    ;(getMobilePrinters as ReturnType<typeof vi.fn>).mockResolvedValue([])
    ;(getMobileSpoolAssignment as ReturnType<typeof vi.fn>).mockResolvedValue(null)
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

  // ---------------------------------------------------------------------------
  // Dry cycle section
  // ---------------------------------------------------------------------------

  it('renders the Log dry cycle section with temp/duration prefilled from recommended values', async () => {
    ;(getMobileSpool as ReturnType<typeof vi.fn>).mockResolvedValue(
      makeDetail({ recommended_drying_temp_c: 65, recommended_drying_time_min: 240 }),
    )
    render(<MobileSpoolUpdate filId="fil-001" spoolId="spool-001" />)

    await waitFor(() => expect(screen.getByText('ELEGOO')).toBeInTheDocument())
    expect(screen.getByLabelText(/temperature/i)).toHaveValue('65')
    expect(screen.getByLabelText(/duration/i)).toHaveValue('240')
    expect(screen.getByRole('button', { name: /log dry cycle/i })).toBeInTheDocument()
  })

  it('clicking Log dry cycle calls logMobileDryCycle with prefilled values', async () => {
    ;(getMobileSpool as ReturnType<typeof vi.fn>).mockResolvedValue(
      makeDetail({ recommended_drying_temp_c: 65, recommended_drying_time_min: 240 }),
    )
    ;(logMobileDryCycle as ReturnType<typeof vi.fn>).mockResolvedValue(makeDetail())
    render(<MobileSpoolUpdate filId="fil-001" spoolId="spool-001" />)

    await waitFor(() => expect(screen.getByText('ELEGOO')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /log dry cycle/i }))

    await waitFor(() => expect(logMobileDryCycle).toHaveBeenCalledTimes(1))
    expect(logMobileDryCycle).toHaveBeenCalledWith('fil-001', 'spool-001', expect.objectContaining({
      temp_c: 65,
      duration_min: 240,
    }))
  })

  it('clicking Save does NOT call logMobileDryCycle', async () => {
    ;(getMobileSpool as ReturnType<typeof vi.fn>).mockResolvedValue(makeDetail())
    ;(updateMobileSpool as ReturnType<typeof vi.fn>).mockResolvedValue(makeDetail())
    render(<MobileSpoolUpdate filId="fil-001" spoolId="spool-001" />)

    await waitFor(() => expect(screen.getByText('ELEGOO')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText(/scale weight/i), { target: { value: '1000' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))

    await waitFor(() => expect(updateMobileSpool).toHaveBeenCalledTimes(1))
    expect(logMobileDryCycle).not.toHaveBeenCalled()
  })

  // ---------------------------------------------------------------------------
  // Printer slot picker section — render smoke test + occupied-slot detection
  // ---------------------------------------------------------------------------

  it('renders the Printer slot section', async () => {
    ;(getMobileSpool as ReturnType<typeof vi.fn>).mockResolvedValue(makeDetail())
    render(<MobileSpoolUpdate filId="fil-001" spoolId="spool-001" />)

    await waitFor(() => expect(screen.getByText('ELEGOO')).toBeInTheDocument())
    // The section heading must be present
    expect(screen.getByText(/printer slot/i)).toBeInTheDocument()
  })

  it('shows "Currently unassigned" when the assignment is null', async () => {
    ;(getMobileSpool as ReturnType<typeof vi.fn>).mockResolvedValue(makeDetail())
    ;(getMobileSpoolAssignment as ReturnType<typeof vi.fn>).mockResolvedValue(null)
    render(<MobileSpoolUpdate filId="fil-001" spoolId="spool-001" />)

    await waitFor(() => expect(screen.getByText('ELEGOO')).toBeInTheDocument())
    await waitFor(() => expect(screen.getByText(/currently unassigned/i)).toBeInTheDocument())
  })

  it('shows the current assignment when one exists', async () => {
    ;(getMobileSpool as ReturnType<typeof vi.fn>).mockResolvedValue(makeDetail())
    ;(getMobileSpoolAssignment as ReturnType<typeof vi.fn>).mockResolvedValue(makeAssignment())
    render(<MobileSpoolUpdate filId="fil-001" spoolId="spool-001" />)

    await waitFor(() => expect(screen.getByText('ELEGOO')).toBeInTheDocument())
    await waitFor(() =>
      expect(screen.getByText(/bambu x1c.*ams 1/i)).toBeInTheDocument()
    )
  })

  it('shows the printer select when printers are available', async () => {
    ;(getMobileSpool as ReturnType<typeof vi.fn>).mockResolvedValue(makeDetail())
    ;(getMobilePrinters as ReturnType<typeof vi.fn>).mockResolvedValue([makePrinter()])
    render(<MobileSpoolUpdate filId="fil-001" spoolId="spool-001" />)

    await waitFor(() => expect(screen.getByText('ELEGOO')).toBeInTheDocument())
    await waitFor(() =>
      expect(screen.getByLabelText(/^printer$/i)).toBeInTheDocument()
    )
    expect(screen.getByRole('option', { name: 'Bambu X1C' })).toBeInTheDocument()
  })

  it('shows the slot select after a printer is selected', async () => {
    ;(getMobileSpool as ReturnType<typeof vi.fn>).mockResolvedValue(makeDetail())
    ;(getMobilePrinters as ReturnType<typeof vi.fn>).mockResolvedValue([makePrinter()])
    render(<MobileSpoolUpdate filId="fil-001" spoolId="spool-001" />)

    await waitFor(() => expect(screen.getByText('ELEGOO')).toBeInTheDocument())
    await waitFor(() => expect(screen.getByLabelText(/^printer$/i)).toBeInTheDocument())

    fireEvent.change(screen.getByLabelText(/^printer$/i), { target: { value: 'printer-1' } })

    await waitFor(() => expect(screen.getByLabelText(/^slot$/i)).toBeInTheDocument())
  })

  it('shows occupied warning when choosing a slot held by a different spool', async () => {
    ;(getMobileSpool as ReturnType<typeof vi.fn>).mockResolvedValue(makeDetail())
    ;(getMobilePrinters as ReturnType<typeof vi.fn>).mockResolvedValue([makePrinter()])
    render(<MobileSpoolUpdate filId="fil-001" spoolId="spool-001" />)

    await waitFor(() => expect(screen.getByText('ELEGOO')).toBeInTheDocument())
    await waitFor(() => expect(screen.getByLabelText(/^printer$/i)).toBeInTheDocument())

    fireEvent.change(screen.getByLabelText(/^printer$/i), { target: { value: 'printer-1' } })
    await waitFor(() => expect(screen.getByLabelText(/^slot$/i)).toBeInTheDocument())

    // slot-2 is occupied by spool-999 (not our spool spool-001)
    fireEvent.change(screen.getByLabelText(/^slot$/i), { target: { value: 'slot-2' } })

    await waitFor(() =>
      expect(screen.getByText(/occupied by another spool/i)).toBeInTheDocument()
    )
  })

  it('does NOT show occupied warning when choosing our own current slot', async () => {
    ;(getMobileSpool as ReturnType<typeof vi.fn>).mockResolvedValue(makeDetail())
    // Slot-1 is occupied by our own spool ('spool-001')
    const printer = makePrinter({
      slots: [
        { slot_id: 'slot-1', slot_name: 'AMS 1', spool_id: 'spool-001', filament_id: 'fil-001' },
      ],
    })
    ;(getMobilePrinters as ReturnType<typeof vi.fn>).mockResolvedValue([printer])
    render(<MobileSpoolUpdate filId="fil-001" spoolId="spool-001" />)

    await waitFor(() => expect(screen.getByText('ELEGOO')).toBeInTheDocument())
    await waitFor(() => expect(screen.getByLabelText(/^printer$/i)).toBeInTheDocument())

    fireEvent.change(screen.getByLabelText(/^printer$/i), { target: { value: 'printer-1' } })
    await waitFor(() => expect(screen.getByLabelText(/^slot$/i)).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText(/^slot$/i), { target: { value: 'slot-1' } })

    expect(screen.queryByText(/occupied by another spool/i)).not.toBeInTheDocument()
  })

  it('disables the slot picker with a message when the spool is retired', async () => {
    ;(getMobileSpool as ReturnType<typeof vi.fn>).mockResolvedValue(makeDetail({ is_retired: true }))
    ;(getMobilePrinters as ReturnType<typeof vi.fn>).mockResolvedValue([makePrinter()])
    render(<MobileSpoolUpdate filId="fil-001" spoolId="spool-001" />)

    await waitFor(() => expect(screen.getByText('ELEGOO')).toBeInTheDocument())
    await waitFor(() =>
      expect(screen.getByText(/this spool is retired/i)).toBeInTheDocument()
    )
    // The printer select must not appear
    expect(screen.queryByLabelText(/^printer$/i)).not.toBeInTheDocument()
  })

  it('clicking Assign calls setMobileSpoolAssignment with selected printer+slot', async () => {
    ;(getMobileSpool as ReturnType<typeof vi.fn>).mockResolvedValue(makeDetail())
    ;(getMobilePrinters as ReturnType<typeof vi.fn>).mockResolvedValue([makePrinter()])
    ;(getMobileSpoolAssignment as ReturnType<typeof vi.fn>).mockResolvedValue(null)
    ;(setMobileSpoolAssignment as ReturnType<typeof vi.fn>).mockResolvedValue(makeAssignment())
    render(<MobileSpoolUpdate filId="fil-001" spoolId="spool-001" />)

    await waitFor(() => expect(screen.getByText('ELEGOO')).toBeInTheDocument())
    await waitFor(() => expect(screen.getByLabelText(/^printer$/i)).toBeInTheDocument())

    fireEvent.change(screen.getByLabelText(/^printer$/i), { target: { value: 'printer-1' } })
    await waitFor(() => expect(screen.getByLabelText(/^slot$/i)).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText(/^slot$/i), { target: { value: 'slot-1' } })

    fireEvent.click(screen.getByRole('button', { name: /^assign$/i }))

    await waitFor(() => expect(setMobileSpoolAssignment).toHaveBeenCalledWith(
      'fil-001', 'spool-001', { printer_id: 'printer-1', slot_id: 'slot-1' },
    ))
    await waitFor(() => expect(screen.getByText(/assigned\./i)).toBeInTheDocument())
  })

  it('clicking Clear calls clearMobileSpoolAssignment', async () => {
    ;(getMobileSpool as ReturnType<typeof vi.fn>).mockResolvedValue(makeDetail())
    ;(getMobilePrinters as ReturnType<typeof vi.fn>).mockResolvedValue([makePrinter()])
    ;(getMobileSpoolAssignment as ReturnType<typeof vi.fn>).mockResolvedValue(makeAssignment())
    ;(clearMobileSpoolAssignment as ReturnType<typeof vi.fn>).mockResolvedValue(null)
    render(<MobileSpoolUpdate filId="fil-001" spoolId="spool-001" />)

    await waitFor(() => expect(screen.getByText('ELEGOO')).toBeInTheDocument())
    await waitFor(() => expect(screen.getByRole('button', { name: /^clear$/i })).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: /^clear$/i }))

    await waitFor(() => expect(clearMobileSpoolAssignment).toHaveBeenCalledWith('fil-001', 'spool-001'))
    await waitFor(() => expect(screen.getByText(/assignment cleared/i)).toBeInTheDocument())
  })
})
