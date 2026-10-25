"""Meterless-compatible runner seam; execution remains local until a client is integrated."""
from __future__ import annotations

import os
import time
from typing import Any, Callable, Protocol


class AgentRunner(Protocol):
    name: str

    def run(self, step: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any: ...


class LocalRunner:
    name = "local"

    def run(self, step: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        return fn(*args, **kwargs)


class MeterlessRunner:
    """Local execution scaffold with configuration hooks for future hotspot integration."""

    name = "meterless"

    def __init__(self) -> None:
        self.base_url = os.getenv("METERLESS_BASE_URL", "http://127.0.0.1:8088/v1")
        # Descriptive profile only; no context-window enforcement is implemented here.
        self.engine = "Markovian (Bounded State)"

    def run(self, step: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        print(f"\n[Meterless scaffold] Running '{step}' locally.")
        print(f"  Configured profile: {self.engine} (label only)")
        print(f"  Hotspot URL: {self.base_url} (not called by this runner)")
        started = time.perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            elapsed = time.perf_counter() - started
            print(f"  '{step}' local execution finished in {elapsed:.2f}s.\n")


def get_runner() -> AgentRunner:
    if os.getenv("AGENT_RUNTIME", "local").lower() == "meterless":
        return MeterlessRunner()
    return LocalRunner()
