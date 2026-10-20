from fastapi import APIRouter
from app.models.schemas import AnalysisResponse
from app.services.orchestrator import run_analysis

router = APIRouter()

@router.get("/analyze", response_model=AnalysisResponse)
@router.post("/analyze", response_model=AnalysisResponse)
def analyze() -> AnalysisResponse:
    """Triggers the full FinOps analysis pipeline and returns structured results."""
    return run_analysis()