/**
 * App-level auth-gate tests for the public mobile scan flow.
 *
 * When auth is enabled and the user is NOT authenticated:
 *   - on /scan/:filId/:spoolId AND mobile_public (mobile_session_days == 0) → render
 *     the scan page (no Login)
 *   - on /scan/... when NOT mobile_public → still show Login
 *   - on any other path → still show Login
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

// ---------------------------------------------------------------------------
// Mocks — keep child route pages trivial so we only assert the gate.
// ---------------------------------------------------------------------------

vi.mock('./api/client', () => ({
  getAuthStatus: vi.fn(),
  getVersionInfo: vi.fn(),
  register401Handler: vi.fn(),
}))

vi.mock('./pages/Login', () => ({
  default: () => <div data-testid="login-page">LOGIN</div>,
}))

vi.mock('./pages/ScanTarget', () => ({
  default: () => <div data-testid="scan-page">SCAN</div>,
}))

// The Layout + every in-nav page sit behind the Layout route; we never reach them
// in these tests (unauthenticated), but stub the Layout so the router can build.
vi.mock('./components/Layout', () => ({
  Layout: () => <div data-testid="layout">LAYOUT</div>,
}))

vi.mock('./context/ThemeContext', () => ({
  ThemeProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('./components/DeepLinkContext', () => ({
  DeepLinkProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

import type { AuthStatusResponse, VersionInfo } from './api/types'

const UNAUTH: AuthStatusResponse = {
  auth_enabled: true,
  password_set: true,
  authenticated: false,
  api_token_enabled: false,
}

function version(mobilePublic: boolean): VersionInfo {
  return {
    current: '0.5.1',
    latest: null,
    update_available: false,
    release_url: null,
    release_name: null,
    release_notes: null,
    current_release_url: null,
    current_release_name: null,
    current_release_notes: null,
    channel: 'release',
    commit: null,
    build: 'v0.5.1',
    is_dev: false,
    mobile_labels_enabled: true,
    mobile_public: mobilePublic,
  }
}

/**
 * The router is created at App module-load time from window.location, so the path
 * must be set BEFORE App is imported. Reset the module graph per test and re-import
 * App + the client mock together so the configured vi.fn instances match.
 */
async function renderAt(path: string, mobilePublic: boolean) {
  window.history.pushState({}, '', path)
  vi.resetModules()
  const client = await import('./api/client')
  ;(client.getAuthStatus as ReturnType<typeof vi.fn>).mockResolvedValue(UNAUTH)
  ;(client.getVersionInfo as ReturnType<typeof vi.fn>).mockResolvedValue(version(mobilePublic))
  const { default: App } = await import('./App')
  return render(<App />)
}

describe('App auth gate — public scan flow', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the scan page without login on /scan/... when mobile_public', async () => {
    await renderAt('/scan/fil-1/spool-1', true)
    await waitFor(() => expect(screen.getByTestId('scan-page')).toBeInTheDocument())
    expect(screen.queryByTestId('login-page')).not.toBeInTheDocument()
  })

  it('shows Login on /scan/... when NOT mobile_public', async () => {
    await renderAt('/scan/fil-1/spool-1', false)
    await waitFor(() => expect(screen.getByTestId('login-page')).toBeInTheDocument())
    expect(screen.queryByTestId('scan-page')).not.toBeInTheDocument()
  })

  it('shows Login on a non-scan path even when mobile_public', async () => {
    await renderAt('/settings', true)
    await waitFor(() => expect(screen.getByTestId('login-page')).toBeInTheDocument())
    expect(screen.queryByTestId('scan-page')).not.toBeInTheDocument()
  })
})
