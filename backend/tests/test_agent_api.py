"""API-level tests for the agent mode and the reviewer feedback loop."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.review import ReviewAction
from app.services.store import Store


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FINOPS_DB_PATH", str(tmp_path / "history.sqlite3"))
    import app.api.deps as deps
    deps._services = None
    with TestClient(app) as test_client:
        yield test_client
    deps._services = None


class TestAgentMode:
    def test_agent_mode_returns_the_review_cycle_analysis(self, client):
        res = client.post("/api/analyze", json={"mode": "agent"})
        assert res.status_code == 200
        body = res.json()
        assert body["mode"] == "agent"
        assert body["summary"]["workloads_evaluated"] > 0

    def test_agent_results_carry_confidence_and_evidence(self, client):
        body = client.post("/api/analyze", json={"mode": "agent"}).json()
        for result in body["results"]:
            assert "confidence_score" in result
            assert "evidence_trail" in result
            assert "objections" in result
            assert result["evidence_trail"], "the agent must record the tools it called"

    def test_agent_and_pipeline_agree_on_decisions(self, client):
        agent = client.post("/api/analyze", json={"mode": "agent"}).json()
        pipeline = client.post("/api/analyze", json={"mode": "pipeline"}).json()
        agent_decisions = {r["workload_id"]: r["decision"] for r in agent["results"]}
        pipeline_decisions = {r["workload_id"]: r["decision"] for r in pipeline["results"]}
        assert agent_decisions == pipeline_decisions, \
            "the adversarial phase may add objections but must not change any decision"

    def test_pipeline_mode_still_works(self, client):
        res = client.post("/api/analyze", json={"mode": "pipeline"})
        assert res.status_code == 200
        assert res.json()["summary"]["workloads_evaluated"] > 0

    def test_confidence_differs_between_safe_and_risky_workloads(self, client):
        body = client.post("/api/analyze", json={"mode": "agent"}).json()
        scores = {r["workload_id"]: r["confidence_score"] for r in body["results"]}
        assert len(set(scores.values())) > 1, "confidence must discriminate between workloads"

    def test_markdown_report_includes_the_confidence_score(self, client):
        client.post("/api/analyze", json={"mode": "agent"})
        res = client.get("/api/report?format=markdown")
        assert res.status_code == 200
        assert "Agent confidence" in res.text


class TestReviewLoop:
    def test_rejection_is_recorded_with_structured_reasons(self, client):
        body = client.post("/api/analyze", json={"mode": "agent"}).json()
        report_id = body["analysis_id"]
        res = client.post(f"/api/reports/{report_id}/review", json={
            "workload_id": "payment-api",
            "action": "REJECTED",
            "comment": "No memory cuts",
            "reviewer": "alice",
            "rejection_reasons": ["memory reduction caused an OOMKill"],
            "resource": "memory",
            "reviewer_guidance": "keep memory, cpu is fine",
        })
        assert res.status_code == 201
        record = res.json()
        assert record["rejection_reasons"] == ["memory reduction caused an OOMKill"]
        assert record["resource"] == "memory"
        assert record["reviewer_guidance"] == "keep memory, cpu is fine"

    def test_rejection_is_replayed_to_the_next_agent_run(self, client, tmp_path):
        body = client.post("/api/analyze", json={"mode": "agent"}).json()
        report_id = body["analysis_id"]
        client.post(f"/api/reports/{report_id}/review", json={
            "workload_id": "payment-api",
            "action": "REJECTED",
            "rejection_reasons": ["memory reduction caused an OOMKill"],
            "resource": "memory",
        })
        # The next agent run must carry the lesson into its reasoning.
        from app.services.orchestrator import default_inputs
        from app.services.agent_orchestrator import AgentOrchestrator
        from app.services.simulated_llm import SimulatedLLMClient
        from app.services.store import Store
        import os

        store = Store(os.environ["FINOPS_DB_PATH"])
        orchestrator = AgentOrchestrator(default_inputs(), SimulatedLLMClient(), store=store)
        _, audit = __import__("asyncio").run(orchestrator.analyze_workload_agentic("payment-api"))
        assert audit.historical_lessons
        assert any("OOMKill" in lesson for lesson in audit.historical_lessons)

    def test_audit_trail_is_retrievable(self, client):
        body = client.post("/api/analyze", json={"mode": "agent"}).json()
        report_id = body["analysis_id"]
        client.post(f"/api/reports/{report_id}/review", json={
            "workload_id": "payment-api", "action": "REJECTED", "comment": "no",
        })
        detail = client.get(f"/api/reports/{report_id}").json()
        trail = [record for decision in detail["decisions"] for record in decision["audit"]]
        assert trail
        assert trail[0]["action"] == "REJECTED"

    def test_review_for_an_unknown_workload_is_a_404(self, client):
        body = client.post("/api/analyze", json={"mode": "agent"}).json()
        res = client.post(f"/api/reports/{body['analysis_id']}/review", json={
            "workload_id": "not-a-workload", "action": "REJECTED",
        })
        assert res.status_code == 404

    def test_accepting_a_non_approved_decision_is_refused(self, client):
        body = client.post("/api/analyze", json={"mode": "agent"}).json()
        deferred = next(r for r in body["results"] if r["decision"] != "approved")
        res = client.post(f"/api/reports/{body['analysis_id']}/review", json={
            "workload_id": deferred["workload_id"], "action": "ACCEPTED_FOR_IMPLEMENTATION",
        })
        assert res.status_code in (400, 422)
