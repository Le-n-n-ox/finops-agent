"""Developer 2 — what-if simulator. Pure: copies the proposal, never mutates the source, saves nothing, applies nothing."""
from __future__ import annotations

from datetime import datetime

from app.models.review import ResourceRequests, SimulationResult
from app.models.schemas import InputBundle, OptimizationProposal, ProposalStatus, ResourceSettings
from app.services.critic_service import evaluate
from app.services.savings import estimate_monthly_saving


def _pct(cur: int | None, new: int) -> float | None:
    return round((new - cur) / cur * 100, 1) if cur else None


def _headroom(new: int, p99: float | None) -> float | None:
    return round((new / p99 - 1) * 100, 1) if p99 else None


def simulate_recommendation(proposal: OptimizationProposal, overrides: ResourceRequests, bundle: InputBundle,
                            now: datetime | None = None) -> SimulationResult:
    spec = next((s for s in bundle.services if s.name == proposal.workload_id), None)
    new = ResourceSettings(cpu_request_millicores=overrides.cpu_request_millicores, memory_request_mib=overrides.memory_request_mib)
    saving = estimate_monthly_saving(proposal.current, new, spec.replicas if spec else 1, bundle.cost_model)
    hypothetical = proposal.model_copy(deep=True, update={"status": ProposalStatus.PROPOSED, "proposed": new,
                                                          "estimated_monthly_saving_usd": saving})
    m, cur = proposal.metrics, proposal.current
    return SimulationResult(
        workload_id=proposal.workload_id,
        original_decision=evaluate(proposal, bundle, now).decision,
        simulated=evaluate(hypothetical, bundle, now),   # no patch is ever attached to a simulation
        cpu_change_pct=_pct(cur.cpu_request_millicores, new.cpu_request_millicores),
        memory_change_pct=_pct(cur.memory_request_mib, new.memory_request_mib),
        estimated_monthly_saving_usd=saving,
        cpu_headroom_pct=_headroom(new.cpu_request_millicores, m.cpu_p99),
        memory_headroom_pct=_headroom(new.memory_request_mib, m.memory_p99),
    )