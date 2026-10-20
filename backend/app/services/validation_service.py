"""Data quality summary shared by the API validation endpoint and analysis response."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from app.models.schemas import InputBundle, ValidationIssue, ValidationResponse, WorkloadDataHealth
from app.services.data_loader import get_inputs


def validate_data(data_dir: str | Path = "data") -> ValidationResponse:
    bundle = get_inputs(data_dir)
    return validation_from_bundle(bundle)


def validation_from_bundle(bundle: InputBundle) -> ValidationResponse:
    now = bundle.policy.simulation_now or datetime.now(timezone.utc)
    by_service: dict[str, list] = {service.name: [] for service in bundle.services}
    for row in bundle.usage_rows:
        if row.service in by_service:
            by_service[row.service].append(row)

    issues = list(bundle.issues)
    workloads: list[WorkloadDataHealth] = []
    for service in bundle.services:
        rows = sorted(by_service[service.name], key=lambda row: row.timestamp)
        sample_count = len(rows)
        span_hours = (rows[-1].timestamp - rows[0].timestamp).total_seconds() / 3600 if sample_count > 1 else 0.0
        latest_age = (now - rows[-1].timestamp).total_seconds() / 3600 if rows else None
        missing = sample_count == 0
        sparse = sample_count < bundle.policy.optimizer.min_samples or span_hours < bundle.policy.optimizer.min_span_hours
        stale = latest_age is None or latest_age > bundle.policy.optimizer.max_metric_age_hours
        if missing:
            issues.append(ValidationIssue(severity="error", code="MISSING_METRICS", source="usage_history",
                                          workload_id=service.name, message="No usage observations found."))
        elif sparse:
            issues.append(ValidationIssue(severity="warning", code="SPARSE_METRICS", source="usage_history",
                                          workload_id=service.name,
                                          message=(f"{sample_count} samples over {span_hours:.1f} hours; need "
                                                   f"{bundle.policy.optimizer.min_samples} samples over "
                                                   f"{bundle.policy.optimizer.min_span_hours:.1f} hours.")))
        if stale and not missing:
            issues.append(ValidationIssue(severity="warning", code="STALE_METRICS", source="usage_history",
                                          workload_id=service.name,
                                          message=(f"Latest usage observation is {latest_age:.1f} hours old; "
                                                   f"maximum allowed is {bundle.policy.optimizer.max_metric_age_hours:.1f} hours.")))

        status = "error" if missing else "warning" if sparse or stale else "healthy"
        workloads.append(WorkloadDataHealth(
            workload_id=service.name,
            namespace=service.namespace,
            sample_count=sample_count,
            required_samples=bundle.policy.optimizer.min_samples,
            span_hours=round(span_hours, 2),
            required_span_hours=bundle.policy.optimizer.min_span_hours,
            latest_metric_age_hours=round(latest_age, 2) if latest_age is not None else None,
            max_metric_age_hours=bundle.policy.optimizer.max_metric_age_hours,
            missing_metrics=missing,
            sparse_metrics=sparse and not missing,
            stale_metrics=stale and not missing,
            status=status,
        ))

    source = "zetaris" if os.getenv("DATA_SOURCE", "local").lower() == "zetaris" else "local"
    if any(issue.code == "ZETARIS_FALLBACK" for issue in issues):
        source = "local_fallback"
    return ValidationResponse(
        generated_at=now,
        source=source,
        workloads_checked=len(workloads),
        error_count=sum(issue.severity == "error" for issue in issues),
        warning_count=sum(issue.severity == "warning" for issue in issues),
        workloads=workloads,
        issues=issues,
    )
