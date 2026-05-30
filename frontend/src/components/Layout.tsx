import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { getHealth } from '../api/client'
import type { HealthResponse } from '../api/types'

const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', exact: true },
  { to: '/synced-records', label: 'Synced Records', exact: false },
  { to: '/conflicts', label: 'Conflicts', exact: false },
  { to: '/sync-log', label: 'Sync Log', exact: false },
  { to: '/settings', label: 'Settings', exact: false },
  { to: '/wizard', label: 'Wizard', exact: false },
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
  const navigate = useNavigate()

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth(null))
  }, [])

  const statusDot = health
    ? health.status === 'ok'
      ? 'bg-green-400'
      : health.status === 'degraded'
        ? 'bg-yellow-400'
        : 'bg-red-400'
    : 'bg-gray-400'

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      {/* Sidebar */}
      <aside className="w-52 bg-indigo-800 flex flex-col shrink-0">
        <div className="px-4 py-4 border-b border-indigo-700">
          <button
            onClick={() => navigate('/')}
            className="text-white font-bold text-sm leading-tight text-left w-full"
          >
            filament-bridge
          </button>
          {health && (
            <p className="text-indigo-300 text-xs mt-1">v{health.bridge_version}</p>
          )}
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
        <div className="px-4 py-3 border-t border-indigo-700 flex items-center gap-2">
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
    </div>
  )
}
