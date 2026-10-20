// Mirrors backend/app/models/schemas.py (source of truth). Do not diverge.
export type DecisionStatus = 'approved' | 'deferred' | 'rejected' | 'needs_review' | 'no_change'
export type RiskLevel = 'low' | 'medium' | 'high'
export type CheckStatus = 'passed' | 'triggered' | 'skipped'
export type ProposalStatus = 'proposed' | 'no_action' | 'insufficient_data'

export interface ResourceSettings {
  cpu_request_millicores: number | null
  memory_request_mib: number | null
  cpu_limit_millicores?: number | null
  memory_limit_mib?: number | null
}

export interface UsageMetrics {
  sample_count: number
  span_hours: number
  cpu_p95: number | null
  cpu_p99: number | null
  memory_p95: number | null
  memory_p99: number | null
  cpu_max?: number | null
  memory_max?: number | null
  last_observed_at?: string | null
}

export interface OptimizationProposal {
  proposal_id: string
  workload_id: string
  namespace: string
  status: ProposalStatus
  current: ResourceSettings
  proposed: ResourceSettings | null
  metrics: UsageMetrics
  reasons: string[]
  warnings: string[]
  estimated_monthly_saving_usd: number
  created_at: string
}

export interface CriticCheck {
  name: string
  code: string
  status: CheckStatus
  message: string
  evidence: Record<string, unknown>
}

/** OPTIONAL (not yet in schemas.py): hourly usage for the evidence chart. */
export interface UsagePoint {
   t: string; 
   cpu: number; 
   mem: number
   }
/** OPTIONAL (not yet in schemas.py): business events overlapping the decision. */

export interface EventWindow { 
  name: string; 
  start_at: string; 
  end_at: string; 
  risk?: string
 }
export interface WorkloadResult {
  workload_id: string
  namespace: string
  decision: DecisionStatus
  risk_level: RiskLevel
  reason: string
  checks: CriticCheck[]
  proposal: OptimizationProposal
  monthly_savings_estimate_usd: number
  yaml_patch: string | null
}

export interface AnalysisSummary {
  workloads_evaluated: number
  approved: number
  deferred: number
  rejected: number
  needs_review: number
  no_change: number
  estimated_monthly_savings_usd: number
}

export interface AnalysisResponse {
  analysis_id: string
  generated_at: string
  mode: string
  summary: AnalysisSummary
  results: WorkloadResult[]
  warnings: string[]
}

  yaml_patch: string | null
  usage_series?: UsagePoint[]
  events?: EventWindow[]
}