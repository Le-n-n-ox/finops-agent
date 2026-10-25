import { useEffect, useState } from 'react'

export type Route = { kind: 'landing' } | { kind: 'home' } | { kind: 'workload'; workloadId: string }

/**
 * The hash is the route: `#/workload/<id>` opens that workload's page, `#/` is the workspace,
 * and no hash at all is the landing page. A hash rather than a path, because the app is served
 * as static files: a deep link to `/workload/x` would 404 on reload, while `#/workload/x`
 * resolves however it is hosted.
 */
const WORKLOAD = /^#\/workload\/(.+)$/

function parse(hash: string): Route {
  const match = WORKLOAD.exec(hash)
  if (match) return { kind: 'workload', workloadId: decodeURIComponent(match[1]) }
  // An empty hash is the front door. The landing page explains the system before the
  // workspace asks for a run.
  if (hash === '' || hash === '#' || hash === '#/welcome') return { kind: 'landing' }
  return { kind: 'home' }
}

export function useHashRoute(): Route {
  const [route, setRoute] = useState(() => parse(location.hash))
  useEffect(() => {
    const on = () => setRoute(parse(location.hash))
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return route
}

/** Opens a workload's page. */
export function goToWorkload(workloadId: string) {
  location.hash = `#/workload/${encodeURIComponent(workloadId)}`
}

/** Returns to the dashboard. */
export function goHome() {
  location.hash = '#/'
}

/** Returns to the landing page, which is the route with no hash at all. */
export function goLanding() {
  location.hash = ''
}
