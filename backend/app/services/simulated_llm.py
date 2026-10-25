from __future__ import annotations
import re
from typing import Any, Dict, List

from app.integrations.llm_client import LLMResponse

__all__ = ["LLMResponse", "SimulatedLLMClient"]


class SimulatedLLMClient:
    """
    A simulated LLM that follows the FinOps Agent's reasoning paths.

    It doesn't just return a result; it simulates the 'Investigation Loop'. The client is
    phase-aware: the orchestrator tells it which role is speaking ('proposer' or 'critic') and
    it answers in character, so the Proposer -> Critic -> Judge cycle is exercised end to end
    without a real model behind it.

    It is the fallback when no model server answers, and the fixture the tests run against. It
    speaks exactly the same protocol as the live client, so the orchestrator cannot tell the
    difference - which is the point: the same code path is exercised either way, and the status
    says out loud which one answered.
    """

    def __init__(self):
        self.call_count = 0
        self.phase = "proposer"

    async def chat(self, system: str, user: str, tools: List[Dict[str, Any]],
                   history: List[Dict[str, Any]]) -> LLMResponse:
        self.call_count += 1

        # The orchestrator's system prompt tells us which role is speaking.
        if "adversarial reviewer" in system.lower():
            self.phase = "critic"
        elif "final judge" in system.lower():
            self.phase = "judge"
        else:
            self.phase = "proposer"

        if self.phase == "critic":
            response = self._critic_turn(user, tools, history)
        elif self.phase == "judge":
            response = self._judge_turn(user)
        else:
            response = self._proposer_turn(user, tools, history)

        # The live client reports the provider's own call id so the orchestrator can pair a
        # tool result with the call that asked for it. The stand-in has no provider, so it mints
        # a stable one.
        response["tool_call_id"] = f"sim-{self.call_count}" if response.get("tool_call") else None
        return response

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _tool_calls_made(history: List[Dict[str, Any]] | None, user: str) -> int:
        """How many tool calls this phase has already made.

        The orchestrator records each turn in the phase's own OpenAI message list, so the count
        comes from the assistant messages that carry `tool_calls`. The fallback to counting "Tool "
        in the prose context is there for callers that predate the message list.
        """
        if history:
            return sum(1 for message in history if message.get("role") == "assistant" and message.get("tool_calls"))
        return user.count("Tool ")

    @staticmethod
    def _workload_id(user: str) -> str:
        match = re.search(r"Analyze workload: ([^\s,.]+)", user)
        if match:
            return match.group(1)
        match = re.search(r"workload:\s*([^\s,.]+)", user, re.IGNORECASE)
        return match.group(1) if match else "unknown"

    @staticmethod
    def _tool_available(tools: List[Dict[str, Any]], name: str) -> bool:
        return any(tool.get("name") == name for tool in tools)

    # ------------------------------------------------------------------ proposer
    def _proposer_turn(self, user: str, tools: List[Dict[str, Any]],
                       history: List[Dict[str, Any]] | None = None) -> LLMResponse:
        workload_id = self._workload_id(user)
        lower = workload_id.lower()

        # How many tool calls has the proposer already made on this workload?
        made = self._tool_calls_made(history, user)

        if "payments" in lower or "payment" in lower:
            # Path 1: The "Investigative" path (spike -> incident -> downgrade)
            if made == 0:
                return {
                    "thought": f"Checking basic metrics for {workload_id} to see if it's over-provisioned.",
                    "tool_call": {"name": "analyze_rightsizing", "arguments": {"workload_id": workload_id}},
                    "content": None,
                    "conclusion": False,
                }
            if made == 1:
                return {
                    "thought": "I see a significant CPU spike in the history. I need to check if this was a one-off incident or a trend.",
                    "tool_call": {"name": "get_incident_history", "arguments": {"workload_id": workload_id}},
                    "content": None,
                    "conclusion": False,
                }
            if made == 2 and self._tool_available(tools, "search_logs"):
                return {
                    "thought": "The incident history is not enough on its own. Let me check the container logs for OOM or throttling evidence.",
                    "tool_call": {"name": "search_logs", "arguments": {"workload_id": workload_id}},
                    "content": None,
                    "conclusion": False,
                }
            return {
                "thought": "The spike correlates with a known incident and the logs show pressure. I will recommend a cautious reduction but mark it as needing review.",
                "tool_call": {"name": "validate_policy", "arguments": {}},
                "content": (f"Analysis for {workload_id}: found a correlation between usage spikes and historical "
                            f"incidents, and the container logs show memory pressure. Recommending a cautious "
                            f"reduction subject to human review."),
                "conclusion": True,
            }

        if "auth" in lower:
            # Path 2: The "Clean" path (direct approval)
            if made == 0:
                return {
                    "thought": f"Analyzing {workload_id}. Starting with rightsizing calculations.",
                    "tool_call": {"name": "analyze_rightsizing", "arguments": {"workload_id": workload_id}},
                    "content": None,
                    "conclusion": False,
                }
            return {
                "thought": "Metrics are stable and data quality is high. Proceeding to policy validation.",
                "tool_call": {"name": "validate_policy", "arguments": {}},
                "content": f"Analysis for {workload_id}: stable usage pattern detected with no incident or event overlap. Safe to reduce requests.",
                "conclusion": True,
            }

        if "session" in lower or "catalog" in lower:
            # Path 3: The "Dependency-aware" path
            if made == 0:
                return {
                    "thought": f"Investigating {workload_id}. Checking right-sizing first.",
                    "tool_call": {"name": "analyze_rightsizing", "arguments": {"workload_id": workload_id}},
                    "content": None,
                    "conclusion": False,
                }
            if made == 1 and self._tool_available(tools, "get_dependencies"):
                return {
                    "thought": "Before reducing this workload, I should check which services depend on it or which it depends on.",
                    "tool_call": {"name": "get_dependencies", "arguments": {"workload_id": workload_id}},
                    "content": None,
                    "conclusion": False,
                }
            return {
                "thought": "Dependencies are clear and no upstream pressure was found. Validating against policy.",
                "tool_call": {"name": "validate_policy", "arguments": {}},
                "content": f"Analysis for {workload_id}: dependency map checked, no upstream pressure identified.",
                "conclusion": True,
            }

        # Path 4: The "Data Quality" path (not enough data)
        if made == 0:
            return {
                "thought": f"Investigating {workload_id}. Checking data health first.",
                "tool_call": {"name": "get_workload_metrics", "arguments": {"workload_id": workload_id}},
                "content": None,
                "conclusion": False,
            }
        if made == 1:
            return {
                "thought": "Checking the deterministic right-sizing result to confirm the data quality verdict.",
                "tool_call": {"name": "analyze_rightsizing", "arguments": {"workload_id": workload_id}},
                "content": None,
                "conclusion": False,
            }
        return {
            "thought": "Sample count is too low for a confident recommendation. Validating against policy anyway.",
            "tool_call": {"name": "validate_policy", "arguments": {}},
            "content": f"Analysis for {workload_id}: insufficient data to make a safe recommendation.",
            "conclusion": True,
        }

    # ------------------------------------------------------------------ critic
    def _critic_turn(self, user: str, tools: List[Dict[str, Any]],
                     history: List[Dict[str, Any]] | None = None) -> LLMResponse:
        workload_id = self._workload_id(user)
        made = self._tool_calls_made(history, user)

        # The critic gathers its own evidence: logs, then dependencies, then it rules.
        if made == 0 and self._tool_available(tools, "search_logs"):
            return {
                "thought": "Red-teaming this: is the container already under pressure?",
                "tool_call": {"name": "search_logs", "arguments": {"workload_id": workload_id}},
                "content": None,
                "conclusion": False,
            }
        if made == 1 and self._tool_available(tools, "get_incident_history"):
            return {
                "thought": "Now checking whether a prior incident covers this exact reduction.",
                "tool_call": {"name": "get_incident_history", "arguments": {"workload_id": workload_id}},
                "content": None,
                "conclusion": False,
            }
        if made == 2 and self._tool_available(tools, "get_dependencies"):
            return {
                "thought": "Checking upstream dependencies for pressure that a reduction could worsen.",
                "tool_call": {"name": "get_dependencies", "arguments": {"workload_id": workload_id}},
                "content": None,
                "conclusion": False,
            }
        return {
            "thought": "I have enough evidence to state my objections.",
            "tool_call": {"name": "validate_policy", "arguments": {}},
            "content": (f"Adversarial review of {workload_id}: checked logs, incident history and dependencies "
                        f"against the proposer's case."),
            "conclusion": True,
        }

    # ------------------------------------------------------------------ judge
    def _judge_turn(self, user: str) -> LLMResponse:
        return {
            "thought": "Weighing the objections against the deterministic verdict.",
            "tool_call": None,
            "content": ("The objections either confirm the deterministic verdict or hold the recommendation "
                        "for a human; the ruling stands either way."),
            "conclusion": True,
        }
