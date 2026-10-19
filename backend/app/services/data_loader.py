"""
Developer 1 — data loading + validation.

Rules: parsing lives ONLY here (no YAML/CSV parsing in the API or UI).
Never fill missing resource values with 0, never silently drop unknown services.
"""
from __future__ import annotations

from pathlib import Path

from app.models.schemas import InputBundle, ValidationIssue

DATA_FILES = {
    "deployments": "deployments.yaml",
    "usage": "usage_history.csv",
    "events": "business_events.json",
    "incidents": "incident_history.csv",
    "cost_model": "cost_model.json",
    "policy": "policy.yaml",
}


def load_inputs(data_dir: str | Path = "data") -> InputBundle:
    """Load the local fixture files and return a validated InputBundle.

    TODO(Dev1): yaml.safe_load for YAML, pandas.read_csv for CSV, json.load for JSON.
    - Raise ValueError with a helpful message if a file is missing or malformed.
    - Strip whitespace from service names; parse timestamps tz-aware.
    - Collect problems into bundle.issues instead of swallowing them.
    """
    raise NotImplementedError("load_inputs: implement with Cursor (see docs/CURSOR.md prompt #1)")


def validate_inputs(bundle: InputBundle) -> list[ValidationIssue]:
    """Return errors/warnings: unknown services, negative usage, duplicate (timestamp, service),
    bad timestamps, missing columns. Developer 2 shows these in the UI."""
    raise NotImplementedError("validate_inputs")


def load_inputs_from_zetaris(data_dir: str | Path = "data") -> InputBundle:
    """Same return type as load_inputs(), but data comes through Zetaris.
    Implement after the connection works (docs/ZETARIS_SETUP.md). Falls back to load_inputs()."""
    from app.integrations.zetaris_client import ZetarisClient  # noqa: F401

    raise NotImplementedError("load_inputs_from_zetaris")
