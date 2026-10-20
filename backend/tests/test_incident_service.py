from datetime import datetime, timedelta, timezone

from app.models.schemas import IncidentRecord
from app.services.incident_service import find_relevant_incidents, incident_quality_warning, load_incident_history


def test_loads_canonical_and_guide_incident_columns(tmp_path):
    path = tmp_path / "incidents.csv"
    path.write_text("incident_id,timestamp,workload,namespace,incident_type,severity,description\n"
                    "INC-1,2026-10-01T10:00:00Z,svc,apps,OOM,high,Memory exhaustion\n")
    incidents = load_incident_history(path)
    assert incidents[0].service == "svc"
    assert incidents[0].pattern == "OOM"
    assert incidents[0].severity == "high"


def test_matches_direct_then_indirect_and_respects_time_window():
    now = datetime(2026, 10, 10, tzinfo=timezone.utc)
    incidents = [
        IncidentRecord(incident_id="old", service="svc", occurred_at=now - timedelta(days=10),
                      pattern="old", namespace="apps"),
        IncidentRecord(incident_id="near-other-ns", service="svc", occurred_at=now - timedelta(days=1),
                      pattern="indirect", namespace="other"),
        IncidentRecord(incident_id="near", service="svc", occurred_at=now - timedelta(hours=1),
                      pattern="direct", namespace="apps", incident_type="OOM", severity="high"),
    ]
    matched = find_relevant_incidents("svc", incidents, start=now - timedelta(days=2), end=now,
                                      namespace="apps")
    assert [item.incident_id for item in matched] == ["near", "near-other-ns"]
    assert [item.match_type for item in matched] == ["direct", "indirect"]
    assert matched[0].incident_type == "OOM"


def test_no_incident_evidence_is_empty_and_quality_warning_is_explicit():
    assert find_relevant_incidents("svc", []) == []
    assert incident_quality_warning([], "svc")
    assert incident_quality_warning([IncidentRecord(incident_id="i", service="other",
                                                    occurred_at=datetime.now(timezone.utc), pattern="x")], "svc")
