"""Deterministic resource optimizer. Requests only; never touch limits."""
from __future__ import annotations

from datetime import datetime, timezone

from app.models.schemas import (
    CostModel,
    InputBundle,
    OptimizationProposal,
    OptimizerPolicy,
    ProposalStatus,
    ResourceSettings,
    UsageMetrics,
    UsageRow,
    WorkloadSpec,
)


def percentile(values: list[float], percentile_value: float) -> float:
    """Return a linearly interpolated percentile from a nonempty list."""
    if not values:
        raise ValueError("percentile requires at least one value")
    if not 0 <= percentile_value <= 100:
        raise ValueError("percentile must be between 0 and 100")
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile_value / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def round_up(value: float, unit: int) -> int:
    """Round a resource quantity up to the next unit multiple."""
    if unit <= 0:
        raise ValueError("rounding unit must be positive")
    return int(-(-value // unit) * unit)


def analyze_workload(
    workload: WorkloadSpec,
    rows: list[UsageRow],
    policy: OptimizerPolicy | None = None,
    now: datetime | None = None,
    cost_model: CostModel | None = None,
) -> OptimizationProposal:
    """Analyze one workload and return its proposal or a reason for no change."""
    policy = policy or OptimizerPolicy()
    now = now or datetime.now(timezone.utc)
    ordered_rows = sorted(rows, key=lambda row: row.timestamp)
    times = [row.timestamp for row in ordered_rows]
    cpu = [float(row.cpu_millicores) for row in ordered_rows]
    mem = [float(row.memory_mib) for row in ordered_rows]
    span_hours = 0.0
    if len(times) > 1:
        first = _as_utc(times[0])
        last = _as_utc(times[-1])
        span_hours = (last - first).total_seconds() / 3600

    proposal_id = f"{workload.name}:{times[-1].isoformat() if times else 'no-data'}"
    workload_id = workload.name
    namespace = workload.namespace
    current = ResourceSettings(
        cpu_request_millicores=workload.cpu_request_millicores,
        memory_request_mib=workload.memory_request_mib,
        cpu_limit_millicores=workload.cpu_limit_millicores,
        memory_limit_mib=workload.memory_limit_mib,
    )
    
    if not ordered_rows:
        metrics = UsageMetrics(
            sample_count=0,
            span_hours=0.0,
            last_observed_at=None,
        )
        return OptimizationProposal(
            proposal_id=proposal_id,
            workload_id=workload_id,
            namespace=namespace,
            current=current,
            status=ProposalStatus.INSUFFICIENT_DATA,
            metrics=metrics,
            reasons=["No usage observations."],
            created_at=now,
        )

    latest_age = (_as_utc(now) - _as_utc(times[-1])).total_seconds() / 3600
    metrics = UsageMetrics(
        sample_count=len(ordered_rows),
        span_hours=round(span_hours, 2),
        last_observed_at=times[-1],
    )

    if len(ordered_rows) < policy.min_samples:
        return OptimizationProposal(
            proposal_id=proposal_id,
            workload_id=workload_id,
            namespace=namespace,
            current=current,
            status=ProposalStatus.INSUFFICIENT_DATA,
            metrics=metrics,
            reasons=[f"Only {len(ordered_rows)} observations; need {policy.min_samples}."],
            created_at=now,
        )
    if span_hours < policy.min_span_hours:
        return OptimizationProposal(
            proposal_id=proposal_id,
            workload_id=workload_id,
            namespace=namespace,
            current=current,
            status=ProposalStatus.INSUFFICIENT_DATA,
            metrics=metrics,
            reasons=[f"Usage history spans {span_hours:.1f} hours; need {policy.min_span_hours:.1f}."],
            created_at=now,
        )
    if latest_age > policy.max_metric_age_hours:
        return OptimizationProposal(
            proposal_id=proposal_id,
            workload_id=workload_id,
            namespace=namespace,
            current=current,
            status=ProposalStatus.INSUFFICIENT_DATA,
            metrics=metrics,
            reasons=[f"Latest metric is {latest_age:.1f} hours old; metrics older than "
                     f"{policy.max_metric_age_hours:.1f} hours are insufficient."],
            created_at=now,
        )

    cpu_p95 = round(percentile(cpu, 95), 1)
    cpu_p99 = round(percentile(cpu, 99), 1)
    mem_p95 = round(percentile(mem, 95), 1)
    mem_p99 = round(percentile(mem, 99), 1)
    
    metrics = UsageMetrics(
        sample_count=len(ordered_rows),
        span_hours=round(span_hours, 2),
        cpu_p95=cpu_p95,
        cpu_p99=cpu_p99,
        memory_p95=mem_p95,
        memory_p99=mem_p99,
        cpu_max=max(cpu),
        memory_max=max(mem),
        last_observed_at=times[-1],
    )

    cpu_candidate = round_up(
        max(cpu_p95 * policy.cpu_p95_multiplier, cpu_p99 * policy.cpu_p99_multiplier),
        policy.cpu_round_millicores,
    )
    mem_candidate = round_up(
        max(mem_p95 * policy.memory_p95_multiplier, mem_p99 * policy.memory_p99_multiplier),
        policy.memory_round_mib,
    )
    cpu_current = workload.cpu_request_millicores or 0
    mem_current = workload.memory_request_mib or 0

    if cpu_p99 > cpu_current or mem_p99 > mem_current:
        return OptimizationProposal(
            proposal_id=proposal_id,
            workload_id=workload_id,
            namespace=namespace,
            current=current,
            status=ProposalStatus.NO_ACTION,
            metrics=metrics,
            reasons=["Observed P99 usage exceeds a current request; requests will not be raised."],
            warnings=["Usage exceeded the configured request."],
            created_at=now,
        )

    cpu_reduction = (cpu_current - cpu_candidate) / cpu_current * 100 if cpu_current > 0 else 0
    mem_reduction = (mem_current - mem_candidate) / mem_current * 100 if mem_current > 0 else 0
    if (cpu_candidate >= cpu_current or mem_candidate >= mem_current or
            max(cpu_reduction, mem_reduction) < policy.min_reduction_pct):
        return OptimizationProposal(
            proposal_id=proposal_id,
            workload_id=workload_id,
            namespace=namespace,
            current=current,
            status=ProposalStatus.NO_ACTION,
            metrics=metrics,
            reasons=[f"Potential reduction is less than {policy.min_reduction_pct:g}% for both resources."],
            created_at=now,
        )

    proposed = ResourceSettings(
        cpu_request_millicores=min(cpu_candidate, cpu_current),
        memory_request_mib=min(mem_candidate, mem_current),
        cpu_limit_millicores=workload.cpu_limit_millicores,
        memory_limit_mib=workload.memory_limit_mib,
    )
    savings = _estimate_savings(workload, proposed, cost_model)
    return OptimizationProposal(
        proposal_id=proposal_id,
        workload_id=workload_id,
        namespace=namespace,
        current=current,
        proposed=proposed,
        status=ProposalStatus.PROPOSED,
        metrics=metrics,
        reasons=["Requests can be reduced while staying above the configured P99 safety floor."],
        estimated_monthly_saving_usd=savings,
        created_at=now,
    )


def build_proposals(bundle: InputBundle, now: datetime | None = None) -> list[OptimizationProposal]:
    """Return one deterministic proposal per configured service."""
    effective_now = now or bundle.policy.simulation_now or datetime.now(timezone.utc)
    by_service: dict[str, list[UsageRow]] = {}
    known_services = {service.name for service in bundle.services}
    for row in bundle.usage_rows:
        if row.service in known_services:
            by_service.setdefault(row.service, []).append(row)
    return [
        analyze_workload(service, by_service.get(service.name, []), bundle.policy.optimizer,
                         effective_now, bundle.cost_model)
        for service in bundle.services
    ]


def _estimate_savings(workload: WorkloadSpec, proposed: ResourceSettings,
                      cost_model: CostModel | None) -> float:
    if cost_model is None:
        return 0.0
    
    current_cpu = workload.cpu_request_millicores or 0
    proposed_cpu = proposed.cpu_request_millicores or 0
    current_mem = workload.memory_request_mib or 0
    proposed_mem = proposed.memory_request_mib or 0
    
    cpu_cost = cost_model.cpu_core_monthly_cost_usd or 0.0
    mem_cost = cost_model.memory_gib_monthly_cost_usd or 0.0

    cpu_delta_cores = (current_cpu - proposed_cpu) / 1000
    memory_delta_gib = (current_mem - proposed_mem) / 1024
    
    monthly = (cpu_delta_cores * cpu_cost + memory_delta_gib * mem_cost) * workload.replicas
    return round(max(monthly, 0.0), 2)


def _as_utc(value: datetime) -> datetime:
    """Normalize timestamps so naive fixture values remain comparable."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)