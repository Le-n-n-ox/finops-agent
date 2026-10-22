"""POST /api/analyze, POST /api/analyze/stream, GET /api/llm/status and POST /api/simulate."""
from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict

from app.api.deps import Services, api_errors, get_services
from app.models.review import ResourceRequests, SimulationRequest, SimulationResult
from app.models.schemas import AnalysisResponse, ValidationResponse
from app.services.orchestrator import llm_status_payload, run_analysis, run_and_record
from app.services.report_service import render_markdown_report
from app.services.simulator import simulate_recommendation
from app.services.validation_service import validate_data

router = APIRouter(prefix="/api", tags=["analysis"])


class AnalyzeRequest(BaseModel):
    """Body is optional.

    `mode` is accepted for backward compatibility with older frontends and is IGNORED: the agent
    cycle is the only reasoning path. `scenario` is used by the UI's mock mode and ignored here.
    """
    model_config = ConfigDict(extra="ignore")
    scenario: str = "all"
    mode: str = "agent"  # accepted for backward compatibility; the agent cycle always runs


@router.post("/analyze", response_model=AnalysisResponse)
async def analyze(req: AnalyzeRequest | None = None, svc: Services = Depends(get_services)) -> AnalysisResponse:
    """Triggers the FinOps Agent analysis and returns structured results.

    There is ONE reasoning path: the Proposer -> Critic -> Judge cycle, answered by the live
    OpenAI-compatible model server when one is reachable and by the deterministic stand-in
    otherwise. The `mode` field is still accepted in the body so an older frontend keeps
    working, but it is ignored: the deterministic pipeline is not a selectable alternative, it
    is the safety model behind every final decision.

    This waits for the whole run. Use `/api/analyze/stream` when the caller needs to see it
    happening.
    """
    with api_errors():
        # `mode` is deliberately not read: the agent cycle always runs.
        return await run_and_record(svc.store, mode=(req.mode if req else "agent"),
                                    inputs_fn=svc.inputs_fn)


def _sse(event: str, payload: object) -> str:
    """One server-sent event."""
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


@router.post("/analyze/stream")
async def analyze_stream(req: AnalyzeRequest | None = None,
                         svc: Services = Depends(get_services)) -> Response:
    """The same analysis, reported as it happens.

    A full run is a multi-turn conversation with the model server for every workload, so it
    takes minutes - and a caller that sees nothing until the end has no way to tell a slow run
    from a stuck one. This sends each workload's result as it is finished, then the complete
    response.

    The events are:

    | Event | Payload |
    |---|---|
    | `start` | `{"total": n}` - how many workloads there are, so the caller can show a progress bar. |
    | `workload` | One `WorkloadResult`, as it is finished. |
    | `done` | The complete `AnalysisResponse`, the same one `/api/analyze` returns. |
    | `error` | `{"detail": "..."}`, when the run could not be completed. |
    """
    queue: asyncio.Queue = asyncio.Queue()

    async def run() -> None:
        try:
            response = await run_and_record(
                svc.store, mode=(req.mode if req else "agent"), inputs_fn=svc.inputs_fn,
                on_workload=lambda result: queue.put_nowait(("workload", result)),
            )
            await queue.put(("done", response))
        except Exception as exc:  # noqa: BLE001 - the stream has to say what went wrong
            await queue.put(("error", {"detail": f"{type(exc).__name__}: {exc}"}))

    async def frames() -> AsyncIterator[str]:
        task = asyncio.create_task(run())
        try:
            # How many workloads there are, before the first one is finished. Without it a
            # progress bar has no denominator, and "1 of ?" is not a progress bar.
            try:
                yield _sse("start", {"total": len(svc.bundle().services)})
            except Exception:  # noqa: BLE001 - the count is a convenience, not a requirement
                yield _sse("start", {"total": 0})
            while True:
                kind, payload = await queue.get()
                if kind == "workload":
                    yield _sse("workload", payload.model_dump(mode="json"))
                elif kind == "done":
                    yield _sse("done", payload.model_dump(mode="json"))
                    return
                else:
                    yield _sse("error", payload)
                    return
        finally:
            # If the client goes away, the run is abandoned rather than left in the background.
            task.cancel()

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/llm/status")
def llm_status() -> dict:
    """Which model server the backend resolved, before any analysis runs.

    A plain JSON object (not a schema wrapper) so the UI can show the model name, or say plainly
    that the deterministic stand-in is in use. The analysis response carries the same facts after
    a run; this endpoint exists so the badge can name the model before anything is produced.
    """
    with api_errors():
        return llm_status_payload()


@router.get("/validation", response_model=ValidationResponse)
def validation() -> ValidationResponse:
    """Report ingestion issues and per-workload metric completeness and freshness."""
    return validate_data()


@router.get("/report")
async def report(format: Literal["json", "markdown"] = "json", report_id: str | None = None,
                 svc: Services = Depends(get_services)) -> Response:
    """Export a review-only audit report as JSON or Markdown.

    `report_id` selects a stored report. Without it the latest stored report is used, so the export
    matches the analysis the reviewer is actually looking at. A fresh analysis is never run here:
    exporting something other than what was reviewed would defeat the point of an audit trail.
    """
    analysis = None
    if report_id:
        analysis = svc.store.get_report(report_id)
        if analysis is None:
            raise HTTPException(404, f"Unknown report: {report_id}")
    else:
        analysis = svc.store.latest_report()
    if analysis is None:
        # Nothing stored yet (first run against a cold database). Fall back to a fresh analysis.
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