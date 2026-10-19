"""
Agent execution seam (Developer 2 owns, Developer 1 may run optimizer through it).
Every agent step (collector / optimizer / critic / report) is called via a runner so Meterless can be
plugged in without touching business logic. LocalRunner is the always-working default.
Do not claim Meterless is integrated until MeterlessRunner makes a real, tested call.
"""
from __future__ import annotations

import os
from typing import Any, Callable, Protocol


class AgentRunner(Protocol):
    name: str

    def run(self, step: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any: ...


class LocalRunner:
    name = "local"

    def run(self, step, fn, *args, **kwargs):
        return fn(*args, **kwargs)


class MeterlessRunner:
    """TODO: implement against the runtime/SDK Meterless actually provides to your team."""
    name = "meterless"

    def run(self, step, fn, *args, **kwargs):
        raise NotImplementedError("Meterless adapter not implemented yet")


def get_runner() -> AgentRunner:
    return MeterlessRunner() if os.getenv("AGENT_RUNTIME", "local") == "meterless" else LocalRunner()
