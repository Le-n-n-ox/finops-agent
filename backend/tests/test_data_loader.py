"""Developer 1 specs for loading and validating the input fixtures."""
from pathlib import Path
import shutil
import csv

import pytest

from app.services.data_loader import load_inputs

DATA = Path(__file__).resolve().parents[2] / "data"


def test_valid_fixture_loads():
    b = load_inputs(DATA)
    assert len(b.services) == 12 and len(b.usage_rows) > 8500 and b.events and b.cost_model
    assert not any(issue.code == "MISSING_METRIC" for issue in b.issues)


def test_missing_file_gives_clear_error(tmp_path):
    with pytest.raises(ValueError, match="deployments"):
        load_inputs(tmp_path)


def test_unknown_service_is_flagged_not_dropped(tmp_path):
    target = tmp_path_copy(DATA, tmp_path)
    usage = target / "usage_history.csv"
    with usage.open(encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        fields = reader.fieldnames
        rows = list(reader)
    row = {field: "" for field in fields}
    row.update(timestamp="2026-10-13T09:00:00+03:00", workload="ghost-svc", namespace="ghost",
               cpu_usage_millicores="10", memory_usage_mib="20", data_quality_flag="ok")
    with usage.open("a", encoding="utf-8", newline="") as file:
        csv.DictWriter(file, fieldnames=fields).writerow(row)
    bundle = load_inputs(target)
    assert any(issue.code == "UNKNOWN_SERVICE" and issue.workload_id == "ghost-svc" for issue in bundle.issues)


def test_negative_usage_and_bad_timestamp_flagged(tmp_path):
    target = tmp_path_copy(DATA, tmp_path)
    usage = target / "usage_history.csv"
    text = usage.read_text()
    rows = list(csv.DictReader(text.splitlines()))
    rows[0]["timestamp"] = "not-a-time"
    negative = dict(rows[1])
    negative.update(timestamp="2026-10-13T09:00:00+03:00", workload="payment-api",
                    cpu_usage_millicores="-1", data_quality_flag="ok")
    rows.append(negative)
    with usage.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    bundle = load_inputs(target)
    codes = {issue.code for issue in bundle.issues}
    assert "NEGATIVE_USAGE" in codes
    assert "BAD_TIMESTAMP" in codes


def test_missing_incident_history_is_a_warning_not_a_pipeline_failure(tmp_path):
    target = tmp_path_copy(DATA, tmp_path)
    (target / "incident_history.csv").unlink()
    bundle = load_inputs(target)
    assert bundle.incidents == []
    assert any(issue.code == "MISSING_INCIDENT_HISTORY" for issue in bundle.issues)


def test_missing_pricing_keeps_relative_recommendation_mode(tmp_path):
    target = tmp_path_copy(DATA, tmp_path)
    (target / "cost_model.json").unlink()
    bundle = load_inputs(target)
    assert bundle.cost_model is None
    assert any(issue.code == "MISSING_COST_MODEL" for issue in bundle.issues)


def test_partial_pricing_is_reported_as_incomplete(tmp_path):
    target = tmp_path_copy(DATA, tmp_path)
    (target / "cost_model.json").write_text('{"cpu_core_monthly_cost_usd": 20}')
    bundle = load_inputs(target)
    assert bundle.cost_model is not None and bundle.cost_model.memory_gib_monthly_cost_usd is None
    assert any(issue.code == "MISSING_PRICING_RATES" for issue in bundle.issues)


def test_duplicate_usage_and_missing_columns_are_reported(tmp_path):
    target = tmp_path_copy(DATA, tmp_path)
    usage = target / "usage_history.csv"
    lines = usage.read_text().splitlines()
    lines.append(lines[1])
    usage.write_text("\n".join(lines) + "\n")
    bundle = load_inputs(target)
    assert any(issue.code == "DUPLICATE_USAGE" for issue in bundle.issues)

    lines[0] = "timestamp,service,cpu_millicores"
    usage.write_text("\n".join(lines) + "\n")
    bundle = load_inputs(target)
    assert any(issue.code == "MISSING_COLUMNS" and "memory_mib" in issue.message for issue in bundle.issues)


def tmp_path_copy(source: Path, destination: Path) -> Path:
    # Use a fresh fixture directory so each test can mutate an input independently.
    for item in source.iterdir():
        if item.is_file():
            shutil.copy2(item, destination / item.name)
    return destination
