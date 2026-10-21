from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.models.schemas import (
    InputBundle,
    OptimizationProposal,
    WorkloadResult,
    AgentAuditLog,
    ToolCall,
    DecisionStatus,
    VerificationResult
)
from app.services.agent_tools import AgentToolbox
from app.services.verification_service import VerificationService

class AgentOrchestrator:
    """
    The 'Brain' of the FinOps Agent.
    Manages the reasoning loop: Thought -> Tool -> Observation -> Conclusion.
    """
    def __init__(self, bundle: InputBundle, llm_client: Any):
        self.bundle = bundle
        self.llm = llm_client  # Assume an LLM client that supports tool use
        self.toolbox = AgentToolbox(bundle)
        self.verifier = VerificationService()

    async def analyze_workload_agentic(self, workload_id: str) -> tuple[WorkloadResult, AgentAuditLog]:
        session_id = str(uuid.uuid4())
        audit_log = AgentAuditLog(session_id=session_id, workload_id=workload_id)

        # Initial context for the LLM
        system_prompt = (
            "You are a FinOps Expert Agent. Your goal is to recommend safe resource optimizations. "
            "You have access to tools to get metrics, analyze right-sizing, and check policies. "
            "CRITICAL RULES:\n"
            "1. Use tools to gather evidence. Do not guess numbers.\n"
            "2. You MUST call 'validate_policy' as the final step before concluding.\n"
            "3. If 'validate_policy' rejects a proposal, you must report the rejection.\n"
            "4. Every number in your final summary must come from a tool result."
        )

        current_context = f"Analyze workload: {workload_id}. Find safe savings."
        max_iterations = 10
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            # 1. Reasoning Phase: Ask LLM what to do next
            # In a real implementation, this would be a tool-calling LLM API call
            response = await self.llm.chat(
                system=system_prompt,
                user=current_context,
                tools=self.toolbox.get_tool_definitions(),
                history=[(t.thought, str(t.result)) for t in audit_log.steps]
            )

            if response.conclusion:
                # LLM has reached a final answer
                final_report = response.content

                # 2. Safety Gate: Number-to-Tool Verification
                verification = self.verifier.verify_report(final_report, audit_log.steps)
                if not verification.is_valid:
                    current_context += f"\n\nVERIFICATION ERROR: The following values were not found in tool outputs: {verification.errors}. Please correct your report using only tool-provided data."
                    continue

                # 3. Final Decision Extraction
                # The agent must have called validate_policy to get the formal DecisionStatus
                final_decision = self._extract_final_decision(audit_log)

                audit_log.final_decision = final_decision

                # We return the result from the last validate_policy call as the formal WorkloadResult
                formal_result = self._get_last_policy_result(audit_log)

                return formal_result, audit_log

            if response.tool_call:
                # 4. Action Phase: Execute the tool
                tool_name = response.tool_call.name
                params = response.tool_call.arguments

                result = self.toolbox.call(tool_name, **params)

                # Record in Audit Log
                step = ToolCall(
                    tool=tool_name,
                    params=params,
                    result=result.data,
                    thought=response.thought
                )
                audit_log.steps.append(step)

                current_context += f"\nTool {tool_name} returned: {result.data}"
            else:
                break

        raise RuntimeError("Agent failed to converge on a conclusion.")

    def _extract_final_decision(self, audit_log: AgentAuditLog) -> DecisionStatus:
        for step in reversed(audit_log.steps):
            if step.tool == "validate_policy":
                # result is a WorkloadResult
                return step.result.decision if hasattr(step.result, 'decision') else DecisionStatus.NEEDS_REVIEW
        return DecisionStatus.NEEDS_REVIEW

    def _get_last_policy_result(self, audit_log: AgentAuditLog) -> WorkloadResult:
        for step in reversed(audit_log.steps):
            if step.tool == "validate_policy":
                return step.result
        # Fallback: create a dummy needs_review result if the agent skipped the policy check
        return WorkloadResult(
            workload_id=audit_log.workload_id,
            decision=DecisionStatus.NEEDS_REVIEW,
            risk_level="high",
            reason="Agent failed to perform mandatory policy validation.",
            checks=[],
            proposal=OptimizationProposal(
                proposal_id="err", workload_id=audit_log.workload_id,
                status="needs_review", current=ResourceSettings(), metrics=UsageMetrics(), created_at=datetime.now(timezone.utc)
            )
        )
