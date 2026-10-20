"""Developer 1 specs for loading and validating the input fixtures."""
from pathlib import Path

import pytest

from app.services.data_loader import load_inputs

DATA = Path(__file__).resolve().parents[2] / "data"


def test_valid_fixture_loads():
    b = load_inputs(DATA)
    assert len(b.services) == 5 and b.usage_rows and b.events and b.cost_model


def test_missing_file_gives_clear_error(tmp_path):
    with pytest.raises(ValueError, match="deployments"):
        load_inputs(tmp_path)


def test_unknown_service_is_flagged_not_dropped():
    ...  # copy fixtures to tmp_path, add a row for "ghost-svc", assert an UNKNOWN_SERVICE issue


def test_negative_usage_and_bad_timestamp_flagged():
    ...
