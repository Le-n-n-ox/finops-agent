"""Developer 2 API/workflow models. NOT the shared contract: Dev 1 never imports these.
The shared contract (models/schemas.py) is unchanged apart from the optional additions agreed separately."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.models.schemas import AnalysisResponse, DecisionStatus, RiskLevel, WorkloadResult


class ReviewAction(str, Enum):
    ACCEPTED_FOR_IMPLEMENTATION = "ACCEPTED_FOR_IMPLEMENTATION"
    REJECTED = "REJECTED"
    NEEDS_INVESTIGATION = "NEEDS_INVESTIGATION"


# ----- simulator
class ResourceRequests(BaseModel):
    cpu_request_millicores: int = Field(gt=0, le=1_000_000)
    memory_request_mib: int = Field(gt=0, le=100_000_000)


class SimulationRequest(ResourceRequests):
    workload_id: str = Field(min_length=1, max_length=253)


class SimulationResult(BaseModel):
    simulation: bool = True
    label: str = "Simulation only — not the official report. Nothing was saved or applied."
    workload_id: str
    original_decision: DecisionStatus
    simulated: WorkloadResult
    cpu_change_pct: float | None
    memory_change_pct: float | None
    estimated_monthly_saving_usd: float
    cpu_headroom_pct: float | None      # simulated request above observed p99
    memory_headroom_pct: float | None


# ----- patch
class PatchChange(BaseModel):
    path: str
    before: Any = None
    after: Any = None


class PatchValidationResult(BaseModel):
    valid: bool
    changes: list[PatchChange] = []
    errors: list[str] = []


PATCH_BANNER = "Proposed patch — human review required. This application does not apply changes to a cluster."


class PatchArtifact(BaseModel):
    workload_id: str
    yaml: str
    original_yaml: str
    validation: PatchValidationResult
    ready_for_review: bool
    banner: str = PATCH_BANNER


# ----- history / audit / expiry
class AuditRecord(BaseModel):
    id: int
    decision_id: str
    report_id: str
    workload_id: str
    action: ReviewAction
    comment: str | None = None
    reviewer: str | None = None
    created_at: datetime


class ExpiryResult(BaseModel):
    stale: bool
    reasons: list[str] = []
    message: str = "Current"


class DecisionRecord(BaseModel):
    decision_id: str
    report_id: str
    workload_id: str
    namespace: str
    decision: DecisionStatus
    risk_level: RiskLevel
    reason: str
    created_at: datetime
    policy_version: str
    config_hash: str
    metrics_at: datetime | None
    event_version: str
    latest_action: ReviewAction | None = None
    snapshot: WorkloadResult | None = None   # omitted from list views


class ReviewRequest(BaseModel):
    workload_id: str = Field(min_length=1, max_length=253)
    action: ReviewAction
    comment: str | None = Field(default=None, max_length=2000)
    reviewer: str | None = Field(default=None, max_length=120)


class DecisionDetail(BaseModel):
    record: DecisionRecord
    patch: PatchArtifact | None
    expiry: ExpiryResult | None          # None = could not re-read inputs to check
    audit: list[AuditRecord]


class ReportDetail(BaseModel):
    report: AnalysisResponse
    decisions: list[DecisionDetail]