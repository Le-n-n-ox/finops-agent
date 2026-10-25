"""Zetaris returns everything as strings; these records are copied from the real check_zetaris_query output."""
from pathlib import Path

from app.integrations.zetaris_source import bundle_from_records

DATA = Path(__file__).resolve().parents[2] / "data"

RAW = {
    "deployments": [{"name": "payment-api", "replicas": "3", "cpu_request_millicores": "1000",
                     "cpu_limit_millicores": "2000", "namespace": "payments",
                     "memory_limit_mib": "6144", "memory_request_mib": "4096"}],
    "usage_history": [
        {"timestamp": "2026-10-10T09:00:00+03:00", "service": "checkout-service",
         "cpu_millicores": "484", "memory_mib": "1898"},
        {"timestamp": "not-a-date", "service": "checkout-service", "cpu_millicores": "1", "memory_mib": "1"},
        {"timestamp": "2026-10-10T10:00:00+03:00", "service": "checkout-service",
         "cpu_millicores": "-5", "memory_mib": "1"},
    ],
    "business_events": [{"services": "[\"checkout-service\"]", "name": "Major marketing campaign",
                         "expected_traffic": "high", "risk": "high", "start_at": "2026-10-14T08:00:00+03:00",
                         "notes": "Expected customer traffic spike", "end_at": "2026-10-14T22:00:00+03:00"}],
    "incident_history": [{"pattern": "memory spike after model refresh", "incident_id": "INC-2041",
                          "service": "recommendation-api", "occurred_at": "2026-08-21T14:10:00+03:00",
                          "summary": "OOMKilled"}],
}


def test_string_values_become_typed_models():
    b = bundle_from_records(RAW, DATA)
    assert b.services[0].replicas == 3 and b.services[0].memory_request_mib == 4096
    assert b.usage_rows[0].cpu_millicores == 484 and b.usage_rows[0].timestamp.utcoffset() is not None
    assert b.events[0].services == ["checkout-service"]
    assert b.incidents[0].incident_id == "INC-2041"
    assert b.policy.simulation_now is not None
    assert b.cost_model is not None
    assert b.cost_model.cpu_core_monthly_cost_usd == 25.0


def test_bad_rows_are_reported_not_dropped_silently():
    b = bundle_from_records(RAW, DATA)
    assert len(b.usage_rows) == 1
    assert [i.code for i in b.issues] == ["BAD_ROW", "BAD_ROW"] and all(i.source == "usage_history" for i in b.issues)


def test_guide_incident_column_names_are_normalized():
    raw = {**RAW, "incident_history": [{"incident_id": "INC-9", "timestamp": "2026-10-12T00:00:00Z",
                                        "workload": "checkout-service", "namespace": "commerce",
                                        "incident_type": "latency", "severity": "medium",
                                        "description": "Latency increased"}]}
    bundle = bundle_from_records(raw, DATA)
    incident = bundle.incidents[0]
    assert incident.service == "checkout-service"
    assert incident.incident_type == "latency" and incident.severity == "medium"
