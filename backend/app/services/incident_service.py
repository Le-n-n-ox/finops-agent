"""Incident-history loading and deterministic workload evidence matching."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from app.models.schemas import IncidentEvidence, IncidentRecord


def load_incident_history(path: Path) -> list[IncidentRecord]:
    """Load canonical or guide-format incident CSV fields; invalid rows fail clearly."""
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        headers = set(reader.fieldnames or [])
        has_service = "service" in headers or "workload" in headers
        has_timestamp = "occurred_at" in headers or "timestamp" in headers
        if not {"incident_id"}.issubset(headers) or not has_service or not has_timestamp:
            absent = [key for key, okay in (("incident_id", "incident_id" in headers),
                                             ("service/workload", has_service),
                                             ("occurred_at/timestamp", has_timestamp)) if not okay]
            raise ValueError(f"Missing incident CSV columns: {', '.join(absent)}")
        incidents: list[IncidentRecord] = []
        for line, raw in enumerate(reader, start=2):
            row = {str(key).strip(): value.strip() if isinstance(value, str) else value
                   for key, value in raw.items() if key is not None}
            normalized = normalize_incident_row(row)
            try:
                incidents.append(IncidentRecord(**normalized))
            except ValidationError as exc:
                raise ValueError(f"Invalid incident row {line}: {exc.errors()[0]['msg']}") from exc
        return incidents


def normalize_incident_row(row: dict[str, str | None]) -> dict[str, str | None]:
    """Map current and guide CSV fields to the shared IncidentRecord contract."""
    pattern = row.get("pattern") or row.get("incident_type") or "unspecified"
    return {
        "incident_id": row.get("incident_id"),
        "service": row.get("service") or row.get("workload"),
        "occurred_at": row.get("occurred_at") or row.get("timestamp"),
        "pattern": pattern,
        "summary": row.get("summary") or row.get("description") or "",
        "namespace": row.get("namespace") or None,
        "incident_type": row.get("incident_type") or pattern,
        "severity": row.get("severity") or "unknown",
    }


def find_relevant_incidents(
    workload_id: str,
    incidents: list[IncidentRecord],
    start: datetime | None = None,
    end: datetime | None = None,
    namespace: str | None = None,
) -> list[IncidentEvidence]:
    """Return same-workload matches; exact namespace is direct, unknown namespace indirect."""
    matches: list[tuple[int, IncidentRecord]] = []
    for incident in incidents:
        if incident.service != workload_id:
            continue
        occurred = _utc(incident.occurred_at)
        if start is not None and occurred < _utc(start):
            continue
        if end is not None and occurred > _utc(end):
            continue
        exact_namespace = namespace is not None and incident.namespace == namespace
        matches.append((0 if exact_namespace else 1, incident))

    matches.sort(key=lambda item: (item[0], _utc(item[1].occurred_at), item[1].incident_id))
    return [
        IncidentEvidence(
            incident_id=incident.incident_id,
            timestamp=incident.occurred_at,
            incident_type=incident.incident_type or incident.pattern,
            severity=incident.severity or "unknown",
            description=incident.summary or incident.pattern,
            match_type="direct" if match_rank == 0 else "indirect",
            relevance_reason=("Same workload and namespace." if match_rank == 0 else
                              "Same workload; namespace is missing or does not exactly match."),
        )
        for match_rank, incident in matches
    ]


def incident_quality_warning(incidents: list[IncidentRecord], workload_id: str) -> str | None:
    if not incidents:
        return "Incident history is empty; no incident evidence is available."
    if not any(incident.service == workload_id for incident in incidents):
        return f"No incident history matches workload '{workload_id}'."
    return None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
