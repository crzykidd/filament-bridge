import { useState } from 'react'
import { authLogin, authSetup } from '../api/client'

interface LoginProps {
  passwordSet: boolean
  onAuthenticated: () => void
}

export default function Login({ passwordSet, onAuthenticated }: LoginProps) {
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const isSetup = !passwordSet

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')

    if (isSetup && password !== confirm) {
      setError('Passwords do not match.')
      return
    }
    if (!password) {
      setError('Password is required.')
      return
    }

    setLoading(true)
    try {
      if (isSetup) {
        await authSetup(password)
      } else {
        await authLogin(password)
      }
      onAuthenticated()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Authentication failed.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-8 w-full max-w-sm space-y-5">
        <div>
          <h1 className="text-xl font-bold text-gray-900">filament-bridge</h1>
          <p className="text-sm text-gray-500 mt-1">
            {isSetup ? 'Set an admin password to get started.' : 'Sign in to continue.'}
          </p>
        </div>

        <form onSubmit={(e) => { void handleSubmit(e) }} className="space-y-4">
          <div>
            <label htmlFor="password" className="block text-sm font-medium text-gray-700 mb-1">
              {isSetup ? 'New password' : 'Password'}
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
              autoFocus
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
            />
          </div>

          {isSetup && (
            <div>
              <label htmlFor="confirm" className="block text-sm font-medium text-gray-700 mb-1">
                Confirm password
              </label>
              <input
                id="confirm"
                type="password"
                value={confirm}
                onChange={e => setConfirm(e.target.value)}
                required
                className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
              />
            </div>
          )}

          {error && (
            <p className="text-sm text-red-600">{error}</p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-indigo-600 text-white rounded px-4 py-2 text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? (isSetup ? 'Setting up…' : 'Signing in…') : (isSetup ? 'Set password & continue' : 'Sign in')}
          </button>
        </form>

        {!isSetup && (
          <p className="text-xs text-gray-400">
            Locked out? Set <code>AUTH_ENABLED=false</code> in your environment, restart, change
            your password in Settings, then re-enable.
          </p>
        )}
      </div>
    </div>
  )
}
