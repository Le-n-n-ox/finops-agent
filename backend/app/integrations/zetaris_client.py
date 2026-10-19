"""
Zetaris access (Developer 1). Based on the public docs at kbase.zetaris.com:
  * REST login:  GET {ZETARIS_BASE_URL}/api/v1.0/auth/login
                 headers X-Request-ID (uuid), X-Org-ID; HTTP Basic auth -> {"idToken", "refreshToken"}
  * Other calls: Bearer <API key> + the same headers.
  * SQL query endpoints (start / page / close) are documented in the Redoc at
    https://api.saas.enterprise.zetaris.com/redoc/index.html  -> NOT guessed here; fill in from Redoc.
  * Enterprise JDBC: jdbc:zetaris:lightning@<host>:10000 (driver jar from the Zetaris KB).
Nothing here runs unless ZETARIS_* env vars are set; the app falls back to local files.
"""
from __future__ import annotations

import os
import uuid

import httpx


class ZetarisNotConfigured(RuntimeError):
    pass


class ZetarisClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("ZETARIS_BASE_URL", "").rstrip("/")
        self.org_id = os.getenv("ZETARIS_ORG_ID", "")
        self.username = os.getenv("ZETARIS_USERNAME", "")
        self.password = os.getenv("ZETARIS_PASSWORD", "")
        self.api_key = os.getenv("ZETARIS_API_KEY", "")
        if not (self.base_url and self.org_id and self.username and self.password):
            raise ZetarisNotConfigured("Set ZETARIS_* variables in .env (see .env.example)")

    def _headers(self) -> dict[str, str]:
        return {"X-Request-ID": str(uuid.uuid4()), "X-Org-ID": self.org_id}

    def login(self) -> dict:
        """Returns {"idToken": ..., "refreshToken": ...}. Run scripts/check_zetaris.py to test."""
        r = httpx.get(
            f"{self.base_url}/api/v1.0/auth/login",
            headers=self._headers(),
            auth=(self.username, self.password),
            timeout=20,
        )
        r.raise_for_status()
        return r.json()

    def query(self, sql: str) -> list[dict]:
        """TODO: implement from the Redoc 'SQL Query' endpoints (start -> page -> close)."""
        raise NotImplementedError("Fill in from Zetaris Redoc; do not invent endpoints")
