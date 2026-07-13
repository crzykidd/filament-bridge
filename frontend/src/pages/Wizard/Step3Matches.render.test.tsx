/**
 * Render smoke test for Step3Matches — the FDB→Spoolman selectable-import feature.
 *
 * In the filamentdb_to_spoolman direction, an unmatched Filament DB filament must
 * render a "create in Spoolman" checkbox (unchecked by default — check to include),
 * a master must NOT, and ticking a row must send it in fdb_selection on save.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import React from 'react'

vi.mock('../../api/client', () => ({
  getWizardMatches: vi.fn(),
  postWizardMatches: vi.fn(),
}))
vi.mock('../../api/hooks', () => ({ useApi: vi.fn() }))
vi.mock('../../components/DeepLinks', () => ({ DeepLinks: () => null }))
vi.mock('../../components/HelpTip', () => ({ HelpTip: () => null }))
vi.mock('../../components/OptBadge', () => ({ OptBadge: () => null }))
vi.mock('../../components/WizardActionBar', () => ({
  WizardActionBar: ({ onNext, nextLabel }: { onNext: () => void; nextLabel: string }) => (
    <button onClick={onNext}>{nextLabel}</button>
  ),
}))

import Step3Matches from './Step3Matches'
import { useApi } from '../../api/hooks'
import { postWizardMatches } from '../../api/client'
import type { WizardMatchesResponse } from '../../api/types'

function makeMatches(over?: Partial<WizardMatchesResponse>): WizardMatchesResponse {
  return {
    matched: [],
    unmatched_spoolman: [],
    unmatched_filamentdb: [
      { filamentdb_filament_id: 'v1', name: 'Ultraglow Green', vendor: 'Prusament', material: 'PETG', is_master_container: false } as any,
      { filamentdb_filament_id: 'm1', name: 'Ultraglow (Master)', vendor: 'Prusament', material: 'PETG', is_master_container: true } as any,
    ],
    ambiguous: [],
    saved_decisions: [],
    import_direction: 'filamentdb_to_spoolman',
    saved_fdb_selection: [],
    ...over,
  }
}

const ctx = { next: vi.fn(), prev: vi.fn(), goTo: vi.fn(), step: 2, tareOverrides: [], setTareOverrides: vi.fn() }

beforeEach(() => {
  vi.clearAllMocks()
  ;(useApi as any).mockReturnValue({ data: makeMatches(), loading: false, error: null, reload: vi.fn() })
  ;(postWizardMatches as any).mockResolvedValue({ persisted: 0 })
})

describe('Step3Matches — FDB→SM selectable import', () => {
  it('renders the unmatched FDB filament with a create/skip control, unchecked by default', async () => {
    render(<Step3Matches {...(ctx as any)} />)
    await waitFor(() => expect(screen.getByText('Ultraglow Green')).toBeInTheDocument())
    // Default is "check to include", so the row shows the "Skip" hint until ticked.
    expect(screen.getAllByText('Skip').length).toBeGreaterThan(0)
  })

  it('ticking the unmatched FDB row sends it in fdb_selection on save', async () => {
    const { container } = render(<Step3Matches {...(ctx as any)} />)
    await waitFor(() => expect(screen.getByText('Ultraglow Green')).toBeInTheDocument())

    // Click the checkbox inside the variant's own row.
    const row = screen.getByText('Ultraglow Green').closest('.py-3') as HTMLElement
    fireEvent.click(row.querySelector('input[type="checkbox"]') as HTMLInputElement)

    fireEvent.click(screen.getAllByText('Save & Next →')[0])
    await waitFor(() => expect(postWizardMatches).toHaveBeenCalled())
    const body = (postWizardMatches as any).mock.calls[0][0]
    expect(body.fdb_selection).toContain('v1')       // the variant is selected
    expect(body.fdb_selection).not.toContain('m1')   // the master never is
  })
})
