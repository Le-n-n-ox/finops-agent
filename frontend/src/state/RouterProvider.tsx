import { useCallback, useEffect, useMemo, useState } from 'react'
import { RouterContext } from './router-context'

/**
 * A minimal router.
 *
 * The dashboard is a handful of top-level sections, not a site with nested layouts, so a routing
 * library would be more machinery than the job needs. This gives what actually matters: real
 * URLs, a working back button, and a link you can paste to a colleague. The back button is the
 * reason to route at all — without it, a reviewer who opens a workload and goes back loses their
 * place entirely.
 */
export default function RouterProvider({ children }: { children: React.ReactNode }) {
  const [path, setPath] = useState(() => window.location.pathname)
  const [search, setSearch] = useState(() => window.location.search)

  useEffect(() => {
    const onPop = () => {
      setPath(window.location.pathname)
      setSearch(window.location.search)
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const navigate = useCallback((to: string, options?: { replace?: boolean }) => {
    const current = window.location.pathname + window.location.search
    if (to === current) return
    if (options?.replace) window.history.replaceState(null, '', to)
    else window.history.pushState(null, '', to)
    setPath(window.location.pathname)
    setSearch(window.location.search)
  }, [])

  const value = useMemo(() => ({ path, search, navigate }), [path, search, navigate])
  return <RouterContext.Provider value={value}>{children}</RouterContext.Provider>
}
