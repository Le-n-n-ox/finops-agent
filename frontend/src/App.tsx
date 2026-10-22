import { useCallback, useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { FileDown, FileJson2, Info, Lock, Printer, RefreshCw, ServerCog, TriangleAlert } from 'lucide-react'
import { fetchDashboard, fetchEvents, fetchWorkloadRows, runAnalysis, type LoadResult } from '@/api'
import type { DecisionStatus, DashboardSummary, EventRow, WorkloadRow } from '@/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import { buildReport, downloadText } from '@/lib/report'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import AppToaster from '@/components/AppToaster'
import ThemeToggle from '@/components/ThemeToggle'
import ScenarioSwitcher from '@/components/ScenarioSwitcher'
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
import DetailPanel from '@/components/DetailPanel'
import DetailSheet from '@/components/DetailSheet'

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
  const [mode, setMode] = useState<'pipeline' | 'agent'>('pipeline')
  const [filter, setFilter] = useState<DecisionStatus | 'all'>('all')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [view, setView] = useState<'analysis' | 'policy' | 'history'>('analysis')
  const [dashboard, setDashboard] = useState<DashboardSummary | null>(null)
  const [events, setEvents] = useState<EventRow[] | null>(null)
  const [workloadRows, setWorkloadRows] = useState<WorkloadRow[] | null>(null)
  const isDesktop = useMediaQuery('(min-width: 1024px)')

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await runAnalysis(scenario, mode)
      setState(res)
      setFilter('all')
      // single-workload scenarios open their detail straight away (demo flow)
      setSelectedId(res.data.results.length === 1 ? res.data.results[0].workload_id : null)
      // History and events come from separate endpoints. A failure there must not fail the page, but
      // it must not leave the previous run's numbers on screen either: a stale trend is worse than
      // no trend, because it looks current.
      void fetchDashboard().then((d) => setDashboard(d.data))
      void fetchEvents().then((e) => setEvents(e.data))
      void fetchWorkloadRows().then((w) => setWorkloadRows(w.data))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load analysis')
    } finally {
      setLoading(false)
    }
  }, [scenario, mode])

  useEffect(() => { void load() }, [load])

  const visible = useMemo(
    () => (state?.data.results ?? []).filter((r) => filter === 'all' || r.decision === filter),
    [state, filter],
  )
  const selected = state?.data.results.find((r) => r.workload_id === selectedId) ?? null

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

  return (
    <div className="mx-auto max-w-7xl space-y-6 px-4 py-8">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="flex size-10 items-center justify-center rounded-lg bg-primary text-primary-foreground"><ServerCog className="size-5" aria-hidden /></span>
          <div>
            <h1 className="text-xl leading-tight font-semibold">Kubernetes FinOps Agent</h1>
            <p className="text-sm text-muted-foreground">Evidence-based, multi-agent resource recommendations</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline"><Lock aria-hidden />Recommendation-only</Badge>
          {state && (
            <Badge variant="outline" className={cn(state.source === 'api' && 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300')}>
              {state.source === 'api'
                ? `Live API · ${MODE_LABEL[state.data.mode] ?? state.data.mode}`
                : 'Mock data · API offline'}
            </Badge>
          )}
          {state?.source === 'mock' && <ScenarioSwitcher value={scenario} onChange={setScenario} />}
          <div className="flex items-center gap-1 rounded-lg border p-0.5 print:hidden" role="group" aria-label="Reasoning mode">
            <Button
              variant={mode === 'pipeline' ? 'secondary' : 'ghost'}
              size="sm"
              className="h-7"
              aria-pressed={mode === 'pipeline'}
              onClick={() => setMode('pipeline')}
              title="Deterministic optimizer and critic. No language model involved."
            >
              Pipeline
            </Button>
            <Button
              variant={mode === 'agent' ? 'secondary' : 'ghost'}
              size="sm"
              className="h-7"
              aria-pressed={mode === 'agent'}
              onClick={() => setMode('agent')}
              title="Proposer, Critic and Judge review cycle with evidence-based confidence scoring."
            >
              Agent cycle
            </Button>
          </div>
          <div className="flex items-center gap-2 print:hidden">
            <Button variant="outline" size="icon" onClick={() => void exportReport('markdown')} disabled={!state} aria-label="Export report as Markdown" title="Export report (Markdown)"><FileDown /></Button>
            <Button variant="outline" size="icon" onClick={() => void exportReport('json')} disabled={!state} aria-label="Export audit data as JSON" title="Export audit data (JSON)"><FileJson2 /></Button>
            <Button variant="outline" size="icon" onClick={() => window.print()} disabled={!state} aria-label="Print or save as PDF" title="Print / save as PDF"><Printer /></Button>
            <ThemeToggle />
            <Button onClick={() => void load()} disabled={loading}>
              <RefreshCw className={cn(loading && 'animate-spin')} aria-hidden />{loading ? 'Running…' : 'Run analysis'}
            </Button>
          </div>
        </div>
      </header>

      {error && (
        <p role="alert" className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
          <TriangleAlert className="size-4 shrink-0" aria-hidden />{error}
        </p>
      )}
      {loading && !state && <LoadingSkeleton />}

      {state && (
        <>
          <nav className="flex gap-1 border-b print:hidden" aria-label="Sections">
            {([['analysis', 'Analysis'], ['policy', 'Policy'], ['history', 'History']] as const).map(([key, label]) => (
              <button
                key={key}
                onClick={() => setView(key)}
                aria-current={view === key ? 'page' : undefined}
                className={cn(
                  'px-3 py-2 text-sm font-medium -mb-px border-b-2 transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50',
                  view === key ? 'border-primary text-foreground' : 'border-transparent text-muted-foreground hover:text-foreground',
                )}
              >
                {label}
              </button>
            ))}
          </nav>

          {view === 'policy' ? (
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
          <ProvenanceStrip data={state.data} />
          <Workflow data={state.data} />
          <InputStatus data={state.data} />
          <SummaryCards summary={state.data.summary} active={filter} onFilter={setFilter} />
          {!!state.data.top_opportunities?.length && <section className="rounded-xl border bg-card p-4" aria-label="Top ranked opportunities">
            <div className="mb-3 flex items-baseline justify-between gap-3">
              <h2 className="font-semibold">Top opportunities</h2>
              <span className="text-xs text-muted-foreground">Ranked from approved recommendations · top {state.data.top_n_findings ?? 5}</span>
            </div>
            <ol className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
              {state.data.top_opportunities.map((item, index) => <li key={item.workload_id} className="rounded-lg border p-3">
                <p className="text-xs text-muted-foreground">#{index + 1} · priority {item.priority_score.toFixed(2)}</p>
                <p className="font-medium">{item.workload_id}</p>
                <p className="text-sm">${item.monthly_savings_usd.toFixed(2)} / month</p>
                <p className="text-xs text-muted-foreground">{item.confidence_score.toFixed(0)}% confidence · {item.risk_level} risk</p>
              </li>)}
            </ol>
          </section>}
          <SavingsPotential results={state.data.results} />
          <div className="grid gap-6 md:grid-cols-2">
            <DecisionDonut summary={state.data.summary} active={filter} onFilter={setFilter} />
            <SavingsChart results={state.data.results} />
          </div>
          <div className="grid gap-6 lg:grid-cols-2">
            <TrendChart trend={dashboard?.trend ?? []} />
            <EventTimeline events={events ?? []} now={state.data.generated_at} />
          </div>
          <div className="grid items-start gap-6 lg:grid-cols-[1fr_440px]">
            <ResultsTable results={visible} selectedId={selectedId} onSelect={setSelectedId} workloadRows={workloadRows} />
            {isDesktop && (selected ? (
              <DetailPanel
                key={selected.workload_id}
                result={selected}
                reportId={state.data.analysis_id}
                simulatorUnavailable={simulatorUnavailable}
              />
            ) : (
              <p className="rounded-xl border border-dashed p-10 text-center text-sm text-muted-foreground">Select a workload to see evidence, the critic's audit trail and the proposed patch.</p>
            ))}
          </div>
          <footer className="border-t pt-4 text-xs text-muted-foreground">
            Prototype using local/mock data. Savings are illustrative estimates, not guaranteed bill reductions. Every change requires human approval; nothing is applied to a cluster.
          </footer>
            </>
          )}
        </>
      )}

      {!isDesktop && selected && state && (
        <DetailSheet
          result={selected}
          reportId={state.data.analysis_id}
          onClose={() => setSelectedId(null)}
          simulatorUnavailable={simulatorUnavailable}
        />
      )}
      <AppToaster />
    </div>
  )
}
