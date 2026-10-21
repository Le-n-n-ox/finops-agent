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
        return _read_file(data_dir / name, lambda path: list(yaml.safe_load_all(path.read_text(encoding="utf-8"))))

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

    deployment_docs = read_yaml(DATA_FILES["deployments"])
    deployments = _deployment_records(deployment_docs)

    services = _parse_records(deployments, WorkloadSpec, DATA_FILES["deployments"], issues)
    usage = _parse_records(read_csv(DATA_FILES["usage"]), UsageRow, DATA_FILES["usage"], issues)
    events_data = read_json(DATA_FILES["events"])
    if isinstance(events_data, dict) and isinstance(events_data.get("events"), list):
        events_data = [_normalize_event(event) for event in events_data["events"]]
    events = _parse_records(events_data, BusinessEvent, DATA_FILES["events"], issues)
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
        if isinstance(policy_data, list) and len(policy_data) == 1:
            policy_data = policy_data[0]
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
    missing_metrics: dict[tuple[str, str], list[int]] = {}
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
            field = str(first["loc"][0])
            if first["type"] == "float_parsing" and not cleaned.get(field):
                workload_id = str(cleaned.get("service") or cleaned.get("name") or "unknown")
                missing_metrics.setdefault((workload_id, field), []).append(index)
                continue
            issue_code = "NEGATIVE_USAGE" if first["type"] == "greater_than_equal" else (
                "BAD_TIMESTAMP" if str(first["loc"][0]) in {"timestamp", "occurred_at", "start_at", "end_at"}
                else "BAD_ROW"
            )
            issues.append(ValidationIssue(severity="error", code=issue_code, source=source,
                                         workload_id=str(cleaned.get("service") or cleaned.get("name") or "") or None,
                                         message=f"Row {index}: {first['loc']} {first['msg']}"))
    missing_by_field: dict[str, dict[str, list[int]]] = {}
    for (workload_id, field), rows in missing_metrics.items():
        missing_by_field.setdefault(field, {})[workload_id] = rows
    for field, workloads in missing_by_field.items():
        row_count = sum(len(rows) for rows in workloads.values())
        breakdown = ", ".join(f"{name}: {len(rows)}" for name, rows in sorted(workloads.items()))
        issues.append(ValidationIssue(
            severity="warning", code="MISSING_METRIC", source=source, workload_id=None,
            message=(f"{row_count} usage row(s) across {len(workloads)} workload(s) have a missing "
                     f"{field} value and were excluded. By workload: {breakdown}."),
        ))
    return parsed


def _read_csv(path: Path, required_columns: tuple[str, ...] = (),
              issues: list[ValidationIssue] | None = None) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        headers = {str(header).strip() for header in (reader.fieldnames or [])}
        aliases = {
            "service": ("service", "workload"),
            "cpu_millicores": ("cpu_millicores", "cpu_usage_millicores"),
            "memory_mib": ("memory_mib", "memory_usage_mib"),
        }
        missing = [column for column in required_columns
                   if not any(name in headers for name in aliases.get(column, (column,)))]
        if missing and issues is not None:
            issues.append(ValidationIssue(
                severity="error", code="MISSING_COLUMNS", source=path.name,
                message=f"Missing required column(s): {', '.join(missing)}.",
            ))
        rows = list(reader)
        normalized: list[dict[str, str]] = []
        for row in rows:
            clean = {str(key).strip(): value.strip() if isinstance(value, str) else value
                     for key, value in row.items() if key is not None}
            for target, candidates in aliases.items():
                if target not in clean:
                    source = next((candidate for candidate in candidates if candidate in clean), None)
                    if source:
                        clean[target] = clean[source]
            normalized.append(clean)
        return normalized


def _deployment_records(documents: Any) -> list[dict[str, Any]]:
    """Accept the original services list or Kubernetes Deployment YAML documents."""
    if isinstance(documents, list) and len(documents) == 1 and isinstance(documents[0], dict):
        wrapped = documents[0].get("services")
        if isinstance(wrapped, list):
            return wrapped
    if not isinstance(documents, list):
        raise ValueError(f"Malformed {DATA_FILES['deployments']}: expected Kubernetes YAML documents")

    records: list[dict[str, Any]] = []
    for index, doc in enumerate(documents, start=1):
        if not isinstance(doc, dict):
            continue
        if doc.get("kind") == "List":
            nested = _deployment_records(doc.get("items", []))
            records.extend(nested)
            continue
        if doc.get("kind") != "Deployment":
            continue
        metadata = doc.get("metadata") or {}
        spec = doc.get("spec") or {}
        template = (spec.get("template") or {}).get("spec") or {}
        containers = template.get("containers") or []
        if not containers:
            raise ValueError(f"Malformed {DATA_FILES['deployments']}: Deployment {index} has no containers")
        requests = [c.get("resources", {}).get("requests", {}) for c in containers]
        limits = [c.get("resources", {}).get("limits", {}) for c in containers]
        cpu_request = _sum_kubernetes_quantity([r.get("cpu") for r in requests], "cpu")
        cpu_limit = _sum_kubernetes_quantity([r.get("cpu") for r in limits], "cpu")
        memory_request = _sum_kubernetes_quantity([r.get("memory") for r in requests], "memory")
        memory_limit = _sum_kubernetes_quantity([r.get("memory") for r in limits], "memory")
        records.append({
            "name": metadata.get("name", ""),
            "namespace": metadata.get("namespace", "default"),
            "replicas": spec.get("replicas", 1),
            "cpu_request_millicores": cpu_request,
            "cpu_limit_millicores": cpu_limit,
            "memory_request_mib": memory_request,
            "memory_limit_mib": memory_limit,
        })
    if not records:
        raise ValueError(f"Malformed {DATA_FILES['deployments']}: no Deployment records found")
    return records


def _sum_kubernetes_quantity(values: list[Any], kind: str) -> int:
    if any(value is None for value in values):
        raise ValueError(f"Kubernetes Deployment is missing a container {kind} resource")
    total = 0.0
    for value in values:
        text = str(value).strip()
        if kind == "cpu":
            total += float(text[:-1]) if text.endswith("m") else float(text) * 1000
        elif text.endswith("Ki"):
            total += float(text[:-2]) / 1024
        elif text.endswith("Mi"):
            total += float(text[:-2])
        elif text.endswith("Gi"):
            total += float(text[:-2]) * 1024
        elif text.endswith("Ti"):
            total += float(text[:-2]) * 1024 * 1024
        else:
            total += float(text) / (1024 * 1024)
    return int(round(total))


def _normalize_event(event: Any) -> Any:
    if not isinstance(event, dict):
        return event
    multiplier = event.get("expected_load_multiplier", 1)
    return {
        "name": event.get("name", ""),
        "start_at": event.get("start_at", event.get("start")),
        "end_at": event.get("end_at", event.get("end")),
        "services": event.get("services", event.get("affected_workloads", [])),
        "expected_traffic": event.get("expected_traffic", "high" if multiplier >= 1.5 else "normal"),
        "risk": event.get("risk", event.get("severity", "low")),
        "notes": event.get("notes", ""),
    }


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
