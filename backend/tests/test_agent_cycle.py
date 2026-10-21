"""Tests for the agent intelligence layer: tooling, adversarial cycle, confidence, feedback memory."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app.models.review import ReviewAction
from app.models.schemas import (
    AgentAuditLog,
    CheckStatus,
    DecisionStatus,
    ResourceSettings,
    UsageMetrics,
    WorkloadResult,
)
from app.services import adversarial_service, data_loader
from app.services.agent_orchestrator import AgentOrchestrator
from app.services.agent_tools import AgentToolbox
from app.services.simulated_llm import SimulatedLLMClient
from app.services.store import Store
from app.services.verification_service import VerificationService


# --------------------------------------------------------------------------- fixtures
@pytest.fixture()
def bundle():
    from app.services.orchestrator import default_inputs
    return default_inputs()


@pytest.fixture()
def store(tmp_path):
    return Store(tmp_path / "history.sqlite3")


# --------------------------------------------------------------------------- 1. tooling
class TestTooling:
    def test_search_logs_returns_pressure_entries(self):
        logs = data_loader.get_logs("payment-api")
        assert logs, "payment-api should have simulated logs"
        assert any("OOMKilled" in entry["message"] for entry in logs)

    def test_search_logs_filters_by_keyword(self):
        logs = data_loader.get_logs("payment-api", keyword="throttling")
        assert logs
        assert all("throttl" in entry["message"].lower() for entry in logs)

    def test_search_logs_filters_by_level(self):
        errors = data_loader.get_logs("payment-api", level="error")
        assert errors
        assert all(entry["level"] == "ERROR" for entry in errors)

    def test_search_logs_unknown_workload_is_empty_not_an_error(self):
        assert data_loader.get_logs("does-not-exist") == []

    def test_get_dependencies_returns_upstream_services(self):
        assert "auth-service" in data_loader.get_dependencies("payment-api")
        assert data_loader.get_dependencies("auth-service") == []

    def test_toolbox_exposes_new_tools(self, bundle):
        toolbox = AgentToolbox(bundle)
        names = {tool["name"] for tool in toolbox.get_tool_definitions()}
        assert {"search_logs", "get_dependencies"} <= names

    def test_toolbox_executes_the_new_tools(self, bundle):
        toolbox = AgentToolbox(bundle)
        result = toolbox.call("search_logs", workload_id="payment-api")
        assert result.status == "success"
        assert result.data
        deps = toolbox.call("get_dependencies", workload_id="payment-api")
        assert deps.status == "success"
        assert "auth-service" in deps.data

    def test_validate_policy_reuses_the_last_rightsizing_result(self, bundle):
        """The agent must not have to retype a whole proposal through the LLM."""
        toolbox = AgentToolbox(bundle)
        proposal = toolbox.call("analyze_rightsizing", workload_id="image-resizer")
        assert proposal.status == "success"
        judged = toolbox.call("validate_policy")
        assert judged.status == "success"
        assert judged.data.decision in set(DecisionStatus)

    def test_validate_policy_without_a_proposal_errors_cleanly(self, bundle):
        toolbox = AgentToolbox(bundle)
        judged = toolbox.call("validate_policy")
        assert judged.status == "error"
        assert "analyze_rightsizing" in judged.error


# --------------------------------------------------------------------------- 2. adversarial cycle
class TestAdversarialCycle:
    def test_agent_runs_proposer_critic_judge(self, bundle):
        orchestrator = AgentOrchestrator(bundle, SimulatedLLMClient())
        result, audit = asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))
        roles = [cycle.role for cycle in audit.cycles]
        assert roles == ["proposer", "critic", "judge"]

    def test_audit_log_records_the_cycle(self, bundle):
        orchestrator = AgentOrchestrator(bundle, SimulatedLLMClient())
        _, audit = asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))
        assert isinstance(audit, AgentAuditLog)
        assert audit.steps, "the agent must actually call tools"
        assert audit.evidence_trail
        assert audit.final_decision is not None

    def test_proposer_calls_the_mandatory_policy_check(self, bundle):
        orchestrator = AgentOrchestrator(bundle, SimulatedLLMClient())
        _, audit = asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))
        assert any(step.tool == "validate_policy" for step in audit.steps), \
            "validate_policy is mandatory and must run"

    def test_log_pressure_raises_a_blocking_objection(self, bundle):
        orchestrator = AgentOrchestrator(bundle, SimulatedLLMClient())
        result, _ = asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))
        codes = {o.code for o in result.objections}
        assert adversarial_service.LOG_PRESSURE in codes
        assert any(o.severity == "blocking" for o in result.objections)

    def test_incident_overlap_raises_an_objection(self, bundle):
        orchestrator = AgentOrchestrator(bundle, SimulatedLLMClient())
        result, _ = asyncio.run(orchestrator.analyze_workload_agentic("email-worker"))
        codes = {o.code for o in result.objections}
        assert adversarial_service.INCIDENT_OVERLAP in codes

    def test_clean_workload_raises_no_blocking_objection(self, bundle):
        orchestrator = AgentOrchestrator(bundle, SimulatedLLMClient())
        result, _ = asyncio.run(orchestrator.analyze_workload_agentic("image-resizer"))
        blocking = [o for o in result.objections if o.severity == "blocking"]
        assert blocking == [], f"unexpected blocking objections: {[o.code for o in blocking]}"

    def test_past_events_do_not_block(self, bundle):
        """A finished event is history. It must not hold a future change forever."""
        orchestrator = AgentOrchestrator(bundle, SimulatedLLMClient())
        result, _ = asyncio.run(orchestrator.analyze_workload_agentic("auth-service"))
        codes = {o.code for o in result.objections}
        assert adversarial_service.RECURRING_EVENT not in codes

    def test_judge_verdict_is_recorded(self, bundle):
        orchestrator = AgentOrchestrator(bundle, SimulatedLLMClient())
        _, audit = asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))
        judge = audit.cycles[-1]
        assert judge.role == "judge"
        assert judge.verdict in {"accept", "confirm", "escalate", "proceed_with_caveat"}

    def test_agentic_decisions_match_the_deterministic_pipeline(self, bundle):
        """The adversarial phase may add objections; it must not change the decision."""
        from app.services.critic_service import evaluate
        from app.services.optimizer_service import build_proposals

        proposals = {p.workload_id: p for p in build_proposals(bundle, bundle.policy.simulation_now)}
        orchestrator = AgentOrchestrator(bundle, SimulatedLLMClient())
        for workload_id, proposal in proposals.items():
            expected = evaluate(proposal, bundle, bundle.policy.simulation_now).decision
            actual, _ = asyncio.run(orchestrator.analyze_workload_agentic(workload_id))
            assert actual.decision == expected, f"{workload_id}: agent said {actual.decision}, expected {expected}"

    def test_cycle_is_bounded_and_does_not_loop_forever(self, bundle):
        """A non-concluding LLM must hit the iteration cap, not hang."""

        class EndlessLLM:
            async def chat(self, system, user, tools, history):
                return {"content": None, "thought": "thinking",
                        "tool_call": {"name": "get_workload_metrics", "arguments": {"workload_id": "payment-api"}},
                        "conclusion": False}

        orchestrator = AgentOrchestrator(bundle, EndlessLLM())
        _, audit = asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))
        assert len(audit.cycles[0].steps) <= AgentOrchestrator.MAX_PROPOSER_ITERATIONS


# --------------------------------------------------------------------------- 3. confidence scoring
class TestConfidenceScoring:
    def test_hallucinated_numbers_reduce_the_score(self):
        service = VerificationService()
        from app.models.schemas import ToolCall
        steps = [ToolCall(tool="get_workload_metrics", params={"workload_id": "w"},
                          result=[{"cpu_millicores": 100, "memory_mib": 200}])]
        honest = service.verify_report("CPU is 100 millicores", steps)
        fabricated = service.verify_report("CPU is 100 millicores and memory is 9999 MiB", steps)
        assert service.calculate_confidence_score(honest) == 100.0
        assert service.calculate_confidence_score(fabricated) < 100.0

    def test_score_drops_proportionally_to_the_number_of_fakes(self):
        service = VerificationService()
        from app.models.schemas import ToolCall
        steps = [ToolCall(tool="get_workload_metrics", params={"workload_id": "w"},
                          result=[{"cpu_millicores": 100}])]
        one_fake = service.verify_report("CPU 100 fake 5000", steps)
        two_fakes = service.verify_report("CPU 100 fake 5000 fake 6000", steps)
        assert service.calculate_confidence_score(one_fake) > service.calculate_confidence_score(two_fakes)

    def test_score_is_zero_when_every_number_is_fabricated(self):
        service = VerificationService()
        from app.models.schemas import ToolCall
        steps = [ToolCall(tool="get_workload_metrics", params={"workload_id": "w"}, result=[])]
        verification = service.verify_report("CPU 100 memory 200", steps)
        assert service.calculate_confidence_score(verification) == 0.0

    def test_thin_evidence_scores_lower_than_thick_evidence(self):
        service = VerificationService()
        from app.models.schemas import VerificationResult
        clean = VerificationResult(is_valid=True, verified_count=10, unverified_count=0)
        thin, _ = service.score_confidence(clean, sample_count=10, required_samples=168, age_hours=1)
        thick, _ = service.score_confidence(clean, sample_count=720, required_samples=168, age_hours=1)
        assert thick > thin

    def test_risk_overlap_lowers_the_score(self):
        service = VerificationService()
        from app.models.schemas import VerificationResult
        clean = VerificationResult(is_valid=True, verified_count=10, unverified_count=0)
        safe, _ = service.score_confidence(clean, sample_count=720, required_samples=168, age_hours=1)
        risky, _ = service.score_confidence(clean, sample_count=720, required_samples=168, age_hours=1,
                                            risk_overlap=True)
        assert risky < safe

    def test_objections_lower_the_score_proportionally(self):
        service = VerificationService()
        from app.models.schemas import VerificationResult
        clean = VerificationResult(is_valid=True, verified_count=10, unverified_count=0)
        one, _ = service.score_confidence(clean, sample_count=720, required_samples=168, age_hours=1,
                                          blocking_objections=1)
        three, _ = service.score_confidence(clean, sample_count=720, required_samples=168, age_hours=1,
                                            blocking_objections=3)
        assert three < one

    def test_result_carries_score_and_basis(self, bundle):
        orchestrator = AgentOrchestrator(bundle, SimulatedLLMClient())
        result, audit = asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))
        assert 0 <= result.confidence_score <= 100
        assert result.confidence_basis
        assert audit.confidence_score == result.confidence_score

    def test_risky_workload_scores_lower_than_a_clean_one(self, bundle):
        orchestrator = AgentOrchestrator(bundle, SimulatedLLMClient())
        clean, _ = asyncio.run(orchestrator.analyze_workload_agentic("image-resizer"))
        risky, _ = asyncio.run(orchestrator.analyze_workload_agentic("recommendation-api"))
        assert risky.confidence_score < clean.confidence_score

    def test_evidence_trail_lists_the_tool_calls(self, bundle):
        orchestrator = AgentOrchestrator(bundle, SimulatedLLMClient())
        result, _ = asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))
        assert result.evidence_trail
        assert any("analyze_rightsizing" in line for line in result.evidence_trail)


# --------------------------------------------------------------------------- 4. human feedback memory
class TestFeedbackMemory:
    def _seed_rejection(self, store, workload_id="payment-api"):
        """Record a human rejection against an existing decision."""
        from app.services.orchestrator import run_analysis_with_bundle
        from app.services.fingerprints import fingerprint
        response, bundle = run_analysis_with_bundle()
        for result in response.results:
            if result.workload_id != workload_id:
                continue
            decision_id = store.save_decision_record(
                result, "ANL-TEST", fingerprint(workload_id, bundle), "demo-1")
            return store.record_reviewer_action(
                decision_id, ReviewAction.REJECTED,
                comment="Do not cut memory; we saw an OOM last month.",
                reviewer="alice",
                rejection_reasons=["memory reduction caused an OOMKill"],
                resource="memory",
                reviewer_guidance="keep memory, cpu is fine",
            )
        return None

    def test_rejection_reasons_are_persisted(self, store):
        record = self._seed_rejection(store)
        assert record is not None
        assert record.rejection_reasons == ["memory reduction caused an OOMKill"]
        assert record.resource == "memory"

    def test_feedback_is_retrievable_for_the_workload(self, store):
        self._seed_rejection(store)
        feedback = store.get_feedback_for_workload("payment-api")
        assert feedback
        assert feedback[0].rejection_reasons == ["memory reduction caused an OOMKill"]

    def test_feedback_is_scoped_to_the_workload(self, store):
        self._seed_rejection(store)
        assert store.get_feedback_for_workload("auth-service") == []

    def test_agent_injects_historical_lessons_into_the_prompt(self, bundle, store):
        self._seed_rejection(store)
        orchestrator = AgentOrchestrator(bundle, SimulatedLLMClient(), store=store)
        result, audit = asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))
        assert audit.historical_lessons
        assert any("OOMKill" in lesson for lesson in audit.historical_lessons)

    def test_the_llm_actually_receives_the_lesson(self, bundle, store):
        """The lesson must reach the prompt the model is given, not just the audit log."""
        self._seed_rejection(store)
        seen: list[str] = []

        class RecordingLLM:
            async def chat(self, system, user, tools, history):
                seen.append(system)
                return {"content": None, "thought": "checking",
                        "tool_call": {"name": "analyze_rightsizing", "arguments": {"workload_id": "payment-api"}},
                        "conclusion": False}

        orchestrator = AgentOrchestrator(bundle, RecordingLLM(), store=store)
        asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))
        assert seen, "the LLM was never called"
        assert any("HISTORICAL LESSONS" in system for system in seen)
        assert any("OOMKill" in system for system in seen)

    def test_a_lesson_names_the_resource_and_the_guidance(self, bundle, store):
        self._seed_rejection(store)
        orchestrator = AgentOrchestrator(bundle, SimulatedLLMClient(), store=store)
        lessons = orchestrator._historical_lessons("payment-api")
        assert lessons
        assert any("resource: memory" in lesson for lesson in lessons)
        assert any("keep memory" in lesson for lesson in lessons)

    def test_only_rejections_become_lessons(self, bundle, store):
        """An acceptance is not a lesson. Only rejections should steer the agent."""
        from app.services.orchestrator import run_analysis_with_bundle
        from app.services.fingerprints import fingerprint
        response, bundle_ = run_analysis_with_bundle()
        # An approved workload, so the acceptance is a legal reviewer action.
        result = next(r for r in response.results if r.decision.value == "approved")
        decision_id = store.save_decision_record(result, "ANL-TEST", fingerprint(result.workload_id, bundle_), "demo-1")
        store.record_reviewer_action(decision_id, ReviewAction.ACCEPTED_FOR_IMPLEMENTATION,
                                     comment="looks good to me", reviewer="bob")
        orchestrator = AgentOrchestrator(bundle, SimulatedLLMClient(), store=store)
        assert orchestrator._historical_lessons(result.workload_id) == []

    def test_lesson_appears_in_the_proposer_system_prompt(self, bundle, store):
        self._seed_rejection(store)
        orchestrator = AgentOrchestrator(bundle, SimulatedLLMClient(), store=store)
        prompt = orchestrator._proposer_prompt("payment-api", orchestrator._historical_lessons("payment-api"))
        assert "HISTORICAL LESSONS" in prompt
        assert "OOMKill" in prompt

    def test_no_lessons_when_the_store_is_empty(self, bundle, store):
        orchestrator = AgentOrchestrator(bundle, SimulatedLLMClient(), store=store)
        _, audit = asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))
        assert audit.historical_lessons == []

    def test_agent_survives_a_broken_store(self, bundle):
        """A missing history must never abort an analysis."""

        class BrokenStore:
            def get_feedback_for_workload(self, workload_id):
                raise RuntimeError("db is down")

        orchestrator = AgentOrchestrator(bundle, SimulatedLLMClient(), store=BrokenStore())
        result, audit = asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))
        assert result.decision in set(DecisionStatus)
        assert audit.historical_lessons == []

    def test_audit_trail_returns_the_structured_reasons(self, store):
        record = self._seed_rejection(store)
        trail = store.audit(decision_id=record.decision_id)
        assert trail
        assert trail[0].rejection_reasons == ["memory reduction caused an OOMKill"]
