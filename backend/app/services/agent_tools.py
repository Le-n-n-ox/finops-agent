from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, TypedDict
from pydantic import BaseModel, Field

from app.models.schemas import (
    InputBundle,
    OptimizationProposal,
    WorkloadResult,
    UsageRow,
    IncidentRecord
)
from app.services import data_loader, optimizer_service, critic_service

class ToolResult(BaseModel):
    status: str = "success"
    data: Any
    error: Optional[str] = None


# A month of hourly usage is 720 rows, about 98 KB of JSON. Serialising that into the prompt and
# cutting it at the 20 KB character cap produced an unparseable fragment of the OLDEST week - the
# peak was never in what the model read. The model needs the shape and the peaks, not every row:
# the percentiles and the maximum are computed over all samples, and only the series is thinned.
SERIES_POINTS = 48


def _usage_summary(workload_id: str, rows: list[UsageRow]) -> Dict[str, Any]:
    """Counts, percentiles, the peak and a downsampled series - small, and valid JSON."""
    if not rows:
        return {"workload_id": workload_id, "sample_count": 0,
                "note": "No usage samples were recorded for this workload."}

    ordered = sorted(rows, key=lambda row: row.timestamp)
    cpu = [float(row.cpu_millicores) for row in ordered]
    mem = [float(row.memory_mib) for row in ordered]
    cpu_peak = max(range(len(cpu)), key=cpu.__getitem__)
    mem_peak = max(range(len(mem)), key=mem.__getitem__)

    def stats(values: list[float], peak: int) -> Dict[str, Any]:
        return {
            "p50": round(optimizer_service.percentile(values, 50), 1),
            "p95": round(optimizer_service.percentile(values, 95), 1),
            "p99": round(optimizer_service.percentile(values, 99), 1),
            "max": round(values[peak], 1),
            "max_at": ordered[peak].timestamp.isoformat(),
        }

    step = max(1, len(ordered) // SERIES_POINTS)
    return {
        "workload_id": workload_id,
        "sample_count": len(ordered),
        "window_start": ordered[0].timestamp.isoformat(),
        "window_end": ordered[-1].timestamp.isoformat(),
        "cpu_millicores": stats(cpu, cpu_peak),
        "memory_mib": stats(mem, mem_peak),
        "series": [
            {"t": row.timestamp.isoformat(), "cpu": round(float(row.cpu_millicores), 1),
             "mem": round(float(row.memory_mib), 1)}
            for row in ordered[::step]
        ],
        "note": ("The series is downsampled to about 48 points across the window; the "
                 "percentiles and the peak are computed over every sample."),
    }

class AgentTool:
    def __init__(self, name: str, func: Callable, schema: Dict[str, Any], description: str):
        self.name = name
        self.func = func
        self.schema = schema
        self.description = description

    def execute(self, **kwargs) -> ToolResult:
        try:
            result = self.func(**kwargs)
            return ToolResult(data=result)
        except Exception as e:
            return ToolResult(status="error", data=None, error=str(e))

class AgentToolbox:
    def __init__(self, bundle: InputBundle, workload_id: str | None = None):
        self.bundle = bundle
        # The workload this toolbox is bound to, when it is bound to one.
        #
        # The model chooses which tool to call and with which workload id, and `validate_policy`
        # judges the most recent `analyze_rightsizing` result. Unbound, that combination lets a
        # model make one workload's review validate another workload's proposal - and publish
        # that workload's verdict under the wrong name. A bound toolbox refuses the call, so the
        # model cannot choose which proposal the safety check judges.
        self.workload_id = workload_id
        self._tools: Dict[str, AgentTool] = {}
        # Every call is remembered so a later tool can refer to an earlier result. The agent
        # never has to round-trip a large object through the LLM, which is both lossy and a
        # hallucination risk.
        self._history: List[Dict[str, Any]] = []
        self._setup_tools()

    def _require(self, workload_id: str) -> str:
        """Refuse a call about a workload this toolbox is not reviewing."""
        if self.workload_id is not None and workload_id != self.workload_id:
            raise ValueError(
                f"This review is about workload '{self.workload_id}'. Call the tool with "
                f"workload_id='{self.workload_id}' - a review may not use another workload's data.")
        return workload_id

    def _setup_tools(self):
        # The analysis clock. The demo fixes it in policy.yaml so results are repeatable; without
        # that, every metric looks stale relative to the wall clock.
        def analysis_now() -> datetime:
            return self.bundle.policy.simulation_now or datetime.now(timezone.utc)

        # Tool: get_workload_metrics
        # A statistical summary of the workload's usage (see _usage_summary).
        def get_workload_metrics(workload_id: str, **kwargs) -> Dict[str, Any]:
            self._require(workload_id)
            rows = [row for row in self.bundle.usage_rows if row.service == workload_id]
            return _usage_summary(workload_id, rows)

        # Tool: analyze_rightsizing
        # Computes the optimal resource requests
        def analyze_rightsizing(workload_id: str, **kwargs) -> OptimizationProposal:
            self._require(workload_id)
            spec = next((s for s in self.bundle.services if s.name == workload_id), None)
            if not spec:
                raise ValueError(f"Workload {workload_id} not found.")

            metrics = [row for row in self.bundle.usage_rows if row.service == workload_id]

            return optimizer_service.analyze_workload(
                workload=spec,
                rows=metrics,
                policy=self.bundle.policy.optimizer,
                now=analysis_now(),
                cost_model=self.bundle.cost_model,
                incidents=self.bundle.incidents,
                events=self.bundle.events
            )

        # Tool: detect_risk_patterns
        # Identifies capacity and configuration risks
        def detect_risk_patterns(workload_id: str, **kwargs) -> List[Any]:
            self._require(workload_id)
            spec = next((s for s in self.bundle.services if s.name == workload_id), None)
            if not spec:
                raise ValueError(f"Workload {workload_id} not found.")

            metrics = [row for row in self.bundle.usage_rows if row.service == workload_id]

            return optimizer_service.detect_resource_findings(
                workload=spec,
                rows=metrics,
                policy=self.bundle.policy.optimizer,
                events=self.bundle.events,
                now=analysis_now()
            )

        # Tool: validate_policy
        # Checks a proposal against safety floors and corporate policy.
        #
        # The proposal that gets judged is always the one the deterministic optimizer produced.
        # A model may echo that proposal back as `proposal_data`, and it usually does, but the
        # copy is never what the safety check approves: a retyped proposal that does not even
        # parse used to fail the tool, and a failed tool used to cost the workload its review.
        # An unusable `proposal_data` is ignored, and the optimizer's proposal is judged.
        def validate_policy(proposal_data: Dict[str, Any] | None = None, **kwargs) -> WorkloadResult:
            proposal = self.last_result("analyze_rightsizing")
            if not isinstance(proposal, OptimizationProposal):
                raise ValueError(
                    "No proposal to validate. Call 'analyze_rightsizing' first.")
            if self.workload_id is not None and proposal.workload_id != self.workload_id:
                # Belt and braces: the tools are already bound to one workload, so this cannot
                # happen. It is checked anyway, because this is the step that decides the
                # workload's verdict and a wrong proposal here is a wrong verdict published.
                raise ValueError(
                    f"The proposal on file is for workload '{proposal.workload_id}', not "
                    f"'{self.workload_id}'. Call 'analyze_rightsizing' for this workload first.")
            return critic_service.evaluate(proposal, self.bundle)

        # Tool: get_incident_history
        # Retrieves incidents related to the workload
        def get_incident_history(workload_id: str, **kwargs) -> List[IncidentRecord]:
            self._require(workload_id)
            return [inc for inc in self.bundle.incidents if inc.service == workload_id]

        # Tool: search_logs
        # Searches simulated logs for error patterns (OOM, Throttling)
        def search_logs(workload_id: str, keyword: str | None = None, level: str | None = None,
                        **kwargs) -> List[Dict[str, Any]]:
            self._require(workload_id)
            return data_loader.get_logs(workload_id, keyword=keyword, level=level)

        # Tool: get_dependencies
        # Maps service dependencies to detect upstream pressure
        def get_dependencies(workload_id: str, **kwargs) -> List[str]:
            self._require(workload_id)
            return data_loader.get_dependencies(workload_id)

        self.add_tool("get_workload_metrics", get_workload_metrics,
                      {"workload_id": "string"},
                      "Summarise a workload's usage metrics: sample count, window, CPU and memory "
                      "p50/p95/p99, the peak and when it happened, plus a downsampled series.")
        self.add_tool("analyze_rightsizing", analyze_rightsizing,
                      {"workload_id": "string"}, "Compute the deterministic right-sizing proposal.")
        self.add_tool("detect_risk_patterns", detect_risk_patterns,
                      {"workload_id": "string"}, "Detect capacity risks and over-provisioning signals.")
        self.add_tool("validate_policy", validate_policy,
                      {"proposal_data": "object?"},
                      "Run the proposal through the safety critic. The proposal judged is always "
                      "the one analyze_rightsizing produced; proposal_data is accepted but ignored.")
        self.add_tool("get_incident_history", get_incident_history,
                      {"workload_id": "string"}, "Get historical incident records for a workload.")
        self.add_tool("search_logs", search_logs,
                      {"workload_id": "string", "keyword": "string?", "level": "string?"},
                      "Search simulated logs for errors (OOM, Throttling). Optional keyword/level filters.")
        self.add_tool("get_dependencies", get_dependencies,
                      {"workload_id": "string"}, "Get service dependencies to detect upstream pressure.")

    def add_tool(self, name: str, func: Callable, schema: Dict[str, Any], description: str):
        self._tools[name] = AgentTool(name, func, schema, description)

    def last_result(self, tool_name: str) -> Any:
        """The most recent result of `tool`, or None if it was never called."""
        for entry in reversed(self._history):
            if entry["tool"] == tool_name:
                return entry["result"]
        return None

    def call(self, tool_name: str, **kwargs) -> ToolResult:
        if tool_name not in self._tools:
            return ToolResult(status="error", data=None, error=f"Tool {tool_name} not found.")
        result = self._tools[tool_name].execute(**kwargs)
        if result.status == "success":
            self._history.append({"tool": tool_name, "params": kwargs, "result": result.data})
        return result

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        return [
            {"name": t.name, "description": t.description, "parameters": t.schema}
            for t in self._tools.values()
        ]
