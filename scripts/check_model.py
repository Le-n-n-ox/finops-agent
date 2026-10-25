"""Diagnostic for the local model server (Nightshift / meterless hotspot).

Run:
    python scripts/check_model.py          # from the repository root
    .venv/Scripts/python.exe scripts/check_model.py

It answers one question: *can the app reach and authenticate against the local
OpenAI-compatible model server?* It reports

  * every candidate base URL it tried, and whether that URL answered /v1/models;
  * every key source it found, by NAME and PATH ONLY;
  * the working (base URL, key source) combination, or exactly what is wrong;
  * whether the configured model id is in the server's model list.

It NEVER prints a credential, a token, or any fragment of one. Credentials are
referred to by env-var name or by the path of the file that holds them.

Exit code 0 when a working combination was found, 1 otherwise.
"""
from __future__ import annotations

import os
import socket
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")

PROBE_TIMEOUT = 5.0
DEFAULT_PORT = 8088
# The same default the app uses (app.integrations.llm_client.DEFAULT_MODEL): the model that was
# benchmarked on tool-call reliability. A script that reports on a different model than the app
# runs sends you looking at the wrong one.
DEFAULT_MODEL = "local-runtime/llama-3.3-70b-instruct"


# --------------------------------------------------------------------- helpers
def _local_ipv4s() -> List[str]:
    """Non-loopback IPv4 addresses of this machine.

    A container reaches the hotspot through `host.docker.internal` or through
    the host's LAN address.  The host's own loopback is not an option from in
    there: 127.0.0.1 inside a container is the container.  A UDP connect does
    not send packets, it just asks the OS which local address would be used to
    reach the outside.
    """
    found = set()
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("8.8.8.8", 80))
            found.add(probe.getsockname()[0])
        finally:
            probe.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass
    return sorted(ip for ip in found if not ip.startswith("127."))


def _normalise_base_url(raw: str) -> str:
    """Strip a trailing slash and add the /v1 suffix when it is missing."""
    url = raw.strip().rstrip("/")
    if not url:
        return url
    if not url.endswith("/v1"):
        url = f"{url}/v1"
    return url


def _nightshift_token_paths() -> List[Path]:
    """The auto-discovered Nightshift token file locations, per platform."""
    candidates: List[Path] = []
    local_appdata = os.getenv("LOCALAPPDATA")
    if local_appdata:
        candidates.append(Path(local_appdata) / "ai.meterless.runtime" / "proxy-token")
    candidates.append(
        Path.home() / "Library" / "Application Support" / "ai.meterless.runtime" / "proxy-token"
    )
    candidates.append(Path("/var/lib/meterless/proxy-token"))
    return candidates


def _read_token_file(path: Path) -> Optional[str]:
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return token or None


# ------------------------------------------------------------------ key sources
class KeySource:
    """A candidate credential.  `label` names it; the value is never printed."""

    def __init__(self, label: str, value: Optional[str], origin: str) -> None:
        self.label = label
        self.value = value
        self.origin = origin  # "env" | "file"

    @property
    def available(self) -> bool:
        return bool(self.value)

    def describe(self) -> str:
        if self.origin == "env":
            return f"env {self.label} (value hidden)"
        return f"file {self.label} (value hidden)"

    def redact(self, text: str) -> str:
        """Defence in depth: never let a token reach the output."""
        if self.value and self.value in text:
            return text.replace(self.value, "[REDACTED]")
        return text


def _key_sources() -> List[KeySource]:
    """Key candidates, in the same precedence order the backend uses."""
    sources: List[KeySource] = []

    env_key = os.getenv("METERLESS_API_KEY")
    sources.append(KeySource("METERLESS_API_KEY", env_key.strip() if env_key else None, "env"))

    token_file_env = os.getenv("METERLESS_TOKEN_FILE")
    if token_file_env:
        path = Path(token_file_env)
        sources.append(
            KeySource(
                f"METERLESS_TOKEN_FILE ({path})",
                _read_token_file(path),
                "file",
            )
        )

    for path in _nightshift_token_paths():
        if token_file_env and path == Path(token_file_env):
            continue
        sources.append(
            KeySource(
                f"Nightshift token file ({path})",
                _read_token_file(path),
                "file",
            )
        )

    # The NVIDIA key is deliberately not a candidate here. It belongs to a different cloud
    # service, the model server rejects it with a 401, and offering it means sending a
    # credential for one service to whatever address this script probes.
    return sources


# ----------------------------------------------------------------- base URLs
def _base_url_candidates() -> List[str]:
    """Candidate base URLs, in the same precedence order the backend uses."""
    candidates: List[str] = []

    configured = os.getenv("METERLESS_BASE_URL")
    if configured and configured.strip():
        candidates.append(_normalise_base_url(configured))

    candidates.append(f"http://127.0.0.1:{DEFAULT_PORT}/v1")
    candidates.append(f"http://host.docker.internal:{DEFAULT_PORT}/v1")
    for ip in _local_ipv4s():
        candidates.append(f"http://{ip}:{DEFAULT_PORT}/v1")

    seen = set()
    ordered = []
    for url in candidates:
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered


# --------------------------------------------------------------------- probing
def _probe(base_url: str, key: Optional[str]) -> Tuple[bool, int, str]:
    """GET {base_url}/models with the bearer token.

    Returns (ok, status_code, note).  Never raises.
    """
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        with httpx.Client(timeout=PROBE_TIMEOUT) as client:
            response = client.get(f"{base_url}/models", headers=headers)
    except httpx.TimeoutException:
        return False, 0, "timed out"
    except httpx.ConnectError:
        return False, 0, "connection refused / not reachable"
    except httpx.HTTPError as exc:
        return False, 0, f"transport error ({type(exc).__name__})"

    if response.status_code == 200:
        return True, 200, "answered /models"
    if response.status_code in (401, 403):
        if key:
            return False, response.status_code, "reachable but rejected the credential"
        return False, response.status_code, "reachable, but requires a credential"
    return False, response.status_code, "reachable but not a usable /models endpoint"


def _model_ids(base_url: str, key: Optional[str]) -> List[str]:
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        with httpx.Client(timeout=PROBE_TIMEOUT) as client:
            response = client.get(f"{base_url}/models", headers=headers)
        if response.status_code != 200:
            return []
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return []
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return []
    return [str(item.get("id")) for item in data if isinstance(item, dict) and item.get("id")]


# ------------------------------------------------------------------------ main
def main() -> int:
    model = os.getenv("METERLESS_MODEL") or DEFAULT_MODEL
    key_sources = _key_sources()
    base_urls = _base_url_candidates()

    # Defence in depth: every line printed below passes through this, so a
    # credential can never reach stdout even if a message echoes one back.
    secrets = [s.value for s in key_sources if s.value]

    def say(text: str = "") -> None:
        for secret in secrets:
            if secret in text:
                text = text.replace(secret, "[REDACTED]")
        print(text)

    say("Local model server check")
    say("=" * 60)
    say(f"model id: {model}")
    say()

    # ---- key sources -------------------------------------------------------
    say("Key sources found (values are never printed):")
    found_any = False
    for source in key_sources:
        if source.available:
            found_any = True
            say(f"  [ok]   {source.describe()}")
        else:
            say(f"  [none] {source.describe()}")
    if not found_any:
        say("  -> no credential was found in any source.")
    say()

    # ---- base URLs ---------------------------------------------------------
    say("Candidate base URLs:")
    reachable: List[str] = []
    for url in base_urls:
        ok, status, note = _probe(url, None)
        if ok:
            reachable.append(url)
            say(f"  [ok]   {url}  -> {note}")
        else:
            say(f"  [no]   {url}  -> {note}" + (f" (HTTP {status})" if status else ""))
    say()

    # ---- working combination ----------------------------------------------
    working: Optional[Tuple[str, KeySource]] = None
    rejected: List[str] = []

    for url in base_urls:
        for source in key_sources:
            if not source.available:
                continue
            ok, status, note = _probe(url, source.value)
            if ok:
                working = (url, source)
                break
            if status in (401, 403):
                rejected.append(f"{url} + {source.label} -> HTTP {status}")
        if working:
            break

    if working is None:
        say("FAILED: no (base URL, key) combination works.")
        if not found_any:
            say("  Reason: no API key was found for the local model server.")
        elif not reachable:
            say("  Reason: no candidate base URL answered /v1/models.")
            say("  The hotspot is probably not running. Start it, or set")
            say("  METERLESS_BASE_URL in .env to the address it is bound to.")
        else:
            say("  Reason: the server answered, but rejected every credential:")
            for line in rejected:
                say(f"    - {line}")
            say("  METERLESS_API_KEY is a different (cloud) key and returns 401 here;")
            say("  the local server wants the token from the Nightshift state directory.")
        say()
        say("The app still runs: it falls back to the deterministic stand-in and")
        say("says so in the UI and in the API response.")
        return 1

    url, source = working
    say("Working combination:")
    say(f"  base URL   : {url}")
    say(f"  credential : {source.describe()}")
    say(f"  model      : {model}")

    ids = _model_ids(url, source.value)
    if ids:
        say(f"  server lists {len(ids)} model id(s).")
        if model in ids:
            say(f"  -> '{model}' is present on the server.")
        else:
            say(f"  -> WARNING: '{model}' is NOT in the server's model list.")
            say(f"     Known ids include: {', '.join(sorted(ids)[:8])}")
            say("     Set METERLESS_MODEL to one of them.")
    say()
    say("OK: the local model server is reachable and authenticated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
