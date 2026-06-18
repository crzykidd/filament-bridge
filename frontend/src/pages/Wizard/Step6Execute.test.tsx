/**
 * Tests for Step6Execute — the Bulk Import execute step.
 *
 * Focus: the execute result view must clearly show failed records with their
 * label + exact error message (per the 2026-06-10-wizard-import-failure-visibility
 * handoff prompt). Created/updated/skipped records should also appear in the
 * main table.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import React from 'react'

// ---------------------------------------------------------------------------
// Mocks — all vi.mock calls are hoisted; they run before any imports below.
// ---------------------------------------------------------------------------

// Mock the api/client module to avoid real network calls.
vi.mock('../../api/client', () => ({
  postWizardExecute: vi.fn(),
}))

// Mock DeepLinkContext to avoid the health endpoint call on mount.
vi.mock('../../components/DeepLinkContext', () => ({
  useDeepLinkBases: () => ({ filamentdbUrl: 'http://fdb.test', spoolmanUrl: 'http://sm.test' }),
  DeepLinkProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

// BackupSafetyDialog mock: when open=true, immediately call onProceed so that
// the execute flow runs without requiring a user click on the dialog.
vi.mock('../../components/BackupSafetyDialog', () => ({
  BackupSafetyDialog: ({
    open,
    onProceed,
  }: {
    open: boolean
    onProceed: () => void
    onCancel: () => void
    actionLabel?: string
  }) => {
    React.useEffect(() => {
      if (open) onProceed()
    }, [open])
    return null
  },
}))

// ---------------------------------------------------------------------------
// Import component and API mock AFTER mocks are declared.
// ---------------------------------------------------------------------------

import Step6Execute from './Step6Execute'
import { postWizardExecute } from '../../api/client'
import type { WizardExecuteResponse } from '../../api/types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeResult(overrides?: Partial<WizardExecuteResponse>): WizardExecuteResponse {
  return {
    cycle_id: 'cycle-test-1',
    direction: 'spoolman_to_filamentdb',
    created: 0,
    updated: 0,
    skipped: 0,
    failed: 0,
    wizard_completed: false,
    records: [],
    created_filaments: 0,
    created_spools: 0,
    updated_filaments: 0,
    updated_spools: 0,
    skipped_filaments: 0,
    skipped_spools: 0,
    failed_filaments: 0,
    failed_spools: 0,
    ...overrides,
  }
}

const DEFAULT_CTX = {
  prev: vi.fn(),
  next: vi.fn(),
  goTo: vi.fn(),
  step: 5,
  tareOverrides: [],
  setTareOverrides: vi.fn(),
}

/** Render the component, confirm the checkbox, and click Execute sync. */
async function renderAndExecute(response: WizardExecuteResponse) {
  vi.mocked(postWizardExecute).mockResolvedValue(response)
  render(<Step6Execute {...DEFAULT_CTX} />)

  // Tick the confirmation checkbox and click execute.
  // Two "Execute sync" buttons are rendered (top + bottom action bar); click the first.
  const checkbox = screen.getByRole('checkbox')
  fireEvent.click(checkbox)
  const execBtns = screen.getAllByRole('button', { name: /execute sync/i })
  fireEvent.click(execBtns[0])

  // BackupSafetyDialog mock auto-calls onProceed (via useEffect), which triggers
  // runExecute(). Wait for the postWizardExecute mock to be called.
  await waitFor(() => expect(postWizardExecute).toHaveBeenCalled())
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('Step6Execute — result view', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows the Failed section with label and error message when a record fails', async () => {
    const result = makeResult({
      failed: 1,
      records: [
        {
          entity_type: 'spool',
          action: 'failed',
          spoolman_filament_id: 10,
          spoolman_spool_id: 1,
          filamentdb_filament_id: null,
          filamentdb_spool_id: null,
          label: 'ELEGOO PLA Red',
          detail: null,
          error: 'upstream 503: Service Unavailable',
        },
      ],
    })

    await renderAndExecute(result)

    await waitFor(() => {
      // The "Failed (N)" section heading must be visible.
      expect(screen.getByText(/failed \(1\)/i)).toBeInTheDocument()
      // The human-readable label must appear.
      expect(screen.getByText('ELEGOO PLA Red')).toBeInTheDocument()
      // The exact error message must appear.
      expect(screen.getByText(/upstream 503: service unavailable/i)).toBeInTheDocument()
    })
  })

  it('does NOT show the Failed section when there are no failures', async () => {
    const result = makeResult({
      created: 1,
      failed: 0,
      records: [
        {
          entity_type: 'spool',
          action: 'created',
          spoolman_filament_id: 10,
          spoolman_spool_id: 1,
          filamentdb_filament_id: 'fil-1',
          filamentdb_spool_id: 'spool-1',
          label: 'ELEGOO PLA Red',
          detail: null,
          error: null,
        },
      ],
    })

    await renderAndExecute(result)

    await waitFor(() => {
      // The created record label should appear in the main table.
      expect(screen.getByText('ELEGOO PLA Red')).toBeInTheDocument()
    })

    // The "Failed (N)" section should not be present.
    expect(screen.queryByText(/failed \(\d+\)/i)).not.toBeInTheDocument()
  })

  it('shows label fallback (spool ID) when no label is provided in the record', async () => {
    const result = makeResult({
      failed: 1,
      records: [
        {
          entity_type: 'spool',
          action: 'failed',
          spoolman_filament_id: null,
          spoolman_spool_id: 99,
          filamentdb_filament_id: null,
          filamentdb_spool_id: null,
          label: null,
          detail: null,
          error: 'connection timeout',
        },
      ],
    })

    await renderAndExecute(result)

    await waitFor(() => {
      // Without a label, the component should fall back to "Spool #99".
      expect(screen.getByText('Spool #99')).toBeInTheDocument()
      expect(screen.getByText(/connection timeout/i)).toBeInTheDocument()
    })
  })

  it('shows summary counters after execute', async () => {
    const result = makeResult({
      created: 3,
      updated: 1,
      skipped: 2,
      failed: 4,
      records: [
        {
          entity_type: 'spool',
          action: 'failed',
          spoolman_filament_id: 5,
          spoolman_spool_id: 10,
          filamentdb_filament_id: null,
          filamentdb_spool_id: null,
          label: 'Some Filament',
          detail: null,
          error: 'boom',
        },
      ],
    })

    await renderAndExecute(result)

    await waitFor(() => {
      // Counter values are rendered as large numbers.
      expect(screen.getByText('3')).toBeInTheDocument() // created
      expect(screen.getByText('1')).toBeInTheDocument() // updated (distinct from failed=4)
      expect(screen.getByText('2')).toBeInTheDocument() // skipped
      expect(screen.getByText('4')).toBeInTheDocument() // failed
    })
  })

  it('shows filament/spool breakdown under each non-zero counter', async () => {
    const result = makeResult({
      created: 3,
      created_filaments: 1,
      created_spools: 2,
      updated: 0,
      updated_filaments: 0,
      updated_spools: 0,
      skipped: 1,
      skipped_filaments: 0,
      skipped_spools: 1,
      failed: 2,
      failed_filaments: 1,
      failed_spools: 1,
      records: [
        {
          entity_type: 'filament',
          action: 'failed',
          spoolman_filament_id: 5,
          spoolman_spool_id: null,
          filamentdb_filament_id: null,
          filamentdb_spool_id: null,
          label: 'ELEGOO PLA',
          detail: null,
          error: 'write failed',
        },
      ],
    })

    await renderAndExecute(result)

    await waitFor(() => {
      // The "1f / 2s" breakdown should appear under the Created counter.
      expect(screen.getByText('1f / 2s')).toBeInTheDocument()
      // Skipped breakdown: "0f / 1s"
      expect(screen.getByText('0f / 1s')).toBeInTheDocument()
      // Failed breakdown: "1f / 1s"
      expect(screen.getByText('1f / 1s')).toBeInTheDocument()
    })
  })

  it('does NOT show breakdown line when counter is zero', async () => {
    const result = makeResult({
      created: 0,
      created_filaments: 0,
      created_spools: 0,
      updated: 2,
      updated_filaments: 1,
      updated_spools: 1,
      records: [
        {
          entity_type: 'filament',
          action: 'updated',
          spoolman_filament_id: 10,
          spoolman_spool_id: null,
          filamentdb_filament_id: 'fil-1',
          filamentdb_spool_id: null,
          label: 'My PLA',
          detail: null,
          error: null,
        },
        {
          entity_type: 'spool',
          action: 'updated',
          spoolman_filament_id: 10,
          spoolman_spool_id: 5,
          filamentdb_filament_id: 'fil-1',
          filamentdb_spool_id: 'sp-1',
          label: 'My PLA spool',
          detail: null,
          error: null,
        },
      ],
    })

    await renderAndExecute(result)

    await waitFor(() => {
      // Updated counter value should appear.
      expect(screen.getByText('2')).toBeInTheDocument()
      // "1f / 1s" breakdown should appear under Updated.
      expect(screen.getByText('1f / 1s')).toBeInTheDocument()
    })

    // Created is zero — no breakdown line for it.
    expect(screen.queryByText('0f / 0s')).not.toBeInTheDocument()
  })
})
