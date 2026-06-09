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
import { WizardShell } from './pages/Wizard'

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
      <Route path="wizard/*" element={<WizardShell />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Route>,
  ),
)

export default function App() {
  // DeepLinkProvider uses no router hooks, so it can wrap the RouterProvider.
  return (
    <DeepLinkProvider>
      <RouterProvider router={router} />
    </DeepLinkProvider>
  )
}
