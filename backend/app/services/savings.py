"""Illustrative monthly-saving estimate (demo rates from data/cost_model.json — NOT a billing figure).

TODO(Dev1): if optimizer_service already has a saving formula, expose it and call it from here so the
simulator and the optimizer can never disagree. tests/test_simulator.py has an xfail spec that checks this.
"""
from __future__ import annotations

from app.models.schemas import CostModel, ResourceSettings


def estimate_monthly_saving(current: ResourceSettings, proposed: ResourceSettings, replicas: int, cost: CostModel) -> float:
    cpu_m = (current.cpu_request_millicores or 0) - (proposed.cpu_request_millicores or 0)
    mem_mib = (current.memory_request_mib or 0) - (proposed.memory_request_mib or 0)
    per_replica = cpu_m / 1000 * cost.cpu_core_monthly_cost_usd + mem_mib / 1024 * cost.memory_gib_monthly_cost_usd
    return round(per_replica * max(replicas, 1), 2)