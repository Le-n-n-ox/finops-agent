"""Developer 1 specs for build_proposals(). Pass an explicit `now`; never use the wall clock."""
from datetime import datetime
from pathlib import Path

from app.services.data_loader import load_inputs
from app.services.optimizer_service import build_proposals

DATA = Path(__file__).resolve().parents[2] / "data"
NOW = datetime.fromisoformat("2026-10-13T09:00:00+03:00")


def _by_id():
    return {p.workload_id: p for p in build_proposals(load_inputs(DATA), now=NOW)}


def test_one_proposal_per_service():
    assert set(_by_id()) == {"payment-api", "checkout-service", "email-worker", "session-store", "recommendation-api"}


def test_over_provisioned_service_is_proposed_with_metrics():
    p = _by_id()["payment-api"]
    assert p.status == "proposed"
    assert p.proposed is not None
    assert p.proposed.cpu_request_millicores is not None
    assert p.current.cpu_request_millicores is not None
    assert p.proposed.cpu_request_millicores < p.current.cpu_request_millicores
    assert p.metrics.cpu_p95 is not None and p.metrics.cpu_p99 is not None
    assert p.metrics.sample_count == 72 and p.reasons


def test_insufficient_history():
    p = _by_id()["email-worker"]
    assert p.status == "needs_review" and p.proposed is None


def test_never_below_p99_floor_and_limits_untouched():
    for p in _by_id().values():
        if p.proposed is not None:
            assert p.metrics.cpu_p99 is not None and p.metrics.memory_p99 is not None
            assert p.proposed.cpu_request_millicores is not None
            assert p.proposed.memory_request_mib is not None
            assert p.proposed.cpu_request_millicores >= p.metrics.cpu_p99
            assert p.proposed.memory_request_mib >= p.metrics.memory_p99
            assert p.proposed.cpu_limit_millicores in (None, p.current.cpu_limit_millicores)
