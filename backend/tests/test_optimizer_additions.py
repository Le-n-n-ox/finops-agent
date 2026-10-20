from datetime import datetime, timedelta, timezone

from app.models.schemas import (
    CostModel, DataQualityResult, OptimizationProposal, OptimizerPolicy, ProposalStatus,
    ResourceSettings, UsageMetrics, UsageRow, UsageSummary, ValidationIssue, WorkloadSpec,
)
from app.services.confidence_service import calculate_recommendation_confidence
from app.services.optimizer_service import (
    analyze_workload, estimate_monthly_savings, rank_recommendations, recommend_resources,
)
from app.services.data_loader import validate_usage_history


NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)


def workload():
    return WorkloadSpec(name="svc", namespace="apps", replicas=3,
                        cpu_request_millicores=1000, cpu_limit_millicores=2000,
                        memory_request_mib=4096, memory_limit_mib=8192)


def usage(count=48, cpu=200, memory=800):
    start = NOW - timedelta(hours=count)
    return [UsageRow(timestamp=start + timedelta(hours=i), service="svc",
                     cpu_millicores=cpu, memory_mib=memory) for i in range(count)]


def test_stale_or_invalid_usage_does_not_propose_and_confidence_is_capped():
    stale = analyze_workload(workload(), usage(), OptimizerPolicy(), now=NOW + timedelta(days=8))
    assert stale.status == ProposalStatus.NEEDS_REVIEW and stale.proposed is None
    assert stale.confidence is not None and stale.confidence.score < 40

    invalid = analyze_workload(workload(), usage(), now=NOW,
                               data_issues=[ValidationIssue(severity="error", code="BAD_ROW", message="bad row",
                                                            workload_id="svc")])
    assert invalid.status == ProposalStatus.NEEDS_REVIEW and invalid.proposed is None
    assert invalid.data_quality is not None and not invalid.data_quality.usable_for_recommendation


def test_confidence_has_explainable_weighted_factors():
    quality = DataQualityResult(workload_id="svc", usable_for_recommendation=True, sample_count=50,
                                last_observed_at=NOW, is_stale=False)
    summary = UsageSummary(workload_id="svc", sample_count=50)
    confidence = calculate_recommendation_confidence(quality, summary, [], NOW, min_samples=30,
                                                      cpu_values=[200] * 50, memory_values=[800] * 50)
    assert 0 <= confidence.score <= 100
    assert {factor.name for factor in confidence.factors} == {
        "validity", "sample_sufficiency", "freshness", "stability", "anomalies"
    }
    assert sum(factor.weight for factor in confidence.factors) == 1


def test_usage_quality_reports_sample_count_freshness_and_missing_data():
    quality = validate_usage_history(usage(12), NOW, min_samples=30, max_age_hours=72, workload_id="svc")
    assert quality.sample_count == 12 and quality.last_observed_at is not None
    assert not quality.usable_for_recommendation and not quality.is_stale
    missing = validate_usage_history([], NOW, workload_id="svc", missing_fields=["cpu_millicores"])
    assert missing.is_stale and missing.missing_fields and missing.warnings


def test_savings_price_and_no_price_paths_scale_by_replica_count():
    current = ResourceSettings(cpu_request_millicores=1000, memory_request_mib=4096)
    proposed = ResourceSettings(cpu_request_millicores=500, memory_request_mib=2048)
    priced = estimate_monthly_savings(current, proposed,
                                      CostModel(cpu_core_monthly_cost_usd=20, memory_gib_monthly_cost_usd=4),
                                      replicas=3)
    assert priced.monthly_savings_usd == 54
    assert priced.pricing_available
    relative = estimate_monthly_savings(current, proposed, None, replicas=3)
    assert relative.monthly_savings_usd is None
    assert relative.total_request_reduction_pct == 50
    assert not relative.pricing_available
    half_month = estimate_monthly_savings(
        current, proposed, CostModel(cpu_core_monthly_cost_usd=20, memory_gib_monthly_cost_usd=4),
        replicas=3, days=15,
    )
    assert half_month.monthly_savings_usd == 27


def test_rank_recommendations_is_deterministic_and_optimizer_only():
    proposals = [
        OptimizationProposal(proposal_id="a", workload_id="a", status=ProposalStatus.PROPOSED,
                             current=ResourceSettings(), proposed=ResourceSettings(), metrics=UsageMetrics(),
                             created_at=NOW, priority_score=20),
        OptimizationProposal(proposal_id="b", workload_id="b", status=ProposalStatus.NO_CHANGE,
                             current=ResourceSettings(), metrics=UsageMetrics(),
                             created_at=NOW, priority_score=80),
    ]
    ranked = rank_recommendations(proposals)
    assert [p.workload_id for p in ranked] == ["b", "a"]
    assert all(not hasattr(p, "decision") for p in ranked)


def test_proposal_keeps_limits_out_of_proposed_resource_object():
    proposal = analyze_workload(workload(), usage(), now=NOW,
                                cost_model=CostModel(cpu_core_monthly_cost_usd=25,
                                                     memory_gib_monthly_cost_usd=4))
    assert proposal.status == ProposalStatus.PROPOSED
    assert proposal.current.cpu_limit_millicores == 2000
    assert proposal.proposed is not None
    assert proposal.proposed.cpu_limit_millicores is None
    assert proposal.confidence and proposal.priority_score is not None
    assert proposal.metrics.p99_reliable is False  # 48 samples are below the default 100-sample P99 threshold.
    assert proposal.usage_summary and proposal.usage_summary.cpu_p99_m is None
    assert proposal.savings_estimate and proposal.savings_estimate.monthly_savings_usd is not None


def test_guide_name_recommendation_entry_point_returns_optimizer_status_only():
    result = recommend_resources(workload(), usage(), analysis_time=NOW)
    assert result.status == ProposalStatus.PROPOSED
    assert not hasattr(result, "decision")
