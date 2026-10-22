import { useCallback, useEffect, useMemo, useState } from 'react'
import { fetchDashboard, fetchEvents, fetchLLMStatus, fetchWorkloadRows, runAnalysis, type LoadResult } from '@/api'
import { AnalysisContext, type AnalysisValue } from './analysis-context'
import type { DecisionStatus, DashboardSummary, EventRow, LLMStatus, WorkloadRow } from '@/types'

/**
 * The analysis, and everything derived from it, shared by every page.
 *
 * The dashboard was one long scroll with every panel stacked on it. Splitting it into pages means
 * the panels have to share their data, or each page would re-run the analysis. So the analysis
 * lives here, once, and the pages read from it.
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

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await runAnalysis(scenario)
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
    simulatorUnavailable,
  }), [state, loading, error, scenario, load, llmStatus, dashboard, events, workloadRows, filter, selectedId, simulatorUnavailable])

  return <AnalysisContext.Provider value={value}>{children}</AnalysisContext.Provider>
}
