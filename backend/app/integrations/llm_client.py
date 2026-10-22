"""The live language-model client behind the agent cycle.

The agent cycle used to be driven by `SimulatedLLMClient` - a scripted stand-in that answered in
character. It was never a language model, and the UI said so. This module is the real thing: an
OpenAI-compatible chat-completions client with tool calling, pointed at whatever model server the
machine happens to run (the Nightshift/meterless hotspot, by default).

Two rules shape everything here.

**Never pretend a model ran.** `get_llm_client()` returns the live client when a server
authenticated, and the deterministic stand-in otherwise - and the status says which, and why. A
reviewer who believes a model was called reads a different kind of trust into the objections than
the code actually supports, so the app has to be able to say "nothing ran" out loud.

**Never leak the credential.** The bearer token is discovered from the environment or from a file
next to the model server. It is never printed, never logged, and never written anywhere. It is
referred to only by the name of the source it came from.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TypedDict

import httpx

# The model this app is tuned for. Chosen by benchmarking the tool-call reliability of every model
# the local server exposes (5 runs each, measuring whether the model emits a well-formed tool call
# on the first turn and whether it reaches a conclusion):
#
#   local-runtime/llama-3.3-70b-instruct   5/5 first-turn tool calls, 5/5 conclusions,  5.4s avg
#   meterless/fast                          5/5 first-turn tool calls, 5/5 conclusions, 12.5s avg
#   local-runtime/qwen3.8-27b               3/5 first-turn tool calls, 3/5 conclusions,  7.4s avg
#   local-runtime/gpt-oss-20b               2/5 first-turn tool calls, 3/5 conclusions,  7.7s avg
#   meterless/auto                          2/5 first-turn tool calls, 2/5 conclusions, 11.6s avg
#
# A model that cannot reliably call a tool is worse than no model: it burns the cycle's iteration
# budget without gathering evidence, and the critic then rules on a proposal nobody validated.
DEFAULT_MODEL = "local-runtime/llama-3.3-70b-instruct"

# Where the hotspot listens. Overridable, because the answer depends on where the app runs: on the
# host, loopback works; in a container, the host's LAN address is the only thing that answers.
DEFAULT_PORT = 8088
LOOPBACK_BASE_URL = f"http://127.0.0.1:{DEFAULT_PORT}/v1"
DOCKER_HOST_BASE_URL = f"http://host.docker.internal:{DEFAULT_PORT}/v1"

# The model server's own token file. It lives beside the server, and it is the only credential the
# local server accepts - a cloud API key returns 401 here.
TOKEN_FILE_CANDIDATES = (
    "{localappdata}/ai.meterless.runtime/proxy-token",
    "~/Library/Application Support/ai.meterless.runtime/proxy-token",
    "/var/lib/meterless/proxy-token",
)

# The simplified tool schema the toolbox speaks -> JSON Schema the model server understands.
_JSON_TYPES = {
    "string": "string",
    "number": "number",
    "integer": "integer",
    "boolean": "boolean",
    "object": "object",
    "array": "array",
}

# Which reasoner to use, chosen by configuration.
#
#   auto      - probe for a model server; fall back to the deterministic stand-in when none
#               answers. The default, and the only mode that is allowed to use a live model.
#   simulated - pin the deterministic stand-in. No probe, no network, no live model, whatever
#               happens to be running on the machine. The test suite pins it, so a suite that
#               runs next to a model server is still offline, fast and deterministic; and a
#               demo that must be reproducible can pin it too.
BACKEND_AUTO = "auto"
BACKEND_SIMULATED = "simulated"
BACKEND_ENV_VAR = "LLM_BACKEND"


class LLMResponse(TypedDict):
    """One turn from a language model, normalised across clients.

    `conclusion` means "this turn ends the phase". A turn that calls a tool is never a conclusion:
    the model is still working, and treating its preamble ("let me check X") as a final answer
    would end the phase after a single tool call - before `validate_policy` ever runs.
    """

    content: Optional[str]
    tool_call: Optional[Dict[str, Any]]
    thought: Optional[str]
    conclusion: bool
    tool_call_id: Optional[str]


class LLMStatus(TypedDict):
    """What the UI needs to say out loud about which reasoner ran."""

    backend: str  # "openai-compatible" | "simulated"
    model: Optional[str]
    base_url: Optional[str]
    key_source: Optional[str]  # the NAME of the credential's source, never the credential
    detail: Optional[str]  # why the stand-in was used, when it was


@dataclass(frozen=True)
class LLMConfig:
    """A resolved connection to a model server."""

    base_url: str
    api_key: str
    model: str
    key_source: str


class LLMUnavailable(RuntimeError):
    """The model server could not be reached, or refused the request.

    Carries the base URL and the HTTP status so the failure can be explained without guessing.
    """


# A model server that hiccups is not the same as one that refuses the request. A dropped
# connection, a read timeout, or a 503 while the server reloads a model are all transient: the
# same request usually succeeds a moment later. Giving up on the first one costs a whole
# workload its review cycle, so transient failures are retried a bounded number of times with a
# growing pause. A refusal (4xx) is not transient and is never retried.
#
# The patience here is deliberate. The model server is a single local runtime, and a full
# analysis is a long series of back-to-back requests against it - so the server is exactly
# busiest when the app is talking to it most. A dropped connection or a 502 in the middle of
# that is usually a queue backing up, not a server that is down, and the next request a few
# seconds later is usually fine. Giving up after a few seconds of patience cut a third of the
# reviews short, for no reason that had anything to do with the workload.
#
# It is still bounded: a server that is genuinely gone is reported in about half a minute, and
# the phase ends with the evidence it had rather than hanging.
TRANSIENT_RETRY_ATTEMPTS = 4
TRANSIENT_RETRY_BACKOFF_SECONDS = 3.0


# ---------------------------------------------------------------------- tool schema


def tool_schema_to_json_schema(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Convert the toolbox's simplified parameter map into JSON Schema.

    The toolbox describes a tool as `{"workload_id": "string", "proposal_data": "object?"}`.
    A trailing `?` marks the parameter optional, which is exactly the distinction JSON Schema
    draws between a property and a required property.
    """
    properties: Dict[str, Any] = {}
    required: List[str] = []
    for name, spec in (parameters or {}).items():
        text = str(spec)
        optional = text.endswith("?")
        base = text[:-1] if optional else text
        properties[name] = {"type": _JSON_TYPES.get(base, "string")}
        if not optional:
            required.append(name)
    schema: Dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def to_openai_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Wrap the toolbox's tool definitions in the OpenAI `tools` envelope."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool_schema_to_json_schema(tool.get("parameters") or {}),
            },
        }
        for tool in (tools or [])
    ]


# ---------------------------------------------------------------------- credential discovery


def _normalise_base_url(url: str) -> str:
    """Trim a base URL to a canonical `.../v1` form."""
    cleaned = (url or "").strip().rstrip("/")
    if not cleaned:
        return ""
    return cleaned if cleaned.endswith("/v1") else cleaned + "/v1"


def _token_file_candidates() -> List[Path]:
    """Every place the model server's token file might be, most likely first."""
    candidates: List[Path] = []
    configured = os.getenv("METERLESS_TOKEN_FILE")
    if configured:
        candidates.append(Path(configured).expanduser())
    for template in TOKEN_FILE_CANDIDATES:
        local = os.environ.get("LOCALAPPDATA")
        text = template.format(localappdata=local) if local else template
        if "{" in text:
            continue
        candidates.append(Path(text).expanduser())
    return candidates


def _key_candidates() -> List[Tuple[str, str]]:
    """Credential sources, most authoritative first.

    Each entry is `(source name, the credential)`. The name is what gets reported; the credential
    never leaves this function except into an HTTP header.

    Only the model server's own token is listed. A cloud key - the NVIDIA one, for instance -
    belongs to a different service, is rejected by this server with a 401, and must not be sent
    to an arbitrary base URL merely because we ran out of ideas: that is a credential handed to
    the wrong host.
    """
    found: List[Tuple[str, str]] = []

    env_key = os.getenv("METERLESS_API_KEY")
    if env_key:
        found.append(("env METERLESS_API_KEY", env_key))

    for path in _token_file_candidates():
        try:
            if path.is_file():
                value = path.read_text(encoding="utf-8").strip()
                if value:
                    found.append((f"file {path}", value))
                    break
        except OSError:
            continue

    return found


def _local_ipv4_addresses() -> List[str]:
    """This machine's non-loopback IPv4 addresses.

    A container cannot reach the host's loopback, and the hotspot deliberately does not bind the
    Docker bridge. The host's LAN address is the one address that answers from both places.
    """
    addresses: List[str] = []
    try:
        _host, _alias, ips = socket.gethostbyname_ex(socket.gethostname())
        addresses.extend(ips)
    except OSError:
        pass
    try:
        # The address the OS would route outbound on - usually the LAN address.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))  # TEST-NET-1: never routed, no packet is sent
            addresses.append(probe.getsockname()[0])
    except OSError:
        pass

    unique: List[str] = []
    for address in addresses:
        if address in unique or address.startswith("127."):
            continue
        try:
            import ipaddress

            if ipaddress.ip_address(address).is_loopback:
                continue
        except ValueError:
            continue
        unique.append(address)
    return unique


def _base_url_candidates() -> List[str]:
    """Base URLs to try, most explicit first."""
    candidates: List[str] = []
    configured = os.getenv("METERLESS_BASE_URL")
    if configured:
        candidates.append(_normalise_base_url(configured))
    candidates.append(LOOPBACK_BASE_URL)
    candidates.append(DOCKER_HOST_BASE_URL)
    for address in _local_ipv4_addresses():
        candidates.append(_normalise_base_url(f"http://{address}:{DEFAULT_PORT}"))
    return candidates


# ---------------------------------------------------------------------- the client


class OpenAICompatClient:
    """A chat-completions client with tool calling, over any OpenAI-compatible server.

    The client owns the wire format and nothing else. It does not know what a Proposer is, what
    `validate_policy` means, or which numbers are safe to trust - the orchestrator owns all of
    that. Keeping the split sharp is what lets the deterministic stand-in be swapped in for the
    live model without either side changing.
    """

    def __init__(self, config: LLMConfig, timeout: float = 180.0) -> None:
        self.config = config
        self.timeout = timeout
        self.status: LLMStatus = {
            "backend": "openai-compatible",
            "model": config.model,
            "base_url": config.base_url,
            "key_source": config.key_source,
            "detail": None,
        }

    # -- wire helpers
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

    def _url(self, path: str) -> str:
        return f"{self.config.base_url.rstrip('/')}/{path.lstrip('/')}"

    def _redact(self, text: str) -> str:
        """Strip the credential out of a message that is about to be published.

        These messages end up in the API response, so a transport error that happens to echo a
        request header must not carry the token into the UI.
        """
        key = self.config.api_key
        if key and key in text:
            text = text.replace(key, "[REDACTED]")
        return text

    def _body(self, system: str, user: str, tools: List[Dict[str, Any]],
              history: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "model": self.config.model,
            "messages": self._messages(system, user, history),
            "tools": to_openai_tools(tools),
            "tool_choice": "auto",
            "temperature": 0.2,
            "max_tokens": 2048,
        }

    @staticmethod
    def _messages(system: str, user: str, history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Build the message list for one turn.

        The phase's own history is the real conversation: it already contains the tool results, so
        when the last thing that happened was a tool returning, the accumulated prose the
        orchestrator keeps alongside it would only repeat the same evidence in a second, larger
        form. The trailing user turn is therefore added only when the model is not already
        answering a tool result.
        """
        messages: List[Dict[str, Any]] = [{"role": "system", "content": system}]
        messages.extend(history or [])
        if not (messages and messages[-1].get("role") == "tool"):
            messages.append({"role": "user", "content": user})
        return messages

    # -- public API
    async def chat(self, system: str, user: str, tools: List[Dict[str, Any]],
                   history: List[Dict[str, Any]]) -> LLMResponse:
        """One turn: the model either calls a tool, or answers."""
        body = self._body(system, user, tools, history)
        payload = await self._post("/chat/completions", body)

        # A 200 is not a guarantee of a well-formed body. A server that answers with a list, or
        # with a choice that is not an object, must be reported as an outage - not as a raw
        # AttributeError, which would slip past the outage handling and leave the workload
        # looking like it was never reviewed.
        if not isinstance(payload, dict):
            raise LLMUnavailable(
                f"The model server at {self.config.base_url} returned a response that is not a JSON object."
            )
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LLMUnavailable(
                f"The model server at {self.config.base_url} returned no choices."
            )
        first = choices[0]
        if not isinstance(first, dict):
            raise LLMUnavailable(
                f"The model server at {self.config.base_url} returned a malformed choice."
            )
        message = first.get("message")
        if not isinstance(message, dict):
            raise LLMUnavailable(
                f"The model server at {self.config.base_url} returned a malformed message."
            )
        return self._parse(message)

    async def probe(self) -> bool:
        """True when the server answers `/models` with the configured credential."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(self._url("/models"), headers=self._headers())
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """POST, and turn every failure mode into an `LLMUnavailable` that names the cause.

        Transient failures (a dropped connection, a timeout, a 5xx) are retried before they are
        given up on, because one of them used to cost a whole workload its review cycle. A refusal
        (4xx) is the server's considered answer and is not retried.
        """
        last_cause = "did not answer"
        for attempt in range(TRANSIENT_RETRY_ATTEMPTS):
            transient = False
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(self._url(path), headers=self._headers(), json=body)
                    if response.status_code == 400 and self._blames_optional_params(response):
                        # Some models reject `temperature`/`max_tokens` outright. The request is
                        # otherwise valid, so retry it with the bare minimum rather than fail the
                        # cycle. Only when the server says so: a 400 caused by anything else -
                        # an unknown model id, a tool schema it rejects - is not fixed by dropping
                        # those two fields, and retrying it anyway only doubles the wait.
                        minimal = {key: body[key] for key in ("model", "messages", "tools") if key in body}
                        response = await client.post(self._url(path), headers=self._headers(), json=minimal)
                    if response.status_code >= 500:
                        # The server is up but broken: 502/503/504 are the shapes a model server
                        # takes while it swaps a model in.
                        last_cause = f"returned HTTP {response.status_code}"
                        transient = True
                    elif response.status_code >= 400:
                        raise LLMUnavailable(self._redact(
                            f"The model server at {self.config.base_url} returned HTTP {response.status_code}."
                        ))
                    else:
                        try:
                            return response.json()
                        except ValueError as exc:
                            raise LLMUnavailable(self._redact(
                                f"The model server at {self.config.base_url} returned a response that is not JSON."
                            )) from exc
            except httpx.HTTPError as exc:
                last_cause = self._redact(f"could not be reached: {exc}")
                transient = True

            if transient and attempt + 1 < TRANSIENT_RETRY_ATTEMPTS:
                await asyncio.sleep(TRANSIENT_RETRY_BACKOFF_SECONDS * (attempt + 1))

        raise LLMUnavailable(self._redact(
            f"The model server at {self.config.base_url} {last_cause} "
            f"after {TRANSIENT_RETRY_ATTEMPTS} attempts."
        ))

    @staticmethod
    def _blames_optional_params(response: httpx.Response) -> bool:
        """Whether a 400 points at `temperature` or `max_tokens`.

        That is the only case the minimal retry can fix. Everything else - an unknown model
        id, a tool schema the server rejects - is the server's considered answer, and the
        request is not going to succeed with two fewer fields.
        """
        try:
            detail = response.text.lower()
        except Exception:  # noqa: BLE001 - a body we cannot read is not evidence either way
            return False
        return "temperature" in detail or "max_tokens" in detail or "max tokens" in detail

    def _parse(self, message: Dict[str, Any]) -> LLMResponse:
        """Turn one assistant message into an `LLMResponse`."""
        content = message.get("content")
        thought = message.get("reasoning_content") or message.get("reasoning")
        tool_calls = message.get("tool_calls") or []

        if not tool_calls:
            # No tool call: the model is answering. This is the end of the phase.
            return {
                "content": content,
                "tool_call": None,
                "thought": thought,
                "conclusion": True,
                "tool_call_id": None,
            }

        first = tool_calls[0] or {}
        function = first.get("function") or {}
        arguments = self._parse_arguments(function.get("arguments"))
        return {
            # The content alongside a tool call is the model's preamble, not its answer. Treating
            # it as the answer would end the phase before the tool had been used.
            "content": content,
            "tool_call": {"name": function.get("name"), "arguments": arguments},
            "thought": thought,
            "conclusion": False,
            "tool_call_id": first.get("id"),
        }

    @staticmethod
    def _parse_arguments(raw: Any) -> Dict[str, Any]:
        """Tool arguments are a JSON string; a malformed one must not kill the cycle."""
        if isinstance(raw, dict):
            return raw
        if not isinstance(raw, str) or not raw.strip():
            return {}
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}


# ---------------------------------------------------------------------- resolution


def _probe_sync(base_url: str, api_key: str) -> bool:
    """Synchronous reachability probe, used only during resolution."""
    try:
        response = httpx.get(
            f"{base_url.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10.0,
        )
        return response.status_code == 200
    except httpx.HTTPError:
        return False


def resolve_llm_config() -> Optional[LLMConfig]:
    """Find a model server that accepts one of the credentials we have.

    Tries every base URL against every credential and returns the first combination that
    authenticates. Never raises and never prints the credential: a resolution failure is a
    normal, expected state, and the app has to keep working without a model.
    """
    model = os.getenv("METERLESS_MODEL") or DEFAULT_MODEL
    keys = _key_candidates()
    if not keys:
        return None

    failures: List[str] = []
    for base_url in _base_url_candidates():
        for key_source, api_key in keys:
            if _probe_sync(base_url, api_key):
                return LLMConfig(base_url=base_url, api_key=api_key, model=model, key_source=key_source)
            failures.append(f"{base_url} with {key_source}")

    return None


def _simulated_client() -> Tuple[Any, LLMStatus]:
    """The offline stand-in, and the status that says so."""
    from app.services.simulated_llm import SimulatedLLMClient

    detail = _why_simulated()
    return SimulatedLLMClient(), {
        "backend": "simulated",
        "model": None,
        "base_url": None,
        "key_source": None,
        "detail": detail,
    }


def _why_simulated() -> str:
    """The honest, specific reason the stand-in is being used."""
    if not _key_candidates():
        return (
            "No credential for the local model server was found. Set METERLESS_API_KEY, or point "
            "METERLESS_TOKEN_FILE at the token file beside the model server."
        )
    # `_base_url_candidates()` returns plain URLs - one string per candidate, not a pair.
    return (
        "No model server accepted the available credentials. Tried: "
        f"{', '.join(_base_url_candidates())}."
    )


# The resolved client is cached for the process lifetime. A cached "simulated" verdict is not
# sticky: while the app is running on the stand-in, the probe is repeated, so a model server that
# starts later is picked up without a restart. The re-probe is rate-limited, though: a machine
# with no model server would otherwise pay the full probe - every base URL against every
# credential - on every single request.
_cached_client: Optional[Any] = None
_cached_status: Optional[LLMStatus] = None
_simulated_at: float = 0.0

# How long a "no model server answered" verdict is believed before the probe is repeated.
SIMULATED_RETRY_SECONDS = 30.0


def requested_backend() -> str:
    """Which reasoner the configuration asks for: `auto` or `simulated`."""
    value = (os.getenv(BACKEND_ENV_VAR) or BACKEND_AUTO).strip().lower()
    return value if value in (BACKEND_AUTO, BACKEND_SIMULATED) else BACKEND_AUTO


def reset_llm_client() -> None:
    """Forget the resolved client, so the next call probes again."""
    global _cached_client, _cached_status, _simulated_at
    _cached_client = None
    _cached_status = None
    _simulated_at = 0.0


def get_llm_client(refresh: bool = False) -> Tuple[Any, LLMStatus]:
    """The client the agent cycle should use, and a status describing it."""
    global _cached_client, _cached_status, _simulated_at

    if requested_backend() == BACKEND_SIMULATED:
        # Pinned offline: no probe, no network, and a fresh stand-in per call so that one
        # analysis cannot influence the next through the client's call counter.
        client, status = _simulated_client()
        status["detail"] = (
            f"The deterministic stand-in was selected by configuration ({BACKEND_ENV_VAR}="
            f"{BACKEND_SIMULATED}); no model server was contacted.")
        return client, status

    live = (_cached_status or {}).get("backend") == "openai-compatible"
    believed = _cached_client is not None and (time.monotonic() - _simulated_at) < SIMULATED_RETRY_SECONDS
    if refresh or _cached_client is None or (not live and not believed):
        config = resolve_llm_config()
        if config is not None:
            client = OpenAICompatClient(config)
            _cached_client = client
            _cached_status = {
                "backend": "openai-compatible",
                "model": config.model,
                "base_url": config.base_url,
                "key_source": config.key_source,
                "detail": None,
            }
        else:
            _cached_client, _cached_status = _simulated_client()
            _simulated_at = time.monotonic()

    return _cached_client, _cached_status  # type: ignore[return-value]


def llm_status() -> LLMStatus:
    """The status of the client currently in use, without re-probing."""
    if requested_backend() == BACKEND_SIMULATED:
        _client, status = _simulated_client()
        status["detail"] = (
            f"The deterministic stand-in was selected by configuration ({BACKEND_ENV_VAR}="
            f"{BACKEND_SIMULATED}); no model server was contacted.")
        return status
    if _cached_status is None:
        get_llm_client()
    return _cached_status or {  # type: ignore[return-value]
        "backend": "simulated",
        "model": None,
        "base_url": None,
        "key_source": None,
        "detail": "The model server has not been contacted yet.",
    }
