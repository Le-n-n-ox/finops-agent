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
    def __init__(self, bundle: InputBundle):
        self.bundle = bundle
        self._tools: Dict[str, AgentTool] = {}
        # Every call is remembered so a later tool can refer to an earlier result. The agent
        # never has to round-trip a large object through the LLM, which is both lossy and a
        # hallucination risk.
        self._history: List[Dict[str, Any]] = []
        self._setup_tools()

    def _setup_tools(self):
        # The analysis clock. The demo fixes it in policy.yaml so results are repeatable; without
        # that, every metric looks stale relative to the wall clock.
        def analysis_now() -> datetime:
            return self.bundle.policy.simulation_now or datetime.now(timezone.utc)

        # Tool: get_workload_metrics
        # Returns raw usage data for a specific workload
        def get_workload_metrics(workload_id: str, **kwargs) -> List[UsageRow]:
            return [row for row in self.bundle.usage_rows if row.service == workload_id]

        # Tool: analyze_rightsizing
        # Computes the optimal resource requests
        def analyze_rightsizing(workload_id: str, **kwargs) -> OptimizationProposal:
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
        # `proposal_data` is optional: when the agent omits it, the most recent
        # `analyze_rightsizing` result is validated instead. That keeps the authoritative
        # proposal the one the deterministic optimizer produced, rather than one the LLM retyped.
        def validate_policy(proposal_data: Dict[str, Any] | None = None, **kwargs) -> WorkloadResult:
            if proposal_data:
                proposal = OptimizationProposal(**proposal_data)
            else:
                proposal = self.last_result("analyze_rightsizing")
                if not isinstance(proposal, OptimizationProposal):
                    raise ValueError(
                        "No proposal to validate. Call 'analyze_rightsizing' first or pass proposal_data.")
            return critic_service.evaluate(proposal, self.bundle)

        # Tool: get_incident_history
        # Retrieves incidents related to the workload
        def get_incident_history(workload_id: str, **kwargs) -> List[IncidentRecord]:
            return [inc for inc in self.bundle.incidents if inc.service == workload_id]

        # Tool: search_logs
        # Searches simulated logs for error patterns (OOM, Throttling)
        def search_logs(workload_id: str, keyword: str | None = None, level: str | None = None,
                        **kwargs) -> List[Dict[str, Any]]:
            return data_loader.get_logs(workload_id, keyword=keyword, level=level)

        # Tool: get_dependencies
        # Maps service dependencies to detect upstream pressure
        def get_dependencies(workload_id: str, **kwargs) -> List[str]:
            return data_loader.get_dependencies(workload_id)

        self.add_tool("get_workload_metrics", get_workload_metrics,
                      {"workload_id": "string"}, "Retrieve raw usage metrics for a workload.")
        self.add_tool("analyze_rightsizing", analyze_rightsizing,
                      {"workload_id": "string"}, "Compute the deterministic right-sizing proposal.")
        self.add_tool("detect_risk_patterns", detect_risk_patterns,
                      {"workload_id": "string"}, "Detect capacity risks and over-provisioning signals.")
        self.add_tool("validate_policy", validate_policy,
                      {"proposal_data": "object?"},
                      "Run the proposal through the safety critic. Omit proposal_data to validate the "
                      "most recent analyze_rightsizing result.")
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
