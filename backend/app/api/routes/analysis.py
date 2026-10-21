"""POST /api/analyze and POST /api/simulate."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.api.deps import Services, api_errors, get_services
from app.models.review import ResourceRequests, SimulationRequest, SimulationResult
from app.models.schemas import AnalysisResponse, ValidationResponse
from app.services.orchestrator import run_analysis, run_and_record
from app.services.report_service import render_markdown_report
from app.services.simulator import simulate_recommendation
from app.services.validation_service import validate_data

router = APIRouter(prefix="/api", tags=["analysis"])


class AnalyzeRequest(BaseModel):
    """Body is optional. `mode` determines if we use the deterministic pipeline or the agent.
    `scenario` is used by the UI's mock mode and ignored here."""
    model_config = ConfigDict(extra="ignore")
    scenario: str = "all"
    mode: str = "pipeline"  # "pipeline" | "agent"


@router.post("/analyze", response_model=AnalysisResponse)
async def analyze(req: AnalyzeRequest | None = None, svc: Services = Depends(get_services)) -> AnalysisResponse:
    """Triggers the FinOps Agent analysis and returns structured results.

    `mode` selects the reasoning path: "pipeline" (deterministic) or "agent" (Proposer -> Critic -> Judge).
    """
    with api_errors():
        mode = (req.mode if req else "pipeline") or "pipeline"
        if mode == "agent":
            return await run_and_record(svc.store, mode="agent")
        return await run_and_record(svc.store, inputs_fn=svc.inputs_fn, proposals_fn=svc.proposals_fn)


@router.get("/validation", response_model=ValidationResponse)
def validation() -> ValidationResponse:
    """Report ingestion issues and per-workload metric completeness and freshness."""
    return validate_data()


@router.get("/report")
async def report(format: Literal["json", "markdown"] = "json") -> Response:
    """Generate a fresh, review-only audit report as JSON or Markdown."""
    analysis = await run_analysis()
    if format == "markdown":
        return Response(
            content=render_markdown_report(analysis),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="finops-audit-report.md"'},
        )
    return JSONResponse(
        content=analysis.model_dump(mode="json"),
        headers={"Content-Disposition": 'attachment; filename="finops-audit-report.json"'},
    )


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