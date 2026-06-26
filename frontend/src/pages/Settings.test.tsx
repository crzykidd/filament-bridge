/**
 * Frontend tests for the Settings debug section.
 *
 * Tests:
 *   - Full reset button is rendered when debug mode is on in the config response
 *   - Full reset button calls the fullReset API function when confirmed
 *   - The two existing one-sided buttons are also present with updated labels
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import React from 'react'

// ---------------------------------------------------------------------------
// Mocks — all vi.mock calls are hoisted; they run before any imports below.
// ---------------------------------------------------------------------------

vi.mock('../api/client', () => ({
  getConfig: vi.fn(),
  updateConfig: vi.fn(),
  setAutoSync: vi.fn(),
  exportBackup: vi.fn(),
  importBackup: vi.fn(),
  clearSpoolmanFdbRefs: vi.fn(),
  clearSpoolmanOpentagIds: vi.fn(),
  resetBridgeState: vi.fn(),
  fullReset: vi.fn(),
  authChangePassword: vi.fn(),
  authRegenerateToken: vi.fn(),
  getAuthStatus: vi.fn(),
  getPrinterStatus: vi.fn(),
  getBackupStatus: vi.fn().mockResolvedValue({
    last_run: null,
    next_run_at: null,
    schedule_enabled: true,
    retention_days: 7,
    retained: { count: 0, total_bytes: 0 },
  }),
  BridgeApiError: class BridgeApiError extends Error {
    constructor(public status: number, public code: string, message: string) {
      super(message)
    }
  },
}))

vi.mock('../api/hooks', () => ({
  useApi: vi.fn(),
}))

vi.mock('../components/BackupSafetyDialog', () => ({
  BackupSafetyDialog: ({
    open,
    onProceed,
  }: {
    open: boolean
    onProceed: () => void
    onCancel: () => void
    actionLabel?: string
  }) => {
    // Auto-proceed so tests don't need to interact with the dialog
    React.useEffect(() => {
      if (open) onProceed()
    }, [open])
    return null
  },
}))

vi.mock('../components/DebugConfirmDialog', () => ({
  DebugConfirmDialog: ({
    open,
    onConfirm,
  }: {
    open: boolean
    onConfirm: () => void
    onCancel: () => void
    actionLabel?: string
    warningBody?: string
  }) => {
    // Auto-confirm so tests that click debug buttons don't need to interact with the dialog
    React.useEffect(() => {
      if (open) onConfirm()
    }, [open])
    return null
  },
}))

vi.mock('../context/ThemeContext', () => ({
  useTheme: () => ({ mode: 'system', setMode: vi.fn() }),
  ThemeProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

// react-router-dom blocker + Link stub
vi.mock('react-router-dom', () => ({
  useBlocker: vi.fn(() => ({ state: 'unblocked' })),
  Link: ({ to, children, ...rest }: { to: string; children: React.ReactNode; [k: string]: unknown }) => (
    <a href={to} {...rest}>{children}</a>
  ),
}))

// ---------------------------------------------------------------------------
// Import component + mocks after declarations
// ---------------------------------------------------------------------------

import Settings from './Settings'
import { fullReset, clearSpoolmanFdbRefs, resetBridgeState, getAuthStatus, getPrinterStatus, updateConfig } from '../api/client'
import { useApi } from '../api/hooks'
import type { ConfigResponse, FullResetResponse } from '../api/types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeConfig(overrides?: Partial<ConfigResponse>): ConfigResponse {
  return {
    sync_weight_threshold_grams: 2,
    weight_precision_decimals: 1,
    auto_sync_enabled: false,
    wizard_completed: true,
    import_direction: null,
    variant_line_keywords: '',
    opentag_vendor_aliases: '',
    weight_sync_direction: 'spoolman_to_filamentdb',
    weight_conflict_policy: 'manual',
    material_properties_sync_direction: 'filamentdb_to_spoolman',
    material_properties_conflict_policy: 'manual',
    archive_sync_direction: 'two_way',
    archive_conflict_policy: 'manual',
    location_sync_direction: 'two_way',
    location_sync_conflict_policy: 'manual',
    new_spool_sync_direction: 'two_way',
    new_filament_policy: 'manual_review',
    new_spool_policy: 'manual_review',
    sync_interval_seconds: 120,
    sync_log_retention_days: 30,
    never_import_empties: false,
    debug_mode: true,
    variant_parent_mode: 'promote_color',
    container_parent_marker: '(Master)',
    api_token: null,
    api_token_enabled: false,
    backup_schedule_enabled: true,
    backup_bridge_state_enabled: true,
    backup_filamentdb_enabled: true,
    backup_retention_days: 7,
    backup_hour_utc: 3,
    mobile_labels_enabled: false,
    mobile_session_days: 30,
    mobile_redirect_target: 'bridge',
    mobile_weight_default_mode: 'direct_correction',
    bridge_public_url: '',
    labelforge_url: '',
    labelforge_token: '',
    labelforge_template: '',
    labelforge_fields: '',
    labelforge_label_media: '',
    required_settings_unset: [],
    ...overrides,
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('Settings debug section — Full reset', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(getAuthStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      auth_enabled: false,
      password_set: false,
      authenticated: true,
      api_token_enabled: false,
    })
    ;(useApi as ReturnType<typeof vi.fn>).mockReturnValue({
      data: makeConfig(),
      loading: false,
      error: null,
      reload: vi.fn(),
    })
  })

  it('renders the Full reset button when debug mode is on', () => {
    render(<Settings />)
    expect(
      screen.getByRole('button', { name: /full reset/i }),
    ).toBeInTheDocument()
  })

  it('renders the relabeled Spoolman-only button', () => {
    render(<Settings />)
    expect(
      screen.getByRole('button', { name: /clear spoolman cross-refs \(spoolman only\)/i }),
    ).toBeInTheDocument()
  })

  it('renders the relabeled bridge-DB-only button', () => {
    render(<Settings />)
    expect(
      screen.getByRole('button', { name: /reset bridge db \(bridge only\)/i }),
    ).toBeInTheDocument()
  })

  it('calls fullReset when Full reset button is clicked and dialog confirmed', async () => {
    const mockResult: FullResetResponse = {
      filament_mappings: 3,
      spool_mappings: 5,
      snapshots: 8,
      conflicts: 1,
      sync_log: 20,
      wizard_completed_reset: true,
      spoolman_cleared: 7,
      spoolman_failed: 0,
      spoolman_error: null,
    }
    ;(fullReset as ReturnType<typeof vi.fn>).mockResolvedValue(mockResult)

    render(<Settings />)

    const fullResetBtn = screen.getByRole('button', { name: /full reset \(bridge db \+ spoolman links\)/i })
    fireEvent.click(fullResetBtn)

    // Dialog should appear — find the confirm button inside it
    await waitFor(() => {
      expect(screen.getByText(/this will perform/i)).toBeInTheDocument()
    })

    const confirmBtn = screen.getByRole('button', { name: /^full reset$/i })
    fireEvent.click(confirmBtn)

    await waitFor(() => {
      expect(fullReset).toHaveBeenCalledTimes(1)
    })
  })

  it('shows combined result message after successful full reset', async () => {
    const mockResult: FullResetResponse = {
      filament_mappings: 2,
      spool_mappings: 4,
      snapshots: 6,
      conflicts: 0,
      sync_log: 10,
      wizard_completed_reset: true,
      spoolman_cleared: 3,
      spoolman_failed: 0,
      spoolman_error: null,
    }
    ;(fullReset as ReturnType<typeof vi.fn>).mockResolvedValue(mockResult)

    render(<Settings />)

    fireEvent.click(screen.getByRole('button', { name: /full reset \(bridge db \+ spoolman links\)/i }))

    await waitFor(() => {
      expect(screen.getByText(/this will perform/i)).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /^full reset$/i }))

    await waitFor(() => {
      expect(screen.getByText(/spoolman: 3 spool\(s\) cleared/i)).toBeInTheDocument()
    })
  })

  it('does not call fullReset when dialog is cancelled', async () => {
    render(<Settings />)

    fireEvent.click(screen.getByRole('button', { name: /full reset \(bridge db \+ spoolman links\)/i }))

    await waitFor(() => {
      expect(screen.getByText(/this will perform/i)).toBeInTheDocument()
    })

    const cancelBtn = screen.getByRole('button', { name: /^cancel$/i })
    fireEvent.click(cancelBtn)

    expect(fullReset).not.toHaveBeenCalled()
  })

  it('renders the Clear Spoolman OpenPrintTag ids button when debug mode is on', () => {
    render(<Settings />)
    expect(
      screen.getByRole('button', { name: /clear spoolman openprinttag ids \(spoolman only\)/i }),
    ).toBeInTheDocument()
  })

  it('does not render debug zone when debug_mode is off', () => {
    ;(useApi as ReturnType<typeof vi.fn>).mockReturnValue({
      data: makeConfig({ debug_mode: false }),
      loading: false,
      error: null,
      reload: vi.fn(),
    })

    render(<Settings />)
    expect(screen.queryByRole('button', { name: /full reset/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /clear spoolman cross-refs/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /clear spoolman openprinttag ids/i })).not.toBeInTheDocument()
  })
})

describe('Settings — Scheduled backups section', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(getAuthStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      auth_enabled: false,
      password_set: false,
      authenticated: true,
      api_token_enabled: false,
    })
  })

  it('renders the Scheduled backups heading and controls', () => {
    ;(useApi as ReturnType<typeof vi.fn>).mockReturnValue({
      data: makeConfig(),
      loading: false,
      error: null,
      reload: vi.fn(),
    })
    render(<Settings />)
    expect(
      screen.getByRole('heading', { name: /^scheduled backups$/i }),
    ).toBeInTheDocument()
    expect(screen.getByText(/enable scheduled backups/i)).toBeInTheDocument()
    expect(screen.getByText(/back up bridge state/i)).toBeInTheDocument()
    expect(screen.getByText(/back up filament db snapshot/i)).toBeInTheDocument()
    expect(screen.getByText(/^retention \(days\)$/i)).toBeInTheDocument()
    expect(screen.getByText(/run at \(utc hour\)/i)).toBeInTheDocument()
  })

  it('disables the sub-toggles when the master switch is off', () => {
    ;(useApi as ReturnType<typeof vi.fn>).mockReturnValue({
      data: makeConfig({ backup_schedule_enabled: false }),
      loading: false,
      error: null,
      reload: vi.fn(),
    })
    render(<Settings />)
    const bridgeToggle = screen
      .getByText(/back up bridge state/i)
      .parentElement!.querySelector('button')!
    expect(bridgeToggle).toBeDisabled()
  })
})

describe('Settings — Mobile updates section', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(getAuthStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      auth_enabled: false,
      password_set: false,
      authenticated: true,
      api_token_enabled: false,
    })
  })

  it('renders the Mobile & Labels heading and controls', () => {
    ;(useApi as ReturnType<typeof vi.fn>).mockReturnValue({
      data: makeConfig(),
      loading: false,
      error: null,
      reload: vi.fn(),
    })
    render(<Settings />)
    expect(screen.getByRole('heading', { name: /^mobile & labels$/i })).toBeInTheDocument()
    expect(screen.getByText(/enable mobile updates/i)).toBeInTheDocument()
    expect(screen.getByText(/qr redirect target/i)).toBeInTheDocument()
    expect(screen.getByText(/default weight mode/i)).toBeInTheDocument()
  })

  it('renders the LabelForge connection fields and a Test printer button', () => {
    ;(useApi as ReturnType<typeof vi.fn>).mockReturnValue({
      data: makeConfig({ mobile_labels_enabled: true }),
      loading: false,
      error: null,
      reload: vi.fn(),
    })
    render(<Settings />)
    expect(screen.getByText(/labelforge label printing/i)).toBeInTheDocument()
    expect(screen.getByText(/^labelforge url$/i)).toBeInTheDocument()
    expect(screen.getByText(/^labelforge api token$/i)).toBeInTheDocument()
    expect(screen.getByText(/^fields \(csv\)$/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /test printer/i })).toBeInTheDocument()
  })

  it('calls getPrinterStatus and shows the result when Test printer is clicked', async () => {
    ;(useApi as ReturnType<typeof vi.fn>).mockReturnValue({
      data: makeConfig({ mobile_labels_enabled: true, labelforge_url: 'http://lf.test' }),
      loading: false,
      error: null,
      reload: vi.fn(),
    })
    ;(getPrinterStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      ready: true,
      model: 'QL-800',
      loaded_media: { id: '62', display_name: '62mm Continuous', width_mm: 62, length_mm: 0, color_capable: false },
      errors: [],
    })
    render(<Settings />)
    fireEvent.click(screen.getByRole('button', { name: /test printer/i }))
    await waitFor(() => expect(getPrinterStatus).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(screen.getByText(/QL-800/)).toBeInTheDocument())
  })

  it('saves the LabelForge fields via updateConfig', async () => {
    const reload = vi.fn()
    ;(useApi as ReturnType<typeof vi.fn>).mockReturnValue({
      data: makeConfig({ mobile_labels_enabled: true }),
      loading: false,
      error: null,
      reload,
    })
    ;(updateConfig as ReturnType<typeof vi.fn>).mockResolvedValue(makeConfig({ mobile_labels_enabled: true }))
    render(<Settings />)

    const tmpl = screen
      .getByText(/^template name$/i)
      .parentElement!.querySelector('input')!
    fireEvent.change(tmpl, { target: { value: 'spool' } })
    fireEvent.click(screen.getAllByRole('button', { name: /^save$/i })[0])

    await waitFor(() => expect(updateConfig).toHaveBeenCalledTimes(1))
    expect((updateConfig as ReturnType<typeof vi.fn>).mock.calls[0][0]).toMatchObject({
      labelforge_template: 'spool',
    })
  })

  it('disables the redirect + weight selects when the feature is off', () => {
    ;(useApi as ReturnType<typeof vi.fn>).mockReturnValue({
      data: makeConfig({ mobile_labels_enabled: false }),
      loading: false,
      error: null,
      reload: vi.fn(),
    })
    render(<Settings />)
    const redirectSelect = screen
      .getByText(/qr redirect target/i)
      .parentElement!.querySelector('select')!
    expect(redirectSelect).toBeDisabled()
  })

  it('enables the selects when the feature is on', () => {
    ;(useApi as ReturnType<typeof vi.fn>).mockReturnValue({
      data: makeConfig({ mobile_labels_enabled: true }),
      loading: false,
      error: null,
      reload: vi.fn(),
    })
    render(<Settings />)
    const redirectSelect = screen
      .getByText(/qr redirect target/i)
      .parentElement!.querySelector('select')!
    expect(redirectSelect).not.toBeDisabled()
  })

  it('renders the Scan login (days) field with the configured value', () => {
    ;(useApi as ReturnType<typeof vi.fn>).mockReturnValue({
      data: makeConfig({ mobile_labels_enabled: true, mobile_session_days: 0 }),
      loading: false,
      error: null,
      reload: vi.fn(),
    })
    render(<Settings />)
    expect(screen.getByText(/scan login \(days\)/i)).toBeInTheDocument()
    const input = screen
      .getByText(/scan login \(days\)/i)
      .parentElement!.querySelector('input')! as HTMLInputElement
    expect(input.value).toBe('0')
  })

  it('saves mobile_session_days via updateConfig', async () => {
    ;(useApi as ReturnType<typeof vi.fn>).mockReturnValue({
      data: makeConfig({ mobile_labels_enabled: true, mobile_session_days: 30 }),
      loading: false,
      error: null,
      reload: vi.fn(),
    })
    ;(updateConfig as ReturnType<typeof vi.fn>).mockResolvedValue(
      makeConfig({ mobile_labels_enabled: true, mobile_session_days: 0 }),
    )
    render(<Settings />)

    const input = screen
      .getByText(/scan login \(days\)/i)
      .parentElement!.querySelector('input')!
    fireEvent.change(input, { target: { value: '0' } })
    fireEvent.click(screen.getAllByRole('button', { name: /^save$/i })[0])

    await waitFor(() => expect(updateConfig).toHaveBeenCalledTimes(1))
    expect((updateConfig as ReturnType<typeof vi.fn>).mock.calls[0][0]).toMatchObject({
      mobile_session_days: 0,
    })
  })
})
