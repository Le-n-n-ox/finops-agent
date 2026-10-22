# Kubernetes Over-Provisioning FinOps Agent

A recommendation-only FinOps prototype. The optimizer proposes lower Kubernetes CPU and memory **requests** from historical usage. A deterministic critic checks those proposals against P99 safety floors, business events, incident history, and estimated savings. A human reviews the result and any generated YAML patch; the application never changes a cluster.

## What it does

1. Loads deployments, usage history, business events, incidents, policy, and an illustrative cost model.
2. Computes per-workload usage percentiles and a candidate request.
3. Applies deterministic data-quality, freshness, P99, and minimum-reduction checks.
4. Has the critic approve, defer, reject, or request review, with evidence for its decision.
5. Optionally runs the same decision path inside a **Proposer → Critic → Judge** review cycle that adds red-team objections, an evidence trail, and a confidence score.
6. Returns a report and review-only YAML patch for approved recommendations.
7. Carries human rejections forward as "Historical Lessons" into the next analysis.

The Pydantic models in `backend/app/models/schemas.py` define the shared input and output contract. Units are CPU millicores, memory MiB, and timezone-aware ISO-8601 timestamps. Kubernetes limits are included as context and are never changed.

## Two analysis modes

`POST /api/analyze` takes a `mode`:

| Mode | What runs | What it changes |
|---|---|---|
| `pipeline` (default) | Deterministic optimizer → deterministic Context Critic. | The decision. |
| `agent` | The same decision path, wrapped in a Proposer → Critic → Judge review cycle. | Nothing about the decision — only the reasoning, objections, evidence trail, and confidence score. |

The deterministic critic owns every final status. The adversarial phase can only *downgrade* an approval to `needs_review`; it can never approve, reject, or defer. A regression test asserts the two modes produce identical decisions for every workload.

The dashboard has a **Pipeline / Agent cycle** toggle in the header.

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

The critic independently checks that the proposal stays at or above its configured P99 safety floors (`1.10 × CPU P99` and `1.15 × memory P99` by default). It also checks upcoming business-event risk, incident history, and the minimum estimated monthly savings. Deterministic checks determine the outcome; NVIDIA NIM, when configured, can phrase an explanation but cannot change the decision.

## Agent review cycle

In `agent` mode, `backend/app/services/agent_orchestrator.py` runs each workload through three bounded phases and records them as `ReviewCycle` objects in the audit log:

| Phase | Role | Bound |
|---|---|---|
| Proposer | Gathers evidence with tools and argues for or against a reduction. | 10 iterations |
| Critic | Red-teams the proposal. May call read-only tools to ground its objections. | 4 iterations |
| Judge | Weighs the objections against the deterministic verdict. | 3 iterations |

The Critic's objections are grounded in evidence the agent actually retrieved, not invented. The stable codes are `RECURRING_EVENT_UNMODELLED`, `INCIDENT_OVERLAP_IGNORED`, `LOG_PRESSURE_IGNORED`, `DEPENDENCY_PRESSURE_IGNORED`, `VERIFICATION_GAP`, and `THIN_EVIDENCE`; each carries a `blocking` or `advisory` severity.

Two tools support the cycle beyond the usual workload metrics:

- **`search_logs`** returns simulated container logs for a workload, including `OOMKilled`, CPU throttling, and eviction entries. A log that reports memory pressure raises a blocking objection against reducing the memory request.
- **`get_dependencies`** maps the upstream services a workload depends on, so an incident on an upstream dependency is visible rather than a surprise.

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
frontend makes it reviewable. The panels that carry the agent's work:

| Panel | What it shows | Endpoint |
|---|---|---|
| **Cycle** tab (detail panel) | The Proposer → Critic → Judge phases as they ran: each phase's summary, the tools it called, the objections it raised, and the Judge's ruling. | `POST /api/analyze` (`mode: "agent"`) |
| **What-if simulator** | Move the CPU/memory request sliders and the deterministic critic re-decides against your numbers. Nothing is saved and no patch is produced. | `POST /api/simulate` |
| **Review history** | What a human already decided about this workload, with the structured rejection reasons — the exact text the agent replays as "Historical Lessons" next time. | `GET /api/reports/{id}`, `GET /api/decisions` |
| **Decision history** (History tab) | Every decision the critic has made, across reports, with a search box, a status filter, and a validity column. A decision whose metrics have moved since it was made is marked stale — and the backend refuses to accept a stale decision for implementation. | `GET /api/decisions`, `GET /api/reports/{id}` |
| **Trend across analyses** | Approved savings over successive runs, with deferred and needs-review counts on the second axis. | `GET /api/dashboard/summary` |
| **Business events** | Campaigns and freezes split into live / upcoming / past, with the services each one puts at risk. | `GET /api/events` |
| **Safety policy** | The critic's guardrails, editable — every field the critic reads, not a selection. Saving appends a new policy version and flags earlier reports as expired. | `GET`/`PUT /api/policies`, `GET /api/policies/defaults` |
| **Savings potential** | Everything the optimizer found, how much survived the safety rules, and what was held back. A deferral is shown with its price, not as a gap in the output. | `POST /api/analyze` |
| **Top opportunities** | Findings ranked by savings × confidence ÷ risk, so the short list is at the top rather than buried. | `GET /api/dashboard/summary` |

A **provenance strip** sits above the analysis: the policy version, the rule version, the input
fingerprint and the run id, so a recommendation can be traced to the rules and the data that
produced it. In agent mode it also says plainly that the cycle is driven by a deterministic
stand-in, not a live language model.

The header has a **Pipeline / Agent cycle** toggle. The workflow strip changes with it, so the
stages shown are the ones that actually produced the numbers on screen. The export button writes
the report you are looking at — same `analysis_id`, same decisions — not a fresh run.

Printing is a first-class path: the detail panel's tabs are all mounted, so a printed report
contains the evidence, the review cycle, the critic's checks and the patch, not only whichever tab
happened to be open. The print stylesheet forces the light palette, so a report printed from a
dark-mode screen is not white text on white paper.

## Demo data

The `data/` directory contains synthetic fixture inputs: `deployments.yaml`, `usage_history.csv`, `business_events.json`, `incident_history.csv`, `policy.yaml`, and `cost_model.json`. The policy includes a fixed `simulation_now` so the demo scenarios and freshness decisions are repeatable. `data/sample_analysis_response.json` is a sample output. These fixtures demonstrate outcomes; they are not live production telemetry.

## Integrations

- **Zetaris:** `backend/app/integrations/zetaris_client.py` queries the deployments, usage, events, and incidents tables from `finops_data`, including paginated query results. Set the `ZETARIS_*` values in the root `.env` to use Zetaris; when it is not configured, the loader uses local fixture files. Local `policy.yaml` and `cost_model.json` remain the source for those configuration values. See [`docs/ZETARIS_SETUP.md`](docs/ZETARIS_SETUP.md).
- **Meterless / Nightshift runner seam:** the orchestrator routes collector, optimizer, and critic steps through `get_runner()`. `AGENT_RUNTIME=meterless` selects the Meterless-named scaffold, but the current runner still executes each function locally. `METERLESS_BASE_URL` is logged as configuration only; this scaffold does not call the hotspot or enforce a Markovian context engine. It is an integration seam, not a claim of remote execution.
- **NVIDIA NIM:** can provide critic explanation text when configured. Deterministic critic checks remain authoritative.
- **Language model:** the agent mode calls an LLM client through a small interface (`SimulatedLLMClient` stands in when no model is configured). The model proposes and argues; it never decides. Whatever it writes, the deterministic critic still owns the status.

More details: [`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md), [`docs/CONTRACT.md`](docs/CONTRACT.md), and [`docs/FINOPS_METHOD.md`](docs/FINOPS_METHOD.md) for the sizing formula, risk findings, the agent review cycle, and measurable scenario results.

## Tests and scenario evaluation

```bash
python -m pytest                      # backend suite
python scripts/evaluate_scenarios.py  # planted-scenario acceptance table
```

`scripts/evaluate_scenarios.py` replays the labelled scenarios in `data/test_scenarios.json` and reports expected vs. actual per scenario, plus recall, false-positive rate, and the count of event/incident reduction suggestions. The current fixture passes 7/7 with 100% recall and a 0% false-positive rate. See [`docs/FINOPS_METHOD.md`](docs/FINOPS_METHOD.md) for the table and its caveats.

## Run with Docker Compose

Start the backend API and Vite frontend together from the repository root:

```bash
docker compose up --build
```

Open `http://localhost:5173` for the frontend. It proxies `/api` requests to the backend container. The backend API remains available at `http://localhost:8000`.

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

Copy `.env.example` to `.env` and set only the integrations you intend to use. Start FastAPI from the repository root:

```bash
uvicorn app.main:app --reload --port 8000 --app-dir backend
```

The React frontend is in `frontend/`; see [`frontend/README.md`](frontend/README.md) for its development commands. API routes are registered under `/api`.

## Repository map

```text
backend/app/       FastAPI API, schemas, optimizer, critic, orchestrator, integrations
backend/tests/     Backend tests
data/              Demo fixtures and policy/cost configuration
docs/              Shared contract and integration guides
frontend/          React + TypeScript + Vite application
scripts/            Fixture generation and integration checks
```

```
finops-agent
├─ .cursor
│  └─ rules
│     └─ finops.mdc
├─ .dockerignore
├─ backend
│  ├─ app
│  │  ├─ api
│  │  │  ├─ deps.py
│  │  │  ├─ routes
│  │  │  │  ├─ analysis.py
│  │  │  │  ├─ data.py
│  │  │  │  ├─ reports.py
│  │  │  │  └─ __init__.py
│  │  │  └─ __init__.py
│  │  ├─ integrations
│  │  │  ├─ meterless_runner.py
│  │  │  ├─ nvidia_nim.py
│  │  │  ├─ zetaris_client.py
│  │  │  ├─ zetaris_source.py
│  │  │  └─ __init__.py
│  │  ├─ main.py
│  │  ├─ models
│  │  │  ├─ review.py
│  │  │  ├─ schemas.py
│  │  │  └─ __init__.py
│  │  ├─ services
│  │  │  ├─ adversarial_service.py
│  │  │  ├─ agent_orchestrator.py
│  │  │  ├─ agent_tools.py
│  │  │  ├─ confidence_service.py
│  │  │  ├─ critic_service.py
│  │  │  ├─ data_loader.py
│  │  │  ├─ fingerprints.py
│  │  │  ├─ incident_service.py
│  │  │  ├─ optimizer_service.py
│  │  │  ├─ orchestrator.py
│  │  │  ├─ report_service.py
│  │  │  ├─ savings.py
│  │  │  ├─ simulator.py
│  │  │  ├─ simulated_llm.py
│  │  │  ├─ store.py
│  │  │  ├─ usage_service.py
│  │  │  ├─ validation_service.py
│  │  │  ├─ verification_service.py
│  │  │  └─ __init__.py
│  │  └─ __init__.py
│  ├─ requirements.txt
│  └─ tests
│     ├─ test_agent_api.py
│     ├─ test_agent_cycle.py
│     ├─ test_data_loader.py
│     ├─ test_incident_service.py
│     ├─ test_optimizer.py
│     ├─ test_optimizer_additions.py
│     ├─ test_optimizer_logic.py
│     ├─ test_schemas.py
│     ├─ test_usage_service.py
│     ├─ test_zetaris_client.py
│     ├─ test_zetaris_source.py
│     └─ __init__.py
├─ data
│  ├─ business_events.json
│  ├─ cost_model.json
│  ├─ deployments.json
│  ├─ deployments.yaml
│  ├─ finops_policy.json
│  ├─ incident_history.csv
│  ├─ policy.yaml
│  ├─ sample_analysis_response.json
│  ├─ test_scenarios.json
│  ├─ usage_history.csv
│  └─ workloads.json
├─ docker-compose.yml
├─ Dockerfile
├─ docs
│  ├─ CONTRACT.md
│  ├─ CURSOR.md
│  ├─ FINOPS_METHOD.md
│  ├─ INTEGRATIONS.md
│  ├─ ZETARIS_SETUP.md
│  └─ ZETARIS_UPLOAD.md
├─ e -i HEAD~5
├─ frontend
│  ├─ .oxlintrc.json
│  ├─ components.json
│  ├─ Dockerfile
│  ├─ index.html
│  ├─ package-lock.json
│  ├─ package.json
│  ├─ public
│  │  ├─ favicon.svg
│  │  └─ mock
│  │     ├─ analysis.json
│  │     ├─ scenarios
│  │     │  ├─ event-risk.json
│  │     │  ├─ no-change.json
│  │     │  ├─ normal.json
│  │     │  ├─ spike.json
│  │     │  └─ stale.json
│  │     └─ scenarios.json
│  ├─ README.md
│  ├─ scripts
│  │  └─ make-mock-scenarios.mjs
│  ├─ src
│  │  ├─ api.ts
│  │  ├─ App.tsx
│  │  ├─ components
│  │  │  ├─ AppToaster.tsx
│  │  │  ├─ DecisionBadge.tsx
│  │  │  ├─ DecisionDonut.tsx
│  │  │  ├─ DetailPanel.tsx
│  │  │  ├─ InputStatus.tsx
│  │  │  ├─ ResultsTable.tsx
│  │  │  ├─ ReviewForm.tsx
│  │  │  ├─ SavingsChart.tsx
│  │  │  ├─ ScenarioSwitcher.tsx
│  │  │  ├─ SummaryCards.tsx
│  │  │  ├─ ThemeToggle.tsx
│  │  │  ├─ ui
│  │  │  │  ├─ badge.tsx
│  │  │  │  ├─ button.tsx
│  │  │  │  ├─ card.tsx
│  │  │  │  ├─ skeleton.tsx
│  │  │  │  ├─ table.tsx
│  │  │  │  └─ tabs.tsx
│  │  │  ├─ UsageChart.tsx
│  │  │  ├─ Workflow.tsx
│  │  │  └─ YamlDiff.tsx
│  │  ├─ hooks
│  │  │  ├─ useCountUp.ts
│  │  │  └─ useMediaQuery.ts
│  │  ├─ index.css
│  │  ├─ lib
│  │  │  ├─ report.ts
│  │  │  └─ utils.ts
│  │  ├─ main.tsx
│  │  └─ types.ts
│  ├─ tsconfig.app.json
│  ├─ tsconfig.json
│  ├─ tsconfig.node.json
│  └─ vite.config.ts
├─ pyrightconfig.json
├─ pytest.ini
├─ README.md
└─ scripts
   ├─ check_nvidia.py
   ├─ check_zetaris.py
   ├─ check_zetaris_query.py
   ├─ evaluate_scenarios.py
   ├─ export_zetaris_data.py
   ├─ generate_fixtures.py
   └─ generate_sample_response.py
```
