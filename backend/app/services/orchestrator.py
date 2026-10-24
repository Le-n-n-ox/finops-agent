"""Developer 2 — load input -> build_proposals -> critic per proposal -> aggregate -> report.

Every agent step goes through app.integrations.meterless_runner.get_runner(), so Meterless can be swapped in
without touching business logic. The Dev 1 entry points are resolved lazily so this module imports cleanly
even while they are still being written.

There is ONE reasoning path now: the Proposer -> Critic -> Judge cycle, backed by a live
OpenAI-compatible model server when one is reachable. The deterministic optimizer + critic stay
as the safety model (they own every final decision, and the `validate_policy` tool calls them),
but they are no longer a selectable alternative to the agent cycle.
"""
from __future__ import annotations

import asyncio
import os
import hashlib
import logging
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable, Any, Dict

from app.integrations.meterless_runner import AgentRunner, get_runner
from app.models.schemas import (
    AgentAuditLog,
    AnalysisResponse,
    AnalysisSummary,
    CriticPolicy,
    DecisionStatus,
    EventWindow,
    InputBundle,
    OptimizationProposal,
    UsagePoint,
    WorkloadResult,
    TopOpportunity,
)
from app.services.critic_service import evaluate
from app.services.fingerprints import fingerprint
from app.services.redaction import scrub as _scrub
from app.services.report_service import with_patch
from app.services.store import Store
from app.services.agent_orchestrator import AgentOrchestrator, deterministic_result
from app.services.validation_service import validation_from_bundle

logger = logging.getLogger(__name__)

DISCLAIMER = "Sample/illustrative data. Savings are estimates, not guaranteed bill reductions."


def _name_the_workloads(affected: dict[str, str], limit: int = 3) -> str:
    """Name the affected workloads and their causes, in a form a reader can scan.

    A model server that stays down affects every workload, and a warning that names all twelve
    is unreadable. The count is always exact, so nothing is hidden by the cap; the per-result
    disclosure names the rest.
    """
    items = list(affected.items())
    shown = "; ".join(f"{name} ({reason})" for name, reason in items[:limit])
    if len(items) > limit:
        shown += f"; and {len(items) - limit} more"
    return shown


def _short_reason(exc: BaseException, limit: int = 200) -> str:
    """One line naming why a workload fell back, safe to publish in the response.

    The text can be anything the failing code put into the exception, and this string ends up in
    the API response, so it is flattened to one line, truncated, and scrubbed of anything that
    looks like a credential. A transport error that echoes a request header must not carry the
    token into the UI.
    """
    text = " ".join(str(exc).split()) or type(exc).__name__
    text = _scrub(text)
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return f"{type(exc).__name__}: {text}"

# The shape of the LLM status the API publishes. The keys match app.integrations.llm_client.LLMStatus.
LLM_STATUS_KEYS = ("backend", "model", "base_url", "key_source", "detail")


def _status_of(status: Any) -> Dict[str, Any]:
    """Normalise an LLM status into the five keys the API publishes."""
    data = dict(status or {})
    return {key: data.get(key) for key in LLM_STATUS_KEYS}


def _simulated_status(detail: str) -> Dict[str, Any]:
    return {"backend": "simulated", "model": None, "base_url": None, "key_source": None, "detail": detail}


def _status_from_client(client: Any) -> Dict[str, Any]:
    """Derive a status from a client that carries no status of its own."""
    own = getattr(client, "status", None)
    if isinstance(own, dict) and own.get("backend"):
        return _status_of(own)

    config = (getattr(client, "config", None) or getattr(client, "_config", None)
              or getattr(client, "llm_config", None))
    base_url = getattr(config, "base_url", None)
    if base_url:
        return {
            "backend": "openai-compatible",
            "model": getattr(config, "model", None),
            "base_url": base_url,
            "key_source": getattr(config, "key_source", None),
            "detail": None,
        }
    return _simulated_status("The deterministic stand-in answered the agent turns; no model was called.")


def resolve_llm() -> tuple[Any, Dict[str, Any]]:
    """The model client for the agent cycle, and a status describing it.

    `app.integrations.llm_client` owns credential discovery and the reachability probe: it returns
    the live OpenAI-compatible client when a model server answered, and the deterministic
    stand-in otherwise. The status travels with the client so the API can say out loud which one
    ran - a reviewer who believes a model was called reads a different kind of trust into the
    objections than the code supports.
    """
    try:
        from app.integrations.llm_client import get_llm_client
    except ImportError as exc:  # the client module is not in place yet
        from app.services.simulated_llm import SimulatedLLMClient
        return SimulatedLLMClient(), _simulated_status(f"The model client is unavailable: {exc}")

    resolved = get_llm_client()
    if isinstance(resolved, tuple) and len(resolved) == 2:
        client, status = resolved
    else:  # a client without a status: derive one so the response can still be honest
        client, status = resolved, None
    if status:
        return client, _status_of(status)
    # A client that carries no status of its own: derive one. Without this the response would
    # publish a blank backend, and "we do not know which reasoner ran" would read as
    # "the deterministic stand-in ran".
    return client, _status_from_client(client)


def llm_status_payload() -> Dict[str, Any]:
    """The status of the model server, for GET /api/llm/status.

    `detail` says WHY the deterministic stand-in was used, so the UI can say it out loud rather
    than implying a model ran. The client is selected here, so the status describes the same
    client the next analysis will use.
    """
    try:
        _client, status = resolve_llm()
        return _status_of(status)
    except Exception:  # noqa: BLE001 - the status must never take the page down
        pass

    try:
        from app.integrations.llm_client import llm_status
        return _status_of(llm_status())
    except Exception:  # noqa: BLE001
        return _simulated_status("The model server has not been contacted yet.")


def default_inputs() -> InputBundle:
    from app.services import data_loader

    getter = getattr(data_loader, "get_inputs", None)  # Dev 1: DATA_SOURCE=local|zetaris
    return getter() if getter else data_loader.load_inputs()


def default_proposals(bundle: InputBundle, now: datetime | None = None) -> list[OptimizationProposal]:
    from app.services.optimizer_service import build_proposals

    return build_proposals(bundle, now=now)


def _chart_data(workload_id: str, bundle: InputBundle, now: datetime) -> dict:
    """Optional UI fields. Only included when the shared schema defines them."""
    extra: dict = {}
    if "usage_series" in WorkloadResult.model_fields:
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        cutoff = now - timedelta(days=bundle.policy.optimizer.window_days)
        rows = sorted((r for r in bundle.usage_rows if r.service == workload_id and cutoff <= r.timestamp <= now),
                      key=lambda r: r.timestamp)
        extra["usage_series"] = [UsagePoint(t=r.timestamp, cpu=r.cpu_millicores, mem=r.memory_mib) for r in rows]
    if "events" in WorkloadResult.model_fields:
        extra["events"] = [
            EventWindow(name=e.name, start_at=e.start_at, end_at=e.end_at, risk=e.risk)
            for e in bundle.events if workload_id in e.services
        ]
    return extra


def apply_policy(bundle: InputBundle, policy: CriticPolicy | None) -> InputBundle:
    """Use a saved safety-policy override (PUT /api/policies) instead of the one in policy.yaml."""
    return bundle if policy is None else bundle.model_copy(update={"policy": bundle.policy.model_copy(update={"critic": policy})})


def run_analysis_with_bundle(
    now: datetime | None = None,
    *,
    runner: AgentRunner | None = None,
    inputs_fn: Callable[[], InputBundle] | None = None,
    proposals_fn: Callable[..., list[OptimizationProposal]] | None = None,
    policy: CriticPolicy | None = None,
) -> tuple[AnalysisResponse, InputBundle]:
    runner = runner or get_runner()
    bundle: InputBundle = apply_policy(runner.run("collector", inputs_fn or default_inputs), policy)
    specs = {sp.name: sp for sp in bundle.services}
    now = now or bundle.policy.simulation_now or datetime.now(timezone.utc)

    proposals = runner.run("optimizer", proposals_fn or default_proposals, bundle, now=now)

    results: list[WorkloadResult] = []
    for proposal in proposals:
        judged = runner.run("critic", evaluate, proposal, bundle, now)
        patched = runner.run("report", with_patch, judged, specs.get(proposal.workload_id))
        extra = _chart_data(proposal.workload_id, bundle, now)
        results.append(patched.model_copy(update=extra) if extra else patched)

    results.sort(key=lambda result: -(result.proposal.priority_score or 0.0))
    top_n = bundle.policy.critic.top_n_findings
    top_opportunities = [TopOpportunity(
        workload_id=result.workload_id,
        monthly_savings_usd=result.monthly_savings_estimate_usd,
        priority_score=result.proposal.priority_score or 0.0,
        confidence_score=result.proposal.confidence.score if result.proposal.confidence else 0.0,
        risk_level=result.risk_level,
    ) for result in results if result.decision is DecisionStatus.APPROVED
        and result.proposal.proposed is not None][:top_n]

    summary = AnalysisSummary(
        workloads_evaluated=len(results),
        approved=sum(r.decision is DecisionStatus.APPROVED for r in results),
        deferred=sum(r.decision is DecisionStatus.DEFERRED for r in results),
        rejected=sum(r.decision is DecisionStatus.REJECTED for r in results),
        needs_review=sum(r.decision is DecisionStatus.NEEDS_REVIEW for r in results),
        no_change=sum(r.decision is DecisionStatus.NO_CHANGE for r in results),
        estimated_monthly_savings_usd=round(
            sum(r.monthly_savings_estimate_usd for r in results if r.decision is DecisionStatus.APPROVED), 2),
    )

    warnings = [DISCLAIMER]
    if bundle.policy.simulation_now:
        warnings.append(f"Demo clock fixed at {bundle.policy.simulation_now.isoformat()}.")

    payload: dict = dict(
        analysis_id=f"ANL-{now:%Y%m%d%H%M%S}-{uuid.uuid4().hex[:6]}",
        generated_at=now,
        mode="demo" if bundle.policy.simulation_now else os.getenv("DATA_SOURCE", "local"),
        summary=summary,
        results=results,
        warnings=warnings,
        policy_version=bundle.policy.critic.version,
        rule_version=bundle.policy.critic.rule_version,
        input_fingerprint="sha256:" + hashlib.sha256(bundle.model_dump_json().encode("utf-8")).hexdigest(),
        top_n_findings=top_n,
        top_opportunities=top_opportunities,
    )
    if "input_issues" in AnalysisResponse.model_fields:
        payload["input_issues"] = bundle.issues
    if "data_health" in AnalysisResponse.model_fields:
        # The same validation the /api/validation endpoint returns, computed from the bundle that
        # produced this analysis. The UI shows metric completeness and freshness per workload, so
        # a reviewer can see which recommendations rest on thin data.
        payload["data_health"] = validation_from_bundle(bundle)
    return AnalysisResponse(**payload), bundle


async def run_analysis(now: datetime | None = None, **kwargs) -> AnalysisResponse:
    """
    The primary entry point for analysis. Uses the AgentOrchestrator to perform a deep,
    investigative review of all workloads through the Proposer -> Critic -> Judge cycle.
    """
    response, _ = await run_analysis_agentic(now=now, **kwargs)
    return response


def _workload_concurrency(workloads: int) -> int:
    """How many workload reviews may be in flight at once.

    The model server is the bottleneck here, not this process: a few turns in flight hides most
    of the round-trip time, while too many just queues requests behind the server's own limit and
    trades latency for timeouts. `FINOPS_WORKLOAD_CONCURRENCY=1` restores one-at-a-time behaviour.
    """
    try:
        configured = int(os.getenv("FINOPS_WORKLOAD_CONCURRENCY", "4"))
    except ValueError:
        configured = 4
    return max(1, min(configured, max(1, workloads)))


async def run_analysis_agentic(
    now: datetime | None = None,
    llm_client: Any = None,
    llm_status: Dict[str, Any] | None = None,
    on_workload: Callable[[WorkloadResult], None] | None = None,
    **kwargs
) -> tuple[AnalysisResponse, InputBundle]:
    """
    Run the agentic reasoning loop for all workloads.

    Each workload goes through the full Proposer -> Critic -> Judge cycle. The agent's results ARE
    the results: they are aggregated here, not discarded in favour of a second deterministic run.
    A per-workload failure falls back to the deterministic pipeline for that workload only.

    The model client is resolved from the live model server when one is reachable. When it is not,
    the deterministic stand-in answers and the response says so: the UI must never imply a
    language model ran when it did not.

    `on_workload` is called with each workload's result as it is finished. A full review of
    every workload is a multi-turn conversation with the model server for each one, so the run
    takes minutes - and a caller that cannot see it progressing has no way to tell a slow run
    from a stuck one.
    """
    bundle = kwargs.get("bundle") or default_inputs()
    now = now or bundle.policy.simulation_now or datetime.now(timezone.utc)

    if llm_client is None:
        llm_client, llm_status = resolve_llm()
    elif llm_status is None:
        llm_status = _status_from_client(llm_client)

    specs = {spec.name: spec for spec in bundle.services}
    results: list[WorkloadResult] = []
    audits: list[AgentAuditLog | None] = [None] * len(bundle.services)
    fallbacks: dict[str, str] = {}
    degraded: dict[str, str] = {}

    # One workload's review is a long conversation with the model server (up to ten proposer
    # turns, then the critic and the judge). The workloads share nothing but read-only inputs,
    # so running them in turn made the whole analysis pay every workload's latency one after
    # another. They now run side by side, bounded, because the model server is the scarce
    # resource and unbounded fan-out would just queue requests behind its own limit.
    #
    # Each review gets its own AgentOrchestrator: that object carries per-workload state - the
    # toolbox bound to one workload, and the model-outage flag - and two reviews sharing one
    # would let a workload validate another workload's proposal. The client is shared, and it
    # is safe to share: httpx pools connections and every request is independent.
    limit = asyncio.Semaphore(_workload_concurrency(len(bundle.services)))

    async def review(index: int, spec) -> None:
        async with limit:
            agent = AgentOrchestrator(bundle, llm_client, store=kwargs.get("store"))
            try:
                res, audit = await agent.analyze_workload_agentic(spec.name)
                audits[index] = audit
                # Attach the validated patch exactly as the deterministic pipeline does.
                patched = with_patch(res, specs.get(spec.name))
                if agent.model_outage:
                    # The model server went away mid-review. The cycle still produced a verdict, but
                    # it is a shorter review than the others, and the report has to say so.
                    degraded[spec.name] = _scrub(agent.model_outage)
            except Exception as exc:  # noqa: BLE001 - one bad workload must not sink the whole analysis
                # Fail-safe: if the agent crashes, fallback to the deterministic pipeline for this
                # workload. The cause is logged and published: a silent fallback reads like a review
                # that happened, and a reviewer has to be able to tell the difference.
                #
                # The traceback is scrubbed before it is logged. The exception's message can carry a
                # header the server echoed back, and a log file is read by people who should not be
                # holding a token.
                logger.error("The agent cycle failed for %s; the deterministic critic decided it.\n%s",
                             spec.name, _scrub(traceback.format_exc()))
                patched = with_patch(deterministic_result(bundle, spec.name, now), specs.get(spec.name))
                fallbacks[spec.name] = _short_reason(exc)
            # The usage chart and event band are UI-only fields. The agent path must attach them too,
            # or "Agent cycle" mode renders an empty chart where the pipeline shows 720 points.
            extra = _chart_data(spec.name, bundle, now)
            finished = patched.model_copy(update=extra) if extra else patched
            results.append(finished)
            if on_workload is not None:
                # Reported as it is finished, so a caller can show the run progressing. A failure
                # here must not sink the analysis: the progress callback is a convenience.
                try:
                    on_workload(finished)
                except Exception:  # noqa: BLE001 - a broken progress callback is not a broken analysis
                    logger.warning("The progress callback failed for %s.", spec.name, exc_info=True)

    await asyncio.gather(*(review(index, spec) for index, spec in enumerate(bundle.services)))
    audits = [audit for audit in audits if audit is not None]

    results.sort(key=lambda result: -(result.proposal.priority_score or 0.0))
    return _aggregate(results, bundle, now, llm_status=llm_status, fallbacks=fallbacks,
                      degraded=degraded), bundle


def _aggregate(results: list[WorkloadResult], bundle: InputBundle, now: datetime,
               llm_status: Dict[str, Any] | None = None,
               fallbacks: dict[str, str] | None = None,
               degraded: dict[str, str] | None = None) -> AnalysisResponse:
    """Turn a list of judged results into the AnalysisResponse the UI consumes.

    `llm_status` says which model actually answered the agent's turns. It travels with the
    response so the UI can name the model, or say plainly that none ran.
    """
    summary = AnalysisSummary(
        workloads_evaluated=len(results),
        approved=sum(r.decision is DecisionStatus.APPROVED for r in results),
        deferred=sum(r.decision is DecisionStatus.DEFERRED for r in results),
        rejected=sum(r.decision is DecisionStatus.REJECTED for r in results),
        needs_review=sum(r.decision is DecisionStatus.NEEDS_REVIEW for r in results),
        no_change=sum(r.decision is DecisionStatus.NO_CHANGE for r in results),
        estimated_monthly_savings_usd=round(
            sum(r.monthly_savings_estimate_usd for r in results if r.decision is DecisionStatus.APPROVED), 2),
    )

    status = _status_of(llm_status)
    warnings = [DISCLAIMER]
    if bundle.policy.simulation_now:
        warnings.append(f"Demo clock fixed at {bundle.policy.simulation_now.isoformat()}.")
    if status.get("backend") != "openai-compatible":
        detail = status.get("detail") or "The model server was not reachable."
        warnings.append(f"No live language model answered the agent turns. {detail}")
    if fallbacks:
        # Name the cause, not just the workload. "The agent cycle failed for payment-api" tells a
        # reviewer nothing; "the model server returned HTTP 503" tells them whether to retry.
        warnings.append(
            "The agent cycle failed for " + _name_the_workloads(fallbacks) +
            "; the deterministic critic decided those workloads.")
    if degraded:
        # A workload whose review was cut short by a model outage. It still has a verdict, but a
        # shorter review than its neighbours, and the report has to say so.
        warnings.append(
            "The agent review was cut short for " + _name_the_workloads(degraded) +
            "; the deterministic critic decided those workloads.")

    top_n = bundle.policy.critic.top_n_findings
    top_opportunities = [TopOpportunity(
        workload_id=result.workload_id,
        monthly_savings_usd=result.monthly_savings_estimate_usd,
        priority_score=result.proposal.priority_score or 0.0,
        confidence_score=result.confidence_score or (
            result.proposal.confidence.score if result.proposal.confidence else 0.0),
        risk_level=result.risk_level,
    ) for result in results if result.decision is DecisionStatus.APPROVED
        and result.proposal.proposed is not None][:top_n]

    payload: dict = dict(
        analysis_id=f"ANL-{now:%Y%m%d%H%M%S}-{uuid.uuid4().hex[:6]}",
        generated_at=now,
        # The agent cycle is the only reasoning path now, so the response says so. The demo clock
        # is disclosed in the warnings above rather than by hijacking this field.
        mode="agent",
        summary=summary,
        results=results,
        warnings=warnings,
        policy_version=bundle.policy.critic.version,
        rule_version=bundle.policy.critic.rule_version,
        input_fingerprint="sha256:" + hashlib.sha256(bundle.model_dump_json().encode("utf-8")).hexdigest(),
        top_n_findings=top_n,
        top_opportunities=top_opportunities,
        llm_backend=status.get("backend") or "simulated",
        llm_model=status.get("model"),
        llm_base_url=status.get("base_url"),
    )
    if "input_issues" in AnalysisResponse.model_fields:
        payload["input_issues"] = bundle.issues
    if "data_health" in AnalysisResponse.model_fields:
        payload["data_health"] = validation_from_bundle(bundle)
    return AnalysisResponse(**payload)


async def run_and_record(store: Store, now: datetime | None = None, *, mode: str = "agent", **kwargs) -> AnalysisResponse:
    """Run the analysis with the saved policy, then persist the report + immutable decision snapshots.

    `mode` is accepted for call-site compatibility and is IGNORED: the agent cycle is the only
    reasoning path. The deterministic optimizer + critic remain the safety model behind every
    final decision (the `validate_policy` tool calls them), and the adversarial phase can only
    downgrade a recommendation - it can never approve, reject or change a number.
    """
    response, bundle = await _run_agentic_with_policy(store, now, **kwargs)
    store.save_report(response, {r.workload_id: fingerprint(r.workload_id, bundle) for r in response.results}, bundle.policy.critic.version)
    return response


async def _run_agentic_with_policy(store: Store, now: datetime | None = None, **kwargs) -> tuple[AnalysisResponse, InputBundle]:
    """Run the agentic cycle with the saved safety policy applied."""
    inputs_fn = kwargs.get("inputs_fn") or default_inputs
    bundle = apply_policy(inputs_fn(), store.get_policy())
    llm_client = kwargs.get("llm_client")
    llm_status = kwargs.get("llm_status")
    if llm_client is None:
        llm_client, llm_status = resolve_llm()
    response, bundle = await run_analysis_agentic(now=now, llm_client=llm_client, llm_status=llm_status,
                                                  bundle=bundle, store=store,
                                                  on_workload=kwargs.get("on_workload"))
    return response, bundle
