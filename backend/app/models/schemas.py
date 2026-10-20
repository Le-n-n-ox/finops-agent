"""
SHARED CONTRACT between Developer 1 (data + optimizer) and Developer 2 (critic + API + UI).

Rules (see docs/CONTRACT.md):
  * Units are fixed: CPU = integer millicores, memory = integer MiB, timestamps = ISO-8601 with timezone.
  * Do NOT rename or remove a field without telling the other developer. Adding optional fields is fine.
  * Canonical workload key is `workload_id` (== the service name in deployments.yaml).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- enums
class ProposalStatus(str, Enum):
    """Optimizer output (Developer 1)."""
    PROPOSED = "proposed"
    NO_ACTION = "no_action"
    INSUFFICIENT_DATA = "insufficient_data"


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
    name: str
    namespace: str = "default"
    replicas: int = 1
    cpu_request_millicores: int
    cpu_limit_millicores: int
    memory_request_mib: int
    memory_limit_mib: int


class UsageRow(BaseModel):
    """One row of data/usage_history.csv."""
    timestamp: datetime
    service: str
    cpu_millicores: float = Field(ge=0)
    memory_mib: float = Field(ge=0)


class BusinessEvent(BaseModel):
    """One entry of data/business_events.json."""
    name: str
    start_at: datetime
    end_at: datetime
    services: list[str]
    expected_traffic: str = "normal"   # low | normal | high
    risk: str = "low"                  # low | medium | high
    notes: str = ""


class IncidentRecord(BaseModel):
    """One row of data/incident_history.csv (used by Developer 2's critic)."""
    incident_id: str
    service: str
    occurred_at: datetime
    pattern: str            # e.g. "memory spike before campaign"
    summary: str = ""


class CostModel(BaseModel):
    cpu_core_monthly_cost_usd: float
    memory_gib_monthly_cost_usd: float
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
    max_metric_age_hours: float = 72   # latest metric older than this -> insufficient_data


class CriticPolicy(BaseModel):
    """Developer 2 owns these."""
    risk_window_hours: int = 48
    stale_after_hours: int = 72
    cpu_floor_p99_multiplier: float = 1.10
    memory_floor_p99_multiplier: float = 1.15
    min_monthly_saving_usd: float = 1.0


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
    cost_model: CostModel
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


# --------------------------------------------------------------------------- Developer 2 output
class CriticCheck(BaseModel):
    name: str                      # event_window | metrics_completeness | incident_pattern | resource_floor | benefit
    code: str                      # stable code, e.g. HIGH_IMPACT_EVENT
    status: CheckStatus
    message: str
    evidence: dict[str, Any] = {}  # event id, usage window, incident id, computed floor ...


class WorkloadResult(BaseModel):
    workload_id: str
    namespace: str = "default"
    decision: DecisionStatus
    risk_level: RiskLevel
    reason: str
    checks: list[CriticCheck] = []
    proposal: OptimizationProposal
    monthly_savings_estimate_usd: float = 0.0
    yaml_patch: str | None = None  # review-only


class AnalysisSummary(BaseModel):
    workloads_evaluated: int
    approved: int = 0
    deferred: int = 0
    rejected: int = 0
    needs_review: int = 0
    no_change: int = 0
    estimated_monthly_savings_usd: float = 0.0   # counts APPROVED decisions only


class AnalysisResponse(BaseModel):
    analysis_id: str
    generated_at: datetime
    mode: str = "demo"
    summary: AnalysisSummary
    results: list[WorkloadResult]
    warnings: list[str] = []
