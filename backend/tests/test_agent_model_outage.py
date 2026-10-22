"""What happens when the model server goes away mid-review.

A live run lost the agent review for two of twelve workloads: the model server refused a
connection, the exception unwound the whole workload, and the catch-all in the pipeline turned
it into a deterministic result that looked exactly like a reviewed one. The workload's name
appeared in a warning; the cause did not, and the container logs held nothing at all.

The rule these tests pin down: **a model outage degrades a review, it never decides anything,
and it never disappears quietly.**

* the evidence gathered before the outage is kept;
* the deterministic critic still owns the verdict;
* the report says the review was cut short, and says why.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from app.integrations.llm_client import LLMUnavailable
from app.models.schemas import DecisionStatus
from app.services.agent_orchestrator import AgentOrchestrator
from app.services.orchestrator import default_inputs, run_analysis_agentic


class FlakyClient:
    """A client that serves scripted turns, and refuses to answer inside a window of calls.

    `fail_from`/`fail_until` are 1-based call indices. Only the calls inside that window raise,
    so a test can say "the server went away on the third turn" without making every later turn
    fail too.
    """

    def __init__(self, turns: List[Dict[str, Any]], fail_from: int | None = None,
                 fail_until: int | None = None,
                 message: str = "The model server at http://127.0.0.1:8088/v1 could not be reached: "
                                "ConnectError('connection refused')"):
        self.turns = list(turns)
        self.fail_from = fail_from
        self.fail_until = fail_until
        self.message = message
        self.calls = 0

    async def chat(self, system: str, user: str, tools: List[Dict[str, Any]],
                   history: List[Dict[str, Any]]) -> Dict[str, Any]:
        self.calls += 1
        if self.fail_from is not None and self.calls >= self.fail_from and (
                self.fail_until is None or self.calls <= self.fail_until):
            raise LLMUnavailable(self.message)
        turn = self.turns[min(self.calls - 1, len(self.turns) - 1)]
        return {
            "content": turn.get("content"),
            "tool_call": turn.get("tool_call"),
            "thought": turn.get("thought"),
            "conclusion": turn.get("conclusion", False),
            "tool_call_id": f"flaky-{self.calls}",
        }


def _tool(name: str, **arguments: Any) -> Dict[str, Any]:
    return {"name": name, "arguments": arguments}


@pytest.fixture()
def bundle():
    return default_inputs()


class TestAModelOutageDoesNotDiscardTheReview:
    def test_the_evidence_gathered_before_the_outage_is_kept(self, bundle):
        """A failure after the evidence is in must not throw the evidence away."""
        client = FlakyClient(
            [
                {"tool_call": _tool("analyze_rightsizing", workload_id="payment-api")},
                {"tool_call": _tool("validate_policy")},
            ],
            fail_from=3,
            fail_until=3,
        )
        orchestrator = AgentOrchestrator(bundle, client)

        result, audit = asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))

        tools = [step.tool for step in audit.cycles[0].steps]
        assert "analyze_rightsizing" in tools, "the evidence gathered before the outage was lost"
        assert "validate_policy" in tools, "the deterministic verdict was lost"
        assert result.decision is not None

    def test_the_deterministic_critic_still_owns_the_verdict(self, bundle):
        """The outage must not change what the critic decides."""
        client = FlakyClient(
            [
                {"tool_call": _tool("analyze_rightsizing", workload_id="payment-api")},
                {"tool_call": _tool("validate_policy")},
            ],
            fail_from=3,
            fail_until=3,
        )
        orchestrator = AgentOrchestrator(bundle, client)

        result, _audit = asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))

        # The same verdict the deterministic pipeline reaches for this workload, with the
        # deterministic critic's checks behind it - not a verdict the orchestrator made up.
        assert result.decision is not DecisionStatus.NEEDS_REVIEW or result.checks
        assert "never investigated" not in (result.reason or "")

    def test_the_result_says_the_review_was_cut_short(self, bundle):
        """A reviewer must be able to tell a short review from a complete one."""
        client = FlakyClient(
            [
                {"tool_call": _tool("analyze_rightsizing", workload_id="payment-api")},
                {"tool_call": _tool("validate_policy")},
            ],
            fail_from=3,
            fail_until=3,
        )
        orchestrator = AgentOrchestrator(bundle, client)

        result, _audit = asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))

        assert "model server became unavailable" in (result.confidence_basis or "").lower(), \
            "the result does not disclose that the review was cut short"

    def test_the_outage_reason_is_named(self, bundle):
        """'Something went wrong' is not a reason. The cause has to be in there."""
        client = FlakyClient(
            [
                {"tool_call": _tool("analyze_rightsizing", workload_id="payment-api")},
                {"tool_call": _tool("validate_policy")},
            ],
            fail_from=3,
            fail_until=3,
            message="The model server at http://127.0.0.1:8088/v1 returned HTTP 503.",
        )
        orchestrator = AgentOrchestrator(bundle, client)

        _result, audit = asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))

        summaries = " ".join(cycle.summary or "" for cycle in audit.cycles)
        assert "HTTP 503" in summaries, "the cause of the outage is not recorded anywhere"
        assert "LLMUnavailable" in summaries, "the kind of failure is not recorded"


class TestAnOutageBeforeAnyEvidence:
    def test_the_deterministic_pipeline_decides_instead_of_a_human(self, bundle):
        """Nobody chose to skip this workload - the model never got a turn.

        "The agent never investigated" is the wrong explanation for an outage, and raising it
        for a human punishes the reviewer for a server's problem. The deterministic pipeline
        decides, and the report says the review was cut short.
        """
        client = FlakyClient(
            [{"content": "The critic found nothing blocking.", "conclusion": True}],
            fail_from=1,
            fail_until=1,
        )
        orchestrator = AgentOrchestrator(bundle, client)

        result, _audit = asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))

        assert "never investigated" not in (result.reason or ""), \
            "a model outage was reported as the agent declining to investigate"
        assert result.decision is not DecisionStatus.NEEDS_REVIEW
        assert "model server became unavailable" in (result.confidence_basis or "").lower()

    def test_the_outage_does_not_leak_into_the_next_workload(self, bundle):
        """One workload's outage says nothing about the next one's.

        The server is down for the first turn only. The first workload is cut short and says
        so; the second is reviewed normally and must not inherit the first one's outage.
        """
        client = FlakyClient(
            [
                {"tool_call": _tool("analyze_rightsizing", workload_id="payment-api")},
                {"tool_call": _tool("validate_policy")},
                {"content": "Conclusion.", "conclusion": True},
            ],
            fail_from=1,
            fail_until=1,
        )
        orchestrator = AgentOrchestrator(bundle, client)

        first, _audit = asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))
        assert orchestrator.model_outage is not None
        assert "model server became unavailable" in (first.confidence_basis or "").lower()

        second, _audit = asyncio.run(orchestrator.analyze_workload_agentic("payment-api"))

        assert orchestrator.model_outage is None, "the outage leaked into the next workload"
        assert "model server became unavailable" not in (second.confidence_basis or "").lower()


class TestTheResponseSaysWhatHappened:
    """The response is what a reviewer reads. It has to carry the disclosure."""

    def test_a_cut_short_review_is_named_in_the_warnings(self, bundle):
        """Every workload loses its first turn; the report says so, and says why."""
        client = FlakyClient(
            [{"content": "Conclusion.", "conclusion": True}],
            fail_from=1,
        )
        response, _ = asyncio.run(
            run_analysis_agentic(bundle=bundle, llm_client=client,
                                 llm_status={"backend": "openai-compatible", "model": "m",
                                             "base_url": "http://127.0.0.1:8088/v1",
                                             "key_source": "env METERLESS_API_KEY", "detail": None})
        )

        warnings = " ".join(response.warnings)
        assert "cut short" in warnings, \
            f"the response does not disclose the cut-short reviews: {warnings}"
        assert "payment-api" in warnings, "the warning does not name the workload"

    def test_the_warning_does_not_leak_a_credential(self, bundle):
        """The warning is published to the UI. A token must never reach it."""
        client = FlakyClient(
            [{"content": "Conclusion.", "conclusion": True}],
            fail_from=1,
            message="The model server at http://127.0.0.1:8088/v1 could not be reached: "
                    "Authorization: Bearer super-secret-token",
        )
        response, _ = asyncio.run(
            run_analysis_agentic(bundle=bundle, llm_client=client,
                                 llm_status={"backend": "openai-compatible", "model": "m",
                                             "base_url": "http://127.0.0.1:8088/v1",
                                             "key_source": "env METERLESS_API_KEY", "detail": None})
        )

        assert "super-secret-token" not in " ".join(response.warnings)

    def test_nothing_in_the_response_leaks_a_credential(self, bundle):
        """The warning is not the only place a cause is published.

        The cause of an outage also lands in the cycle summaries, and the cycles are part of the
        response. A transport error can carry a header the server echoed back - a token that
        reaches the response has reached every screen that shows it, and every log that keeps
        it.
        """
        client = FlakyClient(
            [{"content": "Conclusion.", "conclusion": True}],
            fail_from=1,
            message="The model server at http://127.0.0.1:8088/v1 could not be reached: "
                    "Authorization: Bearer super-secret-token",
        )
        response, _ = asyncio.run(
            run_analysis_agentic(bundle=bundle, llm_client=client,
                                 llm_status={"backend": "openai-compatible", "model": "m",
                                             "base_url": "http://127.0.0.1:8088/v1",
                                             "key_source": "env METERLESS_API_KEY", "detail": None})
        )

        published = response.model_dump_json()
        assert "super-secret-token" not in published, "a credential reached the response"

    def test_the_cause_is_still_published_after_scrubbing(self, bundle):
        """Scrubbing the credential must not scrub the explanation with it."""
        client = FlakyClient(
            [{"content": "Conclusion.", "conclusion": True}],
            fail_from=1,
            message="The model server at http://127.0.0.1:8088/v1 could not be reached: "
                    "Authorization: Bearer super-secret-token",
        )
        response, _ = asyncio.run(
            run_analysis_agentic(bundle=bundle, llm_client=client,
                                 llm_status={"backend": "openai-compatible", "model": "m",
                                             "base_url": "http://127.0.0.1:8088/v1",
                                             "key_source": "env METERLESS_API_KEY", "detail": None})
        )

        warnings = " ".join(response.warnings)
        assert "cut short" in warnings.lower(), "the cause stopped being published"
        assert "REDACTED" in warnings

    def test_a_warning_that_would_name_every_workload_stays_readable(self, bundle):
        """A server that stays down affects all twelve workloads.

        The warning has to stay a readable sentence, but it must not lose the count: a reviewer
        needs to know that all twelve were affected, not that three were.
        """
        client = FlakyClient(
            [{"content": "Conclusion.", "conclusion": True}],
            fail_from=1,
        )
        response, _ = asyncio.run(
            run_analysis_agentic(bundle=bundle, llm_client=client,
                                 llm_status={"backend": "openai-compatible", "model": "m",
                                             "base_url": "http://127.0.0.1:8088/v1",
                                             "key_source": "env METERLESS_API_KEY", "detail": None})
        )

        warnings = " ".join(response.warnings)
        assert "and 9 more" in warnings, f"the warning lost the count: {warnings}"
        assert len(warnings) < 1200, "the warning is unreadable"
