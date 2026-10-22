# Shared contract (Dev 1 ⇄ Dev 2)

Source of truth: `backend/app/models/schemas.py`. Change it only via a PR both developers approve.

## Decisions made while merging the two guides (confirm with Dev 2 on Day 1)
| Topic | Conflict | Decision |
|---|---|---|
| UI / API | Proposal & Dev 1 guide say Streamlit + flat `finops/`; Dev 2's *updated* guide says FastAPI + React | **FastAPI + React** (newer doc). Dev 1 code lives in `backend/app/services/`. |
| Field name | Dev 1: `service`; Dev 2: `workload_id` | **`workload_id`** everywhere (= service name in deployments.yaml). |
| Events file | `events.json` vs `business_events.json` | **`business_events.json`** |
| Extra inputs | Dev 2 needs incidents + namespace | Added `incident_history.csv`, `namespace` in deployments.yaml, `policy.yaml`. |
| Dev 1 statuses | `proposed / no_change / needs_review` | Kept (`ProposalStatus`). Critic maps them to `approved / deferred / rejected / needs_review / no_change` (`DecisionStatus`). |
| Dev 1 model | dict-based `InputBundle` | Pydantic models (same names, validated). |

## Units
CPU = integer **millicores**; memory = integer **MiB**; timestamps ISO-8601 with timezone. Requests only — limits are context, never changed.

## Hand-off interface
```python
load_inputs(data_dir) -> InputBundle
validate_inputs(bundle) -> list[ValidationIssue]
build_proposals(bundle, now=None) -> list[OptimizationProposal]   # one per service, never empty
```
Dev 2 can start now from `data/sample_analysis_response.json` (a valid `AnalysisResponse`).

## Agent review cycle additions

The agent mode adds fields to the shared contract. All are additive and defaulted, so an older payload still validates.

`WorkloadResult` gained:

| Field | Type | Meaning |
|---|---|---|
| `confidence_score` | `float \| None` (0–100) | Agent-level confidence. Distinct from `proposal.confidence.score`, which scores the *proposal's* factors. **Null in pipeline mode**, where no agent runs: a default of `0.0` would read as "the agent is certain of nothing" rather than "there was no agent". |
| `confidence_basis` | `str` | One line explaining how `confidence_score` was derived. |
| `evidence_trail` | `list[str]` | One line per tool call the agent made. |
| `objections` | `list[CriticObjection]` | Red-team objections from the Critic phase. |
| `cycles` | `list[ReviewCycle]` | The Proposer → Critic → Judge phases, in order. Populated in agent mode; empty in pipeline mode. |
| `historical_lessons` | `list[str]` | Human rejections from prior reviews of this workload, injected into the proposer's prompt. |

`CriticObjection` is `{code, severity, message, source}`. `severity` is `"blocking"` or `"advisory"`; `code` is a stable identifier; `source` names the tool the objection is grounded in.

## Savings the critic held back

`OptimizationProposal` gained two fields, so a refusal is visible instead of silent:

| Field | Type | Meaning |
|---|---|---|
| `suppressed_saving_usd` | `float` | The monthly saving the optimizer found and a safety rule refused. `0.0` when nothing was suppressed. |
| `suppressed_proposal` | `ResourceSettings \| None` | The candidate request the optimizer proposed before the critic suppressed it. |

When the critic defers a reduction it no longer erases the finding: `proposed` is set to `null` and `estimated_monthly_saving_usd` to `0.0`, and the refused candidate and its saving move into these two fields. The counted saving (`WorkloadResult.monthly_savings_estimate_usd`) stays `0.0`, so a deferred reduction is never counted as money.

**Potential = `estimated_monthly_saving_usd + suppressed_saving_usd`.** Any total that means "what the optimizer found" must include the suppressed part; any total that means "what was approved" must not. `GET /api/dashboard/summary` reports both as `potential_savings_usd` and `estimated_monthly_savings_usd`, with the difference as `held_back_usd`.

`AgentAuditLog` gained `cycles: list[ReviewCycle]`, `confidence_score`, `evidence_trail`, and `historical_lessons`. A `ReviewCycle` is `{role, summary, steps, objections, verdict, started_at, completed_at}`, with `role` one of `"proposer"`, `"critic"`, `"judge"`, and `steps` a list of `ToolCall` (`{timestamp, tool, params, result, thought}`).

`WorkloadResult.cycles` and `WorkloadResult.historical_lessons` mirror the same two `AgentAuditLog` fields. They exist on the result so a reviewer can read the reasoning behind a decision without a second call to the audit endpoint — the reasoning is part of the decision, not a side channel. `ToolCall` and `ReviewCycle` are declared above `WorkloadResult` in `schemas.py` to keep the forward reference resolvable.

`POST /api/analyze` accepts `mode`: `"pipeline"` (default) or `"agent"`. Both return the same `AnalysisResponse` shape and, by design, the same decisions — the adversarial phase may only downgrade an approval to `needs_review`. The invariant is asserted by `backend/tests/test_agent_api.py::test_agent_and_pipeline_agree_on_decisions`.

Review records gained `rejection_reasons: list[str]`, `resource: str | None`, and `reviewer_guidance: str | None`. Only rejections become "Historical Lessons" on the next agent run for that workload.

## Endpoints added

| Endpoint | Purpose |
|---|---|
| `GET /api/policies/defaults` | The built-in `CriticPolicy` defaults, so the policy editor can offer a reset. Nothing is stored by reading it. `GET /api/policies` still returns the live policy. |
| `GET /api/validation` | Already existed; `AnalysisResponse.data_health` now carries the same `ValidationResponse` the endpoint returns, computed from the bundle that produced the analysis. |

`AnalysisResponse.data_health` was already in the schema but was never populated. It is now filled in by both the pipeline and the agent path, so the UI can show per-workload metric completeness and freshness without a second call.

## Demo scenarios baked into `data/`
| Service | Expected optimizer | Expected critic |
|---|---|---|
| payment-api | proposed | approved |
| checkout-service | proposed | deferred (campaign in 23h) |
| email-worker | needs_review | needs_review |
| session-store | no_change | no_change |
| recommendation-api | proposed | deferred (incident INC-2041) |

The demo clock is fixed in `data/policy.yaml` (`simulation_now`). Regenerate fixtures with `python scripts/generate_fixtures.py`.
