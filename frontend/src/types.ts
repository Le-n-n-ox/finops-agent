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
  /** What the optimizer found but a safety rule refused. Zero when nothing was suppressed. */
  suppressed_saving_usd?: number
  /** The candidate request the optimizer proposed before the critic suppressed it. */
  suppressed_proposal?: ResourceSettings | null
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

/** One red-team objection raised by the adversarial Critic phase. */
export interface CriticObjection {
  code: string
  severity: 'blocking' | 'advisory' | string
  message: string
  source?: string | null
}

/** One tool call made by the agent. */
export interface ToolCall {
  timestamp?: string
  tool: string
  params: Record<string, unknown>
  result: unknown
  thought?: string | null
}

/** One phase of the Proposer -> Critic -> Judge review cycle. */
export interface ReviewCycle {
  role: 'proposer' | 'critic' | 'judge' | string
  summary: string
  steps: ToolCall[]
  objections: CriticObjection[]
  verdict?: string | null
  started_at?: string
  completed_at?: string | null
}

export interface WorkloadResult {
  workload_id: string
  namespace: string
  decision: DecisionStatus
  risk_level: RiskLevel
  reason: string
  /**
   * Evidence-based confidence from the agent's verification pass (0-100).
   * Null in pipeline mode, where no agent runs. The proposal's own factor-based score is
   * `proposal.confidence.score` and is present in both modes.
   */
  confidence_score?: number | null
  /** One-line explanation of how confidence_score was derived. */
  confidence_basis?: string
  /** One line per tool the agent called. */
  evidence_trail?: string[]
  /** Adversarial objections raised during the Proposer -> Critic -> Judge cycle. */
  objections?: CriticObjection[]
  /** The three review phases, in order (agent mode only). */
  cycles?: ReviewCycle[]
  /** Human rejections from prior reviews, injected into the proposer's prompt. */
  historical_lessons?: string[]
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

// ----- reviewer workflow (backend/app/models/review.py)

export type ReviewAction = 'ACCEPTED_FOR_IMPLEMENTATION' | 'REJECTED' | 'NEEDS_INVESTIGATION'

export interface ReviewRequest {
  workload_id: string
  action: ReviewAction
  comment?: string | null
  reviewer?: string | null
  outcome?: string | null
  /** Structured objections. Replayed to the agent as "Historical Lessons" on the next run. */
  rejection_reasons?: string[]
  /** Which resource the objection targets, e.g. "memory". */
  resource?: string | null
  /** Free-form "do this instead" guidance for the agent. */
  reviewer_guidance?: string | null
}

export interface AuditRecord {
  id: number
  decision_id: string
  report_id: string
  workload_id: string
  action: ReviewAction
  comment: string | null
  reviewer: string | null
  created_at: string
  outcome: string | null
  rejection_reasons: string[]
  resource: string | null
  reviewer_guidance: string | null
}

// ----- dashboard / history endpoints

export interface Opportunity {
  workload_id: string
  decision: DecisionStatus
  potential_saving_usd: number
  priority_score: number
}

export interface TrendPoint {
  report_id: string
  generated_at: string
  approved: number
  deferred: number
  rejected: number
  needs_review: number
  no_change: number
  savings_usd: number
}

export interface DashboardSummary {
  has_data: boolean
  report_id: string | null
  generated_at: string | null
  workloads_analyzed: number
  approved: number
  deferred: number
  rejected: number
  needs_review: number
  no_change: number
  /** Counted for approved decisions only. */
  estimated_monthly_savings_usd: number
  /** Everything the optimizer proposed, approved or not. */
  potential_savings_usd: number
  /** Potential minus approved: what the safety rules held back. */
  held_back_usd: number
  top_opportunities: Opportunity[]
  /** Oldest -> newest. */
  trend: TrendPoint[]
}

export interface WorkloadRow {
  workload_id: string
  namespace: string
  decision: DecisionStatus
  risk_level: string
  cpu_request_millicores: number | null
  proposed_cpu_request_millicores: number | null
  memory_request_mib: number | null
  proposed_memory_request_mib: number | null
  potential_saving_usd: number
  priority_score: number
  /** 0-100: 60% sample volume vs 72h + 40% freshness vs stale_after_hours. */
  data_quality: number
  latest_action: ReviewAction | null
}

export interface EventRow {
  event_id: string
  name: string
  start_at: string
  end_at: string
  services: string[]
  expected_traffic: string
  risk: string
  notes: string
}

/** The editable safety policy (backend CriticPolicy). */
export interface CriticPolicy {
  version: string
  rule_version: string
  min_samples: number
  stale_after_hours: number
  max_reduction_pct: number
  min_monthly_saving_usd: number
  min_cpu_request_millicores: number
  min_memory_request_mib: number
  cpu_floor_p99_multiplier: number
  memory_floor_p99_multiplier: number
  risk_window_hours: number
  event_freeze_hours_after: number
  top_n_findings: number
  change_window_start_hour: number
  change_window_end_hour: number
  change_window_days: number[]
  protected_workloads: string[]
  excluded_workloads: string[]
  criticality_headroom: Record<string, number>
  policy_exceptions: PolicyException[]
}

export interface PolicyException {
  workload_id: string
  reason: string
  expires_at: string
}

/** Result of POST /api/simulate - a what-if, never saved, never applied. */
export interface SimulationResult {
  simulation: boolean
  label: string
  workload_id: string
  original_decision: DecisionStatus
  simulated: WorkloadResult
  cpu_change_pct: number | null
  memory_change_pct: number | null
  estimated_monthly_saving_usd: number
  cpu_headroom_pct: number | null
  memory_headroom_pct: number | null
}

/** One decision in the searchable history (backend DecisionRecord). */
export interface DecisionRecord {
  decision_id: string
  report_id: string
  workload_id: string
  namespace: string
  decision: DecisionStatus
  risk_level: RiskLevel
  reason: string
  created_at: string
  policy_version: string
  rule_version: string
  input_fingerprint: string | null
  config_hash: string
  metrics_at: string | null
  event_version: string
  latest_action: ReviewAction | null
  snapshot: WorkloadResult | null
}

export interface ExpiryResult {
  stale: boolean
  reasons: string[]
  message: string
}

export interface DecisionDetail {
  record: DecisionRecord
  patch: { workload_id: string; yaml: string; original_yaml: string; validation: { valid: boolean; errors: string[] }; ready_for_review: boolean } | null
  expiry: ExpiryResult | null
  audit: AuditRecord[]
}

export interface ReportDetail {
  report: AnalysisResponse
  decisions: DecisionDetail[]
}
