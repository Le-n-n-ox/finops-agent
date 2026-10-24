"""Parity between the two review engines, and the routing the graph exists for.

The graph is not allowed to be a second implementation: if `REVIEW_ENGINE=langgraph` and
`REVIEW_ENGINE=native` disagree about a workload, the graph is wrong, however pretty it looks.
"""
from __future__ import annotations

import asyncio

import pytest

from app.services import agent_orchestrator as module
from app.services.agent_orchestrator import AgentOrchestrator, review_engine
from app.services.orchestrator import default_inputs
from app.services.simulated_llm import SimulatedLLMClient


@pytest.fixture()
def bundle():
    return default_inputs()


def _run(workload_id: str, bundle):
    from app.services.orchestrator import default_inputs as _defaults

    orchestrator = AgentOrchestrator(bundle, SimulatedLLMClient())
    return asyncio.run(orchestrator.analyze_workload_agentic(workload_id))


def test_an_unknown_engine_setting_falls_back_to_native(monkeypatch):
    monkeypatch.setenv("REVIEW_ENGINE", "langgraphh")  # typo
    assert review_engine() == "native"
    monkeypatch.setenv("REVIEW_ENGINE", "langgraph")
    assert review_engine() == "langgraph"


class TestParity:
    def test_both_engines_agree_on_every_workload(self, bundle, monkeypatch):
        """Same decisions, same cycles, same numbers - only the wiring differs."""
        monkeypatch.setenv("REVIEW_ENGINE", "native")
        native = {spec.name: _run(spec.name, bundle) for spec in bundle.services}

        monkeypatch.setenv("REVIEW_ENGINE", "langgraph")
        graph = {spec.name: _run(spec.name, bundle) for spec in bundle.services}

        for name, (native_result, native_audit) in native.items():
            graph_result, graph_audit = graph[name]
            assert graph_result.decision == native_result.decision, name
            assert graph_result.monthly_savings_estimate_usd == native_result.monthly_savings_estimate_usd, name
            assert graph_result.confidence_score == native_result.confidence_score, name
            assert [c.role for c in graph_audit.cycles] == [c.role for c in native_audit.cycles], name
            assert [o.code for o in graph_result.objections] == [o.code for o in native_result.objections], name

    def test_the_graph_keeps_the_same_proposal_numbers(self, bundle, monkeypatch):
        monkeypatch.setenv("REVIEW_ENGINE", "native")
        native_result, _ = _run("docs-renderer", bundle)
        monkeypatch.setenv("REVIEW_ENGINE", "langgraph")
        graph_result, _ = _run("docs-renderer", bundle)

        for result in (native_result, graph_result):
            current, proposed = result.proposal.current, result.proposal.proposed
            assert proposed.memory_request_mib == current.memory_request_mib
            assert proposed.cpu_request_millicores < current.cpu_request_millicores


class TestRouting:
    def test_a_blocking_objection_routes_through_revision(self, bundle, monkeypatch):
        monkeypatch.setenv("REVIEW_ENGINE", "langgraph")
        _, audit = _run("docs-renderer", bundle)

        assert [c.role for c in audit.cycles] == ["proposer", "critic", "revision", "judge"]

    def test_a_clean_workload_skips_revision(self, bundle, monkeypatch):
        monkeypatch.setenv("REVIEW_ENGINE", "langgraph")
        _, audit = _run("catalog-api", bundle)

        assert [c.role for c in audit.cycles] == ["proposer", "critic", "judge"]

    def test_a_workload_with_nothing_to_change_skips_revision(self, bundle, monkeypatch):
        monkeypatch.setenv("REVIEW_ENGINE", "langgraph")
        _, audit = _run("payment-api", bundle)

        assert [c.role for c in audit.cycles] == ["proposer", "critic", "judge"]


class TestFallback:
    def test_a_broken_graph_falls_back_to_the_native_loop(self, bundle, monkeypatch):
        """A graph failure must cost the run its wiring, not the workload its review."""
        monkeypatch.setenv("REVIEW_ENGINE", "langgraph")

        def explode(*_args, **_kwargs):
            raise RuntimeError("graph is on fire")

        monkeypatch.setattr("app.services.review_graph.run_review_graph", explode)

        result, audit = _run("docs-renderer", bundle)

        assert result.decision.name == "APPROVED"
        assert [c.role for c in audit.cycles] == ["proposer", "critic", "revision", "judge"]
