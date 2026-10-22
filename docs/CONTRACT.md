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

The agent cycle adds fields to the shared contract. All are additive and defaulted, so an older payload still validates.

`WorkloadResult` gained:

| Field | Type | Meaning |
|---|---|---|
| `confidence_score` | `float \| None` (0–100) | Agent-level confidence. Distinct from `proposal.confidence.score`, which scores the *proposal's* factors. **Null when no agent ran**: a default of `0.0` would read as "the agent is certain of nothing" rather than "there was no agent". |
| `confidence_basis` | `str` | One line explaining how `confidence_score` was derived. |
| `evidence_trail` | `list[str]` | One line per tool call the agent made. |
| `objections` | `list[CriticObjection]` | Red-team objections from the Critic phase. |
| `cycles` | `list[ReviewCycle]` | The Proposer → Critic → Judge phases, in order. Populated when the agent cycle ran; empty when it did not. |
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

`POST /api/analyze` no longer selects a reasoning path. The `mode` field is still accepted in the request body for compatibility with older frontends, but it is **ignored**: the agent cycle always runs. The response's `mode` is `"agent"` when the agent cycle ran. There is one reasoning path now.

The invariant that mattered is unchanged and still holds: the adversarial phase may only downgrade an approval to `needs_review`. It can never approve, reject, or defer, and it can never change a number. The deterministic Context Critic owns every final status.

Review records gained `rejection_reasons: list[str]`, `resource: str | None`, and `reviewer_guidance: str | None`. Only rejections become "Historical Lessons" on the next agent run for that workload.

## Endpoints added

| Endpoint | Purpose |
|---|---|
| `GET /api/policies/defaults` | The built-in `CriticPolicy` defaults, so the policy editor can offer a reset. Nothing is stored by reading it. `GET /api/policies` still returns the live policy. |
| `GET /api/validation` | Already existed; `AnalysisResponse.data_health` now carries the same `ValidationResponse` the endpoint returns, computed from the bundle that produced the analysis. |
| `GET /api/llm/status` | Which language model backend is in use, before any analysis has run. |

`AnalysisResponse.data_health` was already in the schema but was never populated. It is now filled in by the agent path, so the UI can show per-workload metric completeness and freshness without a second call.

## Language model disclosure

The agent cycle talks to a language model. Which one — and whether there was one at all — is part of the contract, because a report that looks model-written but was produced by the deterministic stand-in is a false claim.

`AnalysisResponse` gained three fields. All are additive and defaulted, so an older stored payload still validates.

| Field | Type | Meaning |
|---|---|---|
| `llm_backend` | `str` | `"openai-compatible"` when a live model server answered, `"simulated"` when the deterministic stand-in ran. Defaults to `"simulated"`. |
| `llm_model` | `str \| None` | The model id that ran, e.g. `"local-runtime/llama-3.3-70b-instruct"`. `None` when no model ran. |
| `llm_base_url` | `str \| None` | The base URL of the model server that answered. `None` when no model ran. |

A payload with **no** `llm_backend` at all is a third case, and it is not the same as
`"simulated"`: it means the payload does not record which reasoner answered. The bundled mock
fixtures and reports stored before this field existed are both in that state, and neither of them
is a stand-in run. A reader must not upgrade "not recorded" into "the stand-in answered", because
that is a claim about a run that the payload does not describe.

`GET /api/llm/status` returns the same information as a plain JSON object — not wrapped in a response schema — so the frontend can show it before any analysis has run:

```json
{
  "backend": "openai-compatible",
  "model": "local-runtime/llama-3.3-70b-instruct",
  "base_url": "http://127.0.0.1:8088/v1",
  "key_source": "file C:/Users/.../ai.meterless.runtime/proxy-token",
  "detail": null
}
```

| Field | Type | Meaning |
|---|---|---|
| `backend` | `str` | `"openai-compatible"` or `"simulated"`. |
| `model` | `str \| None` | The model id in use, or `None`. |
| `base_url` | `str \| None` | The model server's base URL, or `None`. |
| `key_source` | `str \| None` | Where the credential came from, **by name and path only**. A token value never appears here or anywhere else in the API. |
| `detail` | `str \| None` | Present only when `backend` is `"simulated"`: exactly why the stand-in was used, e.g. `"no API key found for the local model server\"` or `\"model server at http://... did not authenticate (HTTP 401)\"`. |

**A credential never reaches the response, the log, or the report.** The client removes its own token from its own messages, and a pattern-based scrubber removes anything else that looks like one — a `Bearer` header the server echoed back, an `api_key=…` in a URL, a password in a third party's error text. It is applied to the cycle summaries and the warnings, which is where the cause of a failure is published, and to the logs. (The cause of an outage reached the cycle summaries unscrubbed, so a token in a transport error reached every screen that showed the review.)

**Degradation is honest.** If the model server is unreachable or rejects the credential, the app still runs the cycle on the stand-in, sets `llm_backend` to `"simulated"`, fills in `detail`, and says so in the UI. It never silently implies a model ran.

The model server is the local Nightshift / meterless hotspot, an OpenAI-compatible API. It is configured with `METERLESS_BASE_URL`, `METERLESS_MODEL`, `METERLESS_API_KEY`, and `METERLESS_TOKEN_FILE` — see [`.env.example`](../.env.example). `scripts/check_model.py` diagnoses it. The `NVIDIA_*` settings are for the separate, optional explanation-only NIM integration and are **not** what the agent cycle uses.

`LLM_BACKEND` selects the reasoner: `auto` (the default) probes for the model server and falls back to the stand-in when none answers; `simulated` pins the stand-in and never contacts a model server. The pinned mode is what the test suite runs under, so the suite is offline, fast and deterministic on a machine that happens to have a model server running.

The backend loads `.env` at startup (`backend/app/config.py`). A real environment variable wins over the file, so a container's or CI's environment always takes precedence.

The model never decides. Every number in the output still comes from a tool result, every final status still comes from the deterministic Context Critic, and nothing is ever applied to a cluster.

The proposal the safety check approves is the one the deterministic optimizer produced. A model may echo that proposal back to `validate_policy` as `proposal_data`, and it usually does, but the copy is never what is judged: `proposal_data` is accepted and ignored, so the model cannot author the numbers that pass the safety floors. (When a retyped copy was used as-is, a truncated one failed the tool, and a failed tool was briefly mistaken for a verdict — the workload lost its review to the deterministic fallback for a reason that had nothing to do with the workload.)

The model cannot choose *which* proposal is judged either. Every workload-scoped tool is bound to the workload under review and refuses another workload's id, with a message naming the one to use, so a model that names the wrong workload is told so and can retry. (The toolbox used to be shared across the whole run and remembered the last result of every tool, so a model that named a different workload had that workload's proposal judged and its verdict published under the workload actually under review — the critic still decided, but about the wrong workload.) The verdict lookup checks the workload id as well, so a verdict about another workload cannot be published even if one reaches the audit log.

The critic's verdict survives a model that misbehaves. `validate_policy` runs the deterministic Context Critic over the proposal the optimizer produced, so when the agent never calls it, the orchestrator runs the same critic over the same proposal rather than inventing a verdict. The only workload left without a verdict is one the agent never investigated at all, and that one is raised for a human (`needs_review`, with the reason saying so). A model that opens with a plan instead of calling a tool does not end its phase: the phase continues until there is evidence and a policy check, or until the iteration cap is reached.

A model server that goes away is handled the same way, and the difference is stated out loud. A transport failure is retried (a dropped connection, a timeout or a 5xx is transient; a 4xx refusal is not) and, if the server stays down, the phase ends with whatever evidence it had gathered and the deterministic critic still owns the verdict. Three things are published, so a short review can never be mistaken for a complete one:

| Where | What it says |
|---|---|
| `WorkloadResult.confidence_basis` | "The model server became unavailable during the review, so the agent cycle was cut short and the deterministic critic decided this workload on its own." |
| `ReviewCycle.summary` (proposer, critic) | Which phase stopped, after how many tool calls, and the cause — the exception type and its message. |
| `AnalysisResponse.warnings` | One line naming each affected workload and its cause, so the report says which reviews were incomplete. |

A workload the agent never touched *because the model was down* is decided by the deterministic pipeline, not raised for a human: "the agent never investigated" would be the wrong explanation when nobody chose anything. A workload the agent investigated and chose to leave alone is still raised for a human.

Every one of these messages is scrubbed of anything that looks like a credential before it is published, and the client removes its own token from an error message before raising it.

## Demo scenarios baked into `data/`
| Service | Expected optimizer | Expected critic |
|---|---|---|
| payment-api | proposed | approved |
| checkout-service | proposed | deferred (campaign in 23h) |
| email-worker | needs_review | needs_review |
| session-store | no_change | no_change |
| recommendation-api | proposed | deferred (incident INC-2041) |

The demo clock is fixed in `data/policy.yaml` (`simulation_now`). Regenerate fixtures with `python scripts/generate_fixtures.py`.
