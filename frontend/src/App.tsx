import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import { Info, PanelLeftClose, PanelLeftOpen, RefreshCw, TriangleAlert, X } from 'lucide-react'
import { fetchDashboard, fetchEvents, fetchWorkloadRows, runAnalysis, type LoadResult } from '@/api'
import type { DecisionStatus, DashboardSummary, EventRow, WorkloadRow } from '@/types'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { buildReport, downloadText } from '@/lib/report'
import { cn } from '@/lib/utils'
import { goHome, goLanding, goToWorkload, useHashRoute } from '@/hooks/useHashRoute'
import LandingPage from '@/components/landing/LandingPage'
import AppToaster from '@/components/AppToaster'
import Navbar, { Toolbar, type Mode } from '@/components/Navbar'
import Sidebar, { type View } from '@/components/Sidebar'
import WorkloadPage from '@/components/WorkloadPage'
import Workflow from '@/components/Workflow'
import InputStatus from '@/components/InputStatus'
import SummaryCards from '@/components/SummaryCards'
import DecisionDonut from '@/components/DecisionDonut'
import SavingsChart from '@/components/SavingsChart'
import SavingsPotential from '@/components/SavingsPotential'
import TrendChart from '@/components/TrendChart'
import EventTimeline from '@/components/EventTimeline'
import PolicyPanel from '@/components/PolicyPanel'
import DecisionHistory from '@/components/DecisionHistory'
import ProvenanceStrip from '@/components/ProvenanceStrip'
import ResultsTable from '@/components/ResultsTable'
import Band from '@/components/Band'
import TopOpportunities from '@/components/TopOpportunities'

function LoadingSkeleton() {
  return (
    <div className="space-y-6" aria-busy="true" aria-label="Loading analysis">
      <Skeleton className="h-20" />
      <Skeleton className="h-32" />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-24" />)}</div>
      <div className="grid gap-6 md:grid-cols-2"><Skeleton className="h-56" /><Skeleton className="h-56" /></div>
      <Skeleton className="h-64" />
    </div>
  )
}

/** The backend reports "demo" when the fixed demo clock is in use. Say what it means. */
const MODE_LABEL: Record<string, string> = {
  agent: 'agent cycle',
  demo: 'deterministic pipeline',
  pipeline: 'deterministic pipeline',
}

export default function App() {
  const [state, setState] = useState<LoadResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [scenario, setScenario] = useState('all')
  const [mode, setMode] = useState<Mode>('pipeline')
  const [filter, setFilter] = useState<DecisionStatus | 'all'>('all')
  const [view, setView] = useState<View>('analysis')
  const [dashboard, setDashboard] = useState<DashboardSummary | null>(null)
  const [events, setEvents] = useState<EventRow[] | null>(null)
  const [workloadRows, setWorkloadRows] = useState<WorkloadRow[] | null>(null)
  const [navOpen, setNavOpen] = useState(false)
  // The route is the URL: a workload opens on its own page, everything else is the dashboard.
  const route = useHashRoute()
  // The landing page is the front door and needs no analysis behind it, so nothing is run
  // until the reader steps into the workspace. This is a boolean rather than the route kind,
  // because home and workload are both "in the workspace" and must not restart the run.
  const inWorkspace = route.kind !== 'landing'

  // The rail can be folded down to its icons to give the tables and charts the width back.
  // The choice is remembered, because re-collapsing it on every reload is a small daily tax.
  const [railCollapsed, setRailCollapsed] = useState(
    () => localStorage.getItem('finops.rail-collapsed') === '1',
  )
  useEffect(() => {
    localStorage.setItem('finops.rail-collapsed', railCollapsed ? '1' : '0')
  }, [railCollapsed])

  // The bar wraps to two rows on narrow screens, so its height is not a constant. Measuring it
  // keeps the sidebar flush against the bar instead of guessing a pixel value that goes stale.
  const navRef = useRef<HTMLElement>(null)
  const [navHeight, setNavHeight] = useState(0)
  useEffect(() => {
    const el = navRef.current
    if (!el) return
    const observer = new ResizeObserver(([entry]) => setNavHeight(entry.contentRect.height))
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  // The drawer is a modal on small screens: Escape closes it and the page behind it must not
  // scroll away under the user's finger.
  useEffect(() => {
    if (!navOpen) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setNavOpen(false) }
    document.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
    }
  }, [navOpen])

  // Widening the window to desktop while the drawer is open would leave the page scroll-locked
  // with an invisible drawer on top of it. The listener, rather than a plain effect, means the
  // drawer is closed by the resize itself and not on every render that follows it.
  useEffect(() => {
    const mq = matchMedia('(min-width: 1024px)')
    const on = (e: MediaQueryListEvent) => { if (e.matches) setNavOpen(false) }
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])

  // A newer run supersedes the one in flight. The request is aborted so the backend is not asked
  // to do work nobody is waiting for, and the run id keeps a superseded run from overwriting the
  // results of the run that replaced it. Without this, React StrictMode's double-invoked effect
  // leaves two analyses writing to the same store at once.
  const runIdRef = useRef(0)
  const abortRef = useRef<AbortController | null>(null)

  const load = useCallback(async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    const runId = ++runIdRef.current

    setLoading(true)
    setError(null)
    try {
      const res = await runAnalysis(scenario, mode, controller.signal)
      if (runId !== runIdRef.current) return
      setState(res)
      setFilter('all')
      // single-workload scenarios open their detail straight away (demo flow)
      if (res.data.results.length === 1) goToWorkload(res.data.results[0].workload_id)
      // History and events come from separate endpoints. A failure there must not fail the page, but
      // it must not leave the previous run's numbers on screen either: a stale trend is worse than
      // no trend, because it looks current.
      void fetchDashboard().then((d) => { if (runId === runIdRef.current) setDashboard(d.data) })
      void fetchEvents().then((e) => { if (runId === runIdRef.current) setEvents(e.data) })
      void fetchWorkloadRows().then((w) => { if (runId === runIdRef.current) setWorkloadRows(w.data) })
    } catch (e) {
      // A superseded run is not a failure; the run that replaced it owns the screen now.
      if (runId !== runIdRef.current) return
      setError(e instanceof Error ? e.message : 'Failed to load analysis')
    } finally {
      if (runId === runIdRef.current) setLoading(false)
    }
  }, [scenario, mode])

  useEffect(() => {
    if (!inWorkspace) return
    void load()
    return () => { abortRef.current?.abort() }
  }, [load, inWorkspace])

  const visible = useMemo(
    () => (state?.data.results ?? []).filter((r) => filter === 'all' || r.decision === filter),
    [state, filter],
  )
  const selected = state?.data.results.find((r) => r.workload_id === (route.kind === 'workload' ? route.workloadId : null)) ?? null

  // The what-if needs a stored report on the backend to re-decide against. Offline it cannot run,
  // and saying so is better than a raw error toast.
  const simulatorUnavailable = state?.source === 'mock'
    ? 'The what-if needs the backend to re-run the critic, so it is unavailable while the app is running on mock data.'
    : undefined

  const exportReport = async (format: 'markdown' | 'json') => {
    if (!state) return
    const extension = format === 'markdown' ? 'md' : 'json'
    const filename = `finops-audit-report-${state.data.analysis_id}.${extension}`
    try {
      // Export the analysis that is ON SCREEN. Fetching a fresh report would hand the reviewer a
      // document describing a run they never looked at, which defeats the point of an audit trail.
      if (state.source === 'api') {
        const response = await fetch(`/api/report?format=${format}&report_id=${encodeURIComponent(state.data.analysis_id)}`)
        if (!response.ok) throw new Error(`Report API ${response.status}`)
        const content = format === 'markdown' ? await response.text() : JSON.stringify(await response.json(), null, 2)
        downloadText(filename, content, format === 'markdown' ? 'text/markdown' : 'application/json')
      } else if (format === 'markdown') {
        downloadText(filename, buildReport(state.data), 'text/markdown')
      } else {
        downloadText(filename, JSON.stringify(state.data, null, 2), 'application/json')
      }
      toast.success(`Report saved as ${filename}`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not export audit report')
    }
  }

  // Picking a section leaves the workload page: the sections are the dashboard's own views, and
  // a workload page is a page of its own.
  const pickView = (next: View) => {
    setView(next)
    goHome()
  }

  // The controls live in two places: the top bar on wide screens, the drawer on narrow ones.
  // They are described once here so the two surfaces can never drift apart.
  const toolbar = {
    source: state?.source ?? null,
    modeLabel: state ? MODE_LABEL[state.data.mode] ?? state.data.mode : '',
    mode,
    onModeChange: setMode,
    scenario,
    onScenarioChange: setScenario,
    loading,
    onRun: () => void load(),
    canExport: !!state,
    onExport: (format: 'markdown' | 'json') => void exportReport(format),
  }

  // The landing page has its own chrome, and none of the workspace's state applies to it.
  if (!inWorkspace) return <LandingPage />

  return (
    <div className="min-h-screen">
      <Navbar {...toolbar} ref={navRef} navOpen={navOpen} onOpenNav={() => setNavOpen(true)} />

      <div className="mx-auto flex w-full max-w-[1600px]">
        <aside className={cn('app-rail hidden shrink-0 lg:block', railCollapsed ? 'w-16' : 'w-60')}>
          <div className="sticky top-16 flex flex-col" style={navHeight ? { top: navHeight } : undefined}>
            <div className="flex-1 py-6">
              {!railCollapsed && (
                <p className="mb-2 px-3 text-xs font-semibold tracking-wide text-muted-foreground uppercase">Workspace</p>
              )}
              <Sidebar
                id="app-rail-nav"
                view={route.kind === 'workload' ? 'analysis' : view}
                onViewChange={pickView}
                collapsed={railCollapsed}
                onOverview={goLanding}
              />
            </div>
            <div className={cn('border-t py-3', railCollapsed ? 'flex justify-center' : 'px-3')}>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setRailCollapsed((c) => !c)}
                aria-expanded={!railCollapsed}
                aria-controls="app-rail-nav"
                aria-label={railCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
                title={railCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
                className={cn(railCollapsed && 'size-8 p-0')}
              >
                {railCollapsed ? <PanelLeftOpen aria-hidden /> : <PanelLeftClose aria-hidden />}
                {!railCollapsed && <span>Collapse</span>}
              </Button>
            </div>
          </div>
        </aside>

        <main className="min-w-0 flex-1 space-y-6 px-4 py-6 lg:px-6">

          {error && !state ? (
            // Nothing to show and no data: say what went wrong and offer a retry, rather than
            // leaving an empty page that looks like the app is broken.
            <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-6 text-center dark:border-red-900 dark:bg-red-950">
              <p className="flex items-start justify-center gap-2 text-sm font-medium text-red-800 dark:text-red-200">
                <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />{error}
              </p>
              <Button variant="outline" size="sm" className="mt-4" onClick={() => void load()}>
                <RefreshCw aria-hidden />Try again
              </Button>
            </div>
          ) : error && (
            <p role="alert" className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
              <TriangleAlert className="size-4 shrink-0" aria-hidden />{error}
            </p>
          )}
          {loading && !state && !error && <LoadingSkeleton />}

          {state && (
            <>
              {route.kind === 'workload' ? (
                selected ? (
                  <WorkloadPage
                    result={selected}
                    reportId={state.data.analysis_id}
                    onBack={goHome}
                    simulatorUnavailable={simulatorUnavailable}
                  />
                ) : (
                  <div className="rounded-xl border border-dashed p-10 text-center">
                    <p className="text-sm font-medium">{route.workloadId} is not in this analysis</p>
                    <p className="mt-1 text-sm text-muted-foreground">
                      It may have been analysed under a different scenario or policy. Run the analysis again, or go back to the workload list.
                    </p>
                    <Button variant="outline" size="sm" className="mt-4" onClick={goHome}>Back to all workloads</Button>
                  </div>
                )
              ) : view === 'policy' ? (
                <PolicyPanel onSaved={() => void load()} />
              ) : view === 'history' ? (
                <DecisionHistory />
              ) : (
                <>
              {state.data.warnings.map((w) => (
                <p key={w} className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
                  <Info className="size-4 shrink-0" aria-hidden />{w}
                </p>
              ))}

              {/* The page is one long report. Three bands, so a reader who lands in the middle
                  of it knows whether they are looking at how the run went, what it found, or the
                  evidence behind the finding. */}
              <div className="space-y-8">
                <section className="space-y-4" aria-label="How the run went">
                  <Band title="How the run went" />
                  <ProvenanceStrip data={state.data} />
                  <Workflow data={state.data} />
                  <InputStatus data={state.data} />
                </section>

                <section className="space-y-4" aria-label="What it found">
                  <Band title="What it found" />
                  <SummaryCards summary={state.data.summary} active={filter} onFilter={setFilter} />
                  {!!state.data.top_opportunities?.length && (
                    <TopOpportunities items={state.data.top_opportunities} />
                  )}
                  <SavingsPotential results={state.data.results} />
                </section>

                <section className="space-y-4" aria-label="The evidence">
                  <Band title="The evidence" />
                  <div className="grid gap-6 md:grid-cols-2">
                    <DecisionDonut summary={state.data.summary} active={filter} onFilter={setFilter} />
                    <SavingsChart results={state.data.results} />
                  </div>
                  <div className="grid gap-6 lg:grid-cols-2">
                    <TrendChart trend={dashboard?.trend ?? []} />
                    <EventTimeline events={events ?? []} now={state.data.generated_at} />
                  </div>
                  <ResultsTable
                    results={visible}
                    selectedId={null}
                    onSelect={(id) => goToWorkload(id)}
                    workloadRows={workloadRows}
                  />
                  <footer className="border-t pt-4 text-xs text-muted-foreground">
                    Prototype using local/mock data. Savings are illustrative estimates, not guaranteed bill reductions. Every change requires human approval; nothing is applied to a cluster.
                  </footer>
                </section>
              </div>
                </>
              )}
            </>
          )}

        </main>
      </div>

      {navOpen && (
        <div className="fixed inset-0 z-50 lg:hidden print:hidden" role="dialog" aria-modal="true" aria-label="Navigation" id="mobile-nav">
          <div className="absolute inset-0 bg-black/50" onClick={() => setNavOpen(false)} />
          <div className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col gap-4 overflow-y-auto border-r bg-background p-4 shadow-xl animate-in slide-in-from-left duration-200">
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold">Navigation</span>
              <Button variant="ghost" size="icon" onClick={() => setNavOpen(false)} aria-label="Close navigation">
                <X />
              </Button>
            </div>
            <Sidebar
              view={route.kind === 'workload' ? 'analysis' : view}
              onViewChange={pickView}
              onNavigate={() => setNavOpen(false)}
              onOverview={goLanding}
            />
            <div className="border-t pt-4">
              <Toolbar {...toolbar} layout="stack" />
            </div>
          </div>
        </div>
      )}

      <AppToaster />
    </div>
  )
}
