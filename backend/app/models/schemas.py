"""
SHARED CONTRACT between Developer 1 (data + optimizer) and Developer 2 (critic + API + UI).

Rules (see docs/CONTRACT.md):
  * Units are fixed: CPU = integer millicores, memory = integer MiB, timestamps = ISO-8601 with timezone.
  * Do NOT rename or remove a field without telling the other developer. Adding optional fields is fine.
  * Canonical workload key is `workload_id` (== the service name in deployments.yaml).
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# --------------------------------------------------------------------------- enums
class ProposalStatus(str, Enum):
    """Optimizer output (Developer 1)."""
    PROPOSED = "proposed"
    NO_CHANGE = "no_change"
    NEEDS_REVIEW = "needs_review"


class DecisionStatus(str, Enum):
    """Final critic decision (Developer 2). Only these five values reach the UI."""
    APPROVED = "approved"
    DEFERRED = "deferred"
    REJECTED = "rejected"
    NEEDS_REVIEW = "needs_review"
    NO_CHANGE = "no_change"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CheckStatus(str, Enum):
    PASSED = "passed"
    TRIGGERED = "triggered"
    SKIPPED = "skipped"


# --------------------------------------------------------------------------- raw inputs
class WorkloadSpec(BaseModel):
    """One row of data/deployments.yaml."""
    name: str = Field(min_length=1)
    namespace: str = "default"
    replicas: int = 1
    cpu_request_millicores: int | None = None
    cpu_limit_millicores: int | None = None
    memory_request_mib: int | None = None
    memory_limit_mib: int | None = None
    criticality: str = "medium"
    protected: bool = False
    autoscaler_enabled: bool | None = None


class UsageRow(BaseModel):
    """One row of data/usage_history.csv."""
    timestamp: datetime
    service: str = Field(min_length=1)
    cpu_millicores: float = Field(ge=0)
    memory_mib: float = Field(ge=0)
    namespace: str | None = None

    @field_validator("timestamp", mode="before")
    @classmethod
    def ensure_utc_timestamp(cls, value: Any) -> Any:
        """Interpret naive timestamps as UTC and normalize aware timestamps to UTC."""
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            else:
                value = value.astimezone(timezone.utc)
        return value


class BusinessEvent(BaseModel):
    """One entry of data/business_events.json."""
    name: str
    start_at: datetime
    end_at: datetime
    services: list[str]
    expected_traffic: str = "normal"   # low | normal | high
    risk: str = "low"                  # low | medium | high
    notes: str = ""
    expected_load_multiplier: float = Field(default=1.0, ge=1.0)
    freeze_optimization: bool = False


class IncidentRecord(BaseModel):
    """One row of data/incident_history.csv (used by Developer 2's critic)."""
    incident_id: str = Field(min_length=1)
    service: str = Field(min_length=1)
    occurred_at: datetime
    pattern: str            # e.g. "memory spike before campaign"
    summary: str = ""
    namespace: str | None = None
    incident_type: str | None = None
    severity: str | None = None

    @field_validator("occurred_at", mode="before")
    @classmethod
    def ensure_utc_incident_timestamp(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            else:
                value = value.astimezone(timezone.utc)
        return value


class CostModel(BaseModel):
    cpu_core_monthly_cost_usd: float | None = Field(default=None, ge=0)
    memory_gib_monthly_cost_usd: float | None = Field(default=None, ge=0)
    rate_uncertainty_pct: float = Field(default=20.0, ge=0, le=100)
    note: str = "Illustrative demo rates only; not a cloud-provider quote"


class OptimizerPolicy(BaseModel):
    """Developer 1 owns these. Demo heuristics, NOT production guarantees."""
    min_samples: int = 24
    min_span_hours: float = 24
    cpu_p95_multiplier: float = 1.25
    cpu_p99_multiplier: float = 1.10
    memory_p95_multiplier: float = 1.30
    memory_p99_multiplier: float = 1.15
    cpu_round_millicores: int = 10
    memory_round_mib: int = 64
    min_reduction_pct: float = 15.0
    max_metric_age_hours: float = 72   # latest metric older than this -> needs_review
    window_days: int = Field(default=30, ge=1, le=365)
    p99_min_samples: int = Field(default=100, ge=1)  # below this, p99 is omitted from the evidence summary
    criticality_headroom: dict[str, float] = Field(default_factory=dict)
    event_projection_hours: int = Field(default=168, ge=0)


class PolicyException(BaseModel):
    workload_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    expires_at: datetime


class CriticPolicy(BaseModel):
    """Developer 2 owns these. Every field added after v1 defaults to the previous behaviour."""
    version: str = "demo-1"                 # recorded in every decision snapshot (audit)
    rule_version: str = "rules-1"
    risk_window_hours: int = 48
    stale_after_hours: int = 72
    cpu_floor_p99_multiplier: float = 1.10
    memory_floor_p99_multiplier: float = 1.15
    min_monthly_saving_usd: float = 1.0
    top_n_findings: int = Field(default=5, ge=1, le=50)
    min_samples: int = 24                    # critic re-checks evidence volume (fail safe)
    min_cpu_request_millicores: int = 50     # absolute floors
    min_memory_request_mib: int = 128
    max_reduction_pct: float = 70.0          # largest allowed cut per resource
    protected_workloads: list[str] = []      # reductions are blocked
    excluded_workloads: list[str] = []       # never optimised -> no_change
    event_freeze_hours_after: int = 0        # keep deferring N hours after a high-impact event ends
    change_window_days: list[int] = []       # permitted weekdays (0=Mon..6=Sun); empty = any day
    change_window_start_hour: int = 0        # permitted hours [start, end) in the analysis clock's timezone
    change_window_end_hour: int = 24
    criticality_headroom: dict[str, float] = Field(default_factory=dict)
    policy_exceptions: list[PolicyException] = Field(default_factory=list)


class Policy(BaseModel):
    simulation_now: datetime | None = None   # fixed "clock" so tests do not age out
    optimizer: OptimizerPolicy = OptimizerPolicy()
    critic: CriticPolicy = CriticPolicy()


class ValidationIssue(BaseModel):
    severity: str                    # "error" | "warning"
    code: str                        # e.g. UNKNOWN_SERVICE, NEGATIVE_USAGE, BAD_TIMESTAMP
    message: str
    source: str | None = None        # file name
    workload_id: str | None = None


class InputBundle(BaseModel):
    """Everything load_inputs() returns."""
    services: list[WorkloadSpec]
    usage_rows: list[UsageRow]
    events: list[BusinessEvent]
    incidents: list[IncidentRecord] = []
    cost_model: CostModel | None = None
    policy: Policy = Policy()
    issues: list[ValidationIssue] = []


# --------------------------------------------------------------------------- Developer 1 output
class ResourceSettings(BaseModel):
    cpu_request_millicores: int | None = None
    memory_request_mib: int | None = None
    # Limits are shown as context only; the prototype NEVER proposes limit changes.
    cpu_limit_millicores: int | None = None
    memory_limit_mib: int | None = None


class UsageMetrics(BaseModel):
    sample_count: int = 0
    span_hours: float = 0.0
    cpu_p95: float | None = None
    cpu_p99: float | None = None
    memory_p95: float | None = None
    memory_p99: float | None = None
    cpu_max: float | None = None
    memory_max: float | None = None
    last_observed_at: datetime | None = None
    p99_reliable: bool = False


class MetricWindow(BaseModel):
    start: datetime | None = None
    end: datetime | None = None
    sample_count: int = 0


class DataQualityResult(BaseModel):
    workload_id: str
    usable_for_recommendation: bool
    sample_count: int
    last_observed_at: datetime | None = None
    is_stale: bool
    missing_fields: list[str] = []
    errors: list[str] = []
    warnings: list[str] = []


class UsageSummary(BaseModel):
    workload_id: str
    cpu_p50_m: float | None = None
    cpu_p95_m: float | None = None
    cpu_p99_m: float | None = None
    cpu_peak_m: float | None = None
    memory_p50_mib: float | None = None
    memory_p95_mib: float | None = None
    memory_p99_mib: float | None = None
    memory_peak_mib: float | None = None
    sample_count: int = 0
    window_start: datetime | None = None
    window_end: datetime | None = None
    p99_reliable: bool = False
    trend_hints: list[str] = []


class UsageAnomaly(BaseModel):
    metric_name: str
    observed_value: float
    baseline_value: float
    severity: str
    timestamp: datetime | None = None
    explanation: str


class AnomalyConfig(BaseModel):
    recent_window_samples: int = Field(default=6, ge=1)
    rise_ratio: float = Field(default=1.5, gt=1)
    min_absolute_increase_cpu_m: float = Field(default=100.0, ge=0)
    min_absolute_increase_memory_mib: float = Field(default=128.0, ge=0)


class ConfidenceFactor(BaseModel):
    name: str
    score: float = Field(ge=0, le=100)
    weight: float = Field(ge=0, le=1)
    explanation: str


class ConfidenceAssessment(BaseModel):
    score: float = Field(ge=0, le=100)
    label: str
    factors: list[ConfidenceFactor] = []
    explanation: str


class IncidentEvidence(BaseModel):
    incident_id: str
    timestamp: datetime
    incident_type: str
    severity: str
    description: str
    match_type: str
    relevance_reason: str


class SavingsEstimate(BaseModel):
    monthly_savings_usd: float | None = None
    monthly_savings_low_usd: float | None = None
    monthly_savings_high_usd: float | None = None
    cpu_request_reduction_pct: float = 0.0
    memory_request_reduction_pct: float = 0.0
    total_request_reduction_pct: float = 0.0
    pricing_available: bool = False
    replicas: int = 1
    days: int = 30
    assumptions: list[str] = []


class ResourceFinding(BaseModel):
    code: str
    category: str
    severity: RiskLevel
    message: str
    resource: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)


class RolloutGuidance(BaseModel):
    test_steps: list[str]
    watch_metrics: list[str]
    rollback: str


class PriorityBreakdown(BaseModel):
    value_score: float = Field(ge=0)
    confidence_score: float = Field(ge=0, le=100)
    risk_penalty: float = Field(ge=0, le=100)
    explanation: str


class OptimizationProposal(BaseModel):
    proposal_id: str
    workload_id: str
    namespace: str = "default"
    status: ProposalStatus
    current: ResourceSettings
    proposed: ResourceSettings | None = None     # requests only; None unless status == proposed
    metrics: UsageMetrics
    reasons: list[str] = []
    warnings: list[str] = []
    estimated_monthly_saving_usd: float = 0.0    # ILLUSTRATIVE estimate only
    created_at: datetime
    data_quality: DataQualityResult | None = None
    usage_summary: UsageSummary | None = None
    confidence: ConfidenceAssessment | None = None
    anomalies: list[UsageAnomaly] = []
    incident_evidence: list[IncidentEvidence] = []
    metric_window: MetricWindow | None = None
    savings_estimate: SavingsEstimate | None = None
    priority_score: float | None = Field(default=None, ge=0)
    priority_breakdown: PriorityBreakdown | None = None
    findings: list[ResourceFinding] = Field(default_factory=list)
    # What the critic suppressed. When an event, incident or policy exception blocks a reduction,
    # the optimizer's candidate and its saving are moved here instead of being erased, so the
    # reviewer can see what was found and what it cost to refuse it. Zero/None when nothing was
    # suppressed.
    suppressed_saving_usd: float = 0.0
    suppressed_proposal: ResourceSettings | None = None


# --------------------------------------------------------------------------- Developer 2 output
class CriticCheck(BaseModel):
    name: str                      # event_window | metrics_completeness | incident_pattern | resource_floor | benefit
    code: str                        # stable code, e.g. HIGH_IMPACT_EVENT
    status: CheckStatus
    message: str
    evidence: dict[str, Any] = {}  # event id, usage window, incident id, computed floor ...


class CriticObjection(BaseModel):
    """One red-team objection raised by the adversarial Critic phase of the review cycle."""
    code: str                        # stable code, e.g. "RECURRING_SPIKE_UNVERIFIED"
    severity: str = "advisory"       # "blocking" | "advisory"
    message: str
    source: str | None = None        # the tool or evidence the objection is grounded in


class ToolCall(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    tool: str
    params: Dict[str, Any]
    result: Any
    thought: Optional[str] = None


class ReviewCycle(BaseModel):
    """One phase of the Proposer -> Critic -> Judge cycle, kept separate so the reasoning is auditable."""
    role: str                        # "proposer" | "critic" | "judge"
    summary: str = ""
    steps: List[ToolCall] = []
    objections: List[CriticObjection] = []
    verdict: str | None = None       # phase verdict, e.g. "escalate" | "accept"
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None


class UsagePoint(BaseModel):
    """OPTIONAL chart data for the UI (hourly usage). Units as everywhere: millicores / MiB."""
    t: datetime
    cpu: float
    mem: float


class EventWindow(BaseModel):
    """OPTIONAL: business event overlapping the decision, for the UI chart band."""
    name: str
    start_at: datetime
    end_at: datetime
    risk: str | None = None


class WorkloadResult(BaseModel):
    workload_id: str
    namespace: str = "default"
    decision: DecisionStatus
    risk_level: RiskLevel
    reason: str
    # The agent's verification confidence. None in pipeline mode, where no agent runs: a default
    # of 0.0 would read as "the agent is certain of nothing" rather than "there was no agent".
    # The proposal's own factor-based score lives in proposal.confidence.score.
    confidence_score: float | None = Field(default=None, ge=0, le=100)
    confidence_basis: str = ""   # how confidence_score was derived, in one line
    evidence_trail: list[str] = Field(default_factory=list)
    objections: list[CriticObjection] = []   # adversarial objections raised during the review cycle
    cycles: list[ReviewCycle] = []           # proposer / critic / judge, in order (agent mode only)
    historical_lessons: list[str] = []       # human rejections injected into the proposer's prompt
    checks: list[CriticCheck] = []
    proposal: OptimizationProposal
    monthly_savings_estimate_usd: float = 0.0
    yaml_patch: str | None = None  # review-only
    usage_series: list[UsagePoint] = []   # optional, for the UI usage chart
    events: list[EventWindow] = []        # optional, for the UI event band
    rollout_guidance: RolloutGuidance | None = None


class AnalysisSummary(BaseModel):
    workloads_evaluated: int
    approved: int = 0
    deferred: int = 0
    rejected: int = 0
    needs_review: int = 0
    no_change: int = 0
    estimated_monthly_savings_usd: float = 0.0   # counts APPROVED decisions only


class WorkloadDataHealth(BaseModel):
    workload_id: str
    namespace: str
    sample_count: int
    required_samples: int
    span_hours: float
    required_span_hours: float
    latest_metric_age_hours: float | None = None
    max_metric_age_hours: float
    missing_metrics: bool = False
    sparse_metrics: bool = False
    stale_metrics: bool = False
    status: str


class ValidationResponse(BaseModel):
    generated_at: datetime
    source: str
    workloads_checked: int
    error_count: int
    warning_count: int
    workloads: list[WorkloadDataHealth]
    issues: list[ValidationIssue] = []


class AnalysisResponse(BaseModel):
    analysis_id: str
    generated_at: datetime
    mode: str = "demo"
    summary: AnalysisSummary
    results: list[WorkloadResult]
    warnings: list[str] = []
    input_issues: list[ValidationIssue] = []
    data_health: ValidationResponse | None = None
    policy_version: str = "demo-1"
    rule_version: str = "rules-1"
    input_fingerprint: str | None = None
    top_n_findings: int = 5
    top_opportunities: list["TopOpportunity"] = Field(default_factory=list)


class TopOpportunity(BaseModel):
    workload_id: str
    monthly_savings_usd: float
    priority_score: float
    confidence_score: float
    risk_level: RiskLevel

# --------------------------------------------------------------------------- Agent Schemas
class VerificationStep(BaseModel):
    claimed_value: str
    source_tool: Optional[str] = None
    status: str  # "verified" | "unverified"


class AgentAuditLog(BaseModel):
    session_id: str
    workload_id: str
    steps: List[ToolCall] = []
    cycles: List[ReviewCycle] = []           # proposer / critic / judge, in order
    final_decision: Optional[DecisionStatus] = None
    verification_report: List[VerificationStep] = []
    confidence_score: float = Field(default=0.0, ge=0, le=100)
    evidence_trail: List[str] = []
    historical_lessons: List[str] = []       # human rejections injected into the proposer prompt

class VerificationResult(BaseModel):
    is_valid: bool
    errors: List[str] = []
    verified_count: int = 0
    unverified_count: int = 0
