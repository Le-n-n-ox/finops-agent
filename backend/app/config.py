"""Process configuration: the `.env` file, loaded once, at import.

The app is configured through environment variables - `METERLESS_BASE_URL`, `METERLESS_MODEL`,
`METERLESS_API_KEY`, `DATA_SOURCE` and the rest. `.env` is how a developer supplies them on a
laptop, where a shell export is easy to forget and a compose file is not in play.

The backend used to ignore `.env` entirely: `python-dotenv` was a dependency, but nothing ever
called `load_dotenv()`. Every setting in the file was silently inert, and the app ran on its
built-in defaults no matter what the file said. That is a worse failure than a missing setting,
because the file looks like it is doing something.

Real environment variables still win over the file. In a container the compose file sets the
values it cares about, and a developer's exported variable beats a checked-out default.

The file is never echoed, logged or parsed into a report: it holds credentials, and a
configuration loader that prints what it read is a credential leak.
"""
from __future__ import annotations

import os
from pathlib import Path

# The repository root: backend/app/config.py -> backend/app -> backend -> <root>.
REPO_ROOT = Path(__file__).resolve().parents[2]

# The environment file. `FINOPS_ENV_FILE` overrides the location, for the case where the file
# does not sit next to the repository (a packaged install, a container image, a test fixture).
ENV_FILE = Path(os.getenv("FINOPS_ENV_FILE") or (REPO_ROOT / ".env")).expanduser()

# Whether the file was found and applied. Exposed so a caller can say so without re-reading it.
loaded_from: Path | None = None


def load_env() -> Path | None:
    """Load `.env` into the process environment. Returns the file that was read, if any.

    Never raises: a missing `python-dotenv`, a missing file or an unreadable file all mean the
    same thing to the app - the environment is whatever the process was given.
    """
    global loaded_from

    try:
        from dotenv import load_dotenv
    except ImportError:
        return None

    if not ENV_FILE.is_file():
        return None

    try:
        # override=False: a real environment variable beats the file.
        load_dotenv(ENV_FILE, override=False)
    except OSError:
        return None

    loaded_from = ENV_FILE
    return ENV_FILE
