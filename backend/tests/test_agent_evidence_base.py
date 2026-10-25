"""The evidence the objections are grounded in is retrieved every time.

The log-pressure objection is a blocking one: reducing a container that is already being
OOMKilled is a reliability regression, not a saving. It used to depend on the model choosing
to call `search_logs`, and the deterministic critic has no log rule of its own - so a model
that did not call it had the objection suppressed, and the workload was approved on the
strength of an omission.

The same goes for the dependency map, which grounds the upstream-pressure objection.

These tests drive the orchestrator with a scripted client that never calls either tool.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from app.models.schemas import DecisionStatus
from app.services.agent_orchestrator import AgentOrchestrator
from app.services.orchestrator import default_inputs


class ScriptedClient:
    """A client that replays a fixed list of turns, one per call."""

    def __init__(self, turns: List[Dict[str, Any]]):
        self.turns = list(turns)
        self.calls = 0
        self.users: List[str] = []

    async def chat(self, system: str, user: str, tools: List[Dict[str, Any]],
                   history: List[Dict[str, Any]]) -> Dict[str, Any]:
        turn = self.turns[min(self.calls, len(self.turns) - 1)]
        self.calls += 1
        self.users.append(user)
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


class TestTheEvidenceIsAlwaysRetrieved:
    def test_a_model_that_never_asks_for_the_logs_still_gets_the_objection(self, bundle):
        """`payment-api` has an OOMKilled log. Not asking for it must not hide it."""
        client = ScriptedClient([
            {"tool_call": _tool("analyze_rightsizing", workload_id="payment-api")},
            {"tool_call": _tool("validate_policy")},
            {"content": "The proposal is safe.", "conclusion": True},
        ])
        orchestrator = AgentOrchestrator(bundle, client)
        result, audit = asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))

        codes = {o.code for o in result.objections}
        assert "LOG_PRESSURE_IGNORED" in codes, (
            f"the log-pressure objection was suppressed: {codes}")
        assert result.decision is not DecisionStatus.APPROVED, (
            "a workload being OOMKilled was approved")

    def test_the_logs_are_in_the_evidence_trail(self, bundle):
        """The evidence has to be visible to a reviewer, not just to the objection pass."""
        client = ScriptedClient([
            {"tool_call": _tool("analyze_rightsizing", workload_id="payment-api")},
            {"tool_call": _tool("validate_policy")},
            {"content": "done", "conclusion": True},
        ])
        orchestrator = AgentOrchestrator(bundle, client)
        _result, audit = asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))

        tools = [step.tool for step in audit.steps]
        assert "search_logs" in tools, f"the logs were never retrieved: {tools}"
        assert "get_dependencies" in tools, f"the dependencies were never retrieved: {tools}"
        assert any("search_logs" in entry for entry in audit.evidence_trail), \
            "the logs are not in the evidence trail"

    def test_the_model_is_told_the_evidence_is_already_there(self, bundle):
        """So it does not fetch it again, and so the reason is visible in the transcript."""
        client = ScriptedClient([
            {"tool_call": _tool("analyze_rightsizing", workload_id="payment-api")},
            {"tool_call": _tool("validate_policy")},
            {"content": "done", "conclusion": True},
        ])
        orchestrator = AgentOrchestrator(bundle, client)
        asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))

        # The note goes to the critic, in the turn's context.
        assert any("already been" in user for user in client.users), \
            f"the critic was not told: {client.users}"

    def test_a_workload_with_no_pressure_logs_raises_no_log_objection(self, bundle):
        """The fix must not raise objections that the evidence does not support."""
        client = ScriptedClient([
            {"tool_call": _tool("analyze_rightsizing", workload_id="image-resizer")},
            {"tool_call": _tool("validate_policy")},
            {"content": "done", "conclusion": True},
        ])
        orchestrator = AgentOrchestrator(bundle, client)
        result, _audit = asyncio.run(orchestrator.analyze_workload_agentic("image-resizer"))

        codes = {o.code for o in result.objections}
        assert "LOG_PRESSURE_IGNORED" not in codes, f"an unsupported objection was raised: {codes}"
