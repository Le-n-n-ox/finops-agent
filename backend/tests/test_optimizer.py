"""Developer 1 specs for build_proposals(). Pass an explicit `now`; never use the wall clock."""
from datetime import datetime
from pathlib import Path

from app.services.data_loader import load_inputs
from app.services.optimizer_service import build_proposals

DATA = Path(__file__).resolve().parents[2] / "data"
NOW = datetime.fromisoformat("2026-09-30T23:05:00+00:00")


def _by_id():
    return {p.workload_id: p for p in build_proposals(load_inputs(DATA), now=NOW)}


def test_one_proposal_per_service():
    assert set(_by_id()) == {service.name for service in load_inputs(DATA).services}
    assert len(_by_id()) == 10


def test_recent_service_has_recommendation_metrics():
    p = _by_id()["payment-api"]
    assert p.status == "no_change"
    assert not p.data_quality.is_stale
    assert p.current.cpu_request_millicores is not None
    assert p.metrics.cpu_p95 is not None and p.metrics.sample_count > 700
    assert p.reasons


def test_mock_imputed_measurements_provide_complete_usage_coverage():
    p = _by_id()["email-worker"]
    assert p.status == "proposed" and p.proposed is not None
    assert p.data_quality.usable_for_recommendation
    assert not any("missing cpu_millicores" in warning for warning in p.data_quality.warnings)


def test_never_below_p99_floor_and_limits_untouched():
    for p in _by_id().values():
        if p.proposed is not None:
            assert p.metrics.cpu_p99 is not None and p.metrics.memory_p99 is not None
            assert p.proposed.cpu_request_millicores is not None
            assert p.proposed.memory_request_mib is not None
            assert p.proposed.cpu_request_millicores >= p.metrics.cpu_p99
            assert p.proposed.memory_request_mib >= p.metrics.memory_p99
            assert p.proposed.cpu_limit_millicores in (None, p.current.cpu_limit_millicores)
