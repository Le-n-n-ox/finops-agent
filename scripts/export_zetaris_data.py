"""Build CSV files ready to register as the FinOps tables in Zetaris.

Run from the repository root with: python scripts/export_zetaris_data.py
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = DATA / "zetaris_upload"


def write_csv(name: str, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with (OUTPUT / name).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)

    workloads_raw = json.loads((DATA / "workloads.json").read_text(encoding="utf-8"))
    # The fixture is a Zetaris-shaped response ({"value": [...], "Count": n}), not a bare list:
    # it is what the connector's query returns. Accept either so the export survives both.
    workloads = workloads_raw.get("value", workloads_raw) if isinstance(workloads_raw, dict) else workloads_raw
    deployment_fields = [
        "name", "namespace", "replicas", "cpu_request_millicores", "cpu_limit_millicores",
        "memory_request_mib", "memory_limit_mib", "criticality", "protected",
    ]
    write_csv("deployments.csv", deployment_fields, workloads)

    with (DATA / "usage_history.csv").open(encoding="utf-8-sig", newline="") as stream:
        raw_usage = list(csv.DictReader(stream))
    usage_rows = [{
        "timestamp": row["timestamp"],
        "service": row["workload"],
        "namespace": row["namespace"],
        "cpu_millicores": row["cpu_usage_millicores"],
        "memory_mib": row["memory_usage_mib"],
        "data_quality_flag": row.get("data_quality_flag", ""),
    } for row in raw_usage]
    write_csv("usage_history.csv", [
        "timestamp", "service", "namespace", "cpu_millicores", "memory_mib", "data_quality_flag",
    ], usage_rows)

    events_data = json.loads((DATA / "business_events.json").read_text(encoding="utf-8"))
    event_rows = []
    for event in events_data.get("events", []):
        multiplier = float(event.get("expected_load_multiplier", 1))
        event_rows.append({
            "event_id": event.get("event_id", ""),
            "name": event.get("name", ""),
            "start_at": event.get("start_at", event.get("start", "")),
            "end_at": event.get("end_at", event.get("end", "")),
            # Keep list values free of commas and nested CSV quoting. Zetaris' file
            # source parser splits these JSON arrays across columns in practice.
            "services": "|".join(event.get("services", event.get("affected_workloads", []))),
            "expected_traffic": event.get("expected_traffic", "high" if multiplier >= 1.5 else "normal"),
            "risk": event.get("risk", event.get("severity", "low")),
            "notes": event.get("notes", ""),
            "freeze_optimization": event.get("freeze_optimization", False),
            "expected_load_multiplier": multiplier,
        })
    write_csv("business_events.csv", [
        "event_id", "name", "start_at", "end_at", "services", "expected_traffic", "risk", "notes",
        "freeze_optimization", "expected_load_multiplier",
    ], event_rows)

    with (DATA / "incident_history.csv").open(encoding="utf-8-sig", newline="") as stream:
        raw_incidents = list(csv.DictReader(stream))
    incident_rows = [{
        "incident_id": row.get("incident_id", ""),
        "service": row.get("service", row.get("workload", "")),
        "occurred_at": row.get("occurred_at", row.get("timestamp", "")),
        "pattern": row.get("pattern", row.get("incident_type", "unspecified")),
        "summary": row.get("summary", row.get("description", "")),
        "namespace": row.get("namespace", ""),
        "incident_type": row.get("incident_type", row.get("pattern", "")),
        "severity": row.get("severity", "unknown"),
    } for row in raw_incidents]
    write_csv("incident_history.csv", [
        "incident_id", "service", "occurred_at", "pattern", "summary", "namespace", "incident_type", "severity",
    ], incident_rows)

    # Keep the extra planning/config files alongside the tabular inputs for Zetaris file storage.
    for name in ("finops_policy.json", "test_scenarios.json"):
        source = DATA / name
        if source.is_file():
            (OUTPUT / name).write_bytes(source.read_bytes())

    print(f"Prepared Zetaris upload files in {OUTPUT.relative_to(ROOT)}")
    for name in ("deployments.csv", "usage_history.csv", "business_events.csv", "incident_history.csv"):
        with (OUTPUT / name).open(encoding="utf-8", newline="") as stream:
            count = sum(1 for _ in csv.DictReader(stream))
        print(f"  {name}: {count} rows")
    for name in ("finops_policy.json", "test_scenarios.json"):
        if (OUTPUT / name).is_file():
            print(f"  {name}: copied for reference (not queried by the current app connector)")


if __name__ == "__main__":
    main()
