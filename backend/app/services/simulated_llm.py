from __future__ import annotations
import random
import asyncio
from typing import Any, Dict, List, Optional, TypedDict

class LLMResponse(TypedDict):
    content: Optional[str]
    tool_call: Optional[Dict[str, Any]]
    thought: Optional[str]
    conclusion: bool

class SimulatedLLMClient:
    """
    A simulated LLM that follows the FinOps Agent's reasoning paths.
    It doesn't just return a result; it simulates the 'Investigation Loop'.
    """
    def __init__(self):
        self.call_count = 0

    async def chat(self, system: str, user: str, tools: List[Dict[str, Any]], history: List[tuple]) -> LLMResponse:
        self.call_count += 1

        # Extract workload_id from the user prompt
        import re
        match = re.search(r"Analyze workload: ([^\s,.]+)", user)
        workload_id = match.group(1) if match else "unknown"

        # SIMULATED REASONING PATHS
        # We simulate a few different types of workload behavior to demo the agent
        if "payments" in workload_id.lower():
            # Path 1: The "Investigative" path (Spike -> Incident -> Downgrade)
            if self.call_count == 1:
                return {
                    "thought": f"Checking basic metrics for {workload_id} to see if it's over-provisioned.",
                    "tool_call": {"name": "analyze_rightsizing", "arguments": {"workload_id": workload_id}},
                    "content": None,
                    "conclusion": False
                }
            if self.call_count == 2:
                return {
                    "thought": "I see a significant CPU spike in the history. I need to check if this was a one-off incident or a trend.",
                    "tool_call": {"name": "get_incident_history", "arguments": {"workload_id": workload_id}},
                    "content": None,
                    "conclusion": False
                }
            return {
                "thought": "The spike correlates with a known incident. I will recommend a cautious reduction but mark it as needing review.",
                "tool_call": {"name": "validate_policy", "arguments": {"proposal_data": {}}},
                "content": f"Analysis for {workload_id}: Found a correlation between usage spikes and historical incidents. Recommendation downgraded to 'Needs Review'.",
                "conclusion": True
            }

        elif "auth" in workload_id.lower():
            # Path 2: The "Clean" path (Direct approval)
            if self.call_count == 1:
                return {
                    "thought": f"Analyzing {workload_id}. Starting with rightsizing calculations.",
                    "tool_call": {"name": "analyze_rightsizing", "arguments": {"workload_id": workload_id}},
                    "content": None,
                    "conclusion": False
                }
            return {
                "thought": "Metrics are stable and data quality is high. Proceeding to policy validation.",
                "tool_call": {"name": "validate_policy", "arguments": {"proposal_data": {}}},
                "content": f"Analysis for {workload_id}: Stable usage pattern detected. Safe to reduce requests.",
                "conclusion": True
            }

        else:
            # Path 3: The "Data Quality" path (Not enough data)
            if self.call_count == 1:
                return {
                    "thought": f"Investigating {workload_id}. Checking data health first.",
                    "tool_call": {"name": "get_workload_metrics", "arguments": {"workload_id": workload_id}},
                    "content": None,
                    "conclusion": False
                }
            return {
                "thought": "Sample count is too low for a confident recommendation.",
                "tool_call": None,
                "content": f"Analysis for {workload_id}: Insufficient data to make a safe recommendation.",
                "conclusion": True
            }
