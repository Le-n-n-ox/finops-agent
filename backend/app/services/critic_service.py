"""Developer 2 — Context Critic (deterministic rules; no LLM ever decides).

Input : one OptimizationProposal ("recommendation") + InputBundle (events, incidents, services, policy.critic).
Output: one WorkloadResult. Every relevant rule yields a CriticCheck "finding": `name` = rule family,
        `code` = stable rule ID, `status` passed/triggered/skipped, `evidence` incl. `severity`.

Contract status mapping (the guide's names -> shared contract values, which Dev 1 froze):
    APPROVED -> approved | DEFERRED -> deferred | BLOCKED -> rejected | NO_CHANGE -> no_change
    "insufficient / stale evidence" -> needs_review (fail safe: never approved)

Optimizer status -> decision:  insufficient_data -> needs_review | no_action -> no_change | proposed -> rules below.

Priority when several rules trigger (most conservative wins):
    BLOCK  resource_floor BELOW_P99_FLOOR, policy_rules MIN_REQUEST_FLOOR / MAX_REDUCTION / PROTECTED_WORKLOAD
    DEFER  event_window HIGH_IMPACT_EVENT / EVENT_FREEZE, incident_pattern PRIOR_INCIDENT_PATTERN (exact match),
           policy_rules CHANGE_WINDOW
    REVIEW metrics_completeness (stale / missing / too few samples) or a skipped verification
    NONE   benefit BELOW_MIN_SAVING, policy_rules EXCLUDED_WORKLOAD
    otherwise approved
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone

from app.models.schemas import (
    BusinessEvent, CheckStatus, CriticCheck, DecisionStatus, IncidentRecord, InputBundle,
    OptimizationProposal, ProposalStatus, RiskLevel, RolloutGuidance, WorkloadResult,
)

INCIDENT_LOOKBACK_DAYS = 180  # not in CriticPolicy yet; promote to policy.yaml if both devs agree


def evaluate_proposal(proposal: OptimizationProposal, bundle: InputBundle) -> WorkloadResult:
    """Evaluate a proposal against metrics, events, incidents, floors, and savings."""
    critic_policy = bundle.policy.critic
    now = _as_utc(bundle.policy.simulation_now or datetime.now(timezone.utc))
    checks: list[CriticCheck] = []

    if proposal.status == ProposalStatus.NEEDS_REVIEW:
        checks.append(CriticCheck(
            name="metrics_completeness",
            code="INSUFFICIENT_METRICS",
            status=CheckStatus.TRIGGERED,
            message="Data history or observation count is insufficient for optimization.",
            evidence={"reasons": proposal.reasons, "sample_count": proposal.metrics.sample_count},
        ))
        return _build_result(
            proposal, DecisionStatus.NEEDS_REVIEW, RiskLevel.MEDIUM,
            "Insufficient usage data to generate a safe recommendation.", checks,
        )

    if proposal.status == ProposalStatus.NO_CHANGE or proposal.proposed is None:
        checks.append(CriticCheck(
            name="optimizer_status",
            code="NO_OPTIMIZATION_NEEDED",
            status=CheckStatus.PASSED,
            message="Workload usage is already optimal or reduction is below threshold.",
            evidence={"reasons": proposal.reasons},
        ))
        return _build_result(
            proposal, DecisionStatus.NO_CHANGE, RiskLevel.LOW,
            "Workload is already operating within optimal resource targets.", checks,
        )

    has_event_conflict = False
    for event in bundle.events:
        if proposal.workload_id not in event.services and "all" not in event.services:
            continue
        start_diff_hours = (_as_utc(event.start_at) - now).total_seconds() / 3600
        end_diff_hours = (_as_utc(event.end_at) - now).total_seconds() / 3600
        if (-24 <= end_diff_hours <= critic_policy.risk_window_hours and
                start_diff_hours <= critic_policy.risk_window_hours and
                (event.risk.lower() in {"high", "medium"} or event.expected_traffic.lower() == "high")):
            has_event_conflict = True
            checks.append(CriticCheck(
                name="event_window",
                code="UPCOMING_BUSINESS_EVENT",
                status=CheckStatus.TRIGGERED,
                message=f"Upcoming high-impact event '{event.name}' risk window.",
                evidence={
                    "event_name": event.name,
                    "start_at": event.start_at.isoformat(),
                    "end_at": event.end_at.isoformat(),
                    "expected_traffic": event.expected_traffic,
                },
            ))
    if has_event_conflict:
        return _build_result(
            proposal, DecisionStatus.DEFERRED, RiskLevel.HIGH,
            "Resource changes deferred due to upcoming high-traffic business events.", checks,
        )
    checks.append(CriticCheck(
        name="event_window",
        code="NO_EVENT_CONFLICT",
        status=CheckStatus.PASSED,
        message="No conflicting business events in the evaluation window.",
    ))

    matching_incidents = [inc for inc in bundle.incidents if inc.service == proposal.workload_id]
    if matching_incidents:
        recent_incident = max(matching_incidents, key=lambda incident: _as_utc(incident.occurred_at))
        checks.append(CriticCheck(
            name="incident_pattern",
            code="HISTORICAL_INCIDENT_CORRELATION",
            status=CheckStatus.TRIGGERED,
            message=f"Historical incident pattern detected: '{recent_incident.pattern}'.",
            evidence={
                "incident_id": recent_incident.incident_id,
                "pattern": recent_incident.pattern,
                "summary": recent_incident.summary,
                "occurred_at": recent_incident.occurred_at.isoformat(),
            },
        ))
        return _build_result(
            proposal, DecisionStatus.NEEDS_REVIEW, RiskLevel.HIGH,
            f"Workload has past incident history ({recent_incident.incident_id}); manual review required.", checks,
        )
    checks.append(CriticCheck(
        name="incident_pattern",
        code="NO_INCIDENT_CORRELATION",
        status=CheckStatus.PASSED,
        message="No relevant incident history associated with this workload.",
    ))

    proposed = proposal.proposed
    p99_cpu = proposal.metrics.cpu_p99 or 0.0
    p99_memory = proposal.metrics.memory_p99 or 0.0
    proposed_cpu = proposed.cpu_request_millicores or 0
    proposed_memory = proposed.memory_request_mib or 0
    cpu_floor = p99_cpu * critic_policy.cpu_floor_p99_multiplier
    memory_floor = p99_memory * critic_policy.memory_floor_p99_multiplier
    floor_violation = False

    if proposed_cpu < cpu_floor:
        floor_violation = True
        checks.append(CriticCheck(
            name="resource_floor",
            code="CPU_FLOOR_VIOLATION",
            status=CheckStatus.TRIGGERED,
            message=f"Proposed CPU request ({proposed_cpu}m) drops below P99 safety floor ({cpu_floor:.1f}m).",
            evidence={"proposed": proposed_cpu, "required_floor": cpu_floor, "p99": p99_cpu},
        ))
    if proposed_memory < memory_floor:
        floor_violation = True
        checks.append(CriticCheck(
            name="resource_floor",
            code="MEMORY_FLOOR_VIOLATION",
            status=CheckStatus.TRIGGERED,
            message=f"Proposed memory request ({proposed_memory}MiB) drops below P99 safety floor ({memory_floor:.1f}MiB).",
            evidence={"proposed": proposed_memory, "required_floor": memory_floor, "p99": p99_memory},
        ))
    if floor_violation:
        return _build_result(
            proposal, DecisionStatus.REJECTED, RiskLevel.HIGH,
            "Proposed reduction breaches required P99 headroom safety floors.", checks,
        )
    checks.append(CriticCheck(
        name="resource_floor",
        code="HEADROOM_FLOOR_SAFE",
        status=CheckStatus.PASSED,
        message="Proposed requests maintain safe headroom above P99 usage peaks.",
    ))

    savings = proposal.estimated_monthly_saving_usd
    if savings < critic_policy.min_monthly_saving_usd:
        checks.append(CriticCheck(
            name="benefit",
            code="INSIGNIFICANT_SAVINGS",
            status=CheckStatus.TRIGGERED,
            message=f"Monthly savings (${savings:.2f}) below threshold (${critic_policy.min_monthly_saving_usd:.2f}).",
            evidence={"estimated_savings": savings, "min_required": critic_policy.min_monthly_saving_usd},
        ))
        return _build_result(
            proposal, DecisionStatus.NO_CHANGE, RiskLevel.LOW,
            "Estimated monthly savings are too small to justify workload redeployment.", checks,
        )
    checks.append(CriticCheck(
        name="benefit",
        code="SAVINGS_THRESHOLD_MET",
        status=CheckStatus.PASSED,
        message=f"Projected savings (${savings:.2f}/mo) meet minimum economic threshold.",
    ))

    return _build_result(
        proposal, DecisionStatus.APPROVED, RiskLevel.LOW,
        "Proposal passed all safety, event, incident, and headroom checks.", checks,
        yaml_patch=_generate_yaml_patch(proposal), monthly_savings=savings,
    )

_MEMORY_RE = re.compile(r"\bmemory\b|\boom")
_CPU_RE = re.compile(r"\bcpu\b|throttl")
_EPS = 1e-6
T, P, S = CheckStatus.TRIGGERED, CheckStatus.PASSED, CheckStatus.SKIPPED



def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _hours(delta: timedelta) -> float:
    return delta.total_seconds() / 3600


def _check(name: str, code: str, status: CheckStatus, message: str, sev: str = "info", **evidence) -> CriticCheck:
    evidence["severity"] = sev if status is not P else "info"
    return CriticCheck(name=name, code=code, status=status, message=message, evidence=evidence)


def event_id(e: BusinessEvent) -> str:
    raw = f"{e.name}|{e.start_at.isoformat()}|{e.end_at.isoformat()}"
    return "EVT-" + hashlib.sha1(raw.encode()).hexdigest()[:8].upper()


def _reduction_pct(cur: int | None, new: int | None) -> float | None:
    return (cur - new) / cur * 100 if cur and new is not None else None


# --------------------------------------------------------------------------- evidence quality
def check_metrics(proposal: OptimizationProposal, bundle: InputBundle, now: datetime) -> CriticCheck:
    m, pol = proposal.metrics, bundle.policy.critic
    if m.last_observed_at is None:
        return _check("metrics_completeness", "MISSING_TIMESTAMP", T,
                      "No last-observed timestamp; cannot judge how fresh the evidence is", "review", sample_count=m.sample_count)
    age = _hours(now - _aware(m.last_observed_at))
    if age > pol.stale_after_hours:
        return _check("metrics_completeness", "STALE_METRICS", T,
                      f"Latest sample is {age:.0f}h old (limit {pol.stale_after_hours}h)", "review",
                      last_observed_at=m.last_observed_at.isoformat(), age_hours=round(age, 1), limit_hours=pol.stale_after_hours)
    if m.sample_count < pol.min_samples:
        return _check("metrics_completeness", "INSUFFICIENT_SAMPLES", T,
                      f"{m.sample_count} < {pol.min_samples} samples", "review", sample_count=m.sample_count)
    return _check("metrics_completeness", "OK", P,
                  f"{m.sample_count} samples over {m.span_hours:.0f}h; latest {max(age, 0):.0f}h ago",
                  sample_count=m.sample_count, span_hours=m.span_hours)


# --------------------------------------------------------------------------- events
def _relevant_events(proposal: OptimizationProposal, bundle: InputBundle, now: datetime) -> list[BusinessEvent]:
    pol = bundle.policy.critic
    projection_horizon = max(pol.risk_window_hours, bundle.policy.optimizer.event_projection_hours)
    window_end = now + timedelta(hours=projection_horizon)
    freeze = timedelta(hours=pol.event_freeze_hours_after)
    found = [e for e in bundle.events
             if proposal.workload_id in e.services and _aware(e.end_at) + freeze > now and _aware(e.start_at) <= window_end]
    return sorted(found, key=lambda e: _aware(e.start_at))


def check_events(proposal: OptimizationProposal, bundle: InputBundle, now: datetime) -> CriticCheck:
    pol = bundle.policy.critic
    relevant = _relevant_events(proposal, bundle, now)
    high = [e for e in relevant if e.risk.lower() == "high" or e.expected_traffic.lower() == "high"]
    if high:
        e = high[0]
        until = _hours(_aware(e.start_at) - now)
        ev = dict(event=e.name, event_id=event_id(e), start_at=e.start_at.isoformat(), end_at=e.end_at.isoformat(),
                  expected_traffic=e.expected_traffic, risk=e.risk, hours_until_start=round(until, 1))
        if _aware(e.end_at) <= now:  # over, but inside the post-event freeze
            return _check("event_window", "EVENT_FREEZE", T,
                          f"{e.name} ended {_hours(now - _aware(e.end_at)):.0f}h ago; change freeze runs "
                          f"{pol.event_freeze_hours_after}h after high-impact events", "defer", **ev)
        when = f"starts in {round(until)}h" if until > 0 else f"is in progress (ends in {round(_hours(_aware(e.end_at) - now))}h)"
        return _check("event_window", "HIGH_IMPACT_EVENT", T, f"{e.name} {when}", "defer", **ev)
    if relevant:
        return _check("event_window", "LOW_IMPACT_EVENT", T,
                      "Request changes are held during event window(s): " + ", ".join(e.name for e in relevant), "defer",
                      events=[e.name for e in relevant], event_ids=[event_id(e) for e in relevant])
    return _check("event_window", "NO_EVENT", P, f"No event in {pol.risk_window_hours}h window")


# --------------------------------------------------------------------------- incidents
def _incident_relevant(incident: IncidentRecord, proposal: OptimizationProposal) -> bool:
    """An incident matters only if this proposal reduces the resource the incident was about."""
    cur, new = proposal.current, proposal.proposed
    text = f"{incident.pattern} {incident.summary}".lower()
    reduces_mem = (new is not None and new.memory_request_mib is not None and cur.memory_request_mib is not None
                   and new.memory_request_mib < cur.memory_request_mib)
    reduces_cpu = (new is not None and new.cpu_request_millicores is not None and cur.cpu_request_millicores is not None
                   and new.cpu_request_millicores < cur.cpu_request_millicores)
    mem_hit, cpu_hit = bool(_MEMORY_RE.search(text)), bool(_CPU_RE.search(text))
    if not mem_hit and not cpu_hit:
        return reduces_mem or reduces_cpu
    return (mem_hit and reduces_mem) or (cpu_hit and reduces_cpu)


def _incident_evidence(i: IncidentRecord, now: datetime, match: str) -> dict:
    return dict(incident_id=i.incident_id, service=i.service, occurred_at=i.occurred_at.isoformat(), pattern=i.pattern,
                summary=i.summary, days_ago=round(_hours(now - _aware(i.occurred_at)) / 24), match=match)


def check_incidents(proposal: OptimizationProposal, bundle: InputBundle, now: datetime) -> list[CriticCheck]:
    """Exact match (same workload) can defer. Indirect match (same namespace, other workload) is advisory only."""
    cutoff = now - timedelta(days=INCIDENT_LOOKBACK_DAYS)
    ns = {s.name: s.namespace for s in bundle.services}
    recent = [i for i in bundle.incidents if cutoff <= _aware(i.occurred_at) <= now]
    key = lambda i: _aware(i.occurred_at)  # noqa: E731
    exact = sorted((i for i in recent if i.service == proposal.workload_id), key=key, reverse=True)
    indirect = sorted((i for i in recent if i.service != proposal.workload_id and ns.get(i.service) == proposal.namespace
                       and _incident_relevant(i, proposal)),
                      key=key, reverse=True)
    out: list[CriticCheck] = []
    if exact:
        i = exact[0]
        out.append(_check("incident_pattern", "PRIOR_INCIDENT_PATTERN", T,
                          f"{i.incident_id} ({_aware(i.occurred_at):%Y-%m-%d}) matches: {i.pattern}", "defer",
                          **_incident_evidence(i, now, "exact")))
    if indirect:
        i = indirect[0]
        out.append(_check("incident_pattern", "INDIRECT_INCIDENT_MATCH", P,
                          f"Advisory: {i.incident_id} on {i.service} (same namespace) matches: {i.pattern}",
                          **_incident_evidence(i, now, "indirect")))
    if not out:
        out.append(_check("incident_pattern", "NO_RELEVANT_INCIDENT", P,
                          f"No related incident in the last {INCIDENT_LOOKBACK_DAYS} days"))
    return out


# --------------------------------------------------------------------------- headroom + policy rules
def check_floor(proposal: OptimizationProposal, bundle: InputBundle) -> CriticCheck:
    """Ensure reductions keep p99 headroom without blocking unchanged resources."""
    p, m, pol = proposal.proposed, proposal.metrics, bundle.policy.critic
    if p is None:
        return _check("resource_floor", "MISSING_PROPOSAL", S, "Proposal has no proposed requests to verify")
    if m.cpu_p99 is None or m.memory_p99 is None:
        return _check("resource_floor", "NO_P99", S, "p99 usage missing; cannot verify headroom")
    spec = next((s for s in bundle.services if s.name == proposal.workload_id), None)
    headroom = pol.criticality_headroom.get(spec.criticality.lower(), 1.0) if spec else 1.0
    cpu_floor = m.cpu_p99 * pol.cpu_floor_p99_multiplier * headroom
    mem_floor = m.memory_p99 * pol.memory_floor_p99_multiplier * headroom
    breaches: list[str] = []
    unchanged_gaps: list[str] = []
    cpu_reduced = (p.cpu_request_millicores is not None and
                   (proposal.current.cpu_request_millicores is None or
                    p.cpu_request_millicores < proposal.current.cpu_request_millicores - _EPS))
    memory_reduced = (p.memory_request_mib is not None and
                      (proposal.current.memory_request_mib is None or
                       p.memory_request_mib < proposal.current.memory_request_mib - _EPS))
    if cpu_reduced and p.cpu_request_millicores < cpu_floor - _EPS:
        breaches.append(f"CPU {p.cpu_request_millicores} m < floor {cpu_floor:.0f} m "
                        f"({pol.cpu_floor_p99_multiplier:g} × p99 {m.cpu_p99:.0f} m)")
    elif not cpu_reduced and p.cpu_request_millicores is not None and p.cpu_request_millicores < cpu_floor - _EPS:
        unchanged_gaps.append(f"CPU remains {p.cpu_request_millicores} m below the {cpu_floor:.0f} m floor")
    if memory_reduced and p.memory_request_mib < mem_floor - _EPS:
        breaches.append(f"memory {p.memory_request_mib} MiB < floor {mem_floor:.0f} MiB "
                        f"({pol.memory_floor_p99_multiplier:g} × p99 {m.memory_p99:.0f} MiB)")
    elif not memory_reduced and p.memory_request_mib is not None and p.memory_request_mib < mem_floor - _EPS:
        unchanged_gaps.append(f"memory remains {p.memory_request_mib} MiB below the {mem_floor:.0f} MiB floor")
    ev = dict(cpu_floor_m=round(cpu_floor, 1), memory_floor_mib=round(mem_floor, 1), cpu_p99=m.cpu_p99, memory_p99=m.memory_p99,
              proposed_cpu_m=p.cpu_request_millicores, proposed_memory_mib=p.memory_request_mib,
              reduced_resources=[name for name, reduced in (("cpu", cpu_reduced), ("memory", memory_reduced)) if reduced],
              unchanged_floor_gaps=unchanged_gaps)
    if breaches:
        return _check("resource_floor", "BELOW_P99_FLOOR", T,
                      "Proposed request is below the safety floor: " + "; ".join(breaches), "block", **ev)
    if unchanged_gaps:
        return _check("resource_floor", "REDUCTIONS_CLEAR_EXISTING_GAPS", P,
                      "Reduced requests meet their p99 safety floors; " + "; ".join(unchanged_gaps) +
                      ". Unchanged resources are not reduced by this proposal.", **ev)
    return _check("resource_floor", "HEADROOM_OK", P,
                  f"Reduced requests meet their p99 safety floors (CPU {cpu_floor:.0f} m, memory {mem_floor:.0f} MiB)", **ev)


def check_policy_rules(proposal: OptimizationProposal, bundle: InputBundle, now: datetime) -> list[CriticCheck]:
    pol, cur, new = bundle.policy.critic, proposal.current, proposal.proposed
    out: list[CriticCheck] = []
    if new is None:
        return out
    cut_cpu = _reduction_pct(cur.cpu_request_millicores, new.cpu_request_millicores)
    cut_mem = _reduction_pct(cur.memory_request_mib, new.memory_request_mib)
    reduces = any(c is not None and c > 0 for c in (cut_cpu, cut_mem))

    spec = next((s for s in bundle.services if s.name == proposal.workload_id), None)
    is_protected = proposal.workload_id in pol.protected_workloads or bool(spec and spec.protected)
    if is_protected:
        if reduces:
            out.append(_check("policy_rules", "PROTECTED_WORKLOAD", T,
                              "Protected workload: request reductions are not allowed by workload metadata or policy", "block"))
        else:
            out.append(_check("policy_rules", "PROTECTED_NO_REDUCTION", P, "Protected workload has no request reduction."))
    else:
        out.append(_check("policy_rules", "NOT_PROTECTED", P, "Workload is not protected by metadata or policy."))

    bad = []
    if new.cpu_request_millicores is not None and new.cpu_request_millicores < pol.min_cpu_request_millicores:
        bad.append(f"CPU {new.cpu_request_millicores} m < minimum {pol.min_cpu_request_millicores} m")
    if new.memory_request_mib is not None and new.memory_request_mib < pol.min_memory_request_mib:
        bad.append(f"memory {new.memory_request_mib} MiB < minimum {pol.min_memory_request_mib} MiB")
    out.append(_check("policy_rules", "MIN_REQUEST_FLOOR", T, "Below the policy minimum request: " + "; ".join(bad), "block")
               if bad else _check("policy_rules", "MIN_REQUEST_FLOOR", P, "Proposed requests meet the policy minimums"))

    over = []
    if cut_cpu is not None and cut_cpu > pol.max_reduction_pct + _EPS:
        over.append(f"CPU cut {cut_cpu:.0f}%")
    if cut_mem is not None and cut_mem > pol.max_reduction_pct + _EPS:
        over.append(f"memory cut {cut_mem:.0f}%")
    out.append(_check("policy_rules", "MAX_REDUCTION", T, f"{' and '.join(over)} exceeds the {pol.max_reduction_pct:g}% maximum reduction",
                      "block", cpu_cut_pct=cut_cpu, memory_cut_pct=cut_mem)
               if over else _check("policy_rules", "MAX_REDUCTION", P,
                                   f"Reductions within the {pol.max_reduction_pct:g}% maximum",
                                   cpu_cut_pct=cut_cpu, memory_cut_pct=cut_mem))

    restricted = bool(pol.change_window_days) or (pol.change_window_start_hour, pol.change_window_end_hour) != (0, 24)
    if restricted:
        day_ok = not pol.change_window_days or now.weekday() in pol.change_window_days
        hour_ok = pol.change_window_start_hour <= now.hour < pol.change_window_end_hour
        out.append(_check("policy_rules", "CHANGE_WINDOW", T, "Outside the permitted change window", "defer",
                          weekday=now.weekday(), hour=now.hour, allowed_days=pol.change_window_days,
                          allowed_hours=[pol.change_window_start_hour, pol.change_window_end_hour])
                   if not (day_ok and hour_ok) else _check("policy_rules", "CHANGE_WINDOW", P, "Inside the permitted change window"))
    return out


def check_benefit(proposal: OptimizationProposal, bundle: InputBundle) -> CriticCheck:
    saving, minimum = proposal.estimated_monthly_saving_usd, bundle.policy.critic.min_monthly_saving_usd
    if saving < minimum:
        return _check("benefit", "BELOW_MIN_SAVING", T, f"Estimated saving ${saving:.2f}/mo is below the ${minimum:.2f} minimum",
                      "none", saving_usd=saving, minimum_usd=minimum)
    return _check("benefit", "OK", P, f"Estimated saving ${saving:.2f}/mo (illustrative)", saving_usd=saving)


# --------------------------------------------------------------------------- decision
_BLOCK_CODES = {"BELOW_P99_FLOOR", "MIN_REQUEST_FLOOR", "MAX_REDUCTION", "PROTECTED_WORKLOAD"}


def _decide(checks: list[CriticCheck]) -> tuple[DecisionStatus, RiskLevel, str]:
    def first(pred):
        return next((c for c in checks if pred(c)), None)

    trig = lambda c: c.status is T  # noqa: E731
    if c := first(lambda c: trig(c) and c.code in _BLOCK_CODES):
        return DecisionStatus.REJECTED, RiskLevel.HIGH, f"Rejected: {c.message}. Keeping the current request."
    if c := first(lambda c: trig(c) and c.name == "event_window"):
        lead = "change freeze" if c.code == "EVENT_FREEZE" else (
            "event window" if c.code == "LOW_IMPACT_EVENT" else "high-impact event")
        return DecisionStatus.DEFERRED, RiskLevel.HIGH, f"Deferred: {lead} — {c.message}. Revisit after it ends."
    if c := first(lambda c: trig(c) and c.name == "incident_pattern"):
        return (DecisionStatus.DEFERRED, RiskLevel.HIGH,
                f"Deferred: {c.message}. A similar change caused an incident; needs owner review.")
    if c := first(lambda c: trig(c) and c.code == "CHANGE_WINDOW"):
        return DecisionStatus.DEFERRED, RiskLevel.MEDIUM, f"Deferred: {c.message}. Retry inside the window."
    if c := first(lambda c: trig(c) and c.name == "metrics_completeness"):
        return DecisionStatus.NEEDS_REVIEW, RiskLevel.MEDIUM, f"Needs review: {c.message}."
    if c := first(lambda c: c.status is S):
        return DecisionStatus.NEEDS_REVIEW, RiskLevel.MEDIUM, f"Needs review: {c.message}."
    if c := first(lambda c: trig(c) and c.name == "benefit"):
        return DecisionStatus.NO_CHANGE, RiskLevel.LOW, f"No change: {c.message}."
    return DecisionStatus.APPROVED, RiskLevel.LOW, "All safety checks passed; patch is review-only."


def _result(proposal: OptimizationProposal, decision: DecisionStatus, risk: RiskLevel, reason: str,
            checks: list[CriticCheck]) -> WorkloadResult:
    suppress_reduction = any(
        check.status is CheckStatus.TRIGGERED and check.code in {
            "HIGH_IMPACT_EVENT", "LOW_IMPACT_EVENT", "EVENT_FREEZE", "PRIOR_INCIDENT_PATTERN", "ACTIVE_POLICY_EXCEPTION"
        }
        for check in checks
    )
    if suppress_reduction:
        estimate = proposal.savings_estimate
        if estimate:
            estimate = estimate.model_copy(update={"monthly_savings_usd": 0.0,
                "monthly_savings_low_usd": 0.0, "monthly_savings_high_usd": 0.0,
                "cpu_request_reduction_pct": 0.0, "memory_request_reduction_pct": 0.0,
                "total_request_reduction_pct": 0.0,
                "assumptions": ["No request reduction is recommended while an incident or event deferral is active."]})
        proposal = proposal.model_copy(update={"proposed": None, "estimated_monthly_saving_usd": 0.0,
            "savings_estimate": estimate, "priority_score": 0.0,
            "findings": [finding for finding in proposal.findings
                         if not finding.code.startswith("OVERPROVISIONED_")]})
    elif decision is not DecisionStatus.APPROVED:
        proposal = proposal.model_copy(update={"priority_score": 0.0})
    guidance = RolloutGuidance(
        test_steps=["Apply to one canary replica or a staging workload first.",
                    "Increase rollout gradually only after the observation window passes."],
        watch_metrics=["CPU throttling and utilization", "Memory working set and OOMKilled restarts",
                       "Latency, error rate, and workload-specific SLOs"],
        rollback="Restore the prior requests from the recorded manifest if an SLO regresses, throttling rises, or OOMKills occur.",
    ) if proposal.proposed is not None else None
    return WorkloadResult(
        workload_id=proposal.workload_id, namespace=proposal.namespace, decision=decision, risk_level=risk,
        reason=reason, checks=checks, proposal=proposal,
        monthly_savings_estimate_usd=proposal.estimated_monthly_saving_usd if decision is DecisionStatus.APPROVED else 0.0,
        yaml_patch=None,  # added by report_service for approved + validated results only
        rollout_guidance=guidance,
    )


def evaluate(proposal: OptimizationProposal, bundle: InputBundle, now: datetime | None = None) -> WorkloadResult:
    """Judge one proposal. `now` is injected so tests/demos never depend on the wall clock."""
    now = _aware(now or bundle.policy.simulation_now or datetime.now(timezone.utc))
    pol = bundle.policy.critic
    reasons = " ".join(proposal.reasons).strip()

    exception = next((item for item in pol.policy_exceptions
                      if item.workload_id == proposal.workload_id and _aware(item.expires_at) > now), None)
    if exception:
        chk = _check("policy_rules", "ACTIVE_POLICY_EXCEPTION",
                     T, f"Temporarily excluded until {_aware(exception.expires_at).isoformat()}: {exception.reason}",
                     "none", expires_at=_aware(exception.expires_at).isoformat(), exception_reason=exception.reason)
        return _result(proposal, DecisionStatus.NO_CHANGE, RiskLevel.LOW,
                       f"No change: active time-limited policy exception ({exception.reason}).", [chk])

    if proposal.workload_id in pol.excluded_workloads:
        chk = _check("policy_rules", "EXCLUDED_WORKLOAD", T, "Workload is excluded from optimisation by policy", "none")
        return _result(proposal, DecisionStatus.NO_CHANGE, RiskLevel.LOW, "No change: workload is excluded from optimisation by policy.", [chk])

    if proposal.status is ProposalStatus.NEEDS_REVIEW:
        m, opt = proposal.metrics, bundle.policy.optimizer
        code = "INSUFFICIENT_SAMPLES" if m.sample_count < opt.min_samples else "INSUFFICIENT_HISTORY"
        message = (f"{m.sample_count} < {opt.min_samples} samples" if code == "INSUFFICIENT_SAMPLES"
                   else f"{m.span_hours:.0f}h < {opt.min_span_hours:g}h of history")
        chk = _check("metrics_completeness", code, T, message, "review", sample_count=m.sample_count, span_hours=m.span_hours)
        return _result(proposal, DecisionStatus.NEEDS_REVIEW, RiskLevel.MEDIUM, f"Needs review: {reasons or message}", [chk])

    if proposal.status is ProposalStatus.NO_CHANGE:
        # Event-aware sizing can intentionally push the candidate above the current
        # request, leaving the optimizer with no proposal. Still surface the active
        # event as the reason for deferral instead of returning a misleading low-risk
        # NO_CHANGE result before the event critic runs.
        event_check = check_events(proposal, bundle, now)
        if event_check.status is T:
            decision, risk, reason = _decide([event_check])
            return _result(proposal, decision, risk, reason, [event_check])
        chk = _check("benefit", "BELOW_THRESHOLD", T, reasons or "No safe reduction identified", "none")
        return _result(proposal, DecisionStatus.NO_CHANGE, RiskLevel.LOW, f"No change: {reasons or 'no safe reduction identified'}", [chk])

    checks = [check_metrics(proposal, bundle, now), check_events(proposal, bundle, now), *check_incidents(proposal, bundle, now),
              check_floor(proposal, bundle), *check_policy_rules(proposal, bundle, now), check_benefit(proposal, bundle)]
    decision, risk, reason = _decide(checks)
    return _result(proposal, decision, risk, reason, checks)
