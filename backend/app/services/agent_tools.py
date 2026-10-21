from __future__ import annotations
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
        self._setup_tools()

    def _setup_tools(self):
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
                events=self.bundle.events
            )

        # Tool: validate_policy
        # Checks a proposal against safety floors and corporate policy
        def validate_policy(proposal_data: Dict[str, Any], **kwargs) -> WorkloadResult:
            # Convert dict back to OptimizationProposal model
            proposal = OptimizationProposal(**proposal_data)
            return critic_service.evaluate(proposal, self.bundle)

        # Tool: get_incident_history
        # Retrieves incidents related to the workload
        def get_incident_history(workload_id: str, **kwargs) -> List[IncidentRecord]:
            return [inc for inc in self.bundle.incidents if inc.service == workload_id]

        self.add_tool("get_workload_metrics", get_workload_metrics,
                      {"workload_id": "string"}, "Retrieve raw usage metrics for a workload.")
        self.add_tool("analyze_rightsizing", analyze_rightsizing,
                      {"workload_id": "string"}, "Compute the deterministic right-sizing proposal.")
        self.add_tool("detect_risk_patterns", detect_risk_patterns,
                      {"workload_id": "string"}, "Detect capacity risks and over-provisioning signals.")
        self.add_tool("validate_policy", validate_policy,
                      {"proposal_data": "object"}, "Run the proposal through the safety critic.")
        self.add_tool("get_incident_history", get_incident_history,
                      {"workload_id": "string"}, "Get historical incident records for a workload.")

    def add_tool(self, name: str, func: Callable, schema: Dict[str, Any], description: str):
        self._tools[name] = AgentTool(name, func, schema, description)

    def call(self, tool_name: str, **kwargs) -> ToolResult:
        if tool_name not in self._tools:
            return ToolResult(status="error", data=None, error=f"Tool {tool_name} not found.")
        return self._tools[tool_name].execute(**kwargs)

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        return [
            {"name": t.name, "description": t.description, "parameters": t.schema}
            for t in self._tools.values()
        ]
