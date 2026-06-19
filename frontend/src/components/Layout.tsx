import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useEffect, useRef, useState } from 'react'
import { getHealth, authLogout, getAuthStatus, getVersionInfo } from '../api/client'
import type { HealthResponse, VersionInfo } from '../api/types'
import { RequiredSettingsGate } from './RequiredSettingsGate'
import { useTheme } from '../context/ThemeContext'
import type { ThemeMode } from '../context/ThemeContext'

// ---------------------------------------------------------------------------
// Helpers for release-notes dismissal (per-version, localStorage)
// ---------------------------------------------------------------------------

const LS_KEY = 'fb_last_seen_version'
const LS_RUNNING_KEY = 'fb_last_running_version'

function getLastSeenVersion(): string | null {
  try {
    return localStorage.getItem(LS_KEY)
  } catch {
    return null
  }
}

function setLastSeenVersion(version: string): void {
  try {
    localStorage.setItem(LS_KEY, version)
  } catch {
    // ignore storage errors
  }
}

function getLastRunningVersion(): string | null {
  try {
    return localStorage.getItem(LS_RUNNING_KEY)
  } catch {
    return null
  }
}

function setLastRunningVersion(version: string): void {
  try {
    localStorage.setItem(LS_RUNNING_KEY, version)
  } catch {
    // ignore storage errors
  }
}

// ---------------------------------------------------------------------------
// Release-notes modal (generic — used for both "update available" and "post-upgrade")
// ---------------------------------------------------------------------------

interface ReleaseNotesModalProps {
  releaseName: string | null
  releaseNotes: string | null
  releaseUrl: string | null
  subtitle: string
  onDismiss: () => void
}

function ReleaseNotesModal({ releaseName, releaseNotes, releaseUrl, subtitle, onDismiss }: ReleaseNotesModalProps) {
  const overlayRef = useRef<HTMLDivElement>(null)

  // Dismiss on Esc
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onDismiss()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onDismiss])

  function handleBackdropClick(e: React.MouseEvent<HTMLDivElement>) {
    if (e.target === overlayRef.current) onDismiss()
  }

  return (
    <div
      ref={overlayRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={handleBackdropClick}
    >
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl max-w-lg w-full mx-4 flex flex-col max-h-[80vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 dark:border-gray-700">
          <div>
            <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
              {releaseName ?? 'Release notes'}
            </h2>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{subtitle}</p>
          </div>
          <button
            type="button"
            onClick={onDismiss}
            className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 text-xl leading-none"
            aria-label="Close"
          >
            ×
          </button>
        </div>
        {/* Body — release notes rendered as plain text (untrusted markdown from GitHub) */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {releaseNotes ? (
            <pre className="whitespace-pre-wrap text-sm text-gray-700 dark:text-gray-300 font-sans leading-relaxed">
              {releaseNotes}
            </pre>
          ) : (
            <p className="text-sm text-gray-500 dark:text-gray-400">No release notes available.</p>
          )}
        </div>
        {/* Footer */}
        <div className="px-5 py-3 border-t border-gray-200 dark:border-gray-700 flex items-center justify-between gap-3">
          {releaseUrl && (
            <a
              href={releaseUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline"
            >
              Full release notes ↗
            </a>
          )}
          <button
            type="button"
            onClick={onDismiss}
            className="ml-auto text-xs bg-indigo-600 text-white px-3 py-1.5 rounded hover:bg-indigo-700"
          >
            Got it
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Version badge component
// ---------------------------------------------------------------------------

// Which modal is currently showing: none, the "update available" modal, or the "post-upgrade" modal
type ModalKind = 'none' | 'update' | 'postupgrade'

function VersionBadge() {
  const [info, setInfo] = useState<VersionInfo | null>(null)
  const [activeModal, setActiveModal] = useState<ModalKind>('none')

  useEffect(() => {
    getVersionInfo()
      .then(v => {
        setInfo(v)

        // --- Post-upgrade flow (takes precedence over "update available") ---
        // Uses a separate localStorage key from the "update available" flow.
        const lastRunning = getLastRunningVersion()
        if (lastRunning === null) {
          // First ever run — record current version silently, no modal.
          setLastRunningVersion(v.current)
        } else if (lastRunning !== v.current && v.current_release_notes) {
          // Version changed since last run and we have release notes → show post-upgrade modal.
          setActiveModal('postupgrade')
          return
        }

        // --- "Update available" flow (only when post-upgrade modal isn't shown) ---
        // Only when update_available, a stored last-seen value existed (not first run),
        // and the new version was not already dismissed.
        if (v.update_available && v.latest) {
          const lastSeen = getLastSeenVersion()
          if (lastSeen !== null && lastSeen !== v.latest) {
            setActiveModal('update')
          }
        }
      })
      .catch(() => {
        // Fail silently — the badge just doesn't render
      })
  }, [])

  function dismissUpdateModal() {
    if (info?.latest) {
      setLastSeenVersion(info.latest)
    }
    setActiveModal('none')
  }

  function dismissPostUpgradeModal() {
    if (info?.current) {
      setLastRunningVersion(info.current)
    }
    setActiveModal('none')
  }

  if (!info) return null

  const buildLabel = info.build ?? `v${info.current}`
  const tagUrl = `https://github.com/crzykidd/filament-bridge/releases/tag/v${info.current}`
  const linkUrl = !info.update_available && info.release_url ? info.release_url : tagUrl

  return (
    <>
      <div className="flex flex-col gap-0.5">
        <a
          href={linkUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="text-indigo-300 text-xs hover:text-indigo-100 transition-colors"
          title={info.is_dev ? `channel: ${info.channel}${info.commit ? ` @ ${info.commit}` : ''}` : undefined}
        >
          {buildLabel}
        </a>
        {info.update_available && info.latest && (
          <a
            href={info.release_url ?? tagUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs bg-indigo-500 text-white px-1.5 py-0.5 rounded hover:bg-indigo-400 transition-colors leading-tight"
            title={`Update available: v${info.latest}`}
          >
            Update Available
          </a>
        )}
      </div>
      {activeModal === 'update' && (
        <ReleaseNotesModal
          releaseName={info.release_name}
          releaseNotes={info.release_notes}
          releaseUrl={info.release_url}
          subtitle="filament-bridge update"
          onDismiss={dismissUpdateModal}
        />
      )}
      {activeModal === 'postupgrade' && (
        <ReleaseNotesModal
          releaseName={info.current_release_name}
          releaseNotes={info.current_release_notes}
          releaseUrl={info.current_release_url}
          subtitle={`You're now running filament-bridge v${info.current}`}
          onDismiss={dismissPostUpgradeModal}
        />
      )}
    </>
  )
}

// ---------------------------------------------------------------------------
// Theme toggle — compact segmented control for the sidebar footer
// ---------------------------------------------------------------------------

const THEME_OPTIONS: { value: ThemeMode; label: string; title: string }[] = [
  { value: 'light', label: '☀', title: 'Light' },
  { value: 'system', label: '⊙', title: 'System' },
  { value: 'dark', label: '☾', title: 'Dark' },
]

function SidebarThemeToggle() {
  const { mode, setMode } = useTheme()
  return (
    <div className="flex rounded overflow-hidden border border-indigo-600" role="group" aria-label="Theme">
      {THEME_OPTIONS.map(opt => (
        <button
          key={opt.value}
          type="button"
          title={opt.title}
          onClick={() => setMode(opt.value)}
          className={`flex-1 py-1 text-xs font-medium transition-colors ${
            mode === opt.value
              ? 'bg-indigo-600 text-white'
              : 'text-indigo-300 hover:bg-indigo-700 hover:text-white'
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}

const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', exact: true },
  { to: '/synced-records', label: 'Synced Records', exact: false },
  { to: '/reconcile', label: 'Reconcile', exact: false },
  { to: '/conflicts', label: 'Conflicts', exact: false },
  { to: '/sync-log', label: 'Sync Log', exact: false },
  { to: '/wizard', label: 'Bulk Import Wizard', exact: false },
  { to: '/opentag-cleanup', label: 'OpenPrintTag Cleanup', exact: false },
]

function navClass({ isActive }: { isActive: boolean }) {
  return [
    'block px-3 py-2 rounded text-sm font-medium transition-colors',
    isActive
      ? 'bg-indigo-700 text-white'
      : 'text-indigo-100 hover:bg-indigo-700 hover:text-white',
  ].join(' ')
}

export function Layout() {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [authEnabled, setAuthEnabled] = useState(false)
  const [loggingOut, setLoggingOut] = useState(false)
  const navigate = useNavigate()

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth(null))
    getAuthStatus().then(s => setAuthEnabled(s.auth_enabled)).catch(() => {})
  }, [])

  const statusDot = health
    ? health.status === 'ok'
      ? 'bg-green-400'
      : health.status === 'degraded'
        ? 'bg-yellow-400'
        : 'bg-red-400'
    : 'bg-gray-400'

  async function handleLogout() {
    setLoggingOut(true)
    try {
      await authLogout()
      // Reload the page so App.tsx re-checks auth status and shows login
      window.location.reload()
    } catch {
      window.location.reload()
    }
  }

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50 dark:bg-gray-900">
      {/* Sidebar */}
      <aside className="w-52 bg-indigo-800 dark:bg-indigo-950 flex flex-col shrink-0">
        <div className="px-4 py-4 border-b border-indigo-700 dark:border-indigo-800">
          <button
            onClick={() => navigate('/')}
            className="text-white font-bold text-sm leading-tight text-left w-full"
          >
            filament-bridge
          </button>
          <div className="mt-1">
            <VersionBadge />
          </div>
        </div>
        <nav className="flex-1 px-2 py-3 space-y-1 overflow-y-auto">
          {NAV_ITEMS.map(item => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.exact}
              className={navClass}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        {/* Docs + Settings pinned at bottom, visually separated */}
        <div className="px-2 pb-1 border-t border-indigo-700 dark:border-indigo-800 pt-2">
          <NavLink to="/docs" end={false} className={navClass}>
            Docs
          </NavLink>
        </div>
        <div className="px-2 pb-2">
          <NavLink to="/settings" end={false} className={navClass}>
            Settings
          </NavLink>
        </div>
        {authEnabled && (
          <div className="px-2 pb-2">
            <button
              type="button"
              onClick={() => { void handleLogout() }}
              disabled={loggingOut}
              className="block w-full px-3 py-2 rounded text-sm font-medium text-indigo-200 hover:bg-indigo-700 hover:text-white text-left transition-colors disabled:opacity-50"
            >
              {loggingOut ? 'Signing out…' : 'Sign out'}
            </button>
          </div>
        )}
        {/* Theme toggle */}
        <div className="px-3 pb-2">
          <SidebarThemeToggle />
        </div>
        <div className="px-4 py-3 border-t border-indigo-700 dark:border-indigo-800 flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${statusDot}`} />
          <span className="text-indigo-200 text-xs">
            {health ? health.status : 'connecting…'}
          </span>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>

      {/* Required settings gate (overlays the whole app when needed) */}
      <RequiredSettingsGate />
    </div>
  )
}
