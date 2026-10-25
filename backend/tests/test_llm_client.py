"""Tests for the model client's resolution, credential discovery and disclosure.

These cover the parts of the client that decide *which* reasoner answers and what the app is
allowed to say about it - the two things a reviewer has to be able to trust.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.integrations import llm_client


@pytest.fixture(autouse=True)
def _no_token_file_anywhere(monkeypatch, tmp_path):
    """Point every token-file candidate at a directory that holds no token.

    The real candidates are the machine's own state directories. A test that depends on the
    developer's machine is a test that fails on someone else's.
    """
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("METERLESS_TOKEN_FILE", str(tmp_path / "absent"))
    monkeypatch.delenv("METERLESS_API_KEY", raising=False)


class TestBackendSelection:
    def test_the_default_is_auto(self, monkeypatch):
        monkeypatch.delenv("LLM_BACKEND", raising=False)
        assert llm_client.requested_backend() == "auto"

    def test_simulated_is_pinned(self, monkeypatch):
        monkeypatch.setenv("LLM_BACKEND", "simulated")
        assert llm_client.requested_backend() == "simulated"

    def test_an_unknown_value_falls_back_to_auto(self, monkeypatch):
        """A typo must not silently disable the model."""
        monkeypatch.setenv("LLM_BACKEND", "lve")
        assert llm_client.requested_backend() == "auto"

    def test_pinning_simulated_never_contacts_a_server(self, monkeypatch):
        """The pinned mode must not probe, even when a server is reachable.

        The test suite runs under this mode. A probe would make the suite depend on whatever
        model server happens to be running, and a live model in the loop makes it slow and
        non-deterministic.
        """
        monkeypatch.setenv("LLM_BACKEND", "simulated")

        def _boom(*args, **kwargs):  # pragma: no cover - the assertion is that it never runs
            raise AssertionError("the pinned mode must not probe for a model server")

        monkeypatch.setattr(llm_client, "resolve_llm_config", _boom)
        monkeypatch.setattr(llm_client, "_probe_sync", _boom)
        # Start from nothing cached, so a client resolved earlier cannot answer for this test.
        llm_client.reset_llm_client()

        _client, status = llm_client.get_llm_client()
        assert status["backend"] == "simulated"
        assert "LLM_BACKEND" in (status["detail"] or "")

    def test_the_pinned_status_is_reported_by_llm_status(self, monkeypatch):
        monkeypatch.setenv("LLM_BACKEND", "simulated")
        status = llm_client.llm_status()
        assert status["backend"] == "simulated"
        assert status["model"] is None
        assert status["detail"], "the app must say why no model ran"


class TestCredentialDiscovery:
    def test_a_cloud_key_is_never_used_as_a_model_server_credential(self, monkeypatch):
        """A key for a different service must not be sent to the model server.

        The NVIDIA key belongs to a cloud service that is not the agent cycle's model. Sending
        it to whatever base URL we happen to try hands a credential to the wrong host, and it
        is rejected with a 401 anyway.
        """
        monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-not-a-model-server-key")
        sources = [name for name, _ in llm_client._key_candidates()]
        assert not any("NVIDIA" in name for name in sources)

    def test_the_env_key_is_used_when_it_is_set(self, monkeypatch):
        monkeypatch.setenv("METERLESS_API_KEY", "a-key")
        sources = dict(llm_client._key_candidates())
        assert "env METERLESS_API_KEY" in sources

    def test_the_token_file_is_used_when_there_is_no_env_key(self, monkeypatch, tmp_path):
        token = tmp_path / "proxy-token"
        token.write_text("file-token", encoding="utf-8")
        monkeypatch.setenv("METERLESS_TOKEN_FILE", str(token))
        sources = dict(llm_client._key_candidates())
        assert any(name.startswith("file ") and value == "file-token" for name, value in sources.items())


class TestHonestDisclosure:
    def test_the_reason_the_stand_in_was_used_is_specific(self, monkeypatch):
        """The status must say WHY, not just "no model"."""
        monkeypatch.setenv("METERLESS_API_KEY", "a-key")
        detail = llm_client._why_simulated()
        assert "http://" in detail, "the status must name the base URLs that were tried"

    def test_a_missing_credential_is_reported_as_a_missing_credential(self, monkeypatch):
        detail = llm_client._why_simulated()
        assert "METERLESS_API_KEY" in detail
        assert "credential" in detail.lower()

    def test_the_detail_never_contains_the_credential(self, monkeypatch):
        """The reason is for a human to read; the token is not part of it."""
        monkeypatch.setenv("METERLESS_API_KEY", "super-secret-value")
        detail = llm_client._why_simulated()
        assert "super-secret-value" not in detail


class _FakeResponse:
    """The two things `_post` reads off a response: the status code and the body."""

    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    @property
    def text(self):
        return str(self._payload)


class TestAMalformedAnswerIsAnOutage:
    """A 200 is not a guarantee of a well-formed body.

    A server that answers with a list, or with a choice that is not an object, used to raise
    a raw AttributeError. That is not an `LLMUnavailable`, so it slipped past the outage
    handling and left the workload looking like it was never reviewed - the opposite of what
    the outage path exists to say.
    """

    def _client(self) -> "llm_client.OpenAICompatClient":
        return llm_client.OpenAICompatClient(
            llm_client.LLMConfig(base_url="http://127.0.0.1:8088/v1", api_key="k",
                                 model="m", key_source="env METERLESS_API_KEY"),
            timeout=1.0,
        )

    def _patch_post(self, monkeypatch, payload):
        async def fake_post(_client, url, **kwargs):
            return _FakeResponse(200, payload)

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    @pytest.mark.parametrize("payload", [
        ["not", "an", "object"],
        {"choices": []},
        {"choices": ["not an object"]},
        {"choices": [{"message": "not an object"}]},
        {"choices": [{"no_message_key": True}]},
    ])
    def test_a_malformed_body_is_reported_as_an_outage(self, monkeypatch, payload):
        self._patch_post(monkeypatch, payload)
        client = self._client()
        with pytest.raises(llm_client.LLMUnavailable):
            asyncio.run(client.chat("system", "user", [], []))

    def test_a_well_formed_body_still_works(self, monkeypatch):
        self._patch_post(monkeypatch, {"choices": [{"message": {"content": "hello"}}]})
        client = self._client()
        answer = asyncio.run(client.chat("system", "user", [], []))
        assert answer["content"] == "hello"
        assert answer["conclusion"] is True


class TestABadRequestIsOnlyRetriedWhenRetryingCanFixIt:
    """Some models reject `temperature` or `max_tokens` outright.

    The request is otherwise valid, so it is worth one more attempt without those two fields.
    A 400 with any other cause is the server's considered answer, and retrying it just makes
    the failure take twice as long.
    """

    def _client(self) -> "llm_client.OpenAICompatClient":
        return llm_client.OpenAICompatClient(
            llm_client.LLMConfig(base_url="http://127.0.0.1:8088/v1", api_key="k",
                                 model="m", key_source="env METERLESS_API_KEY"),
            timeout=1.0,
        )

    def _patch_post(self, monkeypatch, responses):
        bodies = []

        async def fake_post(_client, url, **kwargs):
            bodies.append(kwargs.get("json"))
            item = responses[min(len(bodies) - 1, len(responses) - 1)]
            if isinstance(item, Exception):
                raise item
            return item

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        monkeypatch.setattr(llm_client, "TRANSIENT_RETRY_BACKOFF_SECONDS", 0.0)
        return bodies

    def test_a_400_that_blames_temperature_is_retried_without_it(self, monkeypatch):
        bodies = self._patch_post(monkeypatch, [
            _FakeResponse(400, {"error": "temperature is not supported by this model"}),
            _FakeResponse(200, {"choices": [{"message": {"content": "hello"}}]}),
        ])

        client = self._client()
        answer = asyncio.run(client.chat("s", "u", [], []))

        assert answer["content"] == "hello"
        assert len(bodies) == 2, "the 400 was not retried"
        assert "temperature" in bodies[0]
        assert "temperature" not in bodies[1], "the retry still carried the offending field"

    def test_a_400_with_another_cause_is_not_retried(self, monkeypatch):
        bodies = self._patch_post(monkeypatch, [
            _FakeResponse(400, {"error": "unknown model id"}),
        ])

        client = self._client()
        with pytest.raises(llm_client.LLMUnavailable):
            asyncio.run(client.chat("s", "u", [], []))

        assert len(bodies) == 1, "a 400 that cannot be fixed was retried"

    def test_a_400_with_a_generic_body_is_not_retried(self, monkeypatch):
        """A server that does not say what is wrong is not evidence that dropping fields helps."""
        bodies = self._patch_post(monkeypatch, [
            _FakeResponse(400, {"error": "Bad Request"}),
        ])

        client = self._client()
        with pytest.raises(llm_client.LLMUnavailable):
            asyncio.run(client.chat("s", "u", [], []))

        assert len(bodies) == 1


class TestTransientFailuresAreRetried:
    """A model server that hiccups is not the same as one that refuses.

    One dropped connection used to cost a whole workload its review cycle, because the
    exception unwound the workload and the pipeline fell back to the deterministic critic
    without saying why. These tests pin that a transient failure is retried, and that a
    considered refusal is not.
    """

    def _client(self) -> "llm_client.OpenAICompatClient":
        return llm_client.OpenAICompatClient(
            llm_client.LLMConfig(base_url="http://127.0.0.1:8088/v1", api_key="k",
                                 model="m", key_source="env METERLESS_API_KEY"),
            timeout=1.0,
        )

    def _patch_post(self, monkeypatch, responses):
        """Replace the HTTP POST with a scripted sequence of responses or exceptions."""
        calls = []

        async def fake_post(_client, url, **kwargs):
            calls.append(url)
            item = responses[min(len(calls) - 1, len(responses) - 1)]
            if isinstance(item, Exception):
                raise item
            return item

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        monkeypatch.setattr(llm_client, "TRANSIENT_RETRY_BACKOFF_SECONDS", 0.0)
        return calls

    def test_a_server_error_is_retried_and_then_answers(self, monkeypatch):
        calls = self._patch_post(monkeypatch, [
            _FakeResponse(503, {"error": "loading"}),
            _FakeResponse(200, {"choices": [{"message": {"content": "hello"}}]}),
        ])

        client = self._client()
        answer = asyncio.run(client.chat("s", "u", [], []))

        assert answer["content"] == "hello"
        assert len(calls) == 2, "the 503 was not retried"

    def test_a_connection_error_is_retried(self, monkeypatch):
        calls = self._patch_post(monkeypatch, [
            httpx.ConnectError("connection refused"),
            _FakeResponse(200, {"choices": [{"message": {"content": "hello"}}]}),
        ])

        client = self._client()
        answer = asyncio.run(client.chat("s", "u", [], []))

        assert answer["content"] == "hello"
        assert len(calls) == 2, "the connection error was not retried"

    def test_a_refusal_is_not_retried(self, monkeypatch):
        """A 401 is the server's considered answer. Retrying it just wastes the review."""
        calls = self._patch_post(monkeypatch, [_FakeResponse(401, {"error": "no"})])

        client = self._client()
        with pytest.raises(llm_client.LLMUnavailable) as caught:
            asyncio.run(client.chat("s", "u", [], []))

        assert "401" in str(caught.value)
        assert len(calls) == 1, "a refusal was retried"

    def test_a_server_that_never_answers_gives_up_and_says_why(self, monkeypatch):
        calls = self._patch_post(monkeypatch, [_FakeResponse(503, {"error": "loading"})])

        client = self._client()
        with pytest.raises(llm_client.LLMUnavailable) as caught:
            asyncio.run(client.chat("s", "u", [], []))

        assert "503" in str(caught.value)
        assert len(calls) == llm_client.TRANSIENT_RETRY_ATTEMPTS

    def test_a_busy_server_is_hidden_out(self, monkeypatch):
        """The model server is busiest exactly when the app is talking to it most.

        A full analysis is a long series of back-to-back requests against a single local
        runtime, so a dropped connection or a 502 in the middle of one is usually a queue
        backing up rather than a server that is down - and the next request a few seconds
        later is usually fine. Giving up too quickly cut a third of the reviews short, for
        no reason that had anything to do with the workload.
        """
        calls = self._patch_post(monkeypatch, [
            _FakeResponse(502, {"error": "upstream unavailable"}),
            _FakeResponse(502, {"error": "upstream unavailable"}),
            _FakeResponse(200, {"choices": [{"message": {"content": "hello"}}]}),
        ])

        client = self._client()
        answer = asyncio.run(client.chat("s", "u", [], []))

        assert answer["content"] == "hello"
        assert len(calls) == 3, "the client gave up on a server that was only briefly busy"

    def test_the_patience_is_bounded(self):
        """A server that is genuinely gone has to be reported, not waited on forever."""
        total_wait = sum(llm_client.TRANSIENT_RETRY_BACKOFF_SECONDS * (attempt + 1)
                         for attempt in range(llm_client.TRANSIENT_RETRY_ATTEMPTS - 1))
        assert total_wait <= 30, f"the client would wait {total_wait:.0f}s before giving up"
        assert llm_client.TRANSIENT_RETRY_ATTEMPTS >= 4, "the client is not patient enough"


class TestTheCredentialNeverReachesAnErrorMessage:
    """An error message can end up in the API response, so it must be scrubbed.

    The client redacts its own token on the way out. A transport error that echoes a request
    header is exactly the case this exists for.
    """

    def _client(self, key: str = "super-secret-token") -> "llm_client.OpenAICompatClient":
        return llm_client.OpenAICompatClient(
            llm_client.LLMConfig(base_url="http://127.0.0.1:8088/v1", api_key=key,
                                 model="m", key_source="env METERLESS_API_KEY"),
            timeout=1.0,
        )

    def test_a_transport_error_that_echoes_the_token_is_scrubbed(self, monkeypatch):
        async def fake_post(_client, url, **kwargs):
            raise httpx.ConnectError("Authorization: Bearer super-secret-token")

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        monkeypatch.setattr(llm_client, "TRANSIENT_RETRY_BACKOFF_SECONDS", 0.0)

        client = self._client()
        with pytest.raises(llm_client.LLMUnavailable) as caught:
            asyncio.run(client.chat("s", "u", [], []))

        assert "super-secret-token" not in str(caught.value)

    def test_the_reason_a_server_refused_does_not_carry_the_token(self, monkeypatch):
        async def fake_post(_client, url, **kwargs):
            return _FakeResponse(401, {"error": "bad key super-secret-token"})

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

        client = self._client()
        with pytest.raises(llm_client.LLMUnavailable) as caught:
            asyncio.run(client.chat("s", "u", [], []))

        assert "super-secret-token" not in str(caught.value)
