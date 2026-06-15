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
import DocsViewer from './pages/DocsViewer'
import { WizardShell } from './pages/Wizard'
import Login from './pages/Login'
import { getAuthStatus, register401Handler } from './api/client'
import type { AuthStatusResponse } from './api/types'
import { ThemeProvider } from './context/ThemeContext'

// Data router (createBrowserRouter) is required so pages can use `useBlocker`
// (e.g. Settings' unsaved-changes guard). The classic <BrowserRouter> component
// does not provide the data-router context that useBlocker needs.
const router = createBrowserRouter(
  createRoutesFromElements(
    <Route element={<Layout />}>
      <Route index element={<Dashboard />} />
      <Route path="synced-records" element={<SyncedRecords />} />
      <Route path="conflicts" element={<Conflicts />} />
      <Route path="sync-log" element={<SyncLog />} />
      <Route path="settings" element={<Settings />} />
      <Route path="opentag-cleanup" element={<OpenTagCleanup />} />
      <Route path="reconcile" element={<Reconcile />} />
      <Route path="wizard/*" element={<WizardShell />} />
      <Route path="docs" element={<DocsViewer />} />
      <Route path="docs/:slug" element={<DocsViewer />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Route>,
  ),
)

export default function App() {
  const [authStatus, setAuthStatus] = useState<AuthStatusResponse | null>(null)
  const [authLoading, setAuthLoading] = useState(true)

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

  // Show setup/login when auth is enabled and user is not authenticated
  if (authStatus && authStatus.auth_enabled && !authStatus.authenticated) {
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
