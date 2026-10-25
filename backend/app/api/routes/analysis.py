"""POST /api/analyze, POST /api/analyze/stream, GET /api/llm/status and POST /api/simulate."""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Callable, Literal

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


def _analyze_off_loop(svc: Services,
                      on_workload: Callable[[Any], None] | None = None) -> AnalysisResponse:
    """Run one analysis on a worker thread.

    An analysis is CPU- and IO-heavy: the optimizer, the critic, the agent cycle and the database
    writes. Run straight from the async endpoint it occupies the event loop for its whole duration,
    so every other request - /api/health included - waits behind it and the whole API looks dead
    while a run is in flight. Off the loop, the dashboard keeps answering during an analysis.

    The analysis is driven through `asyncio.run` because it is written as coroutines, but nothing
    in it waits on real IO: the only awaited call is the model client.

    `on_workload` is called with each workload's result as it is finished, so a caller can report
    the run as it happens. It is called from this thread, so a caller that hands results to an
    event loop has to do the hand-off itself.
    """
    return asyncio.run(run_and_record(svc.store, mode="agent", inputs_fn=svc.inputs_fn,
                                      on_workload=on_workload))


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
        return await asyncio.to_thread(_analyze_off_loop, svc)


@router.get("/analysis/latest")
def latest_analysis(svc: Services = Depends(get_services)) -> Response:
    """The last completed review, without running a new one.

    Opening the workspace used to mean sitting through a fresh twelve-workload agent run before
    anything appeared. Every report is already saved, so the page can open on the last one and
    let the reader decide when to re-run it - which is a decision they can only make if the page
    shows them something first.

    The stored JSON is returned as it is. Validating a 1.5 MB payload into pydantic models and
    serialising it again costs ~45 ms per call, and the bytes are already the response.
    """
    payload = svc.store.latest_report_json()
    if payload is None:
        raise HTTPException(status_code=404, detail="No review has been run yet.")
    return Response(content=payload, media_type="application/json")


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
    loop = asyncio.get_running_loop()

    def publish(kind: str, payload: Any) -> None:
        """Hand a result from the worker thread to the event loop.

        The analysis runs on a worker thread so it does not occupy the event loop, and
        `asyncio.Queue` is not safe to touch from another thread. `call_soon_threadsafe` is the
        documented way to wake the loop from elsewhere, so that is what carries the result.
        """
        loop.call_soon_threadsafe(queue.put_nowait, (kind, payload))

    def run() -> None:
        try:
            response = _analyze_off_loop(svc, on_workload=lambda result: publish("workload", result))
            publish("done", response)
        except Exception as exc:  # noqa: BLE001 - the stream has to say what went wrong
            publish("error", {"detail": f"{type(exc).__name__}: {exc}"})

    async def frames() -> AsyncIterator[str]:
        task = asyncio.create_task(asyncio.to_thread(run))
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