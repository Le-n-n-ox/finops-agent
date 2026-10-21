# Kubernetes Over-Provisioning FinOps Agent

A recommendation-only FinOps prototype. The optimizer proposes lower Kubernetes CPU and memory **requests** from historical usage. A deterministic critic checks those proposals against P99 safety floors, business events, incident history, and estimated savings. A human reviews the result and any generated YAML patch; the application never changes a cluster.

## What it does

1. Loads deployments, usage history, business events, incidents, policy, and an illustrative cost model.
2. Computes per-workload usage percentiles and a candidate request.
3. Applies deterministic data-quality, freshness, P99, and minimum-reduction checks.
4. Has the critic approve, defer, reject, or request review, with evidence for its decision.
5. Returns a report and review-only YAML patch for approved recommendations.

The Pydantic models in `backend/app/models/schemas.py` define the shared input and output contract. Units are CPU millicores, memory MiB, and timezone-aware ISO-8601 timestamps. Kubernetes limits are included as context and are never changed.

## Deterministic calculation

Optimizer parameters live in `data/policy.yaml` and can be changed without changing code:

| Parameter | Demo value | Purpose |
|---|---:|---|
| `min_samples` | 24 | Minimum usage observations required per workload |
| `min_span_hours` | 24 | Minimum time span covered by observations |
| `max_metric_age_hours` | 72 | Older latest observation triggers `needs_review` |
| CPU P95 / P99 multipliers | 1.25 / 1.10 | Headroom factors applied to CPU percentiles |
| Memory P95 / P99 multipliers | 1.30 / 1.15 | Headroom factors applied to memory percentiles |
| CPU / memory rounding units | 10 millicores / 64 MiB | Candidate requests round up to these increments |
| `min_reduction_pct` | 15 | Minimum reduction required for an individual resource |

For each resource, the optimizer sorts the samples and calculates P95 and P99 using linear interpolation at position `(n - 1) × percentile / 100`. It calculates the candidate as:

```text
candidate = round_up(max(P95 × P95_multiplier, P99 × P99_multiplier), rounding_unit)
```

A resource is eligible only when its P99 is no greater than the current request, the candidate is lower than the current request, and the candidate is at most 85% of the current request (the configured 15% reduction floor). CPU and memory are evaluated independently: an eligible resource can be reduced while the other stays at its current request. Requests are never increased. Missing, too-short, or stale histories produce `needs_review`; workloads without an eligible reduction produce `no_change`.

The critic independently checks that the proposal stays at or above its configured P99 safety floors (`1.10 × CPU P99` and `1.15 × memory P99` by default). It also checks upcoming business-event risk, incident history, and the minimum estimated monthly savings. Deterministic checks determine the outcome; NVIDIA NIM, when configured, can phrase an explanation but cannot change the decision.

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

## Demo data

The `data/` directory contains synthetic fixture inputs: `deployments.yaml`, `usage_history.csv`, `business_events.json`, `incident_history.csv`, `policy.yaml`, and `cost_model.json`. The policy includes a fixed `simulation_now` so the demo scenarios and freshness decisions are repeatable. `data/sample_analysis_response.json` is a sample output. These fixtures demonstrate outcomes; they are not live production telemetry.

## Integrations

- **Zetaris:** `backend/app/integrations/zetaris_client.py` queries the deployments, usage, events, and incidents tables from `finops_data`, including paginated query results. Set the `ZETARIS_*` values in the root `.env` to use Zetaris; when it is not configured, the loader uses local fixture files. Local `policy.yaml` and `cost_model.json` remain the source for those configuration values. See [`docs/ZETARIS_SETUP.md`](docs/ZETARIS_SETUP.md).
- **Meterless / Nightshift runner seam:** the orchestrator routes collector, optimizer, and critic steps through `get_runner()`. `AGENT_RUNTIME=meterless` selects the Meterless-named scaffold, but the current runner still executes each function locally. `METERLESS_BASE_URL` is logged as configuration only; this scaffold does not call the hotspot or enforce a Markovian context engine. It is an integration seam, not a claim of remote execution.
- **NVIDIA NIM:** can provide critic explanation text when configured. Deterministic critic checks remain authoritative.

More details: [`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md) and [`docs/CONTRACT.md`](docs/CONTRACT.md).

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
│  │  │  ├─ routes
│  │  │  │  ├─ analysis.py
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
│  │  │  ├─ schemas.py
│  │  │  └─ __init__.py
│  │  ├─ services
│  │  │  ├─ critic_service.py
│  │  │  ├─ data_loader.py
│  │  │  ├─ optimizer_service.py
│  │  │  ├─ orchestrator.py
│  │  │  ├─ report_service.py
│  │  │  └─ __init__.py
│  │  └─ __init__.py
│  ├─ requirements.txt
│  └─ tests
│     ├─ test_data_loader.py
│     ├─ test_optimizer.py
│     ├─ test_optimizer_logic.py
│     ├─ test_schemas.py
│     ├─ test_zetaris_client.py
│     ├─ test_zetaris_source.py
│     └─ __init__.py
├─ data
│  ├─ business_events.json
│  ├─ cost_model.json
│  ├─ deployments.json
│  ├─ deployments.yaml
│  ├─ incident_history.csv
│  ├─ policy.yaml
│  ├─ sample_analysis_response.json
│  └─ usage_history.csv
├─ docker-compose.yml
├─ Dockerfile
├─ docs
│  ├─ CONTRACT.md
│  ├─ CURSOR.md
│  ├─ INTEGRATIONS.md
│  └─ ZETARIS_SETUP.md
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
   ├─ generate_fixtures.py
   └─ generate_sample_response.py

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
│  │  │  ├─ store.py
│  │  │  ├─ usage_service.py
│  │  │  ├─ validation_service.py
│  │  │  └─ __init__.py
│  │  └─ __init__.py
│  ├─ requirements.txt
│  └─ tests
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
│  ├─ incident_history.csv
│  ├─ policy.yaml
│  ├─ sample_analysis_response.json
│  └─ usage_history.csv
├─ docker-compose.yml
├─ Dockerfile
├─ docs
│  ├─ CONTRACT.md
│  ├─ CURSOR.md
│  ├─ INTEGRATIONS.md
│  └─ ZETARIS_SETUP.md
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
   ├─ generate_fixtures.py
   └─ generate_sample_response.py

```