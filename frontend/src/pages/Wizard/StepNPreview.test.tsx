/**
 * Tests for StepNPreview — the wizard preview step.
 *
 * Focus: the "Empty/archived spools" flag section must render an
 * "archived → imports as retired" badge for archived entries (archived=true),
 * and no badge for plain empty-active entries (archived=false).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import React from 'react'

// ---------------------------------------------------------------------------
// Mocks — hoisted before any imports.
// ---------------------------------------------------------------------------

vi.mock('../../api/client', () => ({
  getWizardPreview: vi.fn(),
  getConfig: vi.fn(),
  postWizardContainerNameOverrides: vi.fn(),
}))

vi.mock('../../api/hooks', () => ({
  useApi: vi.fn(),
}))

vi.mock('../../components/DeepLinkContext', () => ({
  useDeepLinkBases: () => ({ filamentdbUrl: 'http://fdb.test', spoolmanUrl: 'http://sm.test' }),
  DeepLinkProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('../../components/HelpTip', () => ({
  HelpTip: () => null,
}))

// ---------------------------------------------------------------------------
// Imports after mocks.
// ---------------------------------------------------------------------------

import StepNPreview from './StepNPreview'
import { useApi } from '../../api/hooks'
import { getConfig } from '../../api/client'
import type { WizardPreviewResponse } from '../../api/types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makePreview(overrides?: Partial<WizardPreviewResponse>): WizardPreviewResponse {
  return {
    direction: 'spoolman_to_filamentdb',
    plan_rows: [],
    flag_counts: {
      name_collision: 0,
      empty_active: 0,
      default_tare: 0,
      variant_group: 0,
    },
    name_collisions: [],
    empty_active: [],
    default_tare: [],
    variant_groups: [],
    variant_plan: [],
    include_empty_spools: true,
    planned_writes: [],
    container_name_overrides: [],
    ...overrides,
  }
}

const DEFAULT_CTX = {
  prev: vi.fn(),
  next: vi.fn(),
  goTo: vi.fn(),
  step: 4,
  tareOverrides: [],
  setTareOverrides: vi.fn(),
}

function setupUseApi(data: WizardPreviewResponse, configData?: object) {
  const config = configData ?? { never_import_empties: false }
  vi.mocked(useApi).mockImplementation((fn) => {
    // StepNPreview calls useApi(getWizardPreview) and useApi(getConfig).
    // Differentiate by checking function reference identity.
    if (fn === getConfig) {
      return { data: config, loading: false, error: null }
    }
    return { data, loading: false, error: null }
  })
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('StepNPreview — archived spool display', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders "archived → imports as retired" badge for archived empty entry', async () => {
    const preview = makePreview({
      flag_counts: { name_collision: 0, empty_active: 1, default_tare: 0, variant_group: 0 },
      empty_active: [
        {
          spoolman_spool_id: 65,
          spoolman_filament_id: 63,
          name: 'Light Purple PLA',
          archived: true,
        },
      ],
    })

    setupUseApi(preview)
    render(<StepNPreview {...DEFAULT_CTX} />)

    // Open the empty_active section by clicking on it (it starts collapsed)
    const sectionBtn = screen.getByRole('button', { name: /empty\/archived spools/i })
    sectionBtn.click()

    await waitFor(() => {
      expect(screen.getByText('Light Purple PLA')).toBeInTheDocument()
      expect(screen.getByText(/archived → imports as retired/i)).toBeInTheDocument()
    })
  })

  it('does NOT render "imports as retired" badge for active empty (archived=false) entry', async () => {
    const preview = makePreview({
      flag_counts: { name_collision: 0, empty_active: 1, default_tare: 0, variant_group: 0 },
      empty_active: [
        {
          spoolman_spool_id: 10,
          spoolman_filament_id: 5,
          name: 'PLA Active Empty',
          archived: false,
        },
      ],
    })

    setupUseApi(preview)
    render(<StepNPreview {...DEFAULT_CTX} />)

    const sectionBtn = screen.getByRole('button', { name: /empty\/archived spools/i })
    sectionBtn.click()

    await waitFor(() => {
      expect(screen.getByText('PLA Active Empty')).toBeInTheDocument()
    })

    // Must NOT show the archived badge
    expect(screen.queryByText(/archived → imports as retired/i)).not.toBeInTheDocument()
  })

  it('shows both active-empty and archived entries when both are present', async () => {
    const preview = makePreview({
      flag_counts: { name_collision: 0, empty_active: 2, default_tare: 0, variant_group: 0 },
      empty_active: [
        {
          spoolman_spool_id: 65,
          spoolman_filament_id: 63,
          name: 'Light Purple PLA',
          archived: true,
        },
        {
          spoolman_spool_id: 10,
          spoolman_filament_id: 5,
          name: 'PLA Active Empty',
          archived: false,
        },
      ],
    })

    setupUseApi(preview)
    render(<StepNPreview {...DEFAULT_CTX} />)

    const sectionBtn = screen.getByRole('button', { name: /empty\/archived spools/i })
    sectionBtn.click()

    await waitFor(() => {
      expect(screen.getByText('Light Purple PLA')).toBeInTheDocument()
      expect(screen.getByText('PLA Active Empty')).toBeInTheDocument()
      expect(screen.getByText(/archived → imports as retired/i)).toBeInTheDocument()
    })
  })

  it('shows "skipped" text in section label when never_import_empties is true', async () => {
    const preview = makePreview({
      flag_counts: { name_collision: 0, empty_active: 1, default_tare: 0, variant_group: 0 },
      empty_active: [{ spoolman_spool_id: 65, spoolman_filament_id: 63, name: 'Light Purple PLA', archived: true }],
    })

    setupUseApi(preview, { never_import_empties: true })
    render(<StepNPreview {...DEFAULT_CTX} />)

    // The emptyActiveLabel string is rendered inside the FlagSection button.
    // When never_import_empties is true, the label includes "skipped".
    // Use a text content match via getAllByText.
    const matches = screen.queryAllByText(/skipped.*never import empties/i)
    // If not found as a direct text node, look for an element containing the text
    const container = document.body.innerHTML
    expect(container).toMatch(/skipped.*never import empties/i)
  })
})
