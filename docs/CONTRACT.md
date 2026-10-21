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
| `confidence_score` | `float` (0–100) | Agent-level confidence. Distinct from `proposal.confidence.score`, which scores the *proposal's* factors. |
| `confidence_basis` | `str` | One line explaining how `confidence_score` was derived. |
| `evidence_trail` | `list[str]` | One line per tool call the agent made. |
| `objections` | `list[CriticObjection]` | Red-team objections from the Critic phase. |

`CriticObjection` is `{code, severity, message, source}`. `severity` is `"blocking"` or `"advisory"`; `code` is a stable identifier; `source` names the tool the objection is grounded in.

`AgentAuditLog` gained `cycles: list[ReviewCycle]`, `confidence_score`, `evidence_trail`, and `historical_lessons`. A `ReviewCycle` is `{role, summary, steps, objections, verdict, started_at, completed_at}`, with `role` one of `"proposer"`, `"critic"`, `"judge"`.

`POST /api/analyze` accepts `mode`: `"pipeline"` (default) or `"agent"`. Both return the same `AnalysisResponse` shape and, by design, the same decisions — the adversarial phase may only downgrade an approval to `needs_review`. The invariant is asserted by `backend/tests/test_agent_api.py::test_agent_and_pipeline_agree_on_decisions`.

Review records gained `rejection_reasons: list[str]`, `resource: str | None`, and `reviewer_guidance: str | None`. Only rejections become "Historical Lessons" on the next agent run for that workload.

## Demo scenarios baked into `data/`
| Service | Expected optimizer | Expected critic |
|---|---|---|
| payment-api | proposed | approved |
| checkout-service | proposed | deferred (campaign in 23h) |
| email-worker | needs_review | needs_review |
| session-store | no_change | no_change |
| recommendation-api | proposed | deferred (incident INC-2041) |

The demo clock is fixed in `data/policy.yaml` (`simulation_now`). Regenerate fixtures with `python scripts/generate_fixtures.py`.
