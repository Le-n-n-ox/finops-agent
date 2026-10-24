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

    def test_the_agent_never_changes_a_deterministic_decision(self, client):
        """The adversarial phase may downgrade an approval; it may never change anything else.

        This is the invariant the review cycle exists to protect. It used to be checked by
        comparing the API's two modes against each other - but `mode` no longer selects a
        reasoning path, so that comparison would have compared the agent with itself and
        proved nothing. The invariant is asserted against the deterministic pipeline itself,
        which is the safety model underneath the agent cycle.
        """
        from app.models.schemas import DecisionStatus
        from app.services.orchestrator import run_analysis_with_bundle

        agent = client.post("/api/analyze", json={"mode": "agent"}).json()
        pipeline, _bundle = run_analysis_with_bundle()

        agent_decisions = {r["workload_id"]: r["decision"] for r in agent["results"]}
        pipeline_decisions = {r.workload_id: r.decision.value for r in pipeline.results}

        assert set(agent_decisions) == set(pipeline_decisions), \
            "the agent must reach the same workloads as the deterministic pipeline"
        for workload_id, decision in agent_decisions.items():
            deterministic = pipeline_decisions[workload_id]
            if decision != deterministic:
                assert (deterministic == DecisionStatus.APPROVED.value
                        and decision == DecisionStatus.NEEDS_REVIEW.value), (
                    f"{workload_id}: the agent changed {deterministic} to {decision}. The only "
                    "change it may make is downgrading an approval to a human review.")

    def test_the_agent_never_raises_the_savings(self, client):
        """The adversarial phase may lower a saving; it may never invent one.

        A decision that stays the same but claims more money is still a broken decision, and the
        reviewer is the one who has to catch it.
        """
        from app.services.orchestrator import run_analysis_with_bundle

        agent = client.post("/api/analyze", json={"mode": "agent"}).json()
        pipeline, _bundle = run_analysis_with_bundle()

        agent_savings = {r["workload_id"]: r["monthly_savings_estimate_usd"] for r in agent["results"]}
        pipeline_savings = {r.workload_id: r.monthly_savings_estimate_usd for r in pipeline.results}

        for workload_id, savings in agent_savings.items():
            assert savings <= pipeline_savings[workload_id] + 0.01, \
                f"{workload_id}: the agent claimed more savings than the deterministic critic did"

    def test_the_mode_field_is_accepted_and_ignored(self, client):
        """`mode` is still accepted by older frontends, but it no longer selects a path.

        The agent cycle always runs. A frontend that still sends `mode: "pipeline"` must get the
        agent cycle's answer, not a second, different reasoning path.
        """
        legacy = client.post("/api/analyze", json={"mode": "pipeline"})
        assert legacy.status_code == 200
        body = legacy.json()
        assert body["mode"] == "agent", "the response always says which path actually ran"
        assert body["summary"]["workloads_evaluated"] > 0
        # The agent ran, so the agent's own fields are present even in "pipeline" mode.
        for result in body["results"]:
            assert result["cycles"], "the agent cycle ran, so its review cycle is reported"

    def test_confidence_differs_between_safe_and_risky_workloads(self, client):
        body = client.post("/api/analyze", json={"mode": "agent"}).json()
        scores = {r["workload_id"]: r["confidence_score"] for r in body["results"]}
        assert len(set(scores.values())) > 1, "confidence must discriminate between workloads"

    def test_markdown_report_includes_the_confidence_score(self, client):
        client.post("/api/analyze", json={"mode": "agent"})
        res = client.get("/api/report?format=markdown")
        assert res.status_code == 200
        assert "Agent confidence" in res.text

    def test_agent_results_carry_the_review_cycle(self, client):
        """The review phases must reach the reviewer, not just the audit log.

        A cycle the API computes and then discards is invisible reasoning, and invisible reasoning
        cannot be checked by the person who has to approve the change.
        """
        body = client.post("/api/analyze", json={"mode": "agent"}).json()
        for result in body["results"]:
            roles = [c["role"] for c in result["cycles"]]
            # The revision phase is optional: it runs only when a change is on the table and the
            # critic raised a blocking objection. The order around it is not optional.
            assert roles[:2] == ["proposer", "critic"], f"unexpected cycle order for {result['workload_id']}"
            assert roles[-1] == "judge", f"the judge must rule on every workload: {roles}"
            assert roles[2:-1] in ([], ["revision"]), f"unexpected middle phase for {result['workload_id']}: {roles}"
            for cycle in result["cycles"]:
                assert cycle["summary"], "every phase must say what it concluded"
            assert "historical_lessons" in result

    def test_agent_mode_carries_the_usage_chart(self, client):
        """The agent path must return the same usage series the pipeline does.

        The chart is a UI-only field. If the agent path skips it, the mode that showcases the new
        reasoning is also the mode where the evidence chart is blank.
        """
        from app.services.orchestrator import run_analysis_with_bundle

        agent = client.post("/api/analyze", json={"mode": "agent"}).json()
        pipeline, _bundle = run_analysis_with_bundle()

        agent_points = {r["workload_id"]: len(r.get("usage_series") or []) for r in agent["results"]}
        pipeline_points = {r.workload_id: len(r.usage_series or []) for r in pipeline.results}
        assert agent_points == pipeline_points
        assert any(count > 0 for count in agent_points.values()), "the agent path produced no chart data"


class TestSuppressedSavings:
    """The cost of the safety rules must be visible, not erased.

    When an event or an incident defers a reduction, the critic used to zero the optimizer's
    estimate. The reviewer then saw a workload worth $0.00 and could not tell "nothing to save"
    from "we found something and refused it".
    """

    def test_suppressed_savings_are_preserved(self, client):
        body = client.post("/api/analyze", json={"mode": "pipeline"}).json()
        suppressed = [r for r in body["results"] if r["proposal"]["suppressed_saving_usd"] > 0]
        assert suppressed, "the fixture must defer at least one reduction with a real saving"
        for r in suppressed:
            assert r["proposal"]["suppressed_proposal"] is not None, "the refused candidate must be kept"
            assert r["monthly_savings_estimate_usd"] == 0.0, "a deferred reduction is never counted"

    def test_dashboard_reports_the_money_held_back(self, client):
        client.post("/api/analyze", json={"mode": "pipeline"})
        summary = client.get("/api/dashboard/summary").json()
        assert summary["potential_savings_usd"] > summary["estimated_monthly_savings_usd"]
        assert summary["held_back_usd"] > 0, "the safety rules cost something; the report must say so"
        assert summary["held_back_usd"] == pytest.approx(
            summary["potential_savings_usd"] - summary["estimated_monthly_savings_usd"], abs=0.01)

    def test_the_deterministic_pipeline_reports_no_agent_confidence(self, client):
        """The deterministic pipeline runs no agent, so it reports no agent confidence.

        A default of 0.0 would be read as "the agent is certain of nothing" rather than
        "there was no agent", and would sit next to the proposal's real score of ~90.

        The API has one reasoning path now, so this is asserted against the pipeline function
        itself rather than against a `mode` the API ignores.
        """
        from app.services.orchestrator import run_analysis_with_bundle

        response, _bundle = run_analysis_with_bundle()
        for result in response.results:
            assert result.confidence_score is None
            assert result.proposal.confidence.score > 0, "the proposal still has its own score"

    def test_agent_mode_reports_agent_confidence(self, client):
        body = client.post("/api/analyze", json={"mode": "agent"}).json()
        for result in body["results"]:
            assert result["confidence_score"] is not None
            assert result["confidence_basis"]


class TestReportExport:
    def test_export_matches_the_analysis_on_screen(self, client):
        """Exporting a different report than the reviewer is looking at defeats the audit trail."""
        body = client.post("/api/analyze", json={"mode": "agent"}).json()
        report_id = body["analysis_id"]
        exported = client.get(f"/api/report?format=json&report_id={report_id}").json()
        assert exported["analysis_id"] == report_id

    def test_export_without_a_report_id_uses_the_latest_report(self, client):
        body = client.post("/api/analyze", json={"mode": "pipeline"}).json()
        exported = client.get("/api/report?format=json").json()
        assert exported["analysis_id"] == body["analysis_id"]

    def test_export_of_an_unknown_report_is_a_404(self, client):
        res = client.get("/api/report?format=json&report_id=ANL-NOPE")
        assert res.status_code == 404

    def test_markdown_export_includes_the_review_cycle(self, client):
        body = client.post("/api/analyze", json={"mode": "agent"}).json()
        res = client.get(f"/api/report?format=markdown&report_id={body['analysis_id']}")
        assert res.status_code == 200
        assert "Review cycle" in res.text


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


class TestDataHealth:
    """The validation report the UI shows behind the analysis."""

    def test_the_analysis_carries_the_validation_report(self, client):
        body = client.post("/api/analyze", json={"mode": "pipeline"}).json()
        health = body["data_health"]
        assert health, "data_health was in the contract but never populated"
        assert health["workloads_checked"] == len(body["results"])
        assert health["workloads"], "no per-workload metric health was reported"
        for workload in health["workloads"]:
            assert workload["status"] in ("healthy", "warning", "error")
            assert workload["required_samples"] > 0

    def test_the_agent_path_carries_it_too(self, client):
        body = client.post("/api/analyze", json={"mode": "agent"}).json()
        assert body["data_health"]["workloads_checked"] == len(body["results"])

    def test_it_matches_the_validation_endpoint(self, client):
        body = client.post("/api/analyze", json={"mode": "pipeline"}).json()
        endpoint = client.get("/api/validation").json()
        assert [w["workload_id"] for w in endpoint["workloads"]] == \
               [w["workload_id"] for w in body["data_health"]["workloads"]]


class TestPolicyDefaults:
    def test_the_defaults_endpoint_returns_the_built_in_policy(self, client):
        res = client.get("/api/policies/defaults")
        assert res.status_code == 200
        defaults = res.json()
        assert defaults["version"]
        assert defaults["max_reduction_pct"] > 0
        assert defaults["cpu_floor_p99_multiplier"] >= 1

    def test_reading_the_defaults_stores_nothing(self, client):
        client.get("/api/policies/defaults")
        live = client.get("/api/policies").json()
        assert live["version"] == "demo-1"
