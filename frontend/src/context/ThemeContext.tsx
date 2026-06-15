/**
 * ThemeContext — light / dark / system theme management.
 *
 * Persists the user's choice in localStorage under `fb_theme`.
 * `system` (the default) tracks the OS preference via matchMedia and
 * live-updates when the OS theme changes.
 * Applies by toggling the `dark` class on <html> and setting `color-scheme`
 * so native controls (scrollbars, date pickers, etc.) follow.
 */

import { createContext, useContext, useEffect, useState } from 'react'

export type ThemeMode = 'light' | 'dark' | 'system'

const LS_KEY = 'fb_theme'

function readStoredMode(): ThemeMode {
  try {
    const v = localStorage.getItem(LS_KEY)
    if (v === 'light' || v === 'dark' || v === 'system') return v
  } catch {
    // ignore
  }
  return 'system'
}

function applyTheme(mode: ThemeMode) {
  const root = document.documentElement
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
  const isDark = mode === 'dark' || (mode === 'system' && prefersDark)

  if (isDark) {
    root.classList.add('dark')
    root.style.colorScheme = 'dark'
  } else {
    root.classList.remove('dark')
    root.style.colorScheme = 'light'
  }
}

interface ThemeContextValue {
  mode: ThemeMode
  setMode: (mode: ThemeMode) => void
}

const ThemeContext = createContext<ThemeContextValue>({
  mode: 'system',
  setMode: () => undefined,
})

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(readStoredMode)

  function setMode(next: ThemeMode) {
    try {
      localStorage.setItem(LS_KEY, next)
    } catch {
      // ignore
    }
    setModeState(next)
    applyTheme(next)
  }

  // Apply on mount (in case React hydrates after the inline script)
  useEffect(() => {
    applyTheme(mode)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Live-update when OS theme changes (only relevant in `system` mode)
  useEffect(() => {
    if (mode !== 'system') return
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    function handleChange() {
      applyTheme('system')
    }
    mq.addEventListener('change', handleChange)
    return () => mq.removeEventListener('change', handleChange)
  }, [mode])

  return (
    <ThemeContext.Provider value={{ mode, setMode }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext)
}
