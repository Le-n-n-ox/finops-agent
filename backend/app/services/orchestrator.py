"""Run the data, optimizer, critic, and summary steps for one analysis."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.integrations.meterless_runner import get_runner
from app.models.schemas import (
    AnalysisResponse,
    AnalysisSummary,
    DecisionStatus,
    Policy,
    WorkloadResult,
)
from app.services.critic_service import evaluate_proposal
from app.services.data_loader import get_inputs
from app.services.optimizer_service import build_proposals
from app.services.validation_service import validation_from_bundle


def run_analysis(
    data_dir: str | Path = "data",
    policy_override: Policy | None = None,
    mode: str = "demo",
) -> AnalysisResponse:
    """Run the complete analysis pipeline and return its dashboard response."""
    runner = get_runner()

    bundle = runner.run("collector", get_inputs, data_dir)
    if policy_override is not None:
        bundle.policy = policy_override

    now = bundle.policy.simulation_now or datetime.now(timezone.utc)
    proposals = runner.run("optimizer", build_proposals, bundle, now=now)
    results: list[WorkloadResult] = [
        runner.run("critic", evaluate_proposal, proposal, bundle)
        for proposal in proposals
    ]

    summary = AnalysisSummary(
        workloads_evaluated=len(results),
        approved=sum(result.decision == DecisionStatus.APPROVED for result in results),
        deferred=sum(result.decision == DecisionStatus.DEFERRED for result in results),
        rejected=sum(result.decision == DecisionStatus.REJECTED for result in results),
        needs_review=sum(result.decision == DecisionStatus.NEEDS_REVIEW for result in results),
        no_change=sum(result.decision == DecisionStatus.NO_CHANGE for result in results),
        estimated_monthly_savings_usd=round(
            sum(result.monthly_savings_estimate_usd for result in results
                if result.decision == DecisionStatus.APPROVED),
            2,
        ),
    )
    warnings = [issue.message for issue in bundle.issues if issue.severity == "warning"]
    validation = validation_from_bundle(bundle)
    return AnalysisResponse(
        analysis_id=f"analysis-{uuid.uuid4().hex[:8]}",
        generated_at=now,
        mode=mode,
        summary=summary,
        results=results,
        warnings=warnings,
        input_issues=validation.issues,
        data_health=validation,
    )
