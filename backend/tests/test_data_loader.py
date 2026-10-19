"""Developer 1 specs. xfail(NotImplementedError) until load_inputs() exists; remove the marker when done."""
from pathlib import Path

import pytest

from app.services.data_loader import load_inputs

DATA = Path(__file__).resolve().parents[2] / "data"
todo = pytest.mark.xfail(raises=NotImplementedError, reason="Dev1: implement data_loader")


@todo
def test_valid_fixture_loads():
    b = load_inputs(DATA)
    assert len(b.services) == 5 and b.usage_rows and b.events and b.cost_model


@todo
def test_missing_file_gives_clear_error(tmp_path):
    with pytest.raises(ValueError, match="deployments"):
        load_inputs(tmp_path)


@todo
def test_unknown_service_is_flagged_not_dropped():
    ...  # copy fixtures to tmp_path, add a row for "ghost-svc", assert an UNKNOWN_SERVICE issue


@todo
def test_negative_usage_and_bad_timestamp_flagged():
    ...
