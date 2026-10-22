import { createContext, useContext } from 'react'

export interface RouterValue {
  /** The current path, e.g. "/workloads". */
  path: string
  /** The current query string, e.g. "?workload=email-worker". */
  search: string
  /** Go to a path. A query string is part of `to`. */
  navigate: (to: string, options?: { replace?: boolean }) => void
}

export const RouterContext = createContext<RouterValue>({
  path: '/',
  search: '',
  navigate: () => {},
})

export function useRouter(): RouterValue {
  return useContext(RouterContext)
}
