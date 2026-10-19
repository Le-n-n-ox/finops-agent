"""
Developer 1 — deterministic resource optimizer. No LLM here. Requests only; never touch limits.
"""
from __future__ import annotations

from datetime import datetime

from app.models.schemas import InputBundle, OptimizationProposal


def build_proposals(bundle: InputBundle, now: datetime | None = None) -> list[OptimizationProposal]:
    """Return ONE OptimizationProposal per service (never an empty object).

    Algorithm (values come from bundle.policy.optimizer):
      1. group usage by service, sort by timestamp
      2. coverage fails (samples < min_samples or span < min_span_hours) -> status=insufficient_data + reason
      3. CPU/memory P95 and P99
      4. cpu_candidate = max(p95*1.25, p99*1.10); mem_candidate = max(p95*1.30, p99*1.15)
      5. round UP (cpu 10m, memory 64MiB), never down
      6. propose only if candidate >= 15% below current request, else status=no_action + reason
      7. never change limits; fill estimated_monthly_saving_usd from cost_model (illustrative)
    `now` is injected so tests never depend on the wall clock.
    """
    raise NotImplementedError("build_proposals: implement with Cursor (see docs/CURSOR.md prompt #2)")
