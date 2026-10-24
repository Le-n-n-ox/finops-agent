"""Contract tests for the endpoints the UI leans on, which had no coverage.

`/api/analysis/latest`, `/api/llm/status` and `/api/health` are the first three calls the app
makes. They are cheap to test and expensive to get wrong: a broken `latest` is a blank workspace,
and a wrong `llm/status` misnames the model that answered.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FINOPS_DB_PATH", str(tmp_path / "history.sqlite3"))
    import app.api.deps as deps
    deps._services = None
    with TestClient(app) as test_client:
        yield test_client
    deps._services = None


def test_latest_is_a_404_before_any_review_has_run(client):
    """The workspace needs to tell "nothing saved yet" from "saved review broken"."""
    res = client.get("/api/analysis/latest")

    assert res.status_code == 404
    assert "No review" in res.json()["detail"]


def test_latest_returns_the_saved_review_without_running_one(client):
    analysed = client.post("/api/analyze", json={"mode": "agent"}).json()

    res = client.get("/api/analysis/latest")

    assert res.status_code == 200
    body = res.json()
    assert body["analysis_id"] == analysed["analysis_id"]
    assert body["results"] == analysed["results"]


def test_latest_is_served_without_revalidating_the_model(client):
    """It is the stored JSON, so it must not need a model or a policy re-run to answer."""
    client.post("/api/analyze", json={"mode": "agent"})

    first = client.get("/api/analysis/latest")
    second = client.get("/api/analysis/latest")

    assert first.content == second.content


def test_llm_status_names_the_backend_before_anything_runs(client):
    body = client.get("/api/llm/status").json()

    assert set(body) >= {"backend", "model", "base_url", "key_source", "detail"}
    assert body["backend"] in {"openai-compatible", "simulated"}


def test_health_reports_the_mode_it_is_running_in(client):
    body = client.get("/api/health").json()

    assert body["status"] == "ok"
    assert body["sample_mode"] in {"true", "false"}
    assert body["data_source"] in {"local", "zetaris"}
    assert body["llm_backend"] in {"auto", "simulated"}
