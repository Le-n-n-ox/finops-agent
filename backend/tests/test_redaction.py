"""The scrubber: what it must remove, and what it must not.

A credential must never reach the response, the log or the report. But a scrubber that eats
ordinary words is a scrubber nobody trusts, and one that misses a prefixed credential name is
a scrubber that leaks. Both failure modes are pinned here.
"""
from __future__ import annotations

import pytest

from app.services.redaction import scrub


class TestCredentialsAreRemoved:
    @pytest.mark.parametrize("text", [
        "Authorization: Bearer super-secret-token",
        "authorization=Bearer super-secret-token",
        "Bearer super-secret-token",
        "api_key=super-secret-token",
        "api-key: super-secret-token",
        "token=super-secret-token",
        "secret: super-secret-token",
        "password=super-secret-token",
        # Prefixed names. The prefix ends in a word character, so a word-boundary anchor
        # misses these entirely.
        "access_token=super-secret-token",
        "refresh_token=super-secret-token",
        "auth_token=super-secret-token",
        "session_token=super-secret-token",
        "id_token=super-secret-token",
        "client_secret=super-secret-token",
        "app_secret: super-secret-token",
        "db_password=super-secret-token",
        "user_password: super-secret-token",
        # A credential in a URL, echoed back by a third party.
        "https://example.test/cb?access_token=super-secret-token&state=1",
    ])
    def test_a_credential_is_removed(self, text):
        assert "super-secret-token" not in scrub(text), f"the credential survived: {text}"

    def test_the_value_is_removed_with_its_label(self):
        """`token: value` must not become `token: [REDACTED]` - the label names the field."""
        assert scrub("token: super-secret-token") == "[REDACTED]"

    def test_a_credential_in_the_middle_of_a_message(self):
        text = "The server refused the request: api_key=super-secret-token was rejected."
        assert "super-secret-token" not in scrub(text)
        assert "refused" in scrub(text), "the rest of the message must survive"


class TestOrdinaryTextSurvives:
    @pytest.mark.parametrize("text", [
        "the bearer token was rejected",
        "the model server returned HTTP 401",
        "the model server at http://127.0.0.1:8088/v1 could not be reached",
    ])
    def test_prose_is_left_alone(self, text):
        assert scrub(text) == text, f"ordinary text was destroyed: {text}"

    def test_a_message_with_nothing_to_hide_is_unchanged(self):
        text = "The model server at http://127.0.0.1:8088/v1 could not be reached."
        assert scrub(text) == text

    def test_a_field_label_with_a_value_is_redacted_anyway(self):
        """A deliberate trade-off, and it is the safe way round.

        The scrubber only ever sees failure causes and log lines, never prose, so it cannot
        tell `token: abc` from `token: 30-day expiry`. It redacts the shape rather than
        guessing at the value: a scrubber that decides "this one is not a secret" is a
        scrubber that leaks the next time it guesses wrong. Losing a word in an error
        message costs nothing; leaking a credential costs everything.
        """
        assert "30-day" not in scrub("token: 30-day expiry")
        assert "not" not in scrub("secret: not configured")
