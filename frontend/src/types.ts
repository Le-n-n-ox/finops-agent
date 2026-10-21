// Mirrors backend/app/models/schemas.py (source of truth). Do not diverge.
export type DecisionStatus = 'approved' | 'deferred' | 'rejected' | 'needs_review' | 'no_change'
export type RiskLevel = 'low' | 'medium' | 'high'
export type CheckStatus = 'passed' | 'triggered' | 'skipped'
export type ProposalStatus = 'proposed' | 'no_change' | 'needs_review'

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
  p99_reliable?: boolean
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
  data_quality?: DataQualityResult | null
  usage_summary?: UsageSummary | null
  confidence?: ConfidenceAssessment | null
  anomalies?: UsageAnomaly[]
  incident_evidence?: IncidentEvidence[]
  metric_window?: MetricWindow | null
  savings_estimate?: SavingsEstimate | null
  priority_score?: number | null
  priority_breakdown?: PriorityBreakdown | null
  findings?: ResourceFinding[]
}

export interface DataQualityResult {
  workload_id: string
  usable_for_recommendation: boolean
  sample_count: number
  last_observed_at: string | null
  is_stale: boolean
  missing_fields: string[]
  errors: string[]
  warnings: string[]
}

export interface UsageSummary {
  workload_id: string
  cpu_p50_m: number | null
  cpu_p95_m: number | null
  cpu_p99_m: number | null
  cpu_peak_m: number | null
  memory_p50_mib: number | null
  memory_p95_mib: number | null
  memory_p99_mib: number | null
  memory_peak_mib: number | null
  sample_count: number
  window_start: string | null
  window_end: string | null
  p99_reliable: boolean
  trend_hints: string[]
}

export interface UsageAnomaly {
  metric_name: string
  observed_value: number
  baseline_value: number
  severity: string
  timestamp: string | null
  explanation: string
}

export interface ConfidenceFactor { name: string; score: number; weight: number; explanation: string }
export interface ConfidenceAssessment { score: number; label: string; factors: ConfidenceFactor[]; explanation: string }
export interface IncidentEvidence {
  incident_id: string
  timestamp: string
  incident_type: string
  severity: string
  description: string
  match_type: string
  relevance_reason: string
}
export interface MetricWindow { start: string | null; end: string | null; sample_count: number }
export interface SavingsEstimate {
  monthly_savings_usd: number | null
  monthly_savings_low_usd?: number | null
  monthly_savings_high_usd?: number | null
  cpu_request_reduction_pct: number
  memory_request_reduction_pct: number
  total_request_reduction_pct: number
  pricing_available: boolean
  replicas: number
  days: number
  assumptions: string[]
}
export interface ResourceFinding { code: string; category: string; severity: RiskLevel; message: string; resource?: string | null; evidence: Record<string, unknown> }
export interface RolloutGuidance { test_steps: string[]; watch_metrics: string[]; rollback: string }
export interface PriorityBreakdown { value_score: number; confidence_score: number; risk_penalty: number; explanation: string }

export interface CriticCheck {
  name: string
  code: string
  status: CheckStatus
  message: string
  evidence: Record<string, unknown>
}

/** OPTIONAL (not yet in schemas.py): hourly usage for the evidence chart. */
export interface UsagePoint { t: string; cpu: number; mem: number }
/** OPTIONAL (not yet in schemas.py): business events overlapping the decision. */
export interface EventWindow { name: string; start_at: string; end_at: string; risk?: string }

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
  usage_series?: UsagePoint[]
  events?: EventWindow[]
  rollout_guidance?: RolloutGuidance | null
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

/** OPTIONAL: load_inputs() validation issues (schemas.py ValidationIssue). */
export interface ValidationIssue {
  severity: 'error' | 'warning' | string
  code: string
  message: string
  source?: string | null
  workload_id?: string | null
}

export interface AnalysisResponse {
  analysis_id: string
  generated_at: string
  mode: string
  summary: AnalysisSummary
  results: WorkloadResult[]
  warnings: string[]
  input_issues?: ValidationIssue[]
  data_health?: ValidationResponse | null
  policy_version?: string
  rule_version?: string
  input_fingerprint?: string | null
  top_n_findings?: number
  top_opportunities?: TopOpportunity[]
}

export interface TopOpportunity { workload_id: string; monthly_savings_usd: number; priority_score: number; confidence_score: number; risk_level: RiskLevel }

export interface WorkloadDataHealth {
  workload_id: string
  namespace: string
  sample_count: number
  required_samples: number
  span_hours: number
  required_span_hours: number
  latest_metric_age_hours: number | null
  max_metric_age_hours: number
  missing_metrics: boolean
  sparse_metrics: boolean
  stale_metrics: boolean
  status: 'healthy' | 'warning' | 'error' | string
}

export interface ValidationResponse {
  generated_at: string
  source: string
  workloads_checked: number
  error_count: number
  warning_count: number
  workloads: WorkloadDataHealth[]
  issues: ValidationIssue[]
}
