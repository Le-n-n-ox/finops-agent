"""Deterministic resource optimizer. Requests only; never touch limits."""
from __future__ import annotations

from datetime import datetime, timezone

from app.models.schemas import (
    AnomalyConfig,
    CostModel,
    DataQualityResult,
    IncidentEvidence,
    IncidentRecord,
    InputBundle,
    MetricWindow,
    OptimizationProposal,
    OptimizerPolicy,
    ProposalStatus,
    ResourceSettings,
    SavingsEstimate,
    UsageMetrics,
    UsageAnomaly,
    UsageRow,
    UsageSummary,
    WorkloadSpec,
)
from app.services.confidence_service import calculate_recommendation_confidence, score_priority
from app.services.data_loader import validate_usage_history
from app.services.incident_service import find_relevant_incidents, incident_quality_warning
from app.services.usage_service import detect_usage_anomalies, summarize_usage


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


def _analyze_workload_core(
    workload: WorkloadSpec,
    rows: list[UsageRow],
    policy: OptimizerPolicy | None = None,
    now: datetime | None = None,
    cost_model: CostModel | None = None,
) -> OptimizationProposal:
    """Analyze one workload and return its proposal or a reason for no change."""
    effective_policy = policy if policy is not None else OptimizerPolicy()
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
            status=ProposalStatus.NEEDS_REVIEW,
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

    if len(ordered_rows) < effective_policy.min_samples:
        return OptimizationProposal(
            proposal_id=proposal_id,
            workload_id=workload_id,
            namespace=namespace,
            current=current,
            status=ProposalStatus.NEEDS_REVIEW,
            metrics=metrics,
            reasons=[f"Only {len(ordered_rows)} observations; need {effective_policy.min_samples}."],
            created_at=now,
        )
    if span_hours < effective_policy.min_span_hours:
        return OptimizationProposal(
            proposal_id=proposal_id,
            workload_id=workload_id,
            namespace=namespace,
            current=current,
            status=ProposalStatus.NEEDS_REVIEW,
            metrics=metrics,
            reasons=[f"Usage history spans {span_hours:.1f} hours; need {effective_policy.min_span_hours:.1f}."],
            created_at=now,
        )
    if latest_age > effective_policy.max_metric_age_hours:
        return OptimizationProposal(
            proposal_id=proposal_id,
            workload_id=workload_id,
            namespace=namespace,
            current=current,
            status=ProposalStatus.NEEDS_REVIEW,
            metrics=metrics,
            reasons=[f"Latest metric is {latest_age:.1f} hours old; metrics older than "
                     f"{effective_policy.max_metric_age_hours:.1f} hours are insufficient."],
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
        max(cpu_p95 * effective_policy.cpu_p95_multiplier, cpu_p99 * effective_policy.cpu_p99_multiplier),
        effective_policy.cpu_round_millicores,
    )
    mem_candidate = round_up(
        max(mem_p95 * effective_policy.memory_p95_multiplier, mem_p99 * effective_policy.memory_p99_multiplier),
        effective_policy.memory_round_mib,
    )
    cpu_current = workload.cpu_request_millicores or 0
    mem_current = workload.memory_request_mib or 0

    minimum_remaining_ratio = 1 - effective_policy.min_reduction_pct / 100
    cpu_is_reduced = (
        cpu_p99 <= cpu_current
        and cpu_candidate < cpu_current
        and cpu_candidate <= cpu_current * minimum_remaining_ratio
    )
    mem_is_reduced = (
        mem_p99 <= mem_current
        and mem_candidate < mem_current
        and mem_candidate <= mem_current * minimum_remaining_ratio
    )
    if not cpu_is_reduced and not mem_is_reduced:
        warnings: list[str] = []
        if cpu_p99 > cpu_current or mem_p99 > mem_current:
            warnings.append("Observed P99 usage exceeds a current request; requests will not be raised.")
        return OptimizationProposal(
            proposal_id=proposal_id,
            workload_id=workload_id,
            namespace=namespace,
            current=current,
            status=ProposalStatus.NO_CHANGE,
            metrics=metrics,
            reasons=[f"Potential reduction is less than {effective_policy.min_reduction_pct:g}% for both resources."],
            warnings=warnings,
            created_at=now,
        )

    proposed_cpu = cpu_candidate if cpu_is_reduced else cpu_current
    proposed_mem = mem_candidate if mem_is_reduced else mem_current
    proposed = ResourceSettings(
        cpu_request_millicores=proposed_cpu,
        memory_request_mib=proposed_mem,
    )
    warnings: list[str] = []
    if cpu_p99 > cpu_current or mem_p99 > mem_current:
        warnings.append("Observed P99 usage exceeds a current request; that resource will not be reduced.")
    savings = _estimate_savings(workload, proposed, cost_model)
    return OptimizationProposal(
        proposal_id=proposal_id,
        workload_id=workload_id,
        namespace=namespace,
        current=current,
        proposed=proposed,
        status=ProposalStatus.PROPOSED,
        metrics=metrics,
        reasons=["Eligible requests meet the minimum reduction threshold and stay above the P99 safety floor."],
        warnings=warnings,
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
        analyze_workload(
            service,
            by_service.get(service.name, []),
            bundle.policy.optimizer,
            effective_now,
            bundle.cost_model,
            incidents=bundle.incidents,
            data_issues=[issue for issue in bundle.issues
                         if issue.workload_id in (None, service.name)
                         and (issue.source in ("usage_history.csv", "incident_history.csv", "usage_history", "incident_history")
                              or issue.code in {"BAD_ROW", "MISSING_COLUMNS", "UNKNOWN_SERVICE"})],
        )
        for service in bundle.services
    ]


def analyze_workload(
    workload: WorkloadSpec,
    rows: list[UsageRow],
    policy: OptimizerPolicy | None = None,
    now: datetime | None = None,
    cost_model: CostModel | None = None,
    *,
    incidents: list[IncidentRecord] | None = None,
    data_issues: list | None = None,
    anomaly_config: AnomalyConfig | None = None,
) -> OptimizationProposal:
    """Build a conservative optimizer proposal enriched with evidence and confidence."""
    effective_policy = policy if policy is not None else OptimizerPolicy()
    now = now or datetime.now(timezone.utc)
    proposal = _analyze_workload_core(workload, rows, effective_policy, now, cost_model)
    summary = summarize_usage(rows, workload.name, effective_policy.p99_min_samples)
    relevant_issues = [issue for issue in (data_issues or [])
                       if issue.workload_id in (None, workload.name)]
    input_errors = [issue.message for issue in relevant_issues if issue.severity == "error"]
    input_warnings = [issue.message for issue in relevant_issues if issue.severity != "error"]
    missing_fields = [
        column.strip().rstrip(".")
        for issue in relevant_issues if issue.code == "MISSING_COLUMNS"
        for column in issue.message.partition(":")[2].split(",")
        if column.strip()
    ]
    quality = validate_usage_history(
        rows,
        now,
        min_samples=effective_policy.min_samples,
        max_age_hours=effective_policy.max_metric_age_hours,
        workload_id=workload.name,
        errors=input_errors,
        missing_fields=missing_fields,
    )
    span = proposal.metrics.span_hours
    if rows and span < effective_policy.min_span_hours:
        quality.usable_for_recommendation = False
        quality.warnings.append(f"Usage spans {span:.1f} hours; {effective_policy.min_span_hours:.1f} required.")
    if input_warnings:
        quality.warnings.extend(input_warnings)
    anomalies = detect_usage_anomalies(summary, rows, anomaly_config)
    evidence = find_relevant_incidents(
        workload.name, incidents or [], namespace=workload.namespace,
    )
    incident_warning = incident_quality_warning(incidents or [], workload.name)
    if incident_warning:
        quality.warnings.append(incident_warning)

    # A malformed row for this workload is a hard optimizer stop; the critic still owns all
    # final review statuses and no approval/rejection is produced here.
    if input_errors and proposal.status == ProposalStatus.PROPOSED:
        proposal.status = ProposalStatus.NEEDS_REVIEW
        proposal.proposed = None
        proposal.estimated_monthly_saving_usd = 0.0
        proposal.reasons.append("Input validation errors prevent a trustworthy recommendation.")

    confidence = calculate_recommendation_confidence(
        quality,
        summary,
        anomalies,
        now,
        min_samples=effective_policy.min_samples,
        max_age_hours=effective_policy.max_metric_age_hours,
        cpu_values=[row.cpu_millicores for row in rows],
        memory_values=[row.memory_mib for row in rows],
    )
    savings = estimate_monthly_savings(
        proposal.current,
        proposal.proposed,
        cost_model,
        replicas=workload.replicas,
    )
    proposal.estimated_monthly_saving_usd = savings.monthly_savings_usd or 0.0
    proposal.metrics.p99_reliable = summary.p99_reliable
    proposal.data_quality = quality
    proposal.usage_summary = summary
    proposal.confidence = confidence
    proposal.anomalies = anomalies
    proposal.incident_evidence = evidence
    proposal.metric_window = MetricWindow(
        start=summary.window_start,
        end=summary.window_end,
        sample_count=summary.sample_count,
    )
    proposal.savings_estimate = savings
    if quality.warnings:
        proposal.warnings.extend(message for message in quality.warnings if message not in proposal.warnings)
    proposal.warnings.extend(item.explanation for item in anomalies if item.explanation not in proposal.warnings)
    proposal.warnings.extend(
        f"Related incident {item.incident_id} ({item.match_type} match): {item.description}"
        for item in evidence
    )

    value_score = (min(100.0, savings.monthly_savings_usd * 5.0)
                   if savings.monthly_savings_usd is not None
                   else min(100.0, savings.total_request_reduction_pct * 2.0))
    proposal.priority_score, proposal.priority_breakdown = score_priority(
        proposal, value_score, confidence.score,
    )
    return proposal


def recommend_resources(
    workload: WorkloadSpec,
    metrics: list[UsageRow],
    config: OptimizerPolicy | None = None,
    *,
    analysis_time: datetime | None = None,
    pricing: CostModel | None = None,
    incidents: list[IncidentRecord] | None = None,
    data_issues: list | None = None,
) -> OptimizationProposal:
    """Guide-name entry point; returns the shared optimizer proposal, never a critic decision."""
    return analyze_workload(
        workload,
        metrics,
        policy=config,
        now=analysis_time,
        cost_model=pricing,
        incidents=incidents,
        data_issues=data_issues,
    )


def estimate_monthly_savings(
    current: ResourceSettings,
    proposed: ResourceSettings | None,
    pricing: CostModel | None,
    replicas: int = 1,
    days: int = 30,
) -> SavingsEstimate:
    """Return USD only when both price rates exist; otherwise expose relative request change."""
    if proposed is None:
        cpu_rate = pricing.cpu_core_monthly_cost_usd if pricing is not None else None
        memory_rate = pricing.memory_gib_monthly_cost_usd if pricing is not None else None
        return SavingsEstimate(
            pricing_available=cpu_rate is not None and memory_rate is not None,
            replicas=replicas,
            days=days,
            assumptions=["No proposed request reduction exists."],
        )
    current_cpu = current.cpu_request_millicores or 0
    next_cpu = proposed.cpu_request_millicores or 0
    current_mem = current.memory_request_mib or 0
    next_mem = proposed.memory_request_mib or 0
    cpu_pct = max(0.0, (current_cpu - next_cpu) / current_cpu * 100) if current_cpu else 0.0
    memory_pct = max(0.0, (current_mem - next_mem) / current_mem * 100) if current_mem else 0.0
    active = [pct for pct, base in ((cpu_pct, current_cpu), (memory_pct, current_mem)) if base > 0]
    total_pct = sum(active) / len(active) if active else 0.0
    cpu_rate = pricing.cpu_core_monthly_cost_usd if pricing is not None else None
    memory_rate = pricing.memory_gib_monthly_cost_usd if pricing is not None else None
    priced = cpu_rate is not None and memory_rate is not None
    monthly: float | None = None
    assumptions = [f"Replica count: {replicas}.", f"Estimate period: {days} days, scaled from a 30-day month."]
    if cpu_rate is not None and memory_rate is not None and pricing is not None:
        cpu_delta = (current_cpu - next_cpu) / 1000
        memory_delta = (current_mem - next_mem) / 1024
        monthly = round(max(0.0, (cpu_delta * cpu_rate
                                  + memory_delta * memory_rate)
                            * replicas * days / 30), 2)
        assumptions.append(pricing.note)
    else:
        assumptions.append("Pricing is unavailable; no currency value is reported.")
    return SavingsEstimate(
        monthly_savings_usd=monthly,
        cpu_request_reduction_pct=round(cpu_pct, 2),
        memory_request_reduction_pct=round(memory_pct, 2),
        total_request_reduction_pct=round(total_pct, 2),
        pricing_available=priced,
        replicas=replicas,
        days=days,
        assumptions=assumptions,
    )


def rank_recommendations(recommendations: list[OptimizationProposal]) -> list[OptimizationProposal]:
    """Sort by deterministic opportunity score; critic decisions remain out of scope."""
    return sorted(recommendations, key=lambda proposal: -(proposal.priority_score or 0.0))


def _estimate_savings(workload: WorkloadSpec, proposed: ResourceSettings,
                      cost_model: CostModel | None) -> float:
    if cost_model is None:
        return 0.0
    
    current_cpu = workload.cpu_request_millicores or 0
    proposed_cpu = proposed.cpu_request_millicores or 0
    current_mem = workload.memory_request_mib or 0
    proposed_mem = proposed.memory_request_mib or 0
    
    cpu_cost = (cost_model.cpu_core_monthly_cost_usd or 0.0) if cost_model else 0.0
    mem_cost = (cost_model.memory_gib_monthly_cost_usd or 0.0) if cost_model else 0.0

    cpu_delta_cores = (current_cpu - proposed_cpu) / 1000
    memory_delta_gib = (current_mem - proposed_mem) / 1024
    
    monthly = (cpu_delta_cores * cpu_cost + memory_delta_gib * mem_cost) * workload.replicas
    return round(max(monthly, 0.0), 2)


def _as_utc(value: datetime) -> datetime:
    """Normalize timestamps so naive fixture values remain comparable."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
