import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { DeepLinkProvider } from './components/DeepLinkContext'
import Dashboard from './pages/Dashboard'
import SyncedRecords from './pages/SyncedRecords'
import Conflicts from './pages/Conflicts'
import SyncLog from './pages/SyncLog'
import Settings from './pages/Settings'
import OpenTagCleanup from './pages/OpenTagCleanup'
import { WizardShell } from './pages/Wizard'

export default function App() {
  return (
    <BrowserRouter>
      <DeepLinkProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Dashboard />} />
            <Route path="synced-records" element={<SyncedRecords />} />
            <Route path="conflicts" element={<Conflicts />} />
            <Route path="sync-log" element={<SyncLog />} />
            <Route path="settings" element={<Settings />} />
            <Route path="opentag-cleanup" element={<OpenTagCleanup />} />
            <Route path="wizard/*" element={<WizardShell />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </DeepLinkProvider>
    </BrowserRouter>
  )
}
