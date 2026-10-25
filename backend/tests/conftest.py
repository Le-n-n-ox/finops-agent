"""Suite-wide configuration.

The test suite must never call a live model. Without this, the suite silently depends on
whatever model server happens to be running on the machine: the API tests would drive a real
70B model through the whole review cycle for every workload, which is slow, non-deterministic,
and - on a machine with no model server at all - so slow that the suite looks hung rather than
broken.

So the suite pins the deterministic stand-in and clears the model-server settings. The stand-in
speaks the same protocol as the live client, so the code under test is the code that runs in
production; only the reasoner behind it changes.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

# Imported for its side effect: the stand-in answers instead of a live model.
os.environ["LLM_BACKEND"] = "simulated"

# The app loads `.env` at import (app.config). The suite must not: the developer's `.env`
# points at a real model server and carries real credentials. Point the loader at a file that
# is not there, so the suite runs on the environment it was given and nothing else.
os.environ["FINOPS_ENV_FILE"] = str(Path(tempfile.gettempdir()) / "finops-agent-tests" / ".env.absent")

# Nothing in the suite may reach the model server, so the settings that point at one are
# removed rather than merely ignored. `LLM_BACKEND=simulated` already prevents the probe;
# clearing these keeps a stray `os.getenv("METERLESS_BASE_URL")` from finding a live address.
for _name in ("METERLESS_API_KEY", "METERLESS_BASE_URL", "METERLESS_TOKEN_FILE", "METERLESS_MODEL"):
    os.environ.pop(_name, None)
