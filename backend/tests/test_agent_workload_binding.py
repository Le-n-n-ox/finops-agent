"""The model must not be able to choose which workload's proposal is judged.

The agent cycle is a safety review: the deterministic critic decides, on a proposal the
deterministic optimizer produced, about one specific workload. The model chooses which tool
to call and with which arguments, so two things have to hold that the model cannot break:

* a review of workload A may not validate workload B's proposal, and
* the verdict published for workload A must be about workload A.

Before this was enforced, the toolbox was shared across the whole run and remembered the last
result of every tool. A model that named a different workload in `analyze_rightsizing` had
that workload's proposal judged by the deterministic critic, and the resulting verdict was
published under the workload actually under review. The critic still decided - but it decided
about the wrong workload.

These tests drive the orchestrator with a scripted client, so the rules are pinned without
needing a model server.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from app.models.schemas import DecisionStatus
from app.services.agent_orchestrator import AgentOrchestrator
from app.services.agent_tools import AgentToolbox
from app.services.orchestrator import default_inputs


class ScriptedClient:
    """A client that replays a fixed list of turns, one per call."""

    def __init__(self, turns: List[Dict[str, Any]]):
        self.turns = list(turns)
        self.calls = 0

    async def chat(self, system: str, user: str, tools: List[Dict[str, Any]],
                   history: List[Dict[str, Any]]) -> Dict[str, Any]:
        index = min(self.calls, len(self.turns) - 1)
        turn = self.turns[index]
        self.calls += 1
        return {
            "content": turn.get("content"),
            "tool_call": turn.get("tool_call"),
            "thought": turn.get("thought"),
            "conclusion": turn.get("conclusion", False),
            "tool_call_id": f"scripted-{self.calls}",
        }


def _tool(name: str, **arguments: Any) -> Dict[str, Any]:
    return {"name": name, "arguments": arguments}


@pytest.fixture()
def bundle():
    return default_inputs()


class TestTheToolboxIsBoundToOneWorkload:
    def test_a_tool_call_for_another_workload_is_refused(self, bundle):
        toolbox = AgentToolbox(bundle, workload_id="payment-api")
        result = toolbox.call("analyze_rightsizing", workload_id="queue-cleaner")
        assert result.status == "error"
        assert "payment-api" in (result.error or "")

    @pytest.mark.parametrize("tool", [
        "get_workload_metrics", "analyze_rightsizing", "detect_risk_patterns",
        "get_incident_history", "search_logs", "get_dependencies",
    ])
    def test_every_workload_scoped_tool_refuses_another_workload(self, bundle, tool):
        toolbox = AgentToolbox(bundle, workload_id="payment-api")
        result = toolbox.call(tool, workload_id="queue-cleaner")
        assert result.status == "error", f"{tool} accepted another workload's id"

    def test_the_workload_under_review_still_works(self, bundle):
        toolbox = AgentToolbox(bundle, workload_id="payment-api")
        result = toolbox.call("analyze_rightsizing", workload_id="payment-api")
        assert result.status == "success", result.error
        assert result.data.workload_id == "payment-api"

    def test_an_unbound_toolbox_is_unchanged(self, bundle):
        """The toolbox is still usable unbound - the tests and the tooling use it directly."""
        toolbox = AgentToolbox(bundle)
        result = toolbox.call("analyze_rightsizing", workload_id="payment-api")
        assert result.status == "success", result.error


class TestTheModelCannotChooseTheProposal:
    def test_a_model_naming_another_workload_does_not_get_that_verdict(self, bundle):
        """The model names a different workload; the review must not publish its verdict."""
        client = ScriptedClient([
            {"tool_call": _tool("analyze_rightsizing", workload_id="queue-cleaner")},
            {"tool_call": _tool("validate_policy")},
            {"content": "done", "conclusion": True},
        ])
        orchestrator = AgentOrchestrator(bundle, client)
        result, audit = asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))

        # The other workload's proposal never entered the review at all.
        foreign = [s for s in audit.steps
                   if s.tool == "analyze_rightsizing"
                   and getattr(s.result, "workload_id", None) == "queue-cleaner"]
        assert not foreign, "another workload's proposal entered the review"

        # The tool refused the call, and said which workload it would accept.
        refusals = [s for s in audit.steps if s.tool == "analyze_rightsizing"
                    and isinstance(s.result, dict) and "error" in s.result]
        assert refusals, "the tool accepted another workload's id"

        assert result.workload_id == "payment-api"
        assert result.proposal.workload_id != "queue-cleaner"
        assert result.decision is not DecisionStatus.APPROVED, (
            "a workload was approved on another workload's evidence")

    def test_a_model_that_corrects_itself_gets_a_real_verdict(self, bundle):
        """The refusal tells the model what to do; a model that retries gets a full review."""
        client = ScriptedClient([
            {"tool_call": _tool("analyze_rightsizing", workload_id="queue-cleaner")},
            {"tool_call": _tool("analyze_rightsizing", workload_id="payment-api")},
            {"tool_call": _tool("validate_policy")},
            {"content": "done", "conclusion": True},
        ])
        orchestrator = AgentOrchestrator(bundle, client)
        result, audit = asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))

        assert result.proposal.workload_id == "payment-api"
        assert any(s.tool == "validate_policy" for s in audit.steps)
        assert result.decision is not DecisionStatus.NEEDS_REVIEW

    def test_a_failed_policy_check_does_not_end_the_phase(self, bundle):
        """A policy check that produced no verdict must not end the phase.

        The proposer stops once the deterministic verdict is in hand, because the proposal
        cannot change after that. A policy check that *failed* holds no verdict - and the
        model's next move is usually to correct what it got wrong. Treating the failure as a
        verdict ended the phase before the correction could run, and the workload was left
        with no verdict at all.
        """
        client = ScriptedClient([
            {"tool_call": _tool("analyze_rightsizing", workload_id="queue-cleaner")},
            {"tool_call": _tool("validate_policy")},
            {"tool_call": _tool("analyze_rightsizing", workload_id="payment-api")},
            {"tool_call": _tool("validate_policy")},
            {"content": "done", "conclusion": True},
        ])
        orchestrator = AgentOrchestrator(bundle, client)
        result, audit = asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))

        # The correction ran, and the policy check after it produced the verdict.
        tools = [s.tool for s in audit.steps]
        assert tools.count("analyze_rightsizing") == 2, f"the correction never ran: {tools}"
        verdicts = [s for s in audit.steps
                    if s.tool == "validate_policy" and getattr(s.result, "workload_id", None)]
        assert verdicts, f"no policy verdict was produced: {tools}"
        assert verdicts[-1].result.workload_id == "payment-api"
        assert result.proposal.workload_id == "payment-api"
        assert result.decision is not DecisionStatus.NEEDS_REVIEW, \
            "the workload was left without a verdict"

    def test_each_workload_gets_its_own_verdict(self, bundle):
        """Two reviews in a row must not share a toolbox's history."""
        client = ScriptedClient([
            {"tool_call": _tool("analyze_rightsizing", workload_id="image-resizer")},
            {"tool_call": _tool("validate_policy")},
            {"content": "done", "conclusion": True},
        ])
        orchestrator = AgentOrchestrator(bundle, client)
        first, _ = asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))
        second, _ = asyncio.run(orchestrator.analyze_workload_agentic("email-worker"))

        assert first.proposal.workload_id == "payment-api"
        assert second.proposal.workload_id == "email-worker"

    def test_a_verdict_about_another_workload_is_not_published(self, bundle):
        """Even if a foreign verdict reached the audit log, it is not this workload's verdict."""
        from app.models.schemas import AgentAuditLog, ToolCall
        from app.services.critic_service import evaluate
        from app.services.optimizer_service import analyze_workload

        spec = next(s for s in bundle.services if s.name == "queue-cleaner")
        foreign = evaluate(
            analyze_workload(workload=spec,
                             rows=[r for r in bundle.usage_rows if r.service == "queue-cleaner"],
                             policy=bundle.policy.optimizer,
                             now=bundle.policy.simulation_now,
                             cost_model=bundle.cost_model,
                             incidents=bundle.incidents,
                             events=bundle.events),
            bundle)

        orchestrator = AgentOrchestrator(bundle, ScriptedClient([]))
        audit = AgentAuditLog(session_id="s", workload_id="payment-api")
        audit.steps.append(ToolCall(tool="validate_policy", params={}, result=foreign))

        verdict = orchestrator._get_last_policy_result(audit)
        assert verdict.workload_id != "queue-cleaner"
