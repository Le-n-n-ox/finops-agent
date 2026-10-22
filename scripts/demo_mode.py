"""Switch the stack between the live model and the deterministic stand-in.

    python scripts/demo_mode.py fast     # the stand-in: seconds instead of minutes
    python scripts/demo_mode.py live     # the real model server
    python scripts/demo_mode.py status   # which one is running

Why this exists
---------------
A full analysis is a multi-turn conversation with the model server for every workload. On a
machine with no GPU, a 70B model is paged in from disk for every turn, so a run takes minutes -
and that is the wrong thing to be looking at while you are trying to show somebody what the
tool does. The stand-in answers the same turns from the same tools and produces the same
decisions; it just does not need a model server.

The mode is a compose override rather than a flag on the main compose file, so the default
stays the live model - the one that proves anything - and "which mode am I in?" is answerable
by looking at how the stack was started.

Nothing about the run is dressed up as something it was not: the response carries
`"llm_backend": "simulated"`, the header badge says so, and the provenance strip says so.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BASE = REPO / "docker-compose.yml"
FAST = REPO / "docker-compose.fast.yml"
API = "http://127.0.0.1:8080/api/llm/status"

MODES = ("fast", "live", "status")


def compose(files: list[Path], *args: str) -> list[str]:
    """The `docker compose` command for the given files.

    The files come first, because `-f` has to precede the subcommand: `docker compose -f a.yml
    -f b.yml up -d`, not `docker compose -f a.yml up -f b.yml -d`.
    """
    cmd = ["docker", "compose"]
    for f in files:
        cmd += ["-f", str(f)]
    return cmd + list(args)


def run(cmd: list[str]) -> int:
    print(" ".join(cmd), flush=True)
    return subprocess.call(cmd, cwd=str(REPO))


def current_mode() -> str | None:
    """What the running backend says it is using."""
    try:
        out = subprocess.run(
            ["curl", "-s", "--max-time", "5", API],
            capture_output=True, text=True, timeout=15,
        ).stdout
        if not out:
            return None
        status = json.loads(out)
    except Exception:  # noqa: BLE001 - the status is a convenience, not a requirement
        return None
    backend = status.get("backend")
    if backend == "simulated":
        return "fast"
    if backend == "openai-compatible":
        return "live"
    return None


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in MODES:
        print(__doc__)
        print(f"usage: python scripts/demo_mode.py {{{'|'.join(MODES)}}}")
        return 2

    mode = argv[1]
    if mode == "status":
        running = current_mode()
        if running is None:
            print("The backend is not answering. Is the stack up? (docker compose up -d)")
        elif running == "fast":
            print("The stack is running the DETERMINISTIC STAND-IN (fast mode).")
            print("  python scripts/demo_mode.py live   to go back to the real model.")
        else:
            print(f"The stack is running the LIVE MODEL (live mode).")
            print("  python scripts/demo_mode.py fast   for the stand-in, which is seconds.")
        return 0

    if mode == "fast":
        if not FAST.is_file():
            print(f"Missing {FAST}", file=sys.stderr)
            return 1
        code = run(compose([BASE, FAST], "up", "-d"))
    else:
        # The plain compose file has no override, so the container is recreated with the live
        # model. The stand-in is not a setting that lingers.
        code = run(compose([BASE], "up", "-d"))

    if code == 0:
        print()
        print(f"Now in {mode} mode.")
        if mode == "fast":
            print("  A full analysis now finishes in seconds instead of minutes.")
            print("  The UI says the stand-in ran, and so does the response.")
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
