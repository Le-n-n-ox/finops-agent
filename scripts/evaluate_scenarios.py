"""Evaluate planted FinOps cases from data/test_scenarios.json.

Run from the repository root with: python scripts/evaluate_scenarios.py
Prints a Markdown results table and aggregate recall/false-positive metrics.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.models.schemas import DecisionStatus
from app.services.critic_service import evaluate
from app.services.data_loader import load_inputs
from app.services.optimizer_service import analyze_workload
from app.services.report_service import with_patch


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def run_case(bundle, scenario: dict) -> tuple[str, str, bool, bool]:
    sid = scenario["id"]
    name = scenario["name"]
    workload_id = "image-resizer" if scenario["workload"] == "any" else scenario["workload"]
    spec = next(s for s in bundle.services if s.name == workload_id)
    now = bundle.policy.simulation_now or datetime(2026, 9, 30, 23, 5, tzinfo=timezone.utc)
    rows = [row for row in bundle.usage_rows if row.service == workload_id]
    case_bundle = bundle

    # Plant deterministic signals so each scenario tests the stated rule, not an
    # accidental property of the demo fixture's latest values.
    if sid in {"SCN-02", "SCN-04"}:
        rows = [row.model_copy(update={"cpu_millicores": 100.0, "memory_mib": 256.0}) for row in rows]
    if sid == "SCN-03":
        rows = [row.model_copy(update={"cpu_millicores": 500.0, "memory_mib": 2000.0}) for row in rows]
    if sid == "SCN-02":
        spec = spec.model_copy(update={"protected": True})
        case_bundle = bundle.model_copy(update={
            "services": [spec if s.name == workload_id else s for s in bundle.services],
            "incidents": [i for i in bundle.incidents if i.service != workload_id],
        })
    elif sid == "SCN-03":
        now = dt(scenario.get("timestamp", "2026-09-16T02:00:00Z"))
        rows = [r for r in rows if r.timestamp <= now]
    elif sid == "SCN-04":
        now = dt(scenario.get("timestamp", "2026-09-22T15:00:00Z"))
        rows = [r for r in rows if r.timestamp <= now]
    elif sid == "SCN-05":
        rows = rows[:10]
    elif sid == "SCN-06":
        rows = [row.model_copy(update={"cpu_millicores": 1.0, "memory_mib": 16.0}) for row in rows]
        case_bundle = bundle.model_copy(update={"events": [], "incidents": []})
    elif sid == "SCN-07":
        case_bundle = bundle.model_copy(update={"events": [], "incidents": []})

    proposal = analyze_workload(
        spec, rows, case_bundle.policy.optimizer, now, case_bundle.cost_model,
        incidents=case_bundle.incidents, events=case_bundle.events,
    )
    result = with_patch(evaluate(proposal, case_bundle, now), spec)
    has_cut = bool(result.proposal.proposed and (
        (result.proposal.current.cpu_request_millicores or 0) > (result.proposal.proposed.cpu_request_millicores or 0)
        or (result.proposal.current.memory_request_mib or 0) > (result.proposal.proposed.memory_request_mib or 0)
    )) or any(f.code.startswith("OVERPROVISIONED_") for f in result.proposal.findings)

    if sid == "SCN-01":
        passed = result.decision == DecisionStatus.APPROVED and has_cut
    elif sid == "SCN-02":
        passed = result.decision == DecisionStatus.REJECTED
    elif sid == "SCN-03":
        passed = result.decision == DecisionStatus.DEFERRED and not has_cut
    elif sid == "SCN-04":
        passed = result.decision in {DecisionStatus.DEFERRED, DecisionStatus.REJECTED} and not has_cut
    elif sid == "SCN-05":
        passed = result.decision == DecisionStatus.NEEDS_REVIEW and not has_cut
    elif sid == "SCN-06":
        reduction = max((
            (result.proposal.current.cpu_request_millicores - result.proposal.proposed.cpu_request_millicores)
            / result.proposal.current.cpu_request_millicores * 100
            if result.proposal.proposed and result.proposal.current.cpu_request_millicores else 0,
            (result.proposal.current.memory_request_mib - result.proposal.proposed.memory_request_mib)
            / result.proposal.current.memory_request_mib * 100
            if result.proposal.proposed and result.proposal.current.memory_request_mib else 0,
        ))
        passed = result.decision == DecisionStatus.REJECTED or reduction <= case_bundle.policy.critic.max_reduction_pct
    else:  # SCN-07: request-only patch contract; limit values are context, never patch targets.
        passed = bool(result.yaml_patch and "limits:" not in result.yaml_patch
                      and result.proposal.current.cpu_limit_millicores is not None
                      and result.proposal.current.memory_limit_mib is not None)
    return result.decision.value, result.reason, passed, has_cut


def main() -> int:
    data = json.loads((ROOT / "data/test_scenarios.json").read_text(encoding="utf-8"))
    bundle = load_inputs(ROOT / "data")
    rows = []
    risky_ids = {"SCN-02", "SCN-03", "SCN-04"}
    risky_false_positives = 0
    overprovisioned_total = 0
    overprovisioned_caught = 0
    for scenario in data["scenarios"]:
        actual, reason, passed, has_cut = run_case(bundle, scenario)
        expected = scenario["expected_outcome"]
        rows.append((scenario["id"], scenario["name"], expected, actual, "PASS" if passed else "FAIL", reason, has_cut))
        if scenario["id"] == "SCN-01":
            overprovisioned_total += 1
            overprovisioned_caught += int(has_cut)
        if scenario["id"] in risky_ids and actual == "approved" and has_cut:
            risky_false_positives += 1

    print("| ID | Scenario | Expected | Actual | Result |")
    print("|---|---|---|---|---|")
    for sid, name, expected, actual, result, _, _ in rows:
        print(f"| {sid} | {name} | {expected} | {actual} | {result} |")
    passed_count = sum(row[4] == "PASS" for row in rows)
    recall = 100 * overprovisioned_caught / max(overprovisioned_total, 1)
    fpr = 100 * risky_false_positives / max(len(risky_ids), 1)
    print()
    print(f"- Scenario pass rate: {passed_count}/{len(rows)} ({100 * passed_count / max(len(rows), 1):.1f}%).")
    print(f"- Planted safe over-provisioning recall: {overprovisioned_caught}/{overprovisioned_total} ({recall:.1f}%).")
    print(f"- Risk-scenario false-positive rate (approved reduction in protected/event/incident case): "
          f"{risky_false_positives}/{len(risky_ids)} ({fpr:.1f}%).")
    event_incident_leaks = sum(1 for row in rows if row[0] in {"SCN-03", "SCN-04"} and row[6])
    print(f"- Event/incident reduction suggestions: {event_incident_leaks}/2 (target 0).")
    if any(row[4] != "PASS" for row in rows):
        for sid, name, _, _, result, reason, _ in rows:
            if result != "PASS":
                print(f"  - {sid} {name}: {reason}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
