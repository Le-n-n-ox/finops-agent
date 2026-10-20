"""POST /api/analyze and POST /api/simulate."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from app.api.deps import Services, api_errors, get_services
from app.models.review import ResourceRequests, SimulationRequest, SimulationResult
from app.models.schemas import AnalysisResponse
from app.services.orchestrator import run_and_record
from app.services.simulator import simulate_recommendation

router = APIRouter(prefix="/api", tags=["analysis"])


class AnalyzeRequest(BaseModel):
    """Body is optional. `scenario` is used by the UI's mock mode and ignored here."""
    model_config = ConfigDict(extra="ignore")
    scenario: str = "all"


@router.post("/analyze", response_model=AnalysisResponse)
def analyze(_: AnalyzeRequest | None = None, svc: Services = Depends(get_services)) -> AnalysisResponse:
    with api_errors():
        return run_and_record(svc.store, inputs_fn=svc.inputs_fn, proposals_fn=svc.proposals_fn)


@router.post("/simulate", response_model=SimulationResult)
def simulate(req: SimulationRequest, svc: Services = Depends(get_services)) -> SimulationResult:
    """Hypothetical request values for one workload. Nothing is saved, no patch is produced, nothing is applied."""
    with api_errors():
        report = svc.store.latest_report()
        if report is None:
            raise HTTPException(409, "Run an analysis first; the simulator starts from the latest recommendation.")
        match = next((r for r in report.results if r.workload_id == req.workload_id), None)
        if match is None:
            raise HTTPException(404, f"Unknown workload: {req.workload_id}")
        return simulate_recommendation(match.proposal, ResourceRequests(**req.model_dump(exclude={"workload_id"})), svc.bundle())