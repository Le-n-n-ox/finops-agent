"""The review cycle as a LangGraph state machine (`REVIEW_ENGINE=langgraph`).

Why this exists: the phases are the same four calls either way, but signing the cycle in one
`analyze_workload_agentic` body hides the shape of it. As a graph the shape is explicit - nodes are
phases, the conditional edge is the revision decision, the state is the audit log - and a reviewer
can see the loop rather than infer it from reading an async function top to bottom.

What it is not: a second implementation. Every node calls the orchestrator's own phase method, the
decision still comes from the deterministic critic, and nothing here may change a number or a
verdict. `test_review_engine_parity.py` runs both engines over the same fixture and fails if they
disagree about any workload's decision.

The dependency is optional at import time and required at run time: if `langgraph` is missing, the
orchestrator falls back to the native sequence and logs why, rather than failing the review.
"""
from __future__ import annotations

from typing import Any, NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph


class ReviewState(TypedDict):
    """The graph's state.

    The three inputs are required; the phase outputs are `NotRequired` because a node only exists
    once the node before it has written them. They are read with `.get()`, which is also what makes
    the routing honest: a missing key is `None`, not a KeyError halfway through a review.
    """

    workload_id: str
    lessons: list[str]
    audit_log: Any

    proposer: NotRequired[Any]
    critic: NotRequired[Any]
    formal: NotRequired[Any]
    revision: NotRequired[Any]
    revised: NotRequired[bool]
    judge: NotRequired[Any]


def build_review_graph(orchestrator: Any):
    """Compile the four-phase graph around one orchestrator.

    The orchestrator owns the phases (and the bundle, the toolbox, the client); the graph owns the
    order and the one branch. Nodes mutate the audit log they are handed, which is the same object
    the caller keeps, so the evidence trail is identical to the native path's.
    """

    async def proposer(state: ReviewState) -> dict:
        cycle = await orchestrator._run_proposer(state["audit_log"], state["workload_id"], state["lessons"])
        state["audit_log"].cycles.append(cycle)
        # The policy verdict normally arrives from the proposer's `validate_policy` call; if the
        # model never called it, the orchestrator runs the deterministic critic over the same
        # proposal. Either way the critic phase needs a verdict to argue against.
        return {"proposer": cycle, "formal": orchestrator._get_last_policy_result(state["audit_log"])}

    async def critic(state: ReviewState) -> dict:
        cycle = await orchestrator._run_critic(state["audit_log"], state["workload_id"],
                                               state.get("proposer"), state.get("formal"))
        state["audit_log"].cycles.append(cycle)
        return {"critic": cycle}

    async def revision(state: ReviewState) -> dict:
        cycle, revised = await orchestrator._run_revision(
            state["workload_id"], state.get("critic"), state.get("formal"), state["audit_log"].steps)
        if cycle is not None:
            state["audit_log"].cycles.append(cycle)
        update: dict = {"revision": cycle, "revised": revised is not None}
        if revised is not None:
            update["formal"] = revised
        return update

    async def judge(state: ReviewState) -> dict:
        critic_cycle = state.get("critic")
        revision_cycle = state.get("revision")
        if critic_cycle is None:
            raise RuntimeError("The judge ran before the critic produced a cycle.")
        if state.get("revised") and revision_cycle is not None:
            # The judge weighs the objections that survive the revision, not the retired ones.
            critic_cycle = critic_cycle.model_copy(update={"objections": revision_cycle.objections})
        cycle = await orchestrator._run_judge(state["workload_id"], state.get("proposer"), critic_cycle,
                                              state.get("formal"), revision_cycle)
        state["audit_log"].cycles.append(cycle)
        return {"judge": cycle}

    def route(state: ReviewState) -> str:
        # One edge, and it is the whole point of the loop: a blocking objection the change could
        # answer sends the review back to the proposer; everything else goes to the judge.
        return "revision" if orchestrator._needs_revision(state.get("critic"), state.get("formal")) else "judge"

    graph = StateGraph(ReviewState)
    graph.add_node("proposer", proposer)
    graph.add_node("critic", critic)
    graph.add_node("revision", revision)
    graph.add_node("judge", judge)

    graph.add_edge(START, "proposer")
    graph.add_edge("proposer", "critic")
    graph.add_conditional_edges("critic", route, {"revision": "revision", "judge": "judge"})
    graph.add_edge("revision", "judge")
    graph.add_edge("judge", END)
    return graph.compile()


async def run_review_graph(orchestrator: Any, workload_id: str, audit_log: Any,
                           lessons: list[str]) -> Any:
    """Run the graph and return the same ReviewRun the native sequence returns."""
    from app.services.agent_orchestrator import ReviewRun

    compiled = build_review_graph(orchestrator)
    final = await compiled.ainvoke({
        "workload_id": workload_id,
        "lessons": lessons,
        "audit_log": audit_log,
        "revised": False,
    })
    proposer, critic, formal, judge = (final.get("proposer"), final.get("critic"),
                                       final.get("formal"), final.get("judge"))
    if proposer is None or critic is None or formal is None or judge is None:
        # A phase did not run. The orchestrator falls back to the native sequence on this, which
        # is better than publishing a verdict assembled from three quarters of a review.
        raise RuntimeError("The review graph finished without running every phase.")
    return ReviewRun(
        proposer=proposer,
        critic=critic,
        formal=formal,
        revision=final.get("revision"),
        revised=bool(final.get("revised")),
        judge=judge,
    )
