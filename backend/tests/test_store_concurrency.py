"""The store has to survive the API's own concurrency.

FastAPI runs synchronous handlers in a threadpool, so the History page, the report detail and
the dashboard query the same SQLite connection in parallel. `check_same_thread=False` removes
the thread check on that connection; it does not make it safe to use from two threads at once.
Two threads sharing a connection raise `sqlite3.InterfaceError`, which surfaced as a 500 on
`/api/decisions` and `/api/reports/{id}` - the pages a reviewer opens to see what happened.

These tests read and write the store from several threads at once, which is what the API does.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.models.review import ReviewAction
from app.models.schemas import (
    DecisionStatus,
    OptimizationProposal,
    ResourceSettings,
    RiskLevel,
    UsageMetrics,
    WorkloadResult,
)
from app.services.fingerprints import Fingerprint
from app.services.store import Store


def _result(workload_id: str) -> WorkloadResult:
    return WorkloadResult(
        workload_id=workload_id,
        namespace="core",
        decision=DecisionStatus.APPROVED,
        risk_level=RiskLevel.LOW,
        reason="All safety checks passed; patch is review-only.",
        checks=[],
        proposal=OptimizationProposal(
            proposal_id=workload_id,
            workload_id=workload_id,
            status="proposed",
            current=ResourceSettings(),
            metrics=UsageMetrics(),
            created_at=datetime.now(timezone.utc),
        ),
    )


def _fingerprint() -> Fingerprint:
    return Fingerprint(config_hash="h", metrics_at=datetime.now(timezone.utc), event_version="e")


@pytest.fixture()
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "history.sqlite3")


class TestTheStoreIsSafeToShare:
    def test_reads_and_writes_from_several_threads(self, store):
        """Writes and reads at the same time, from different threads."""
        store.save_decision_record(_result("payment-api"), "ANL-1", _fingerprint(), "v1")
        store.save_decision_record(_result("checkout-service"), "ANL-1", _fingerprint(), "v1")

        errors: list[BaseException] = []

        def writer(workload_id: str) -> None:
            try:
                for i in range(20):
                    store.save_decision_record(_result(f"{workload_id}-{i}"), "ANL-1", _fingerprint(), "v1")
            except BaseException as exc:  # noqa: BLE001 - the test wants to see it
                errors.append(exc)

        def reader() -> None:
            try:
                for _ in range(40):
                    store.decisions()
                    store.get_decision("DEC-ANL-1-payment-api")
                    store.audit(decision_id="DEC-ANL-1-payment-api")
                    store.get_feedback_for_workload("payment-api")
                    store.list_reports()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(writer, f"w{i}") for i in range(3)]
            futures += [pool.submit(reader) for _ in range(5)]
            for future in futures:
                future.result()

        assert not errors, f"the store failed under concurrency: {errors[:3]}"

    def test_a_review_can_be_recorded_while_the_history_is_read(self, store):
        """Recording a review reads the decision first, so the two paths overlap."""
        store.save_decision_record(_result("payment-api"), "ANL-1", _fingerprint(), "v1")
        decision_id = "DEC-ANL-1-payment-api"

        errors: list[BaseException] = []

        def record() -> None:
            try:
                for _ in range(20):
                    store.record_reviewer_action(decision_id, ReviewAction.REJECTED,
                                                 comment="not now", reviewer="bob")
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        def read() -> None:
            try:
                for _ in range(40):
                    store.decisions()
                    store.audit(decision_id=decision_id)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(record) for _ in range(2)]
            futures += [pool.submit(read) for _ in range(4)]
            for future in futures:
                future.result()

        assert not errors, f"the store failed under concurrency: {errors[:3]}"
        assert len(store.audit(decision_id=decision_id)) == 40
