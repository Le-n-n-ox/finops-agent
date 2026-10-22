import { createContext, useContext } from 'react'
import type { LoadResult } from '@/api'
import type { DecisionStatus, DashboardSummary, EventRow, LLMStatus, WorkloadRow } from '@/types'

export interface AnalysisValue {
  /** The analysis on screen, and whether it came from the API or the bundled fixtures. */
  state: LoadResult | null
  loading: boolean
  error: string | null
  scenario: string
  setScenario: (scenario: string) => void
  reload: () => void
  /**
   * Which model server the backend resolved, read once when the app opens so the header can
   * name it before anything has been produced.
   * Null when the status endpoint could not be reached; the analysis response is then the
   * authority on which model actually ran.
   */
  llmStatus: LLMStatus | null
  /** Savings trend and top opportunities, from the history endpoints. */
  dashboard: DashboardSummary | null
  /** Business events, from the history endpoints. */
  events: EventRow[] | null
  /** Per-workload data quality and the latest human action. */
  workloadRows: WorkloadRow[] | null
  /** Which decision the workload list is filtered to. */
  filter: DecisionStatus | 'all'
  setFilter: (filter: DecisionStatus | 'all') => void
  /** The workload whose detail is open. */
  selectedId: string | null
  setSelectedId: (id: string | null) => void
  /** Why the what-if cannot run, if it cannot. */
  simulatorUnavailable: string | undefined
  /**
   * How far the run has got: how many workloads are finished, how many there are, and when it
   * started. A full analysis is a multi-turn conversation with the model server for every
   * workload, so it takes minutes - this is what tells the reader it is working.
   */
  progress: { done: number; total: number; startedAt: number }
}

export const AnalysisContext = createContext<AnalysisValue | null>(null)

export function useAnalysis(): AnalysisValue {
  const value = useContext(AnalysisContext)
  if (!value) throw new Error('useAnalysis must be used inside <AnalysisProvider>')
  return value
}
