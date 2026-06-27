import { useEffect, useState } from 'react'
import {
  createBrowserRouter,
  createRoutesFromElements,
  Navigate,
  Route,
  RouterProvider,
} from 'react-router-dom'
import { Layout } from './components/Layout'
import { DeepLinkProvider } from './components/DeepLinkContext'
import Dashboard from './pages/Dashboard'
import SyncedRecords from './pages/SyncedRecords'
import Conflicts from './pages/Conflicts'
import SyncLog from './pages/SyncLog'
import Settings from './pages/Settings'
import OpenTagCleanup from './pages/OpenTagCleanup'
import Reconcile from './pages/Reconcile'
import TareEditor from './pages/TareEditor'
import DocsViewer from './pages/DocsViewer'
import { WizardShell } from './pages/Wizard'
import WizardFailureReport from './pages/WizardFailureReport'
import MobileUpdates from './pages/MobileUpdates'
import ScanTarget from './pages/ScanTarget'
import Login from './pages/Login'
import { getAuthStatus, getVersionInfo, register401Handler } from './api/client'
import type { AuthStatusResponse } from './api/types'
import { ThemeProvider } from './context/ThemeContext'

// A bare phone scan opens /scan/:filId/:spoolId. When the backend reports the scan
// flow is public (mobile_session_days == 0 → mobile_public), this route renders
// WITHOUT the app login; every other path still shows Login. Matches the same path
// the ScanTarget route is registered under.
const SCAN_PATH_RE = /^\/scan\/[^/]+\/[^/]+\/?$/

// Data router (createBrowserRouter) is required so pages can use `useBlocker`
// (e.g. Settings' unsaved-changes guard). The classic <BrowserRouter> component
// does not provide the data-router context that useBlocker needs.
const router = createBrowserRouter(
  createRoutesFromElements(
    <>
      {/* Bare QR scan-target page — SIBLING of the Layout wrapper so it renders
          with no side nav. Still behind the global auth gate below. */}
      <Route path="scan/:filId/:spoolId" element={<ScanTarget />} />
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="synced-records" element={<SyncedRecords />} />
        <Route path="conflicts" element={<Conflicts />} />
        <Route path="sync-log" element={<SyncLog />} />
        <Route path="settings" element={<Settings />} />
        <Route path="opentag-cleanup" element={<OpenTagCleanup />} />
        <Route path="reconcile" element={<Reconcile />} />
        <Route path="tare-editor" element={<TareEditor />} />
        <Route path="mobile-updates" element={<MobileUpdates />} />
        <Route path="wizard/report" element={<WizardFailureReport />} />
        <Route path="wizard/*" element={<WizardShell />} />
        <Route path="docs" element={<DocsViewer />} />
        <Route path="docs/:slug" element={<DocsViewer />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </>,
  ),
)

export default function App() {
  const [authStatus, setAuthStatus] = useState<AuthStatusResponse | null>(null)
  const [authLoading, setAuthLoading] = useState(true)
  // Whether the scan flow is public (mobile_session_days == 0). Read from /api/version.
  const [mobilePublic, setMobilePublic] = useState(false)

  async function checkAuth() {
    try {
      const status = await getAuthStatus()
      setAuthStatus(status)
    } catch {
      // If auth status fails entirely, assume not authenticated
      setAuthStatus({ auth_enabled: true, password_set: false, authenticated: false, api_token_enabled: false })
    } finally {
      setAuthLoading(false)
    }
  }

  useEffect(() => {
    // Register 401 handler so any protected-route 401 causes a re-check
    register401Handler(() => {
      void checkAuth()
    })
    void checkAuth()
    // The /api/version flag is public, so this works even with no session.
    getVersionInfo().then(v => setMobilePublic(v.mobile_public)).catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (authLoading) {
    return (
      <ThemeProvider>
        <div className="min-h-screen bg-gray-50 dark:bg-gray-900 flex items-center justify-center">
          <span className="text-gray-400 dark:text-gray-500 text-sm">Loading…</span>
        </div>
      </ThemeProvider>
    )
  }

  // Show setup/login when auth is enabled and user is not authenticated — EXCEPT on
  // the bare scan page when the scan flow is public (mobile_public). In that case the
  // router renders the public ScanTarget (whose API calls hit public endpoints);
  // everything else still shows Login.
  const onPublicScanPage = mobilePublic && SCAN_PATH_RE.test(window.location.pathname)
  if (authStatus && authStatus.auth_enabled && !authStatus.authenticated && !onPublicScanPage) {
    return (
      <ThemeProvider>
        <Login
          passwordSet={authStatus.password_set}
          onAuthenticated={() => void checkAuth()}
        />
      </ThemeProvider>
    )
  }

  // DeepLinkProvider uses no router hooks, so it can wrap the RouterProvider.
  return (
    <ThemeProvider>
      <DeepLinkProvider>
        <RouterProvider router={router} />
      </DeepLinkProvider>
    </ThemeProvider>
  )
}
