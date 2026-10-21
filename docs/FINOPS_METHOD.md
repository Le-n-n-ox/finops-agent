# FinOps method and success criteria

This is a recommendation-only demo. The scenario metrics below measure deterministic behavior on the planted fixtures; they are not a production accuracy claim.

The local fixture includes two additional synthetic, low-criticality workloads (`docs-renderer` and `queue-cleaner`) with 30 days of low, steady usage and no matching incidents or business events. They are included to demonstrate safe approvals alongside protected and risk-challenged examples; they are not live services.

## Right-sizing method

- Analyze the most recent 30 days of usage. Require at least 168 hourly samples spanning at least 7 days, and a latest sample no older than 72 hours. Missing, stale, or malformed evidence yields `needs_review` and no patch.
- Compute CPU and memory p95 and p99 independently. CPU candidate request is `ceil_unit(max(CPU p95 × 1.20, CPU p99 × 1.10))`; memory candidate is `ceil_unit(max(memory p95 × 1.30, memory p99 × 1.15))`. The policy applies an additional criticality headroom multiplier: low `1.00`, medium `1.10`, critical `1.25`. The defaults are in [`data/policy.yaml`](../data/policy.yaml).
- P99 is a safety floor. A proposal cannot reduce a request below the configured P99 floor. The critic also enforces a minimum 15% reduction, minimum requests, and a 70% maximum cut. Limits are context only and are never edited in a request patch.
- CPU and memory findings differ: high CPU p99 against a request signals possible throttling exposure; memory p99/peak near a limit signals OOM risk. The current usage feed does not include CPU throttling counters, so the CPU finding is a capacity risk signal, not proof of observed throttling.
- For an event within the next 7 days, candidate sizing includes `expected_load_multiplier × p99`. Any event in the decision window defers the change and suppresses the proposed reduction until the event passes. A matching historical incident also defers the change and suppresses reductions.

## Findings, confidence, and ranking

Findings include safe over-provisioning candidates, CPU or memory near/above request and limit, missing requests or limits, request-to-limit ratios below 10% or above 90%, low utilization, no usage despite configured replicas, and an explicitly reported missing autoscaler. `autoscaler_enabled: null` means unknown and does not produce a missing-autoscaler finding.

Confidence is a weighted score from validity (20%), sample coverage (20%), freshness (15%), usage stability (15%), anomalies (10%), and incident/event overlap (20%). The detail view shows each factor. Priority is `monthly savings × confidence / 100 ÷ (1 + risk penalty / 100)`. Only approved opportunities retain a nonzero priority. Results are sorted by this score; the dashboard's top-N count is configurable with `critic.top_n_findings`.

Illustrative monthly savings use:

```text
((CPU request delta in cores × CPU rate per core-month)
 + (memory request delta in GiB × memory rate per GiB-month))
 × replicas × days / 30
```

Rates come from [`data/cost_model.json`](../data/cost_model.json); the estimate range varies both rates by ±20% by default. These are demo rates, not a cloud quote or guaranteed bill reduction. The recommendation detail shows the formula assumptions and range.

Approved recommendations include canary/staging checks, metrics to watch, and rollback guidance. The append-only review log captures reviewer, timestamp, rationale, and an optional outcome (`worked`, `regressed`, `rolled_back`, or free-form). Each report stores policy version, rule version, and a SHA-256 fingerprint of its input bundle alongside the decision snapshots.

Policy exceptions are scoped by workload, reason, and UTC expiry. Add them through `PUT /api/policies` in the `policy_exceptions` array; an expired exception stops suppressing the workload automatically. They do not bypass safety checks for other workloads.

## Planted scenario evaluation

Run `python scripts/evaluate_scenarios.py` from the repository root to regenerate the table and aggregate metrics below. Boundary scenarios plant controlled usage values so each rule is tested directly.

| ID | Scenario | Expected | Actual | Result |
|---|---|---|---|---|
| SCN-01 | Safe over-provisioning opportunity | recommend small reduction | approved | PASS |
| SCN-02 | Protected critical workload | block | rejected | PASS |
| SCN-03 | Active business event freeze | defer | deferred | PASS |
| SCN-04 | Incident memory protection | defer or block | rejected | PASS |
| SCN-05 | Insufficient data | defer for insufficient data | needs review | PASS |
| SCN-06 | Maximum reduction cap | block or clamp | rejected | PASS |
| SCN-07 | Limits preservation | request-only patch | approved; patch contains no limits | PASS |

Current fixture results:

- Scenario pass rate: **7/7 (100%)**.
- Planted safe over-provisioning recall: **1/1 (100%)**.
- Risk-scenario false-positive rate, defined as an approved cut in a protected/event/incident case: **0/3 (0%)**.
- Event/incident reduction suggestions: **0/2**, target **0**.
- Limit preservation: **1/1**, target **100%**.

These are small, deterministic acceptance cases, not a statistically meaningful false-positive estimate. Add more labeled risky and safe workloads before using the rates to compare releases.
