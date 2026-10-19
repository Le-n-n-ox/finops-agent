"""Contract tests — these must always pass; they guard the Dev1/Dev2 interface."""
import json
from pathlib import Path

import yaml

from app.models.schemas import AnalysisResponse, DecisionStatus, Policy, WorkloadSpec

DATA = Path(__file__).resolve().parents[2] / "data"


def test_sample_response_matches_contract():
    AnalysisResponse.model_validate(json.loads((DATA / "sample_analysis_response.json").read_text()))


def test_decision_statuses_are_the_agreed_five():
    assert {s.value for s in DecisionStatus} == {"approved", "deferred", "rejected", "needs_review", "no_change"}


def test_deployments_fixture_parses():
    services = yaml.safe_load((DATA / "deployments.yaml").read_text())["services"]
    specs = [WorkloadSpec(**s) for s in services]
    assert len(specs) == 5 and all(s.memory_request_mib > 0 for s in specs)


def test_policy_fixture_parses():
    Policy(**yaml.safe_load((DATA / "policy.yaml").read_text()))


def test_usage_fixture_has_expected_coverage():
    lines = (DATA / "usage_history.csv").read_text().strip().splitlines()[1:]
    counts: dict[str, int] = {}
    for ln in lines:
        svc = ln.split(",")[1]
        counts[svc] = counts.get(svc, 0) + 1
    assert counts["email-worker"] == 10  # insufficient-data scenario
    assert all(v == 72 for k, v in counts.items() if k != "email-worker")
