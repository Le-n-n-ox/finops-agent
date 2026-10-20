"""Developer 2 — what a recommendation was based on, and whether it is still valid (expiry)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from app.models.review import DecisionRecord, ExpiryResult
from app.models.schemas import InputBundle


def _h(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


@dataclass(frozen=True)
class Fingerprint:
    config_hash: str
    metrics_at: datetime | None
    event_version: str   # events touching the workload + the full critic policy (incl. its version)


def fingerprint(workload_id: str, bundle: InputBundle) -> Fingerprint:
    spec = next((s for s in bundle.services if s.name == workload_id), None)
    stamps = [r.timestamp for r in bundle.usage_rows if r.service == workload_id]
    events = sorted(({"name": e.name, "start": e.start_at.isoformat(), "end": e.end_at.isoformat(), "risk": e.risk,
                      "traffic": e.expected_traffic} for e in bundle.events if workload_id in e.services), key=lambda e: e["start"])
    return Fingerprint(config_hash=_h(spec.model_dump() if spec else None), metrics_at=max(stamps) if stamps else None,
                       event_version=_h({"events": events, "policy": bundle.policy.critic.model_dump()}))


def is_recommendation_stale(record: DecisionRecord, latest_metrics_at: datetime | None, latest_config_hash: str,
                            current_event_version: str) -> ExpiryResult:
    """Flag recommendations that need a fresh analysis before anyone relies on them."""
    reasons: list[str] = []
    if latest_metrics_at and (record.metrics_at is None or latest_metrics_at > record.metrics_at):
        reasons.append("Newer usage metrics are available")
    if latest_config_hash != record.config_hash:
        reasons.append("The workload's resource configuration changed")
    if current_event_version != record.event_version:
        reasons.append("Business events or the safety policy changed")
    if reasons:
        return ExpiryResult(stale=True, reasons=reasons, message="Expired — re-run analysis")
    return ExpiryResult(stale=False, message="Current")