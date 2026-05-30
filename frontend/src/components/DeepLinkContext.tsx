import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { getHealth } from '../api/client'

interface DeepLinkBases {
  filamentdbUrl: string
  spoolmanUrl: string
}

const DeepLinkContext = createContext<DeepLinkBases>({ filamentdbUrl: '', spoolmanUrl: '' })

export function DeepLinkProvider({ children }: { children: ReactNode }) {
  const [bases, setBases] = useState<DeepLinkBases>({ filamentdbUrl: '', spoolmanUrl: '' })

  useEffect(() => {
    getHealth()
      .then(h => {
        setBases({
          filamentdbUrl: h.systems['filamentdb']?.url ?? '',
          spoolmanUrl: h.systems['spoolman']?.url ?? '',
        })
      })
      .catch(() => {
        // stay with empty strings — DeepLinks render as disabled
      })
  }, [])

  return <DeepLinkContext.Provider value={bases}>{children}</DeepLinkContext.Provider>
}

export function useDeepLinkBases() {
  return useContext(DeepLinkContext)
}
