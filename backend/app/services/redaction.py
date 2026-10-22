"""Removing anything that looks like a credential from text bound for the outside world.

A credential must never be printed, logged, or published in an API response. The client that
holds the token redacts its own value out of its own error messages, but a message can carry
something else: a header the server echoed back, a token in a URL, a password in a third
party's error text. Those are not known to the client, so they are removed by shape.

The patterns are applied in order, and the value is removed before the label that introduces
it - so `Authorization: Bearer abc123` becomes `[REDACTED]`, not `Bearer [REDACTED]`.
"""
from __future__ import annotations

import re

# Anything that looks like a credential in a message that is about to be published.
SECRET_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+\S+"),
    re.compile(r"(?i)\bauthorization[:=]\s*\S+"),
    re.compile(r"(?i)\b(?:api[_-]?key|token|secret|password)[:=]\s*\S+"),
)


def scrub(text: str) -> str:
    """Strip anything that looks like a credential out of a message bound for the response."""
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text
