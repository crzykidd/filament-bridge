/**
 * Tests for the Master Defaults backfill page (issue #76).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import React from 'react'
import type { MasterDefaultsResponse } from '../../api/types'

vi.mock('../../api/client', () => ({
  getMasterDefaults: vi.fn(),
  applyMasterDefaults: vi.fn(),
}))

vi.mock('../../components/DeepLinks', () => ({
  DeepLinks: () => null,
}))

vi.mock('../../components/HelpTip', () => ({
  HelpTip: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

import { getMasterDefaults, applyMasterDefaults } from '../../api/client'

const fillableRow: MasterDefaultsResponse['rows'][number] = {
  filamentdb_id: 'm1',
  name: 'Acme PLA (Master)',
  vendor: 'Acme',
  is_synthetic: false,
  spoolman_filament_id: 101,
  variant_count: 3,
  fields: {
    spool_weight: {
      current: null, current_sm: null, proposal: 200, would_fill: true,
      breakdown: [
        { filamentdb_id: 'v1', name: 'Acme PLA Red', value: 200 },
        { filamentdb_id: 'v2', name: 'Acme PLA Blue', value: 200 },
      ],
    },
    nozzle_temp: { current: null, current_sm: null, proposal: null, would_fill: false, breakdown: [] },
    bed_temp: { current: null, current_sm: null, proposal: null, would_fill: false, breakdown: [] },
    density: { current: null, current_sm: null, proposal: null, would_fill: false, breakdown: [] },
    diameter: { current: null, current_sm: null, proposal: null, would_fill: false, breakdown: [] },
    type: { current: 'PLA', current_sm: 'PLA', proposal: 'PLA', would_fill: false, breakdown: [] },
  },
}

const upToDateRow: MasterDefaultsResponse['rows'][number] = {
  filamentdb_id: 'm2',
  name: 'Acme PETG (Master)',
  vendor: 'Acme',
  is_synthetic: true,
  spoolman_filament_id: null,
  variant_count: 2,
  fields: {
    spool_weight: { current: 180, current_sm: null, proposal: 180, would_fill: false, breakdown: [] },
    nozzle_temp: { current: null, current_sm: null, proposal: null, would_fill: false, breakdown: [] },
    bed_temp: { current: null, current_sm: null, proposal: null, would_fill: false, breakdown: [] },
    density: { current: null, current_sm: null, proposal: null, would_fill: false, breakdown: [] },
    diameter: { current: null, current_sm: null, proposal: null, would_fill: false, breakdown: [] },
    type: { current: 'PETG', current_sm: null, proposal: 'PETG', would_fill: false, breakdown: [] },
  },
}

const MasterDefaultsModule = await import('./index')
const MasterDefaults = MasterDefaultsModule.default

describe('MasterDefaults page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the fillable field with its proposed value', async () => {
    vi.mocked(getMasterDefaults).mockResolvedValue({ rows: [fillableRow] })

    render(<MasterDefaults />)

    await waitFor(() => {
      expect(screen.getByText('Acme PLA (Master)')).toBeInTheDocument()
      expect(screen.getByText('Tare (spool weight)')).toBeInTheDocument()
      expect(screen.getByText('200 g')).toBeInTheDocument()
    })
  })

  it('hides masters with nothing to fill when the toggle is on (default)', async () => {
    vi.mocked(getMasterDefaults).mockResolvedValue({ rows: [fillableRow, upToDateRow] })

    render(<MasterDefaults />)

    await waitFor(() => expect(screen.getByText('Acme PLA (Master)')).toBeInTheDocument())
    expect(screen.queryByText('Acme PETG (Master)')).not.toBeInTheDocument()
  })

  it('shows up-to-date masters once the toggle is switched off', async () => {
    vi.mocked(getMasterDefaults).mockResolvedValue({ rows: [fillableRow, upToDateRow] })

    render(<MasterDefaults />)
    await waitFor(() => expect(screen.getByText('Acme PLA (Master)')).toBeInTheDocument())

    fireEvent.click(screen.getByText(/Only masters with something to fill/i))

    await waitFor(() => {
      expect(screen.getByText('Acme PETG (Master)')).toBeInTheDocument()
      expect(screen.getByText(/Nothing to fill/i)).toBeInTheDocument()
    })
  })

  it('selecting a field and applying calls applyMasterDefaults with the right payload', async () => {
    vi.mocked(getMasterDefaults).mockResolvedValue({ rows: [fillableRow] })
    vi.mocked(applyMasterDefaults).mockResolvedValue({ updated: 1, failed: [] })

    render(<MasterDefaults />)
    await waitFor(() => expect(screen.getByText('Tare (spool weight)')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('checkbox', { name: /Fill Tare \(spool weight\)/i }))

    const applyBtn = screen.getByRole('button', { name: /Apply 1 field/i })
    expect(applyBtn).not.toBeDisabled()
    fireEvent.click(applyBtn)

    await waitFor(() => {
      expect(applyMasterDefaults).toHaveBeenCalledWith([
        { filamentdb_id: 'm1', fields: ['spool_weight'] },
      ])
    })
  })

  it('Apply is disabled with nothing selected', async () => {
    vi.mocked(getMasterDefaults).mockResolvedValue({ rows: [fillableRow] })

    render(<MasterDefaults />)
    await waitFor(() => expect(screen.getByText('Tare (spool weight)')).toBeInTheDocument())

    expect(screen.getByRole('button', { name: /Apply 0 fields/i })).toBeDisabled()
  })

  it('shows the failed reason after a partial apply failure', async () => {
    vi.mocked(getMasterDefaults).mockResolvedValue({ rows: [fillableRow] })
    vi.mocked(applyMasterDefaults).mockResolvedValue({
      updated: 0,
      failed: [{ filamentdb_id: 'm1', error: 'upstream write failed' }],
    })

    render(<MasterDefaults />)
    await waitFor(() => expect(screen.getByText('Tare (spool weight)')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('checkbox', { name: /Fill Tare \(spool weight\)/i }))
    fireEvent.click(screen.getByRole('button', { name: /Apply 1 field/i }))

    await waitFor(() => {
      expect(screen.getByText(/upstream write failed/i)).toBeInTheDocument()
    })
  })
})
