import type {
  AnalysisResponse,
  AuditRecord,
  CriticPolicy,
  DashboardSummary,
  DecisionRecord,
  EventRow,
  ReportDetail,
  ReviewRequest,
  SimulationResult,
  WorkloadRow,
} from '@/types'

export interface LoadResult {
  data: AnalysisResponse
  source: 'api' | 'mock'
}

export interface ScenarioInfo { id: string; label: string; description: string }

/**
 * A request that reached the backend and came back with an error.
 *
 * This is deliberately distinct from a network failure: the backend being absent means "show the
 * mock fixtures", but the backend erroring means something is wrong, and silently substituting
 * fixtures would misrepresent the state of the system to whoever is looking at it.
 */
export class BackendError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'BackendError'
    this.status = status
  }
}

/**
 * The result of a read that is allowed to fail.
 *
 * `failed` separates "the call failed" from "the call succeeded and there was nothing to show",
 * so a panel can say so instead of silently keeping the previous value on screen.
 */
export interface Fetched<T> {
  data: T | null
  failed: boolean
}

/**
 * How long a request may take before the UI stops waiting for it.
 *
 * The analysis can be slow: the agent cycle runs a proposer, a critic and a judge, and each of
 * them can call a model. Two minutes is generous for that. But a backend that never answers must
 * not leave the page waiting forever — that reads as a blank page with no explanation.
 */
const ANALYSIS_TIMEOUT_MS = 120_000

/** The panels that hang off the analysis are quick; a tenth of that is already a broken backend. */
const READ_TIMEOUT_MS = 20_000

const isTimeout = (e: unknown) =>
  e instanceof DOMException && (e.name === 'TimeoutError' || e.name === 'AbortError')

/**
 * Try POST /api/analyze; fall back to bundled fixtures so the UI works before the backend does.
 * `scenario` is sent to the API (ignored until backend supports it) and selects the mock fixture.
 *
 * `signal` cancels the request when the caller no longer wants the result. A cancelled run must
 * not fall back to the fixtures: the analysis may still be running on the backend, and showing
 * fixtures for it would present mock data as a completed analysis.
 */
export async function runAnalysis(scenario = 'all', mode = 'pipeline', signal?: AbortSignal): Promise<LoadResult> {
  const timeout = AbortSignal.timeout(ANALYSIS_TIMEOUT_MS)
  let res: Response
  try {
    res = await fetch('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scenario, mode }),
      signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
    })
  } catch (e) {
    if (signal?.aborted) {
      throw new BackendError('The analysis was superseded by a newer run.', 409)
    }
    // A backend that is unreachable and a backend that never answers are different failures. The
    // first can fall back to the fixtures, because nothing is running. The second might still be
    // working on the run, and showing fixtures for it would misrepresent a live analysis as a
    // completed one - so it is reported instead.
    if (isTimeout(e)) {
      throw new BackendError(
        `The backend did not answer within ${ANALYSIS_TIMEOUT_MS / 1000} seconds. It may be busy or stuck - check that it is running, then try again.`,
        408,
      )
    }
    // The backend is not reachable at all. Falling back to fixtures is honest here.
    return loadMock(scenario)
  }
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new BackendError(
      `The analysis failed (${res.status}). ${detail}`.trim(),
      res.status,
    )
  }
  return { data: (await res.json()) as AnalysisResponse, source: 'api' }
}

async function loadMock(scenario: string): Promise<LoadResult> {
  const safe = /^[a-z-]+$/.test(scenario) ? scenario : 'all'
  const res = await fetch(safe === 'all' ? '/mock/analysis.json' : `/mock/scenarios/${safe}.json`)
  if (!res.ok) throw new Error('Mock data not found. Run: npm run mock')
  return { data: (await res.json()) as AnalysisResponse, source: 'mock' }
}

export async function loadScenarios(): Promise<ScenarioInfo[]> {
  try {
    const res = await fetch('/mock/scenarios.json')
    return res.ok ? ((await res.json()) as ScenarioInfo[]) : []
  } catch {
    return []
  }
}

/**
 * Record a human review action. This is a workflow record only: accepting a decision for
 * implementation never deploys anything. Rejections carry structured reasons, which the agent
 * replays as "Historical Lessons" the next time it analyses the same workload.
 */
export async function submitReview(reportId: string, request: ReviewRequest): Promise<AuditRecord> {
  const res = await fetch(`/api/reports/${encodeURIComponent(reportId)}/review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    signal: AbortSignal.timeout(READ_TIMEOUT_MS),
  })
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(detail || `Review failed (${res.status})`)
  }
  return (await res.json()) as AuditRecord
}

// --------------------------------------------------------------------------- history & policy

/**
 * Fetch a JSON endpoint, reporting failure instead of swallowing it.
 *
 * The dashboard degrades to the analysis payload alone rather than failing: a missing history
 * endpoint must never take the whole page down. But it must not keep showing the previous
 * response either, so the caller can say the data is stale.
 */
async function getJSON<T>(path: string): Promise<Fetched<T>> {
  try {
    const res = await fetch(path, { signal: AbortSignal.timeout(READ_TIMEOUT_MS) })
    if (!res.ok) return { data: null, failed: true }
    return { data: (await res.json()) as T, failed: false }
  } catch {
    return { data: null, failed: true }
  }
}

/** Savings trend, potential-vs-held-back totals, and the top opportunities. */
export function fetchDashboard(): Promise<Fetched<DashboardSummary>> {
  return getJSON<DashboardSummary>('/api/dashboard/summary')
}

/** Per-workload rows including the data-quality score and the latest human review action. */
export function fetchWorkloadRows(): Promise<Fetched<WorkloadRow[]>> {
  return getJSON<WorkloadRow[]>('/api/workloads')
}

/** Business events with their risk level and the services they affect. */
export function fetchEvents(): Promise<Fetched<EventRow[]>> {
  return getJSON<EventRow[]>('/api/events')
}

/** The saved safety policy, or null when the backend is unavailable. */
export function fetchPolicy(): Promise<Fetched<CriticPolicy>> {
  return getJSON<CriticPolicy>('/api/policies')
}

/** The built-in policy defaults, so the editor can offer a reset. */
export function fetchDefaultPolicy(): Promise<Fetched<CriticPolicy>> {
  return getJSON<CriticPolicy>('/api/policies/defaults')
}

/**
 * Save a new policy version. The backend appends it; existing reports are then flagged stale.
 */
export async function savePolicy(policy: CriticPolicy): Promise<CriticPolicy> {
  const res = await fetch('/api/policies', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(policy),
    signal: AbortSignal.timeout(READ_TIMEOUT_MS),
  })
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(detail || `Could not save the policy (${res.status})`)
  }
  return (await res.json()) as CriticPolicy
}

/** Decision history, newest first. */
export function fetchDecisions(params: { workloadId?: string; status?: string; q?: string } = {}): Promise<Fetched<DecisionRecord[]>> {
  const query = new URLSearchParams()
  if (params.workloadId) query.set('workload_id', params.workloadId)
  if (params.status) query.set('status', params.status)
  if (params.q) query.set('q', params.q)
  query.set('limit', '50')
  return getJSON<DecisionRecord[]>(`/api/decisions?${query.toString()}`)
}

/** The stored report with each decision's audit trail and expiry status. */
export function fetchReportDetail(reportId: string): Promise<Fetched<ReportDetail>> {
  return getJSON<ReportDetail>(`/api/reports/${encodeURIComponent(reportId)}`)
}

/**
 * Ask the critic what it would decide for a hypothetical request.
 *
 * Nothing is saved and no patch is produced: this is a what-if, not a recommendation.
 */
export async function simulate(
  workloadId: string,
  requests: { cpu_request_millicores?: number | null; memory_request_mib?: number | null },
): Promise<SimulationResult> {
  const res = await fetch('/api/simulate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workload_id: workloadId, ...requests }),
    signal: AbortSignal.timeout(READ_TIMEOUT_MS),
  })
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(detail || `Simulation failed (${res.status})`)
  }
  return (await res.json()) as SimulationResult
}
