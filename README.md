# Kubernetes Over-Provisioning FinOps Agent

Recommendation-only prototype: a FinOps Optimizer proposes smaller resource requests, a Context Critic challenges them against events/incidents/evidence, and a human reviews a report + YAML patch. **Nothing is ever applied to a cluster.**

```
finops-agent/
├── backend/app/          FastAPI + services (Dev1: data_loader, optimizer_service | Dev2: critic, orchestrator, report, routes)
│   ├── models/schemas.py   SHARED CONTRACT
│   └── integrations/       zetaris_client, meterless_runner, nvidia_nim
├── backend/tests/
├── frontend/             React + TS + Vite (Dev 2)
├── data/                 fixtures: deployments.yaml, usage_history.csv, business_events.json, incident_history.csv, cost_model.json, policy.yaml
├── docs/                 CONTRACT, ZETARIS_SETUP, INTEGRATIONS, CURSOR
├── scripts/              generate_fixtures.py, check_zetaris.py
└── .cursor/rules/        Cursor project rules
```

## Setup
```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
cp .env.example .env
pytest -q
uvicorn app.main:app --reload --port 8000 --app-dir backend
```

## Ownership & Git
- Dev 1: `data_loader.py`, `optimizer_service.py`, `data/`, their tests. Dev 2: critic, orchestrator, report, `api/`, `frontend/`.
- `schemas.py` changes need both developers. Short-lived feature branches off `main`; small commits; run `pytest -q` after merging.
- Units: CPU millicores, memory MiB, ISO-8601 timestamps. Savings are illustrative estimates only.

See `docs/CONTRACT.md` for decisions, `docs/INTEGRATIONS.md` for Zetaris / Meterless / Cursor / NVIDIA.
