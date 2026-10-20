"""
Developer 1 — data loading + validation.

Rules: parsing lives ONLY here (no YAML/CSV parsing in the API or UI).
Never fill missing resource values with 0, never silently drop unknown services.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from app.integrations.zetaris_client import ZetarisClient
from app.services.incident_service import normalize_incident_row
from app.models.schemas import (
    BusinessEvent,
    CostModel,
    DataQualityResult,
    IncidentRecord,
    InputBundle,
    Policy,
    UsageRow,
    ValidationIssue,
    WorkloadSpec,
)

DATA_FILES = {
    "deployments": "deployments.yaml",
    "usage": "usage_history.csv",
    "events": "business_events.json",
    "incidents": "incident_history.csv",
    "cost_model": "cost_model.json",
    "policy": "policy.yaml",
}

M = TypeVar("M", bound=BaseModel)
R = TypeVar("R")


def load_inputs(data_dir: str | Path = "data") -> InputBundle:
    """Load the local fixture files and return a validated InputBundle."""
    data_dir = _resolve_data_dir(data_dir)
    issues: list[ValidationIssue] = []

    def read_yaml(name: str) -> Any:
        return _read_file(data_dir / name, lambda path: yaml.safe_load(path.read_text(encoding="utf-8")))

    def read_json(name: str) -> Any:
        return _read_file(data_dir / name, lambda path: json.loads(path.read_text(encoding="utf-8")))

    def read_csv(name: str) -> list[dict[str, str]]:
        if name == DATA_FILES["incidents"]:
            if not (data_dir / name).is_file():
                issues.append(ValidationIssue(severity="warning", code="MISSING_INCIDENT_HISTORY",
                                              source=name,
                                              message="Incident history is unavailable; no incident evidence will be used."))
                return []
            return _read_file(data_dir / name, lambda path: _read_incident_csv(path, issues))
        required = ("timestamp", "service", "cpu_millicores", "memory_mib")
        return _read_file(data_dir / name, lambda path: _read_csv(path, required, issues))

    deployments_data = read_yaml(DATA_FILES["deployments"])
    deployments = deployments_data.get("services", []) if isinstance(deployments_data, dict) else deployments_data
    if not isinstance(deployments, list):
        raise ValueError(f"Malformed {DATA_FILES['deployments']}: expected a list of services")

    services = _parse_records(deployments, WorkloadSpec, DATA_FILES["deployments"], issues)
    usage = _parse_records(read_csv(DATA_FILES["usage"]), UsageRow, DATA_FILES["usage"], issues)
    events = _parse_records(read_json(DATA_FILES["events"]), BusinessEvent, DATA_FILES["events"], issues)
    incidents = _parse_records(read_csv(DATA_FILES["incidents"]), IncidentRecord, DATA_FILES["incidents"], issues)

    cost_path = data_dir / DATA_FILES["cost_model"]
    cost_model: CostModel | None = None
    if cost_path.is_file():
        try:
            cost_model = CostModel(**read_json(DATA_FILES["cost_model"]))
            if (cost_model.cpu_core_monthly_cost_usd is None
                    or cost_model.memory_gib_monthly_cost_usd is None):
                issues.append(ValidationIssue(
                    severity="warning", code="MISSING_PRICING_RATES", source=DATA_FILES["cost_model"],
                    message="Both CPU and memory rates are required for currency savings; relative allocation will be reported.",
                ))
        except (TypeError, ValidationError, ValueError) as exc:
            issues.append(ValidationIssue(severity="warning", code="INVALID_COST_MODEL",
                                          source=DATA_FILES["cost_model"],
                                          message=f"Pricing unavailable: {exc}"))
    else:
        issues.append(ValidationIssue(severity="warning", code="MISSING_COST_MODEL",
                                      source=DATA_FILES["cost_model"],
                                      message="Pricing file is missing; savings will be reported as relative allocation only."))

    try:
        policy_data = read_yaml(DATA_FILES["policy"])
        policy = Policy(**(policy_data or {}))
    except (TypeError, ValidationError) as exc:
        raise ValueError(f"Malformed policy configuration in {data_dir}: {exc}") from exc

    bundle = InputBundle(services=services, usage_rows=usage, events=events, incidents=incidents,
                         cost_model=cost_model, policy=policy, issues=issues)
    bundle.issues.extend(validate_inputs(bundle))
    return bundle


def load_project_data(data_dir: str | Path = "data") -> InputBundle:
    """Public guide-name alias for the repository's canonical project input loader."""
    return load_inputs(data_dir)


def validate_inputs(bundle: InputBundle) -> list[ValidationIssue]:
    """Return errors/warnings: unknown services, negative usage, duplicate (timestamp, service),
    bad timestamps, missing columns. Developer 2 shows these in the UI."""
    issues: list[ValidationIssue] = []
    services = {service.name for service in bundle.services}
    seen: set[tuple[Any, str]] = set()
    for row in bundle.usage_rows:
        workload_id = row.service.strip()
        if workload_id not in services:
            issues.append(ValidationIssue(severity="error", code="UNKNOWN_SERVICE", source=DATA_FILES["usage"],
                                         workload_id=workload_id,
                                         message=f"Usage row references unknown service '{workload_id}'."))
        if row.cpu_millicores < 0 or row.memory_mib < 0:
            issues.append(ValidationIssue(severity="error", code="NEGATIVE_USAGE", source=DATA_FILES["usage"],
                                         workload_id=workload_id, message="Usage values must not be negative."))
        key = (row.timestamp, workload_id)
        if key in seen:
            issues.append(ValidationIssue(severity="warning", code="DUPLICATE_USAGE", source=DATA_FILES["usage"],
                                         workload_id=workload_id,
                                         message=f"Duplicate usage row for {workload_id} at {row.timestamp.isoformat()}."))
        seen.add(key)
    return issues


def validate_usage_history(
    metrics: list[UsageRow],
    analysis_time: datetime,
    min_samples: int = 30,
    max_age_hours: float = 24,
    workload_id: str = "unknown",
    missing_fields: list[str] | None = None,
    errors: list[str] | None = None,
) -> DataQualityResult:
    """Assess one workload's sample coverage and freshness without inventing values."""
    ordered = sorted(metrics, key=lambda metric: metric.timestamp)
    last = ordered[-1].timestamp if ordered else None
    now = analysis_time
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    is_stale = last is None or (now - last).total_seconds() / 3600 > max_age_hours
    warnings: list[str] = []
    if len(ordered) < min_samples:
        warnings.append(f"Only {len(ordered)} samples; {min_samples} required.")
    if is_stale:
        warnings.append("No recent usage sample is available within the freshness limit.")
    problem_errors = list(errors or [])
    problem_missing = list(missing_fields or [])
    return DataQualityResult(
        workload_id=workload_id,
        usable_for_recommendation=(len(ordered) >= min_samples and not is_stale
                                   and not problem_errors and not problem_missing),
        sample_count=len(ordered),
        last_observed_at=last,
        is_stale=is_stale,
        missing_fields=problem_missing,
        errors=problem_errors,
        warnings=warnings,
    )


def load_inputs_from_zetaris(data_dir: str | Path = "data", client: ZetarisClient | None = None) -> InputBundle:
    """Same return type as load_inputs(), but data comes through Zetaris.
    Implement after the connection works (docs/ZETARIS_SETUP.md). Falls back to load_inputs()."""
    from app.integrations.zetaris_source import load_inputs_from_zetaris as _load

    return _load(_resolve_data_dir(data_dir), client)


def get_inputs(data_dir: str | Path = "data") -> InputBundle:
    """Entry point for the app. DATA_SOURCE=zetaris uses Zetaris, and falls back to local files
    (with a visible warning in bundle.issues) if Zetaris is unreachable. Default: local files."""
    import os

    if os.getenv("DATA_SOURCE", "local").lower() == "zetaris":
        try:
            return load_inputs_from_zetaris(data_dir)
        except Exception as e:  # noqa: BLE001 - deliberate: never crash the demo on a connector problem
            bundle = load_inputs(data_dir)
            bundle.issues.append(ValidationIssue(
                severity="warning", code="ZETARIS_FALLBACK", source="zetaris",
                message=f"Zetaris unavailable ({type(e).__name__}); using local files."))
            return bundle
    return load_inputs(data_dir)


def _read_file(path: Path, reader: Callable[[Path], R]) -> R:
    try:
        if not path.is_file():
            raise ValueError(f"Required input file is missing: {path.name}")
        return reader(path)
    except ValueError:
        raise
    except (OSError, json.JSONDecodeError, yaml.YAMLError, csv.Error) as exc:
        raise ValueError(f"Could not read {path.name}: {exc}") from exc


def _parse_records(records: Any, model: type[M], source: str,
                   issues: list[ValidationIssue]) -> list[M]:
    if not isinstance(records, list):
        raise ValueError(f"Malformed {source}: expected a list of records")
    parsed: list[M] = []
    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            issues.append(ValidationIssue(severity="error", code="BAD_ROW", source=source,
                                         message=f"Row {index}: expected an object, got {type(record).__name__}."))
            continue
        cleaned: dict[str, Any] = {str(key).strip(): value.strip() if isinstance(value, str) else value
                                   for key, value in record.items()}
        try:
            parsed.append(model(**cleaned))
        except ValidationError as exc:
            first = exc.errors()[0]
            issue_code = "NEGATIVE_USAGE" if first["type"] == "greater_than_equal" else (
                "BAD_TIMESTAMP" if str(first["loc"][0]) in {"timestamp", "occurred_at", "start_at", "end_at"}
                else "BAD_ROW"
            )
            issues.append(ValidationIssue(severity="error", code=issue_code, source=source,
                                         workload_id=str(cleaned.get("service") or cleaned.get("name") or "") or None,
                                         message=f"Row {index}: {first['loc']} {first['msg']}"))
    return parsed


def _read_csv(path: Path, required_columns: tuple[str, ...] = (),
              issues: list[ValidationIssue] | None = None) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        headers = {str(header).strip() for header in (reader.fieldnames or [])}
        missing = [column for column in required_columns if column not in headers]
        if missing and issues is not None:
            issues.append(ValidationIssue(
                severity="error", code="MISSING_COLUMNS", source=path.name,
                message=f"Missing required column(s): {', '.join(missing)}.",
            ))
        return list(reader)


def _read_incident_csv(path: Path, issues: list[ValidationIssue]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        headers = {str(header).strip() for header in (reader.fieldnames or [])}
        missing = []
        if "incident_id" not in headers:
            missing.append("incident_id")
        if not ({"service", "workload"} & headers):
            missing.append("service/workload")
        if not ({"occurred_at", "timestamp"} & headers):
            missing.append("occurred_at/timestamp")
        if missing:
            issues.append(ValidationIssue(severity="error", code="MISSING_COLUMNS", source=path.name,
                                          message=f"Missing required column(s): {', '.join(missing)}."))
        records = []
        for raw in reader:
            row = {str(key).strip(): value.strip() if isinstance(value, str) else value
                   for key, value in raw.items() if key is not None}
            records.append(normalize_incident_row(row))
        return records


def _resolve_data_dir(data_dir: str | Path) -> Path:
    """Resolve the default fixture path from either the repo root or backend/ cwd."""
    path = Path(data_dir)
    if not path.is_absolute() and not path.exists():
        repository_relative = Path(__file__).resolve().parents[3] / path
        if repository_relative.exists():
            return repository_relative
    return path
