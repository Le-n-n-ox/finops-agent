# Kubernetes Over-Provisioning FinOps Agent

A recommendation-only FinOps prototype. The optimizer proposes lower Kubernetes CPU and memory **requests** from historical usage. A deterministic critic checks those proposals against P99 safety floors, business events, incident history, and estimated savings. A human reviews the result and any generated YAML patch; the application never changes a cluster.

## What it does

1. Loads deployments, usage history, business events, incidents, policy, and an illustrative cost model.
2. Computes per-workload usage percentiles and a candidate request.
3. Applies deterministic data-quality, freshness, P99, and minimum-reduction checks.
4. Has the critic approve, defer, reject, or request review, with evidence for its decision.
5. Runs the same decision path inside a **Proposer → Critic → Revision → Judge** review cycle that adds red-team objections, the proposer's answer to them, an evidence trail, and a confidence score.
6. Returns a report and review-only YAML patch for approved recommendations.
7. Carries human rejections forward as "Historical Lessons" into the next analysis.

The Pydantic models in `backend/app/models/schemas.py` define the shared input and output contract. Units are CPU millicores, memory MiB, and timezone-aware ISO-8601 timestamps. Kubernetes limits are included as context and are never changed.

## Quick start (from a clean clone)

Python 3.11+ and pip are the only requirements for the API. No Zetaris tenant, no model server:

```bash
git clone <this repository> finops-agent
cd finops-agent

python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt

cp .env.example .env                 # Windows: copy .env.example .env
export SAMPLE_MODE=true              # Windows: $env:SAMPLE_MODE="true"

uvicorn app.main:app --port 8000 --app-dir backend
curl -s localhost:8000/api/health
# {"status":"ok","mode":"demo","sample_mode":"true","data_source":"local","llm_backend":"simulated"}
```

`SAMPLE_MODE=true` reads the local fixtures and answers with the deterministic stand-in — nothing
external is contacted, and the response says so (`llm_backend: "simulated"`). Drop the variable and
`.env` decides instead; see [Dependencies](#dependencies).

Frontend, in a second terminal (needs Node 18+):

```bash
cd frontend && npm install && npm run dev      # http://localhost:5173, proxies /api to :8000
```

Check the install:

```bash
python -m pytest backend/tests -q              # 250 passed
```

The agents run as a local FastAPI service. There is **no Google Colab notebook** and no Colab link:
the review cycle needs a long-running process and a model server, neither of which a notebook
provides well.

## Usage

Every route is under `/api`. `POST /api/analyze` runs the review; everything else reads the result.

```bash
# Run the review over every workload, and keep the report id
curl -s -X POST localhost:8000/api/analyze \
     -H 'Content-Type: application/json' -d '{"mode":"agent"}' > analysis.json

# Read the last saved review without running anything
curl -s localhost:8000/api/analysis/latest | jq '.summary'

# What-if: re-run the deterministic critic against a different request
curl -s -X POST localhost:8000/api/simulate -H 'Content-Type: application/json' \
     -d '{"workload_id":"image-resizer","cpu_request_millicores":900,"memory_request_mib":4096}'

# The report the UI downloads (JSON or Markdown)
curl -s 'localhost:8000/api/report?format=markdown' | head -40
```

`mode` is accepted in the body and ignored: the agent cycle is the only reasoning path.

## Samples

Three inputs and their real outputs, captured from `SAMPLE_MODE=true`.

**1. The whole review** — `POST /api/analyze` with `{"mode":"agent"}`:

```json
{
  "workloads_evaluated": 12,
  "approved": 4,
  "deferred": 4,
  "rejected": 0,
  "needs_review": 0,
  "no_change": 4,
  "estimated_monthly_savings_usd": 78.25
}
```

**2. One workload from that report** — `results[?workload_id='docs-renderer']`:

```json
{
  "workload_id": "docs-renderer",
  "decision": "approved",
  "risk_level": "low",
  "monthly_savings_estimate_usd": 27.5,
  "confidence_score": 100.0,
  "current":  {"cpu_request_millicores": 800, "memory_request_mib": 3072},
  "proposed": {"cpu_request_millicores": 250, "memory_request_mib": 3072},
  "objections": []
}
```

Memory is untouched: the review objected to lowering it (the workload was OOMKilled) and the
proposer narrowed the change to CPU only. The trace below is how that happened.

**3. A what-if** — `POST /api/simulate`:

```json
// input
{"workload_id": "image-resizer", "cpu_request_millicores": 900, "memory_request_mib": 4096}

// output
{
  "workload_id": "image-resizer",
  "original_decision": "approved",
  "simulated_decision": "approved",
  "cpu_change_pct": -10.0,
  "estimated_monthly_saving_usd": 5.0,
  "cpu_headroom_pct": 109.0,
  "label": "Simulation only — not the official report. Nothing was saved or applied."
}
```

## Traces

Every result carries the phases that produced it, and every response names the model that answered.
For `docs-renderer`:

| Phase | Tools called | Verdict | Summary |
|---|---|---|---|
| proposer | `get_workload_metrics`, `analyze_rightsizing`, `validate_policy` | — | usage summary and right-sizing result gathered; the proposal is with the policy critic |
| critic | `search_logs`, `get_dependencies`, `search_logs` | — | 1 blocking and 0 advisory objection(s) raised from the tool evidence |
| revision | — | `narrow` | kept the CPU reduction and gave memory back to its current request: the memory objection stands |
| judge | — | `accept` | no objection survived review; the proposer's evidence stands on its own |

The same data is in the response as `results[].cycles[]`, with each phase's `summary`, `steps`
(tool, parameters, result) and `verdict`, so a reviewer can replay the reasoning rather than trust
the prose. `results[].evidence_trail` is the one-line version of the same calls.

**Which model handled the request** is named on the response, not inferred:

| Run | `llm_backend` | `llm_model` |
|---|---|---|
| `SAMPLE_MODE=true` | `simulated` | `null` — the deterministic stand-in answered, and the UI says so |
| Nightshift hotspot reachable | `openai-compatible` | `local-runtime/llama-3.3-70b-instruct` (`llm_base_url: http://127.0.0.1:8088/v1`) |

One model answers every turn of a run; the response names it once. There is no per-phase model
routing, and nothing claims a model answered when the stand-in did.

## One analysis path: the agent cycle

`POST /api/analyze` runs the **agent cycle** — the deterministic optimizer and Context Critic, wrapped in a Proposer → Critic → Judge review cycle — and waits for it. `POST /api/analyze/stream` runs the same analysis and sends each workload's result as it finishes; the UI uses it so a slow run looks like work in progress rather than a dead page. `GET /api/analysis/latest` returns the last saved review without running anything. There is no mode to pick. The request body still accepts a `mode` field for compatibility with older frontends, but the backend ignores it.

| Path | What runs | What it changes |
|---|---|---|
| agent cycle (the only one) | Deterministic optimizer → deterministic Context Critic, inside a Proposer → Critic → Revision → Judge review cycle. | The reasoning, objections, evidence trail, and confidence score — never the decision. |

The deterministic critic owns every final status. The adversarial phase can only *downgrade* an approval to `needs_review`; it can never approve, reject, or defer, and it can never change a number. Every number that drives a decision comes from a tool result, never from the model: numbers the model writes in prose are checked back against the tool results, and any that do not trace lower the confidence score instead of being trusted. Nothing is ever applied to a cluster.

The model is disclosed, not assumed. The response carries `llm_backend`, `llm_model`, and `llm_base_url`, and the UI names the model that actually ran. `GET /api/llm/status` reports the same before any analysis has run. If the model server is unreachable, the app still runs on a deterministic stand-in and says so — in the header badge, in the provenance strip, and in the API response. It never implies a model ran when it did not.

## Deterministic calculation

Optimizer parameters live in `data/policy.yaml` and can be changed without changing code:

| Parameter                    |             Demo value | Purpose                                               |
| ---------------------------- | ---------------------: | ----------------------------------------------------- |
| `min_samples`              |                     24 | Minimum usage observations required per workload      |
| `min_span_hours`           |                     24 | Minimum time span covered by observations             |
| `max_metric_age_hours`     |                     72 | Older latest observation triggers `needs_review`    |
| CPU P95 / P99 multipliers    |            1.25 / 1.10 | Headroom factors applied to CPU percentiles           |
| Memory P95 / P99 multipliers |            1.30 / 1.15 | Headroom factors applied to memory percentiles        |
| CPU / memory rounding units  | 10 millicores / 64 MiB | Candidate requests round up to these increments       |
| `min_reduction_pct`        |                     15 | Minimum reduction required for an individual resource |

For each resource, the optimizer sorts the samples and calculates P95 and P99 using linear interpolation at position `(n - 1) × percentile / 100`. It calculates the candidate as:

```text
candidate = round_up(max(P95 × P95_multiplier, P99 × P99_multiplier), rounding_unit)
```

A resource is eligible only when its P99 is no greater than the current request, the candidate is lower than the current request, and the candidate is at most 85% of the current request (the configured 15% reduction floor). CPU and memory are evaluated independently: an eligible resource can be reduced while the other stays at its current request. Requests are never increased. Missing, too-short, or stale histories produce `needs_review`; workloads without an eligible reduction produce `no_change`.

The critic independently checks that the proposal stays at or above its configured P99 safety floors (`1.10 × CPU P99` and `1.15 × memory P99` by default). It also checks upcoming business-event risk, incident history, and the minimum estimated monthly savings. Deterministic checks determine the outcome; the model can phrase an explanation but cannot change the decision.

## Agent review cycle

`backend/app/services/agent_orchestrator.py` runs each workload through four bounded phases and records them as `ReviewCycle` objects in the audit log:

| Phase | Role | Bound |
|---|---|---|
| Proposer | Gathers evidence with tools and argues for or against a reduction. | 10 iterations |
| Critic | Red-teams the proposal. May call read-only tools to ground its objections. | 1 iteration |
| Revision | Answers the blocking objections: concede, narrow the change to one resource, or stand by it. | 1 turn, and only when a change is on the table |
| Judge | Weighs the objections that survive against the deterministic verdict. | 3 iterations |

The critic's bound is one turn because its objections do not come from the model: they are raised
deterministically from the retrieved evidence (`adversarial_service.raise_objections`), and the
judge's verdict and rationale are computed before its own model call, which only adds two
sentences of narration. The critic used to spend four turns — half of a workload's round trips —
on prose that decided nothing. The evidence it would have fetched, the logs and the dependency
map, is retrieved before its turn and inlined in its prompt, so one turn is enough to state the
objections. If the model spends that turn calling a tool instead, the phase summary falls back to
a deterministic sentence; the objections themselves are unaffected.

The revision phase is what turns the cycle from a pipeline into a loop. Without it the critic
objected, the judge escalated, and the proposal that never got to answer was the one published.
The proposer now answers in one of three ways — **concede**, **narrow** to one resource, or
**stand by** the change — and it still cannot touch a number: a narrowing gives one resource back
to its current request, the deterministic critic re-decides the narrowed change, and the saving is
recomputed for what is actually being changed. The objections are then re-raised against the
proposal that survived, so an objection the revision answered stops escalating a change nobody is
making any more.

The same four phases can run on either of two engines, chosen by `REVIEW_ENGINE`:

| Value | What runs | When to use it |
|---|---|---|
| `native` (default) | The phases as a sequence of calls in `agent_orchestrator.py`. | Everything. No dependency, one code path to read. |
| `langgraph` | The same four phase functions as a LangGraph state machine: nodes are the phases, the state is the audit log, and the conditional edge is the revision decision (`backend/app/services/review_graph.py`). | When you want the loop visible as a graph rather than inferred from an async function. |

The graph is not a second implementation: every node calls the orchestrator's own phase method, and
`backend/tests/test_review_engine_parity.py` runs both engines over the fixture and fails if they
disagree on any workload's decision, savings, confidence or objection list. A broken or missing
`langgraph` falls back to the native sequence and logs why, so the engine setting can never cost a
workload its review.

The Critic's objections are grounded in evidence the agent actually retrieved, not invented. The stable codes are `RECURRING_EVENT_UNMODELLED`, `INCIDENT_OVERLAP_IGNORED`, `LOG_PRESSURE_IGNORED`, `DEPENDENCY_PRESSURE_IGNORED`, `VERIFICATION_GAP`, and `THIN_EVIDENCE`; each carries a `blocking` or `advisory` severity.

The tools the cycle reasons with:

- **`get_workload_metrics`** summarises a workload's usage instead of dumping it: sample count, window, CPU and memory p50/p95/p99, the peak and when it happened, plus a series downsampled to about 48 points. A month of hourly rows is 720 samples and roughly 98 KB of JSON, which is more than a prompt should carry and more than a character cap can cut cleanly — the old cut left the model an unparseable fragment of the oldest week, with the peak outside it. The percentiles and the peak are computed over every sample; only the series is thinned.
- **`search_logs`** returns simulated container logs for a workload, including `OOMKilled`, CPU throttling, and eviction entries. A log that reports memory pressure raises a blocking objection against reducing the memory request.
- **`get_dependencies`** maps the upstream services a workload depends on, so an incident on an upstream dependency is visible rather than a surprise.

The logs and the dependency map are retrieved for every review, by the orchestrator, before the Critic's first turn. The
objections they ground are blocking ones, and the deterministic critic has no log rule of its
own to fall back on — so if the evidence depended on the model choosing to ask for it, a model
that did not ask would have the objection suppressed and the workload approved on the strength
of an omission. The evidence is in the audit trail, so a reviewer sees it too.

The model chooses which tool to call, so the tools are bound to the workload under review: every
workload-scoped tool refuses another workload's id and says which one to use. The model
therefore cannot choose *which* proposal the safety check judges, and a verdict about another
workload is never published under this one's name. The proposal judged is always the one the
deterministic optimizer produced — a copy the model echoes back is accepted and ignored.

### Confidence score

`WorkloadResult.confidence_score` (0–100) and its one-line derivation `confidence_basis` are computed in `backend/app/services/verification_service.py`:

```text
score = 0.60 × traceability + 0.40 × evidence − overlap penalty − objection penalty
```

Traceability is the share of numbers in the report that appear in a tool result — a fabricated figure is the failure mode that matters most, so it is weighted highest. Evidence combines sample sufficiency, metric freshness, and freedom from incident/event overlap. The objection penalty scales with the number and severity of objections, so risky workloads score visibly lower than clean ones instead of collapsing to a single value.

`evidence_trail` lists the tool calls the agent made, and `objections` carries the Critic's findings. All three are shown in the workload detail panel and in the Markdown report.

### Reviewer feedback memory

A review submitted through `POST /api/reports/{report_id}/review` may carry `rejection_reasons`, `resource`, and `reviewer_guidance`. `Store.get_feedback_for_workload` reads them back, and the orchestrator injects them into the proposer's system prompt as "Historical Lessons" on the next run for that workload — so a reduction a human already rejected does not get re-argued from scratch. Only rejections become lessons; an acceptance is not a signal to change behaviour.

The review log is append-only: SQLite triggers reject `UPDATE` and `DELETE` on the `reviews` and `audit_log` tables.

## Savings estimate and limitations

The demo estimate uses the rates in `data/cost_model.json`:

```text
monthly estimate =
  ((CPU request reduction in cores × CPU cost per core-month)
   + (memory request reduction in GiB × memory cost per GiB-month))
  × replica count
```

The included rates ($25 per CPU core-month and $4 per GiB-month) are illustrative values, **not a cloud-provider quote or a forecast of an actual bill reduction**. This simple model does not account for provider, region, commitment or discount terms, node packing, autoscaling, shared overhead, workload changes, or billing granularity. Treat savings as directional demo estimates; validate against your own pricing and cluster utilization before making a business decision.

## Data quality and recommendation evidence

The optimizer attaches a per-workload data-quality assessment, usage summary, metric window, confidence factors, detected anomalies, incident evidence, savings assumptions, and priority breakdown to each proposal. These fields extend `OptimizationProposal` in the shared schema; the optimizer status remains `proposed`, `no_change`, or `needs_review`. Only the Context Critic assigns final decisions.

Usage percentiles use linear interpolation at position `(n - 1) × p`. P99 is included in `UsageSummary` only when the sample count reaches `optimizer.p99_min_samples` (100 by default); the existing P99 floor calculations remain conservatively available to the critic and are marked `p99_reliable: false` below that threshold. Trend hints compare means from the first and last quarters of the observed window. Anomaly detection compares a configurable recent sample window with its preceding mean baseline; default thresholds are a 1.5× rise and a minimum absolute increase of 100 millicores or 128 MiB.

Confidence is a deterministic weighted score: validation 20%, sample sufficiency 25%, freshness 20%, usage stability 20%, and anomaly evidence 15%. Invalid or insufficient history caps the score below 40. Priority combines opportunity value (40%) and confidence (60%), then subtracts explicit anomaly and incident penalties. It is for triage only and never changes the critic's decision.

Incident matches are exact-workload matches. A namespace match is labelled `direct`; missing or different namespace is labelled `indirect`. Empty or irrelevant incident history yields no fabricated evidence and adds a warning. Currency savings are produced only when both CPU and memory rates are configured. Without both rates, the proposal reports relative request-allocation reductions and leaves USD savings unset. All monetary figures scale by replicas and the requested number of days from a 30-day month.

## Frontend

`frontend/` is a React + TypeScript + Vite application. The backend exposes the analysis; the
frontend makes it reviewable.

It opens on a **landing page** that explains the system and asks nothing of the backend — no
analysis runs until the reader steps into the workspace, which is the difference between a page
that loads in a second and one that appears to hang. Stepping in opens the **last saved review**
(`GET /api/analysis/latest`) rather than starting a new one: a full run is minutes of model time,
and paying it again before showing anything is what made the workspace feel stuck. The banner
above the results names the run's timestamp and offers a re-run, which streams a fresh agent
cycle (`POST /api/analyze/stream`); only a database with no saved report yet runs on entry. From
there the work is a workspace with a sidebar, and the route is the URL: a workload has its own
page, so a link to one can be pasted to someone else and it opens on that workload.

| Route | Section | What it is for |
|---|---|---|
| *(no hash)* | Landing | What the tool does, and why it is safe to trust. Nothing runs. |
| `#/` | Overview | The money: what is on the table, how much of it is approved, and whether that number is moving. |
| `#/` → Analysis | Analysis | The findings, and the evidence behind each one. |
| `#/` → Policy | Policy | The critic's guardrails, editable. |
| `#/` → History | History | Every decision the critic has made, across reports. |
| `#/workload/<id>` | Workload | One workload: its proposal, the evidence, the review cycle and the patch. |

The route is a hash rather than a path, because the app is served as static files: a deep link
to `/workload/x` would 404 on reload, while `#/workload/x` resolves however it is hosted.

The panels that carry the agent's work:

| Panel | What it shows | Endpoint |
|---|---|---|
| **Cycle** tab (detail panel) | The Proposer → Critic → Revision → Judge phases as they ran: each phase's summary, the tools it called, the objections it raised, and the Judge's ruling. | `GET /api/analysis/latest`, `POST /api/analyze/stream` |
| **What-if simulator** | Move the CPU/memory request sliders and the deterministic critic re-decides against your numbers. Nothing is saved and no patch is produced. | `POST /api/simulate` |
| **Review history** | What a human already decided about this workload, with the structured rejection reasons — the exact text the agent replays as "Historical Lessons" next time. | `GET /api/reports/{id}`, `GET /api/decisions` |
| **Decision history** (History page) | Every decision the critic has made, across reports, with a search box, a status filter, and a validity column. A decision whose metrics have moved since it was made is marked stale — and the backend refuses to accept a stale decision for implementation. | `GET /api/decisions`, `GET /api/reports/{id}` |
| **Trend across analyses** | Approved savings over successive runs, with deferred and needs-review counts on the second axis. | `GET /api/dashboard/summary` |
| **Business events** | Campaigns and freezes split into live / upcoming / past, with the services each one puts at risk. | `GET /api/events` |
| **Safety policy** | The critic's guardrails, editable — every field the critic reads, not a selection. Saving appends a new policy version and flags earlier reports as expired. | `GET`/`PUT /api/policies`, `GET /api/policies/defaults` |
| **Savings potential** | Everything the optimizer found, how much survived the safety rules, and what was held back. A deferral is shown with its price, not as a gap in the output. | `GET /api/analysis/latest`, `POST /api/analyze/stream` |
| **Top opportunities** | Findings ranked by savings × confidence ÷ risk, so the short list is at the top rather than buried. | `GET /api/analysis/latest`, `POST /api/analyze/stream` |

A **provenance strip** sits above the analysis on every page: the policy version, the rule version,
the input fingerprint and the run id, so a recommendation can be traced to the rules and the data
that produced it. It also carries the model disclosure: it names the model that ran, and when the
run fell back to the deterministic stand-in it says so plainly in amber — a cycle driven by a
stand-in is never presented as a live language model.

There is no reasoning-mode toggle. The app always runs the agent cycle, and the header badge names
the model that actually ran (for example `Live API · agent cycle · local-runtime/gpt-oss-20b`) or
states plainly that the deterministic stand-in was used. The workflow strip always shows the
agent-cycle stages, so the stages shown are the ones that actually produced the numbers on screen.
The export button writes the report you are looking at — same `analysis_id`, same decisions — not a
fresh run.

Printing is a first-class path: the detail panel's tabs are all mounted, so a printed report
contains the evidence, the review cycle, the critic's checks and the patch, not only whichever tab
happened to be open. The print stylesheet forces the light palette, so a report printed from a
dark-mode screen is not white text on white paper.

## Demo data

The `data/` directory contains synthetic fixture inputs: `deployments.yaml`, `usage_history.csv`, `business_events.json`, `incident_history.csv`, `policy.yaml`, and `cost_model.json`. The policy includes a fixed `simulation_now` so the demo scenarios and freshness decisions are repeatable. `data/sample_analysis_response.json` is a sample output. These fixtures demonstrate outcomes; they are not live production telemetry.

## Dependencies

| What | Needed for | Without it |
|---|---|---|
| Python 3.11+ and `backend/requirements.txt` | the API and the tests | nothing runs |
| Node 18+ and npm | the frontend | the API works; no UI |
| A **Meterless Nightshift hotspot** (OpenAI-compatible, `:8088`) | model-written narrations and arguments | `SAMPLE_MODE=true`, or `LLM_BACKEND=simulated` — the deterministic stand-in answers the same turns |
| **Zetaris** (`finops_data` with the four tables) | `DATA_SOURCE=zetaris` | the local fixtures in `data/` (the default) |
| Docker and Docker Compose | the containerised stack | run locally, as in Quick start |

Both external services are optional by design, and each has an explicit off switch: the model by
`LLM_BACKEND=simulated`, the data by `DATA_SOURCE=local`. `SAMPLE_MODE=true` sets both, and reports
itself in `GET /api/health`.

Python packages: `fastapi[standard]`, `pydantic`, `PyYAML`, `pandas`, `httpx`, `python-dotenv`,
`pytest`, and `langgraph` (only used when `REVIEW_ENGINE=langgraph`).

`.env.example` holds placeholders only: every credential line is empty (`METERLESS_API_KEY`,
`NVIDIA_API_KEY`, `ZETARIS_*`), and the rest are documented defaults such as the local base URL and
port numbers. No secret is ever committed, and none is printed by `scripts/check_model.py`.

## Integrations

- **Zetaris:** `backend/app/integrations/zetaris_client.py` queries the deployments, usage, events, and incidents tables from `finops_data`, including paginated query results. Set the `ZETARIS_*` values in the root `.env` to use Zetaris; when it is not configured, the loader uses local fixture files. Local `policy.yaml` and `cost_model.json` remain the source for those configuration values. See [`docs/ZETARIS_SETUP.md`](docs/ZETARIS_SETUP.md).
- **Meterless / Nightshift runner seam:** the orchestrator routes collector, optimizer, and critic steps through `get_runner()`. `AGENT_RUNTIME=meterless` selects the Meterless-named scaffold, but the current runner still executes each function locally; it does not enforce a Markovian context engine. It is an integration seam, not a claim of remote execution. It is separate from the language-model integration below, even though both point at the same hotspot: `METERLESS_BASE_URL` is now the live base URL the agent cycle's model client calls.
- **NVIDIA NIM:** not wired in. `backend/app/integrations/nvidia_nim.py` exists and the `NVIDIA_*` settings in `.env` configure it, but nothing in the application, the scripts or the tests imports it today — setting those values has no effect on a run. It is **not** the model the agent cycle uses; that is the local server below. Deterministic critic checks remain authoritative either way.
- **Language model (the one the agent cycle uses):** the local **Nightshift / meterless hotspot**, an OpenAI-compatible API on the host. Configure it with `METERLESS_BASE_URL` (e.g. `http://127.0.0.1:8088/v1` on a host run, `http://<host-lan-ip>:8088/v1` in Docker), `METERLESS_MODEL` (e.g. `local-runtime/gpt-oss-20b`), and either `METERLESS_API_KEY` or `METERLESS_TOKEN_FILE`. When none is set, the app auto-discovers the token file that sits beside the hotspot. The model proposes and argues; it never decides. Whatever it writes, the deterministic critic still owns the status. When no model is reachable, a deterministic stand-in runs instead and the API response and the UI both say so.

Run `python scripts/check_model.py` to see whether the model server is reachable and which credential works. It prints key sources by name and path only, never a token.

More details: [`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md), [`docs/CONTRACT.md`](docs/CONTRACT.md), and [`docs/FINOPS_METHOD.md`](docs/FINOPS_METHOD.md) for the sizing formula, risk findings, the agent review cycle, and measurable scenario results.

## Tests and conformance checks

```bash
python -m pytest backend/tests -q          # 250 passed
python scripts/evaluate_scenarios.py       # planted-scenario acceptance table
python scripts/check_model.py              # is the Nightshift hotspot reachable, and with which credential?
python scripts/check_zetaris_query.py      # does the Zetaris connector return the four tables?
```

`scripts/evaluate_scenarios.py` replays the labelled scenarios in `data/test_scenarios.json` and
reports expected vs. actual per scenario, plus recall, false-positive rate, and the count of
event/incident reduction suggestions. Run against the current fixture:

```text
| ID     | Scenario                          | Expected                    | Actual        | Result |
| SCN-01 | Safe over-provisioning opportunity| recommend_small_reduction   | approved      | PASS   |
| SCN-02 | Protected critical workload       | block                       | rejected      | PASS   |
| SCN-03 | Active business event freeze      | defer                       | deferred      | PASS   |
| SCN-04 | Incident memory protection        | defer_or_block              | rejected      | PASS   |
| SCN-05 | Insufficient data                 | defer_insufficient_data     | needs_review  | PASS   |
| SCN-06 | Maximum reduction cap             | block_or_clamp              | rejected      | PASS   |
| SCN-07 | Limits preservation               | validation_error_if_limit_changed | approved | PASS   |

- Scenario pass rate: 7/7 (100.0%).
- Planted safe over-provisioning recall: 1/1 (100.0%).
- Risk-scenario false-positive rate: 0/3 (0.0%).
```

`scripts/check_model.py` is the conformance check for the Meterless/Nightshift side: it probes the
candidate base URLs, reports which credential source works (by name and path, never the value), and
exits non-zero when nothing answers:

```text
Working combination:
  base URL   : http://127.0.0.1:8088/v1
  credential : env METERLESS_API_KEY (value hidden)
  model      : local-runtime/llama-3.3-70b-instruct
  server lists 77 model id(s).
  -> 'local-runtime/llama-3.3-70b-instruct' is present on the server.

OK: the local model server is reachable and authenticated.
```

`scripts/check_zetaris_query.py` is the same check for the data side: it runs a query against each
of the four `finops_data` tables and reports row counts. See [`docs/FINOPS_METHOD.md`](docs/FINOPS_METHOD.md)
for the scenario table's caveats.

## Run with Docker Compose

Start the backend API and Vite frontend together from the repository root:

```bash
docker compose up --build
```

Open `http://localhost:5173` for the frontend. It proxies `/api` requests to the backend container. The backend API remains available at `http://localhost:8000`.

Both host ports are configurable, because 8000 and 5173 are commonly owned by something else on the same machine — another project's container, or a local dev server. If `docker compose up` fails with `port is already allocated`, set the host ports in `.env`:

```bash
# in .env
FINOPS_API_PORT=8080                   # published as host:8080 -> container:8000
FINOPS_WEB_PORT=5173                   # published as host:5173 -> container:5173
```

The ports **inside** the containers are always 8000 and 5173, so the frontend's proxy to `finops_agent:8000` does not change when the host port does.

### The fast demo

A full analysis is a multi-turn conversation with the model server for every workload. On a
machine with no GPU that is minutes per run — which is the wrong thing to be looking at while
you are trying to show somebody what the tool does.

```bash
python scripts/demo_mode.py fast     # the deterministic stand-in: the whole run in seconds
python scripts/demo_mode.py live     # back to the real model server
python scripts/demo_mode.py status   # which one is running
```

The stand-in answers the same turns from the same tools and produces the same decisions — it is
the same agent cycle with a scripted reasoner instead of a local model. Nothing about the run is
dressed up as something it was not: the response carries `"llm_backend": "simulated"`, the
header badge says so, and the provenance strip says so.

It is a compose override rather than a flag on the main compose file, so the default stays the
live model — the one that proves anything — and "which mode am I in?" is answerable by looking
at how the stack was started.

The backend container needs to reach the model server, which runs on the **host**. A container reaches the host through `host.docker.internal` (Docker Desktop's alias for the host gateway) or through the host's LAN address; the container's own `127.0.0.1` is the container, not the host, so it never reaches the hotspot. The defaults already use `host.docker.internal`, so this usually needs no configuration. To point at the host's LAN address instead:

```bash
# in .env
METERLESS_HOST_IP=192.168.1.7          # the host's LAN address
METERLESS_STATE_DIR=C:/Users/you/AppData/Local/ai.meterless.runtime
```

`METERLESS_STATE_DIR` is the directory holding the hotspot's `proxy-token`; it is bind-mounted read-only into the container at `/run/nightshift`, and the backend reads the token from `/run/nightshift/proxy-token`. `METERLESS_CONTAINER_BASE_URL` overrides the whole URL if you would rather set it directly. The defaults keep `docker compose up` working on a machine without the hotspot installed — the backend then falls back to the deterministic stand-in and says so.

The API also exposes `GET /api/validation` for ingestion issues and per-workload sample coverage/freshness. `GET /api/report?format=json` and `GET /api/report?format=markdown` generate a fresh audit report with proposals, critic checks, savings estimates, warnings, and review-only YAML patches. The dashboard includes the same health summary in its analysis response and exports reports through the report endpoint when the live API is available.

## Run locally

From the repository root, create and activate a virtual environment, install backend dependencies, then start the API:

```bash
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows PowerShell
# .venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
```

Copy `.env.example` to `.env` and set only the integrations you intend to use. The backend loads that file at startup (`backend/app/config.py`); a real environment variable still wins over it, so a container's or CI's environment always takes precedence. The agent cycle's model server is the local Nightshift / meterless hotspot; the `METERLESS_*` settings point at it, and its bearer token lives in a state directory beside it (on Windows: `%LOCALAPPDATA%\ai.meterless.runtime\proxy-token`). The app discovers that file on its own, so an empty `METERLESS_API_KEY` is fine. The `NVIDIA_*` settings are for the separate, optional explanation-only NIM integration and are not what the agent cycle uses.

`LLM_BACKEND` decides which reasoner answers the agent turns:

- `auto` (the default) probes for the model server and uses it when one answers, falling back to the deterministic stand-in when none does. The response says which one ran, and the UI shows it.
- `simulated` pins the deterministic stand-in. No model server is contacted even when one is running — use it for a reproducible demo, or in CI. The test suite pins it, so a suite that runs next to a model server is still offline, fast and deterministic.

Start FastAPI from the repository root:

```bash
uvicorn app.main:app --reload --port 8000 --app-dir backend
```

Check the model server before you trust a run:

```bash
python scripts/check_model.py
```

It reports which base URLs answer `/v1/models`, which key sources were found (by name and path only — never a token), and the working combination. It exits non-zero when nothing works.

A full analysis is a multi-turn tool-calling review for **every** workload, and each turn is a round trip to the model server. A workload takes about five turns — roughly three gathering evidence, one for the adversarial review and one for the judgement. The workloads are independent of each other, so they are reviewed side by side rather than in turn. With a local 70B model that is minutes for a whole run, not seconds — the run is not stuck, it is reasoning. If you want a run that finishes in seconds, pin the deterministic stand-in with `LLM_BACKEND=simulated`; the response then says `"llm_backend": "simulated"` so nobody mistakes it for a model's work.

`FINOPS_WORKLOAD_CONCURRENCY` (default 4) caps how many workload reviews are in flight at once. Raise it when the model server has capacity; set it to 1 to review one workload at a time. It is bounded rather than unlimited because the model server is the scarce resource: unbounded fan-out queues requests behind the server's own limit and trades latency for timeouts.

If the model server goes away mid-run, the review is cut short rather than thrown away: a dropped connection or a 5xx is retried, and if the server stays down the phase ends with the evidence it had and the deterministic critic still decides the workload. The report says so — on the result (`confidence_basis`), in the cycle summary, and in `warnings`, each naming the workload and the cause. A short review is never presented as a complete one.

The React frontend is in `frontend/`; see [`frontend/README.md`](frontend/README.md) for its development commands. API routes are registered under `/api`.

## Repository map

```text
backend/app/       FastAPI API, schemas, optimizer, critic, orchestrator, integrations
backend/tests/     Backend tests
data/              Demo fixtures and policy/cost configuration
docs/              Shared contract and integration guides
frontend/          React + TypeScript + Vite application
scripts/            Fixture generation and integration checks (check_model.py diagnoses the model server;
                   demo_mode.py switches the stack between the live model and the stand-in)
```
