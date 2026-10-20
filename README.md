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

## Demo data

The `data/` directory contains synthetic fixture inputs: `deployments.yaml`, `usage_history.csv`, `business_events.json`, `incident_history.csv`, `policy.yaml`, and `cost_model.json`. The policy includes a fixed `simulation_now` so the demo scenarios and freshness decisions are repeatable. `data/sample_analysis_response.json` is a sample output. These fixtures demonstrate outcomes; they are not live production telemetry.

## Integrations

- **Zetaris:** `backend/app/integrations/zetaris_client.py` queries the deployments, usage, events, and incidents tables from `finops_data`, including paginated query results. Set the `ZETARIS_*` values in the root `.env` to use Zetaris; when it is not configured, the loader uses local fixture files. Local `policy.yaml` and `cost_model.json` remain the source for those configuration values. See [`docs/ZETARIS_SETUP.md`](docs/ZETARIS_SETUP.md).
- **Meterless / Nightshift runner seam:** the orchestrator routes collector, optimizer, and critic steps through `get_runner()`. `AGENT_RUNTIME=meterless` selects the Meterless-named scaffold, but the current runner still executes each function locally. `METERLESS_BASE_URL` is logged as configuration only; this scaffold does not call the hotspot or enforce a Markovian context engine. It is an integration seam, not a claim of remote execution.
- **NVIDIA NIM:** can provide critic explanation text when configured. Deterministic critic checks remain authoritative.

More details: [`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md) and [`docs/CONTRACT.md`](docs/CONTRACT.md).

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
