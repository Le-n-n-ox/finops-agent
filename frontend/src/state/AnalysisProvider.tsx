import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { fetchDashboard, fetchEvents, fetchLLMStatus, fetchWorkloadRows, streamAnalysis, type LoadResult } from '@/api'
import { AnalysisContext, type AnalysisValue } from './analysis-context'
import type {
  AnalysisResponse,
  DecisionStatus,
  DashboardSummary,
  EventRow,
  LLMStatus,
  WorkloadResult,
  WorkloadRow,
} from '@/types'

/**
 * The analysis, and everything derived from it, shared by every page.
 *
 * The dashboard was one long scroll with every panel stacked on it. Splitting it into pages means
 * the panels have to share their data, or each page would re-run the analysis. So the analysis
 * lives here, once, and the pages read from it.
 *
 * The run is streamed. A full analysis is a multi-turn conversation with the model server for
 * every workload, so it takes minutes - and a page that shows nothing for the whole of it is
 * indistinguishable from a broken one. Each workload appears as it is finished.
 */
export default function AnalysisProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<LoadResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [scenario, setScenario] = useState('all')
  const [llmStatus, setLlmStatus] = useState<LLMStatus | null>(null)
  const [dashboard, setDashboard] = useState<DashboardSummary | null>(null)
  const [events, setEvents] = useState<EventRow[] | null>(null)
  const [workloadRows, setWorkloadRows] = useState<WorkloadRow[] | null>(null)
  const [filter, setFilter] = useState<DecisionStatus | 'all'>('all')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  // How far the run has got. The totals come from the workload list, so the bar is honest about
  // how much is left even before the first workload is finished.
  const [progress, setProgress] = useState({ done: 0, total: 0, startedAt: 0 })

  // The results as they arrive, and the running summary built from them.
  const partial = useRef<WorkloadResult[]>([])

  const summarise = (results: WorkloadResult[]) => ({
    workloads_evaluated: results.length,
    approved: results.filter((r) => r.decision === 'approved').length,
    deferred: results.filter((r) => r.decision === 'deferred').length,
    rejected: results.filter((r) => r.decision === 'rejected').length,
    needs_review: results.filter((r) => r.decision === 'needs_review').length,
    no_change: results.filter((r) => r.decision === 'no_change').length,
    estimated_monthly_savings_usd: results
      .filter((r) => r.decision === 'approved')
      .reduce((sum, r) => sum + (r.monthly_savings_estimate_usd ?? 0), 0),
  })

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    partial.current = []
    setProgress({ done: 0, total: 0, startedAt: Date.now() })
    try {
      const res = await streamAnalysis(scenario, (result) => {
        // Each workload lands on screen as it is finished. The summary is recomputed from
        // what is in hand, so the numbers on screen always match the rows on screen.
        partial.current = [...partial.current, result]
        const results = [...partial.current]
        setProgress((p) => ({ ...p, done: results.length }))
        setState((current) => {
          const base = current?.data
          const running: AnalysisResponse = {
            analysis_id: base?.analysis_id ?? 'running',
            generated_at: base?.generated_at ?? new Date().toISOString(),
            mode: base?.mode ?? 'agent',
            summary: summarise(results),
            results,
            warnings: base?.warnings ?? [],
            policy_version: base?.policy_version,
            rule_version: base?.rule_version,
            input_fingerprint: base?.input_fingerprint,
            top_n_findings: base?.top_n_findings ?? 5,
            top_opportunities: base?.top_opportunities ?? [],
            llm_backend: base?.llm_backend,
            llm_model: base?.llm_model,
            llm_base_url: base?.llm_base_url,
          }
          return { data: running, source: 'api' }
        })
      }, (total) => setProgress((p) => ({ ...p, total })))
      setState(res)
      setFilter('all')
      // single-workload scenarios open their detail straight away (demo flow)
      setSelectedId(res.data.results.length === 1 ? res.data.results[0].workload_id : null)
      // History and events come from separate endpoints. A failure there must not fail the page,
      // but it must not leave the previous run's numbers on screen either: a stale trend is worse
      // than no trend, because it looks current.
      void fetchDashboard().then((d) => setDashboard(d.data))
      void fetchEvents().then((e) => setEvents(e.data))
      void fetchWorkloadRows().then((w) => setWorkloadRows(w.data))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load analysis')
    } finally {
      setLoading(false)
    }
  }, [scenario])

  useEffect(() => { void load() }, [load])

  // Which model server the backend resolved.
  //
  // Read when the app opens, not after the analysis: the point of the endpoint is to name the
  // model *before* anything has been produced, and by the time an analysis resolves the badge
  // has already taken the response's word for it - which would leave this branch of the header
  // unreachable. A failure here is not fatal: the analysis response carries the same facts, and
  // a backend without the endpoint must not stop the app.
  useEffect(() => {
    void fetchLLMStatus().then((s) => { if (s.data) setLlmStatus(s.data) })
  }, [])

  // The what-if needs a stored report on the backend to re-decide against. Offline it cannot run,
  // and saying so is better than a raw error toast.
  const simulatorUnavailable = state?.source === 'mock'
    ? 'The what-if needs the backend to re-run the critic, so it is unavailable while the app is running on mock data.'
    : undefined

  const value = useMemo<AnalysisValue>(() => ({
    state, loading, error, scenario, setScenario, reload: load, llmStatus,
    dashboard, events, workloadRows, filter, setFilter, selectedId, setSelectedId,
    simulatorUnavailable, progress,
  }), [state, loading, error, scenario, load, llmStatus, dashboard, events, workloadRows, filter, selectedId, simulatorUnavailable, progress])

  return <AnalysisContext.Provider value={value}>{children}</AnalysisContext.Provider>
}
