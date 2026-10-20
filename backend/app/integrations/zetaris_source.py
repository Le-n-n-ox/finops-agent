"""
Zetaris -> InputBundle (Developer 1).

Observed with the real Zetaris REST API: every record is a dict and EVERY value is a string
("replicas": "3"), and list columns arrive JSON-encoded ("services": "[\"checkout-service\"]").
This module converts that into the shared Pydantic models. Bad rows become ValidationIssues;
they are never silently dropped.

cost_model.json and policy.yaml are small config files and stay local (not stored in Zetaris).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from app.integrations.zetaris_client import ZetarisClient
from app.services.incident_service import normalize_incident_row
from app.models.schemas import (
    BusinessEvent,
    CostModel,
    IncidentRecord,
    InputBundle,
    Policy,
    UsageRow,
    ValidationIssue,
    WorkloadSpec,
)

T = TypeVar("T", bound=BaseModel)


def _clean(record: dict[str, Any]) -> dict[str, Any]:
    """Trim strings; turn empty strings into None so optional fields work."""
    out: dict[str, Any] = {}
    for k, v in record.items():
        if isinstance(v, str):
            v = v.strip()
            if v == "":
                v = None
        out[str(k).strip()] = v
    return out


def _parse_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value]
    text = str(value).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(x).strip() for x in parsed]
    except json.JSONDecodeError:
        pass
    return [p.strip() for p in text.strip("[]").replace('"', "").split(",") if p.strip()]


def _build(
    model: type[T],
    record: Any,
    table: str,
    issues: list[ValidationIssue],
    fix: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> T | None:
    if not isinstance(record, dict):
        issues.append(ValidationIssue(severity="error", code="BAD_ROW", source=table,
                                      message=f"Expected an object, got {type(record).__name__}: {record!r}"[:200]))
        return None
    rec = _clean(record)
    if fix:
        rec = fix(rec)
    try:
        return model(**rec)
    except ValidationError as e:
        issues.append(ValidationIssue(severity="error", code="BAD_ROW", source=table,
                                      workload_id=str(rec.get("service") or rec.get("name") or ""),
                                      message=f"{e.error_count()} problem(s): {e.errors()[0]['loc']} {e.errors()[0]['msg']}"))
        return None


def _fix_event(rec: dict[str, Any]) -> dict[str, Any]:
    rec["services"] = _parse_list(rec.get("services"))
    return rec


def _fix_incident(rec: dict[str, Any]) -> dict[str, Any]:
    """Accept either the repository contract or Developer 1 guide column names."""
    return normalize_incident_row(rec)


def _collect(
    model: type[T],
    records: list[Any],
    table: str,
    issues: list[ValidationIssue],
    fix: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> list[T]:
    """Convert every record; keep the good ones, report the bad ones in `issues`."""
    result: list[T] = []
    for record in records:
        item = _build(model, record, table, issues, fix)
        if item is not None:
            result.append(item)
    return result


def bundle_from_records(raw: dict[str, list[Any]], data_dir: str | Path = "data") -> InputBundle:
    """Convert Zetaris tables ({table: [records]}) + local config into an InputBundle."""
    data_dir = Path(data_dir)
    issues: list[ValidationIssue] = []

    services = _collect(WorkloadSpec, raw.get("deployments", []), "deployments", issues)
    usage = _collect(UsageRow, raw.get("usage_history", []), "usage_history", issues)
    events = _collect(BusinessEvent, raw.get("business_events", []), "business_events", issues, _fix_event)
    incidents = _collect(IncidentRecord, raw.get("incident_history", []), "incident_history", issues, _fix_incident)

    cost_model = CostModel(**json.loads((data_dir / "cost_model.json").read_text()))
    policy = Policy(**yaml.safe_load((data_dir / "policy.yaml").read_text()))

    return InputBundle(services=services, usage_rows=usage, events=events, incidents=incidents,
                       cost_model=cost_model, policy=policy, issues=issues)


def load_inputs_from_zetaris(data_dir: str | Path = "data", client: ZetarisClient | None = None) -> InputBundle:
    client = client or ZetarisClient()
    return bundle_from_records(client.fetch_raw_tables(), data_dir)
