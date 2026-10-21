"""Developer 2 — load input -> build_proposals -> critic per proposal -> aggregate -> report.

Every agent step goes through app.integrations.meterless_runner.get_runner(), so Meterless can be swapped in
without touching business logic. The Dev 1 entry points are resolved lazily so this module imports cleanly
even while they are still being written.
"""
from __future__ import annotations

import os
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable

from app.integrations.meterless_runner import AgentRunner, get_runner
from app.models.schemas import (
    AnalysisResponse,
    AnalysisSummary,
    CriticPolicy,
    DecisionStatus,
    EventWindow,
    InputBundle,
    OptimizationProposal,
    UsagePoint,
    WorkloadResult,
    TopOpportunity,
)
from app.services.critic_service import evaluate
from app.services.fingerprints import fingerprint
from app.services.report_service import with_patch
from app.services.store import Store

DISCLAIMER = "Sample/illustrative data. Savings are estimates, not guaranteed bill reductions."


def default_inputs() -> InputBundle:
    from app.services import data_loader

    getter = getattr(data_loader, "get_inputs", None)  # Dev 1: DATA_SOURCE=local|zetaris
    return getter() if getter else data_loader.load_inputs()


def default_proposals(bundle: InputBundle, now: datetime | None = None) -> list[OptimizationProposal]:
    from app.services.optimizer_service import build_proposals

    return build_proposals(bundle, now=now)


def _chart_data(workload_id: str, bundle: InputBundle, now: datetime) -> dict:
    """Optional UI fields. Only included when the shared schema defines them."""
    extra: dict = {}
    if "usage_series" in WorkloadResult.model_fields:
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        cutoff = now - timedelta(days=bundle.policy.optimizer.window_days)
        rows = sorted((r for r in bundle.usage_rows if r.service == workload_id and cutoff <= r.timestamp <= now),
                      key=lambda r: r.timestamp)
        extra["usage_series"] = [UsagePoint(t=r.timestamp, cpu=r.cpu_millicores, mem=r.memory_mib) for r in rows]
    if "events" in WorkloadResult.model_fields:
        extra["events"] = [
            EventWindow(name=e.name, start_at=e.start_at, end_at=e.end_at, risk=e.risk)
            for e in bundle.events if workload_id in e.services
        ]
    return extra


def apply_policy(bundle: InputBundle, policy: CriticPolicy | None) -> InputBundle:
    """Use a saved safety-policy override (PUT /api/policies) instead of the one in policy.yaml."""
    return bundle if policy is None else bundle.model_copy(update={"policy": bundle.policy.model_copy(update={"critic": policy})})


def run_analysis_with_bundle(
    now: datetime | None = None,
    *,
    runner: AgentRunner | None = None,
    inputs_fn: Callable[[], InputBundle] | None = None,
    proposals_fn: Callable[..., list[OptimizationProposal]] | None = None,
    policy: CriticPolicy | None = None,
) -> tuple[AnalysisResponse, InputBundle]:
    runner = runner or get_runner()
    bundle: InputBundle = apply_policy(runner.run("collector", inputs_fn or default_inputs), policy)
    specs = {sp.name: sp for sp in bundle.services}
    now = now or bundle.policy.simulation_now or datetime.now(timezone.utc)

    proposals = runner.run("optimizer", proposals_fn or default_proposals, bundle, now=now)

    results: list[WorkloadResult] = []
    for proposal in proposals:
        judged = runner.run("critic", evaluate, proposal, bundle, now)
        patched = runner.run("report", with_patch, judged, specs.get(proposal.workload_id))
        extra = _chart_data(proposal.workload_id, bundle, now)
        results.append(patched.model_copy(update=extra) if extra else patched)

    results.sort(key=lambda result: -(result.proposal.priority_score or 0.0))
    top_n = bundle.policy.critic.top_n_findings
    top_opportunities = [TopOpportunity(
        workload_id=result.workload_id,
        monthly_savings_usd=result.monthly_savings_estimate_usd,
        priority_score=result.proposal.priority_score or 0.0,
        confidence_score=result.proposal.confidence.score if result.proposal.confidence else 0.0,
        risk_level=result.risk_level,
    ) for result in results if result.decision is DecisionStatus.APPROVED
        and result.proposal.proposed is not None][:top_n]

    summary = AnalysisSummary(
        workloads_evaluated=len(results),
        approved=sum(r.decision is DecisionStatus.APPROVED for r in results),
        deferred=sum(r.decision is DecisionStatus.DEFERRED for r in results),
        rejected=sum(r.decision is DecisionStatus.REJECTED for r in results),
        needs_review=sum(r.decision is DecisionStatus.NEEDS_REVIEW for r in results),
        no_change=sum(r.decision is DecisionStatus.NO_CHANGE for r in results),
        estimated_monthly_savings_usd=round(
            sum(r.monthly_savings_estimate_usd for r in results if r.decision is DecisionStatus.APPROVED), 2),
    )

    warnings = [DISCLAIMER]
    if bundle.policy.simulation_now:
        warnings.append(f"Demo clock fixed at {bundle.policy.simulation_now.isoformat()}.")

    payload: dict = dict(
        analysis_id=f"ANL-{now:%Y%m%d%H%M%S}-{uuid.uuid4().hex[:6]}",
        generated_at=now,
        mode="demo" if bundle.policy.simulation_now else os.getenv("DATA_SOURCE", "local"),
        summary=summary,
        results=results,
        warnings=warnings,
        policy_version=bundle.policy.critic.version,
        rule_version=bundle.policy.critic.rule_version,
        input_fingerprint="sha256:" + hashlib.sha256(bundle.model_dump_json().encode("utf-8")).hexdigest(),
        top_n_findings=top_n,
        top_opportunities=top_opportunities,
    )
    if "input_issues" in AnalysisResponse.model_fields:
        payload["input_issues"] = bundle.issues
    return AnalysisResponse(**payload), bundle


def run_analysis(now: datetime | None = None, **kwargs) -> AnalysisResponse:
    return run_analysis_with_bundle(now, **kwargs)[0]


def run_and_record(store: Store, now: datetime | None = None, **kwargs) -> AnalysisResponse:
    """Run the pipeline with the saved policy, then persist the report + immutable decision snapshots."""
    response, bundle = run_analysis_with_bundle(now, policy=store.get_policy(), **kwargs)
    store.save_report(response, {r.workload_id: fingerprint(r.workload_id, bundle) for r in response.results}, bundle.policy.critic.version)
    return response
