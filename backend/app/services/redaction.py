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
#
# The credential name may be prefixed - `access_token`, `client_secret`, `db_password` - and a
# prefix ends in a word character, so the name cannot be anchored with a word boundary or the
# prefix is missed and the value survives. The name is therefore matched as "a run of word
# characters ending in token/secret/password", which lets the prefix through.
#
# A `name: value` shape is redacted whatever the value looks like. This scrubs failure causes
# and log lines, not prose, and a scrubber that guesses "this value is not secret" is a
# scrubber that leaks the next time it guesses wrong.
SECRET_PATTERNS = (
    # `Bearer <value>`, but not the ordinary phrase "bearer token".
    re.compile(r"(?i)\bbearer\s+(?!token\s|secret\s|password\s|credential\s)\S+"),
    re.compile(r"(?i)\bauthorization[:=]\s*\S+"),
    re.compile(r"(?i)\b[a-z0-9_-]*(?:api[_-]?key|token|secret|password|credential)[:=]\s*\S+"),
)


def scrub(text: str) -> str:
    """Strip anything that looks like a credential out of a message bound for the response."""
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text
