/**
 * Tests for VersionBadge in Layout.tsx:
 *  - pill reads "Update Available" (not "↑ vX.Y.Z")
 *  - post-upgrade modal shown once when stored running-version differs from current
 *  - post-upgrade modal not shown on first run (key absent)
 *  - post-upgrade modal dismiss writes current version to localStorage
 *  - "update available" modal not shown when post-upgrade modal fires
 *  - no modal when current_release_notes is null (untagged build)
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import React from 'react'

// ---------------------------------------------------------------------------
// Mocks — declared before imports (vi.mock hoists)
// ---------------------------------------------------------------------------

vi.mock('../api/client', () => ({
  getVersionInfo: vi.fn(),
  getHealth: vi.fn().mockResolvedValue({ status: 'ok' }),
  getAuthStatus: vi.fn().mockResolvedValue({ auth_enabled: false, password_set: true, authenticated: true, api_token_enabled: false }),
  authLogout: vi.fn(),
}))

vi.mock('react-router-dom', () => ({
  NavLink: ({ children, to }: { children: React.ReactNode; to: string }) => <a href={to}>{children}</a>,
  Outlet: () => <div data-testid="outlet" />,
  useNavigate: () => vi.fn(),
  useLocation: () => ({ pathname: '/' }),
}))

vi.mock('./RequiredSettingsGate', () => ({
  RequiredSettingsGate: () => null,
}))

vi.mock('../context/ThemeContext', () => ({
  useTheme: () => ({ mode: 'system', setMode: vi.fn() }),
  ThemeProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

// ---------------------------------------------------------------------------
// Imports after mocks
// ---------------------------------------------------------------------------

import { Layout } from './Layout'
import { getVersionInfo } from '../api/client'
import type { VersionInfo } from '../api/types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const LS_KEY = 'fb_last_seen_version'
const LS_RUNNING_KEY = 'fb_last_running_version'

function makeVersionInfo(overrides: Partial<VersionInfo> = {}): VersionInfo {
  return {
    current: '0.2.0',
    latest: '0.2.0',
    update_available: false,
    release_url: 'https://github.com/crzykidd/filament-bridge/releases/tag/v0.2.0',
    release_name: 'v0.2.0',
    release_notes: 'Latest release notes',
    current_release_url: 'https://github.com/crzykidd/filament-bridge/releases/tag/v0.2.0',
    current_release_name: 'v0.2.0',
    current_release_notes: 'What is new in 0.2.0',
    channel: 'release',
    commit: null,
    build: 'v0.2.0',
    is_dev: false,
    mobile_labels_enabled: false,
    mobile_public: false,
    ...overrides,
  }
}

function renderLayout() {
  return render(<Layout />)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('VersionBadge — pill label', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('pill reads "Update Available" when update_available is true', async () => {
    vi.mocked(getVersionInfo).mockResolvedValue(
      makeVersionInfo({ update_available: true, latest: '0.3.0', current: '0.2.0' })
    )
    // Suppress "update available" modal by pre-seeding last seen = latest
    localStorage.setItem(LS_KEY, '0.3.0')
    // Suppress post-upgrade modal: set running version = current
    localStorage.setItem(LS_RUNNING_KEY, '0.2.0')

    renderLayout()

    await waitFor(() => {
      expect(screen.getByText('Update Available')).toBeInTheDocument()
    })
  })

  it('pill does NOT contain "↑ v" text', async () => {
    vi.mocked(getVersionInfo).mockResolvedValue(
      makeVersionInfo({ update_available: true, latest: '0.3.0', current: '0.2.0' })
    )
    localStorage.setItem(LS_KEY, '0.3.0')
    localStorage.setItem(LS_RUNNING_KEY, '0.2.0')

    renderLayout()

    await waitFor(() => {
      expect(screen.queryByText(/↑ v/)).toBeNull()
    })
  })
})

describe('VersionBadge — post-upgrade modal', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('shows post-upgrade modal when stored running-version differs from current', async () => {
    vi.mocked(getVersionInfo).mockResolvedValue(makeVersionInfo())
    // Stored = old version, current = 0.2.0
    localStorage.setItem(LS_RUNNING_KEY, '0.1.0')

    renderLayout()

    await waitFor(() => {
      // The subtitle contains the current version
      expect(screen.getByText(/You're now running filament-bridge v0\.2\.0/)).toBeInTheDocument()
    })
    // The release notes are shown
    expect(screen.getByText('What is new in 0.2.0')).toBeInTheDocument()
  })

  it('does not show post-upgrade modal on first run (key absent)', async () => {
    vi.mocked(getVersionInfo).mockResolvedValue(makeVersionInfo())
    // No LS_RUNNING_KEY set — first ever run

    renderLayout()

    // Wait for version info to load
    await waitFor(() => {
      expect(screen.getByText('v0.2.0')).toBeInTheDocument()
    })
    // Modal must not appear
    expect(screen.queryByText(/You're now running/)).toBeNull()
  })

  it('sets the running-version key to current on first run (no modal)', async () => {
    vi.mocked(getVersionInfo).mockResolvedValue(makeVersionInfo())

    renderLayout()

    await waitFor(() => {
      expect(screen.getByText('v0.2.0')).toBeInTheDocument()
    })

    expect(localStorage.getItem(LS_RUNNING_KEY)).toBe('0.2.0')
  })

  it('does not show post-upgrade modal when current_release_notes is null', async () => {
    vi.mocked(getVersionInfo).mockResolvedValue(
      makeVersionInfo({ current_release_notes: null })
    )
    localStorage.setItem(LS_RUNNING_KEY, '0.1.0')

    renderLayout()

    await waitFor(() => {
      expect(screen.getByText('v0.2.0')).toBeInTheDocument()
    })
    expect(screen.queryByText(/You're now running/)).toBeNull()
  })

  it('dismiss writes current version to fb_last_running_version', async () => {
    vi.mocked(getVersionInfo).mockResolvedValue(makeVersionInfo())
    localStorage.setItem(LS_RUNNING_KEY, '0.1.0')

    renderLayout()

    await waitFor(() => {
      expect(screen.getByText(/You're now running filament-bridge v0\.2\.0/)).toBeInTheDocument()
    })

    // Click "Got it"
    fireEvent.click(screen.getByText('Got it'))

    expect(localStorage.getItem(LS_RUNNING_KEY)).toBe('0.2.0')
    expect(screen.queryByText(/You're now running/)).toBeNull()
  })

  it('post-upgrade modal takes precedence — update-available modal not shown simultaneously', async () => {
    // Both could theoretically fire: running version changed AND an update exists
    vi.mocked(getVersionInfo).mockResolvedValue(
      makeVersionInfo({ update_available: true, latest: '0.3.0', current: '0.2.0' })
    )
    // Would trigger "update available" modal
    localStorage.setItem(LS_KEY, '0.1.0')
    // Would trigger post-upgrade modal
    localStorage.setItem(LS_RUNNING_KEY, '0.1.0')

    renderLayout()

    await waitFor(() => {
      expect(screen.getByText(/You're now running filament-bridge v0\.2\.0/)).toBeInTheDocument()
    })

    // The "update available" subtitle must NOT also appear
    expect(screen.queryByText('filament-bridge update')).toBeNull()
  })
})
