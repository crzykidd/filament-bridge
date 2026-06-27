/**
 * Tests for WizardRunReport — the shared wizard-execute renderer used by both the
 * Step6 Execute result view and the persistent Failure Report page (issue #14).
 * Verifies the user requirement: failed records render FIRST (with reason), then successes.
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('./DeepLinks', () => ({
  DeepLinks: () => null,
}))

import { WizardRunReport } from './WizardRunReport'
import type { WizardExecuteRecord } from '../api/types'

function rec(over: Partial<WizardExecuteRecord>): WizardExecuteRecord {
  return { entity_type: 'spool', action: 'created', ...over } as WizardExecuteRecord
}

describe('WizardRunReport', () => {
  it('renders the failed section with label and error first, before the succeeded table', () => {
    const records: WizardExecuteRecord[] = [
      rec({ action: 'failed', label: 'Broken Spool', error: 'FDB 502 timeout' }),
      rec({ action: 'created', label: 'Good Spool' }),
    ]
    render(<WizardRunReport records={records} created={1} updated={0} skipped={0} failed={1} />)

    // Failed heading + reason are present.
    expect(screen.getByText(/Failed \(1\)/)).toBeInTheDocument()
    expect(screen.getByText('FDB 502 timeout')).toBeInTheDocument()

    // The failed label appears earlier in the DOM than the succeeded one.
    const failedEl = screen.getByText('Broken Spool')
    const okEl = screen.getByText('Good Spool')
    expect(failedEl.compareDocumentPosition(okEl) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('omits the failed section entirely when there are no failures', () => {
    const records = [rec({ action: 'created', label: 'Only Good' })]
    render(<WizardRunReport records={records} created={1} updated={0} skipped={0} failed={0} />)
    expect(screen.queryByText(/Failed \(/)).not.toBeInTheDocument()
    expect(screen.getByText('Only Good')).toBeInTheDocument()
  })

  it('hides the flat counter tiles when showCounters is false', () => {
    const records = [rec({ action: 'failed', label: 'X', error: 'boom' })]
    const { container } = render(
      <WizardRunReport records={records} created={0} updated={0} skipped={0} failed={1} showCounters={false} />,
    )
    // The counter grid uses grid-cols-4; with showCounters=false it should not render.
    expect(container.querySelector('.grid-cols-4')).toBeNull()
  })
})
