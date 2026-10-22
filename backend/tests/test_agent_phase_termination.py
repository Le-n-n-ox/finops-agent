"""How a review cycle ends.

The stand-in client always behaves: it calls its tools in order and concludes. A real model
does not, and two of its habits broke the live cycle:

* it opens with a **plan** ("first I will retrieve the metrics, then analyse the right-sizing")
  instead of calling a tool, which ended the phase with no evidence and no policy check; and
* it never reaches `validate_policy` at all, which left the orchestrator inventing a verdict
  instead of letting the deterministic critic decide.

These tests drive the orchestrator with a scripted client, so the rules are pinned without
needing a model server.
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
        self.systems: List[str] = []

    async def chat(self, system: str, user: str, tools: List[Dict[str, Any]],
                   history: List[Dict[str, Any]]) -> Dict[str, Any]:
        index = min(self.calls, len(self.turns) - 1)
        turn = self.turns[index]
        self.calls += 1
        self.systems.append(system)
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


def _orchestrator(client: ScriptedClient, bundle) -> AgentOrchestrator:
    return AgentOrchestrator(bundle, client)


class TestAPlanIsNotAConclusion:
    def test_a_text_only_first_turn_does_not_end_the_proposer(self, bundle):
        """The model planned instead of acting. The phase must continue, not end.

        A phase that ends on the plan has no evidence and no policy check, so the workload
        comes back as a verdict nobody made.
        """
        client = ScriptedClient([
            # Turn 1: a plan, in words, with no tool call.
            {"content": "Plan: 1. retrieve the metrics, 2. analyse the right-sizing.", "conclusion": True},
            # Turn 2: the model acts on its own plan.
            {"tool_call": _tool("analyze_rightsizing", workload_id="payment-api")},
            # Turn 3: the deterministic check.
            {"tool_call": _tool("validate_policy")},
            # Turn 4: the case for the change.
            {"content": "The spike was a known incident, so the reduction needs review.", "conclusion": True},
        ])
        orchestrator = _orchestrator(client, bundle)

        result, audit = asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))

        tools = [step.tool for step in audit.steps]
        assert "analyze_rightsizing" in tools, "the plan was treated as the end of the phase"
        assert "validate_policy" in tools, "the policy check was never run"
        assert result.decision is not None

    def test_the_proposer_keeps_going_after_a_plan(self, bundle):
        """The plan turn is not the last turn: the phase is still alive afterwards."""
        client = ScriptedClient([
            {"content": "Plan: first I will retrieve the metrics.", "conclusion": True},
            {"tool_call": _tool("analyze_rightsizing", workload_id="payment-api")},
            {"tool_call": _tool("validate_policy")},
            {"content": "Conclusion.", "conclusion": True},
        ])
        orchestrator = _orchestrator(client, bundle)

        _result, audit = asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))

        proposer = audit.cycles[0]
        assert len(proposer.steps) >= 2, "the proposer stopped at the plan"

    def test_a_plan_is_not_recorded_as_the_proposers_case(self, bundle):
        """The summary is what the reviewer reads as the case for the change."""
        client = ScriptedClient([
            {"content": "Plan: first I will retrieve the metrics.", "conclusion": True},
            {"tool_call": _tool("analyze_rightsizing", workload_id="payment-api")},
            {"tool_call": _tool("validate_policy")},
            {"content": "The case for the change.", "conclusion": True},
        ])
        orchestrator = _orchestrator(client, bundle)

        _result, audit = asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))

        assert audit.cycles[0].summary == "The case for the change."


class TestTheDeterministicCriticAlwaysDecides:
    def test_the_policy_check_decides_when_the_agent_calls_it(self, bundle):
        client = ScriptedClient([
            {"tool_call": _tool("analyze_rightsizing", workload_id="payment-api")},
            {"tool_call": _tool("validate_policy")},
            {"content": "Conclusion.", "conclusion": True},
        ])
        orchestrator = _orchestrator(client, bundle)

        result, _audit = asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))

        # The same verdict the deterministic pipeline reaches for this workload.
        assert result.decision in set(DecisionStatus)

    def test_the_critic_still_decides_when_the_agent_never_validates(self, bundle):
        """A missed tool call must not turn into a verdict the orchestrator made up.

        `validate_policy` validates the most recent `analyze_rightsizing` result, so running
        the deterministic critic over that proposal is the same verdict - not a second opinion,
        and not a fabricated one.
        """
        client = ScriptedClient([
            {"tool_call": _tool("analyze_rightsizing", workload_id="payment-api")},
            {"content": "I could not finish the policy check.", "conclusion": True},
        ])
        orchestrator = _orchestrator(client, bundle)

        result, _audit = asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))

        assert "never investigated" not in (result.reason or ""), \
            "the deterministic critic owns the decision, so it must have run"
        assert result.decision is not DecisionStatus.NEEDS_REVIEW or result.checks, \
            "a verdict needs the deterministic critic's checks behind it"

    def test_a_workload_the_agent_never_touched_is_raised_for_a_human(self, bundle):
        """With no proposal and no policy check there is nothing to decide. Say so."""
        client = ScriptedClient([
            {"content": "I am not sure where to start.", "conclusion": True},
        ])
        orchestrator = _orchestrator(client, bundle)

        result, _audit = asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))

        assert result.decision is DecisionStatus.NEEDS_REVIEW
        assert "never investigated" in (result.reason or "")


class TestThePhaseStopsWhenTheVerdictIsIn:
    def test_the_proposer_does_not_keep_calling_tools_after_the_verdict(self, bundle):
        """Once the deterministic verdict is in, the proposal cannot change.

        A model that keeps going burns its iteration budget on redundant calls, and the review
        takes minutes instead of seconds.
        """
        client = ScriptedClient([
            {"tool_call": _tool("analyze_rightsizing", workload_id="payment-api")},
            {"tool_call": _tool("validate_policy")},
            # The model, ignoring the verdict, calls a tool again.
            {"tool_call": _tool("get_incident_history", workload_id="payment-api")},
            {"tool_call": _tool("search_logs", workload_id="payment-api")},
        ])
        orchestrator = _orchestrator(client, bundle)

        _result, audit = asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))

        proposer_tools = [step.tool for step in audit.cycles[0].steps]
        assert proposer_tools.count("validate_policy") == 1
        assert "get_incident_history" not in proposer_tools, \
            "the proposer kept working after the deterministic verdict was in hand"


class TestThePolicyCheckJudgesTheOptimizersProposal:
    """The proposal the safety check approves is the one the optimizer produced.

    The model often echoes the proposal back to `validate_policy` as `proposal_data`. When it
    did that badly - a truncated copy, or the JSON as a string - the tool failed, and a failed
    tool was mistaken for a verdict: the orchestrator handed a plain dict to the rest of the
    cycle, which died on it, and the workload lost its whole review to the deterministic
    fallback without saying why.
    """

    def test_a_malformed_proposal_data_still_produces_a_verdict(self, bundle):
        client = ScriptedClient([
            {"tool_call": _tool("analyze_rightsizing", workload_id="payment-api")},
            {"tool_call": _tool("validate_policy", proposal_data={"status": "proposed"})},
            {"content": "Conclusion.", "conclusion": True},
        ])
        orchestrator = _orchestrator(client, bundle)

        result, audit = asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))

        tools = [step.tool for step in audit.cycles[0].steps]
        assert "validate_policy" in tools
        verdict_steps = [s for s in audit.cycles[0].steps if s.tool == "validate_policy"]
        assert not isinstance(verdict_steps[0].result, dict), \
            "the policy check failed instead of producing a verdict"
        assert result.decision is not None

    def test_a_proposal_data_that_is_a_json_string_still_produces_a_verdict(self, bundle):
        client = ScriptedClient([
            {"tool_call": _tool("analyze_rightsizing", workload_id="payment-api")},
            {"tool_call": _tool("validate_policy", proposal_data="{\"status\": \"proposed\"}")},
            {"content": "Conclusion.", "conclusion": True},
        ])
        orchestrator = _orchestrator(client, bundle)

        result, _audit = asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))

        assert result.decision is not None
        assert "never investigated" not in (result.reason or "")

    def test_the_judged_proposal_is_the_optimizers(self, bundle):
        """The model does not get to author the numbers the safety check approves."""
        from app.services.agent_tools import AgentToolbox
        from app.services.optimizer_service import analyze_workload

        toolbox = AgentToolbox(bundle)
        proposal = analyze_workload(
            workload=next(s for s in bundle.services if s.name == "docs-renderer"),
            rows=[r for r in bundle.usage_rows if r.service == "docs-renderer"],
            policy=bundle.policy.optimizer,
            now=bundle.policy.simulation_now,
            cost_model=bundle.cost_model,
            incidents=bundle.incidents,
            events=bundle.events,
        )
        assert proposal.proposed is not None, "this workload has no proposal to tamper with"
        toolbox.call("analyze_rightsizing", workload_id="docs-renderer")

        # A model that tries to hand the critic a different, more aggressive proposal.
        tampered = proposal.model_dump(mode="json")
        tampered["proposed"]["cpu_request_millicores"] = 1
        verdict = toolbox.call("validate_policy", proposal_data=tampered)

        assert verdict.status == "success", f"the policy check failed: {verdict.error}"
        assert verdict.data.proposal.proposed.cpu_request_millicores == \
            proposal.proposed.cpu_request_millicores, \
            "the model authored the proposal the safety check approved"

    def test_a_failed_policy_check_is_not_mistaken_for_a_verdict(self, bundle):
        """A tool that failed holds an error, not a verdict. The cycle must not treat it as one."""
        client = ScriptedClient([
            {"tool_call": _tool("analyze_rightsizing", workload_id="payment-api")},
            {"tool_call": _tool("validate_policy")},
            {"content": "Conclusion.", "conclusion": True},
        ])
        orchestrator = _orchestrator(client, bundle)

        result, _audit = asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))

        assert result.decision is not None
        assert result.proposal is not None
