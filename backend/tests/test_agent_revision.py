"""The revision turn: the proposer answers the objections the critic raised.

Before this phase existed the cycle was a one-way pipeline - the critic objected, the judge
escalated, and the proposal that never got to answer was the one published. These tests pin the
three answers (concede / narrow / keep), the guarantees around them (no invented numbers, no
decision that gets *less* conservative), and the wiring that records the phase.
"""
from __future__ import annotations

import asyncio

import pytest

from app.services.agent_orchestrator import AgentOrchestrator, _parse_revision
from app.services.critic_service import evaluate
from app.services.optimizer_service import build_proposals
from app.services.orchestrator import default_inputs
from app.services.simulated_llm import SimulatedLLMClient


@pytest.fixture()
def bundle():
    return default_inputs()


def _approved_formal(bundle):
    """A real approved proposal that reduces both resources, so narrowing has something to give back."""
    for proposal in build_proposals(bundle, bundle.policy.simulation_now):
        result = evaluate(proposal, bundle)
        proposed = result.proposal.proposed
        if proposed is None or result.decision.name != "APPROVED":
            continue
        current = result.proposal.current
        if (proposed.cpu_request_millicores != current.cpu_request_millicores
                and proposed.memory_request_mib != current.memory_request_mib):
            return result
    pytest.skip("the fixture has no approved proposal that reduces both resources")


# --------------------------------------------------------------------------- 1. parsing
class TestRevisionParsing:
    def test_narrow_keeps_the_named_resource(self):
        action, resource, reason = _parse_revision(
            '{"action": "narrow", "resource": "cpu", "reason": "memory objection stands"}')
        assert (action, resource) == ("narrow", "cpu")
        assert reason == "memory objection stands"

    def test_concede_is_read(self):
        assert _parse_revision('{"action": "concede", "reason": "fair"}')[0] == "concede"

    def test_prose_around_the_json_is_tolerated(self):
        assert _parse_revision('Here is my answer: {"action": "keep"} done')[0] == "keep"

    def test_unusable_answer_never_changes_the_proposal(self):
        """A garbled reply must not be read as permission to withdraw or halve a real change."""
        for content in (None, "", "I would rather not", "{not json}", '{"action": "delete_everything"}',
                        '{"action": "narrow"}', '{"action": "narrow", "resource": "disk"}'):
            assert _parse_revision(content)[0] == "keep", content


# --------------------------------------------------------------------------- 2. what a revision does
class TestRevisionOutcome:
    def test_narrowing_gives_the_contested_resource_back(self, bundle):
        formal = _approved_formal(bundle)
        orchestrator = AgentOrchestrator(bundle, SimulatedLLMClient())

        narrowed = orchestrator._narrowed(formal, keep="cpu", reason="memory objection stands")

        assert (narrowed.proposal.proposed.memory_request_mib
                == narrowed.proposal.current.memory_request_mib)
        assert (narrowed.proposal.proposed.cpu_request_millicores
                == formal.proposal.proposed.cpu_request_millicores)

    def test_narrowing_reprices_the_remaining_change(self, bundle):
        """The critic reports whatever the proposal says it saves, so the figure has to be recomputed."""
        formal = _approved_formal(bundle)
        orchestrator = AgentOrchestrator(bundle, SimulatedLLMClient())

        narrowed = orchestrator._narrowed(formal, keep="cpu", reason="memory objection stands")

        assert narrowed.monthly_savings_estimate_usd < formal.monthly_savings_estimate_usd
        assert narrowed.monthly_savings_estimate_usd > 0
        assert narrowed.proposal.savings_estimate.cpu_request_reduction_pct > 0
        assert narrowed.proposal.savings_estimate.memory_request_reduction_pct == 0

    def test_withdrawing_is_a_clean_no_change(self, bundle):
        formal = _approved_formal(bundle)
        orchestrator = AgentOrchestrator(bundle, SimulatedLLMClient())

        withdrawn = orchestrator._withdrawn(formal, "the objection is right")

        assert withdrawn.decision.name == "NO_CHANGE"
        assert withdrawn.proposal.proposed is None
        assert withdrawn.monthly_savings_estimate_usd == 0.0

    def test_a_revision_never_makes_the_decision_less_conservative(self, bundle):
        """Narrowing can only shrink a change, so it can never turn a held-back proposal loose."""
        formal = _approved_formal(bundle)
        orchestrator = AgentOrchestrator(bundle, SimulatedLLMClient())

        for keep in ("cpu", "memory"):
            narrowed = orchestrator._narrowed(formal, keep=keep, reason="test")
            assert narrowed.decision.name in {"APPROVED", "NO_CHANGE"}


# --------------------------------------------------------------------------- 3. wiring
def _oom_logs(*_args, **_kwargs):
    """The evidence the deterministic critic has no rule of its own for: a container being OOMKilled."""
    return [{"timestamp": "2026-09-12T10:00:00Z", "level": "error",
             "message": "OOMKilled: container exceeded its memory limit"}]


class TestRevisionPhase:
    def test_the_demo_narrows_a_memory_objection_to_a_cpu_change(self, bundle):
        """`docs-renderer` is over-provisioned and has an OOMKilled log: the case the loop exists for.

        The critic objects to lowering memory; the proposer answers by keeping only the CPU change;
        the narrowed proposal passes, so the workload ships a smaller safe change instead of being
        escalated as a whole.
        """
        orchestrator = AgentOrchestrator(bundle, SimulatedLLMClient())

        result, audit = asyncio.run(orchestrator.analyze_workload_agentic("docs-renderer"))

        assert [cycle.role for cycle in audit.cycles] == ["proposer", "critic", "revision", "judge"]
        assert any(o.code == "LOG_PRESSURE_IGNORED" for o in audit.cycles[1].objections)

        revision = audit.cycles[2]
        assert revision.verdict == "narrow"

        current, proposed = result.proposal.current, result.proposal.proposed
        assert proposed.memory_request_mib == current.memory_request_mib, "memory must be given back"
        assert proposed.cpu_request_millicores < current.cpu_request_millicores, "cpu must stay reduced"
        assert result.decision.name == "APPROVED"
        assert "LOG_PRESSURE_IGNORED" not in {o.code for o in result.objections}, (
            "the memory objection must retire once memory is no longer being changed")

    def test_the_judge_sees_only_the_objections_that_survive(self, bundle):
        orchestrator = AgentOrchestrator(bundle, SimulatedLLMClient())

        _, audit = asyncio.run(orchestrator.analyze_workload_agentic("docs-renderer"))

        critic, revision, judge = audit.cycles[1], audit.cycles[2], audit.cycles[3]
        assert [o.code for o in judge.objections] == [o.code for o in revision.objections]
        assert set(o.code for o in judge.objections) <= {o.code for o in critic.objections}
        assert judge.objections == [], "the only objection was answered by the revision"

    def test_no_change_means_no_revision_turn(self, bundle):
        """There is nothing to answer when the optimizer proposed nothing; the phase must not fire."""
        orchestrator = AgentOrchestrator(bundle, SimulatedLLMClient())

        _, audit = asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))

        assert [cycle.role for cycle in audit.cycles] == ["proposer", "critic", "judge"]


# --------------------------------------------------------------------------- 4. resource-aware objections
class TestLogObjectionIsResourceAware:
    """An OOM kill argues against lowering memory, not against lowering CPU as well."""

    def test_a_memory_objection_does_not_block_a_cpu_only_change(self, bundle, monkeypatch):
        from app.services import data_loader

        monkeypatch.setattr(data_loader, "get_logs", _oom_logs)
        orchestrator = AgentOrchestrator(bundle, SimulatedLLMClient())

        # image-resizer lowers CPU only, so the memory objection does not apply to its proposal.
        result, _ = asyncio.run(orchestrator.analyze_workload_agentic("image-resizer"))

        assert "LOG_PRESSURE_IGNORED" not in {o.code for o in result.objections}

    def test_a_cpu_objection_does_block_a_cpu_change(self, bundle, monkeypatch):
        from app.services import data_loader

        def _cpu_logs(*_args, **_kwargs):
            return [{"timestamp": "2026-09-12T10:00:00Z", "level": "WARN",
                     "message": "CPU throttling detected; latency increasing."}]

        monkeypatch.setattr(data_loader, "get_logs", _cpu_logs)
        orchestrator = AgentOrchestrator(bundle, SimulatedLLMClient())

        result, audit = asyncio.run(orchestrator.analyze_workload_agentic("image-resizer"))

        assert any(o.code == "LOG_PRESSURE_IGNORED" for o in audit.cycles[1].objections)
        # The answer is to keep memory and give up the CPU change, which the log objects to.
        revision = next((c for c in audit.cycles if c.role == "revision"), None)
        assert revision is not None and revision.verdict == "narrow"
        proposed = result.proposal.proposed
        if proposed is not None:
            assert proposed.cpu_request_millicores == result.proposal.current.cpu_request_millicores


