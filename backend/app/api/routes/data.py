"""Read-only dashboard data, events and the editable safety policy."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import Services, api_errors, get_services
from app.models.review import ReviewAction
from app.models.schemas import BusinessEvent, CriticPolicy, DecisionStatus, WorkloadResult
from app.services.critic_service import event_id

router = APIRouter(prefix="/api", tags=["data"])


class Opportunity(BaseModel):
    workload_id: str
    decision: DecisionStatus
    potential_saving_usd: float


class TrendPoint(BaseModel):
    report_id: str
    generated_at: datetime
    approved: int
    deferred: int
    rejected: int
    needs_review: int
    no_change: int
    savings_usd: float


class DashboardSummary(BaseModel):
    has_data: bool
    report_id: str | None = None
    generated_at: datetime | None = None
    workloads_analyzed: int = 0
    approved: int = 0
    deferred: int = 0
    rejected: int = 0
    needs_review: int = 0
    no_change: int = 0
    estimated_monthly_savings_usd: float = 0.0   # approved only
    potential_savings_usd: float = 0.0           # everything the optimizer proposed
    held_back_usd: float = 0.0                   # potential minus approved
    top_opportunities: list[Opportunity] = []
    trend: list[TrendPoint] = []                 # oldest -> newest


class WorkloadRow(BaseModel):
    workload_id: str
    namespace: str
    decision: DecisionStatus
    risk_level: str
    cpu_request_millicores: int | None
    proposed_cpu_request_millicores: int | None
    memory_request_mib: int | None
    proposed_memory_request_mib: int | None
    potential_saving_usd: float
    data_quality: int            # 0-100 = 60% sample volume (vs 72 h) + 40% freshness (vs stale_after_hours)
    latest_action: ReviewAction | None = None


class EventRow(BaseModel):
    event_id: str
    name: str
    start_at: datetime
    end_at: datetime
    services: list[str]
    expected_traffic: str
    risk: str
    notes: str


def _quality(r: WorkloadResult, now: datetime, stale_after: int) -> int:
    m = r.proposal.metrics
    volume = min(1.0, m.sample_count / 72)
    if m.last_observed_at is None:
        fresh = 0.0
    else:
        seen = m.last_observed_at if m.last_observed_at.tzinfo else m.last_observed_at.replace(tzinfo=timezone.utc)
        fresh = 1 - min(1.0, max(0.0, (now - seen).total_seconds() / 3600) / max(stale_after, 1))
    return round(100 * (0.6 * volume + 0.4 * fresh))


@router.get("/dashboard/summary", response_model=DashboardSummary)
def dashboard(svc: Services = Depends(get_services)) -> DashboardSummary:
    with api_errors():
        reports = svc.store.list_reports(20)
        if not reports:
            return DashboardSummary(has_data=False)
        latest, s = reports[0], reports[0].summary
        potential = round(sum(r.proposal.estimated_monthly_saving_usd for r in latest.results), 2)
        top = sorted(latest.results, key=lambda r: r.proposal.estimated_monthly_saving_usd, reverse=True)[:3]
        return DashboardSummary(
            has_data=True, report_id=latest.analysis_id, generated_at=latest.generated_at, workloads_analyzed=s.workloads_evaluated,
            approved=s.approved, deferred=s.deferred, rejected=s.rejected, needs_review=s.needs_review, no_change=s.no_change,
            estimated_monthly_savings_usd=s.estimated_monthly_savings_usd, potential_savings_usd=potential,
            held_back_usd=round(potential - s.estimated_monthly_savings_usd, 2),
            top_opportunities=[Opportunity(workload_id=r.workload_id, decision=r.decision,
                                           potential_saving_usd=r.proposal.estimated_monthly_saving_usd) for r in top],
            trend=[TrendPoint(report_id=r.analysis_id, generated_at=r.generated_at, approved=r.summary.approved,
                              deferred=r.summary.deferred, rejected=r.summary.rejected, needs_review=r.summary.needs_review,
                              no_change=r.summary.no_change, savings_usd=r.summary.estimated_monthly_savings_usd)
                   for r in reversed(reports)])


@router.get("/workloads", response_model=list[WorkloadRow])
def workloads(svc: Services = Depends(get_services)) -> list[WorkloadRow]:
    with api_errors():
        latest = svc.store.latest_report()
        if latest is None:
            return []
        stale_after = (svc.store.get_policy() or CriticPolicy()).stale_after_hours
        rows = []
        for r in latest.results:
            rec = svc.store.get_decision(f"DEC-{latest.analysis_id}-{r.workload_id}", with_snapshot=False)
            p = r.proposal
            rows.append(WorkloadRow(
                workload_id=r.workload_id, namespace=r.namespace, decision=r.decision, risk_level=r.risk_level.value,
                cpu_request_millicores=p.current.cpu_request_millicores, memory_request_mib=p.current.memory_request_mib,
                proposed_cpu_request_millicores=p.proposed.cpu_request_millicores if p.proposed else None,
                proposed_memory_request_mib=p.proposed.memory_request_mib if p.proposed else None,
                potential_saving_usd=p.estimated_monthly_saving_usd, data_quality=_quality(r, latest.generated_at, stale_after),
                latest_action=rec.latest_action if rec else None))
        return sorted(rows, key=lambda w: w.potential_saving_usd, reverse=True)


@router.get("/workloads/{workload_id}")
def workload(workload_id: str, svc: Services = Depends(get_services)) -> dict:
    """Latest decision snapshot (incl. usage_series when present) plus this workload's decision history."""
    with api_errors():
        latest = svc.store.latest_report()
        result = next((r for r in latest.results if r.workload_id == workload_id), None) if latest else None
        if result is None:
            raise HTTPException(404, f"Unknown workload: {workload_id}")
        return {"latest": result.model_dump(mode="json"),
                "history": [d.model_dump(mode="json") for d in svc.store.decisions(workload_id=workload_id, limit=50)]}


@router.get("/events", response_model=list[EventRow])
def events(svc: Services = Depends(get_services)) -> list[EventRow]:
    with api_errors():
        evs: list[BusinessEvent] = svc.bundle().events
        return [EventRow(event_id=event_id(e), name=e.name, start_at=e.start_at, end_at=e.end_at, services=e.services,
                         expected_traffic=e.expected_traffic, risk=e.risk, notes=e.notes)
                for e in sorted(evs, key=lambda e: e.start_at)]


@router.get("/policies", response_model=CriticPolicy)
def get_policy(svc: Services = Depends(get_services)) -> CriticPolicy:
    with api_errors():
        try:
            return svc.bundle().policy.critic
        except Exception:  # noqa: BLE001 - inputs unavailable (Dev 1 pipeline not merged): show saved or default policy
            return svc.store.get_policy() or CriticPolicy()


@router.put("/policies", response_model=CriticPolicy)
def put_policy(policy: CriticPolicy, svc: Services = Depends(get_services)) -> CriticPolicy:
    """Saved as a NEW policy version. Existing reports are flagged 'Expired — re-run analysis' on the next read."""
    with api_errors():
        if policy.change_window_start_hour >= policy.change_window_end_hour and (policy.change_window_start_hour, policy.change_window_end_hour) != (0, 24):
            raise ValueError("change_window_start_hour must be earlier than change_window_end_hour")
        if any(not 0 <= d <= 6 for d in policy.change_window_days):
            raise ValueError("change_window_days must contain values 0 (Mon) to 6 (Sun)")
        if not 0 < policy.max_reduction_pct <= 100:
            raise ValueError("max_reduction_pct must be between 0 and 100")
        return svc.store.save_policy(policy)