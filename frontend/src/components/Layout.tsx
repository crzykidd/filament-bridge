import { NavLink, Outlet, useNavigate, useLocation } from 'react-router-dom'
import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Components } from 'react-markdown'
import type { AnchorHTMLAttributes } from 'react'
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
// Release-notes modal — Markdown component map (trimmed subset for release-note content)
// ---------------------------------------------------------------------------

const releaseNotesComponents: Components = {
  p: ({ children, ...props }) => (
    <p className="text-sm text-gray-700 dark:text-gray-300 mb-3 leading-relaxed" {...props}>
      {children}
    </p>
  ),
  ul: ({ children, ...props }) => (
    <ul className="list-disc list-outside pl-5 mb-3 space-y-1 text-sm text-gray-700 dark:text-gray-300" {...props}>
      {children}
    </ul>
  ),
  ol: ({ children, ...props }) => (
    <ol className="list-decimal list-outside pl-5 mb-3 space-y-1 text-sm text-gray-700 dark:text-gray-300" {...props}>
      {children}
    </ol>
  ),
  li: ({ children, ...props }) => (
    <li className="leading-relaxed" {...props}>{children}</li>
  ),
  h3: ({ children, ...props }) => (
    <h3 className="text-sm font-semibold text-gray-800 dark:text-gray-200 mt-4 mb-2" {...props}>
      {children}
    </h3>
  ),
  h4: ({ children, ...props }) => (
    <h4 className="text-xs font-semibold text-gray-700 dark:text-gray-300 mt-3 mb-1" {...props}>
      {children}
    </h4>
  ),
  strong: ({ children, ...props }) => (
    <strong className="font-semibold text-gray-900 dark:text-gray-100" {...props}>{children}</strong>
  ),
  code: ({ children, ...props }) => (
    <code className="bg-gray-100 dark:bg-gray-700 text-gray-800 dark:text-gray-200 rounded px-1 py-0.5 text-xs font-mono" {...props}>
      {children}
    </code>
  ),
  a: ({ href, children, ...props }: AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-indigo-600 dark:text-indigo-400 hover:underline"
      {...props}
    >
      {children}
    </a>
  ),
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
        {/* Body — release notes rendered as Markdown */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {releaseNotes ? (
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={releaseNotesComponents}>
              {releaseNotes}
            </ReactMarkdown>
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
  { to: '/tare-editor', label: 'Tare Editor', exact: false },
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
  // Mobile-updates feature flag — read from the same /api/version payload the app
  // already loads (the VersionBadge fetches it too). Gates the "Mobile updates" nav item.
  const [mobileLabelsEnabled, setMobileLabelsEnabled] = useState(false)
  // Off-canvas sidebar state — only relevant below the `md` breakpoint. On
  // desktop the sidebar is always static/visible regardless of this flag.
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth(null))
    getAuthStatus().then(s => setAuthEnabled(s.auth_enabled)).catch(() => {})
    getVersionInfo().then(v => setMobileLabelsEnabled(v.mobile_labels_enabled)).catch(() => {})
  }, [])

  // Auto-close the mobile drawer whenever the route changes (e.g. tapping a nav
  // link), so the drawer doesn't linger over the freshly-navigated page.
  useEffect(() => {
    setSidebarOpen(false)
  }, [location.pathname])

  const navItems = mobileLabelsEnabled
    ? [...NAV_ITEMS, { to: '/mobile-updates', label: 'Mobile updates', exact: false }]
    : NAV_ITEMS

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
      {/* Mobile backdrop — only rendered (and only visible) below `md` while the
          drawer is open. Tapping it closes the drawer. */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/50 md:hidden"
          onClick={() => setSidebarOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Sidebar — static on desktop (`md:` and up), an off-canvas slide-in
          drawer below `md` driven by `sidebarOpen`. */}
      <aside
        className={[
          'w-52 bg-indigo-800 dark:bg-indigo-950 flex flex-col shrink-0',
          'fixed inset-y-0 left-0 z-40 transform transition-transform duration-200 ease-in-out',
          'md:static md:z-auto md:translate-x-0',
          sidebarOpen ? 'translate-x-0' : '-translate-x-full',
        ].join(' ')}
      >
        <div className="px-4 py-4 border-b border-indigo-700 dark:border-indigo-800 flex items-start justify-between gap-2">
          <div className="min-w-0">
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
          {/* Close button — mobile only */}
          <button
            type="button"
            onClick={() => setSidebarOpen(false)}
            className="md:hidden -mr-1 -mt-1 p-1 rounded text-indigo-200 hover:bg-indigo-700 hover:text-white"
            aria-label="Close navigation menu"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <nav className="flex-1 px-2 py-3 space-y-1 overflow-y-auto">
          {navItems.map(item => (
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
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Mobile top bar — holds the hamburger that re-opens the drawer.
            Hidden at `md` and up where the sidebar is always visible. */}
        <div className="md:hidden flex items-center gap-2 bg-indigo-800 dark:bg-indigo-950 px-3 py-2 shrink-0">
          <button
            type="button"
            onClick={() => setSidebarOpen(true)}
            className="p-1 rounded text-indigo-100 hover:bg-indigo-700 hover:text-white"
            aria-label="Open navigation menu"
          >
            <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          <span className="text-white font-bold text-sm">filament-bridge</span>
        </div>
        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>

      {/* Required settings gate (overlays the whole app when needed) */}
      <RequiredSettingsGate />
    </div>
  )
}
