"""SAMPLE_MODE: one switch that turns every external dependency off.

The point is a reviewer with no Zetaris tenant and no Nightshift hotspot can still run the app.
Two settings already did that separately (`DATA_SOURCE=local`, `LLM_BACKEND=simulated`); the flag
exists so nobody has to discover both, and so it cannot half-apply.
"""
from __future__ import annotations

import os

import pytest

from app.config import apply_sample_mode, sample_mode


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " true "])
def test_truthy_values_are_recognised(monkeypatch, value):
    monkeypatch.setenv("SAMPLE_MODE", value)
    assert sample_mode() is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "sample"])
def test_other_values_are_not(monkeypatch, value):
    monkeypatch.setenv("SAMPLE_MODE", value)
    assert sample_mode() is False


def test_it_overrides_a_configured_zetaris_and_live_model(monkeypatch):
    """A sample run that half-applies is the one outcome the flag exists to prevent."""
    monkeypatch.setenv("SAMPLE_MODE", "true")
    monkeypatch.setenv("DATA_SOURCE", "zetaris")
    monkeypatch.setenv("LLM_BACKEND", "auto")

    assert apply_sample_mode() is True
    assert os.environ["DATA_SOURCE"] == "local"
    assert os.environ["LLM_BACKEND"] == "simulated"


def test_it_changes_nothing_when_off(monkeypatch):
    monkeypatch.delenv("SAMPLE_MODE", raising=False)
    monkeypatch.setenv("DATA_SOURCE", "zetaris")
    monkeypatch.setenv("LLM_BACKEND", "auto")

    assert apply_sample_mode() is False
    assert os.environ["DATA_SOURCE"] == "zetaris"
    assert os.environ["LLM_BACKEND"] == "auto"


def test_health_reports_which_mode_is_running(monkeypatch):
    from app.main import health

    monkeypatch.setenv("SAMPLE_MODE", "true")
    monkeypatch.setenv("DATA_SOURCE", "zetaris")
    monkeypatch.setenv("LLM_BACKEND", "auto")
    apply_sample_mode()

    body = health()

    assert body["sample_mode"] == "true"
    assert body["data_source"] == "local"
    assert body["llm_backend"] == "simulated"
