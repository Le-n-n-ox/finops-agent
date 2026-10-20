"""Deterministic proposal safety checks with optional LLM-written explanations."""
from __future__ import annotations

from datetime import datetime, timezone

import yaml

from app.integrations.nvidia_nim import explain
from app.models.schemas import (
    CheckStatus,
    CriticCheck,
    DecisionStatus,
    InputBundle,
    OptimizationProposal,
    ProposalStatus,
    RiskLevel,
    WorkloadResult,
)


def evaluate_proposal(proposal: OptimizationProposal, bundle: InputBundle) -> WorkloadResult:
    """Evaluate a proposal against metrics, events, incidents, floors, and savings."""
    critic_policy = bundle.policy.critic
    now = _as_utc(bundle.policy.simulation_now or datetime.now(timezone.utc))
    checks: list[CriticCheck] = []

    if proposal.status == ProposalStatus.INSUFFICIENT_DATA:
        checks.append(CriticCheck(
            name="metrics_completeness",
            code="INSUFFICIENT_METRICS",
            status=CheckStatus.TRIGGERED,
            message="Data history or observation count is insufficient for optimization.",
            evidence={"reasons": proposal.reasons, "sample_count": proposal.metrics.sample_count},
        ))
        return _build_result(
            proposal, DecisionStatus.NEEDS_REVIEW, RiskLevel.MEDIUM,
            "Insufficient usage data to generate a safe recommendation.", checks,
        )

    if proposal.status == ProposalStatus.NO_ACTION or proposal.proposed is None:
        checks.append(CriticCheck(
            name="optimizer_status",
            code="NO_OPTIMIZATION_NEEDED",
            status=CheckStatus.PASSED,
            message="Workload usage is already optimal or reduction is below threshold.",
            evidence={"reasons": proposal.reasons},
        ))
        return _build_result(
            proposal, DecisionStatus.NO_CHANGE, RiskLevel.LOW,
            "Workload is already operating within optimal resource targets.", checks,
        )

    has_event_conflict = False
    for event in bundle.events:
        if proposal.workload_id not in event.services and "all" not in event.services:
            continue
        start_diff_hours = (_as_utc(event.start_at) - now).total_seconds() / 3600
        end_diff_hours = (_as_utc(event.end_at) - now).total_seconds() / 3600
        if (-24 <= end_diff_hours <= critic_policy.risk_window_hours and
                start_diff_hours <= critic_policy.risk_window_hours and
                (event.risk.lower() in {"high", "medium"} or event.expected_traffic.lower() == "high")):
            has_event_conflict = True
            checks.append(CriticCheck(
                name="event_window",
                code="UPCOMING_BUSINESS_EVENT",
                status=CheckStatus.TRIGGERED,
                message=f"Upcoming high-impact event '{event.name}' risk window.",
                evidence={
                    "event_name": event.name,
                    "start_at": event.start_at.isoformat(),
                    "end_at": event.end_at.isoformat(),
                    "expected_traffic": event.expected_traffic,
                },
            ))
    if has_event_conflict:
        return _build_result(
            proposal, DecisionStatus.DEFERRED, RiskLevel.HIGH,
            "Resource changes deferred due to upcoming high-traffic business events.", checks,
        )
    checks.append(CriticCheck(
        name="event_window",
        code="NO_EVENT_CONFLICT",
        status=CheckStatus.PASSED,
        message="No conflicting business events in the evaluation window.",
    ))

    matching_incidents = [inc for inc in bundle.incidents if inc.service == proposal.workload_id]
    if matching_incidents:
        recent_incident = max(matching_incidents, key=lambda incident: _as_utc(incident.occurred_at))
        checks.append(CriticCheck(
            name="incident_pattern",
            code="HISTORICAL_INCIDENT_CORRELATION",
            status=CheckStatus.TRIGGERED,
            message=f"Historical incident pattern detected: '{recent_incident.pattern}'.",
            evidence={
                "incident_id": recent_incident.incident_id,
                "pattern": recent_incident.pattern,
                "summary": recent_incident.summary,
                "occurred_at": recent_incident.occurred_at.isoformat(),
            },
        ))
        return _build_result(
            proposal, DecisionStatus.NEEDS_REVIEW, RiskLevel.HIGH,
            f"Workload has past incident history ({recent_incident.incident_id}); manual review required.", checks,
        )
    checks.append(CriticCheck(
        name="incident_pattern",
        code="NO_INCIDENT_CORRELATION",
        status=CheckStatus.PASSED,
        message="No relevant incident history associated with this workload.",
    ))

    proposed = proposal.proposed
    p99_cpu = proposal.metrics.cpu_p99 or 0.0
    p99_memory = proposal.metrics.memory_p99 or 0.0
    proposed_cpu = proposed.cpu_request_millicores or 0
    proposed_memory = proposed.memory_request_mib or 0
    cpu_floor = p99_cpu * critic_policy.cpu_floor_p99_multiplier
    memory_floor = p99_memory * critic_policy.memory_floor_p99_multiplier
    floor_violation = False

    if proposed_cpu < cpu_floor:
        floor_violation = True
        checks.append(CriticCheck(
            name="resource_floor",
            code="CPU_FLOOR_VIOLATION",
            status=CheckStatus.TRIGGERED,
            message=f"Proposed CPU request ({proposed_cpu}m) drops below P99 safety floor ({cpu_floor:.1f}m).",
            evidence={"proposed": proposed_cpu, "required_floor": cpu_floor, "p99": p99_cpu},
        ))
    if proposed_memory < memory_floor:
        floor_violation = True
        checks.append(CriticCheck(
            name="resource_floor",
            code="MEMORY_FLOOR_VIOLATION",
            status=CheckStatus.TRIGGERED,
            message=f"Proposed memory request ({proposed_memory}MiB) drops below P99 safety floor ({memory_floor:.1f}MiB).",
            evidence={"proposed": proposed_memory, "required_floor": memory_floor, "p99": p99_memory},
        ))
    if floor_violation:
        return _build_result(
            proposal, DecisionStatus.REJECTED, RiskLevel.HIGH,
            "Proposed reduction breaches required P99 headroom safety floors.", checks,
        )
    checks.append(CriticCheck(
        name="resource_floor",
        code="HEADROOM_FLOOR_SAFE",
        status=CheckStatus.PASSED,
        message="Proposed requests maintain safe headroom above P99 usage peaks.",
    ))

    savings = proposal.estimated_monthly_saving_usd
    if savings < critic_policy.min_monthly_saving_usd:
        checks.append(CriticCheck(
            name="benefit",
            code="INSIGNIFICANT_SAVINGS",
            status=CheckStatus.TRIGGERED,
            message=f"Monthly savings (${savings:.2f}) below threshold (${critic_policy.min_monthly_saving_usd:.2f}).",
            evidence={"estimated_savings": savings, "min_required": critic_policy.min_monthly_saving_usd},
        ))
        return _build_result(
            proposal, DecisionStatus.NO_CHANGE, RiskLevel.LOW,
            "Estimated monthly savings are too small to justify workload redeployment.", checks,
        )
    checks.append(CriticCheck(
        name="benefit",
        code="SAVINGS_THRESHOLD_MET",
        status=CheckStatus.PASSED,
        message=f"Projected savings (${savings:.2f}/mo) meet minimum economic threshold.",
    ))

    return _build_result(
        proposal, DecisionStatus.APPROVED, RiskLevel.LOW,
        "Proposal passed all safety, event, incident, and headroom checks.", checks,
        yaml_patch=_generate_yaml_patch(proposal), monthly_savings=savings,
    )


def _build_result(
    proposal: OptimizationProposal,
    decision: DecisionStatus,
    risk_level: RiskLevel,
    default_reason: str,
    checks: list[CriticCheck],
    yaml_patch: str | None = None,
    monthly_savings: float = 0.0,
) -> WorkloadResult:
    """Build the final result; NIM may phrase checks but cannot change decisions."""
    nim_reason = explain(decision=decision.value, checks=[check.model_dump() for check in checks])
    return WorkloadResult(
        workload_id=proposal.workload_id,
        namespace=proposal.namespace,
        decision=decision,
        risk_level=risk_level,
        reason=nim_reason or default_reason,
        checks=checks,
        proposal=proposal,
        monthly_savings_estimate_usd=monthly_savings if decision == DecisionStatus.APPROVED else 0.0,
        yaml_patch=yaml_patch,
    )


def _generate_yaml_patch(proposal: OptimizationProposal) -> str | None:
    """Render a review-only partial Deployment patch using safe YAML serialization."""
    proposed = proposal.proposed
    if proposed is None:
        return None
    cpu = proposed.cpu_request_millicores
    memory = proposed.memory_request_mib
    if cpu is None or memory is None:
        return None
    patch = {
        "spec": {
            "template": {
                "spec": {
                    "containers": [{
                        "name": proposal.workload_id,
                        "resources": {"requests": {"cpu": f"{cpu}m", "memory": f"{memory}Mi"}},
                    }],
                },
            },
        },
    }
    return yaml.safe_dump(patch, sort_keys=False).rstrip()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
