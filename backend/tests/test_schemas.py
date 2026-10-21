"""Contract tests — these must always pass; they guard the Dev1/Dev2 interface."""
import csv
import json
from pathlib import Path

import yaml

from app.models.schemas import AnalysisResponse, DecisionStatus, Policy
from app.services.data_loader import load_inputs

DATA = Path(__file__).resolve().parents[2] / "data"


def test_sample_response_matches_contract():
    AnalysisResponse.model_validate(json.loads((DATA / "sample_analysis_response.json").read_text()))


def test_decision_statuses_are_the_agreed_five():
    assert {s.value for s in DecisionStatus} == {"approved", "deferred", "rejected", "needs_review", "no_change"}


def test_deployments_fixture_parses():
    deployments = [doc for doc in yaml.safe_load_all((DATA / "deployments.yaml").read_text())
                   if isinstance(doc, dict) and doc.get("kind") == "Deployment"]
    bundle = load_inputs(DATA)
    assert len(deployments) == len(bundle.services) == 10
    assert all(spec.memory_request_mib > 0 for spec in bundle.services)


def test_policy_fixture_parses():
    Policy(**yaml.safe_load((DATA / "policy.yaml").read_text()))


def test_usage_fixture_has_expected_coverage():
    with (DATA / "usage_history.csv").open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["workload"]] = counts.get(row["workload"], 0) + 1
    assert len(counts) == 10
    assert all(v == 720 for v in counts.values())
    assert sum(row["data_quality_flag"] == "imputed_mock_cpu" for row in rows) == 16
