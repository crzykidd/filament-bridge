/**
 * Frontend tests for the shared PrintLabelButton (phase 3).
 *
 * Tests:
 *   - clicking Print calls printLabel(fil, spool, false) and shows the job number
 *   - a 409 media-mismatch surfaces the error + a "Print anyway" retry that
 *     re-sends with override=true
 *   - a non-409 error shows the LabelForge detail and offers no override
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import React from 'react'

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client')
  return { ...actual, printLabel: vi.fn() }
})

import { printLabel, BridgeApiError } from '../api/client'
import { PrintLabelButton } from './PrintLabelButton'

describe('PrintLabelButton', () => {
  beforeEach(() => vi.clearAllMocks())

  it('prints and shows the job number', async () => {
    ;(printLabel as ReturnType<typeof vi.fn>).mockResolvedValue({ job_id: 9, status: 'ok' })
    render(<PrintLabelButton filId="fil-1" spoolId="spool-1" />)

    fireEvent.click(screen.getByRole('button', { name: /print label/i }))
    await waitFor(() => expect(screen.getByText(/printed — job #9/i)).toBeInTheDocument())
    expect(printLabel).toHaveBeenCalledWith('fil-1', 'spool-1', false)
  })

  it('offers a "Print anyway" override on a 409 media mismatch', async () => {
    ;(printLabel as ReturnType<typeof vi.fn>)
      .mockRejectedValueOnce(
        new BridgeApiError(409, 'media_mismatch', 'Printer has 29 loaded, template expects 62.'),
      )
      .mockResolvedValueOnce({ job_id: 12, status: 'ok' })
    render(<PrintLabelButton filId="fil-1" spoolId="spool-1" />)

    fireEvent.click(screen.getByRole('button', { name: /^print label$/i }))
    await waitFor(() => expect(screen.getByText(/29 loaded/i)).toBeInTheDocument())

    const overrideBtn = screen.getByRole('button', { name: /print anyway/i })
    fireEvent.click(overrideBtn)
    await waitFor(() => expect(screen.getByText(/printed — job #12/i)).toBeInTheDocument())
    expect(printLabel).toHaveBeenNthCalledWith(2, 'fil-1', 'spool-1', true)
  })

  it('shows a non-409 error with no override option', async () => {
    ;(printLabel as ReturnType<typeof vi.fn>).mockRejectedValue(
      new BridgeApiError(400, 'labelforge_error', "Missing required field: 'brand'"),
    )
    render(<PrintLabelButton filId="fil-1" spoolId="spool-1" />)

    fireEvent.click(screen.getByRole('button', { name: /print label/i }))
    await waitFor(() => expect(screen.getByText(/missing required field/i)).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /print anyway/i })).not.toBeInTheDocument()
  })
})
