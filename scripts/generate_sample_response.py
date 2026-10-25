"""Writes data/sample_analysis_response.json — a hand-authored, ILLUSTRATIVE example of the final API
payload (matches AnalysisResponse) so Developer 2 can build the UI/critic before the optimizer exists."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from app.models.schemas import AnalysisResponse  # noqa: E402

NOW = "2026-10-13T09:00:00+03:00"


def prop(i, wid, ns, status, cur, new, m, reasons, saving, suppressed_saving=0.0, suppressed_proposal=None):
    return {
        "proposal_id": f"PRP-{i:04d}", "workload_id": wid, "namespace": ns, "status": status,
        "current": cur, "proposed": new, "metrics": m, "reasons": reasons, "warnings": [],
        "estimated_monthly_saving_usd": saving, "created_at": NOW,
        "suppressed_saving_usd": suppressed_saving, "suppressed_proposal": suppressed_proposal,
    }


def cur(c, cl, m, ml):
    return {"cpu_request_millicores": c, "cpu_limit_millicores": cl, "memory_request_mib": m, "memory_limit_mib": ml}


def met(n, h, c95, c99, m95, m99):
    return {"sample_count": n, "span_hours": h, "cpu_p95": c95, "cpu_p99": c99, "memory_p95": m95, "memory_p99": m99}


def chk(name, code, status, msg, ev=None):
    return {"name": name, "code": code, "status": status, "message": msg, "evidence": ev or {}}


def obj(code, severity, msg, source=None):
    return {"code": code, "severity": severity, "message": msg, "source": source}


def step(tool, params, result, thought=None, at=None):
    """One tool call inside a review phase."""
    return {"timestamp": at or NOW, "tool": tool, "params": params, "result": result, "thought": thought}


def cycle(role, summary, steps, objections=None, verdict=None, started=None, completed=None):
    return {"role": role, "summary": summary, "steps": steps, "objections": objections or [],
            "verdict": verdict, "started_at": started or NOW, "completed_at": completed or NOW}


def rollout(test_steps, watch_metrics, rollback):
    return {"test_steps": test_steps, "watch_metrics": watch_metrics, "rollback": rollback}


results = [
    {"workload_id": "payment-api", "namespace": "payments", "decision": "approved", "risk_level": "low",
     "reason": "All safety checks passed; patch is review-only.",
     "confidence_score": 100.0,
     "confidence_basis": "100.0% of reported numbers traced to a tool result; 72/24 samples; fresh metrics.",
     "evidence_trail": [
         "analyze_rightsizing(workload_id=payment-api) -> proposal for 72 samples",
         "get_incident_history(workload_id=payment-api) -> 0 record(s)",
         "validate_policy(proposal_data={}) -> approved",
     ],
     "objections": [],
     "cycles": [
         cycle("proposer",
               "Pulled 72 hourly samples and compared p99 against the request. Usage sits at 42% of the CPU "
               "request and 39% of the memory request, so the proposal targets p99 x 1.2 with a floor of 500 m / 2 GiB.",
               [step("get_workload_metrics", {"workload_id": "payment-api"}, "72 record(s)"),
                step("analyze_rightsizing", {"workload_id": "payment-api"}, "proposal for 72 samples")]),
         cycle("critic",
               "Red-teamed the proposal: no incident in the last 90 days, no business event inside the 48h risk "
               "window, and the proposed request stays above observed p99 x 1.2. No blocking objection found.",
               [step("get_incident_history", {"workload_id": "payment-api"}, "0 record(s)"),
                step("search_logs", {"workload_id": "payment-api"}, "0 record(s)"),
                step("get_dependencies", {"workload_id": "payment-api"}, "2 upstream service(s)")],
               verdict="accept"),
         cycle("judge",
               "No objections to weigh. The deterministic critic approved the change, and the evidence behind it "
               "traces to tool results, so the decision stands.",
               [step("validate_policy", {"workload_id": "payment-api"}, "approved")],
               verdict="approved"),
     ],
     "historical_lessons": [
         "2026-09-18 — a human reviewer rejected a 25% memory reduction on payment-api: "
         "'p99 was measured over a quiet weekend; keep the request at or above 2 GiB.' "
         "This proposal keeps memory at 2432 MiB, so it is consistent with that guidance.",
     ],
     "rollout_guidance": rollout(
         ["Apply to one replica of the payments deployment and watch for 30 minutes.",
          "Promote to all replicas only if p99 stays below 70% of the new request."],
         ["Container CPU throttling rate", "p99 CPU usage against the new request",
          "Pod restarts and OOMKilled events"],
         "Revert by restoring the previous request values (CPU 1000 m, memory 4096 MiB); no data migration is involved."),
     "checks": [chk("metrics_completeness", "OK", "passed", "72 hourly samples"),
                chk("event_window", "NO_EVENT", "passed", "No event in 48h window")],
     "proposal": prop(1, "payment-api", "payments", "proposed", cur(1000, 2000, 4096, 6144),
                      {"cpu_request_millicores": 570, "memory_request_mib": 2432},
                      met(72, 71, 410, 420, 1590, 1600), ["Usage percentiles well below requests"], 18.9),
     "monthly_savings_estimate_usd": 18.9, "yaml_patch": "# review-only patch (generated by Dev 2)"},
    {"workload_id": "checkout-service", "namespace": "commerce", "decision": "deferred", "risk_level": "high",
     "reason": "High-impact event starts within risk window.",
     "confidence_score": 46.0,
     "confidence_basis": ("100.0% of reported numbers traced to a tool result; 72/24 samples; fresh metrics; "
                          "incident/event overlap; 1 blocking objection(s)."),
     "evidence_trail": [
         "analyze_rightsizing(workload_id=checkout-service) -> proposal for 72 samples",
         "search_logs(workload_id=checkout-service) -> 1 record(s)",
         "validate_policy(proposal_data={}) -> deferred",
     ],
     "objections": [obj("LOG_PRESSURE_IGNORED", "blocking",
                       "Log at 2026-10-14T09:00:00Z reports pressure: 'Memory limit reached. Container OOMKilled.' "
                       "Reducing requests while the container is being OOMKilled risks an outage.",
                       "search_logs")],
     "cycles": [
         cycle("proposer",
               "Pulled 72 hourly samples and a dependency map. Usage percentiles sit well below the request, so a "
               "reduction to 640 m / 2560 MiB looks safe on paper.",
               [step("get_workload_metrics", {"workload_id": "checkout-service"}, "72 record(s)"),
                step("analyze_rightsizing", {"workload_id": "checkout-service"}, "proposal for 72 samples"),
                step("get_dependencies", {"workload_id": "checkout-service"}, "3 upstream service(s)")]),
         cycle("critic",
               "Red-teamed the proposal and found a blocking objection: the container was OOMKilled against its "
               "memory limit while the request was being reduced. The same pattern appears in a log six hours ago.",
               [step("search_logs", {"workload_id": "checkout-service"}, "1 record(s)"),
                step("get_incident_history", {"workload_id": "checkout-service"}, "0 record(s)")],
               objections=[obj("LOG_PRESSURE_IGNORED", "blocking",
                               "Log at 2026-10-14T09:00:00Z reports pressure: 'Memory limit reached. Container OOMKilled.' "
                               "Reducing requests while the container is being OOMKilled risks an outage.",
                               "search_logs")],
               verdict="escalate"),
         cycle("judge",
               "Weighed the blocking objection against the proposal. The critic may only downgrade an approval, so "
               "the decision moves from approved to needs_review for a human to look at.",
               [step("validate_policy", {"workload_id": "checkout-service"}, "deferred")],
               objections=[obj("LOG_PRESSURE_IGNORED", "blocking",
                               "Log at 2026-10-14T09:00:00Z reports pressure: 'Memory limit reached. Container OOMKilled.' "
                               "Reducing requests while the container is being OOMKilled risks an outage.",
                               "search_logs")],
               verdict="escalate"),
     ],
     "checks": [chk("event_window", "HIGH_IMPACT_EVENT", "triggered", "Campaign starts in 23h",
                    {"event": "Major marketing campaign", "start_at": "2026-10-14T08:00:00+03:00"}),
                chk("metrics_completeness", "OK", "passed", "72 hourly samples")],
     # The critic refused this reduction, so the candidate is preserved rather than erased: the
     # money the optimizer found is visible as suppressed, and the request is unchanged.
     "proposal": prop(2, "checkout-service", "commerce", "proposed", cur(1000, 2000, 4096, 6144),
                      None,
                      met(72, 71, 520, 530, 1990, 2000), ["Usage percentiles below requests"], 0.0,
                      suppressed_saving=17.5,
                      suppressed_proposal={"cpu_request_millicores": 640, "memory_request_mib": 2560}),
     "monthly_savings_estimate_usd": 0.0, "yaml_patch": None},
    {"workload_id": "email-worker", "namespace": "jobs", "decision": "needs_review", "risk_level": "medium",
     "reason": "Only 10 samples; evidence insufficient.",
     "confidence_score": 30.0,
     "confidence_basis": ("100.0% of reported numbers traced to a tool result; 10/24 samples; fresh metrics; "
                          "1 blocking objection(s)."),
     "evidence_trail": [
         "get_workload_metrics(workload_id=email-worker) -> 10 record(s)",
         "analyze_rightsizing(workload_id=email-worker) -> needs_review",
         "validate_policy(proposal_data={}) -> needs_review",
     ],
     "objections": [obj("THIN_EVIDENCE", "blocking",
                       "Only 10 usage samples back this recommendation, below the required 24. "
                       "The sample window is too small to distinguish a trend from noise.",
                       "get_workload_metrics")],
     "cycles": [
         cycle("proposer",
               "Fetched what metrics exist for email-worker. Only 10 hourly samples are available, which is below "
               "the 24-sample floor, so the proposer declines to size a request.",
               [step("get_workload_metrics", {"workload_id": "email-worker"}, "10 record(s)"),
                step("analyze_rightsizing", {"workload_id": "email-worker"}, "needs_review")]),
         cycle("critic",
               "Checked whether the thin sample could be argued around. It cannot: 10 points over 9 hours cannot "
               "separate a trend from noise, and the worker already has an open reliability question.",
               [step("search_logs", {"workload_id": "email-worker"}, "0 record(s)"),
                step("get_incident_history", {"workload_id": "email-worker"}, "0 record(s)")],
               objections=[obj("THIN_EVIDENCE", "blocking",
                               "Only 10 usage samples back this recommendation, below the required 24. "
                               "The sample window is too small to distinguish a trend from noise.",
                               "get_workload_metrics")],
               verdict="escalate"),
         cycle("judge",
               "The objection is well grounded and the deterministic critic already refused to approve, so the "
               "decision is needs_review. More samples are the only way forward.",
               [step("validate_policy", {"workload_id": "email-worker"}, "needs_review")],
               verdict="needs_review"),
     ],
     "checks": [chk("metrics_completeness", "INSUFFICIENT_SAMPLES", "triggered", "10 < 24 samples")],
     "proposal": prop(3, "email-worker", "jobs", "needs_review", cur(500, 1500, 2048, 3072), None,
                      met(10, 9, None, None, None, None), ["Need >= 24 samples and >= 24h span"], 0.0),
     "monthly_savings_estimate_usd": 0.0, "yaml_patch": None},
    {"workload_id": "session-store", "namespace": "core", "decision": "no_change", "risk_level": "low",
     "reason": "No safe reduction identified.",
     "confidence_score": 88.0,
     "confidence_basis": "100.0% of reported numbers traced to a tool result; 72/24 samples; fresh metrics.",
     "evidence_trail": [
         "analyze_rightsizing(workload_id=session-store) -> no_change",
         "validate_policy(proposal_data={}) -> no_change",
     ],
     "objections": [],
     "cycles": [
         cycle("proposer",
               "Pulled 72 hourly samples for session-store. Peak usage sits within 10% of the current request, so "
               "there is no meaningful headroom to give back.",
               [step("get_workload_metrics", {"workload_id": "session-store"}, "72 record(s)"),
                step("analyze_rightsizing", {"workload_id": "session-store"}, "no_change")]),
         cycle("critic",
               "Looked for a way to justify a change anyway and did not find one. The proposed reduction would fall "
               "below observed p99, which is exactly the case the critic refuses to approve.",
               [step("search_logs", {"workload_id": "session-store"}, "0 record(s)"),
                step("get_incident_history", {"workload_id": "session-store"}, "0 record(s)")],
               verdict="accept"),
         cycle("judge",
               "No change to rule on. The deterministic critic returned no_change, so the current allocation stays.",
               [step("validate_policy", {"workload_id": "session-store"}, "no_change")],
               verdict="no_change"),
     ],
     "checks": [chk("benefit", "BELOW_THRESHOLD", "triggered", "Reduction < 15%")],
     "proposal": prop(4, "session-store", "core", "no_change", cur(500, 1000, 1024, 2048), None,
                      met(72, 71, 470, 480, 910, 920), ["Peak usage near current request"], 0.0),
     "monthly_savings_estimate_usd": 0.0, "yaml_patch": None},
]

def health(wid, ns, samples, span, age, status, sparse=False):
    """One row of the validation report: how much metric history backs this workload."""
    return {"workload_id": wid, "namespace": ns, "sample_count": samples, "required_samples": 24,
            "span_hours": span, "required_span_hours": 24.0, "latest_metric_age_hours": age,
            "max_metric_age_hours": 72.0, "missing_metrics": False, "sparse_metrics": sparse,
            "stale_metrics": False, "status": status}


payload = {
    "analysis_id": "ANL-SAMPLE-0001", "generated_at": NOW, "mode": "agent",
    "summary": {"workloads_evaluated": 4, "approved": 1, "deferred": 1, "rejected": 0, "needs_review": 1,
                "no_change": 1, "estimated_monthly_savings_usd": 18.9},
    "results": results,
    "warnings": ["Sample/illustrative data. Savings are estimates, not guaranteed bill reductions."],
    "policy_version": "demo-1",
    "rule_version": "rules-1",
    "input_fingerprint": "sha256:sample0001fingerprint00000000000000000000000000000000000000000000",
    "data_health": {
        "generated_at": NOW, "source": "local", "workloads_checked": 4, "error_count": 0, "warning_count": 1,
        "workloads": [
            health("payment-api", "payments", 72, 71.0, 1.0, "healthy"),
            health("checkout-service", "commerce", 72, 71.0, 1.0, "healthy"),
            health("email-worker", "jobs", 10, 9.0, 1.0, "warning", sparse=True),
            health("session-store", "core", 72, 71.0, 1.0, "healthy"),
        ],
        "issues": [{"severity": "warning", "code": "SPARSE_METRICS", "source": "usage_history",
                    "workload_id": "email-worker",
                    "message": "10 samples over 9.0 hours; need 24 samples over 24.0 hours."}],
    },
}
AnalysisResponse.model_validate(payload)  # fail loudly if it drifts from the contract
(ROOT / "data" / "sample_analysis_response.json").write_text(json.dumps(payload, indent=2) + "\n")
print("written")
