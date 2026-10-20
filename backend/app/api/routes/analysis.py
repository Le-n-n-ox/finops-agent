from typing import Literal

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
from app.models.schemas import AnalysisResponse, ValidationResponse
from app.services.orchestrator import run_analysis
from app.services.report_service import render_markdown_report
from app.services.validation_service import validate_data

router = APIRouter()

@router.get("/analyze", response_model=AnalysisResponse)
@router.post("/analyze", response_model=AnalysisResponse)
def analyze() -> AnalysisResponse:
    """Triggers the full FinOps analysis pipeline and returns structured results."""
    return run_analysis()


@router.get("/validation", response_model=ValidationResponse)
def validation() -> ValidationResponse:
    """Report ingestion issues and per-workload metric completeness and freshness."""
    return validate_data()


@router.get("/report")
def report(format: Literal["json", "markdown"] = "json") -> Response:
    """Generate a fresh, review-only audit report as JSON or Markdown."""
    analysis = run_analysis()
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
