"""Optimizer unit tests on small synthetic data (no files, fixed clock)."""
from datetime import datetime, timedelta, timezone

from app.models.schemas import CostModel, InputBundle, OptimizerPolicy, Policy, UsageRow, WorkloadSpec
from app.services.optimizer_service import analyze_workload, build_proposals, percentile, round_up

TZ = timezone(timedelta(hours=3))
START = datetime(2026, 10, 10, 0, 0, tzinfo=TZ)
NOW = START + timedelta(hours=72)


def workload(name="svc", cpu=1000, mem=4096, replicas=2):
    return WorkloadSpec(name=name, namespace="ns", replicas=replicas, cpu_request_millicores=cpu,
                        cpu_limit_millicores=cpu * 2, memory_request_mib=mem, memory_limit_mib=mem * 2)


def rows(name="svc", n=48, cpu=200.0, mem=800.0, start=START):
    return [UsageRow(timestamp=start + timedelta(hours=i), service=name, cpu_millicores=cpu, memory_mib=mem)
            for i in range(n)]


COST = CostModel(cpu_core_monthly_cost_usd=25.0, memory_gib_monthly_cost_usd=4.0)


def test_percentile_matches_known_values():
    assert percentile([1, 2, 3, 4, 5], 50) == 3
    assert percentile([10], 99) == 10
    assert percentile(list(range(101)), 95) == 95


def test_round_up_never_rounds_down():
    assert round_up(521, 10) == 530 and round_up(530, 10) == 530 and round_up(2049, 64) == 2112


def test_stable_over_provisioned_workload_is_proposed():
    p = analyze_workload(workload(), rows(), now=NOW, cost_model=COST)
    assert p.status == "proposed"
    assert p.proposed is not None
    assert p.proposed.cpu_request_millicores is not None
    assert p.proposed.memory_request_mib is not None
    assert p.proposed.cpu_request_millicores == 250      # 200 * 1.25 = 250
    assert p.proposed.memory_request_mib == 1088         # 800 * 1.30 = 1040 -> 1088 (next 64)
    assert p.metrics.sample_count == 48 and p.metrics.last_observed_at is not None
    assert p.reasons and p.estimated_monthly_saving_usd > 0


def test_limits_are_never_changed():
    p = analyze_workload(workload(), rows(), now=NOW)
    assert p.proposed is not None
    assert p.proposed.cpu_limit_millicores is None and p.proposed.memory_limit_mib is None
    assert p.current.cpu_limit_millicores == 2000 and p.current.memory_limit_mib == 8192


def test_too_few_samples_is_insufficient_data():
    p = analyze_workload(workload(), rows(n=10), now=NOW)
    assert p.status == "insufficient_data" and p.proposed is None and "10 observations" in p.reasons[0]


def test_short_span_is_insufficient_data():
    dense = [UsageRow(timestamp=START + timedelta(minutes=10 * i), service="svc", cpu_millicores=200, memory_mib=800)
             for i in range(30)]                                  # 30 samples but only ~5h
    p = analyze_workload(workload(), dense, now=START + timedelta(hours=6))
    assert p.status == "insufficient_data" and any("spans" in r for r in p.reasons)


def test_stale_metrics_are_insufficient_data():
    p = analyze_workload(workload(), rows(), now=NOW + timedelta(days=10))
    assert p.status == "insufficient_data" and any("old" in r for r in p.reasons)


def test_no_rows_is_insufficient_data():
    assert analyze_workload(workload(), [], now=NOW).status == "insufficient_data"


def test_peak_near_request_blocks_reduction_and_respects_p99_floor():
    spiky = [UsageRow(timestamp=START + timedelta(hours=i), service="svc",
                      cpu_millicores=900.0 if i % 10 == 0 else 100.0, memory_mib=800.0) for i in range(60)]
    p = analyze_workload(workload(cpu=1000), spiky, now=START + timedelta(hours=61))
    assert p.metrics.cpu_p99 is not None
    assert p.metrics.cpu_p99 >= 900
    assert p.proposed is None or p.proposed.cpu_request_millicores == 1000    # CPU request not reduced
    if p.proposed:
        assert p.proposed.cpu_request_millicores is not None
        assert p.metrics.cpu_p99 is not None
        assert p.proposed.cpu_request_millicores >= p.metrics.cpu_p99


def test_usage_above_request_warns_and_never_raises_request():
    p = analyze_workload(workload(cpu=100, mem=500), rows(cpu=300, mem=900), now=NOW)
    assert p.status == "no_action" and p.warnings and p.proposed is None


def test_exactly_15_percent_below_is_proposed():
    # request 1000 -> candidate must be <= 850; usage 680 * 1.25 = 850 exactly
    p = analyze_workload(workload(cpu=1000, mem=100000), rows(cpu=680, mem=800), now=NOW)
    assert p.status == "proposed"
    assert p.proposed is not None
    assert p.proposed.cpu_request_millicores == 850


def test_small_reduction_is_no_action():
    p = analyze_workload(workload(cpu=1000, mem=1100), rows(cpu=700, mem=800), now=NOW)  # 875 / 1040 > 85% of request
    assert p.status == "no_action" and "less than 15%" in " ".join(p.reasons)


def test_without_cost_model_saving_is_zero():
    assert analyze_workload(workload(), rows(), now=NOW, cost_model=None).estimated_monthly_saving_usd == 0.0


def test_build_proposals_one_per_workload_and_unknown_rows_not_assigned():
    bundle = InputBundle(
        services=[workload("a"), workload("b")],
        usage_rows=rows("a") + rows("ghost"),
        events=[], cost_model=COST, policy=Policy(simulation_now=NOW),
    )
    out = build_proposals(bundle)
    assert [p.workload_id for p in out] == ["a", "b"]
    assert out[0].status == "proposed" and out[1].status == "insufficient_data"


def test_results_are_deterministic():
    bundle = InputBundle(services=[workload()], usage_rows=rows(), events=[], cost_model=COST,
                         policy=Policy(simulation_now=NOW))
    assert build_proposals(bundle) == build_proposals(bundle)


def test_custom_policy_changes_the_result():
    strict = OptimizerPolicy(cpu_p95_multiplier=4.0)         # 200 * 4 = 800 -> only 20% below 1000, still reduces
    p = analyze_workload(workload(cpu=1000, mem=100000), rows(), strict, now=NOW)
    assert p.proposed is not None
    assert p.proposed.cpu_request_millicores is not None
    assert p.proposed.cpu_request_millicores == 800
