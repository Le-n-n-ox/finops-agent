"""Developer 2 — Adversarial review phase (the "Critic" of Proposer -> Critic -> Judge).

The deterministic Context Critic (`critic_service`) decides the FINAL status from policy rules. This module
does something different: it red-teams the *reasoning* that produced a recommendation, before the final
decision is made, and raises typed objections the Judge must answer.

Two kinds of objection:
  * blocking   — the evidence does not support the claim (e.g. the spike is a recurring event, not a blip)
  * advisory   — worth a human's attention but not disqualifying

Every objection is grounded in a tool the agent actually called. An objection with no evidence is not raised.
This module NEVER decides; it only produces `CriticObjection` records for the Judge phase to weigh.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from app.models.schemas import (
    BusinessEvent,
    CriticObjection,
    DecisionStatus,
    InputBundle,
    OptimizationProposal,
    ToolCall,
    WorkloadResult,
)

# Objection codes are stable so a UI can group or filter them.
RECURRING_EVENT = "RECURRING_EVENT_UNMODELLED"
INCIDENT_OVERLAP = "INCIDENT_OVERLAP_IGNORED"
LOG_PRESSURE = "LOG_PRESSURE_IGNORED"
DEPENDENCY_PRESSURE = "DEPENDENCY_PRESSURE_IGNORED"
VERIFICATION_GAP = "VERIFICATION_GAP"
THIN_EVIDENCE = "THIN_EVIDENCE"


def _tool_names(steps: Iterable[ToolCall]) -> set[str]:
    return {step.tool for step in steps}


def _aware(value: datetime) -> datetime:
    """Normalize a timestamp so naive fixture values stay comparable."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _result_of(steps: Iterable[ToolCall], tool: str) -> Any:
    """Return the most recent result of `tool`, or None if it was never called."""
    for step in reversed(list(steps)):
        if step.tool == tool:
            return step.result
    return None


def _as_dicts(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    return []


def _log_is_pressure(entry: dict[str, Any]) -> bool:
    """True when a log line signals capacity pressure (OOM, throttling, eviction)."""
    text = f"{entry.get('message', '')} {entry.get('level', '')}".lower()
    return any(marker in text for marker in ("oom", "throttl", "evict", "out of memory", "killed"))


def raise_objections(
    proposal: OptimizationProposal | None,
    result: WorkloadResult | None,
    steps: list[ToolCall],
    bundle: InputBundle,
    workload_id: str,
) -> list[CriticObjection]:
    """Red-team the proposer's case for `workload_id` and return the objections worth raising."""
    objections: list[CriticObjection] = []
    called = _tool_names(steps)

    # 1. The workload sits under an UPCOMING event the proposal did not account for. An agent that
    #    only read usage numbers will happily treat an event-driven spike as a one-off. Events that
    #    already ended are history, not a reason to hold a future change: the optimizer already
    #    projects their demand multiplier, and the critic has its own event-window rule.
    now = bundle.policy.simulation_now or datetime.now(timezone.utc)
    horizon = bundle.policy.critic.risk_window_hours
    upcoming = [e for e in bundle.events
                if workload_id in e.services
                and _aware(e.end_at) >= now
                and _aware(e.start_at) <= now + timedelta(hours=horizon)]
    if upcoming:
        reasons_text = " ".join(proposal.reasons) if proposal else ""
        warnings_text = " ".join(proposal.warnings) if proposal else ""
        accounted = any(event.name in reasons_text or event.name in warnings_text for event in upcoming)
        if not accounted:
            event = max(upcoming, key=lambda e: e.expected_load_multiplier)
            objections.append(CriticObjection(
                code=RECURRING_EVENT,
                severity="blocking",
                message=(f"'{event.name}' targets this workload with an expected {event.expected_load_multiplier:g}x "
                         f"load, but the proposal does not account for it. A spike during a recurring event is "
                         f"not a one-off and must not be sized down on historical evidence alone."),
                source="business_events",
            ))

    # 2. The proposer recommended a reduction while a prior incident about that resource exists.
    if result is not None and result.decision is not DecisionStatus.REJECTED:
        for check in result.checks:
            if check.code == "PRIOR_INCIDENT_PATTERN" and check.status.value == "triggered":
                objections.append(CriticObjection(
                    code=INCIDENT_OVERLAP,
                    severity="blocking",
                    message=(f"Prior incident {check.evidence.get('incident_id')} on this workload "
                             f"({check.evidence.get('pattern')}) overlaps the proposed change. "
                             f"{check.message}"),
                    source="get_incident_history",
                ))
                break

    # 3. Logs show the container is already under pressure (OOMKilled / throttling). Reducing further
    #    on top of an OOMKill is a reliability regression, not a saving.
    if "search_logs" in called:
        for entry in _as_dicts(_result_of(steps, "search_logs")):
            if _log_is_pressure(entry):
                objections.append(CriticObjection(
                    code=LOG_PRESSURE,
                    severity="blocking",
                    message=(f"Log at {entry.get('timestamp')} reports pressure: '{entry.get('message')}'. "
                             f"Reducing requests while the container is being OOMKilled or throttled risks "
                             f"an outage."),
                    source="search_logs",
                ))
                break

    # 4. A dependency is itself under pressure, so a reduction here can push load onto a stressed upstream.
    if "get_dependencies" in called:
        dependencies = _result_of(steps, "get_dependencies")
        if isinstance(dependencies, list):
            for dependency in dependencies:
                if not isinstance(dependency, str):
                    continue
                dep_incidents = [inc for inc in bundle.incidents if inc.service == dependency]
                if dep_incidents:
                    latest = max(dep_incidents, key=lambda inc: inc.occurred_at)
                    objections.append(CriticObjection(
                        code=DEPENDENCY_PRESSURE,
                        severity="advisory",
                        message=(f"Dependency '{dependency}' has incident history "
                                 f"({latest.incident_id}: {latest.pattern}). A reduction here may move load "
                                 f"onto an upstream service that is already struggling."),
                        source="get_dependencies",
                    ))
                    break

    # 5. The proposer asserted numbers the tool outputs do not support.
    if result is not None and getattr(result, "proposal", None) is not None:
        unverified = [step for step in steps
                      if step.tool == "verify_numbers" and isinstance(step.result, dict)
                      and step.result.get("unverified_count")]
        if unverified:
            objections.append(CriticObjection(
                code=VERIFICATION_GAP,
                severity="blocking",
                message=("The proposal contains numbers that could not be traced back to a tool result. "
                         "Unverified figures must not drive a recommendation."),
                source="verify_numbers",
            ))

    # 6. The evidence base is too thin for the confidence being claimed.
    if result is not None and proposal is not None:
        samples = proposal.metrics.sample_count
        required = bundle.policy.critic.min_samples
        if samples and samples < required:
            objections.append(CriticObjection(
                code=THIN_EVIDENCE,
                severity="blocking",
                message=(f"Only {samples} usage samples back this recommendation, below the required {required}. "
                         f"The sample window is too small to distinguish a trend from noise."),
                source="get_workload_metrics",
            ))

    return objections


def judge_verdict(
    objections: list[CriticObjection],
    result: WorkloadResult | None,
) -> tuple[str, str]:
    """Weigh the objections against the deterministic result.

    Returns (verdict, rationale). The verdict never overrides a deterministic block: an objection can only
    downgrade a proposal, never upgrade a rejected or needs_review one.
    """
    blocking = [o for o in objections if o.severity == "blocking"]
    advisory = [o for o in objections if o.severity != "blocking"]
    if not blocking and not advisory:
        return "accept", "No objection survived review; the proposer's evidence stands on its own."

    decision = result.decision if result else DecisionStatus.NEEDS_REVIEW
    if decision in (DecisionStatus.REJECTED, DecisionStatus.NEEDS_REVIEW):
        # The deterministic critic already refused; the objections only reinforce that.
        return "confirm", (f"The deterministic critic returned '{decision.value}' and "
                           f"{len(blocking)} blocking objection(s) agree.")

    if blocking:
        return "escalate", (f"{len(blocking)} blocking objection(s) must be answered before this can be "
                            f"approved: " + "; ".join(o.code for o in blocking))
    return "proceed_with_caveat", (f"No blocking objection, but {len(advisory)} advisory note(s) apply: "
                                    + "; ".join(o.code for o in advisory))
